# RV Total Control (RVTC) — System Reference
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
| `485-7` | `192.168.88.11:4001` | 400A battery current shunt (HW-24) | *(not yet deployed)* | `rvtc/sensors/battery_current/#` (planned) |
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
| `serial-1` | `192.168.88.13:4001` | *(unassigned — general purpose, see note above)* |
| `serial-2` | `192.168.88.14:4001` | *(unassigned)* |
| `serial-3` | `192.168.88.15:4001` | *(unassigned)* |
| `serial-4` | `192.168.88.16:4001` | *(unassigned)* |

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
`telegraf_snmp.conf`), individually bind-mounted in `docker-compose.yml` — there is no
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
| `rvtc.lan` | Static site — `/usr/share/nginx/rvtc` (custom unified dashboard, `rvtc_index.html`) |
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
internet-reachable path is the single WeeWX forward above. Before adding any further NAT rules
for other services, decide deliberately between direct port-forwarding (simple, but expands
attack surface per service) versus a VPN back into the LAN (WireGuard — reuses infrastructure
already planned for the club-bridge topology below) so every `.lan` hostname "just works" remotely
without individually exposing each service.

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

**Club bridge topology (planned, not yet built):** a small always-on Pi at the club runs
`rtl_433` + WireGuard, connecting to a home Home Assistant instance (not directly to the RV).
When the RV is at the club, GNSS geofencing is meant to detect the position match and suppress
the RV's own weather reading in favor of the club station as authoritative source; when the RV is
elsewhere, the club bridge would feed weather data back to the RV via VLAN over the same
WireGuard link. Reuses the WireGuard infrastructure noted above. Not implemented — this is a
design intent, not current behavior.

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

**Docker container log files don't lose history on their own.** No daemon-wide or per-container
log rotation limit is configured on this host — `docker logs <container>` (no `--since`) dumps
the entire history since container creation, which can be hundreds of MB and make it *look* like
data is missing when it's really just buried. Use `--since`/`--until` to scope a query rather
than assuming a gap means lost data.

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

---

## 11  Open Items

Reconciled against the archived backlog (`RVTC_Consolidated_Reference_Version_1_5.md`, Part 3) —
hardware and software work not yet complete as of this rewrite. Check the archived session logs
for full history/context on any item below.

**Hardware:**
- HW-09 — Generator KWS-303L meter: set slave 2 on bench, wire onto RS-485/3  ✅ Closed 2026-07021
- HW-18 — HSR1-25 25A NO relay — water heater + fridge AC wiring ** Closed - Microwave swapped for Fridge ✅
- HW-19 — 12V→5V DC-DC converter to power the relay board
- HW-20 — ESP32-S3 thermostat: fish DMX cable, firmware
- HW-21 — Wire coil 3 (EVO BMS charge inhibit) ✅ closed 2026-07-21
- HW-22 — Install battery heater, wire coil 5 and 5 (?)  Two batteries, one heater each.
- HW-24 — 400A battery current shunt (RS-485) — ordered, not yet in hand
- HW-27 — WitMotion WTGAHRS3-485 GPS-IMU, roof-mounted — ordered, not yet in hand (replaces the
  abandoned HW-25 ESP32/Adafruit IMU node — see the archived 2026-07-13 log if the history matters)
- HW-28 — ** Closed 2026-07-20 duplicate issue with HW-25 ✅
- HW-29 — Holding tank metering system — modules in hand, not yet installed/wired
- HW-30 — Storage compartment temperature sensors — in hand, not yet installed/wired

**Software / Infrastructure:**
- OI-18 — ESPHome Ansible role
- OI-24 — Load & energy management automation (Tier 1–4) — blocked on HW-18/HW-21/HW-22
- OI-37 — Portainer container management UI  ** CLOSED 2026-07-20)  ✅
- OI-38 — ESP32-S3 thermostat firmware
- OI-39 — ESP32 Modbus polling register list
- OI-41 — VoIP PBX / LDAP

**Automation / live-test items (no formal number in the archive):**
- Live bench test of the actual Tier 3 automatic trigger (only the manual override path has been
  tested so far)
- KWS grid/generator connect/disconnect switches — not yet added to the Load Control dashboard
- SAMLUX EVO-2212 operating mode 3 ("line," currently unconfirmed) — needs a live observation of
  grid-passthrough while not actively charging
- Modes 0, 4, 5 on the EVO-2212 — never observed live, still guesses
- Generator-side KWS relay switch — wired but untestable until generator meter is physically
  installed; needs the same alarm-aware pattern as the grid switch once live
- Confirm which of `485-1`/`485-2`/`485-4`/`485-5` actually corresponds to EPEVER vs. any
  remaining unconfirmed device, per Section 3 — mostly resolved but worth a final live check
- Remove the now-unneeded `/usr/bin/mbpoll` volume mount from `docker-compose.yml` (left over
  from an abandoned HA-native-Modbus attempt)
- Suppress default Telegraf system-metrics noise (cpu/disk/mem) cluttering the InfluxDB bucket —
  low priority

**Closed since the last rewrite (confirmed, don't re-open without new evidence):**
- HW-23 — RS485-1M2S splitter — installed, MT50 reconnected
- OI-16 — Grafana weather dashboard rebuild — completed this week (WeeWX → Telegraf → InfluxDB
  migration; see Section 9)

**Open investigation (not resolved, not urgent):**
- 2026-07-05 unexplained full host reboot during inverter/grid transfer testing — root cause not
  determined; correlated with transfer testing but not confirmed causal. See archived session log
  for full analysis if it recurs.
