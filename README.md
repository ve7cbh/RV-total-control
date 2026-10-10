# RV Total Control (RVTC)

**Author:** Steve Bradshaw (ve7cbh) — Nanaimo, BC  
**Status:** Phase 3 Active — Power Integration  
**Last Updated:** June 24, 2026  
**Host:** `http://rvtc.lan` · `http://weewx.lan` · `http://grafana.lan`

---

## Overview

RV Total Control is an integrated monitoring, control, and data-collection platform for a
recreational vehicle. The system runs on a Beelink J45 mini-PC (Linux Mint LMDE) with all
services containerised under Docker Compose and deployed via Ansible. A Waveshare 8-port
RS-485 gateway connects the J45 to all field devices over wired RS-485 Modbus — WiFi is
used only for devices where RS-485 is impractical.

The project draws on industrial, marine, and automotive engineering practice for signal
integrity, grounding, and data architecture. See `docs/` for the full architecture and
design documents.

---

## Phase Status

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

## What's Running

| Service | URL | Notes |
|---|---|---|
| RVTC dashboard | http://rvtc.lan | Unified monitoring — Solar, Battery, Power, Weather tabs |
| Grafana | http://grafana.lan | Solar dashboard live; weather dashboard pending rebuild |
| WeeWX | http://weewx.lan | Belchertown skin, dark mode — Acurite 5n1 via RTL-SDR |
| InfluxDB | http://influxdb.lan | Bucket: rvtc — weewx + solar measurements |
| Home Assistant | http://homeassistant.lan | Onboarding pending (OI-15) |
| Pi-hole | http://pihole.lan | DNS for all .lan domains |

---

## Hardware

### Control Node

| Item | Specification |
|---|---|
| Host | Beelink J45 |
| CPU | Intel Pentium J4205 (4-core) |
| RAM | 8 GB |
| Root drive | /dev/sda — 256 GB — mounted / |
| Data drive | /dev/sdb — 640 GB — mounted /data |
| OS | Linux Mint LMDE (Debian trixie base) |
| Hostname | ve7cbh-control |
| IP | 192.168.88.3 (ethernet) — WiFi disabled |

### RS-485 Gateway

Waveshare 8-port RS-485 to Ethernet gateway (ASIN B0F5WXX4ZQ). All channels answer
Modbus TCP on **port 4001**, distinguished by IP only (192.168.88.5–12).

| Port | IP | Device | Status |
|---|---|---|---|
| RS-485/1 | 192.168.88.5 | EPEVER MPPT60 solar charge controller | ✅ Live |
| RS-485/2 | 192.168.88.6 | SAMLUX EVO-2212 inverter-charger | ✅ Commissioned |
| RS-485/3 | 192.168.88.7 | KWS-303L grid meter (slave 1) + generator (slave 2) | 🔄 Grid live |
| RS-485/4 | 192.168.88.8 | ESP32-S3 Touch LCD thermostat panel (HW-20) | ⏳ Cable pending |
| RS-485/5 | 192.168.88.9 | Water sensors — pressure, flow, turbidity | ⏳ Phase 5 |
| RS-485/6 | 192.168.88.10 | GNSS E108-GN03G-485 | ⏳ Pending install |
| RS-485/7 | 192.168.88.11 | Ecowitt WN90LP weather station | ⏳ In transit |
| RS-485/8 | 192.168.88.12 | Waveshare 8-ch relay board — load management | ✅ Commissioned |

### Field Devices

| Device | Interface | Purpose |
|---|---|---|
| EPEVER MPPT60 | RS-485/1 Modbus RTU, slave 2, 115200 baud | Solar charge controller |
| SAMLUX EVO-2212 | RS-485/2 Modbus RTU, slave 1, 9600 baud | Inverter-charger (online UPS) |
| KWS-303L × 2 | RS-485/3 Modbus RTU, slaves 1+2, Even parity | AC power meters — grid + generator |
| Waveshare relay board | RS-485/8 Modbus RTU, slave 1 | 8-ch load management + BMS interface |
| HSR1-25 × 2 | Relay board coils 1+2 | Water heater AC + fridge AC (NO, 25A) |
| RTL-SDR Blog V3 | USB (SN 1024) | Primary 433 MHz receiver |
| RTL-SDR clone | USB (SN 00000001) | Secondary 433 MHz receiver |
| Acurite 5n1 (ID 1111) | 433 MHz | Home base weather station |
| Ecowitt WN90LP | RS-485/7 | RS-485 Modbus weather station (in transit) |
| diymore IMU (L3GD20 + LSM303D) | I²C → ESP32-S3 | Heading reference for wind direction correction |
| GNSS E108-GN03G-485 | RS-485/6 | Position and time |
| ESP32-S3 Touch LCD 4.3 | RS-485/4 via DMX cable | Thermostat replacement (HW-20) |

---

## Docker Stack

All containers run on network `rvtc_net` from `~/RV-total-control/docker-compose.yml`.
**Always run `docker compose` from this directory.**

| Container | Purpose |
|---|---|
| mosquitto | MQTT broker |
| influxdb | Time-series database |
| grafana | Dashboards |
| telegraf | MQTT → InfluxDB bridge (solar measurement) |
| rtl433 | RTL-SDR primary dongle → MQTT |
| rtl433b | RTL-SDR secondary dongle → MQTT |
| weewx | Weather engine — WeeWX + Belchertown skin |
| nginx | Reverse proxy — all .lan domains + rvtc.lan |
| homeassistant | Home Assistant (host network mode) |
| pihole | DNS + ad blocking |

### Host processes

All bridge services run under systemd. Every unit in `/etc/systemd/system/` for
RVTC is a **symlink** into `config/scripts/` -- edit the repo copy, then
`sudo systemctl daemon-reload`. Never install a standalone copy.

| Unit | Purpose |
|---|---|
| `epever_mqtt` | EPEVER MPPT60 solar -> `rvtc/sensors/solar/#` |
| `samlux_mqtt` | SAMLUX EVO-2212 inverter -> `rvtc/sensors/inverter/#` (script gitignored) |
| `kws_mqtt` | KWS grid / generator meters |
| `battery_current_mqtt` | Battery shunt current |
| `WN90_mqtt` | WN90 weather station |
| `eid041_mqtt` | EID041 temp/humidity |
| `imu_mqtt`, `imu_web`, `imu_gps_heading_autoset` | WitMotion IMU, leveling web page, GPS heading autoset |
| `gps_nmea_bridge`, `gps_nmea_geoclue` | GPS -> NMEA (APRS radio) and geoclue |
| `meshcore_names`, `watchdog_mqtt` | MeshCore name resolver, service watchdog |
| `fetch_eccc_forecast.timer`, `update_weewx_station_location.timer`, `auto_recalibrate_imu_heading.timer` | Scheduled jobs |

---

## Repository Structure

```
RV-total-control/
├── ansible.cfg, site.yml, phase2.yml   # Ansible entry points
├── docker-compose.yml            # Canonical -- always run from repo root
├── docker_volume_backup.sh       # Nightly backup (cron, 02:00)
├── config/
│   ├── scripts/                  # LIVE: bridge scripts + their systemd units (symlinked)
│   ├── telegraf/                 # LIVE: telegraf_*.conf, bind-mounted by compose
│   ├── tools/                    # One-off diagnostics, probes, setup helpers (not services)
│   ├── homeassistant/            # HA YAML + relay scripts (reference copies; live in docker volume)
│   ├── nginx/, grafana/          # Reference copies of dashboards / site
│   ├── mikrotik/                 # Router configs
│   ├── Tank_Mon/, i2c/           # Microcontroller firmware sources
│   ├── docs/                     # Reference config copies (telegraf.conf, weewx.conf)
│   └── archive/                  # Retired scripts kept for reference
├── docs/
│   ├── RVTC_System_Reference_<ver>.md   # Current system reference (latest version only)
│   ├── datasheets/               # Vendor manuals & Modbus register maps
│   ├── handovers/                # Chat-Claude / session handover notes
│   └── archive/                  # Superseded references & session logs
├── tools/flux/                   # Saved InfluxDB Flux queries
├── vendor/                       # Third-party firmware (RAK4631 MeshCore, WitMotion)
├── images/
├── group_vars/all/               # all.yml + vault.yml (Ansible Vault secrets)
├── host_vars/, inventories/production/
└── roles/                        # Ansible roles (mosquitto, influxdb, grafana, ...)
```

Not in git (kept on the host in `~/rvtc-files/`): driver installers, large data
exports, logs, and private notes. Runtime state files (`imu_heading_state.json`,
`weewx_location_state.json`) are gitignored because they contain the RV position.

---|---|
| 192.168.88.1 | MikroTik gateway |
| 192.168.88.2 | Windows workstation |
| 192.168.88.3 | Beelink J45 — all services |
| 192.168.88.5–12 | Waveshare RS-485 gateway ports 1–8 |

DNS: Pi-hole at 192.168.88.3. All local domains use `.lan` TLD.

---

## Network

| IP | Device |
|---|---|
| 192.168.88.1 | MikroTik gateway |
| 192.168.88.2 | Windows workstation |
| 192.168.88.3 | Beelink J45 — all services |
| 192.168.88.5–12 | Waveshare RS-485 gateway ports 1–8 |

DNS: Pi-hole at 192.168.88.3. All local domains use `.lan` TLD.

---

## Modbus Notes

All Modbus work in this project uses **literal/direct register addressing** (0-based PDU).

- `mbpoll`: always pass `-0` flag — without it, mbpoll applies a Modicon-style -1 offset
  that makes every register look shifted by one ("Modbus Shuffle")
- Home Assistant `pymodbus`: addresses literally by default — no offset needed
- EPEVER: input registers FC04 (not holding FC03) for all realtime data; slave address 2
- SAMLUX EVO-2212: holding registers FC03, slave 1, 9600 8N1
- KWS-303L: holding registers FC03, slave 1 (grid) / slave 2 (generator), Even parity

---

## Load & Energy Management

Four-tier architecture documented in project reference Section 2.10:

- **Tier 1** — ESP32-autonomous, source-based: EVO inverting → shed water heater + fridge + A/C
- **Tier 2** — ESP32-autonomous, temperature-based: charge inhibit + battery heater
- **Tier 3** — HA-orchestrated, overload: grid/gen current thresholds → sequential load shed
- **Tier 4** — HA-orchestrated, SOC-based: A/C shed on battery depletion while inverting

Relay board coil assignments: 1=water heater AC, 2=fridge AC, 3=furnace demand,
4=A/C demand, 5=EVO BMS charge inhibit, 6=battery heater, 7–8=spare.

---

## Key Operational Notes

- **Docker compose directory:** always `~/RV-total-control/` — wrong directory puts containers
  on the wrong network and breaks inter-container DNS
- **LMDE Docker repo:** `$VERSION_CODENAME` returns `gigi` on LMDE — docker.list must
  hardcode `trixie`
- **Grafana volume:** must be owned `472:472` — if dashboard disappears after restart:
  `sudo chown -R 472:472 /data/docker/volumes/grafana`
- **WeeWX rain:** `contains_total = true` is critical — Acurite 5n1 sends cumulative counts
- **SAMLUX register map:** held locally under NDA — never paste into chat or commit to repo
- **Ansible vault password:** `~/.vault_pass` — chmod 600, never committed
- **host_vars filename:** must match inventory hostname (`localhost.yml`, not `rvtc.yml`)
