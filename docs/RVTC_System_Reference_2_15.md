# RV Total Control (RVTC) — System Reference
**Version:** 2.15 — 2026-10-10 — Section 9: json_v2 required-field gotcha (wind fields
dropping whole weather packets) and its fix; Telegraf's InfluxDB token now supplied from a
gitignored `.env`; dead WeeWX `[InfluxDB2]` stanza removed; OI-48 (IPsec hash) closed;
trailer↔home IPsec PSK rotated.
**Owner:** Steve Bradshaw (ve7cbh) — Nanaimo, BC
**GitHub:** https://github.com/ve7cbh/RV-total-control
**Document purpose:** how the system is built, right now. Not a session log — historical
debugging detail lives in the archived `RVTC_Project_Reference_*` / `RVTC_Session*` files. This
doc gets rewritten in place as the system changes; it should always describe current reality.

---

## Table of Contents
1. [Architecture Principle](#1-architecture-principle)
2. [Hardware Platform](#2-hardware-platform)
3. [RS-485 / Modbus Gateway Topology](#3-rs-485--modbus-gateway-topology)
4. [Docker Stack](#4-docker-stack)
5. [Network Map — nginx / Pi-hole](#5-network-map--nginx--pi-hole)
6. [Router / WAN Topology (MikroTik)](#6-router--wan-topology-mikrotik)
7. [Data Flow by Sensor Category](#7-data-flow-by-sensor-category)
8. [Home Assistant's Role](#8-home-assistants-role)
9. [Known Quirks & Standing Gotchas](#9-known-quirks--standing-gotchas)
10. [Operator Working Notes](#10-operator-working-notes)
11. [Open Items](#11-open-items)
12. [HVAC Control System](#12-hvac-control-system)
13. [Backup Strategy](#13-backup-strategy)

---

## 1  Architecture Principle

Every sensor in RVTC follows the same four-stage path:

```
Sensor  ⇄  Adaptor  ⇄  Broker (Mosquitto)  ⇄  Database (InfluxDB)  ⇄  Subscriber
```

- **Sensor** — the physical device (Modbus meter, weather head, GPS, IMU).
- **Adaptor** — a thin piece of code that does all necessary mangling to get raw sensor data into
  the right shape: unit conversion, decoding, derived fields. This is the only layer allowed to
  know the sensor's native format. WeeWX counts as an adaptor here, not an exception to the rule
  — it just happens to be a more sophisticated one than a Python polling script.
- **Broker** — Mosquitto. The single live data bus. Every adaptor publishes here; nothing writes
  to the database directly, and nothing bypasses the broker to hand data to a consumer privately.
- **Database** — InfluxDB, bucket `rvtc`. The single source of truth for history. One uniform
  ingestion mechanism (Telegraf `mqtt_consumer`) writes everything, regardless of source. No
  sensor gets a bespoke writer.
- **Subscriber** — Grafana (history), Home Assistant (live automation/display), any future
  consumer. Subscribers read; they don't get a private pipe from any sensor.

**Consequence of this rule:** if a sensor's data needs correction (units, derived values, rain
totalizing), that correction happens once, in the adaptor, before the broker — never downstream,
never duplicated in more than one place. When this rule was violated (WeeWX writing directly to
InfluxDB via `influxdb2.py`, bypassing Telegraf), it produced silent unit-conversion bugs that
took real effort to find. See Section 9 for what that looked like and how it was fixed.

---

## 2  Hardware Platform

| Item | Specification |
|---|---|
| Host | Beelink J45 mini-PC |
| CPU | Intel Pentium J4205 (4-core) |
| RAM | 8 GB |
| Root drive | `/dev/sda` — 256 GB — mounted `/` |
| Data drive | `/dev/sdb` — 640 GB — mounted `/data` |
| OS | Linux Mint LMDE (Debian trixie base) |
| Hostname | `ve7cbh-control` |
| IP | `192.168.88.3` (ethernet, WiFi disabled) |

Docker volumes for every service live under `/data/docker/volumes/<service>/`. Configs that
Docker Compose bind-mounts from the git repo live under `/home/ve7cbh/RV-total-control/config/`.
These are two different locations — check `docker inspect <container> --format '{{json .Mounts}}'`
before assuming where a running container's config actually comes from. This has caused real
confusion more than once (editing a file that looked right but wasn't the one mounted in).

**The authoritative Docker Compose file is `/home/ve7cbh/RV-total-control/docker-compose.yml`.**
Confirm this against any container in question with:
```bash
docker inspect <container> --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'
```
Other `docker-compose.yml`-looking files may exist elsewhere on disk from earlier iterations of
the build — they are not authoritative unless this check says so.

---

## 3  RS-485 / Modbus Gateway Topology

The MikroTik router reserves a static IP block for RS-485-to-Ethernet gateway hardware
(Waveshare units), one reservation per physical bus, labeled `485-1` through `485-8`. Every
Modbus device in RVTC sits behind one of these — polled by its own Python bridge script, never
by Home Assistant directly (see Section 8).

| Bus | Gateway IP | Device | Bridge script | MQTT topic base |
|---|---|---|---|---|
| `485-1` | `192.168.88.5:4001` | EPEVER MPPT60 (solar controller) — shares this line with the MT50 remote display via an EPEVER RS485-1M2S passive multi-drop tap (not an arbitrator — see note below) | `epever_mqtt.py` | `rvtc/sensors/solar/#` |
| `485-2` | `192.168.88.6:4001` | SAMLUX EVO-2212 (inverter/charger) | `samlux_mqtt.py` | `rvtc/sensors/inverter/#` |
| `485-3` | `192.168.88.7:4001` | KWS-303L grid and Gen meters. G | `kws_mqtt.py` | `rvtc/sensors/grid/#`, `rvtc/sensors/generator/#` |
| `485-4` | `192.168.88.8:4001` | WitMotion WTGAHRS3-485 GPS-IMU (HW-27) | — | `rvtc/sensors/imu/# |
| `485-5` | `192.168.88.9:4001` | Water sensors — pressure, filter ΔP, turbidity | — | Pending Phase 5 |
| `485-6` | `192.168.88.10:4001` | WN90LP weather station — permanent home | `WN90_mqtt.py` | `rvtc/sensors/weather/#` |
| `485-7` | `192.168.88.11:4001` | 300A battery current shunt (HW-24) | `battery_current_mqtt.py` | `rvtc/sensors/battery_current/#` (flat, human/HA use) + `.../json` (aggregate, Telegraf) |
| `485-8` | `192.168.88.12:4001` | Waveshare 8-ch relay board (load shed actuation) | `relay.py` (called via HA `shell_command`, not a polling daemon) | — |

**EPEVER's RS485-1M2S module is a passive electrical tap, not a bus arbitrator** — no collision
detection or queuing. Two masters (MT50 + the Python bridge) can share it because EPEVER's own
documentation lists this as a normal supported configuration, not a workaround. Note the naming
trap in EPEVER's manual: it calls the controller-facing ports "master" and the monitoring-facing
ports "slave" — that describes physical position, not Modbus protocol roles. In actual Modbus
terms the EPEVER controller is the slave (it responds to polls); MT50 and the bridge script are
both masters. This module has no spare capacity — it's a fixed 2-master/2-slave-port unit,
already fully used.

**Relay / coil mapping (Waveshare 8-ch board, `485-8`):**

| Relay | Coil (0-based) | Load | Logic |
|---|---|---|---|
| `relay_1_on` / `relay_1_off` | Coil 0 | Water heater | **Inverted** — value 1 = shed/off, value 0 = restore/on |
| `relay_2_on` / `relay_2_off` | Coil 1 | Microwave | Same inverted logic |

This inversion is a Waveshare NC-wiring quirk, not a bridge-script bug — worth remembering before
"fixing" what looks like backwards relay state.

**HF5142B 4-channel serial gateway — installed, in service.** Physically located next to the
workstation, not in the RV/RVTC enclosure — brought in partly because the 8-port Waveshare array
was running out of room, but its four physical DB9 (RS-232) connectors are also general-purpose:
amateur radio TNCs and radio programming are expected uses alongside (or instead of) any RVTC
sensor. **Treat this as shared network infrastructure, not dedicated RVTC hardware** — a port
being free doesn't necessarily mean it's available for RVTC use; check what's physically plugged
in before assuming. Reserved as `serial-1` through `serial-4` (`192.168.88.13`–`.16`). Unlike the
Waveshare units, this gateway is **not isolated** — a ground loop or voltage fault on a connected
device's serial line could affect the gateway (or whatever it's networked to) directly, worth
factoring in for anything that does end up being RVTC-related. Broader protocol support than the
Waveshare array too (RS-232/RS-422 in addition to RS-485).

| Port | Gateway IP | Use |
|---|---|---|
| `serial-1` | `192.168.88.13:4001` | **Assigned 2026-07-30** — `gps_nmea_bridge.py` (`gps_nmea_bridge.service`), MQTT → NMEA ($GPRMC/$GPGGA) → APRS radio/tracker. One persistent TCP connection held open (raw serial pass-through, unlike the Modbus fresh-connection-per-poll pattern above) with reconnect-on-failure. Baud/parity set on the HF5142B's own web UI (currently 9600 8N1 — confirm this matches the APRS radio's NMEA input before final hookup, commonly 4800 for TNC-style input). Loopback-plug bench test not yet done — pending Steve having the DB9 connector shells on hand. |
| `serial-2` | `192.168.88.14:4001` | **Assigned 2026-09** — HVAC control system relay board (RS485/Modbus), see Section 12. Not yet wired. Per the Protocol-mode gotcha in Section 9 (found while commissioning `serial-4`), confirm this port's Protocol setting is `None`, not `Modbus`, before wiring — the same check already flagged as outstanding for this port. |
| `serial-3` | `192.168.88.15:4001` | *(unassigned)* |
| `serial-4` | `192.168.88.16:4001` | **Assigned 2026-07-31** — Ebyte EID041-G01S temp/humidity sensor (HW-32), equipment enclosure (where the J45 lives). 20cm cable, factory-default Modbus address 1. `eid041_mqtt.py` (`eid041_mqtt.service`). See Section 9 for the Protocol-mode gotcha found while commissioning this one. |

---

## 4  Docker Stack

| Container | Image | Port(s) | Config source |
|---|---|---|---|
| `mosquitto` | eclipse-mosquitto | `1883` | broker — no service config needed |
| `influxdb` | influxdb:2 | `8086` | database — bucket `rvtc`, org `rvtc` |
| `telegraf` | telegraf:latest | *(none exposed — outbound only)* | `config/telegraf/telegraf_*.conf`, individually bind-mounted per file into `/etc/telegraf/telegraf.d/` — see Section 7 |
| `grafana` | grafana/grafana | `3000` | — |
| `weewx` | felddy/weewx | *(none exposed — served via nginx)* | `/data/docker/volumes/weewx/weewx.conf` |
| `homeassistant` | ghcr.io/home-assistant/home-assistant:stable | `8123` | `/data/docker/volumes/homeassistant/configuration.yaml` |
| `nginx` | nginx:alpine | `80` | `/data/docker/volumes/nginx/nginx.conf` — full replacement of the stock file, not `conf.d/` |
| `pihole` | pihole/pihole | `8880` (admin UI), `53` (DNS) | Local DNS records under Pi-hole's own admin UI |

**Not currently running:** `rtl433` / `rtl433b` (removed — weather source is now the WN90LP, not
the Acurite 5n1 / rtl_433 SDR path).

**Telegraf's config directory pattern:** each source gets its own file in `config/telegraf/`
(`telegraf_solar.conf`, `telegraf_grid.conf`, `telegraf_generator.conf`, `telegraf_weather.conf`,
`telegraf_snmp.conf`, `telegraf_battery.conf`), individually bind-mounted in `docker-compose.yml` — there is no
directory-level mount, so a new config file requires both creating the file **and** adding a
mount line in the compose file, then `docker compose up -d telegraf` (a plain `docker restart`
will not pick up a new mount).

---

## 5  Network Map — nginx / Pi-hole

nginx does **hostname-based reverse proxying** on port 80 — this is the only port that needs to
be reachable to access every web UI in the stack. Confirm the live config with:
```bash
docker exec nginx cat /etc/nginx/nginx.conf
```

| Hostname (`.lan`) | Routes to |
|---|---|
| `rvtc.lan` | Static site — `/data/docker/volumes/nginx/rvtc/index.html` (`rvtc_index.html`), custom unified dashboard — see below for its two-track data architecture |
| `weewx.lan` | Static site — `/usr/share/nginx/html/belchertown` (WeeWX's Belchertown skin output) |
| `grafana.lan` | `proxy_pass` → `grafana:3000` |
| `influxdb.lan` | `proxy_pass` → `influxdb:8086` |
| `homeassistant.lan` | `proxy_pass` → `192.168.88.3:8123` |
| `esphome.lan` | `proxy_pass` → `esphome:6052` |
| `pihole.lan` | `proxy_pass` → `pihole:80` |

Every hostname above (plus `.local` duplicates for some) resolves to bare `192.168.88.3` via
Pi-hole's **Local DNS → DNS Records**. DNS records cannot carry a port — the hostname-based
routing above is what makes port-free browsing work; without it, every request lands on
whichever `server` block nginx matches first, regardless of intended destination.

**`rvtc.lan` has two separate data paths, not one — worth understanding before debugging it.**
The Solar/Battery tab (the original build) polls InfluxDB over plain HTTP (`queryInflux()` in
`rvtc_index.html`) — no live connection to lose, just periodic query/response. Everything added
later — the Telemetry/"ALL SYSTEMS" tab (Grid, Generator, Attitude/IMU, GPS, Weather, Enclosure,
tank levels, Master Caution) — is genuinely live MQTT data via the `mqtt.js` client library
connecting directly to Mosquitto's **websocket** listener at `ws://192.168.88.3:9001`, not a
database query. The page's `connecting…`/status pill reflects *only* this second path — it says
nothing about whether the first (Solar/Battery, InfluxDB-backed) is working, and a stuck
`connecting…` does not mean the sensors themselves are down, only that this specific websocket
never completed its handshake. See Section 9 for the 2026-08-17 incident where this was broken
for an unknown period because the port was never actually published from the Mosquitto
container, independent of Mosquitto's own config being correct.

**Remote access (club/campground WiFi, or any external network):**

| External URL | Router NAT rule | Destination |
|---|---|---|
| `http://wifi.solsante.com:8801/` | MikroTik `dst-nat`, chain `dstnat`, in-interface `rogers-wan`, dst-port `8801` → `192.168.88.3` (same port, no port translation) | nginx `weewx.lan` server block — `wifi.solsante.com` is included as a second `server_name` on that block specifically so the bare `Host:` header (with no `.lan` suffix) still matches |

**Important:** Pi-hole only answers DNS for devices on the home LAN. It has no effect on how
external traffic reaches the router. External hostnames must be added explicitly as additional
`server_name` entries on the relevant nginx block (as done for `wifi.solsante.com` above) — they
will not be picked up automatically just because Pi-hole knows about a similarly-named `.lan`
record.

**Security note, not yet acted on:** InfluxDB (holds the API token), Grafana, and Mosquitto have
not had an authentication/hardening review for exposure beyond the LAN. The only currently
internet-reachable path is the single WeeWX forward above. That fork has since been resolved —
see the trailer↔home IPsec VPN in Section 6 — so internal services (HA, Grafana, InfluxDB) are
reached over the tunnel, not exposed by port-forward. Only directly internet-facing services
(WeeWX, both locations — see Section 11) need their own public hostname/cert.

**`malacat.ca` — domain active, both subdomains live as of 2026-08-11:**

| Hostname | Type | Resolves to | Purpose |
|---|---|---|---|
| `malacat.ca` (apex) | A record, static | `216.232.193.152` (matches home IP at time of writing) | Not DDNS-backed — no client updates this automatically. **Checked 2026-08-12, deferred rather than closed** — not pursuing an ALIAS-capable nameserver migration right now. DNS is currently hosted on hosting.com's own panel (`ns1–4.stableserver.net`), which has no ALIAS/ANAME record type (confirmed from the Add Record dropdown: A/CNAME/NS/MX/TXT/AAAA/CAA/SRV only). Migrating nameservers to an ALIAS-capable provider (Cloudflare, DNSimple, etc.) is the actual fix if this becomes worth doing later; for now nothing operationally depends on the bare apex — only `home.` and `rv.` (both already self-updating CNAMEs) matter. If the home IP ever changes, this record needs a manual update — check it first if `malacat.ca` (no subdomain) ever stops resolving. |
| `home.malacat.ca` | CNAME → `home-rvtc.ddns.net` | tracks home WAN IP (No-IP Enhanced, self-updating) | Trailer↔home VPN endpoint (Section 6). No manual upkeep needed. |
| `rv.malacat.ca` | CNAME → MikroTik Cloud DDNS (`*.sn.mynetname.net`) | tracks RV's current WAN IP (self-updating, built into the CRS109) | Intended as the permanent replacement for the ad-hoc `wifi.solsante.com` forward above — see Section 11 for cert work. |

Full Plus Managed DNS / nameserver delegation for `malacat.ca` (so it holds real records instead
of relying on the registrar's basic DNS + CNAMEs to other providers' DDNS names) is still a
future task, not started — not blocking, since HTTP-01 cert issuance works fine against a CNAME.

---

## 6  Router / WAN Topology (MikroTik)

**Router:** MikroTik CRS109, `192.168.88.1`. RV subnet `192.168.88.0/24` on the `bridge`
interface, DHCP pool `192.168.88.100`–`192.168.88.254` (kept high to leave room for the static
`485-1`–`485-8` gateway reservations and other fixed IPs below that range). Wireless AP
`VE7CBH_Mikrotik`, 2.4GHz b/g/n. RouterOS is on the v7.x line (upgraded from 6.49.20 — confirmed
no config regressions from that jump).

**Dual-WAN, two modes, toggled manually depending on location:**

| Mode | When | Rogers NAT masquerade |
|---|---|---|
| **HOME** | Connected to home/club network | Disabled — RV subnet reaches the home LAN directly (not NAT'd), via a static route on the home router pointing `192.168.88.0/24` at the Rogers WAN's DHCP-assigned IP |
| **OFF-GRID / AWAY** | Any away-from-home connection through the `rogers-wan` port — a site's own wired internet, or Starlink, whichever's available | Enabled |

Toggle from the MikroTik terminal:
```
Off-grid : /ip firewall nat set [find comment=Rogers] disabled=no
Home     : /ip firewall nat set [find comment=Rogers] disabled=yes
```
A genuine double-NAT condition (Rogers masquerade left on while connected to the home network)
was found and fixed once — worth checking this setting first if home-network connectivity looks
wrong. VOIP phones were confirmed still functional with the double-NAT disabled, so there's no
reason to leave it enabled at home "just in case."

**Two bridges, kept deliberately separate:**
- `bridge` — the trusted LAN bridge (ether3–ether7, sfp1, wlan1) — the only one in the `LAN`
  interface list, and therefore the only one that inherits the LAN-trust firewall posture.
- `passthrough` — holds only `ether8`. Deliberately excluded from the LAN bridge and interface
  list so anything ever plugged into it gets a raw, un-firewalled, un-NAT'd path rather than the
  RV's normal trusted posture. Currently unused — reserved capacity for a device that might need
  to reach a WAN directly, bypassing routing/firewall/NAT entirely. If something is ever
  connected here, don't assume it has the same protections as everything on `bridge`.

**External access — the actual live path, confirmed 2026-07-20:** the MikroTik `dst-nat` rule
forwards `rogers-wan:8801` straight through to `192.168.88.3:8801` (same port, no translation),
landing on nginx, which matches it via `wifi.solsante.com` added as a second `server_name` on the
`weewx.lan` block — see Section 5. **Older documentation describes a different path** (club
router forwarding `:8080` → MikroTik `rogers-wan:80` → dst-nat → `192.168.88.3:80`) — that
description predates this week's fix and should be treated as superseded, not as a second active
path. If external access ever breaks again, check the live MikroTik NAT rule directly
(`/ip firewall nat print`) rather than trusting either written description.

**Trailer↔home IPsec VPN — built and tested, 2026-08-11.** MikroTik (trailer) ↔ TP-Link ER605 V2
(home), IKEv2/AES-256/DH14. Home is Responder (`0.0.0.0` remote gateway, since the trailer's
source IP varies between Club and Starlink WANs); trailer is Initiator. Home side is reached at
`home-rvtc.ddns.net` (No-IP Enhanced), aliased as `home.malacat.ca` (CNAME — see Section 5).
Confirmed working with a real `ping 192.168.0.1` (23–39ms) and a live Home Assistant dashboard
load from the trailer's LAN, through the tunnel — not just SA-established.

**Crypto confirmed matching (OI-48 closed, 2026-10-10):** the ER605's Phase-1 proposal is
`SHA-256 - AES256 - DH14` (its only proposal, so no weaker fallback can be negotiated), and the
MikroTik's installed SAs (Phase 2 / ESP, both directions) show `sha256` / `aes-cbc` 256,
`mature`. The earlier worry that home had landed on SHA-512 no longer applies. To re-check:
ER605 VPN → IPsec → IPsec Policy → edit → Advanced; MikroTik `/ip ipsec installed-sa print`.

**PSK rotated 2026-10-10.** The original key had been pasted into a chat session, so it was
replaced. The current key is held only in `~/rvtc-files/private/` on the control host (and the
owner's password manager) — never in this repo. Procedure that worked, from the trailer: change
the far end (ER605) first while the tunnel is still up, then the MikroTik identity secret;
applying the MikroTik change tears the tunnel down itself and it renegotiated on the new key in
about a minute. If both ends are changed without a drop, force it with
`/ip ipsec active-peers kill-connections` — existing SAs survive a PSK change, so a tunnel that
stays up proves nothing until it has renegotiated.

**Confirmed working over Starlink WAN, 2026-08-18** (previously only tested on Club WiFi — see
OI-49). Real traffic (ping + interactive SSH into the home Pi at `192.168.0.3`) passed
end-to-end through the tunnel over Starlink, not just SA-established. The theoretical CGNAT
concern (trailer's Starlink address showed as `100.67.242.114`, confirming the CGNAT block, as
expected) never actually caused a problem — Phase 1/2 negotiated fine and the peer stayed
`established`. **The real fault was local, not Starlink's:** the Starlink masquerade NAT rules
(`/ip firewall nat`, `chain=srcnat`, `out-interface=starlink-wan`) were missing the
`ipsec-policy=out,none` exclusion that the older Rogers-WAN masquerade rules already carried.
Without it, tunnel-bound traffic was getting NAT'd to the Starlink public IP and routed nowhere
*before* ever reaching the IPsec policy match — SAs stayed healthy (`established`/`mature`)
throughout while user traffic silently vanished, which is why this looked like a routing/CGNAT
problem rather than a NAT-rule scoping bug. Fixed by adding `ipsec-policy=out,none` to both
active Starlink masquerade rules. Two secondary issues found and fixed along the way, neither of
which was the actual root cause of this outage:
- `rvtc-profile`'s DPD was tuned too aggressively (`dpd-interval=10s`,
  `dpd-maximum-failures=5` — a 50s dead-peer threshold) for a satellite link's normal latency
  jitter, versus the `default` profile's `2m`/5 (10min). Loosened to `dpd-interval=30s`,
  `dpd-maximum-failures=6` (~3min).
- No dedicated `ipsec` logging topic existed — IPsec events were only caught incidentally by the
  generic `info`/`warning`/`error` catch-alls sharing RouterOS's small default memory buffer,
  which had already scrolled past the relevant events by the time this was investigated. Added a
  dedicated 1000-line buffer: `/system logging action add name=ipsecbuffer target=memory
  memory-lines=1000` + `/system logging add topics=ipsec,!raw action=ipsecbuffer`.

If the tunnel ever misbehaves again, `/log print where topics~"ipsec"` now actually has something
in it — check that before re-diagnosing from scratch.

**Club bridge (Pi at Solsante) — descoped, 2026-08-12: no longer a weather source, now a
network-admin access tunnel.** The original plan (a Pi running `rtl_433` + WireGuard, GNSS
geofencing to swap the RV's authoritative weather reading between the RV's own WN90LP and the
club station depending on physical proximity) is dropped — home is getting its own permanent
WeeWX station this fall (see Section 11), which covers the "RV is away" gap the club-swap logic
existed for, without needing to know where the RV physically is. `rtl_433` and the geofencing
swap are no longer planned work.

The Pi itself stays, repurposed: Steve manages the club's UniFi UDM Pro network day-to-day
through its own app, but the Pi/VPN leg is still needed for getting *inside* the club LAN
directly — camera web UIs and anything else behind the UDM Pro that isn't otherwise reachable.
Not yet built. The UDM Pro's native Site-to-Site VPN only offers OpenVPN/IPsec (no WireGuard,
despite what UniFi's docs suggested before checking the actual device), so this leg would use
IPsec to match the trailer↔home leg above — unless the Pi has spare capacity to run WireGuard
directly to an endpoint (laptop/phone) itself, bypassing the UDM Pro's site-to-site limitation
entirely; worth checking before committing to IPsec here too.

---

## 7  Data Flow by Sensor Category

All four current sensor categories follow the identical pattern from Section 1, differing only in
which adaptor sits closest to the hardware:

| Source | Adaptor | Broker topic | Telegraf config | InfluxDB measurement |
|---|---|---|---|---|
| EPEVER MPPT60 (solar) | `epever_mqtt.py` (Modbus poll → MQTT) | `rvtc/sensors/solar/#` | `telegraf_solar.conf` | `solar` |
| SAMLUX EVO-2212 (inverter) | `samlux_mqtt.py` | `rvtc/sensors/inverter/#` | `telegraf_solar.conf` (shared file) | `inverter` |
| KWS-303L (grid/generator) | `kws_mqtt.py` | `rvtc/sensors/grid/#`, `rvtc/sensors/generator/#` | `telegraf_grid.conf` | `grid` |
| WN90LP (weather) | `WN90_mqtt.py` (raw Modbus → MQTT, flat topics) **+** WeeWX (`MQTTSubscribeDriver` in, `weewx-mqtt` out) | raw: `rvtc/sensors/weather/#` · corrected: `rvtc/sensors/weather/corrected/loop` | `telegraf_weather.conf` (subscribes to the **corrected** topic only) | `weewx` |
| JSY-MK-229 (battery current, HW-24, `485-7`) | `battery_current_mqtt.py` — publishes both flat per-field topics (for MQTT Explorer/HA) and one aggregate JSON message per poll on a dedicated subtopic (for Telegraf) | flat: `rvtc/sensors/battery_current/#` · aggregate: `rvtc/sensors/battery_current/json` | `telegraf_battery.conf` (subscribes to the **json** topic only, same two-topic pattern as weather's raw/corrected split) | `battery_current` |

**Weather is the one two-stage adaptor**, and it's worth understanding why: `WN90_mqtt.py` only
does register decoding (raw Modbus values → sane units). It does **not** do sea-level pressure
correction, dewpoint/heatindex derivation, or rain-total-to-rain-rate conversion — that requires
WeeWX's own `StdWXCalculate` and `StdRainRater` services, which need historical state (previous
readings) that a stateless polling script doesn't have. So WeeWX sits in the adaptor role for
weather specifically, ingesting the raw MQTT feed, doing the correction, and republishing the
corrected result back to the broker — Telegraf then treats that corrected topic exactly like any
other sensor's output. WeeWX's own SQLite archive (`weewx.sdb`) and its Belchertown/NOAA/CWOP
reporting are a separate, parallel consumer of the same corrected data — not part of the
InfluxDB path, and not something that needs to change if the InfluxDB side changes.

**Field naming convention for weather in InfluxDB:** WeeWX's `weewx-mqtt` publish extension
appends a unit suffix to every field name in its aggregate JSON message — `outTemp_C`,
`barometer_mbar`, `windSpeed_mps`, `radiation_Wpm2`, `rain_mm` — unlike solar/grid/inverter,
whose field names are bare. Grafana queries against the `weewx` measurement must use the
suffixed names.

**Telegraf runs as a single Docker container — this was not always true, and getting it wrong
caused a real bug.** Telegraf was originally deployed as a native systemd service on the host,
before being containerized. At some point both the native service and the Docker container ended
up running simultaneously, both subscribed to the same MQTT topics, both writing to the same
InfluxDB bucket — producing doubled data points (visible as duplicate needles on Grafana gauges,
distinguishable only by a different `host` tag on otherwise-identical rows). The native
`telegraf.service` has since been stopped and disabled. **If duplicate-looking data ever shows up
again, check `systemctl status telegraf` on the host before assuming the bug is in a config file**
— a second writer is a more likely explanation than bad Telegraf config.

**The IMU's MQTT topic (`rvtc/sensors/imu/#`) is deliberately not persisted to InfluxDB.** Every
other sensor gets picked up by a `telegraf_*.conf`; the IMU does not, on purpose — nobody needs a
queryable history of past pitch/roll/heading, only the live value. If this ever looks like
"missing" data during a future Telegraf review, that's expected, not a bug to fix.

**WN90LP's `windDir` is corrected from trailer-relative to true (compass) direction inside
WeeWX itself, not in `WN90_mqtt.py`.** Added 2026-08-01 (`user/truewind.py`,
`TrueWindService`, hooked into `NEW_LOOP_PACKET` right after `StdWXCalculate` in
`process_services`). Why it's needed: the wind vane's zero mark is relative to however the
sensor is bolted to the trailer, not true north — fine for a fixed installation calibrated once
at setup, but broken every time a towed trailer relocates. Why it's in WeeWX, not the adaptor:
matches this project's own correction-happens-once-in-the-adaptor principle (Section 1) —
WeeWX already plays that role for weather data (`StdWXCalculate`'s barometer/dewpoint/heatindex
derivation is the same pattern), and it gets the corrected field into InfluxDB for free via the
existing `user.mqtt.MQTT` republish path (no `[[[inputs]]]` whitelist configured there, so a new
packet field just flows through unchanged). The service runs its own independent MQTT
subscription to `rvtc/sensors/imu/heading` + `heading_needs_init` (a second, completely separate
MQTT client from WeeWX's own `MQTTSubscribeDriver`, which is the input side, not this). Original
relative reading is preserved as `windDirRelative` for diagnosing bad-heading vs. bad-sensor-data
later. **Fails safe completely, not partially**: if the heading is unavailable, flagged
`needs_init`, or stale (>30s — `imu_mqtt.py` publishes at 2Hz, a real gap that long means it's
down), `windDir`, `windSpeed`, AND `windGust` are ALL set to `None` together for that packet, not
just left uncorrected — a trailer-relative `windDir` passed through unmodified would look like a
perfectly valid true-compass reading to Wunderground/PWSWeather/CWOP/AWEKAS and any other
external consumer, and a silently wrong number is worse than a visible gap.

---

## 8  Home Assistant's Role

HA is a **consumer**, not a data-collection layer. It subscribes to the same MQTT topics
everything else does — it does not poll Modbus devices directly. This was tried early on and
abandoned: `pymodbus` holds a persistent TCP connection which the Waveshare gateway drops on
idle, producing reliable write/read failures. See Section 7 for the workaround pattern used
instead.

**Bounded exception — HA does actuate**, for exactly two things:
- **Tier 3 load shedding** (grid/generator overload response — water heater, microwave)
- **Tier 4** (battery SOC-based shedding, planned)

This is deliberate, not a violation of the consumer-only principle: HA is the only place where
grid current, generator current, battery SOC, A/C state, and furnace state all converge
simultaneously, so it's the only place that can make an informed shed/restore decision without
duplicating state elsewhere. All physical safety protection (Tier 1/2) remains hardware-level, in
the ESP32 thermostat controller, independent of HA — if HA is down, the RV stays safe.

**Relay writes from HA** go through `shell_command` calling small Python scripts
(`relay.py`, `kws_relay.py`) that open a fresh Modbus TCP connection per write and close
immediately — same reasoning as above, avoiding the persistent-connection problem entirely.

---

## 9  Known Quirks & Standing Gotchas

These are the durable, still-true facts worth remembering — not a debugging narrative, just the
conclusions.

**WN90LP barometer resolution is 0.1 hPa.** Grafana/Belchertown barometer graphs show a visible
staircase/jitter texture riding on top of the real smooth trend — this is the sensor's real
resolution floor, not a bug, not noise from the pipeline. Confirmed by checking that every raw
reading lands on a 0.1 boundary.

**Wind direction is genuinely noisy at low wind speed.** A vane doesn't hold a stable heading
without enough airflow to push it — dense, scattered wind-direction readings during calm periods
are real sensor behavior, not something to chase as a fault.

**Belchertown's different report pages can have different smoothing.** `graphs.conf` has a
separate `[[chartN]]` block per timespan/page; only some have `[[[[dataGrouping]]]]` sub-blocks
applied. The "Today" page currently shows raw/unsmoothed data by design (left this way
deliberately — useful for seeing real sensor texture); other timespan pages are smoothed via
`groupPixelWidth`/`approximation` settings. If a page looks noisier than expected, check whether
its `dataGrouping` block is missing rather than assuming a data problem.

**`pymodbus` (3.x) is incompatible with the Waveshare RS-485 gateway for persistent connections.**
The gateway drops idle TCP connections; pymodbus doesn't reconnect cleanly. This ruled out HA's
native Modbus integration entirely — every Modbus device in RVTC is read via a Python bridge
script (Python stdlib socket, fresh connection per poll/write), not via HA or any library that
holds a connection open.

**WeeWX's `[Engine][[Services]]` needs an explicit `process_services` line.** Without it,
`StdConvert` (unit conversion) and `StdWXCalculate` (derived fields: barometer, dewpoint,
heatindex) silently never run — packets stay tagged in whatever raw unit system the driver
reported, with no error, no warning. If a WeeWX field is showing an implausible value or is
simply missing, check this line first.

**MQTTSubscribeDriver's per-field `units` option rejects `watt_per_meter_squared`** even though
it's WeeWX's own correct name for that unit — the driver's internal validation table only
recognizes units it has a *conversion* defined for, and `group_radiation` has only one valid unit
(no conversion needed), so it's absent from the table. Fix: omit the `units =` line entirely for
`radiation` — nothing to convert, so it's not needed anyway.

**`weewx-mqtt`'s default publish mode is `individual`, not `aggregate`.** Without explicitly
requesting aggregate mode, it publishes one MQTT message per observation
(`corrected/outTemp_C`, `corrected/barometer_mbar`, ...) rather than one combined JSON blob. It
actually does **both** by default — the combined blob lives at `corrected/loop`. Point any
JSON-consuming subscriber at the `loop` subtopic specifically, not the bare parent topic.

**Telegraf's JSON parser needs explicit type coercion for quoted numeric strings.** WeeWX's
`weewx-mqtt` JSON payload quotes every value (`"outTemp_C": "18.9"`, not `"outTemp_C": 18.9`).
Plain `data_format = "json"` either mistypes or drops these silently. Fix: use
`data_format = "json_v2"` with explicit `[[inputs.mqtt_consumer.json_v2.field]]` blocks declaring
`type = "float"` for each field that needs to be numeric in InfluxDB.

**json_v2 fields are required by default — one missing key drops the entire packet.** WeeWX
omits a field from `corrected/loop` when its value is `None`: `windDir` goes `None` whenever the
wind is calm (normal WeeWX behaviour), and the TrueWind fail-safe (Section 7) sets `windDir`,
`windSpeed`, and `windGust` all to `None` together. With required fields, Telegraf rejected those
whole messages — outTemp/humidity/barometer/UV/rain for that packet were lost too — logging
`the path "windDir" doesn't exist` every few minutes. Fixed 2026-10-10: the three wind fields in
`telegraf_weather.conf` carry `optional = true`. Any future json_v2 field that can legitimately
be absent needs the same flag.

**Telegraf's InfluxDB token lives in `.env`, not in the `telegraf_*.conf` files.** Since
2026-10-10 every `[[outputs.influxdb_v2]]` block reads `token = "${INFLUX_TOKEN}"`; the value
comes from `~/RV-total-control/.env` (chmod 600, gitignored), passed to the container by
`docker-compose.yml`. It's a write-only token on bucket `rvtc`. To rotate: generate a new
write-only `rvtc` token in the InfluxDB web UI, replace the value in `.env` over SSH (not via the
`X:` share — a Windows editor can add a CR), then
`docker compose up -d --no-deps --pull never --force-recreate telegraf`. WeeWX has no InfluxDB
token at all — its old `[InfluxDB2]` stanza was dead config from the removed direct-writer path
(Section 1) and has been deleted.

**Docker container log files don't lose history on their own.** No daemon-wide or per-container
log rotation limit is configured on this host — `docker logs <container>` (no `--since`) dumps
the entire history since container creation, which can be hundreds of MB and make it *look* like
data is missing when it's really just buried. Use `--since`/`--until` to scope a query rather
than assuming a gap means lost data.

**WitMotion's on-chip time block reports LOCAL time, not UTC, despite the register map's field
names.** `YYMM`/`DDHH`/`MMSS`/`MS` (`0x30`–`0x33`) looked like it should be GPS UTC. It isn't —
the module applies its own `TIMEZONE` register (`0x6B`) offset internally before exposing that
block. Confirmed 2026-07-30: `TIMEZONE` read back as `0x05` (UTC-7), and the on-chip block
matched Nanaimo local time to the minute against an actual clock check, not UTC. `imu_mqtt.py`'s
`gps/utc_time` field now reads `TIMEZONE` every poll and subtracts the offset to recover true
UTC; `gps/chip_local_time` publishes the raw, uncorrected value alongside it as a diagnostic. If
a GPS timestamp field on this device ever looks wrong again, check `TIMEZONE` before assuming the
GPS fix itself is bad.

**HF5142B ports have a "Protocol" setting (web UI) that must be `None`, not `Modbus`, for
RVTC's bridge scripts to work.** Discovered 2026-07-31 commissioning the first EID041 sensor on
`serial-4`: that port's Protocol was set to `Modbus` (default on at least this port), which on
gateways like this typically means the unit does its own Modbus-TCP-to-RTU translation — expecting
a standard Modbus TCP (MBAP) frame over the network and adding/stripping the RTU CRC itself.
Every RVTC bridge script instead sends raw RTU frames straight over the TCP socket (the same
"RTU-over-TCP passthrough" every Waveshare gateway and `serial-1`'s NMEA bridge already rely on)
— those two framings aren't compatible. Fix: set Protocol to `None` on any HF5142B port a RVTC
script talks to. Worth checking this setting on `serial-2`/`serial-3` too before wiring anything
new into them, rather than discovering it the same way again.

**`ExecStart` in a `.service` file must be a real symlink into `config/scripts/`, not a copy.**
Two bridge services (`imu_mqtt.service`, `gps_nmea_bridge.service`) had silently drifted into
independent, out-of-sync copies at `/etc/systemd/system/` instead of symlinks — one caused a
production outage (crash-looping on a stray, never-git-tracked script at the repo root) before
being caught. Every bridge service's unit file now lives in exactly one place,
`config/scripts/`, symlinked from `/etc/systemd/system/` — confirmed 2026-07-30. If a bridge
service ever crash-loops on `No such file or directory` for a path that looks plausible, check
`ls -la /etc/systemd/system/<name>.service` first — if it's a real file instead of a symlink,
that's the bug, not the script.

**SNMP monitoring (MikroTik/printer/NAS) can silently stop for weeks with no error anywhere.**
It went unmounted from `docker-compose.yml` at some point for reasons lost to time — there's no
failure log for a data source Telegraf never tried to load, just a quietly stale measurement.
`config/telegraf/telegraf_snmp.conf` is the correct, complete file (the only one of three
near-identical drafts that includes its own `[[outputs.influxdb_v2]]` block); confirmed properly
mounted and producing fresh `mikrotik`/`brother_printer`/`synology_nas` data as of 2026-07-30. If
a `telegraf_*.conf` exists in the repo but its measurement hasn't shown fresh data recently,
check the actual `docker-compose.yml` mount list first, not just whether the file exists.

**Belchertown's `radar_html`/`radar_html_dark`/`radar_html_kiosk` skin.conf values must stay
single-line — a multi-line value silently breaks the whole site, not just that widget.**
ConfigObj happily accepts a multi-line triple-quoted (`'''...'''`) value, and `skin.conf`
parses cleanly either way — **that is not proof the page works.** Somewhere in Belchertown's
template chain, this value gets interpolated directly into a JavaScript string literal inside
the generated `belchertown.js` (a `jQuery('.radar_image').html('...')` call), and a JS string
literal can't contain a real line break. A multi-line value produces an `Uncaught SyntaxError`
that kills parsing of the *entire* `belchertown.js` file — which silently breaks everything else
that file defines (graph rendering, the homepage clock) along with it, not just the widget
itself. Confirmed and fixed 2026-07-31. If editing these values again, keep the HTML+`<script>`
content on one physical line, no embedded newlines — the widget's own JS is fully
semicolon-terminated, so collapsing it to one line doesn't change behavior. If a Belchertown page
ever looks broken again after a skin.conf edit and the config itself parses fine, check the
browser console (F12) for a `SyntaxError`/`ReferenceError` before assuming a server-side cause.

**Never let a second script poll a Modbus device that already has a continuous poller —
RS-485 is half-duplex and most gateways don't arbitrate between TCP clients.** Found TWICE in
one session (2026-08-01), same root cause both times: a second script opened its own connection
to `485-4` (the WitMotion) while `imu_mqtt.py`'s continuous 2Hz poll was still running.
First time (`imu_gps_heading_autoset.py`'s original design), it failed reliably — CRC mismatches,
short responses, timeouts, every cycle. Second time (`set_imu_heading.py`, a one-off manual
read, not a sustained poller), it had been "working" for hours by pure luck, then failed once
with a bare timeout — a race that usually wins isn't the same as not having a race. Fix in both
cases: derive whatever's needed from `imu_mqtt.py`'s own MQTT topics instead of touching the
device directly. `imu_mqtt.py` is the ONLY thing that talks to this device on an ongoing basis —
any new script needing IMU/GPS data should subscribe to MQTT, not poll Modbus, full stop. The
only Modbus-direct scripts left by design are genuine one-off bench tools
(`zero_imu_pitch_roll.py`, `test_imu_reset.py`, `read_imu_ref_registers.py`,
`set_eid041_address.py`) — each of these explicitly stops `imu_mqtt.service` before writing and
restarts it afterward (guaranteed via `try`/`finally` even on failure), rather than trying to
coexist with the continuous poll.

**The WitMotion's roof-forward mounting axis swap (documented since 2026-07-25) applies to the
XREFROLL/YREFPITCH reference registers too, not just the live Roll/Pitch output.** Confirmed
2026-08-01 zeroing pitch/roll: `imu_mqtt.py` swaps raw register `0x3D` ("Roll") → published
`pitch`, and raw `0x3E` ("Pitch") → published `roll`, because of the physical mounting. The
first zeroing attempt wrote MQTT's (already-swapped) `roll`/`pitch` values straight into
`XREFROLL`/`YREFPITCH` as if they mapped 1:1 — they don't, since those registers act on the
device's raw, unswapped axis labels. Fix: `XREFROLL` (0x79) takes the *pitch* value,
`YREFPITCH` (0x7A) takes the *roll* value — the same swap direction, applied in reverse, as
`imu_mqtt.py`'s own publish logic. Confirmed via direct register read-back before assuming the
math was wrong twice.

**WitMotion's `SAVE` register (0x00) has a third documented-in-name-only value, `0x0001`
("Reset"), distinct from `0x0000` ("Save") and `0x00FF` ("Reboot") — partially understood.**
Sending it (with the required unlock sequence first) measurably moved Roll/Pitch toward zero
(confirmed via before/after register read-back) without breaking Modbus communication —
address/baud/parity all confirmed unchanged afterward at the same values. Best working theory:
it clears `XREFROLL`/`YREFPITCH` back to defaults rather than capturing a fresh
zero-to-current-orientation reference on its own. Not confirmed against the manual (no worked
example exists for this value), and its exact scope beyond angle references is unknown — treat
as a partial finding, not a documented feature, if using it again.

**`imu_heading_state.json` silently existed in two different locations with two different
values before 2026-08-01** — `config/imu_mqtt.py` writes/reads from `config/scripts/`, but
`set_imu_heading.py` was writing to plain `config/`, the same `config/` vs. `config/scripts/`
split that already bit `imu_mqtt.service`'s `ExecStart` once. Fixed by pointing
`set_imu_heading.py` at the same path `imu_mqtt.py` actually reads. If a calibration script's
own printed "success" doesn't match what MQTT subsequently shows, check for exactly this kind
of path divergence before assuming the calibration math is wrong.

**HF5142B data ports can run an unprompted Telnet negotiation handshake on connect, separate
from the "Protocol" web-UI setting documented above.** Confirmed 2026-07-31 on `serial-4`
(`eid041_mqtt.py`): even with Protocol set to `None`, the port sent
`FF FB 01 / FF FB 03 / FF FB 00 / FF FE 01 / FF FD 00` (Telnet `IAC WILL ECHO` and friends)
immediately after the TCP handshake, before any real serial data — and because it offered
`WILL ECHO` and got no reply declining it, it also echoed every subsequent request straight
back before the device's real response arrived. Traced with a raw byte-dump diagnostic
(`eid041_raw_probe.py`) rather than assumed. Fix, now baked into `eid041_mqtt.py`'s
`read_registers()`: drain any unsolicited preamble immediately after connecting, then strip an
echoed copy of the outgoing request from the front of the response before parsing. Worth
checking `serial-2`/`serial-3` for the same behavior before wiring new sensors into them,
independent of whatever their own Protocol setting shows.

**A Waveshare RS-485-to-Ethernet gateway's "Destination IP/DNS" field can silently block real
data even while the TCP port itself accepts connections.** Confirmed 2026-08-15 commissioning
HW-24 on `485-7`: `nc -zv 192.168.88.11 4001` succeeded and `battery_current_mqtt.py`'s socket
connected cleanly, but every Modbus poll timed out with no response at all — device was powered,
RS-485 wiring was later confirmed fine. The gateway's web UI had `Destination IP/DNS` set to
`192.168.1.3`, a stale value from a different subnet entirely (RVTC is `192.168.88.0/24`),
apparently left over from an earlier config template and never updated for this network. Even in
`TCP Server` work mode, this field evidently still gated whether real serial pass-through
happened for a given client, despite not blocking the TCP handshake itself — a connect-level
`nc` test alone isn't proof the gateway is correctly configured. Fix: set `Destination IP/DNS` to
the actual RVTC host, `192.168.88.3`. Worth checking this field on any Waveshare gateway before
assuming a "TCP connects fine but Modbus always times out" symptom is wiring or device-side.

**An untracked (non-Compose-managed) `mosquitto` container caused `docker compose up` to fail
with a name conflict — exactly the failure mode Section 2 warned about, now actually observed.**
Hit 2026-08-15 bringing up `telegraf` after adding the battery Telegraf config: `docker compose
up -d telegraf` failed with `Conflict. The container name "/mosquitto" is already in use`, even
run from the correct repo root with the correct `docker-compose.yml`. `docker inspect mosquitto
--format '{{index .Config.Labels "com.docker.compose.project.config_files"}}'` came back
completely blank — the running `mosquitto` container had no Compose labels at all, meaning it was
started some other way (manual `docker run`, or a leftover from before this was containerized
properly) and Compose had no way to recognize it as already satisfying the `mosquitto` service,
so it tried to create a fresh one and collided on the name. Fix: `docker rm -f mosquitto` (safe,
confirmed no Compose labels to lose), then `docker compose up -d telegraf` again — recreated
`mosquitto` cleanly under Compose management this time (confirmed via the same label check coming
back non-blank afterward). Brief broker outage during the removal — every connected bridge
script's MQTT connection dropped and reconnected automatically, expected and harmless. If a
`docker compose up` conflict like this recurs on any container, run the label check first before
assuming it's a wrong-directory or wrong-file problem (Section 2's existing guidance) — this time
it was neither.

**A Telegraf config file intermittently failed to load with `permission denied` despite identical
ownership, permissions, and ACLs to working files — root cause not confirmed, resolved on retry.**
Hit 2026-08-15 with `telegraf_battery.conf`: `open ... permission denied` on load, repeatedly,
even though `ls -la`/`getfacl`/`lsattr` all showed it identical to working `.conf` files in the
same directory, `docker inspect telegraf`'s mount list showed the correct source path, and
`dmesg`/kernel logs showed no AppArmor or other denial. A `docker compose restart telegraf` after
the file's placeholder InfluxDB token was replaced with the real one loaded clean with no error,
and has been stable since. Best guess is a timing race between the editor finishing the write and
Telegraf's config load, but this isn't confirmed — treat as a partial finding. If a `.conf` file
throws `permission denied` again despite checking out clean on every visible attribute, a plain
retry/restart is worth trying before a deeper investigation.

**`rvtc.lan`'s Telemetry tab websocket depended on three separate things all being true at
once — Mosquitto's own config, Docker's port publish, and the host firewall — and only one of
the three had actually been done.** Discovered 2026-08-17 while away from home base: the
Telemetry tab's status pill was stuck on `connecting…` and every panel on that data path (Grid,
Generator, Attitude/IMU, GPS, Weather, Enclosure, tank levels) showed blank/`–`, while
Solar/Battery (the separate InfluxDB-polling path — see Section 5) displayed fine, which was
initially confusing until the two-path split was understood. Root cause: Mosquitto's own config
(`docker exec mosquitto cat /mosquitto/config/mosquitto.conf`) already had `listener 9001` /
`protocol websockets` correctly set, added deliberately in August per its own comment — but
`docker inspect mosquitto`'s port list showed only `1883/tcp` published, never `9001/tcp`, and
`ufw status` had no `9001` entry either. The broker was listening internally the whole time;
nothing on the host or in Docker's port mapping ever let anything reach it. Not something this
trip broke — likely broken since whenever the Telemetry tab panels were first added, just never
noticed because nobody had reason to load that specific tab in the meantime. Fix: add
`"9001:9001"` to `mosquitto`'s `ports:` list in `docker-compose.yml`, `docker compose up -d
mosquitto` (not a plain restart — new port mapping needs the container recreated, same lesson as
the Telegraf mount below), then `sudo ufw allow 9001/tcp`. **`mosquitto.conf` itself carries a
`# Managed by Ansible — do not edit manually` header** — it was already correct here, so it
didn't need touching, but if it ever does, that change belongs in the Ansible role/template
(`roles/`, per the repo root), not a direct host edit, or the next playbook run will silently
revert it. If `rvtc.lan`'s Telemetry tab is ever blank again, check all three layers
independently (Mosquitto's own config, Docker's published ports, UFW) rather than assuming
fixing one fixes the others — this incident is a case where two of the three were fine and only
the Docker port publish was actually missing.

**WitMotion firmware `15822`/`15823` have a genuine GPS longitude defect — stay on `05821`
until/unless WitMotion confirms a real fix in a later build.** Discovered 2026-08 via
`gps_burst_capture.py` (rapid consecutive raw reads of `LonL`/`LonH`/`LatL`/`LatH`, `0x49`–
`0x4C`) after the dashboard's GPS card showed a longitude ~39km off. Latitude was accurate on
every read, on every firmware version tested — this is isolated entirely to longitude. On
`15822`: `LonH` read a fixed, wrong `0xB6E6` (correct is `0xB678`) on 98% of reads, producing an
out-of-range decoded minutes field (>60'); genuinely correct on the other 2%, confirming the
receiver itself had a good fix throughout and this is a data-exposure bug, not reception.
WitMotion's own optimized build `15823` made it *worse* — 0/100 correct in the same test.
Downgrading to `05821` (WitMotion's suggested fix) resolved it completely: confirmed via a
5000-sample rapid burst capture, 0 invalid reads, `LonH` stable at the correct `0xB678` for the
entire ~400s capture, position accurate to ~4m against a surveyed reference. Full register-level
evidence (raw hex, both firmware versions, burst-capture methodology) is in the WitMotion
support thread if this ever needs revisiting — check `LonH` specifically first if longitude
looks wrong again after any future firmware change on this device.

---

## 10  Operator Working Notes

**Steve (ve7cbh) has dyslexia with transpositional errors** — characters, numbers, and flags get
swapped in typed commands. Practical implications:
- When a command has multiple flags, annotate each one inline the first time it's introduced.
- When results are unexpected, check for transposition before assuming a device or config fault.
- For multi-line file edits, prefer `cat >> file << 'EOF'` heredocs or Python find-and-replace
  scripts (with an explicit "pattern not found — aborting" safety check) over manual paste +
  indent-matching in an editor — this has proven far more reliable than hand-editing YAML
  indentation in particular.

**HA's `!include` mechanism is a recurring source of errors:** the included file must contain
only the *contents* that go inside the assigned key, not the key itself. Before adding to any
`!include`d file, check whether it already starts with the same key name `configuration.yaml`
assigns it — if so, that line needs to come out and everything below de-indented.

**The IMU's pitch/roll "zero" is a software reference point, not a physical alignment — and
that's deliberate.** Decided 2026-08-01: rather than physically shimming the WitMotion's mount
to true geometric level, `zero_imu_pitch_roll.py` lets the *current* physical orientation
(however it's actually mounted) become the reference. This means the mount itself never needs
to be perfect — what matters is picking the right trailer position to zero *from*: wherever the
fridge runs happiest (top priority), doors close properly, and the cooktop reads level by eye.
That's the target to level the trailer's jacks to before running the zero script, not
"as level as a bubble level says the ground is."

**Because the trailer chassis flexes under load (same physics as a ship's hull flexing —
"hogging and sagging"), the zero reference can drift with LOADING, not just LOCATION.**
Uneven tank levels or cargo distribution can twist the frame just enough that the fridge/doors/
cooktop fall slightly out of step with what the IMU reports as zero, even parked in the exact
same spot as last time. Worth re-running `zero_imu_pitch_roll.py` after a major load change
(tanks going from empty to full, a big cargo shift), not only after the GPS-detected-move logic
in `auto_recalibrate_imu_heading.py`/`update_weewx_station_location.py` triggers — those only
know about position, not load.

---

## 11  Open Items

Reconciled against the archived backlog (`RVTC_Consolidated_Reference_Version_1_5.md`, Part 3) —
hardware and software work not yet complete as of this rewrite. Check the archived session logs
for full history/context on any item below.

**Hardware:**
- HW-19 — 12V→5V DC-DC converter to power the relay board
- HW-20 — ESP32-S3 thermostat: fish DMX cable, firmware
- HW-22 — Install battery heater, wire coil 5 and 5 (?)  Two batteries, one heater each.
- HW-24 — **300A** battery current shunt (RS-485) — corrected from earlier "400A" note, confirmed
  2026-07-31. **Installed and commissioned 2026-08-15.** Full pipeline live: shunt → `485-7`
  (`192.168.88.11:4001`) → `battery_current_mqtt.py` → `rvtc/sensors/battery_current/#` (flat) +
  `.../json` (aggregate) → `telegraf_battery.conf` → InfluxDB `battery_current` measurement,
  confirmed with real moving data in the Data Explorer. **Correction, 2026-08-19:** the earlier
  note here about the charge/discharge sign being "flipped in software... rather than rewiring
  I+/I- at the shunt" was inaccurate — `battery_current_mqtt.py`'s `decode()` has never applied
  any software sign correction; it passes the device's own `active_power_direction_raw` bit
  straight through (`direction`/`current_signed`/`power_signed` all derive directly from that raw
  bit, no inversion). The shunt's I+/I- wiring was **physically corrected** at the shunt on
  2026-08-19 instead, matching the project's stated preference for fixing wiring faults in
  wiring, not papering over them in software. Confirmed correct under a controlled test: PV
  disconnected → `direction=discharging`, `current_signed=-8.38`; PV reconnected →
  `direction=charging`, `current_signed=+13.71`. See Section 9 for two gotchas hit during
  commissioning (Waveshare gateway Destination IP filtering; an untracked `mosquitto` container
  blocking `docker compose up`).
- HW-31 — Battery temperature sensors — in hand, not yet installed/commissioned. Queued for
  installation alongside HW-24 before the tank-level sensors (HW-29), which are deliberately
  deferred to fall 2026.
- HW-29 — Holding tank metering system — modules in hand, not yet installed/wired. **Deliberately
  deferred to fall 2026**, confirmed 2026-07-31 — not blocked on anything, just sequenced after
  HW-24/HW-31 and the equipment-securing pass (OI-44). **Now also the blocker for the HVAC
  display's tank-level panel (Section 12e)** — deferral status unchanged, this is a note of a
  new downstream dependency, not a reason to reprioritize.
- HW-30 — Storage compartment temperature sensors — in hand, not yet installed/wired
- HW-32 — Ebyte EID041-G01S temp/humidity sensor, equipment enclosure (J45) — **installed and
  commissioned 2026-07-31**, `serial-4` on the HF5142B, factory-default Modbus address 1 (single
  device on its own line, no collision risk). `eid041_mqtt.py`. NOT yet persisted to InfluxDB —
  deliberately deferred (needs a new `telegraf_enclosure.conf` + a docker-compose bind-mount +
  `docker compose up -d telegraf`, not just a restart — see Section 4's Telegraf gotcha).
- HW-33 — Three more Ebyte EID041-G01S units planned: equipment bay (near the Waveshare
  array/batteries, but outside the battery enclosure itself), cargo compartment, holding tank
  compartment. Wiring plan confirmed 2026-07-31: **a mix of dedicated lines and a shared bus**,
  exact pairing TBD on-site (cable-run practicality, not yet decided). **Conflict resolved
  2026-09: HVAC keeps `serial-2`.** Rationale, not just precedence — the HVAC relay board's own
  status feed (Section 12c) already publishes a sensed-temperature reading, which satisfies the
  cabin-temperature requirement RVTC needs regardless; a separate dedicated cabin sensor was
  never going to be needed once that's in place. HW-33's three units are for equipment bay,
  cargo, and holding tank — none of them cabin — so this doesn't reduce that count, but it does
  mean only `serial-3` remains free on the HF5142B for them: a shared bus (unique Modbus
  addresses) for all three, or a second gateway, whichever proves more practical on-site.
  Addresses are reprogrammed via `set_eid041_address.py` (Hold Register `0x000A`, function 0x06)
  BEFORE a unit joins a shared line — same bench-first pattern as the KWS meters (HW-09). Do not
  wire two factory-default (address 1) units onto the same line before reprogramming one of them.

**Software / Infrastructure:**
- OI-18 — ESPHome Ansible role
- OI-24 — Load & energy management automation (Tier 1–4) — blocked on HW-18/HW-21/HW-22
- OI-37 — Portainer container management UI  ** CLOSED 2026-07-20)  ✅
- OI-38 — ESP32-S3 thermostat firmware — scope now concrete, see Section 12: two-board design
  (relay board + display), firmware for both not yet written
- OI-39 — ESP32 Modbus polling register list — superseded/narrowed by Section 12: this is now
  specifically the relay board's own RS485/Modbus register map for `serial-2` (design TBD), not
  a register list for polling the OEM Dometic protocol, which is no longer on the control path
- OI-41 — VoIP PBX / LDAP
- OI-42 — IMU leveling page(s) — standalone mobile-first page (priority) + a tab on `rvtc.lan`
  (lower priority, joins the existing Solar/Battery/Power/Weather tabs). Data's already flowing
  (`rvtc/sensors/imu/heading|pitch|roll`, plus the APRS-driven GPS fields added 2026-07-30) — no
  page built yet. **`imu.lan`/`192.168.88.20` was reserved for the earlier abandoned ESP32
  design (HW-25) and is not part of the current WitMotion/Modbus architecture** — don't reuse
  that address for the new page without first confirming nothing else has claimed it since.
- OI-43 — HF5142B serial-1 loopback-plug bench test for `gps_nmea_bridge.service` — pending
  Steve having the DB9 connector shells on hand. Once done, confirm sent/received frame counts
  match on the gateway's Serial Port State page before considering the APRS output path
  validated end-to-end.
- OI-44 — Physical equipment securing pass — after HW-24/HW-31 are installed and commissioned,
  a general tidy-up/securing pass on all RVTC equipment to withstand road vibration and
  movement. Not a specific fault, just standing housekeeping before more driving.
- OI-45 — **Home WeeWX station — planned for fall 2026.** Confirmed 2026-08-12: home gets its
  own permanent weather station rather than relying on the club-bridge weather-swap plan (which
  is dropped — see Section 6). Same adaptor pattern as the RV's WN90LP (Section 1/7) — TBD
  whether it's a second WN90LP or a different head. Will need its own directly-exposed forward
  (same pattern as the RV's `wifi.solsante.com`/`rv.malacat.ca` path, not routed through the
  trailer↔home VPN — weather data is meant to be public), and its own cert — see OI-46.
- OI-46 — **TLS certs for the two directly-exposed WeeWX endpoints — deferred, low priority
  ("rainy day" project), confirmed 2026-08-12.** Not being actively pursued right now; the plan
  below is the reference for whenever it does get picked up, not a queued task. `rv.malacat.ca`
  first (replaces the ad-hoc `wifi.solsante.com` forward now that the RV has its own
  self-updating DDNS hostname — Section 5): add it as a second `server_name` on the existing
  `weewx.lan` nginx block, forward port 80 on the MikroTik alongside the existing 8801 rule for
  the HTTP-01 challenge, then `certbot --nginx`. `home.malacat.ca` follows the same pattern once
  OI-45's home WeeWX ships. Neither needs a wildcard/DNS-01 cert — internal services (HA/Grafana/
  InfluxDB) stay behind the VPN, not exposed by hostname, so only these two need certs at all.
- OI-47 — **Club leg VPN (Pi at Solsante ↔ home)** — not yet built. Descoped from weather-bridge
  duty to network-admin access (camera web UIs, general access into the club LAN) — see Section
  6. UDM Pro's native site-to-site VPN is IPsec/OpenVPN only; check whether the Pi can instead
  run WireGuard directly to an endpoint device before defaulting to IPsec here too.
- OI-48 — ~~IPsec hash mismatch, trailer↔home VPN.~~ **Closed, 2026-10-10:** both phases on
  SHA-256 / AES-256 (ER605 Phase-1 `SHA-256 - AES256 - DH14`; MikroTik installed SAs `sha256`,
  `aes-cbc` 256). See Section 6.
- OI-49 — ~~Trailer↔home VPN over Starlink WAN — only tested on Club WiFi so far.~~ **Closed,
  confirmed working 2026-08-18 — see Section 6.** Real root cause of the initial failure was a
  missing `ipsec-policy=out,none` exclusion on the Starlink NAT masquerade rules, not Starlink's
  CGNAT as originally suspected.
- OI-50 — **Duplicate Starlink NAT masquerade rules** — `/ip firewall nat` rules 1 (`starlink`)
  and 5 (`Starlink always enabled`) are functionally identical (same chain/action/out-interface),
  found while fixing OI-49. Likely leftover from whenever the Starlink rules were added alongside
  the original Rogers ones. Low priority — not blocking anything, just housekeeping.


**Automation / live-test items (no formal number in the archive):**
- Live bench test of the actual Tier 3 automatic trigger (only the manual override path has been
  tested so far)
- KWS grid/generator connect/disconnect switches — not yet added to the Load Control dashboard
- Remove the now-unneeded `/usr/bin/mbpoll` volume mount from `docker-compose.yml` (left over
  from an abandoned HA-native-Modbus attempt)
- Suppress default Telegraf system-metrics noise (cpu/disk/mem) cluttering the InfluxDB bucket —
  low priority

**Resolved / closed since the 2.3 rewrite (2026-08-11/12), not previously reflected here:**
- **Home Pi rebuild — complete.** CM4 (onboard eMMC, no SD slot) re-flashed via
  `usbboot`/`rpiboot -d mass-storage-gadget64` from a Linux box after Windows `rpiboot` failed
  repeatedly (wrong tool, not a hardware fault — see archived 2026-08-11 session log if this
  ever needs repeating on another CM4 unit). Fresh Raspberry Pi OS Lite (64-bit) written to the
  eMMC, headless SSH/user config set at image-write time. **Pi-hole installed and running.** No
  DNS cutover was needed — confirmed this Pi was never actually in the home network's active DNS
  path.
- **Trailer↔home IPsec VPN — built and tested.** See Section 6 for full detail. OI-48 (hash
  agreement) closed 2026-10-10; PSK rotated the same day.
- **Trailer↔home VPN over Starlink WAN — confirmed working, 2026-08-18.** OI-49 closed. Real
  fault was a missing `ipsec-policy=out,none` exclusion on the Starlink NAT masquerade rules
  (traffic was getting NAT'd and dropped before reaching the IPsec policy, while SAs stayed
  healthy throughout) — not Starlink's CGNAT, which was the original suspicion. `rvtc-profile`
  DPD also loosened and a dedicated `ipsec` log buffer added along the way; see Section 6 for
  full detail. New low-priority item opened from this investigation: OI-50 (duplicate Starlink
  NAT rules).
- **WitMotion GPS longitude defect — closed.** Firmware `05821` confirmed correct via 5000-sample
  burst capture; already documented in Section 9.
- **Hantek 6022BL PulseView bring-up — working, no outstanding tooling blockers.** Two bugs
  found and fixed: use the `hantek-6xxx` driver (not `fx2lafw`, which failed to open the device
  even with a correct WinUSB binding), and connect direct to a USB port, not through a hub (the
  hub silently stalled PulseView's firmware-upload step with no error). Confirmed working with a
  clean ~996 Hz calibration-square-wave capture on CH1. Ready for the actual Dometic HVAC signal
  capture whenever that work resumes — tooling isn't the blocker anymore.

---

## 12  HVAC Control System

The single-zone Dometic 579 rooftop AC, originally analog, was converted to a digital Dometic
CT/SZLCD thermostat and control box at some point before this project began. That digital
system is being **replaced entirely** — wall thermostat, control box, and its proprietary
comms protocol — with a custom two-board ESP32 system. This section documents the
investigation that led to that decision and the architecture replacing it. The PulseView
tooling bring-up noted at the end of Section 11 was in service of the investigation below.

### 12a. The OEM digital protocol — what was found, and why it's not being used

Real effort went into reverse-engineering the OEM Dometic single-wire comms protocol between
the wall thermostat and its control box, using a Hantek 6022BE logic analyzer and PulseView.
Summary of what that investigation established (full raw capture history, byte-level tables,
and a reusable parsing script live in a separate `Dometic_Thermostat_Comms_Handover.md`
working doc, not duplicated here):

- **Not real 1-Wire.** Initial PulseView decoder guesses (Dallas/Maxim 1-Wire, plain async
  UART) both produced misleading results before the actual framing was identified.
- **LIN-style framing, at a non-standard, oscillator-drift baud rate.** Settled on 1245 baud
  after a manual sweep-and-split process (confirmed working range 1208–≥1250) — not a
  standard rate, consistent with a cheap bit-banged software UART rather than a hardware
  peripheral.
- **Confirmed, solid fields:** a constant frame ID; a clean 2-bit mode field (OFF/COOL/HEAT/
  FAN); and the stored COOL setpoint, which turned out to be a **lookup table, not a formula**
  — linear for 20–23°C, then genuinely irregular 24–28°C, with two different setpoints (24°
  and 26°) producing identical bytes on the wire.
- **Never solved:** the checksum formula, a credible HEAT setpoint field (candidate found,
  not fully confirmed), and a "two frame family" structural puzzle (the frame's tail bytes
  come in two different shapes, still not understood) that suggests the bus may carry more
  than one message type.
- **Fan speed (Auto/High/Low) was never found anywhere in the broadcast frame**, across many
  independent, carefully-controlled captures. This was the finding that ultimately mattered
  most: it turned out to be structurally correct, not a gap in the analysis — see 12b.

**This work is being kept, not thrown away** — it remains useful for passively monitoring the
OEM thermostat's status if it's ever left in place elsewhere, and as a worked example of the
project's general approach to reverse-engineering an unknown serial bus. It is simply no
longer on the control path for this AC unit.

### 12b. The pivot — the AC unit itself doesn't speak the digital protocol at all

Photographing the actual **CT/SZLCD control box wiring diagram** (the box the OEM digital
thermostat talks to) showed that the control box's job is entirely to translate that one
digital comm wire into a small set of simple relay-driven signals to the AC unit itself:
compressor (one relay), high-speed fan, low-speed fan, furnace call, and heat pump call (not
applicable — this unit has no heat pump). None of the wrestling in 12a was ever going to be
necessary to control the AC — the digital protocol only exists on the thermostat-to-control-box
leg, and the control box was always going to be replaceable with something that drives those
same five simple signals directly. Independent confirmation from a Forest River Forums thread
about the same OEM hardware: the furnace call, at least, is confirmed to be nothing more than
a dry contact closure — any thermostat with relay contacts works for it.

### 12c. New architecture — two ESP32-S3 boards, treated as one subsystem

Per the Architecture Principle in Section 1, an adaptor is allowed to be internally complex as
long as it presents one clean interface outward — the same allowance that lets WeeWX be a
two-stage adaptor. This HVAC system is architected the same way: **two physical boards, one
logical subsystem.** RVTC only ever sees status and load-shed; nothing else about the internal
split is exposed outward.

| Board | Role |
|---|---|
| Waveshare **ESP32-S3-Relay-6CH** | The brain. Lives at/near the AC unit. Drives the AC unit's relay-level signals directly (compressor, high fan, low fan, furnace — mirroring the CT/SZLCD control box's own outputs per 12b). Holds all authoritative state: mode, setpoint, sensed temperature, actual relay positions, compressor short-cycle lockout, freeze-protection status. Owns both safety-critical behaviors outright (12d) — they must keep working even if the display, WiFi, or the RS485 link is down. |
| Waveshare **ESP32-S3-Touch-LCD-5** | Replaces the OEM wall thermostat. Pure HMI — displays what the relay board reports and sends user requests to it. Holds no authoritative state of its own. **Exception:** hosts the cabin-temperature sensor (12c/12d note below) — the one piece of raw sensor data this board originates rather than relaying, on account of physical location, not authority. |

**Link between the two boards:** a dedicated 3-wire TTL UART (TX, RX, GND) over a new
data-only CAT5 run (a separate 12V supply run to this location already exists). At this
distance (~3 m, inside the vehicle), plain TTL UART is sufficient — RS485's differential
signaling isn't needed at this range, and using it here would only add unnecessary
complexity. Pair allocation: TX + its own GND reference on one twisted pair, RX + its own GND
reference on a second pair (each signal keeps its own return path rather than sharing a
common ground across both directions); two pairs held in reserve for future use (a spare
digital I/O or sensor). **This link now also carries the cabin-temperature reading**: the
display board's sensor (see 12c below) is read locally by the display board and sent to the
relay board over this same UART, since the relay board — not the display — is the one with
the RS485/Modbus tie-in to RVTC. Full path: sensor → display board → UART → relay board →
`serial-2` → RVTC. Not yet decided whether this rides in the existing status/command message
exchange or as a separate periodic message — a detail for the eventual firmware/register-map
design (OI-39), not a wiring concern.

**Link to RVTC:** the relay board's onboard RS485/Modbus interface, wired to the HF5142B
gateway's `serial-2` port (see Section 3's updated port table). This port was contested with
HW-33 (three planned enclosure/compartment sensors); resolved in HVAC's favor — see the HW-33
note in Section 11 for why. The relay board publishes status (mode, setpoint, sensed temp,
compressor running, fan state, freeze-protection engaged, remaining short-cycle lockout time)
and accepts a load-shed signal; it does not run its own MQTT client or need its onboard WiFi
for this. The display board is not part of this link at all — from RVTC's perspective, the
two-board HVAC system is a single Modbus device on `serial-2`, same as any other bridge
script's target. **Before wiring**, confirm `serial-2`'s Protocol setting is `None` per the
Section 9 gotcha — flagged in Section 3's table but easy to re-discover the hard way otherwise.

**The sensed-temperature field doubles as RVTC's cabin temperature reading** — this is *why*
the `serial-2` conflict was resolved in HVAC's favor rather than an incidental side effect (see
Section 11's HW-33 note). **Sensing location confirmed: the display board's wall location**,
not the relay board/AC unit as earlier speculated in this section — the display replaces the
OEM thermostat in the same physical spot, which is the standard place to sense cabin comfort
temperature (and likely how the OEM system itself did it). **The
ESP32-S3-Touch-LCD-5's documented spec sheet has no onboard temperature sensor** (checked
against its published peripheral list: CAN, RS485, I2C, TF card, RTC, digital I/O — no temp
sensor) — a dedicated sensor will need to be added at the display board, wired to it directly
(not the relay board). Sensor choice not yet decided; a DS18B20 on a spare GPIO would match
the type already planned for the relay board's freeze sensor (12d), though that's a
consistency preference, not a technical requirement — the board's onboard I2C is also
available if a combined temp/humidity part is preferred instead. **Whatever it turns out to
be, it is a distinct sensor and signal from the DS18B20 in 12d**, which is specifically
coil/freeze-point sensing on the relay board — do not conflate the two when wiring or in
firmware; they live on different boards, at different physical locations, doing different
jobs.

**Load-shed contract:** the relay board treats an incoming shed signal as an unconditional
"force compressor off," independent of thermostat mode/setpoint. Recovery when shed lifts
still goes through the normal short-cycle timer (12d) rather than immediately re-energizing —
shedding must never be allowed to become the reason the compressor short-cycles.

### 12d. Safety logic — lives entirely on the relay board

Both of the following must keep functioning even if the display, WiFi, RS485 link, or RVTC
itself are unreachable — the relay board enforces them locally regardless of what any upstream
command requests.

- **Compressor short-cycle prevention.** Minimum off-time enforced (commonly 3–5 minutes
  industry-standard; exact value TBD) between the compressor relay opening and it being
  allowed to close again. Open question, not yet decided: whether this timer needs to survive
  a power cycle. The relay board has no onboard RTC (unlike the display board, which does) —
  surviving a reboot mid-lockout means writing the last-off timestamp to flash/NVS; the
  simpler alternative (timer resets on power loss) is a real gap given the load-shed
  automation already power-cycles other boards in this project.
- **Freeze prevention.** A DS18B20 wired directly to the relay board (not the display) reads
  coil/evaporator temperature. Below a threshold (~1–2°C, exact value TBD), the compressor
  relay is forced open regardless of any other command and held open until the reading
  recovers past a hysteresis margin, then normal short-cycle-protected control resumes.

### 12e. Broker-to-display data path — wired, no WiFi (decided 2026-09)

For the environmental/power panels floated as a future idea (12c doesn't cover this — those
panels are optional display content, not part of HVAC control), the decision is to extend the
existing wired `serial-2` link bidirectionally rather than add WiFi to either board. This
keeps the whole HVAC/display subsystem free of wireless dependency, consistent with the rest
of this section.

**Mechanism:** a new bridge script on the J45 subscribes to whichever MQTT topics end up
chosen for display (weather's `rvtc/sensors/weather/corrected/loop`; solar/grid/generator for
AC load; DC/battery load via HW-24, live since 2026-08-15) and writes them into
Modbus registers on the relay board over `serial-2` — the relay board remains the Modbus slave
in this exchange, same role it already has for status reads, just now also accepting writes.
**This is not a new pattern for the project** — it's the same broker→device write flow the
load-shed scripts (`relay.py`, `kws_relay.py`, Section 8) already use, applied to dashboard
data instead of an actuation command. The relay board forwards whatever it receives down the
existing inter-board UART to the display, alongside its own status.

**Not yet decided:** which specific panels/topics actually get built (still just an idea, per
this section's earlier note) — this decision covers the transport only. The register map for
this new write direction is an addition to OI-39's existing scope, not a separate item.

**Panel ideas for the display, status as of this revision** (content/design not started —
this is a placeholder list, not a commitment):

| Panel | Data availability |
|---|---|
| Weather (simplified WeeWX glance-view) | Available now — `rvtc/sensors/weather/corrected/loop` |
| AC load (grid/generator/solar) | Available now — KWS/EPEVER topics already flowing |
| DC/battery load | Available now — HW-24 (300A shunt), installed & commissioned 2026-08-15, `rvtc/sensors/battery_current/#` |
| **Tank levels** | **Blocked on HW-29 (holding tank metering, deliberately deferred to fall 2026 per Section 11) — expected to be the last panel implemented, not the first, despite being daily-use once available.** Reserved here as a placeholder so the eventual panel layout leaves room for it; no design or register-map work started. |

Tank levels are flagged separately because they're expected to be the single most-used panel
once live (daily-use, glance-without-thinking, right beside where the operator normally sits)
— worth remembering that "implemented last" here is purely a hardware-sequencing consequence
(HW-29's existing deferral), not a reflection of how much this panel will actually get used.

### 12f. Status as of this revision

Architecture decided; hardware selected and specs confirmed (both boards' RS485/UART/power
specs checked against this plan). `serial-2` port conflict with HW-33 resolved in HVAC's
favor. Cabin-temperature sourcing resolved: sensed at the display board's wall location, not
the relay board — **sensor itself not yet chosen or installed** (display board has no onboard
temp sensor per its spec sheet). Broker-to-display data path decided: wired, via a new
bridge-script write flow over `serial-2` (12e) — no WiFi on either board for this subsystem.
**Not yet built:** relay board firmware, display firmware, the RS485/Modbus register map for
the `serial-2` tie-in in both directions (see updated OI-39), the short-cycle persistence
decision, and physical wiring (control box removed, CAT5 run in progress as of this revision).

---

## 13  Backup Strategy

Three independent jobs, two tools, two machines, one NAS destination. Each job protects a
different failure mode — they are not redundant with each other, and losing any one of them
narrows recovery options rather than duplicating another job's coverage.

| # | Machine | Tool | Protects | Destination |
|---|---|---|---|---|
| 1 | J45 (`ve7cbh-control`) | Borg (via Vorta) | RVTC project + live Docker volume data | `ve7cbh@192.168.88.4:/volume1/BorgBackups/system_backup` (SSH) |
| 2 | Windows workstation (`ve7cbh-rv`) | Restic (via Backrest) | Music, Photos, and other changing personal files | `sftp:ve7cbh@192.168.88.4:/ResticBackups/rv_workstation_backup` |
| 3 | Windows workstation (`ve7cbh-rv`) | Veeam Agent for Windows (free) | Full disk image — OS, installed programs, registry | `\\VE7CBH_NAS\ResticBackups\rv_workstation_image` (SMB) |

Job 1 is the one that actually matters for RVTC continuity. Jobs 2 and 3 protect the
workstation used to develop and document RVTC, not RVTC itself — included here because the
same NAS and the same evening's work set them up, and because losing the workstation's
irreplaceable installed software (job 3) or personal files (job 2) would have been a real,
separate cost.

### 13a. Job 1 — J45 project + Docker volumes (Borg / Vorta)

**Sources** (deliberately narrow — not a whole-filesystem backup):
```
/home/ve7cbh/meshcore stuff
/home/ve7cbh/Documents
/home/ve7cbh/RV-total-control
/home/ve7cbh/NDA-files
/data/docker/volumes
```
`/data` and `/home/ve7cbh` were tried unscoped first and abandoned — they pulled in Timeshift's
system-restore snapshots under `/data/timeshift`, which are huge, mostly root-owned, and
unrelated to RVTC. Scoping to the explicit list above cut a single run from ~50 minutes to
under 90 seconds.

**Consistency:** a pre-backup hook runs `docker stop influxdb`, a post-backup hook runs
`docker start influxdb`. Vorta only runs the post-backup command if the pre-backup command
exits 0, so a failed stop can't leave the backup running against a half-stopped database or
skip the restart. Nothing else in the stack is paused — Telegraf logs harmless connection
errors for the few minutes InfluxDB is down and resumes writing normally once it's back.
`home-assistant_v2.db` reliably logs a `file changed while we backed it up` warning on every
run; expected and harmless (SQLite, not paused) — not a sign of a bad backup.

**Docker-volume permissions — root-owned files, fixed via ACL, not by loosening broadly.**
Several containers write data as root inside the container, which lands as root-owned,
`600`/`700` files on the host that `ve7cbh` (who Vorta and cron run as) can't read. Rather than
run the backup as root or chmod these open, each file got a scoped ACL grant:
```bash
sudo setfacl -m u:ve7cbh:r <file>
sudo setfacl -R -m u:ve7cbh:rx <directory>   # directories need +x to be traversable
```
Files/directories this was needed for, as of this revision:
- `/data/docker/volumes/homeassistant/.storage/auth`
- `/data/docker/volumes/mosquitto/data/mosquitto.db`
- `/data/docker/volumes/pihole/etc-pihole/logrotate`
- `/data/docker/volumes/portainer/{portainer.db,portainer.pub,certs,tls,compose,bin,chisel}`

**Deliberate exception — `portainer.key`:** Portainer's TLS private key is excluded from
backup rather than ACL'd open, via a Vorta exclude pattern (`**/portainer.key`). It's
regenerable (Portainer creates a new one if missing) and the security cost of widening read
access to a private key — even just to `ve7cbh` — wasn't worth it for a file with no real
recovery value. If a new container's root-owned file shows up as a warning in a future run,
same playbook: ACL it if it needs to survive a restore, exclude it if it's regenerable/secret.

**Auth:** dedicated, passphrase-less SSH keypair (`/root/.ssh/borg_backup_key`, copied to
`ve7cbh`'s own `~/.ssh/` since Vorta runs as `ve7cbh`, not root), authorized on the NAS under
the `ve7cbh` account. A passphrase-protected key doesn't work for unattended backups —
`ssh-askpass` has no GUI helper to call in a headless/background context, so the connection
just stalls. Backrest (job 2, below) needed a completely fresh key generated for the same
reason after an existing key's Windows ACL history got too tangled to debug — see 13c.

**Schedule / retention:** daily at 04:11, autopruning after each backup —
keep 7 daily / 4 weekly / 6 monthly / 2 yearly, `keep-within` the last 10 hours regardless.
Repository validated every 3 weeks. Encryption: `repokey-blake2`.

### 13b. Job 2 — Workstation personal files (Restic / Backrest)

**Sources:** Music, Pictures (and similarly-scoped folders as needed) on `ve7cbh-rv`.

**Destination note — DSM's SFTP root is not the real filesystem root.** DSM chroots SFTP
sessions to the volume root: what's `/volume1/ResticBackups` over plain SSH is just
`/ResticBackups` from inside an SFTP session. A repo URI written as
`sftp:ve7cbh@192.168.88.4:/volume1/ResticBackups/...` connects and authenticates fine but then
fails to `mkdir` with a confusing `permission denied` — it isn't a permissions problem, it's a
path problem. Correct form: `sftp:ve7cbh@192.168.88.4:/ResticBackups/rv_workstation_backup`
(no `/volume1` prefix). Worth remembering for any future SFTP-based tool pointed at this NAS —
plain-SSH tools (Borg, job 1) don't have this chroot and use the full `/volume1/...` path as
normal.

**Schedule:** daily via cron expression (`0 3 * * *` — adjust hour as needed), local reference
clock.

### 13c. Job 3 — Workstation full disk image (Veeam Agent for Windows, free)

Covers what Restic can't: installed programs, Windows itself, drivers, registry. Some software
on this workstation would be difficult or impossible to re-obtain/re-license if lost, which is
the specific risk this job exists for — Restic's file-level backup has no way to reconstruct
an installed application. Recovery media (bootable USB) was created at setup time; restoring
onto a larger drive than the original is supported and was the intended path if/when the
system SSD is ever upgraded, rather than a separate cloning tool. Destination:
`\\VE7CBH_NAS\ResticBackups\rv_workstation_image` over SMB — same NAS, different share/protocol
than jobs 1–2 (SMB, not SSH/SFTP), and a separate credential context from the workstation's
already-cached Explorer sessions (see gotcha below).

### 13d. SSH key / Windows ACL gotcha (Backrest, job 2 setup)

Worth recording since it cost significant setup time and isn't obvious: a private key
generated and ACL'd correctly inside `C:\Users\ve7cbh\.ssh\` was rejected by Windows' OpenSSH
client with `UNPROTECTED PRIVATE KEY FILE`/`bad permissions`, even after repeated `icacls`
resets that produced an ACL listing indistinguishable from a working key elsewhere. Root cause
turned out to be a combination of two things:
- Backrest's installer, by default, registers it as a **Session 0 service** (effectively
  running as `SYSTEM`, not the logged-in user) — confirmed via `tasklist /v` showing
  `Session Name: Services`, `User Name: N/A`. A key ACL'd to `ve7cbh` alone is correctly
  unreadable by that context; ACL'd to *both* `ve7cbh` and `SYSTEM` still fails, because
  OpenSSH's Windows permission check wants the file's **owner** to match the account reading
  it too, not just the ACL grant list.
- Reinstalling Backrest to run in the interactive user session (not as a service) sidesteps
  this whole category of problem, since the process then runs as `ve7cbh` — the same context
  the key was created in and the same context that already passed a plain interactive
  `ssh -i ...` test.

After enough resets/moves that the original key's ACL/owner history was no longer trustworthy,
the faster fix was generating a **brand-new key from scratch** at a fresh path
(`C:\Backrest\ssh\backrest_key_v2`) rather than continuing to debug one that had been through
several different security contexts. If this recurs on a future machine: check the runtime
context of whatever's calling `ssh` first (`tasklist /v`, look for `Session Name: Services`)
before spending time on ACL edits — a service-context tool needs the key owned by and
ACL'd to whatever account actually runs it, not to the interactively-logged-in user.

### 13e. Status as of this revision

All three jobs configured, tested, and completing without errors or warnings. Job 1's
Docker-volume permission gaps are fully closed via ACL (13a). Job 2's DSM SFTP-chroot path
issue is resolved and documented (13b) so it isn't rediscovered by a future SFTP-based tool.
Job 3 completed its first full image, and its recurring schedule survived the credential
troubleshooting in 13d intact — confirmed via Veeam's Edit Backup Job dialog: **Daily at
5:30 AM, Everyday**, with "backup once powered on" catch-up if the machine is off at that time
and "keep running" afterward (no sleep/shutdown). Backrest (job 2) likewise retained its
repository config and cron schedule through the reinstall-to-fix-the-ACL-issue in 13d — nothing
needed to be re-entered there once the service was reinstalled in user-session mode.

**Open items, not yet done:**
- No offsite copy yet. Plan is an rsync-over-tunnel leg from the NAS to a home network location,
  layered on top of Job 1's repo (or run independently) — not started.
- Jobs 2 and 3 exist only on `ve7cbh-rv`. Four more machines (mixed Linux/Windows) in the fleet
  still need Backrest set up — the Windows Session-0/ACL gotcha in 13d is now known in advance,
  so future Windows installs should go faster than this one did.

**Resolved since initial setup — Job 2 stale-lock / AppData incident (2026-09-13):**
An early Job 2 source scope included `C:\Users\ve7cbh\AppData`, which is exactly the wrong kind
of folder for a file-level backup — actively locked by running programs, constantly changing,
mostly regenerable cache rather than data worth protecting. A run against that scope hung and
never exited cleanly, leaving a stale Restic repository lock behind; every subsequent run
(including the nightly `forget`) then failed with `unable to create lock in backend ... already
locked by PID ...`. Three changes fixed this properly rather than just clearing the one lock:
- **AppData removed from the plan's Scope.** Nothing under it was actually needed — Music,
  Pictures, and Documents don't live there. If a specific app's data under AppData is ever
  worth protecting, add that one subfolder explicitly rather than the whole tree.
- **Auto Unlock enabled on the repo** (Identity tab in Backrest's repo settings). Restic will
  now clear a stale lock automatically at the start of an operation instead of hard-failing.
  Its own documentation flags this as unsafe *only* if a repo is written to by multiple
  concurrent clients — not the case here, single workstation, single writer — so it's the
  right setting for this repo specifically, not a blanket recommendation.
- **Retention policy set explicitly**, replacing Backrest's out-of-the-box default
  (`hourly: 24, daily: 30, weekly: 0, monthly: 12, yearly: 0` — mismatched for a once-daily
  job) with the same shape as Job 1: 7 daily / 4 weekly / 6 monthly / 2 yearly, hourly: 0.

As of the 2026-09-13 18:28 run, Job 2 completes cleanly (104.5 GiB in under 2 minutes) and
`forget` runs without error. Job 2 is now considered as solid/tested as Job 1.

