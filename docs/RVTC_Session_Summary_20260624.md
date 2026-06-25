# RVTC Session Summary — 2026-06-24

## Session Goals
- Commission EPEVER MPPT60 Modbus integration (RS-485/1)
- Get solar data into Mosquitto broker
- Build solar monitoring page

---

## Work Completed This Session

### EPEVER MPPT60 — Commissioned

**Connection confirmed:**
- Gateway: Waveshare RS-485/1, IP 192.168.88.5, TCP 4001
- Modbus slave address: **2** (set via MT50 remote display — not the default of 1)
- Register type: **input registers FC04** (not holding registers FC03 — common EPEVER gotcha)
- Baud: 115200 8N1 (set on gateway port 1 — confirmed working from prior session)

**MT50 bus contention diagnosed:**
The EPEVER has two RJ45 RS-485 ports, but both are on the same internal bus — not independent channels. The MT50 remote display and the Waveshare gateway cannot share the bus without collisions. With both connected, mbpoll returned intermittent "Invalid data" and "Connection timed out" errors. MT50 pulled for this session.

**Resolution:** EPEVER RS485-1M2S one-master-two-slave adapter ordered. When it arrives, MT50 reconnects with zero reconfiguration — both ports become independent masters on the same slave.

**Verified registers (all input registers, slave 2, literal addressing with -0):**

| Register | Field | Scale | Sample value |
|---|---|---|---|
| 12544 | PV Voltage | ×0.01 V | 58.22 V |
| 12545 | PV Current | ×0.01 A | 9.84 A |
| 12546/7 | PV Power (32-bit L+H) | ×0.01 W | 612 W |
| 12548 | Battery Voltage | ×0.01 V | 14.14 V |
| 12549 | Charging Current | ×0.01 A | 43.28 A |
| 12550/1 | Charging Power (32-bit L+H) | ×0.01 W | 612 W |
| 12556 | Load Voltage | ×0.01 V | 14.15 V |
| 12557 | Load Current | ×0.01 A | 0.00 A |
| 12560 | Battery Temperature (RTS) | ×0.01 °C | 33.62°C |
| 12561 | Controller Temperature | ×0.01 °C | 49.24°C |
| 12570 | Battery SOC | ×1 % | 100% |
| 12800 | Charging Status (bitmask) | — | 0 |
| 12801 | Battery Status (bitmask) | — | 9 |
| 13068/9 | Daily Energy (32-bit L+H) | ×0.01 kWh | 2.56 kWh |
| 13074/5 | Total Energy (32-bit L+H) | ×0.01 kWh | 2.99 kWh |

**pymodbus 3.13 API change:**
The `slave=` and `unit=` keyword arguments to `read_input_registers()` were both removed in pymodbus 3.13. The correct parameter is now `device_id=`. Discovered by inspection:
```bash
python3 -c "
import inspect
from pymodbus.client import ModbusTcpClient
print(inspect.signature(ModbusTcpClient.read_input_registers))
"
# (self, address, *, count=1, device_id=1, no_response_expected=False) -> T
```

---

### epever_mqtt.py — Written and running

Python bridge script polling EPEVER via Modbus TCP and publishing to Mosquitto every 10 seconds.

**Topic schema:** `rvtc/sensors/solar/<field>`

**Key implementation notes:**
- `read_input_registers()` with `device_id=2`
- 32-bit registers combined low-word-first: `(high << 16) | low`
- String-valued fields (charge_stage decode, last_updated timestamp) disabled — Telegraf pipeline requires float-only topics
- Retained string topics cleared with null publish: `mosquitto_pub -t <topic> -n -r`
- Running as background daemon: `nohup python3 config/epever_mqtt.py >> logs/epever_mqtt.log 2>&1 &`

**File:** `config/epever_mqtt.py`
**Log:** `logs/epever_mqtt.log`

---

### Telegraf — Added to Docker stack

Telegraf container added to `docker-compose.yml` to bridge MQTT → InfluxDB.

**Subscribes to:** `rvtc/sensors/solar/#`
**Writes to:** InfluxDB bucket `rvtc`, measurement `solar`
**Field tag:** `solar_field` (last segment of MQTT topic path)

**Issues encountered and resolved:**
- `org` field renamed in newer Telegraf — must use `organization`
- `data_type = "auto"` not supported — use `float`; string MQTT topics must not be published
- `name_override = "solar"` required — without it Telegraf writes to measurement `mqtt_consumer`
- InfluxDB schema conflict: once a field is written as string, float writes fail with 422. Solution: delete measurement and restart with correct type.
- INFLUXDB_TOKEN environment variable not expanding in compose — hardcoded token in `telegraf_solar.conf` instead (file is not committed to repo)

**File:** `config/telegraf_solar.conf`

---

### Grafana Solar Dashboard — Imported

Dashboard JSON imported via Grafana API. Datasource UID hardcoded (`efotz27vf0q9sd`) after `${DS_INFLUXDB}` template variable failed to resolve.

Flux queries use `solar_field` tag filter:
```flux
from(bucket: "rvtc")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "solar" and r.solar_field == "pv_power")
```

**Dashboard:** `config/rvtc_solar_dashboard.json`
**URL:** `http://grafana.lan/d/rvtc-solar`

---

### rvtc.lan — New unified monitoring site

Single-page application served by nginx with left sidebar tab navigation.

**URL:** `http://rvtc.lan`
**File:** `/data/docker/volumes/nginx/rvtc/index.html`
**Source:** `config/rvtc_index.html` (committed to repo)

**Tabs implemented:**
- ☀️ Solar — PV power hero, PV voltage/current/stage, charging power, daily/lifetime kWh, temperatures
- 🔋 Battery — SOC gauge + bar, battery voltage, charging current/power, temperature, load terminals
- ⚡ Power — placeholder, KWS-303L and EVO-2212 listed as coming soon
- 🌤️ Wx — links to weewx.lan (existing Belchertown skin, unchanged)
- 💧 Tanks / 🚰 Water / 📍 Map — dimmed placeholders for Phase 4/5/7

**Data source:** InfluxDB Flux API queried directly from browser every 10 seconds. Token embedded in HTML (private LAN only — acceptable).

**nginx config:** new `server` block added to `/data/docker/volumes/nginx/nginx.conf` for `server_name rvtc.lan`, root `/usr/share/nginx/rvtc`.

**Pi-hole DNS:** `192.168.88.3 rvtc.lan` added to `/data/docker/volumes/pihole/etc-pihole/custom.list`.

**nginx volume mount added to docker-compose.yml:**
```yaml
- /data/docker/volumes/nginx/rvtc:/usr/share/nginx/rvtc:ro
```

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| HW-23 | EPEVER RS485-1M2S one-master-two-slave adapter | 🟡 Open — added, ordered 2026-06-24 |

---

## Architecture Decisions Made

**MQTT topic schema for solar:** `rvtc/sensors/solar/<field>` — consistent with Phase 7 normalised schema proposal (`rvtc/sensors/{source_id}/{field}`).

**Telegraf as MQTT→InfluxDB bridge:** preferred over writing directly from epever_mqtt.py. Keeps the Python script simple (publish only) and reuses Telegraf for future devices (KWS, EVO-2212) with minimal new config.

**rvtc.lan as unified UI:** weewx.lan retained as-is (Belchertown skin). rvtc.lan is the new primary monitoring interface with tab-per-subsystem layout. Tabs added as phases complete.

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| MT50 disconnected | RS485-1M2S splitter ordered (HW-23) — reconnect MT50 when received |
| Charge stage not on rvtc.lan | String field excluded from float-only Telegraf pipeline — add as separate string measurement later |
| epever_mqtt.py not in systemd | Running as nohup daemon — will not survive reboot. Add systemd service or Docker container next session |
| rvtc.lan KWS Power tab | Placeholder only — KWS-303L grid data to be added next session |
| Git commit pending | epever_mqtt.py, telegraf_solar.conf, docker-compose.yml, rvtc_solar_dashboard.json, rvtc_index.html |

---

## Files Changed This Session

| File | Change |
|---|---|
| `config/epever_mqtt.py` | New — EPEVER Modbus → MQTT bridge |
| `config/telegraf_solar.conf` | New — Telegraf MQTT → InfluxDB config |
| `config/rvtc_solar_dashboard.json` | New — Grafana solar dashboard |
| `config/rvtc_index.html` | New — rvtc.lan unified monitoring page |
| `docker-compose.yml` | Added telegraf service + nginx rvtc volume mount |
| `/data/docker/volumes/nginx/nginx.conf` | Added rvtc.lan server block |
| `/data/docker/volumes/pihole/etc-pihole/custom.list` | Added rvtc.lan DNS record |

---

## Next Session — Phase 3 Priorities

1. Add epever_mqtt.py to systemd so it survives reboot
2. KWS-303L grid meter → MQTT → Power tab on rvtc.lan
3. Git commit all session files
4. Home Assistant onboarding — MQTT integration (OI-15)
5. Rebuild Grafana weather dashboard (OI-16)
6. HSR1-25 physical wiring — water heater and fridge AC relays (HW-18)
7. Wire coil 5 — EVO BMS charge inhibit (HW-21)
8. EPEVER RS485-1M2S — reconnect MT50 when splitter arrives (HW-23)
