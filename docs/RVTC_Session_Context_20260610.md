# RVTC Session Context Document
**Last Updated:** June 10, 2026
**Purpose:** Feed this to Claude at the start of each session to restore project context instantly.

---

## Project Identity

| Item | Value |
|---|---|
| Project | RV Total Control (RVTC) |
| Owner | Steve Bradshaw (ve7cbh) |
| GitHub | https://github.com/ve7cbh/RV-total-control |
| Status | Phase 2 Complete — Phase 3 Active |

---

## Hardware

| Item | Specification |
|---|---|
| Host | Beelink J45 |
| CPU | Intel Pentium J4205 (4-core) |
| RAM | 8 GB |
| Root drive | /dev/sda — 256 GB — mounted / |
| Data drive | /dev/sdb — 640 GB — mounted /data |
| OS | Linux Mint LMDE (Debian trixie base) |
| Hostname | ve7cbh-control |
| Primary user | ve7cbh |
| Access | SSH from Windows workstation |
| Modbus Gateway | Waveshare 8-Ch RS485 to RJ45 Ethernet Serial Server — 8-port RS-485 to Ethernet, Modbus RTU/TCP, MQTT gateway, industrial isolation, PoE (ASIN B0F5WXX4ZQ) — **in hand** |
| RTL-SDR primary | RTL-SDR Blog V3 — R820T tuner, SMA, aluminium case — SN 1024 — **active (rtl433 container)** |
| RTL-SDR secondary | RTL2838 DVB-T clone — R828D tuner — SN 00000001 — **active (rtl433b container)** |

---

## Software Installed on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |
| rtl-433 | Latest (also in Docker container) |
| rtl-sdr | Latest (host package — provides rtl_eeprom, udev rules) |
| mosquitto-clients | Latest (mosquitto_sub / mosquitto_pub CLI tools) |
| sqlite3 | Latest |

---

## Repository Structure (current state)

```
RV-total-control/
├── ansible.cfg
├── config/
│   ├── Mikrotik Failover.md
│   ├── nginx.conf                       # working nginx config — committed 2026-06-09
│   ├── rv-mikrotik-config.rsc           # updated 2026-06-09 (ether8 + pinhole fixes)
│   ├── rv-mikrotik-config_ether8_fix.rsc  # pre-fix copy — kept for reference
│   ├── rvtc-ambient.yml
│   ├── temp_press_flash.yml
│   └── weewx.conf                       # working weewx.conf — committed 2026-06-09
├── docker-compose.yml                   # canonical compose file — run from here always
├── docs/
│   └── [session context and summary files]
├── group_vars/
│   └── all/
│       ├── all.yml
│       └── vault.yml
├── host_vars/
│   └── localhost.yml
├── inventories/
│   └── production/
│       └── hosts.ini
├── roles/
│   ├── common/
│   ├── mosquitto/
│   ├── influxdb/
│   ├── grafana/
│   ├── rtl433/
│   ├── weewx/
│   ├── nginx/
│   ├── homeassistant/
│   ├── pihole/
│   └── rtl433/
├── phase2.yml
├── site.yml
└── README.md
```

---

## Ansible Configuration

**ansible.cfg:**
```ini
[defaults]
interpreter_python = /usr/bin/python3.13
vault_password_file = ~/.vault_pass
```

**~/.vault_pass:** Plain text, chmod 600, never committed.

**inventories/production/hosts.ini:**
```ini
[rvtc]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3.13
```

**group_vars/all/ structure:** Two files loaded automatically:
- `all.yml` — all non-sensitive vars
- `vault.yml` — ansible-vault encrypted, contains:
  - vault_influxdb_user / vault_influxdb_password
  - vault_grafana_user / vault_grafana_password
  - vault_pihole_user / vault_pihole_password
  - vault_influxdb_token

---

## Running Docker Stack

| Container | Image | Port(s) | Volume |
|---|---|---|---|
| mosquitto | eclipse-mosquitto | 1883 | /data/docker/volumes/mosquitto |
| influxdb | influxdb:2 | 8086 | /data/docker/volumes/influxdb |
| grafana | grafana/grafana | 3000 | /data/docker/volumes/grafana |
| rtl433 | hertzg/rtl_433:latest | — | none |
| rtl433b | hertzg/rtl_433:latest | — | none |
| weewx | felddy/weewx | — | /data/docker/volumes/weewx |
| nginx | nginx:alpine | 80 | /data/docker/volumes/weewx/public_html (ro) + nginx.conf |
| homeassistant | ghcr.io/home-assistant/home-assistant | 8123 | /data/docker/volumes/homeassistant |
| pihole | pihole/pihole | 8880 (web), 53 (DNS) | /data/docker/volumes/pihole |

**CRITICAL:** Always run `docker compose up/down` from `~/RV-total-control/` — this is the canonical compose file location. Running from `/data/docker/volumes/` puts containers on the wrong network (`volumes_default` instead of `rvtc_net`) and breaks inter-container DNS.

**Docker network:** `rvtc_net`

---

## Web UIs

| Service | Internal URL | Notes |
|---|---|---|
| WeeWX | http://weewx.lan | nginx reverse proxy — serves Belchertown skin |
| Grafana | http://grafana.lan | nginx reverse proxy |
| InfluxDB | http://influxdb.lan | nginx reverse proxy |
| Home Assistant | http://homeassistant.lan | nginx reverse proxy |
| Pi-hole | http://pihole.lan | nginx reverse proxy |
| WeeWX (club LAN) | http://wifi.solsante.com:8080 | via club router + MikroTik dst-nat |

**Note:** Always use `http://` prefix in browser — bare `.lan` names get intercepted as search queries.
**Note:** `.local` TLD abandoned — mDNS/Avahi conflict; fails in terminal. All records use `.lan`.

---

## WeeWX Configuration

**Config file location (host):** `/data/docker/volumes/weewx/weewx.conf`
**Config file location (inside container):** `/data/weewx.conf`
**Managed:** Manually on host — copy committed to `config/weewx.conf` in repo
**Driver:** MQTTSubscribeDriver — subscribes to `rtl_433/+/events` JSON topic
**Station:** ve7cbh, 48.6686N, 123.6002W, 46m
**Units:** METRICWX (°C, mm, m/s) via `StdConvert target_unit = METRICWX`
**InfluxDB writer:** Custom `/data/docker/volumes/weewx/bin/user/influxdb2.py`
**Archive services:** `weewx.engine.StdArchive, user.influxdb2.InfluxDB2Writer`
**InfluxDB:** host=influxdb, org=rvtc, bucket=rvtc, measurement=weewx
**Time zone:** America/Vancouver (TZ env var in container)
**Archive interval:** 2.5 minutes (150 seconds)
**Skin:** Belchertown (dark mode) — output at `/data/public_html/belchertown`
**PyEphem:** Installed — extended celestial data available including civil twilight

**Field mappings (MQTTSubscribeDriver):**
```ini
[[[[temperature_F]]]]
    name = outTemp
    units = degree_F          # StdConvert handles F→C automatically
[[[[humidity]]]]
    name = outHumidity
[[[[wind_avg_km_h]]]]
    name = windSpeed
    units = km_per_hour
[[[[wind_dir_deg]]]]
    name = windDir
[[[[rain_in]]]]
    ignore = false
    name = rain
    units = inch              # StdConvert handles inch→mm automatically
    contains_total = true     # Acurite 5n1 sends cumulative bucket counts
```

**ID filter:** `filter_out_message_when = 291` — excludes Port Renfrew unit when both in range.
Not yet tested under rain conditions.

**Important — rtl_433 field names:** Both Acurite 5n1 units publish `temperature_F` and `rain_in` regardless of rtl_433 version. `StdConvert` converts to metric before archiving.

**Rain sensor:** `contains_total = true` is the critical setting. Without it, every cumulative reading adds to the total producing phantom rain accumulation. Physical inspection of club rain gauge still pending (HW-14).

---

## WeeWX Database — Key Notes

**Database path (host):** `/data/docker/volumes/weewx/archive/weewx.sdb`
**sqlite3:** Not in WeeWX container — query from host using `sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb`

**Useful queries:**
```bash
# Recent archive records
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, rain, rainRate FROM archive ORDER BY dateTime DESC LIMIT 20;"

# Daily rain summary
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, sum, max, count FROM archive_day_rain ORDER BY dateTime DESC LIMIT 14;"
```

**Rebuild daily summaries after archive edits:**
```bash
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=YYYY-MM-DD --yes
```

---

## Acurite 5n1 Stations

| ID | Channel | Location | Status |
|---|---|---|---|
| 1111 | A | Home base — pole-mounted | Active — primary unit at home base |
| 291 | C | Mobile — travels with RV | At home base — filtered out in weewx.conf |

Note: spare 5n1 unit confirmed DOA (HW-12).

---

## RTL-SDR Dongles

| Unit | Tuner | SN | Status |
|---|---|---|---|
| RTL-SDR Blog V3 | R820T, SMA, aluminium | 1024 | Active — primary (rtl433 container) |
| Clone (old primary) | R828D | 00000001 | Active — secondary (rtl433b container) |

**Notes:**
- PLL not locked warning on both tuners is benign — always present, does not affect reception
- USB device path in compose is `/dev/bus/usb:/dev/bus/usb` (whole bus) — immune to device number changes
- Both containers pin to dongle by serial via `-d` flag — immune to device index changes on reboot
- Counterintuitively, the R828D tuner is in the clone/fake dongle (SN 00000001) and the R820T is in the genuine RTL-SDR Blog V3 (SN 1024)
- WeeWX receives duplicate packets from both containers via `rtl_433/+/events` wildcard — benign, data is identical. Deduplication is a Phase 7 fusion layer concern.

---

## rtl_433 Configuration

**Primary container:** `rtl433` — SN 1024 (Blog V3, R820T)
```
-M si -d 1024 -F "mqtt://mosquitto:1883,retain=1,events=rtl_433/rtl433/events"
```

**Secondary container:** `rtl433b` — SN 00000001 (clone, R828D)
```
-M si -d 00000001 -F "mqtt://mosquitto:1883,retain=1,events=rtl_433/rtl433b/events"
```

**WeeWX MQTT subscription:** `rtl_433/+/events` (wildcard — receives from both containers)
**Note:** `+` wildcard is invalid in MQTT publish topics — use explicit topic name.
**Note:** `-M si` flag does NOT convert Acurite 5n1 field names — decoder hardcodes `temperature_F` and `rain_in`.

---

## InfluxDB

**Version:** 2.x
**Org:** rvtc
**Bucket:** rvtc
**Token:** stored in vault as `vault_influxdb_token`
**Admin user:** ve7cbh
**Data:** WeeWX weather archive records, measurement=weewx
**Note:** Bucket flushed 2026-06-03 — clean metric data from ~15:35 UTC onward only.

---

## Grafana

**URL:** http://grafana.lan
**Admin:** admin / admin (reset after reboot 2026-06-09 — dashboard lost)
**Note:** Dashboard needs rebuilding — lost after volume permissions issue on first post-migration reboot.
**Fix applied:** `user: "472:472"` in docker-compose.yml — prevents future permission issues.
**After every stack restart:** `sudo chown -R 472:472 /data/docker/volumes/grafana` if dashboard missing.

---

## Network Allocation

| IP | Device | Interface |
|---|---|---|
| 192.168.88.1 | MikroTik gateway | — |
| 192.168.88.2 | Windows workstation | — |
| 192.168.88.3 | Beelink J45 — ethernet (primary) | enp1s0 |
| 192.168.88.4 | J45 WiFi interface — disabled | wlp3s0 |
| 192.168.88.5 | Waveshare 8-Ch RS485 gateway | — |

---

## Pi-hole DNS

**Admin:** http://pihole.lan (no password)
**DNS port:** 53
**Upstream:** 8.8.8.8 (Google)

**Local DNS records:**
| Domain | IP |
|---|---|
| weewx.lan | 192.168.88.3 |
| grafana.lan | 192.168.88.3 |
| influxdb.lan | 192.168.88.3 |
| homeassistant.lan | 192.168.88.3 |
| pihole.lan | 192.168.88.3 |

---

## MikroTik — Current State

**Config file:** `config/rv-mikrotik-config.rsc` (dated 2026-06-09)
**DNS:** Primary 192.168.88.3 (Pi-hole), secondary 8.8.8.8
**DHCP:** Hands out 192.168.88.3 as DNS server to all clients

**Active pinholes:**
| Rule | Description |
|---|---|
| NAT dst-nat | rogers-wan port 80 → 192.168.88.3:80 (WeeWX) |

**WeeWX external access path:**
`wifi.solsante.com:8080` → club router → MikroTik rogers-wan:80 → dst-nat → 192.168.88.3:80 → nginx → WeeWX

**Pending:** New RSC (ether8 + pinhole fixes) not yet installed on router — install and test next visit.

---

## Waveshare 8-Ch RS485 Gateway — Port Allocation

| Port | TCP Port | Bus | Device(s) | Phase |
|---|---|---|---|---|
| RS-485/1 | 4001 | Power — Solar | EPEVER MPPT60 | 3 |
| RS-485/2 | 4002 | Power — Inverter | SAMLUX EVO-2212 | 3 |
| RS-485/3 | 4003 | Power — Grid meter | KWS-303L (grid) | 3 |
| RS-485/4 | 4004 | Power — Generator meter | KWS-303L (generator) | 3 |
| RS-485/5 | 4005 | Water sensors | Pressure + Filter ΔP + Turbidity | 5 |
| RS-485/6 | 4006 | GNSS | E108-GN03G-485 position/time receiver | 3 |
| RS-485/7 | 4007 | Spare | — | — |
| RS-485/8 | 4008 | Spare | — | — |

---

## Project Phases

| Phase | Title | Status |
|---|---|---|
| 0 | Architecture & Design | ✅ Complete |
| 1 | Beelink J45 Build | ✅ Complete |
| 2 | Core Stack Deployment | ✅ Complete |
| 3 | Power Integration | 🔄 Active |
| 4 | Tank & Propane Sensing | ⏳ Pending |
| 5 | Water Monitoring | ⏳ Pending |
| 6 | Baseline & Handover | ⏳ Pending |
| 7 | Sensor Fusion | ⏳ Architecture phase |

---

## Phase 7 — Sensor Fusion (Architecture Notes)

**Concept:** A normalised MQTT sensor bus with a fusion/arbitration layer that assigns the best available source to each logical field, with configurable priority ordering and automatic fallback when a source goes stale.

**Planned source types:**
- RTL-SDR (dual dongles, SN 1024 + SN 00000001) — independent receivers, same 433 MHz sensors — deduplication and failover required
- ESPHome nodes — publish directly to MQTT
- Modbus devices via Waveshare gateway — EPEVER, SAMLUX, KWS-303L, water sensors
- GNSS receiver (HW-10)
- External APIs — e.g. Environment Canada as fallback

**Key design decisions to resolve:**
1. Normalised MQTT topic schema (e.g. `rvtc/sensors/{source_id}/{field}`)
2. Staleness timeout — will differ by source type
3. Whether fusion layer does sanity checking (e.g. reject outTemp = 80°C)
4. UI approach — live source discovery, per-field priority assignment
5. Implementation: Python fusion service (new container + Flask API)
6. **Duplicate packet handling** — with dual RTL-SDR dongles both subscribing to the same sensor, WeeWX currently receives identical packets from both containers via the `rtl_433/+/events` wildcard. The fusion layer should deduplicate by (sensor_id, timestamp) and arbitrate by signal quality or source priority rather than processing duplicates. This also enables genuine redundancy — if one dongle drops out, the fusion layer fails over to the other automatically without WeeWX seeing any gap.

**Consumers:** WeeWX (via fused MQTT topic), Home Assistant, Grafana

**Club bridge topology (OI-33/OI-34):**
- Small always-on Pi at club runs rtl_433 + WireGuard
- Connects to home J45 only — never directly to RV
- Home J45 Mosquitto is the hub — RV subscribes to home regardless of its own location
- When RV is at club: GNSS geofence (OI-34) detects position match → fusion layer suppresses RV 5n1 (ID 1111) → club station becomes authoritative source
- When RV is remote: club bridge feeds weather data to home J45 → forwarded to RV via VLAN
- Club Pi Ansible role: rtl_433 + WireGuard + auto-reconnect (reuses OI-20 VPN infrastructure)

---

## Open Items / Backlog

### Software / Configuration

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| OI-14 | WeeWX Seasons skin CSS | 2 | ✅ Complete | Fixed 29/5 — cosmetic only |
| OI-15 | Home Assistant onboarding | 2/3 | 🟡 Open | Container up — setup wizard + MQTT integration not yet done |
| OI-16 | Grafana weather dashboard | 2 | 🟡 Open | Dashboard lost after reboot 2026-06-09 — needs rebuilding; cleanup items remain |
| OI-17 | Ansible weewx role cleanup | 2 | ✅ Complete | weewx.conf saved to config/; manual management accepted |
| OI-18 | ESPHome Ansible role | 3 | 🟡 Open | nginx block already in place; role to be created |
| OI-19 | MQTT Explorer | 2/3 | 🟡 Open | May be superseded by Phase 7 fusion UI |
| OI-20 | HA multi-site linking | 3 | 🟡 Open | VPN prerequisite |
| OI-21 | VOIP / PBX inter-site | 3+ | 🟡 Open | Prerequisite: OI-20 |
| OI-22 | WiFi autoconnect fix | 2 | ✅ Complete | Ansible common role — nmcli radio off + autoconnect=no |
| OI-23 | dvb_usb_rtl28xxu blacklist | 2 | ✅ Complete | Ansible common role |
| OI-24 | 120VAC load shedding on solar | 3 | 🟡 Open | Smart relay + EPEVER MPPT data required |
| OI-25 | Phase 7 Sensor Fusion | 7 | 🟡 Open | Python fusion service, normalised MQTT schema |
| OI-26 | rtl433 container device addressing | 2 | ✅ Complete | Resolved by passing /dev/bus/usb whole bus + serial-based -d flag |
| OI-27 | Add rtl-sdr package to Ansible common role | 2 | ✅ Complete | Added with sqlite3 to common_packages |
| OI-28 | Belchertown skin / PyEphem | 2 | ✅ Complete | Belchertown installed (dark mode); civil twilight in template; PyEphem active |
| OI-29 | GNSS-driven WeeWX position update | 3 | 🟡 Open | Prerequisite: HW-10 |
| OI-30 | RV position display page | 3 | 🟡 Open | Prerequisite: HW-10, Phase 7 |
| OI-31 | Local DNS .local → .lan migration | 2 | ✅ Complete | nginx.conf updated 2026-06-09 |
| OI-32 | WeeWX upstream bug report | — | 🟡 Open | contains_total=true + hardware fault → corrupted archive_day_rain → silent stats failure |
| OI-33 | Club bridge Pi | 3 | 🟡 Open | Small controller at club — rtl_433 + WireGuard, connects to home J45 only, back-feeds to RV when remote. Prerequisite: OI-20 (VPN) |
| OI-34 | GNSS geofence source inhibit | 7 | 🟡 Open | Suppress RV 5n1 (ID 1111) automatically when RV is at club — use club bridge as authoritative source instead. Prerequisite: HW-10, OI-33, Phase 7 fusion layer |

### Hardware / Physical Install

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| HW-01 | Install Waveshare 8-Ch RS485 gateway | 3 | 🟡 Open | **In hand** — commissioning next session |
| HW-02 | Build RS-485 cables | 3 | 🟡 Open | For SAMLUX EVO-2212 and EPEVER MPPT controller |
| HW-03 | Install 4×100W PV panels | 3 | 🟡 Open | Get solar data flowing before full array |
| HW-04 | Wire 9 PV panels (3S×3P, ~36V) | 3 | 🟡 Open | Complete solar system |
| HW-05 | Source barometric pressure sensor | 3/5 | 🟡 Open | For ESP32 sensor node |
| HW-06 | Build ESP32 sensor node | 5 | 🟡 Open | Pulse water meter, turbidity, pressure ×2, flow |
| HW-07 | Design tank monitoring sensors | 4/5 | 🟡 Open | Sensor types and mounting TBD |
| HW-08 | Source/install KWS-303L — grid | 3 | 🟡 Open | AC power meter, grid input; RS-485 port 3 |
| HW-09 | Source/install KWS-303L — generator | 3 | 🟡 Open | AC power meter, generator input; RS-485 port 4 |
| HW-10 | Install GNSS E108-GN03G-485 | 3 | 🟡 Open | RS485, IP67, Waveshare gateway port 6 (TCP 4006) |
| HW-11 | RTL-SDR Blog V3 | 3 | ✅ Complete | R820T tuner, SN 1024, antenna fitted, confirmed working — primary dongle (rtl433 container) |
| HW-12 | Replace spare Acurite 5n1 | — | 🟡 Open | Spare confirmed DOA 2026-06-02 |
| HW-13 | Smart relay/contactor for 120VAC load shedding | 3 | 🟡 Open | Required for OI-24 |
| HW-14 | Rain sensor inspection and repair | — | 🟡 Open | Physical inspection at club required — sensor behaviour now better understood |
| HW-15 | Install POE-SW802-DIN PoE switch | 3 | 🟡 Open | Powers Waveshare gateway and bay devices |

### Design / Documentation

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| DD-01 | System wiring drawing | 3 | 🟡 Open | Full system diagram |
| DD-02 | ESP32 sensor node scope definition | 5 | 🟡 Open | Sensor types TBD |
| DD-03 | Phase 7 sensor fusion architecture document | 7 | 🟡 Open | Topic schema, source types, staleness model |

---

## Key Paths on J45

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root — **always run docker compose from here** |
| `~/RV-total-control/docker-compose.yml` | Canonical compose file |
| `~/.vault_pass` | Ansible Vault password — chmod 600, never committed |
| `/data/docker/volumes` | All Docker volume data |
| `/data/docker/volumes/weewx/weewx.conf` | WeeWX live config (= /data/weewx.conf inside container) |
| `/data/docker/volumes/weewx/bin/user/influxdb2.py` | Custom InfluxDB writer |
| `/data/docker/volumes/weewx/archive/weewx.sdb` | WeeWX SQLite archive database |
| `/data/docker/volumes/nginx/nginx.conf` | nginx reverse proxy config |
| `/data/docker/volumes/weewx/public_html/belchertown` | Belchertown skin output |
| `/etc/udev/rules.d/99-rtlsdr.rules` | Custom RTL-SDR udev rules (MODE=0666 override) |
| `/etc/modprobe.d/rtlsdr.conf` | dvb_usb_rtl28xxu blacklist |

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo uses `trixie` hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE.
- **GitHub auth:** PAT in `~/.git-credentials` via credential.helper store.
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`.
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`.
- **weewx.conf:** Managed manually on host. Edit directly and `docker restart weewx`.
- **weectl config path:** Inside container is `/data/weewx.conf`. Pass as `--config=/data/weewx.conf`. Add `--yes` to skip interactive confirmation via `docker exec`.
- **WeeWX field names:** rtl_433 publishes `temperature_F` and `rain_in` — not metric. StdConvert (target_unit=METRICWX) handles conversion automatically.
- **contains_total = true:** Critical for rain — Acurite 5n1 sends cumulative bucket counts. Without it, phantom rain accumulates rapidly.
- **MQTT topic:** rtl433 publishes to `rtl_433/rtl433/events`, rtl433b publishes to `rtl_433/rtl433b/events`. WeeWX subscribes to `rtl_433/+/events` (wildcard match — receives from both). `+` is valid in subscribe but NOT in publish topics.
- **Dual RTL-SDR setup:** Both dongles active simultaneously. WeeWX receives duplicate packets from both containers — benign, data is identical. Deduplication is a Phase 7 fusion layer concern.
- **RTL-SDR serial addressing:** Both containers use `-d <serial>` to pin to a specific dongle — immune to device index changes on reboot. SN 1024 = Blog V3 (primary), SN 00000001 = clone (secondary).
- **Docker compose location:** MUST run from `~/RV-total-control/`. Wrong directory = wrong network = containers can't reach each other.
- **Pi-hole listeningMode:** Must be `all` — set via `FTLCONF_dns_listeningMode: "all"` env var.
- **SAMLUX register map:** Full Modbus register map held locally under NDA. Never paste into chat.
- **InfluxDB token:** Stored in vault as `vault_influxdb_token`. Also in weewx.conf in plaintext (private network, acceptable).
- **WiFi autoconnect disabled:** wlp3s0 set to autoconnect=no, radio off. Managed via Ansible common role.
- **MQTT retained messages:** rtl_433 publishes with `retain=1`. Stale retained messages persist. Not a problem for WeeWX.
- **InfluxDB historical data:** Bucket flushed 2026-06-03 — all data prior to ~15:35 UTC is gone.
- **Local DNS:** All records use `.lan` TLD. `.local` abandoned.
- **sqlite3:** Not in WeeWX container. Installed on host. Query WeeWX archive at `/data/docker/volumes/weewx/archive/weewx.sdb`.
- **Grafana dashboard:** Lost 2026-06-09 after reboot/permissions fix. Needs rebuilding. `user: "472:472"` now in compose to prevent recurrence.
- **Belchertown dark mode:** Toggled via on-page switch — persists in browser local storage.

---

## Session Log

### 2026-05-27
Tasks 1–7 complete. Full Phase 2 scaffolding + common role live.

### 2026-05-28
Full core stack deployed: Mosquitto, InfluxDB, Grafana, rtl_433, WeeWX, nginx, Home Assistant, Pi-hole. Acurite 5n1 live via rtl_433 → MQTT → WeeWX.

### 2026-05-29
Phase 2 wrap-up: WeeWX → InfluxDB integration, nginx reverse proxy, Pi-hole DNS, MikroTik pinhole for WeeWX.

### 2026-05-30
Backlog formalised. ESPHome ambient sensor YAML built. Grafana RVTC Weather dashboard built.

### 2026-05-31
Waveshare RS485 gateway ordered. mosquitto-clients installed. dvb_usb conflict and WiFi IP conflict diagnosed. Steve taking RV to Port Renfrew.

### 2026-06-02 (Port Renfrew — Starlink)
Stack confirmed live from campsite. Mobile Acurite 5n1 (ID 291, Channel C) working. Phase 7 scoped.

### 2026-06-03 (Port Renfrew — Starlink)
influxdb2.py unit conversion fix. InfluxDB bucket flushed. Rain sensor disabled (phantom triggers).

### 2026-06-05 (Port Renfrew — Starlink)
Rain sensor cumulative fix: `contains_total = true` applied to rain_mm stanza.

### 2026-06-07 (Port Renfrew — Starlink)
sqlite3 installed. archive_day_rain corruption diagnosed and fixed. Local DNS migrated .local → .lan.

### 2026-06-09 (Home base — Rogers)
- Returned from Port Renfrew — trailering caused WeeWX gap
- Full WeeWX/rtl_433 diagnosis: wrong compose file location (network isolation), USB path hardcoded, invalid MQTT publish topic (`+` wildcard), wrong field name mappings (`temperature_C`/`rain_mm` → `temperature_F`/`rain_in`)
- RTL-SDR Blog V3 (HW-11) received — antenna not yet fitted, could not be commissioned
- Old clone dongle used as temporary primary — confirmed working
- dvb_usb_rtl28xxu blacklist applied and baked into Ansible
- Phase 2 OI items completed: OI-22, OI-23, OI-27, OI-17, OI-28, OI-31, OI-26
- Belchertown skin installed with dark mode
- Grafana user fix applied (472:472)
- MikroTik RSC updated (ether8 + pinhole fixes)
- **Phase 2 complete — Phase 3 active**

### 2026-06-10 (Home base — Rogers)
- RTL-SDR Blog V3 (SN 1024, R820T) fitted with antenna — confirmed working on Windows then swapped into J45 as primary dongle
- Clone dongle (SN 00000001, R828D) retained as secondary — rtl433b container added to docker-compose.yml
- Both containers pin to dongle by serial via `-d` flag
- Dual dongle setup confirmed working — both decoding Acurite 5n1 ID 1111 independently
- docker-compose.yml committed and pushed (85b7357)
- OI-33 added: Club bridge Pi (rtl_433 + WireGuard → home J45)
- OI-34 added: GNSS geofence source inhibit (suppress RV 5n1 when at club)
- Club bridge architecture agreed: club Pi → home J45 only → RV via VLAN; home is hub

**Next session:** Waveshare RS-485 gateway commissioning (HW-01), EPEVER MPPT60 Modbus integration, SAMLUX EVO-2212 integration, solar panel wiring, Home Assistant onboarding (OI-15), Grafana dashboard rebuild (OI-16).
