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

### weewx.conf current state
- Station type: MQTTSubscribeDriver
- MQTT topic: rtl_433/+/events (JSON)
- Target unit: METRICWX
- Archive services: weewx.engine.StdArchive, user.influxdb2.InfluxDB2Writer
- InfluxDB: host=influxdb, org=rvtc, bucket=rvtc

---

## Issues Resolved

- **Ansible template deployment corrupts live weewx.conf** — template approach abandoned for weewx.conf; live file managed manually on host volume
- **Duplicate [Engine] and [Logging] sections** — caused configobj parse error at line 560; fixed by removing first set
- **vault_influxdb_token not in vault** — added during this session
- **weectl extension install fails from Ansible** — weectl needs `--config /data/weewx.conf`; extension install done manually

---

## Pending Items

| Item | Notes |
|---|---|
| Verify WeeWX → InfluxDB data flow | Wait for first archive record (5 min interval), check InfluxDB |
| WeeWX time zone | Container needs `TZ: America/Vancouver` env var in Ansible role |
| Ansible weewx role cleanup | Template approach broken — role needs rethink; for now weewx.conf managed manually |
| Home Assistant onboarding | Setup wizard, MQTT integration |
| Local DNS names | Pi-hole local DNS records for services |
| MikroTik dst-nat port 80 | Forward club LAN → 192.168.88.3:80 for WeeWX |
| Update session context document | Reflect Phase 2 complete + all changes |
| MikroTik RSC update | DNS changes made in Winbox not yet in rsc file |

---

## Key File Locations

| File | Path |
|---|---|
| weewx.conf (live) | /data/docker/volumes/weewx/weewx.conf |
| weewx.conf backup | /data/docker/volumes/weewx/weewx.conf.20260528170858 |
| Custom InfluxDB writer | /data/docker/volumes/weewx/bin/user/influxdb2.py |
| Ansible vault | ~/RV-total-control/group_vars/all/vault.yml |
| group_vars | ~/RV-total-control/group_vars/all/all.yml |

---

## Next Session

1. Verify InfluxDB data flowing from WeeWX
2. Build Grafana dashboard for weather data
3. WeeWX time zone fix
4. Home Assistant onboarding
5. Local DNS names via Pi-hole
6. Update session context document
