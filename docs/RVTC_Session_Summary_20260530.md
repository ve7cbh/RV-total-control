# RVTC Session Summary — 2026-05-30

## Session Goals
1. Formalise backlog from Phase 2 wrap-up notes
2. Grafana weather dashboard (OI-16)

---

## Work Completed This Session

### Backlog formalisation
Captured all pending items from the 2026-05-29 session notes into three tracked tables in the context document:

- Software / Configuration: OI-14 through OI-20
- Hardware / Physical Install: HW-01 through HW-07
- Design / Documentation: DD-01 through DD-02

### File naming standard
- `.yaml` adopted as standard extension for all YAML files going forward
- `.yml` → `.yaml` rename across the repo added to OI-17 scope (cleanup phase)

### ESPHome ambient sensor YAML
- Reviewed and corrected user's first-draft ESPHome YAML
- Key fixes: `dallas` → `dallas_temp`, `bmp280` → `bmp280_i2c`
- Built complete deployable `rvtc-ambient.yaml`:
  - ESP32 dev board
  - 5× DS18B20 sensors: Inside RV, Outside RV, Battery Compartment, Battery Box, Basement Storage
  - BME280 (pressure + temperature + humidity)
  - WiFi with static IP placeholder, fallback AP, OTA, HA API
  - secrets.yaml pattern for credentials
  - Address placeholders with first-boot scan instructions

### Grafana weather dashboard (OI-16)
- Connected InfluxDB to Grafana as data source
  - Query language: Flux
  - URL: http://influxdb:8086 (container-to-container, not via nginx)
  - Org: rvtc, Bucket: rvtc, Token: configured
  - Cleaned up duplicate data sources (influxdb, influxdb-1 deleted; influxdb-2 kept as default)
- Built RVTC Weather dashboard with 4 panels:
  - Outside Temperature — time series, °F unit
  - Outdoor Humidity — time series, % unit
  - Wind Speed & Gusts — time series, m/s, both fields on single panel
  - Rain — bar chart, mm, fn: sum
- Dashboard saved as "RVTC Weather"
- Kiosk mode confirmed working via `?kiosk` URL parameter

---

## Issues Resolved

- **Grafana InfluxQL vs Flux** — data source must be configured as Flux for InfluxDB v2; InfluxQL mode shows visual query builder which doesn't work with v2
- **Grafana URL for InfluxDB** — must use container name `influxdb:8086`, not `influxdb.local` or host IP; Grafana queries from inside Docker network

---

## Known Issues / Pending Cleanup

| Item | Notes |
|---|---|
| Temperature stored in °F | Raw influxdb2.py writer bypasses WeeWX unit conversion — values stored as °F despite METRICWX setting |
| Legend labels | Showing field names (outTemp, outHumidity) instead of friendly names |
| Dashboard auto-refresh | Not yet configured |
| Data source name | influxdb-2 should be renamed to influxdb |

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| OI-16 | Grafana weather dashboard | ✅ Complete (cleanup items remain) |

---

## Next Session

1. Home Assistant onboarding — setup wizard, MQTT integration (OI-15)
2. ESPHome container deployment — Ansible role (OI-18)
3. Grafana dashboard cleanup — friendly legend names, °F→°C fix, auto-refresh, rename data source
4. Phase 3 planning — HF5142B install, cable build, solar wiring
