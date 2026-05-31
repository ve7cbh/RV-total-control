# RVTC Session Summary — 2026-05-29

## Session Goals
Phase 2 wrap-up:
1. WeeWX time zone fix (PST)
2. WeeWX metric units fix
3. WeeWX → InfluxDB integration
4. Home Assistant onboarding and MQTT integration
5. Local DNS names for services
6. Pi-hole port 80 dst-nat on MikroTik
7. Update session context document

---

## Work Completed This Session

### group_vars/all/all.yml cleanup
- Removed duplicate InfluxDB vars block that was appended in a previous session
- Fixed bucket name `rvcc` → `rvtc`
- Consolidated all vars into single clean file
- Added `influxdb_token: "{{ vault_influxdb_token }}"` reference

### vault.yml
- Added `vault_influxdb_token` — InfluxDB admin token encrypted in vault
- Vault file now contains: influxdb, grafana, pihole credentials + influxdb token

### Custom InfluxDB2 writer
- Created `/data/docker/volumes/weewx/bin/user/influxdb2.py`
- Pure Python, no external dependencies
- Writes WeeWX archive records to InfluxDB v2 API on each NEW_ARCHIVE_RECORD event
- Uses `urllib` — no pip installs required
- Class name: `InfluxDB2Writer`
- Config section in weewx.conf: `[InfluxDB2]`

### weewx.conf rebuild
- Multiple overwrites during template deployment caused config corruption
- Restored from backup `weewx.conf.20260528170858`
- Reapplied all working changes manually:
  - `station_type = MQTTSubscribeDriver`
  - `target_unit = METRICWX`
  - `unit_system = metricwx` in StdReport
  - Location, lat, lon, altitude
  - MQTTSubscribeDriver section with `rtl_433/+/events` JSON topic
  - `[InfluxDB2]` section with host/port/org/bucket/token
  - `[Engine]` with `user.influxdb2.InfluxDB2Writer` in archive_services
- Removed duplicate `[Engine]` and `[Logging]` sections (lines 495-510 from backup)
- Template approach abandoned for weewx.conf — live file managed manually on host volume

### weewx.conf current state
- Station type: MQTTSubscribeDriver
- MQTT topic: rtl_433/+/events (JSON)
- Target unit: METRICWX
- Archive services: weewx.engine.StdArchive, user.influxdb2.InfluxDB2Writer
- InfluxDB: host=influxdb, org=rvtc, bucket=rvtc

### nginx CSS fix
- Added `include mime.types` and `default_type application/octet-stream` to nginx.conf.j2
- Fixes CSS being served as `text/plain` instead of `text/css`
- Removed dead `proxy_set_header` directives from WeeWX static file block
- Added WebSocket upgrade headers to Grafana block

### ESPHome nginx block
- Added `esphome.local` server block proxying to `esphome:6052`
- Used Docker resolver (`127.0.0.11`) with `set $upstream` pattern to defer DNS
  resolution until request time — prevents nginx startup failure when ESPHome
  container is not yet running

### WeeWX timezone fix
- Added `TZ: America/Vancouver` env var to WeeWX container in Ansible role

### InfluxDB data flow verified
- WeeWX archive records confirmed flowing into InfluxDB bucket `rvtc`

### Local DNS records
- Pi-hole local DNS records added for all services:
  - weewx.local, grafana.local, influxdb.local, homeassistant.local, pihole.local, esphome.local → 192.168.88.3

### MikroTik RSC update
- RSC file updated to reflect DNS changes previously made in Winbox

---

## Issues Resolved

- **Ansible template deployment corrupts live weewx.conf** — template approach abandoned; live file managed manually on host volume
- **Duplicate [Engine] and [Logging] sections** — caused configobj parse error at line 560; fixed by removing first set
- **vault_influxdb_token not in vault** — added during this session
- **weectl extension install fails from Ansible** — weectl needs `--config /data/weewx.conf`; extension install done manually
- **CSS served as text/plain** — fixed with `include mime.types` in nginx config
- **nginx crash on ESPHome upstream** — nginx resolves upstreams at startup; fixed with Docker resolver + `set $upstream` deferred resolution pattern

---

## Pending Items

| Item | Notes |
|---|---|
| Grafana dashboard | Build weather dashboard from InfluxDB rvtc bucket |
| Home Assistant onboarding | Setup wizard, MQTT integration |
| ESPHome container deployment | Ansible role to be created; nginx block already in place |

---

## Key File Locations

| File | Path |
|---|---|
| weewx.conf (live) | /data/docker/volumes/weewx/weewx.conf |
| weewx.conf backup | /data/docker/volumes/weewx/weewx.conf.20260528170858 |
| Custom InfluxDB writer | /data/docker/volumes/weewx/bin/user/influxdb2.py |
| nginx config | /data/docker/volumes/nginx/nginx.conf |
| Ansible vault | ~/RV-total-control/group_vars/all/vault.yml |
| group_vars | ~/RV-total-control/group_vars/all/all.yml |

---

## Next Session

1. Grafana dashboard for weather data
2. Home Assistant onboarding (setup wizard, ESPhome + MQTT integration.  Install MQTT explorer of some sort either in HA or ????)
      Make Homelan HA and RV HA available to each other
3. ESPHome container deployment (Ansible role)

Install Hi-Flying HF5142B — 4-port RS-485 to Ethernet, Modbus RTU/TCP, J45.  Build cables Samlux, EPEVER MPPT controller.  Draw a system drawing - wire lists hardware lists.  
Source a barometric sensor, Build exp32 for pulse water meter, turbitty, preasure (2), flow, etc (how far do you go? )
Install 4x100watt PVpanels, wire 9 PV panels 3x3 (36 volt and complete solar system so we get some data, Design the tank monitoring sensors.

Claude please put the above into a trackable list that will live with these updates.  
