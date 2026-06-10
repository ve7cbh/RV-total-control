# RVTC Session Summary — 2026-06-10

## Session Goals
- Swap in RTL-SDR Blog V3 (antenna now fitted) as primary dongle
- Confirm full decode chain with new hardware
- Attempt dual-dongle setup with clone as secondary

---

## Work Completed This Session

### RTL-SDR Blog V3 — Primary dongle commissioned

**Background:**
The Blog V3 (SN 1024, R820T tuner) could not be commissioned in the previous session due to missing antenna. Antenna sourced and fitted. Device confirmed working on Windows workstation (rtl_433 v25.12, Acurite 5n1 ID 1111 decoding cleanly).

**Swap procedure:**
1. `docker compose stop rtl433` on J45
2. Unplugged old clone dongle, plugged in Blog V3 (SN 1024)
3. Confirmed device recognised: `rtl_test` → R820T tuner, SN 1024, sampling confirmed
4. `docker compose up -d rtl433`
5. Confirmed decode via `mosquitto_sub -t 'rtl_433/+/events'` — ID 1111 JSON flowing
6. Confirmed WeeWX LOOP packets: outTemp, outHumidity, windSpeed, windDir all present
7. Confirmed Belchertown and Seasons skins generating

**Result:** Blog V3 fully operational as primary dongle. Full chain confirmed:
dongle → rtl433 container → MQTT → WeeWX → InfluxDB → Belchertown ✅

---

### Dual RTL-SDR setup — Both dongles active

**Background:**
With the Blog V3 confirmed working, the old clone dongle (SN 00000001, R828D tuner) was plugged in alongside it. Both dongles already had unique serial numbers — no EEPROM changes required.

**Key finding — tuner identification:**
Counterintuitively, `rtl_eeprom -d 1` revealed the clone dongle contains an **R828D** tuner (not R820T as assumed). The genuine Blog V3 has the R820T. Both are functional; the R828D is generally the higher-spec tuner.

**docker-compose.yml changes:**
- `rtl433` service: added `-d 1024` to pin to Blog V3 by serial
- `rtl433b` service: new — pins to clone via `-d 00000001`, publishes to `rtl_433/rtl433b/events`

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

**Result:** Both containers decoding independently. `mosquitto_sub -t 'rtl_433/+/events'` shows duplicate packets — one from each container — for every Acurite 5n1 transmission. WeeWX receives both via wildcard subscription; duplicates are benign. ✅

**Committed and pushed:** `85b7357`

---

## RTL-SDR Dongle State (corrected)

| Unit | Tuner | SN | Container | Status |
|---|---|---|---|---|
| RTL-SDR Blog V3 | R820T | 1024 | rtl433 | Active — primary |
| Clone (old primary) | R828D | 00000001 | rtl433b | Active — secondary |

---

## Issues Resolved

- RTL-SDR Blog V3 not commissioned (no antenna) — resolved, antenna fitted, confirmed working
- Single-dongle only — resolved, dual setup live
- Device index instability on reboot — resolved, both containers use serial-based `-d` flag

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| HW-11 | RTL-SDR Blog V3 | ✅ Complete — R820T tuner, SN 1024, antenna fitted, active as primary |
| OI-33 | Club bridge Pi | 🟡 Open — added to backlog |
| OI-34 | GNSS geofence source inhibit | 🟡 Open — added to backlog |

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| Grafana dashboard | Still needs rebuilding (carried from 2026-06-09) |
| Rain ID filter | `filter_out_message_when = 291` added but not yet tested under rain conditions |
| Dual dongle duplicate packets | WeeWX processes duplicates from both containers — benign now, deduplication deferred to Phase 7 fusion layer |
| HW-14 | Rain gauge physical inspection at club still required |

## Architecture Decisions Made

**Club bridge topology (OI-33/OI-34):**
- Small always-on Pi at club — rtl_433 + WireGuard
- Connects to home J45 only, never directly to RV
- Home J45 Mosquitto is the hub — RV subscribes to home regardless of location
- GNSS geofence (OI-34, requires HW-10) will automatically suppress RV 5n1 when at club
- Reuses OI-20 VPN infrastructure

---

## Next Session — Phase 3

1. Waveshare RS-485 gateway commissioning (HW-01) — device in hand
2. EPEVER MPPT60 Modbus integration (RS-485/1, TCP 4001)
3. SAMLUX EVO-2212 inverter Modbus integration (RS-485/2, TCP 4002)
4. Solar panel wiring (HW-03/HW-04)
5. Home Assistant onboarding — MQTT integration (OI-15)
6. Rebuild Grafana dashboard (OI-16)
7. WeeWX upstream bug report (OI-32)
