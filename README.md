# RV Total Control (RVTC)

**Author:** Steve Bradshaw (ve7cbh) — Nanaimo, BC
**Last updated:** 2026-10-10
**Web UIs:** `http://rvtc.lan` · `http://weewx.lan` · `http://grafana.lan` · `http://homeassistant.lan`

Monitoring, control and data collection for a towed RV: solar, battery, inverter, grid and
generator power, weather, attitude/GPS, enclosure climate, and load shedding. Runs on a Beelink
J45 mini-PC with the core services in Docker Compose. Field devices are on wired RS-485 Modbus
through Ethernet gateways.

> **The authoritative, kept-current description of the system is
> [`docs/RVTC_System_Reference_2_15.md`](docs/RVTC_System_Reference_2_15.md).** This README is the
> front page only; when the two disagree, the System Reference wins. Only the latest version
> lives in `docs/`; older ones are in `docs/archive/`.

---

## Architecture — one path for every sensor

```
Sensor  →  Adaptor (bridge script / WeeWX)  →  Mosquitto (MQTT)  →  Telegraf  →  InfluxDB  →  Grafana / HA / dashboards
```

- Adaptors do all decoding and correction, then publish to MQTT under `rvtc/sensors/<source>/#`.
- **Nothing writes to InfluxDB directly.** Telegraf's `mqtt_consumer` is the only writer.
  WeeWX is an adaptor too: it republishes corrected weather to MQTT, it does not write to the DB.
- Home Assistant is a consumer. Its one bounded exception is actuating load-shed relays.

Details: System Reference §1 (principle), §7 (data flow per sensor), §8 (Home Assistant's role).

---

## Web UIs

All served by nginx on port 80 by hostname. Pi-hole resolves the `.lan` names to `192.168.88.3`.

| URL | What |
|---|---|
| http://rvtc.lan | Unified dashboard: Solar/Battery (InfluxDB) + live Telemetry tab (MQTT websocket, port 9001) |
| http://weewx.lan | WeeWX, Belchertown skin (also public via `rv.malacat.ca`) |
| http://grafana.lan | Grafana dashboards |
| http://homeassistant.lan | Home Assistant |
| http://influxdb.lan | InfluxDB UI (bucket and org `rvtc`) |
| http://imu.lan | IMU leveling page (`imu_web.py`) |
| http://pihole.lan | Pi-hole DNS admin |
| http://portainer.lan | Portainer (Docker admin) |

---

## Hardware

**Control host:** Beelink J45 (Pentium J4205, 8 GB), LMDE 7, hostname `ve7cbh-control`,
`192.168.88.3`. Root on the 238 GB disk; Docker volumes on `/data` (477 GB) under
`/data/docker/volumes/<service>/`.

**RS-485 gateways** (all Modbus RTU over raw TCP, port 4001, protocol mode `None`):

| Bus | IP | Device | Adaptor |
|---|---|---|---|
| 485-1 | 192.168.88.5 | EPEVER MPPT60 solar controller (+ MT50 display) | `epever_mqtt.py` |
| 485-2 | 192.168.88.6 | SAMLUX EVO-2212 inverter/charger | `samlux_mqtt.py` |
| 485-3 | 192.168.88.7 | KWS-303L grid + generator meters | `kws_mqtt.py` |
| 485-4 | 192.168.88.8 | WitMotion WTGAHRS3-485 GPS-IMU (HW-27) | `imu_mqtt.py` |
| 485-5 | 192.168.88.9 | Water sensors | pending |
| 485-6 | 192.168.88.10 | Ecowitt WN90LP weather station | `WN90_mqtt.py` → WeeWX |
| 485-7 | 192.168.88.11 | 300 A battery current shunt (HW-24) | `battery_current_mqtt.py` |
| 485-8 | 192.168.88.12 | Waveshare 8-ch relay board (load shed) | `relay.py` via HA |
| serial-1 | 192.168.88.13 | GPS → NMEA out to APRS radio | `gps_nmea_bridge.py` |
| serial-2 | 192.168.88.14 | HVAC relay board (System Reference §12) | not yet wired |
| serial-4 | 192.168.88.16 | EID041 enclosure temp/humidity (HW-32) | `eid041_mqtt.py` |

`485-*` are isolated Waveshare units. `serial-*` are ports on a shared, **non-isolated** HF5142B
next to the workstation; check what's plugged in before using a free port. Full detail: §3.

---

## Docker stack

Run from the repo root: `docker compose` must be run in `~/RV-total-control/`.

| Container | Purpose | Port |
|---|---|---|
| mosquitto | MQTT broker | 1883, 9001 (websockets) |
| influxdb | Time-series DB, bucket `rvtc` | 8086 |
| telegraf | MQTT → InfluxDB (the only DB writer) | — |
| grafana | Dashboards | 3000 |
| weewx | Weather adaptor + Belchertown site | — |
| homeassistant | Automation / display | 8123 |
| nginx | Hostname reverse proxy for all `.lan` UIs | 80 |
| pihole | DNS | 53, 8880 |
| portainer | Docker admin | 9000 |

## Host services (systemd)

Every RVTC unit in `/etc/systemd/system/` is a **symlink** into `config/scripts/`. Edit the
repo copy, then `sudo systemctl daemon-reload`. Never install a standalone copy.

| Unit | Purpose |
|---|---|
| `epever_mqtt` | Solar → `rvtc/sensors/solar/#` |
| `samlux_mqtt` | Inverter → `rvtc/sensors/inverter/#` (script gitignored: private ports) |
| `kws_mqtt` | Grid / generator meters |
| `battery_current_mqtt` | Battery shunt current |
| `WN90_mqtt` | WN90LP weather, raw (WeeWX publishes the corrected feed) |
| `eid041_mqtt` | Enclosure temp/humidity |
| `imu_mqtt`, `imu_web`, `imu_gps_heading_autoset` | IMU, leveling page, GPS heading autoset |
| `gps_nmea_bridge`, `gps_nmea_geoclue` | GPS → NMEA (APRS radio), GPS → geoclue |
| `meshcore_names`, `watchdog_mqtt` | MeshCore name resolver, service watchdog |
| `fetch_eccc_forecast.timer` | ECCC forecast for the WeeWX site |
| `update_weewx_station_location.timer` | Moves WeeWX station location when the RV moves |
| `auto_recalibrate_imu_heading.timer` | Nightly IMU heading recalibration |

---

## Network

| Address | Device |
|---|---|
| 192.168.88.1 | MikroTik router (Club WiFi / Starlink WAN) |
| 192.168.88.3 | J45 control host — all services |
| 192.168.88.5–12 | Waveshare RS-485 gateways `485-1`…`485-8` |
| 192.168.88.13–16 | HF5142B serial gateway `serial-1`…`serial-4` |
| 192.168.0.0/24 | Home network, reached over the trailer↔home IPsec VPN (§6) |

---

## Repository structure

```
RV-total-control/
├── docker-compose.yml            # Canonical — always run from repo root
├── .env                          # Secrets for compose (InfluxDB token) — gitignored, chmod 600
├── docker_volume_backup.sh       # Nightly backup (cron, 02:00)
├── ansible.cfg, site.yml, phase2.yml   # Ansible entry points
├── config/
│   ├── scripts/                  # LIVE: bridge scripts + their systemd units (symlinked)
│   ├── telegraf/                 # LIVE: telegraf_*.conf, each bind-mounted by compose
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

**Not in git** (kept on the host in `~/rvtc-files/`): driver installers, large data exports,
logs, and private notes/keys. Runtime state files (`imu_heading_state.json`,
`weewx_location_state.json`) are gitignored because they contain the RV's position.

---

## Secrets — this repo is public

- **InfluxDB token:** in `.env` only (write-only on bucket `rvtc`); telegraf configs reference
  `${INFLUX_TOKEN}`. Rotation steps: System Reference §9.
- **Ansible:** secrets in `group_vars/all/vault.yml` (Ansible Vault); vault password in
  `~/.vault_pass` (chmod 600, never committed).
- **SAMLUX:** `samlux_mqtt.py` is gitignored, and the register map is held locally under NDA.
  Never commit or paste either.
- **VPN pre-shared key:** only in `~/rvtc-files/private/` and the password manager.
- Before committing anything from a chat handover, scan it for keys and passwords.

---

## Key operational notes

- **Compose directory:** always `~/RV-total-control/`. The wrong directory puts containers on the
  wrong network and breaks inter-container DNS.
- **New telegraf config:** create the file **and** add its mount line in `docker-compose.yml`,
  then `docker compose up -d telegraf`. A plain restart won't pick up a new mount.
- **Modbus:** literal 0-based register addressing everywhere. `mbpoll` needs `-0`, and these
  gateways speak raw RTU over TCP, not Modbus/TCP. EPEVER uses input registers (FC04), slave 2.
  SAMLUX and KWS use holding registers (FC03).
- **Relays:** board coils are inverted (1 = shed/off). That's a wiring quirk, not a bug (§3).
- **Grafana volume:** must be owned `472:472`. If dashboards vanish after a restart:
  `sudo chown -R 472:472 /data/docker/volumes/grafana`.
- **LMDE Docker repo:** `$VERSION_CODENAME` returns `gigi`, so `docker.list` must hardcode `trixie`.
- **host_vars filename** must match the inventory hostname (`localhost.yml`).
- **Git:** run git over SSH on the host. Windows git on the `X:` share shows bogus mode/CRLF
  changes, and its line-ending conversion can damage live scripts.

Known quirks and their fixes: System Reference §9. Open items and hardware still to install: §11.
