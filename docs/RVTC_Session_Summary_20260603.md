# RVTC Session Summary — 2026-06-03

## Session Goals
- Fix °F storage bug in InfluxDB (influxdb2.py)
- Clean up bogus historical data

---

## Work Completed This Session

### influxdb2.py — unit conversion fix
- Root cause confirmed: WeeWX stores all values in US customary internally regardless of `target_unit = METRICWX` setting; the raw archive record writer was bypassing the display-layer conversion
- Added `CONVERSIONS` map to `influxdb2.py` with the following conversions applied before InfluxDB write:
  - Temperatures (outTemp, inTemp, dewpoint, windchill, heatindex, appTemp, _max, _min variants) — °F → °C
  - Wind speed (windSpeed, windGust, _max variants) — mph → m/s
  - Pressure (barometer, pressure, altimeter) — inHg → hPa
- Deployed to `/data/docker/volumes/weewx/bin/user/influxdb2.py`
- WeeWX restarted; first archive record confirmed at 14.3°C ✅

### InfluxDB bucket flush
- All historical `weewx` measurement data deleted — bucket confirmed empty
- Rationale: existing data was in °F, mph, inHg; not worth backfilling
- Clean metric data now accumulating from 2026-06-03 ~15:35 UTC onward

### Rain sensor
- Tipping bucket triggering phantom rain events (hardware fault — stuck float or reed switch)
- Sensor disabled in WeeWX pending physical inspection
- No InfluxDB rain data being written while disabled

---

## Issues Resolved

- **°F storage bug** — influxdb2.py now converts to metric before writing
- **6 metres of phantom rain** — historical data flushed; rain sensor disabled

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| OI-16 | Grafana weather dashboard | °F display bug resolved — data now in °C |
| OI-29 | GNSS-driven WeeWX position update | Added — manual updates to weewx.conf in the interim; WU and CWOP reporting requires accuracy |
| OI-30 | RV position display page | Added — OSM map via Leaflet.js or Grafana Geomap; prerequisite HW-10 |

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| Rain sensor | Hardware fault — inspect tipping bucket / reed switch; re-enable in WeeWX after fix |
| Historical data | Lost on flush — only data from 2026-06-03 onward is in InfluxDB |

---

## Next Session

1. Home Assistant onboarding — MQTT integration, WeeWX entities (OI-15)
2. ESPHome Ansible role (OI-18)
3. Grafana cleanup — friendly legend names, auto-refresh, rename data source
4. Rain sensor re-enable after hardware fix
