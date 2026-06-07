# RVTC Session Context Document
**Last Updated:** June 7, 2026
**Purpose:** Feed this to Claude at the start of each session to restore project context instantly.

---

## Project Identity

| Item | Value |
|---|---|
| Project | RV Total Control (RVTC) |
| Owner | Steve Bradshaw (ve7cbh) |
| GitHub | https://github.com/ve7cbh/RV-total-control |
| Status | Phase 2 Complete — Phase 3 Planning + Phase 7 Architecture Next |

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
| Modbus Gateway | Waveshare 8-Ch RS485 to RJ45 Ethernet Serial Server — 8-port RS-485 to Ethernet, Modbus RTU/TCP, MQTT gateway, industrial isolation, PoE (ASIN B0F5WXX4ZQ) |
| RTL-SDR primary | RTL2838 DVB-T — Rafael Micro R828D tuner — no case — SN 00000001 — currently active |
| RTL-SDR spare | RTL2838 DVB-T — original cased unit — set aside at Port Renfrew |

---

## Software Installed on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |
| rtl-433 | Latest (also in Docker container) |
| rtl-sdr | 2.0.2 (host package — provides rtl_eeprom, udev rules) |
| mosquitto-clients | Latest (mosquitto_sub / mosquitto_pub CLI tools) |
| sqlite3 | Latest (installed 2026-06-07 — for WeeWX archive queries) |

---

## Repository Structure (current state)

```
RV-total-control/
├── ansible.cfg
├── config/
│   ├── Mikrotik Failover.md
│   └── rv-mikrotik-config.rsc          # updated 2026-05-29
├── docs/
│   ├── RVTC_System_Architecture_V0.1.docx
│   ├── RVTC_Ansible_Role_Structure_V0.1.docx
│   ├── RVTC_Phase1_Build_Log.docx
│   ├── RVTC_Session_Context_20260527.md
│   ├── RVTC_Session_Summary_20260528.md
│   ├── RVTC_Session_Summary_20260529.md
│   ├── RVTC_Session_Context_20260529.md
│   ├── RVTC_Session_Context_20260602.md
│   ├── RVTC_Session_Summary_20260603.md
│   ├── RVTC_Session_Context_20260603.md
│   ├── RVTC_Session_Summary_20260607.md
│   └── RVTC_Session_Context_20260607.md
├── group_vars/
│   └── all/
│       ├── all.yml                      # all non-sensitive vars
│       └── vault.yml                    # ansible-vault encrypted
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
│   │   └── tasks/main.yml              # no -d flag — single dongle, no ambiguity
│   ├── weewx/
│   │   ├── defaults/main.yml
│   │   ├── handlers/main.yml
│   │   ├── tasks/main.yml
│   │   └── templates/weewx.conf.j2     # NOT used — weewx.conf managed manually
│   ├── nginx/
│   │   ├── defaults/main.yml
│   │   ├── handlers/main.yml
│   │   ├── tasks/main.yml
│   │   └── templates/nginx.conf.j2     # reverse proxy config
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
| rtl433 | hertzg/rtl_433 | — | none |
| weewx | felddy/weewx | — | /data/docker/volumes/weewx |
| nginx | nginx:alpine | 80 | /data/docker/volumes/weewx/public_html (ro) + nginx.conf |
| homeassistant | ghcr.io/home-assistant/home-assistant | 8123 | /data/docker/volumes/homeassistant |
| pihole | pihole/pihole | 8880 (web), 53 (DNS) | /data/docker/volumes/pihole |

**Docker network:** `rvtc_net`

---

## Web UIs

| Service | Internal URL | Notes |
|---|---|---|
| WeeWX | http://weewx.lan | nginx reverse proxy |
| Grafana | http://grafana.lan | nginx reverse proxy |
| InfluxDB | http://influxdb.lan | nginx reverse proxy |
| Home Assistant | http://homeassistant.lan | nginx reverse proxy |
| Pi-hole | http://pihole.lan | nginx reverse proxy |
| WeeWX (club LAN) | http://wifi.solsante.com:8080 | via club router + MikroTik dst-nat |

**Note:** `.local` TLD was abandoned — it depends on mDNS/Avahi and fails in terminal sessions. All local DNS records use `.lan` which resolves correctly via Pi-hole for both browsers and terminal.

---

## WeeWX Configuration

**Config file location (host):** `/data/docker/volumes/weewx/weewx.conf`
**Config file location (inside container):** `/data/weewx.conf`
**Managed:** Manually on host — Ansible template approach abandoned (too fragile)
**Driver:** MQTTSubscribeDriver — subscribes to `rtl_433/+/events` JSON topic
**Station:** ve7cbh, 48.6686N, 123.6002W, 46m
**Units:** METRICWX (°C, mm, m/s)
**InfluxDB writer:** Custom `/data/docker/volumes/weewx/bin/user/influxdb2.py`
**Archive services:** `weewx.engine.StdArchive, user.influxdb2.InfluxDB2Writer`
**InfluxDB:** host=influxdb, org=rvtc, bucket=rvtc, measurement=weewx
**Time zone:** America/Vancouver (TZ env var in container)
**Archive interval:** 2.5 minutes (150 seconds) — report generation cycle

**Unit conversion in influxdb2.py:** Writer converts from WeeWX internal US customary to metric before writing:
- Temperatures → °C (outTemp, inTemp, dewpoint, windchill, heatindex, appTemp, _max/_min variants)
- Wind speed → m/s (windSpeed, windGust, _max variants)
- Pressure → hPa (barometer, pressure, altimeter)

**Rain sensor:** Tipping bucket — behaviour under investigation. `contains_total = true` (cumulative mode) applied 2026-06-05. Sensor producing elevated readings; unclear if hardware fault or real rain. Physical inspection pending (HW-14). OEM display shows 9.144mm over 3 days (2026-06-05 to 06-07) — use as sanity check after fix.

**Rain sensor weewx.conf stanza:**
```ini
[[[[rain_mm]]]]
    ignore = false
    name = rain
    units = mm
    contains_total = true
```
To disable: set `ignore = true` and `docker restart weewx`.

**Important — no channel/ID filtering:** WeeWX subscribes to `rtl_433/+/events` and accepts any Acurite 5n1 regardless of channel or ID. Phase 7 (Sensor Fusion) will solve multi-station arbitration properly.

*PyEphem for WeeWX — nice to have (OI-28)*

---

## WeeWX Database — Key Notes

**Database path (host):** `/data/docker/volumes/weewx/archive/weewx.sdb`
**sqlite3:** Not in WeeWX container — query from host using `sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb`

**Useful queries:**
```bash
# Recent archive records
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, rain, rainRate FROM archive ORDER BY dateTime DESC LIMIT 20;"

# Daily rain summary (source for week/month/year stats)
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, sum, max, count FROM archive_day_rain ORDER BY dateTime DESC LIMIT 14;"
```

**Rebuild daily summaries after archive edits:**
```bash
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=YYYY-MM-DD --yes
```
- Config path inside container is `/data/weewx.conf` (not `/home/weewx/weewx.conf`)
- `--yes` required — command prompts interactively and fails via `docker exec` without it

**Rain data history:**
- All data prior to 2026-06-03 ~15:35 UTC was in US customary units — bucket flushed
- Phantom rain data from stuck float (pre-2026-06-05 18:52 UTC) zeroed from archive
- Clean rain data accumulating from 2026-06-05 18:52 UTC onward (with caveats — see rain sensor note)

---

## Acurite 5n1 Stations

| ID | Channel | Location | Status |
|---|---|---|---|
| 1111 | A | Base station — pole-mounted at home | Fixed — stays at base, not being received at Port Renfrew |
| 291 | C | Mobile unit — travels with RV and J45 | Currently active at Port Renfrew |

Note: spare 5n1 unit tested 2026-06-02 — confirmed DOA (HW-12).

---

## RTL-SDR Dongles

| Unit | Tuner | SN | Case | Status |
|---|---|---|---|---|
| Primary (active) | Rafael Micro R828D | 00000001 | No case | In J45 — currently running |
| Spare | Unknown | 00000001 (won't hold 00000002) | Cased | Set aside at Port Renfrew |
| RTL-SDR Blog V3 | R860, TCXO, SMA, aluminium | — | Aluminium | Ordered — delivery 2026-06-05 (HW-11) |

**Notes:**
- Both clone dongles report SN 00000001 — second dongle eeprom write does not stick
- Single dongle operation: no `-d` flag needed — grabs index 0 by default

---

## rtl_433 Configuration

**Container command:**
```
-F "mqtt://mosquitto:1883,retain=1"
-R 40
-M time:iso
-M protocol
-C si
```
**MQTT topic:** `rtl_433/<host_id>/events` (JSON)
**SI units:** temperature_C, wind_avg_km_h, rain_mm
**Note:** `-R 40` limits decoding to Acurite 5n1 protocol only.
**Note:** `retain=1` — stale retained messages persist in MQTT when station moves out of range.

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

## Network Allocation

| IP | Device | Interface |
|---|---|---|
| 192.168.88.1 | MikroTik gateway | — |
| 192.168.88.2 | Windows workstation | — |
| 192.168.88.3 | Beelink J45 — ethernet (primary) | enp1s0 |
| 192.168.88.4 | J45 WiFi interface — disabled autoconnect | wlp3s0 |
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

**Note:** All records use `.lan` — `.local` was abandoned (mDNS conflict; fails in terminal).

---

## MikroTik — Current State

**DNS:** Primary 192.168.88.3 (Pi-hole), secondary 8.8.8.8
**DHCP:** Hands out 192.168.88.3 as DNS server to all clients

**Active pinholes:**
| Rule | Description |
|---|---|
| Filter forward rule 24 | Accept club LAN (192.168.0.0/21) → 192.168.88.3:80 |
| NAT dst-nat rule 7 | rogers-wan port 80 → 192.168.88.3:80 (WeeWX) |

**WeeWX external access path:**
`wifi.solsante.com:8080` → club router → MikroTik rogers-wan:80 → dst-nat → 192.168.88.3:80 → nginx → WeeWX

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
| 3 | Power Integration | ⏳ Pending |
| 4 | Tank & Propane Sensing | ⏳ Pending |
| 5 | Water Monitoring | ⏳ Pending |
| 6 | Baseline & Handover | ⏳ Pending |
| 7 | Sensor Fusion | ⏳ Architecture phase — design next |

---

## Phase 7 — Sensor Fusion (Architecture Notes)

**Concept:** A normalised MQTT sensor bus with a fusion/arbitration layer that assigns the best available source to each logical field, with configurable priority ordering and automatic fallback when a source goes stale.

**Problem it solves:** WeeWX (and HA) currently accept any 5n1 data without discrimination. As the sensor ecosystem grows — multiple RTL-SDR dongles, ESPHome nodes, Modbus devices, GNSS, external APIs — a single subscriber consuming raw topics becomes unmanageable and produces interleaved/conflicting data.

**Planned source types:**
- RTL-SDR (one or more dongles) — 433 MHz ISM band
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

**Consumers:** WeeWX (via fused MQTT topic), Home Assistant, Grafana

---

## Open Items / Backlog

### Software / Configuration

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| OI-14 | WeeWX Seasons skin CSS | 2 | ✅ Complete | Fixed 29/5 — cosmetic only |
| OI-15 | Home Assistant onboarding | 2/3 | 🟡 Open | Container up — setup wizard + MQTT integration not yet done |
| OI-16 | Grafana weather dashboard | 2 | ✅ Complete | Built 2026-05-30 — °F bug fixed 2026-06-03 — cleanup items remain (legends, auto-refresh, data source rename) |
| OI-17 | Ansible weewx role cleanup | 2 | 🟡 Open | Template approach abandoned — role needs rethink for idempotency; .yml → .yaml rename in scope |
| OI-18 | ESPHome Ansible role | 3 | 🟡 Open | nginx block already in place; role to be created |
| OI-19 | MQTT Explorer | 2/3 | 🟡 Open | Install in HA or standalone; TBD — may be superseded by Phase 7 fusion UI |
| OI-20 | HA multi-site linking | 3 | 🟡 Open | Make Homelan HA and RV HA visible to each other — VPN prerequisite |
| OI-21 | VOIP / PBX inter-site | 3+ | 🟡 Open | SIP trunk over site-to-site WireGuard VPN between RV and home. FreePBX is heavy; consider Asterisk or baresip. Prerequisite: OI-20. |
| OI-22 | WiFi autoconnect fix | 2 | 🟡 Open | Make nmcli radio wifi off / autoconnect=no permanent via Ansible common role |
| OI-23 | dvb_usb_rtl28xxu blacklist | 2 | 🟡 Open | Kernel module conflicts with RTL-SDR — blacklist via Ansible rtl433 role |
| OI-24 | 120VAC load shedding on solar | 3 | 🟡 Open | Disconnect water heater and fridge when net solar balance is negative over rolling 24h window. Needs smart relay + EPEVER MPPT data. Design alongside Phase 3. |
| OI-25 | Phase 7 Sensor Fusion — architecture and implementation | 7 | 🟡 Open | Python fusion service (new container), normalised MQTT schema, priority UI, per-field source assignment with auto-fallback |
| OI-26 | rtl433 container device addressing | 2 | 🟡 Open | Stable device addressing for dual dongles. udev-by-serial unreliable on clone hardware. Revisit with HW-11. |
| OI-27 | Add rtl-sdr package to Ansible common role | 2 | 🟡 Open | Provides rtl_eeprom and udev rules. Installed manually 2026-06-02. |
| OI-28 | PyEphem for WeeWX | 2 | 🟡 Open | pip install ephem + weectl extension install + weewx.conf stanza. Bake into custom image or Ansible role. Install when OI-17 done. |
| OI-29 | GNSS-driven WeeWX position update | 3 | 🟡 Open | Auto-update lat/lon/altitude in weewx.conf when position changes. Fix-quality sanity check required. Manual updates in interim. Critical for WU and CWOP accuracy. Prerequisite: HW-10. |
| OI-30 | RV position display page | 3 | 🟡 Open | OSM map — Leaflet.js via nginx or Grafana Geomap. Prerequisite: HW-10, Phase 7. |
| OI-31 | Local DNS .local → .lan migration | 2 | ✅ Complete | All Pi-hole records updated to .lan. .local abandoned — mDNS conflict fails in terminal. |
| OI-32 | WeeWX upstream bug report | — | 🟡 Open | Report to WeeWX GitHub: contains_total=true + hardware fault → corrupted archive_day_rain → silent week/month/year stat failure. Include diagnostic path (sqlite3 queries) and fix procedure. |

### Hardware / Physical Install

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| HW-01 | Install Waveshare 8-Ch RS485 gateway | 3 | 🟡 Open | 8-port RS-485→Ethernet, industrial isolation, PoE; IP 192.168.88.5 already allocated |
| HW-02 | Build RS-485 cables | 3 | 🟡 Open | For SAMLUX EVO-2212 and EPEVER MPPT controller |
| HW-03 | Install 4×100W PV panels | 3 | 🟡 Open | Get solar data flowing before full array |
| HW-04 | Wire 9 PV panels (3S×3P, ~36V) | 3 | 🟡 Open | Complete solar system for data collection |
| HW-05 | Source barometric pressure sensor | 3/5 | 🟡 Open | For ESP32 sensor node |
| HW-06 | Build ESP32 sensor node | 5 | 🟡 Open | Pulse water meter, turbidity, pressure ×2, flow — scope TBD (see DD-02) |
| HW-07 | Design tank monitoring sensors | 4/5 | 🟡 Open | Sensor types and mounting TBD |
| HW-08 | Source/install KWS-303L — grid | 3 | 🟡 Open | AC power meter, grid input; RS-485 Modbus to gateway port 3 |
| HW-09 | Source/install KWS-303L — generator | 3 | 🟡 Open | AC power meter, generator input; RS-485 Modbus to gateway port 4 |
| HW-10 | Install GNSS E108-GN03G-485 | 3 | 🟡 Open | COJXU/Ebyte E108-GN03G-485 — AT6558R chip, BDS/GPS/GLONASS, RS485, IP67. Protocol: NMEA0183 at 9600 baud. Waveshare gateway port 6 (TCP 4006). |
| HW-11 | Replace primary RTL-SDR with RTL-SDR Blog V3 | 3 | 🔵 Ordered | V3 (R860, TCXO, SMA, aluminium case) ordered Amazon.ca C$61.55 — delivery 2026-06-05. Drop-in replacement. |
| HW-12 | Diagnose/replace spare Acurite 5n1 | — | 🟡 Open | Spare unit confirmed DOA 2026-06-02 |
| HW-13 | Smart relay/contactor for 120VAC load shedding | 3 | 🟡 Open | Required for OI-24 — water heater and fridge disconnect under solar deficit |
| HW-14 | Rain sensor inspection and repair | — | 🟡 Open | Tipping bucket producing elevated readings — behaviour ambiguous under light rain. OEM reference: 9.144mm over 3 days. Physical inspection at club required before re-enabling in WeeWX. |
| HW-15 | Install POE-SW802-DIN PoE switch | 3 | 🟡 Open | BV Security POE-SW802-DIN — 10-port unmanaged hardened PoE switch, DIN-rail mount. Powers Waveshare RS485 gateway and other bay devices via PoE. |

### Design / Documentation

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| DD-01 | System wiring drawing | 3 | 🟡 Open | Full system diagram with wire lists and hardware lists |
| DD-02 | ESP32 sensor node scope definition | 5 | 🟡 Open | Decide which sensors to include: water meter pulse, turbidity, pressure ×2, flow |
| DD-03 | Phase 7 sensor fusion architecture document | 7 | 🟡 Open | Topic schema, source types, staleness model, UI spec, container design |

---

## Key Paths on J45

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root |
| `~/.vault_pass` | Ansible Vault password — chmod 600 |
| `/data/docker/volumes` | All Docker volume data |
| `/data/docker/volumes/weewx/weewx.conf` | WeeWX live config — edit here (= /data/weewx.conf inside container) |
| `/data/docker/volumes/weewx/bin/user/influxdb2.py` | Custom InfluxDB writer |
| `/data/docker/volumes/weewx/archive/weewx.sdb` | WeeWX SQLite archive database |
| `/data/docker/volumes/nginx/nginx.conf` | nginx reverse proxy config |
| `/etc/udev/rules.d/99-rtlsdr.rules` | Custom RTL-SDR udev rules (MODE=0666 override) |

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo uses `trixie` hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE.
- **GitHub auth:** PAT in `~/.git-credentials` via credential.helper store.
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`.
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`.
- **weewx.conf:** Managed manually on host at `/data/docker/volumes/weewx/weewx.conf`. Edit directly and `docker restart weewx`.
- **WeeWX no ID/channel filtering:** MQTTSubscribeDriver subscribes to `rtl_433/+/events` and accepts any Acurite 5n1. Phase 7 will solve multi-station arbitration.
- **Pi-hole listeningMode:** Must be `all` — set via `FTLCONF_dns_listeningMode: "all"` env var. Default `local` rejects queries from outside Docker bridge subnet.
- **SAMLUX register map:** Full Modbus register map held locally under NDA. Never paste into chat.
- **InfluxDB token:** Stored in vault as `vault_influxdb_token`. Also in weewx.conf in plaintext (private network, acceptable).
- **WiFi autoconnect disabled:** wlp3s0 set to autoconnect=no. Was causing IP conflict with enp1s0 (.3) on startup. WiFi disabled via `nmcli radio wifi off`. Ansible role needed to make permanent (OI-22).
- **dvb_usb_rtl28xxu:** Kernel module conflicts with RTL-SDR dongle — needs blacklisting via Ansible rtl433 role (OI-23).
- **MQTT retained messages:** rtl_433 publishes with `retain=1`. Stale retained messages from previous locations persist. Not a problem for WeeWX — uses timestamps for data freshness.
- **InfluxDB historical data:** Bucket flushed 2026-06-03 — all data prior to ~15:35 UTC is gone. Was in US customary units. influxdb2.py now converts to metric before writing.
- **Rain sensor:** Tipping bucket producing elevated readings under light rain. Physical inspection required (HW-14). OEM display reference: 9.144mm over 3 days (2026-06-05 to 06-07).
- **Local DNS:** All records use `.lan` TLD. `.local` abandoned — depends on mDNS/Avahi, fails in terminal sessions.
- **sqlite3:** Not in WeeWX container. Installed on host 2026-06-07. Query WeeWX archive directly at `/data/docker/volumes/weewx/archive/weewx.sdb`.
- **weectl config path:** Inside container is `/data/weewx.conf`. Pass as `--config=/data/weewx.conf`. Add `--yes` to skip interactive confirmation when running via `docker exec`.

---

## Session Log

### 2026-05-27
Tasks 1–7 complete. Full Phase 2 scaffolding + common role live.

### 2026-05-28
Tasks 8–13 complete. Full core stack deployed:
- Mosquitto, InfluxDB, Grafana, rtl_433, WeeWX, nginx, Home Assistant, Pi-hole
- Acurite 5n1 weather station live via rtl_433 → MQTT → WeeWX
- Pi-hole DNS working with listeningMode=all fix
- MikroTik DNS updated to Pi-hole

### 2026-05-29
Phase 2 wrap-up complete:
- WeeWX → InfluxDB integration working (custom influxdb2.py writer)
- WeeWX time zone fixed (TZ=America/Vancouver)
- WeeWX units confirmed METRICWX
- nginx reverse proxy configured — local DNS names working
- Pi-hole local DNS records added for all services
- MikroTik pinhole configured — WeeWX accessible at wifi.solsante.com:8080
- MikroTik RSC updated

### 2026-05-30
- Backlog formalised: OI-14 through OI-20, HW-01 through HW-07, DD-01 through DD-02
- ESPHome ambient sensor YAML built: `rvtc-ambient.yaml`
- Grafana RVTC Weather dashboard built (OI-16 ✅)
- InfluxDB data source connected to Grafana

### 2026-05-31
- HF5142B replaced with Waveshare 8-Ch RS485 Ethernet Serial Server
- mosquitto-clients installed
- dvb_usb_rtl28xxu kernel module conflict diagnosed (OI-23)
- WiFi IP conflict diagnosed and disabled (OI-22)
- Steve taking RV to Port Renfrew — project resumes over Starlink from campsite

### 2026-06-02 (Port Renfrew — Starlink)
- Stack confirmed live and logging from campsite over Starlink
- Mobile Acurite 5n1 (ID 291, Channel C) confirmed working
- Spare Acurite 5n1 confirmed DOA (HW-12)
- Phase 7 Sensor Fusion scoped (OI-25, DD-03)
- Second RTL-SDR dongle tested — dual-dongle deferred (OI-26)
- Stack fully recovered and logging — WeeWX live at 13:35 PDT

### 2026-06-03 (Port Renfrew — Starlink)
- influxdb2.py unit conversion fix: CONVERSIONS map added — temperatures °F→°C, wind mph→m/s, pressure inHg→hPa ✅
- InfluxDB bucket flushed — clean metric data accumulating from ~15:35 UTC
- Rain sensor disabled in WeeWX — phantom triggers (hardware fault); HW-14 added
- OI-29 and OI-30 added — GNSS position update and RV position display page

### 2026-06-05 (Port Renfrew — Starlink)
- Rain sensor cumulative fix: changed weewx.conf rain_mm stanza to `contains_total = true`
- Fixed per-interval and daily rain total — week/month/year stats still broken (archive corruption)

### 2026-06-07 (Port Renfrew — Starlink)
- sqlite3 installed on host
- Diagnosed archive_day_rain corruption — phantom data from stuck-float period (pre-2026-06-05 18:52 UTC)
- Zeroed phantom archive records for June 5 (09:30–18:52 UTC) and one June 7 spike
- Zeroed bogus archive_day_rain rows; rebuilt daily summaries via weectl
- Confirmed weectl config path: /data/weewx.conf; --yes flag required via docker exec
- Local DNS migrated from .local to .lan (OI-31 ✅)
- Rain sensor still producing elevated readings under light rain — deferred to club (HW-14)
- OI-32 added — WeeWX upstream bug report

**Next session:** Rain sensor physical inspection at club (HW-14), Home Assistant onboarding (OI-15), ESPHome Ansible role (OI-18), Grafana cleanup (OI-16), WiFi autoconnect fix (OI-22), dvb blacklist (OI-23), WeeWX upstream bug report (OI-32).
