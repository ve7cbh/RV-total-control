# RV Total Control — Project Reference
**Last Updated:** June 13, 2026
**Owner:** Steve Bradshaw (ve7cbh) — Nanaimo, BC
**GitHub:** https://github.com/ve7cbh/RV-total-control
**Status:** Phase 2 Complete — Phase 3 Active

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Hardware](#2-hardware)
3. [Network](#3-network)
4. [Docker Stack](#4-docker-stack)
5. [WeeWX Configuration](#5-weewx-configuration)
6. [Ansible & Repository](#6-ansible--repository)
7. [Open Items & Backlog](#7-open-items--backlog)
8. [Session Log](#8-session-log)
9. [Architecture Notes](#9-architecture-notes)

---

## 1  Project Overview

RV Total Control (RVTC) is a full-stack monitoring and control system for a recreational vehicle, built on a Beelink J45 mini-PC running Linux Mint LMDE. The system integrates weather sensing, power management (solar, inverter, grid, generator), tank monitoring, water quality measurement, and location tracking into a unified dashboard accessible both locally and over the internet.

The architecture uses Ansible-managed Docker containers feeding data via MQTT into InfluxDB and Grafana, with Home Assistant for automation and alerting. The design draws from industrial, marine, and automotive engineering practice — see Section 9.3 for full details.

### 1.1  Phase Status

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

## 2  Hardware

### 2.1  Beelink J45 (Control Node)

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
| Access | SSH from Windows workstation (192.168.88.2) |
| IP | 192.168.88.3 (ethernet enp1s0) — WiFi disabled |

### 2.2  Software on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |
| rtl-433 | Latest (host + Docker container) |
| rtl-sdr | Latest (provides rtl_eeprom, udev rules) |
| mosquitto-clients | Latest (mosquitto_sub / mosquitto_pub CLI) |
| sqlite3 | Latest (host — WeeWX archive queries) |

### 2.3  RTL-SDR Dongles

| Unit | Tuner | Serial | Container | Status |
|---|---|---|---|---|
| RTL-SDR Blog V3 (aluminium, SMA) | R820T | 1024 | rtl433 | ✅ Active — primary |
| Clone (DVB-T) | R828D | 00000001 | rtl433b | ✅ Active — secondary |

**Notes:**
- Both containers pin to dongle via `-d <serial>` — immune to device index changes on reboot
- USB path in compose: `/dev/bus/usb:/dev/bus/usb` (whole bus passthrough)
- PLL not locked warning is benign — always present on both tuners
- Counterintuitively the R828D (generally higher spec) is in the clone, not the Blog V3

### 2.4  Acurite 5n1 Weather Stations

| ID | Channel | Location | Status |
|---|---|---|---|
| 1111 | A | Home base — pole-mounted | Active — primary |
| 291 | C | Mobile — travels with RV | At home — filtered out in weewx.conf |
| Spare | — | — | DOA (HW-12) — replacement pending |

### 2.5  Monitored & Controlled Systems

**Power:**
- EPEVER MPPT60 solar charge controller — Modbus RS-485
- SAMLUX EVO-2212 inverter-charger — Modbus RS-485
- KWS-303L × 2 — AC power meters (grid input, generator input) — RS-485
- Waveshare Modbus RTU 8-ch Relay / RS485 — shore power load management (HW-13)
- HSR1-25 25A NC relay × 2 — water heater and fridge AC disconnection (HW-18)

**Tanks:**
- Fresh, Grey1, Grey2, Black — exterior sensors on plastic tanks
- Propane — 2 × 30 lb tanks — load cell method

**Water Inlet (Solsante V1.5 subset — club demo):**
- Supply pressure (0–0.6 MPa RS-485 transducer)
- Filter ΔP (0–0.1 MPa pair)
- Flow rate (pulse-output meter)
- Turbidity (Seeed S-DTS210-01 RS-485 Modbus)
- Enclosure temperature (DS18B20)

**Weather:** 433 MHz sensor network via WeeWX + RTL-SDR (dual dongle). WN90LP RS-485 Modbus station (HW-16) ordered — will replace Acurite 5n1 long term.

### 2.6  Waveshare 8-Ch RS485 Gateway

ASIN B0F5WXX4ZQ — 8-port RS-485 to Ethernet, Modbus RTU/TCP, MQTT gateway, industrial isolation, PoE.
**Status: In hand — commissioning next session (HW-01)**

NOTE:  Where ever possible every device mounted in the RV will be accessed by a wired connection.  Wireless esp32Home will be used for controlling minor 
things such as remote lighting and the sdr dongles for use as required. If this requires more than one device per 485 channel 
then so be it.  RS-485 is the interface of choice for this project, IP networks notwithstanding.  

| Port | TCP | Bus / Purpose | Device(s) | Phase |
|---|---|---|---|---|
| RS-485/1 | 4001 | Power — Solar | EPEVER MPPT60 | 3 |
| RS-485/2 | 4002 | Power — Inverter | SAMLUX EVO-2212 | 3 |
| RS-485/3 | 4003 | Power — Grid meter | KWS-303L (grid) | 3 |
| RS-485/4 | 4004 | Power — Generator | KWS-303L (generator) | 3 |
| RS-485/5 | 4005 | Water sensors | Pressure + Filter ΔP + Turbidity | 5 |
| RS-485/6 | 4006 | GNSS | E108-GN03G-485 position/time receiver | 3 |
| RS-485/7 | 4007 | Weather station | WN90LP (HW-16) | 3 |
| RS-485/8 | 4008 | Spare | — | — |

### 2.7  IMU / Compass Module

**Device:** diymore 10-axis IMU — L3GD20 (3-axis gyroscope) + LSM303D (3-axis accelerometer + 3-axis magnetometer). Marketed as "10DOF" with a bundled barometric sensor; effective DOF for RVTC purposes is 9 (gyro + accel + mag).
**Interface:** I²C (IIC) or SPI — will be wired I²C to an ESP32-S3 ESPHome node.
**Status: Ordered 2026-06-12 — HW-17**

**Primary use case — True North heading reference:**
The magnetometer provides a stable heading reference when the RV is stationary. This is the gap the GNSS (HW-10) cannot fill: GNSS course-over-ground is undefined at rest. A reliable heading reference enables:

- **WN90LP wind direction correction** — the WN90LP reports wind direction relative to its own mounting orientation, which changes every time the RV is parked. The IMU heading allows the Phase 7 fusion layer to apply a rotation offset and publish `windDir` referenced to true north regardless of RV orientation.
- **Map orientation correction** — position display pages and dashboards can orient correctly without manual compass input.
- **Sensor fusion anchor** — heading is a first-class field in the Phase 7 normalised MQTT schema.

**Why a standalone magnetometer is viable here:**
The RV has an aluminium trailer frame on a steel chassis. With the sensor mounted ~2 m above the steel frame, the residual magnetic interference is consistent and static — equivalent to the compass-boxing technique used on steel-hulled vessels. A one-time hard-iron calibration (figure-eight rotation, constants baked into ESPHome YAML) removes the fixed offset. The calibration holds indefinitely as long as the mounting position does not change.

**Integration path:**
- ESPHome node (I²C) → MQTT → Phase 7 fusion layer
- ESPHome has native components for both L3GD20 and LSM303D
- Fusion layer consumes raw heading, applies WN90LP mounting offset, publishes `rvtc/sensors/imu/heading` and corrected `rvtc/sensors/weather/windDir_true`
- Calibration offsets stored as constants in ESPHome YAML — not in InfluxDB

**Notes:**
- The gyroscope and accelerometer axes are available for transit shock/vibration logging and RV levelling feedback — secondary use cases, not the primary driver
- The barometric sensor sometimes bundled with this module is superseded by WN90LP (HW-16) — ignore if present
- ESPHome does not include a built-in LSM303D calibration wizard; run a short Python script against raw I²C readings to derive hard-iron offsets, then set as static calibration constants in YAML

### 2.8  - Waveshare Modbus RTU 8-ch Relay — Shore Power Load Management

**Device:** - Waveshare Modbus RTU 8-ch Relay
**Interface:** Ethernet — Modbus TCP. 
**IP:** 192.168.88.6 (reserved in MikroTik DHCP)
**Status: On order — commissioning Phase 3 (HW-13)**

**RVTC use case — shore power load management:**
Three independent shed conditions:

1. **Shore power absent** (KWS-303L grid meter reads zero) → open both relay channels immediately → water heater and fridge revert to LPG
2. **Shore power present, grid current >25A** (KWS-303L grid meter) → open water heater relay → restore when current drops below ~20A. Fridge relay unaffected.
3. **Generator running, generator current >22A** (KWS-303L generator meter) → open water heater relay → restore when current drops below ~18A. Fridge relay unaffected.

```
KWS-303L grid meter (HW-08) + KWS-303L generator meter (HW-09)
  → HA automation (three conditions)
    → - Waveshare Modbus RTU 8-ch Relay (2 relay channels)
      → HSR1-25 relay × 2 (water heater AC, fridge AC)
```

**Channel assignment (to be confirmed at commissioning):**

| Channel | Load | Relay | Normal state |
|---|---|---|---|
| TBD | Water heater AC | HSR1-25 | NC — closed on shore power |
| TBD | Fridge AC | HSR1-25 | NC — closed on shore power |
| 3–16 | Spare | — | Reserved for future use |

**Integration:**
- HA Modbus TCP integration — same pattern as EPEVER/SAMLUX
- Map only the two active coils — leave unused channels unmapped to avoid unnecessary InfluxDB writes
- Modbus register addresses to be recorded at commissioning

**Notes:**
- WiFi must not be configured — Ethernet only per RVTC wired-first policy
- 14 spare relay channels available for future expansion
- Wiegand input register address to be documented at commissioning for future reference

---

## 3  Network

### 3.1  IP Allocation

| IP | Device | Notes |
|---|---|---|
| 192.168.88.1 | MikroTik gateway | Primary router |
| 192.168.88.2 | Windows workstation | SSH client |
| 192.168.88.3 | Beelink J45 (enp1s0) | All services — primary IP |
| 192.168.88.4 | J45 WiFi (wlp3s0) | Disabled — autoconnect=no, radio off |
| 192.168.88.5 | Waveshare RS-485 gateway | Pending commissioning |
| 192.168.88.6 | - Waveshare Modbus RTU 8-ch Relay | Ethernet Modbus TCP — load management |

### 3.2  Pi-hole DNS (.lan records)

All local DNS records use `.lan` TLD. The `.local` TLD was abandoned due to mDNS/Avahi conflicts.
**Always use `http://` prefix** — bare `.lan` names are intercepted as search queries.

| Domain | IP | Notes |
|---|---|---|
| weewx.lan | 192.168.88.3 | nginx reverse proxy — Belchertown skin |
| grafana.lan | 192.168.88.3 | nginx reverse proxy |
| influxdb.lan | 192.168.88.3 | nginx reverse proxy |
| homeassistant.lan | 192.168.88.3 | nginx reverse proxy |
| pihole.lan | 192.168.88.3 | nginx reverse proxy (no password) |

### 3.3  Web UIs

| Service | Internal URL | Notes |
|---|---|---|
| WeeWX | http://weewx.lan | Belchertown skin (dark mode) |
| Grafana | http://grafana.lan | Dashboard needs rebuilding (OI-16) |
| InfluxDB | http://influxdb.lan | |
| Home Assistant | http://homeassistant.lan | Onboarding not yet complete (OI-15) |
| Pi-hole | http://pihole.lan | |
| WeeWX (club LAN) | http://wifi.solsante.com:8080 | via club router + MikroTik dst-nat |

### 3.4  MikroTik Router

Config file: `config/rv-mikrotik-config.rsc` (updated 2026-06-09, ether8 + pinhole fixes)
DNS: Primary 192.168.88.3 (Pi-hole), secondary 8.8.8.8. DHCP hands Pi-hole IP to all clients.

**External WeeWX access path:**
```
wifi.solsante.com:8080 → club router → MikroTik rogers-wan:80 → dst-nat → 192.168.88.3:80 → nginx → WeeWX
```

> **NOTE:** New RSC (ether8 + pinhole fixes) committed but not yet loaded onto physical router — install and test at next visit.

---

## 4  Docker Stack

> **CRITICAL:** Always run `docker compose up/down` from `~/RV-total-control/` — this is the canonical compose file location. Running from `/data/docker/volumes/` puts containers on the wrong network (`volumes_default` instead of `rvtc_net`) and breaks inter-container DNS.

**Docker network:** `rvtc_net`
**Compose file:** `~/RV-total-control/docker-compose.yml`

### 4.1  Running Containers

| Container | Image | Port(s) | Volume / Notes |
|---|---|---|---|
| mosquitto | eclipse-mosquitto | 1883 | /data/docker/volumes/mosquitto |
| influxdb | influxdb:2 | 8086 | /data/docker/volumes/influxdb |
| grafana | grafana/grafana | 3000 | /data/docker/volumes/grafana — user: 472:472 |
| rtl433 | hertzg/rtl_433:latest | — | SN 1024 (Blog V3) — primary |
| rtl433b | hertzg/rtl_433:latest | — | SN 00000001 (clone) — secondary |
| weewx | felddy/weewx | — | /data/docker/volumes/weewx |
| nginx | nginx:alpine | 80 | weewx public_html (ro) + nginx.conf |
| homeassistant | ghcr.io/home-assistant/home-assistant | 8123 | /data/docker/volumes/homeassistant |
| pihole | pihole/pihole | 8880 (web), 53 (DNS) | /data/docker/volumes/pihole — listeningMode=all |

### 4.2  rtl_433 Container Configuration

```yaml
rtl433:
  image: hertzg/rtl_433:latest
  container_name: rtl433
  restart: unless-stopped
  devices:
    - /dev/bus/usb:/dev/bus/usb
  command: ["-M", "si", "-d", "1024", "-F", "mqtt://mosquitto:1883,retain=1,events=rtl_433/rtl433/events"]
  depends_on:
    - mosquitto

rtl433b:
  image: hertzg/rtl_433:latest
  container_name: rtl433b
  restart: unless-stopped
  devices:
    - /dev/bus/usb:/dev/bus/usb
  command: ["-M", "si", "-d", "00000001", "-F", "mqtt://mosquitto:1883,retain=1,events=rtl_433/rtl433b/events"]
  depends_on:
    - mosquitto
```

- WeeWX subscribes to `rtl_433/+/events` — wildcard receives from both containers
- Both containers decode the same sensors — duplicate packets to WeeWX are benign; deduplication is a Phase 7 concern
- `+` wildcard is valid in MQTT subscribe but **not** in publish topics
- `-M si` does not convert Acurite 5n1 field names — they always publish `temperature_F` and `rain_in`

### 4.3  Grafana Notes

- Dashboard lost after reboot 2026-06-09 due to volume permissions issue
- Fix applied: `user: "472:472"` in docker-compose.yml
- If dashboard missing after restart: `sudo chown -R 472:472 /data/docker/volumes/grafana`
- Dashboard still needs rebuilding (OI-16)

---

## 5  WeeWX Configuration

### 5.1  Key Settings

| Setting | Value |
|---|---|
| Config (host) | /data/docker/volumes/weewx/weewx.conf |
| Config (container) | /data/weewx.conf |
| Management | Manual on host — copy committed to config/weewx.conf in repo |
| Driver | MQTTSubscribeDriver — subscribes to rtl_433/+/events |
| Station | ve7cbh, 48.6686N, 123.6002W, 46m |
| Units | METRICWX (°C, mm, m/s) via StdConvert target_unit = METRICWX |
| Archive interval | 2.5 min (150 seconds) |
| Time zone | America/Vancouver |
| Skin | Belchertown (dark mode) — output at /data/public_html/belchertown |
| InfluxDB writer | Custom influxdb2.py at /data/docker/volumes/weewx/bin/user/ |
| InfluxDB target | host=influxdb, org=rvtc, bucket=rvtc, measurement=weewx |
| PyEphem | Installed — civil twilight and extended celestial data available |
| ID filter | filter_out_message_when = 291 (excludes Port Renfrew unit) |

### 5.2  Field Mappings (MQTTSubscribeDriver)

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
    units = inch
    contains_total = true     # CRITICAL — Acurite 5n1 sends cumulative bucket counts
```

> **CRITICAL:** `contains_total = true` is essential for rain. Without it every cumulative reading adds to the total, producing phantom rain accumulation. The ID filter (`filter_out_message_when = 291`) is set but not yet tested under live rain conditions.

### 5.3  Database

```
Archive DB (host): /data/docker/volumes/weewx/archive/weewx.sdb
sqlite3 is on the host — not inside the WeeWX container
```

**Useful queries:**
```bash
# Recent archive records
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime,'unixepoch','localtime') as ts, rain, rainRate FROM archive ORDER BY dateTime DESC LIMIT 20;"

# Daily rain summary
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime,'unixepoch','localtime') as ts, sum, max, count FROM archive_day_rain ORDER BY dateTime DESC LIMIT 14;"
```

**Rebuild daily summaries after archive edits:**
```bash
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=YYYY-MM-DD --yes
```

> **NOTE:** InfluxDB bucket flushed 2026-06-03 — clean metric data from ~15:35 UTC onward only. WeeWX SQLite archive retains full history.

### 5.4  Known WeeWX Issues

- **OI-32:** Upstream bug — `contains_total=true` + hardware fault → corrupted archive_day_rain → silent stats failure. Bug report pending.
- **HW-14:** Rain gauge physical inspection at club still required.
- ID filter (`filter_out_message_when = 291`) not yet tested under live rain conditions.

---

## 6  Ansible & Repository

### 6.1  Configuration Files

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

### 6.2  group_vars / host_vars

- `group_vars/all/all.yml` — all non-sensitive variables
- `group_vars/all/vault.yml` — ansible-vault encrypted, contains:
  - vault_influxdb_user / vault_influxdb_password
  - vault_grafana_user / vault_grafana_password
  - vault_pihole_user / vault_pihole_password
  - vault_influxdb_token
- `host_vars/localhost.yml` — J45-specific overrides
  - **NOTE:** filename must match inventory hostname (`localhost`, not `rvtc` or `ve7cbh-control`)

### 6.3  Roles

| Role | Purpose / Notes |
|---|---|
| common | OS baseline, Docker idempotency, UFW firewall, WiFi disable, dvb_usb blacklist, rtl-sdr + sqlite3 |
| mosquitto | Eclipse Mosquitto MQTT broker |
| influxdb | InfluxDB 2.x time-series database |
| grafana | Grafana dashboards — user 472:472 baked in |
| rtl433 | rtl_433 containers — primary and secondary dongle setup |
| weewx | WeeWX weather engine — weewx.conf managed manually on host |
| nginx | Reverse proxy for all .lan domains |
| homeassistant | Home Assistant — onboarding and MQTT integration pending (OI-15) |
| pihole | Pi-hole DNS — listeningMode=all required |

### 6.4  Repository Structure

```
RV-total-control/
├── ansible.cfg
├── config/
│   ├── Mikrotik Failover.md
│   ├── nginx.conf                       # committed 2026-06-09
│   ├── rv-mikrotik-config.rsc           # updated 2026-06-09
│   ├── rv-mikrotik-config_ether8_fix.rsc
│   ├── rvtc-ambient.yml
│   ├── temp_press_flash.yml
│   └── weewx.conf                       # committed 2026-06-09
├── docker-compose.yml                   # canonical — always run from here
├── docs/
│   └── [session context and summary files]
├── group_vars/all/
│   ├── all.yml
│   └── vault.yml
├── host_vars/
│   └── localhost.yml
├── inventories/production/
│   └── hosts.ini
├── roles/
│   ├── common/
│   ├── mosquitto/
│   ├── influxdb/
│   ├── grafana/
│   ├── rtl433/
│   ├── weewx/
│   ├── nginx/
│   ├── homeassistant/
│   └── pihole/
├── phase2.yml
├── site.yml
└── README.md
```

### 6.5  Key Paths

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root — **always run docker compose from here** |
| `~/RV-total-control/docker-compose.yml` | Canonical compose file |
| `~/.vault_pass` | Ansible Vault password — chmod 600, never committed |
| `/data/docker/volumes` | All Docker volume data |
| `/data/docker/volumes/weewx/weewx.conf` | WeeWX live config |
| `/data/docker/volumes/weewx/bin/user/influxdb2.py` | Custom InfluxDB writer |
| `/data/docker/volumes/weewx/archive/weewx.sdb` | WeeWX SQLite archive |
| `/data/docker/volumes/grafana` | Grafana data — must be owned 472:472 |
| `/etc/udev/rules.d/99-rtlsdr.rules` | RTL-SDR udev rules (MODE=0666 override) |
| `/etc/modprobe.d/rtlsdr.conf` | dvb_usb_rtl28xxu blacklist |
| `/etc/apt/sources.list.d/docker.list` | Docker repo — trixie hardcoded (not gigi) |

### 6.6  Known Issues

- **LMDE Docker repo:** `$VERSION_CODENAME` returns `gigi` on LMDE — docker.list must hardcode `trixie`
- **GitHub auth:** PAT stored in `~/.git-credentials` via credential.helper store
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`
- **weewx.conf:** Managed manually on host. Edit directly and `docker restart weewx`
- **SAMLUX register map:** Full Modbus register map held locally under NDA — never paste into chat or commit to repo

---

## 7  Open Items & Backlog

### 7.1  Software / Configuration

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| OI-15 | 2-3 | Home Assistant onboarding | 🟡 Open | Container up — setup wizard + MQTT integration not done |
| OI-16 | 2 | Grafana weather dashboard | 🟡 Open | Lost after reboot 2026-06-09 — needs rebuilding |
| OI-18 | 3 | ESPHome Ansible role | 🟡 Open | nginx block in place; role to be created |
| OI-19 | 2-3 | MQTT Explorer | 🟡 Open | May be superseded by Phase 7 fusion UI |
| OI-20 | 3 | HA multi-site linking | 🟡 Open | VPN prerequisite |
| OI-21 | 3+ | VOIP / PBX inter-site | 🟡 Open | Prerequisite: OI-20 |
| OI-24 | 3 | Shore power load management — water heater + fridge AC shed | 🟡 Open | Three conditions: (1) shore power absent → shed both immediately; (2) shore power present, grid current >25A → shed water heater, restore <20A; (3) generator running, generator current >22A → shed water heater, restore <18A. Current feedback from KWS-303L grid (HW-08) and generator (HW-09). Prerequisites: HW-08, HW-09, HW-13, HW-18 |
| OI-25 | 7 | Phase 7 Sensor Fusion | 🟡 Open | Python fusion service, normalised MQTT schema |
| OI-29 | 3 | GNSS-driven WeeWX position | 🟡 Open | Prerequisite: HW-10 |
| OI-30 | 3 | RV position display page | 🟡 Open | Prerequisite: HW-10, Phase 7 |
| OI-32 | — | WeeWX upstream bug report | 🟡 Open | contains_total=true + hardware fault → silent rain stats failure |
| OI-33 | 3 | Club bridge Pi | 🟡 Open | rtl_433 + WireGuard at club → home J45 hub; prereq: OI-20 |
| OI-34 | 7 | GNSS geofence source inhibit | 🟡 Open | Suppress RV 5n1 when at club; prereq: HW-10, OI-33, Phase 7 |
| OI-35 | 7 | Make weewx webpage dynamicly update.  Requires mqtt websockets enabled in mosquitto broker |🟡 Open |
| OI-36 | 7 | WN90LP wind direction true-north correction pipeline | 🟡 Open | IMU (HW-17) heading → Phase 7 fusion layer → rotation offset applied to WN90LP raw windDir → publish corrected `rvtc/sensors/weather/windDir_true`; prerequisite: HW-17 commissioned, Phase 7 fusion layer |

### 7.2  Hardware / Physical Install

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| HW-01 | 3 | Install Waveshare RS485 gateway | 🟡 Open | **IN HAND** — commissioning next session |
| HW-02 | 3 | Build RS-485 cables | 🟡 Open | For SAMLUX EVO-2212 + EPEVER MPPT |
| HW-03 | 3 | Install 4×100W PV panels | 🟡 Open | Get solar data flowing before full array |
| HW-04 | 3 | Wire 9 PV panels (3S×3P ~36V) | 🟡 Open | Complete solar system |
| HW-05 | 3/5 | Source barometric pressure sensor | ✅ Closed | Covered by WN90LP (HW-16) |
| HW-06 | 5 | Build ESP32 sensor node | 🟡 Open | Pulse water meter, turbidity, pressure ×2, flow |
| HW-07 | 4/5 | Design tank monitoring sensors | 🟡 Open | Sensor types and mounting TBD |
| HW-08 | 3 | Source/install KWS-303L — grid | 🟡 Open | AC power meter, grid input; RS-485 port 3 |
| HW-09 | 3 | Source/install KWS-303L — generator | 🟡 Open | AC power meter, generator input; RS-485 port 4 |
| HW-10 | 3 | Install GNSS E108-GN03G-485 | 🟡 Open | RS485, IP67; Waveshare port 6 (TCP 4006) |
| HW-12 | — | Replace spare Acurite 5n1 | 🟡 Open | Spare confirmed DOA 2026-06-02 |
| HW-13 | 3 | DT-R016 Ethernet Modbus TCP relay controller — shore power load management | 🟡 Open | **IN HAND** — 16-ch, Ethernet Modbus TCP (WiFi disabled), Wiegand D0/D1 input; 2 channels drive HSR1-25 relays (HW-18); prerequisite for OI-24 |
| HW-14 | — | Rain gauge inspection/repair | 🟡 Open | Physical inspection at club required |
| HW-15 | 3 | Install POE-SW802-DIN PoE switch | 🟡 Open | Powers Waveshare gateway and bay devices |
| HW-16 | 3 | Ecowitt WN90LP RS-485 Modbus weather station | 🟡 Open | **Ordered 2026-06-10, ships after June 15** — ultrasonic wind, temp, humidity, rain, UV, light, barometric pressure — Waveshare RS-485/7 (TCP 4007) — closes HW-05 |
| HW-17 | 3/7 | diymore 10-axis IMU (L3GD20 + LSM303D) | 🟡 Open | **Ordered 2026-06-12** — magnetometer heading reference for true-north wind direction correction and map orientation; I²C to ESP32-S3 ESPHome node; one-time hard-iron calibration required; Phase 7 fusion layer consumer |
| HW-18 | 3 | Install HSR1-25 25A NC relay × 2 — water heater AC and fridge AC | 🟡 Open | **Ordered 2026-06-13** — normally closed; activated on: (1) shore power absent, (2) grid current >25A, or (3) generator current >22A; driven by DT-R016 (HW-13); current feedback from KWS-303L grid (HW-08) and generator (HW-09) |

### 7.3  Design / Documentation

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| DD-01 | 3 | System wiring drawing | 🟡 Open | Full system diagram |
| DD-02 | 5 | ESP32 sensor node scope definition | 🟡 Open | Sensor types TBD |
| DD-03 | 7 | Phase 7 sensor fusion architecture document | 🟡 Open | Topic schema, source types, staleness model |

---

## 8  Session Log

### 2026-05-27
Full Phase 2 scaffolding complete. Ansible common role live. `group_vars/all`, `host_vars/localhost`, `site.yml` all created and tested.

### 2026-05-28
Full core stack deployed: Mosquitto, InfluxDB, Grafana, rtl_433, WeeWX, nginx, Home Assistant, Pi-hole. Acurite 5n1 (ID 1111) live via rtl_433 → MQTT → WeeWX. Full data chain confirmed.

### 2026-05-29
WeeWX → InfluxDB integration working. nginx reverse proxy live with all .lan domains. Pi-hole DNS operational. MikroTik pinhole configured for external WeeWX access. Grafana RVTC Weather dashboard built.

### 2026-05-30
Backlog formalised. ESPHome ambient sensor YAML built. Grafana dashboard constructed. Seasons skin CSS cosmetic fix (OI-14 ✅).

### 2026-05-31
Waveshare RS485 gateway ordered. mosquitto-clients installed. dvb_usb_rtl28xxu conflict and WiFi IP conflict diagnosed. Steve departing for Port Renfrew.

### 2026-06-02  (Port Renfrew — Starlink)
Stack confirmed fully live from campsite. Mobile Acurite 5n1 (ID 291, Channel C) decoding. Phase 7 Sensor Fusion architecture scoped.

### 2026-06-03  (Port Renfrew — Starlink)
influxdb2.py unit conversion fix (was writing Fahrenheit as Celsius). InfluxDB bucket flushed for clean data restart. Rain sensor disabled pending investigation.

### 2026-06-05  (Port Renfrew — Starlink)
Rain sensor cumulative fix: `contains_total = true` applied. Root cause confirmed — Acurite 5n1 sends cumulative bucket counts, not incremental rain. Phantom rain accumulation eliminated.

### 2026-06-07  (Port Renfrew — Starlink)
sqlite3 installed on host. archive_day_rain corruption diagnosed and fixed (rebuild-daily). Local DNS migrated `.local` → `.lan` across all configs. Avahi/mDNS conflict with `.local` confirmed as root cause.

### 2026-06-09  (Home base — Rogers)
- Returned from Port Renfrew — trailering caused WeeWX data gap
- Full WeeWX/rtl_433 diagnosis: four simultaneous bugs found — wrong compose directory (network isolation), hardcoded USB path, invalid MQTT publish topic (`+` wildcard), wrong field name mappings (`temperature_C`/`rain_mm` → actual `temperature_F`/`rain_in`)
- RTL-SDR Blog V3 (HW-11) received — antenna missing, could not commission
- Old clone dongle confirmed working as temporary primary
- dvb_usb_rtl28xxu blacklist applied and baked into Ansible common role (OI-23 ✅)
- OI-22, OI-23, OI-26, OI-27, OI-17, OI-28, OI-31 all closed ✅
- Belchertown skin installed with dark mode; PyEphem active
- Grafana user permissions fix applied (472:472 in compose)
- MikroTik RSC updated (ether8 + pinhole fixes)
- **Phase 2 complete — Phase 3 active**

### 2026-06-10  (Home base — Rogers)
- RTL-SDR Blog V3 (SN 1024, R820T): antenna fitted, confirmed on Windows, swapped into J45 as primary dongle
- Clone (SN 00000001, R828D) retained and commissioned as secondary — rtl433b container added to docker-compose.yml
- Key finding: clone contains R828D tuner (higher spec than assumed); confirmed with `rtl_eeprom`
- Both containers pin by serial via `-d` flag
- Dual dongle confirmed: both decoding Acurite 5n1 ID 1111 independently; duplicate packets benign
- Grafana wind speed chart confirms dual dongle improvement — data density visibly doubles from ~08:00 onward
- docker-compose.yml committed and pushed (85b7357)
- OI-33 added: Club bridge Pi (rtl_433 + WireGuard → home J45 hub)
- OI-34 added: GNSS geofence source inhibit
- Club bridge topology agreed: club Pi → home J45 only; RV always subscribes to home hub
- **WN90LP RS-485 Modbus weather station ordered (HW-16)** — ultrasonic anemometer + piezoelectric rain + barometric pressure + temp/humidity/UV/light — Waveshare RS-485/7 — closes HW-05

### 2026-06-12  (Home base — Rogers)
- IMU module ordered (HW-17): diymore 10-axis L3GD20 + LSM303D — C$10.18
- Primary use case: magnetometer heading reference for true-north wind direction correction on WN90LP (HW-16)
- Secondary use cases: transit shock logging, levelling feedback
- Integration path agreed: I²C → ESP32-S3 ESPHome node → MQTT → Phase 7 fusion layer applies rotation offset to WN90LP windDir → publishes `rvtc/sensors/weather/windDir_true`
- Compass-boxing argument validated: ~2 m standoff above steel chassis on aluminium frame; one-time hard-iron calibration sufficient
- OI-36 added: WN90LP wind direction true-north correction pipeline (prerequisite: HW-17 + Phase 7 fusion)
- Section 2.7 added to project reference documenting IMU hardware and integration rationale

### 2026-06-13  (Home base — Rogers)
- DT-R016 16-channel Ethernet Modbus TCP relay controller reviewed and scoped for RVTC
- Confirmed: Ethernet Modbus TCP interface — WiFi present but will not be configured (wired-first policy)
- Confirmed: Wiegand D0/D1 input terminals present; card UID readable via Modbus holding register — reserved for future use
- Confirmed: previously tested on home HA instance — Modbus register map known
- Load shedding scope defined: shore power presence/absence (KWS-303L) drives two relay channels via binary HA automation — water heater and fridge revert to LPG when shore power absent
- HSR1-25 25A NC relay × 2 ordered (HW-18) — one per load
- HW-13 updated: scope is now DT-R016 commission + 2-channel load shed integration
- OI-24 updated: simplified to binary shore-power-loss automation; no threshold management
- Section 2.8 added: DT-R016 hardware and integration documentation
- Section 2.5 updated: DT-R016 and HSR1-25 added to monitored/controlled systems list

### Next Session — Phase 3 Priorities
1. Waveshare RS-485 gateway commissioning (HW-01 — device in hand)
2. EPEVER MPPT60 Modbus integration (RS-485/1, TCP 4001)
3. SAMLUX EVO-2212 Modbus integration (RS-485/2, TCP 4002)
4. Solar panel wiring (HW-03 / HW-04)
5. Home Assistant onboarding — MQTT integration (OI-15)
6. Rebuild Grafana dashboard (OI-16)
7. WeeWX upstream bug report (OI-32)
8. WN90LP commissioning when received (HW-16 — ships after June 15)
9. - Waveshare Modbus RTU 8-ch Relay — record Modbus coil addresses for load relay channels(HW-13)

---

## 9  Architecture Notes

### 9.1  Phase 7 — Sensor Fusion

A normalised MQTT sensor bus with a fusion/arbitration layer that assigns the best available source to each logical field, with configurable priority ordering and automatic fallback when a source goes stale.

**Planned source types:**
- RTL-SDR (dual dongles SN 1024 + SN 00000001) — independent receivers, same 433 MHz sensors
- ESPHome nodes — publish directly to MQTT
- Modbus devices via Waveshare gateway — EPEVER, SAMLUX, KWS-303L, water sensors
- GNSS receiver (HW-10, E108-GN03G-485)
- IMU / magnetometer (HW-17, L3GD20 + LSM303D) — heading reference for wind direction true-north correction and map orientation
- External APIs — e.g. Environment Canada as fallback weather source

**Key design decisions to resolve:**
1. Normalised MQTT topic schema — proposed: `rvtc/sensors/{source_id}/{field}`
2. Staleness timeout — will differ by source type
3. Sanity checking — e.g. reject outTemp = 80°C
4. UI approach — live source discovery, per-field priority assignment
5. Implementation — Python fusion service (new container + Flask API)
6. Duplicate packet handling — deduplicate by (sensor_id, timestamp); arbitrate by signal quality or source priority

**Consumers:** WeeWX (via fused MQTT topic), Home Assistant, Grafana.

### 9.2  Club Bridge Topology (OI-33 / OI-34)

- Small always-on Pi at Solsante Club: rtl_433 + WireGuard
- Pi connects to home J45 only — never directly to RV
- Home J45 Mosquitto is the hub — RV subscribes to home regardless of location
- When RV is at club: GNSS geofence (OI-34) detects position match → fusion layer suppresses RV 5n1 (ID 1111) → club station becomes authoritative source
- When RV is remote: club bridge feeds weather data to home J45 → forwarded to RV via VLAN
- Reuses OI-20 VPN infrastructure (WireGuard). Prerequisite: HW-10

### 9.3  Engineering Standards & Design Philosophy

The RV Total Control (RVTC) architecture rejects fragile consumer electronics conventions in favour of industrial-grade and marine-grade robustness. Because no single engineering standard covers a mobile, containerized smart environment, RVTC draws from proven frameworks across the automation, maritime, and automotive industries:

- **Signal Integrity & Noise Immunity:** Long analog sensor runs use 4–20 mA current loops consistent with industrial process instrumentation practice (ref. IEC 60381-1). Digital sensor buses utilize EIA-485 (RS-485 Modbus RTU) differential signalling. All signal lines use twisted-pair shielded cabling to mitigate electromagnetic interference (EMI).
- **Electrical Safety & Grounding:** The power and grounding architecture follows marine and RV industry best practice (ref. ABYC E-11, NFPA 1192) — single-point grounding at all enclosures to eliminate ground loops and prevent galvanic corrosion.
- **Environmental Ruggedness:** Equipment placement and enclosure selection account for the thermal cycling, shock, and vibration demands of a mobile vehicle environment operating off-grid (ref. SAE J1455).
- **Data & Software Architecture:** Telemetry transport uses ISO/IEC 20922 (MQTT), feeding a decoupled, containerized data pipeline (InfluxDB/Grafana) that mirrors the functional layering principles of industrial automation systems (ref. ISA-95).

These cross-disciplinary design principles ensure the system remains resilient against the harsh electrical noise, vibration, and environmental demands of extended off-grid travel.

> **Note:** RVTC is a private build and does not claim conformance or certification against any of the referenced standards. IEC 60381-1, ABYC E-11, NFPA 1192, SAE J1455, and ISA-95 are cited as engineering guidance and design benchmarks only.
