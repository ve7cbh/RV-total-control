# RVTC Session Context Document
**Last Updated:** June 3, 2026
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
│   └── RVTC_Session_Context_20260603.md
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
| WeeWX | http://weewx.local | nginx reverse proxy |
| Grafana | http://grafana.local | nginx reverse proxy |
| InfluxDB | http://influxdb.local | nginx reverse proxy |
| Home Assistant | http://homeassistant.local | nginx reverse proxy |
| Pi-hole | http://pihole.local | nginx reverse proxy |
| WeeWX (club LAN) | http://wifi.solsante.com:8080 | via club router + MikroTik dst-nat |

---

## WeeWX Configuration

**Config file location (host):** `/data/docker/volumes/weewx/weewx.conf`
**Managed:** Manually on host — Ansible template approach abandoned (too fragile)
**Driver:** MQTTSubscribeDriver — subscribes to `rtl_433/+/events` JSON topic
**Station:** ve7cbh, 48.6686N, 123.6002W, 46m
**Units:** METRICWX (°C, mm, m/s)
**InfluxDB writer:** Custom `/data/docker/volumes/weewx/bin/user/influxdb2.py`
**Archive services:** `weewx.engine.StdArchive, user.influxdb2.InfluxDB2Writer`
**InfluxDB:** host=influxdb, org=rvtc, bucket=rvtc, measurement=weewx
**Time zone:** America/Vancouver (TZ env var in container)

**Unit conversion in influxdb2.py:** Writer converts from WeeWX internal US customary to metric before writing:
- Temperatures → °C (outTemp, inTemp, dewpoint, windchill, heatindex, appTemp, _max/_min variants)
- Wind speed → m/s (windSpeed, windGust, _max variants)
- Pressure → hPa (barometer, pressure, altimeter)

**Rain sensor:** Tipping bucket disabled in WeeWX as of 2026-06-03 — hardware fault (phantom triggers). Re-enable after physical inspection.

**Important — no channel/ID filtering:** WeeWX subscribes to `rtl_433/+/events` and accepts any Acurite 5n1 regardless of channel or ID. Metadata fields (channel, id, model, sequence_num, battery_ok, message_type) are ignored by default but can be enabled — this is one mechanism for discriminating between multiple sensors of the same type. Phase 7 (Sensor Fusion) will solve multi-station arbitration properly.

*PyEphem for WeeWX — nice to have (OI-28)*

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

**Notes:**
- Both dongles report SN 00000001 — second dongle eeprom write does not stick (FC0012 clone behaviour)
- `[R82XX] PLL not locked!` on container startup is harmless — clears once receiving
- udev permissions issue: `/etc/udev/rules.d/99-rtlsdr.rules` exists but `60-librtlsdr0.rules` from rtl-sdr package wins and sets `MODE=0660 GROUP=plugdev` — container can open device because it runs privileged/root with broad `/dev/bus/usb` pass-through
- Single dongle operation: no `-d` flag needed in rtl433 container — grabs index 0 by default
- Dual dongle operation deferred to HW-11 (CC1101) or better quality SDR hardware

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
**MQTT topic:** `rtl_433/<host_id>/devices/<model>/<channel>/<id>/...` (per-field) and `rtl_433/<host_id>/events` (JSON)
**SI units:** temperature_C, wind_avg_km_h, rain_mm
**Note:** `-R 40` limits decoding to Acurite 5n1 protocol only. Use `-R 0` to decode all protocols.

---

## InfluxDB

**Version:** 2.x
**Org:** rvtc
**Bucket:** rvtc
**Token:** stored in vault as `vault_influxdb_token`
**Admin user:** ve7cbh
**Data:** WeeWX weather archive records, measurement=weewx
**Note:** Bucket flushed 2026-06-03 — clean metric data from ~15:35 UTC onward only. All prior data was in US customary units (°F, mph, inHg) and discarded.

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

**Admin:** http://pihole.local (no password)
**DNS port:** 53
**Upstream:** 8.8.8.8 (Google)

**Local DNS records:**
| Domain | IP |
|---|---|
| weewx.local | 192.168.88.3 |
| grafana.local | 192.168.88.3 |
| influxdb.local | 192.168.88.3 |
| homeassistant.local | 192.168.88.3 |
| pihole.local | 192.168.88.3 |

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
- RTL-SDR (one or more dongles) — 433 MHz ISM band, potentially other frequencies via spectrum scan
- CC1101 module (HW-11) — replaces RTL-SDR dongle when installed
- ESPHome nodes — publish directly to MQTT
- Modbus devices via Waveshare gateway — EPEVER, SAMLUX, KWS-303L, water sensors
- GNSS receiver (HW-10)
- External APIs — e.g. Environment Canada as fallback for fields with no local sensor

**Key design decisions to resolve:**
1. Normalised MQTT topic schema (e.g. `rvtc/sensors/{source_id}/{field}`)
2. Staleness timeout — will differ by source type (433 vs Modbus vs API)
3. Whether fusion layer does sanity checking (e.g. reject outTemp = 80°C)
4. UI approach — live source discovery, per-field priority assignment, enable/disable per source
5. Implementation: Python fusion service (new container + Flask API) is the current preference over Node-RED or HA templates

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
| OI-21 | VOIP / PBX inter-site | 3+ | 🟡 Open | SIP trunk over site-to-site WireGuard VPN between RV and home is practical. FreePBX is heavy; consider Asterisk direct config or baresip. Prerequisite: OI-20. Scope when network foundation is in place. |
| OI-22 | WiFi autoconnect fix | 2 | 🟡 Open | Make nmcli radio wifi off / autoconnect=no permanent via Ansible common role |
| OI-23 | dvb_usb_rtl28xxu blacklist | 2 | 🟡 Open | Kernel module conflicts with RTL-SDR — blacklist via Ansible rtl433 role |
| OI-24 | 120VAC load shedding on solar | 3 | 🟡 Open | Automatically disconnect water heater and fridge when net solar balance is negative over a rolling 24h window. Needs: smart relay/contactor on 120VAC circuit (HA or MQTT controlled), EPEVER MPPT data as input (Phase 3). Design alongside Phase 3 power integration. |
| OI-25 | Phase 7 Sensor Fusion — architecture and implementation | 7 | 🟡 Open | Python fusion service (new container), normalised MQTT schema, priority UI, per-field source assignment with auto-fallback |
| OI-26 | rtl433 container device addressing | 2 | 🟡 Open | When running dual dongles, need stable device addressing. udev-by-serial unreliable on clone hardware. Options: udev-by-port-path, or quality dongles with reliable eeproms. Revisit with HW-11. |
| OI-27 | Add rtl-sdr package to Ansible common role | 2 | 🟡 Open | Provides rtl_eeprom and udev rules. Installed manually 2026-06-02. |
| OI-28 | PyEphem for WeeWX | 2 | 🟡 Open | pip install ephem + weectl extension install + weewx.conf stanza. Bake into custom image or Ansible role — don't install manually into running container. Install when OI-17 (weewx role rework) is done. |
| OI-29 | GNSS-driven WeeWX position update | 3 | 🟡 Open | Auto-update lat/lon/altitude in weewx.conf when position changes beyond a threshold. Must include fix-quality sanity check before writing and restart WeeWX after update. Critical: WeeWX reports to Weather Underground and CWOP — position must be accurate. Prerequisite: HW-10. Manual updates to weewx.conf in the interim. |
| OI-30 | RV position display page | 3 | 🟡 Open | OSM map showing current RV position — Leaflet.js page served via nginx, or Grafana Geomap panel pulling lat/lon from InfluxDB. Prerequisite: HW-10, Phase 7 sensor bus for GNSS data feed. |

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
| HW-10 | Install GNSS E108-GN03G-485 | 3 | 🟡 Open | COJXU/Ebyte E108-GN03G-485 — AT6558R chip, BDS/GPS/GLONASS, RS485, IP67, ceramic antenna. C$9.18 AliExpress. Protocol: NMEA0183 at 9600 baud default (GGA, RMC, GSA, GSV, VTG). Wiring: RED=VCC (3.3–5.5V), GREEN=RS485-A, WHITE=RS485-B. Assign to Waveshare gateway port 6 (TCP 4006). Fix quality field in $GPGGA is sanity check for OI-29 — only update weewx.conf on fix quality 1 or 2. Will feed Phase 7 sensor bus. |
| HW-11 | Replace primary RTL-SDR with RTL-SDR Blog V3 | 3 | 🔵 Ordered | CC1101 ruled out — requires custom protocol decoder firmware, not suitable. V4 end-of-line. V3 (R860, TCXO, SMA, aluminium case) ordered Amazon.ca C$61.55 — delivery 2026-06-05. Drop-in replacement for existing rtl_433 container — no software changes required. |
| HW-12 | Diagnose/replace spare Acurite 5n1 | — | 🟡 Open | Spare unit confirmed DOA 2026-06-02 |
| HW-13 | Smart relay/contactor for 120VAC load shedding | 3 | 🟡 Open | Required for OI-24 — water heater and fridge disconnect under solar deficit |
| HW-14 | Rain sensor inspection and repair | — | 🟡 Open | Tipping bucket triggering phantom rain events — inspect float and reed switch; re-enable in WeeWX after fix |
| HW-15 | Install POE-SW802-DIN PoE switch | 3 | 🟡 Open | BV Security POE-SW802-DIN — 10-port unmanaged hardened PoE switch, DIN-rail mount. 8×PoE ports (ports 1–2 ≤90W BT/Hi-PoE, ports 3–8 ≤30W), 1×GbE uplink (port 9), 1×SFP uplink (port 10). Powers Waveshare RS485 gateway and other bay devices via PoE. Powered via 12V→48V DC-DC DIN-rail converter on 12V house bus. Enable PoE Watchdog on RS485 gateway port. |

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
| `/data/docker/volumes/weewx/weewx.conf` | WeeWX live config — edit here |
| `/data/docker/volumes/weewx/bin/user/influxdb2.py` | Custom InfluxDB writer |
| `/data/docker/volumes/nginx/nginx.conf` | nginx reverse proxy config |
| `/etc/udev/rules.d/99-rtlsdr.rules` | Custom RTL-SDR udev rules (MODE=0666 override) |

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo uses `trixie` hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE.
- **GitHub auth:** PAT in `~/.git-credentials` via credential.helper store.
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`.
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`.
- **weewx.conf:** Managed manually on host at `/data/docker/volumes/weewx/weewx.conf`. Ansible template approach was abandoned — too many overwrites corrupted the config. Edit directly and `docker restart weewx`.
- **WeeWX no ID/channel filtering:** MQTTSubscribeDriver subscribes to `rtl_433/+/events` and accepts any Acurite 5n1. No channel or ID discrimination. Works correctly when only one station is in range. Phase 7 will solve multi-station arbitration.
- **Pi-hole listeningMode:** Must be `all` — set via `FTLCONF_dns_listeningMode: "all"` env var in Ansible role. Default `local` rejects queries from outside Docker bridge subnet.
- **SAMLUX register map:** Full Modbus register map held locally under NDA. Never paste into chat.
- **InfluxDB token:** Stored in vault as `vault_influxdb_token`. Also in weewx.conf in plaintext (private network, acceptable).
- **WiFi autoconnect disabled:** wlp3s0 (Auto VE7CBH_Mikrotik + solsante profiles) set to autoconnect=no. Was causing IP conflict with enp1s0 (.3) on startup. WiFi disabled via `nmcli radio wifi off`. Ansible role needed to make this permanent (OI-22).
- **dvb_usb_rtl28xxu:** Kernel module conflicts with RTL-SDR dongle — needs blacklisting via Ansible rtl433 role (OI-23).
- **RTL-SDR udev permissions:** `/etc/udev/rules.d/99-rtlsdr.rules` sets MODE=0666 but `60-librtlsdr0.rules` from rtl-sdr package may win (sets MODE=0660 GROUP=plugdev). Container works because it uses broad `/dev/bus/usb` device pass-through. Fix properly in Ansible rtl433 role (OI-26/OI-27).
- **Clone dongle eeprom:** Cheap RTL2838 clones with FC0012 tuner may not retain eeprom serial number writes across power cycles. Use quality dongles (e.g. RTL-SDR Blog v3/v4) for reliable dual-dongle operation.
- **MQTT retained messages:** rtl_433 publishes with `retain=1`. Stale retained messages from previous locations will appear in MQTT even when that station is out of range. Not a problem for WeeWX — it uses timestamps to determine data freshness.
- **InfluxDB historical data:** Bucket flushed 2026-06-03 — all data prior to ~15:35 UTC is gone. Was in US customary units. influxdb2.py now converts to metric before writing.
- **Rain sensor disabled:** Tipping bucket disabled in WeeWX as of 2026-06-03 due to phantom triggers. Re-enable after HW-14 inspection.

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
- Backlog formalised: OI-14 through OI-20 (software), HW-01 through HW-07 (hardware), DD-01 through DD-02 (design/docs)
- `.yaml` adopted as standard extension for all YAML files; `.yml` → `.yaml` rename added to OI-17 scope
- ESPHome ambient sensor YAML built: `rvtc-ambient.yaml` — 5× DS18B20 + BME280, ESP32 dev board
- Grafana RVTC Weather dashboard built (OI-16 ✅): Outside Temperature, Outdoor Humidity, Wind Speed & Gusts, Rain
- InfluxDB data source connected to Grafana (Flux, container-to-container)

### 2026-05-31
- HF5142B replaced with Waveshare 8-Ch RS485 Ethernet Serial Server (ASIN B0F5WXX4ZQ) — 8 ports, industrial isolation, PoE, MQTT gateway
- Port allocation expanded: ports 3 & 4 assigned to KWS-303L AC power meters (grid and generator)
- HW-08 and HW-09 added to hardware backlog for KWS-303L meters
- Network allocation note: IP 192.168.88.5 carried forward for new gateway
- mosquitto-clients installed (mosquitto_sub / mosquitto_pub)
- dvb_usb_rtl28xxu kernel module conflict diagnosed — blacklist pending Ansible role update (OI-23)
- WiFi IP conflict diagnosed: wlp3s0 was grabbing 192.168.88.3 on startup — autoconnect disabled on both WiFi profiles; `nmcli radio wifi off` applied. Ansible role needed to make permanent (OI-22).
- Steve taking RV to Port Renfrew — project resumes over Starlink from campsite

### 2026-06-02 (Port Renfrew — Starlink)
- Stack confirmed live and logging from campsite over Starlink
- Mobile Acurite 5n1 (ID 291, Channel C) confirmed working — WeeWX receiving and archiving correctly
- Confirmed WeeWX has no channel/ID filtering — accepts any 5n1 in range; documented as known behaviour
- Spare Acurite 5n1 tested — confirmed DOA (HW-12 added)
- Phase 7 Sensor Fusion scoped and added to project (OI-25, DD-03 added)
- OI-21 (VOIP) and OI-24 (120VAC load shedding) assessed and formalised
- Second RTL-SDR dongle tested — both report SN 00000001, eeprom write to spare does not stick; dual-dongle deferred (OI-26)
- rtl-sdr host package installed (OI-27 added)
- Spare dongle set aside; primary (uncased R828D) now active in J45
- Stack fully recovered and logging — WeeWX live at 13:35 PDT

### 2026-06-03 (Port Renfrew — Starlink)
- influxdb2.py unit conversion fix: added CONVERSIONS map — temperatures °F→°C, wind mph→m/s, pressure inHg→hPa; deployed and confirmed working (14.3°C ✅)
- InfluxDB bucket flushed — all historical data in US customary units discarded; clean metric data accumulating from ~15:35 UTC
- Rain sensor disabled in WeeWX — tipping bucket triggering phantom rain events; hardware inspection pending (HW-14 added)
- OI-15 (Home Assistant) — container up, no configuration changes this session
- OI-29 and OI-30 added — GNSS-driven WeeWX position update and OSM position display page; WeeWX position updates manual in the interim (WU and CWOP reporting requires accuracy)

**Next session:** Home Assistant onboarding — MQTT integration, WeeWX entities (OI-15), ESPHome Ansible role (OI-18), Grafana cleanup — legends/auto-refresh/data source rename (OI-16), rain sensor re-enable after HW-14 fix, WiFi autoconnect fix (OI-22), dvb blacklist (OI-23).
