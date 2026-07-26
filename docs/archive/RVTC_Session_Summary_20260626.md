# RVTC Session Summary — 2026-06-26

## Session Goals
- Complete HA onboarding (OI-15)
- Get all Modbus devices into HA as MQTT sensors
- Build samlux_mqtt.py bridge
- Get all device data into InfluxDB

---

## Work Completed This Session

### Home Assistant Onboarding — OI-15 Closed ✅

HA wizard completed. Account created, location set to Nanaimo BC.
MQTT integration added: **Settings → Devices & Services → Add Integration → MQTT**
- Broker: 192.168.88.3, port 1883, no auth
- Status: Platinum quality ✅

---

### Architecture Decision — HA as Data Consumer Only (Reaffirmed)

Initial approach attempted to use HA's Modbus integration directly
(`modbus: !include` in configuration.yaml). This was incorrect — it violated
the core RVTC architecture principle that HA consumes data, not polls devices.

**Root cause of confusion:** Modbus YAML files were built for HA during earlier
sessions before the architecture was fully implemented. When loaded, HA's pymodbus
competed with the Python bridge scripts for gateway connections, causing transaction
ID collisions on all three gateway IPs.

**Resolution:** Removed all Modbus config from HA. HA consumes exclusively via MQTT.
The `modbus/` directory in the HA config volume was removed. The Modbus YAML files
are retained in `~/RV-total-control/config/` for reference only.

**Correct data flow (confirmed working):**
```
Device → RS-485 → Waveshare gateway → Modbus TCP → Python bridge → MQTT → HA
                                                                  → Telegraf → InfluxDB → Grafana
```

---

### SAMLUX EVO-2212 — samlux_mqtt.py Built and Running

**Script:** `config/samlux_mqtt.py`
**Service:** `config/samlux_mqtt.service` → symlinked to `/etc/systemd/system/`
**Topic base:** `rvtc/sensors/inverter/#`
**Poll interval:** 10 seconds

All 27 registers confirmed flowing via `mosquitto_sub`. Key confirmed values:

| Field | Topic | Value |
|---|---|---|
| Grid Input Voltage | voltage_grid_input | 120.1 V |
| Grid Input Frequency | freq_grid_input | 59.94 Hz |
| Input Current | input_current | 2.16 A |
| Input Power | input_watt | 164 W |
| Output Voltage | output_voltage | 120.04 V |
| Output Frequency | output_frequency | 60.06 Hz |
| Battery Voltage | battery_voltage | 13.578 V |
| Battery Current | battery_current | 0.2 A |
| Transformer Temp | transformer_temperature | 25.0°C |
| Operating Mode | operating_mode | 1 (line/passthrough) |
| Operating Mode Text | operating_mode_text | "line" |

**Operating mode decode** (register 284) — critical for Tier 1 load management:
- 0 = standby
- 1 = line (passthrough/grid charging) — normal state
- 2 = inverter (on battery) — **Tier 1 trigger**
- 3 = bypass
- 4 = battery_test
- 5 = fault

**Signed register handling:** int16 conversion applied for battery current,
invert/charge current/watt, and all temperature registers.

---

### Telegraf — Inverter Measurement Added

`telegraf_solar.conf` updated with `[[inputs.mqtt_consumer]]` block for
`rvtc/sensors/inverter/#`, `name_override = "inverter"`.

**InfluxDB measurements now present:**
`weewx`, `solar`, `grid`, `inverter` — plus system metrics (cpu, disk, mem etc.)
from default Telegraf config loading via `telegraf.d/`. System metrics are harmless
but add noise — suppress in a future session by removing the default config.

---

### HA MQTT Sensors — All Devices

`mqtt_sensors.yaml` built and added to configuration.yaml via
`mqtt: !include mqtt_sensors.yaml`.

**Total entities: 76** across all MQTT sensor groups:

| Group | Count | Topics |
|---|---|---|
| EPEVER MPPT60 | 15 | rvtc/sensors/solar/# |
| KWS-303L Grid | 9 | rvtc/sensors/grid/# |
| KWS-303L Generator | 7 | rvtc/sensors/generator/# (unavailable — pending install) |
| SAMLUX EVO-2212 | 17 | rvtc/sensors/inverter/# |

**Entity ID cleanup:** Initial load created `_2` suffix duplicates due to stale
Modbus entity registry entries. Resolved by deleting
`/data/docker/volumes/homeassistant/.storage/core.entity_registry` and restarting
HA. All entities repopulated cleanly from retained MQTT messages.

---

### Phase 3 Hardware Status Update

| ID | Item | Status |
|---|---|---|
| HW-03 | Install 4×100W PV panels | ✅ Closed — panels up, producing |
| HW-04 | Wire 9 PV panels (3S×3P) | ✅ Closed — full array wired |
| OI-15 | HA onboarding | ✅ Closed — MQTT connected, all sensors live |

---

## Files Changed This Session

| File | Change |
|---|---|
| `config/samlux_mqtt.py` | New — SAMLUX EVO-2212 Modbus → MQTT bridge |
| `config/samlux_mqtt.service` | New — systemd unit for samlux_mqtt.py |
| `config/telegraf_solar.conf` | Updated — inverter mqtt_consumer block added |
| `config/mqtt_sensors.yaml` | New — all HA MQTT sensor definitions |
| `config/modbus_kws.yaml` | New — single-hub KWS config (reference only) |
| `/data/docker/volumes/homeassistant/configuration.yaml` | Updated — mqtt include added, modbus removed |
| `/data/docker/volumes/homeassistant/mqtt_sensors.yaml` | New — deployed to HA config volume |

---

## Remaining Phase 3 Items

### Hardware (physical work required)
| ID | Item |
|---|---|
| HW-09 | Generator meter — set slave 2 on bench, wire onto RS-485/3 |
| HW-10 | Install GNSS E108-GN03G-485 (RS-485/6, device in hand) |
| HW-16 | Ecowitt WN90LP weather station (shipped — RS-485/7) |
| HW-18 | HSR1-25 25A NO relay — water heater + fridge AC wiring |
| HW-19 | 12V→5V DC-DC converter to power relay board |
| HW-20 | ESP32-S3 Touch LCD thermostat — fish DMX cable, firmware |
| HW-21 | Wire coil 5 — EVO BMS charge inhibit |
| HW-22 | Install battery heater, wire coil 6 |
| HW-23 | RS485-1M2S splitter — reconnect MT50 (ordered) |
| HW-24 | DC shunt 400A RS-485 (ordered) |

### Software
| ID | Item |
|---|---|
| OI-16 | Rebuild Grafana weather dashboard |
| OI-18 | ESPHome Ansible role |
| OI-24 | Load & energy management automation (Tier 1-4) — needs HW-18/21/22 |
| OI-37 | Portainer container management UI |
| OI-38 | ESP32-S3 thermostat firmware |
| OI-39 | ESP32 Modbus polling register list |

---

## Next Session Priorities

1. Commit all session files to git
2. Rebuild Grafana weather dashboard (OI-16)
3. Add Portainer to Docker stack (OI-37) — quick win
4. WN90LP commissioning when received (HW-16)
5. Begin physical wiring — HW-18 (relays), HW-21 (BMS inhibit), HW-22 (battery heater)
