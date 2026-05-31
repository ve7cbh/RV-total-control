# RVTC Session Context Document
**Last Updated:** May 31, 2026 (evening)
**Purpose:** Feed this to Claude at the start of each session to restore project context instantly.

---

## Project Identity

| Item | Value |
|---|---|
| Project | RV Total Control (RVTC) |
| Owner | Steve Bradshaw (ve7cbh) |
| GitHub | https://github.com/ve7cbh/RV-total-control |
| Status | Phase 2 Complete — Phase 3 Planning Next |

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
| RTL-SDR | RTL2838 DVB-T — Bus 001 Device 007 — 433 MHz weather reception |

---

## Software Installed on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |
| rtl-433 | Latest (also in Docker container) |
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
│   └── RVTC_Session_Context_20260529.md
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

**Known issue:** Seasons skin CSS not loading correctly when browsed via nginx reverse proxy. Data is correct, cosmetic issue only.

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
**Station:** Acurite 5n1, ID 1111, Channel A  
**MQTT topic:** `rtl_433/<id>/events` (JSON)  
**SI units:** temperature_C, wind_avg_km_h, rain_mm  

---

## InfluxDB

**Version:** 2.x  
**Org:** rvtc  
**Bucket:** rvtc  
**Token:** stored in vault as `vault_influxdb_token`  
**Admin user:** ve7cbh  
**Data:** WeeWX weather archive records, measurement=weewx  

---

## Network Allocation

| IP | Device | Interface |
|---|---|---|
| 192.168.88.1 | MikroTik gateway | — |
| 192.168.88.2 | Windows workstation | — |
| 192.168.88.3 | Beelink J45 — ethernet (primary) | enp1s0 |
| 192.168.88.4 | J45 WiFi interface — disabled autoconnect | wlp3s0 |
| 192.168.88.5 | HF5142B Modbus gateway | — |

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
| RS-485/6 | 4006 | Spare | — | — |
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

---

## Open Items / Backlog

### Software / Configuration

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| OI-14 | WeeWX Seasons skin CSS | 2 | ✅ Complete | Not loading via nginx reverse proxy — cosmetic only | Fixed 29/5
| OI-15 | Home Assistant onboarding | 2/3 | 🟡 Open | Setup wizard + MQTT integration — pending hardware mount |
| OI-16 | Grafana weather dashboard | 2 | ✅ Complete | Built 2026-05-30 — cleanup items remain (legends, °F, auto-refresh) |
| OI-17 | Ansible weewx role cleanup | 2 | 🟡 Open | Template approach abandoned — role needs rethink for idempotency |
| OI-18 | ESPHome Ansible role | 3 | 🟡 Open | nginx block already in place; role to be created |
| OI-19 | MQTT Explorer | 2/3 | 🟡 Open | Install in HA or standalone; TBD which tool |
| OI-20 | HA multi-site linking | 3 | 🟡 Open | Make Homelan HA and RV HA visible to each other |

### Hardware / Physical Install

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| HW-01 | Install Waveshare 8-Ch RS485 gateway | 3 | 🟡 Open | Replaces HF5142B — 8-port RS-485→Ethernet, industrial isolation, PoE; IP 192.168.88.5 already allocated |
| HW-02 | Build RS-485 cables | 3 | 🟡 Open | For SAMLUX EVO-2212 and EPEVER MPPT controller |
| HW-03 | Install 4×100W PV panels | 3 | 🟡 Open | Get solar data flowing before full array |
| HW-04 | Wire 9 PV panels (3S×3P, ~36V) | 3 | 🟡 Open | Complete solar system for data collection |
| HW-05 | Source barometric pressure sensor | 3/5 | 🟡 Open | For ESP32 sensor node |
| HW-06 | Build ESP32 sensor node | 5 | 🟡 Open | Pulse water meter, turbidity, pressure ×2, flow — scope TBD |
| HW-07 | Design tank monitoring sensors | 4/5 | 🟡 Open | Sensor types and mounting TBD |
| HW-08 | Source/install KWS-303L — grid | 3 | 🟡 Open | AC power meter, grid input; RS-485 Modbus to gateway port 3 |
| HW-09 | Source/install KWS-303L — generator | 3 | 🟡 Open | AC power meter, generator input; RS-485 Modbus to gateway port 4 |
| HW-10 | Install GNSS BDS/GPS/GLONASS RS485 Multimode Satellite Rx | 3 | 🟡 | 
| HW-11 | Configure and install CC1101 Wireless Module | 3 | 🟡 | to replace RTL-433 dongle prone to vibration failures in mobile appliations

### Design / Documentation

| ID | Item | Phase | Status | Notes |
|---|---|---|---|---|
| DD-01 | System wiring drawing | 3 | 🟡 Open | Full system diagram with wire lists and hardware lists |
| DD-02 | ESP32 sensor node scope definition | 5 | 🟡 Open | Decide which sensors to include: water meter pulse, turbidity, pressure ×2, flow |

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

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo uses `trixie` hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE.
- **GitHub auth:** PAT in `~/.git-credentials` via credential.helper store.
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`.
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`.
- **weewx.conf:** Managed manually on host at `/data/docker/volumes/weewx/weewx.conf`. Ansible template approach was abandoned — too many overwrites corrupted the config. Edit directly and `docker restart weewx`.
- **Pi-hole listeningMode:** Must be `all` — set via `FTLCONF_dns_listeningMode: "all"` env var in Ansible role. Default `local` rejects queries from outside Docker bridge subnet.
- **SAMLUX register map:** Full Modbus register map held locally under NDA. Never paste into chat.
- **InfluxDB token:** Stored in vault as `vault_influxdb_token`. Also in weewx.conf in plaintext (private network, acceptable).
- **WiFi autoconnect disabled:** wlp3s0 (Auto VE7CBH_Mikrotik + solsante profiles) set to autoconnect=no. Was causing IP conflict with enp1s0 (.3) on startup. WiFi disabled via `nmcli radio wifi off`. Ansible role needed to make this permanent — TODO next session.

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
- dvb_usb_rtl28xxu kernel module conflict diagnosed — blacklist pending Ansible role update
- WiFi IP conflict diagnosed: wlp3s0 was grabbing 192.168.88.3 on startup — autoconnect disabled on both WiFi profiles; `nmcli radio wifi off` applied. Ansible role needed to make permanent.
- Steve taking RV to Port Renfrew — project resumes over Starlink from campsite

**Next session:** WiFi autoconnect fix in Ansible (common role), dvb_usb_rtl28xxu blacklist in Ansible, Home Assistant onboarding (OI-15), ESPHome Ansible role (OI-18), Grafana dashboard cleanup, Phase 3 planning.
