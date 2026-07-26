# RV Total Control — Project Reference
**Last Updated:** June 29, 2026
**Owner:** Steve Bradshaw (ve7cbh) — Nanaimo, BC
**GitHub:** https://github.com/ve7cbh/RV-total-control
**Status:** Phase 2 Complete — Phase 3 Active

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Hardware](#2-hardware)
3. [Network](#3-network)
4. [Docker Stack](#4-docker-stack)
5. [WeeWX Configuration](#5-weewx-configuration)
6. [Ansible & Repository](#6-ansible--repository)
7. [Open Items & Backlog](#7-open-items--backlog)
8. [Session Log](#8-session-log)
9. [Architecture Notes](#9-architecture-notes)

---

## 1  Project Overview

RV Total Control (RVTC) is a full-stack monitoring and control system for a recreational vehicle,
built on a Beelink J45 mini-PC running Linux Mint LMDE. The system integrates weather sensing, power
management (solar, inverter, grid, generator), tank monitoring, water quality measurement, and
location tracking into a unified dashboard accessible both locally and over the internet.

The architecture uses Ansible-managed Docker containers feeding data via MQTT into InfluxDB and
Grafana, with Home Assistant for automation and alerting. The design draws from industrial, marine,
and automotive engineering practice — see Section 9.3 for full details.

---

### Operator Note — Working Style

**Steve (ve7cbh) has dyslexia with transpositional errors.** This has practical implications for all CLI work:

- Transpositional errors are the primary issue — characters, numbers, and flags get swapped
  (e.g. `-r 0` becomes `-r 0`, `slave 1` becomes `slave 2`, register `12544` becomes `12454`)
- When introducing a command with multiple flags for the first time, annotate each flag inline
  so the purpose is clear — e.g.:
  `mbpoll -m tcp`  ← protocol
  `-a 1`           ← slave address
  `-t 0`           ← coil data type
  `-r 0`           ← register (0-based with -0 flag)
  `-0`             ← use literal/direct addressing
  `192.168.88.12`  ← device IP
  `-p 4001`        ← port
  `-- 1`           ← value to write
- Once a command pattern is established and familiar, annotation is not needed
- When unexpected results occur, check for transposition first before assuming device or config error
- Over time these patterns will move to long-term memory — annotation is a bridge, not a crutch

---

### 1.1  Phase Status

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

## 2  Hardware

### 2.1  Beelink J45 (Control Node)

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
| Access | SSH from Windows workstation (192.168.88.2) |
| IP | 192.168.88.3 (ethernet enp1s0) — WiFi disabled |

### 2.2  Software on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |
| rtl-433 | Latest (host + Docker container) |
| rtl-sdr | Latest (provides rtl_eeprom, udev rules) |
| mosquitto-clients | Latest (mosquitto_sub / mosquitto_pub CLI) |
| mbpoll | Latest (Modbus TCP/RTU CLI diagnostic tool) |
| sqlite3 | Latest (host — WeeWX archive queries) |
| gpsd | Latest (GNSS daemon — feeds HA GPSD integration) |
| gpsd-clients | Latest (gpsmon, cgps diagnostic tools) |

### 2.3  RTL-SDR Dongles

| Unit | Tuner | Serial | Container | Status |
|---|---|---|---|---|
| RTL-SDR Blog V3 (aluminium, SMA) | R820T | 1024 | rtl433 | ✅ Active — primary |
| Clone (DVB-T) | R828D | 00000001 | rtl433b | ✅ Active — secondary |

**Notes:**
- Both containers pin to dongle via `-d <serial>` — immune to device index changes on reboot
- USB path in compose: `/dev/bus/usb:/dev/bus/usb` (whole bus passthrough)
- PLL not locked warning is benign — always present on both tuners
- Counterintuitively the R828D (generally higher spec) is in the clone, not the Blog V3

### 2.4  Acurite 5n1 Weather Stations

| ID | Channel | Location | Status |
|---|---|---|---|
| 1111 | A | Home base — pole-mounted | Active — primary |
| 291 | C | Mobile — travels with RV | At home — filtered out in weewx.conf |
| Spare | — | — | DOA (HW-12) — replacement pending |

### 2.5  Monitored & Controlled Systems

**Power:**
- EPEVER MPPT60 solar charge controller — Modbus RS-485
- SAMLUX EVO-2212 inverter-charger — Modbus RS-485
- KWS-303L × 2 — AC power meters (grid input, generator input) — RS-485, both on RS-485/3 (slave 1 =
- grid, slave 2 = generator)
- Waveshare Modbus RTU 8-ch Relay / RS485 — shore power load management (HW-13)
- HSR1-25 25A NO relay × 2 — water heater AC (coil 1) and microwave AC (coil 2) (HW-18) — **Normally Open**: coil energised = AC connected; coil de-energised = load off. Fridge AC deferred to coil 3 — wire with Phase 4 tank sensor run.

**Climate Control:**
- ESP32-S3 Touch LCD 4.3 — wall-panel thermostat replacement (HW-20) — Dometic OEM
  thermostat failed; replacement uses Arduino framework + MQTT; A/C and furnace
  controlled via Dometic CCC yellow single-wire serial bus pulse train generated by
  ESP32 (one-way protocol, community reverse-engineered); 12VDC already present at
  thermostat location; cable run ~13 m DMX (140Ω shielded twisted pair); RS-485 back
  to gateway RS-485/4
- Dometic 59516.531 roof A/C — 15,000 BTU, cooling only, no heat pump — all 120VAC
  safety interlocks (hi/lo pressure cutout, OL protector, compressor delay K1)
  self-contained in unit — RVTC controls only the CCC bus demand signal
- Propane furnace — all safeties (sail switch, ignition board, high-limit, gas valve)
  self-contained — RVTC controls only the CCC bus furnace demand signal

**Battery Management (LiFePO4):**
- Battery chemistry: LiFePO4
- EPEVER MPPT60 connected to EVO-2212 External Charger input — EPEVER charges batteries via EVO
- EVO-2212 BMS interface: RJ-45 jack port 6 (front panel) — potential-free contact closure (pins 1–4
- = +, pins 5–8 = −) — RVTC uses Waveshare relay board coil 5 (NO contact) for charge inhibit
- EVO programmed BATTERY TYPE = 1 (Lithium) — activates BMS contact interface on port 6
- Charge inhibit trigger: battery temp <5°C or >45°C — coil 5 closed → EVO displays "CHR STOP BY
- BMS", charging current → 0A, inverting unaffected
- Stop-inverting via BMS contact: NOT automated — EVO internal low-voltage cutoff handles deep
- discharge protection
- Battery temperature primary source: EPEVER RTS sensor register (DC-powered, always live);
- secondary/cross-validation: EVO-2212 temp sensor register — inhibit if either reads out of
- range, resume only when both in range
- Battery heater: greenhouse seed mat (~20W, 120VAC) — Waveshare relay board coil 6 (NO contact,
- direct 120VAC switching <1A, well within 10A contact rating) — heater ON at <10°C, OFF at >15°C
- — ESP32-autonomous, no HA dependency

**Tanks:**
- Fresh, Grey1, Grey2, Black — exterior sensors on plastic tanks
- Propane — 2 × 30 lb tanks — load cell method

**Water Inlet (Solsante V1.5 subset — club demo):**
- Supply pressure (0–0.6 MPa RS-485 transducer)
- Filter ΔP (0–0.1 MPa pair)
- Flow rate (pulse-output meter)
- Turbidity (Seeed S-DTS210-01 RS-485 Modbus)
- Enclosure temperature (DS18B20)

**Weather:** 433 MHz sensor network via WeeWX + RTL-SDR (dual dongle). WN90LP RS-485 Modbus station
(HW-16) ordered — will replace Acurite 5n1 long term.

### 2.6  Waveshare 8-Ch RS485 Gateway

ASIN B0F5WXX4ZQ — 8-port RS-485 to Ethernet, Modbus RTU/TCP, MQTT gateway, industrial isolation,
PoE.
**Status: In hand — commissioning next session (HW-01)**

NOTE:  Where ever possible every device mounted in the RV will be accessed by a wired connection.
Wireless esp32Home will be used for controlling minor
things such as remote lighting and the sdr dongles for use as required. If this requires more than
one device per 485 channel
then so be it.  RS-485 is the interface of choice for this project, IP networks notwithstanding.  

| Port | IP | TCP | Purpose | Device(s) | Phase |
|---|---|---|---|---|---|
| RS-485/1 | 192.168.88.5 | 4001 | Power — Solar | EPEVER MPPT60 (RJ45 D+ 4, D- 6) | 3 | Baud = 115200, CONNECTED - TEST OK
| RS-485/2 | 192.168.88.6 | 4001 | Power — Inverter | SAMLUX EVO-2212 (RJ45 D+ 4, D- 5) | 3 | CONNECTED - TEST OK
| RS-485/3 | 192.168.88.7 | 4001 | Power — AC meters | KWS-303L grid (slave 1) + KWS-303L generator (slave 2) | 3 | Grid CONNECTED - TEST OK; generator meter pending physical wiring — set to slave 2 on bench before install; single RS-485 pair into power cabinet
| RS-485/4 | 192.168.88.8 | 4001 | Climate — Thermostat panel | ESP32-S3 Touch LCD 4.3 (HW-20) | 3 | Reserved — cable to be fished (~13 m DMX); 12VDC present at panel location
| RS-485/5 | 192.168.88.9 | 4001 | Water sensors | Pressure + Filter ΔP + Turbidity | 5 |
| RS-485/6 | 192.168.88.10 | 4001 | GNSS | E108-GN03G-485 position/time receiver | 3 | Device in hand, awaiting install
| RS-485/7 | 192.168.88.11 | 4001 | Weather station | WN90LP (HW-16) | 3 | Shipped
| RS-485/8 | 192.168.88.12 | 4001 | Power — Load shed | Waveshare 8-ch relay board (HW-13) | 3 | COMMISSIONED — all 8 coils verified via mbpoll coil scan 2026-06-19

> **NOTE — gateway addressing scheme:** every channel on this gateway answers Modbus TCP on **port
> 4001**;
  channels are distinguished by **IP only** (192.168.88.5–12), not by port. The unit is effectively
  two separate
  Modbus TCP gateways in one enclosure, so per-port TCP numbering (4002/4006/4007/4008, as appeared
  in earlier drafts)
  does not work — corrected throughout this document 2026-06-17.
  **NOTE - EPEVER baud rate:** Set at 115200 as this is also the same 485 network that talks to its
  OEM remote control.
  **NOTE - WAVESHARE 8 channel relay board:** +5VDC supplied by EPEVER MPPT controller.  Unit
  complains if too many relays
   are turned on at once - possible not enough power or a back emf issue - Confirmed that the solar
   controller does not have
   the current reserve to power the relay board - need to install a DC-DC converter (in hand)

### 2.7  IMU / Compass Module

**Device:** diymore 10-axis IMU — L3GD20 (3-axis gyroscope) + LSM303D (3-axis accelerometer + 3-axis
magnetometer). Marketed as "10DOF" with a bundled barometric sensor; effective DOF for RVTC purposes
is 9 (gyro + accel + mag).
**Interface:** I²C to a dedicated ESP32-S3 node running Arduino framework (not ESPHome — see integration path below).
**Status: Ordered 2026-06-12 — HW-17**

**Primary use case — True North heading reference:**
The magnetometer provides a stable heading reference when the RV is stationary. This is the gap the
GNSS (HW-10) cannot fill: GNSS course-over-ground is undefined at rest. A reliable heading reference
enables:

- **WN90LP wind direction correction** — the WN90LP reports wind direction relative to its own mounting orientation, which changes every time the RV is parked. The IMU heading allows the Phase 7 fusion layer to apply a rotation offset and publish `windDir` referenced to true north regardless of RV orientation.
- **Map orientation correction** — position display pages and dashboards can orient correctly without manual compass input.
- **Sensor fusion anchor** — heading is a first-class field in the Phase 7 normalised MQTT schema.

**Secondary use case — RV levelling display and moving map (cab display):**
The ESP32 node serves a self-contained web page showing live heading, pitch, and roll. Any browser
on the RV MikroTik LAN (phone, tablet, cab display in tow vehicle) can connect without installing
an app. This is a convenience/UI function only — it has no role in any protection or control logic.

When HW-10 (GNSS) is commissioned and publishing to MQTT, the web page will be extended to include
RV position and a moving map via Leaflet.js (OI-30). The cab display in the tow vehicle connects
to the RV MikroTik WiFi while driving and browses `http://imu.lan/` — position updates at 1 Hz via
the ESP32's MQTT subscription to `rvtc/sensors/gnss/latitude` and `longitude`. Map tiles TBD:
cached for offline use or live when data connection available.

**Why a standalone magnetometer is viable here:**
The RV has an aluminium trailer frame on a steel chassis. With the sensor mounted ~2 m above the
steel frame, the residual magnetic interference is consistent and static — equivalent to the
compass-boxing technique used on steel-hulled vessels. A one-time hard-iron calibration
(figure-eight rotation, constants baked into the sketch) removes the fixed offset. The calibration
holds indefinitely as long as the mounting position does not change.

**Integration path — three independent output channels:**

1. **RS-485 Modbus RTU (primary — wired):** ESP32 acts as Modbus slave (ID 10, 9600 8N1) on a Waveshare gateway port. J45 polls heading/pitch/roll as holding registers 0–2 (scaled ×10, signed int16) via Modbus TCP, identical to EPEVER/SAMLUX/KWS-303L. This is the authoritative path for Phase 7 sensor fusion.
2. **MQTT over WiFi (secondary — convenience):** ESP32 also connects to the MikroTik RV LAN and publishes to Mosquitto on the J45 at 1 Hz — topics `rvtc/sensors/imu/heading`, `pitch`, `roll`, `status`. WiFi is a deliberate, bounded exception to the wired-first policy: the levelling display is a UI convenience with no control or protection dependency. WiFi loss has zero effect on the Modbus path.
3. **Built-in web page (secondary — convenience):** ESP32 serves a levelling display page on port 80 at its static IP. Auto-refreshes at 1 Hz via JavaScript fetch to `/api/imu` (JSON endpoint on the ESP32). No app required — works in any browser including phone and cab display.

**Calibration:**
Hard-iron offsets must be derived via a Python script run against raw I²C magnetometer readings, then set as constants (`HARD_IRON_X/Y/Z`) in the sketch and reflashed. Until calibrated, the MQTT `rvtc/sensors/imu/status` topic publishes `UNCALIBRATED` and heading should not be used for OI-36 wind direction correction. The OLED and web page display heading regardless of calibration state for levelling purposes (pitch/roll are unaffected by calibration).

**Modbus register map:**

| Register (0-based) | Field   | Scale | Range     |
|--------------------|---------|-------|-----------|
| 0                  | Heading | ×0.1° | 0–3599   |
| 1                  | Pitch   | ×0.1° | −900–900 |
| 2                  | Roll    | ×0.1° | −900–900 |

```bash
# Verify via gateway (replace IP with assigned port address):
mbpoll -m tcp -a 10 -t 4:int16 -r 0 -c 3 -0 192.168.88.XX -p 4001
```

**Notes:**
- The L3GD20 gyroscope is not used in the current firmware — accel/mag is sufficient for stationary heading and levelling. Gyro axes remain available for future transit shock/vibration logging.
- The barometric sensor sometimes bundled with this module is superseded by WN90LP (HW-16) — ignore if present.
- Firmware: `config/imu_node.ino` (Arduino framework). See `IMU_config.md` for full sketch and calibration procedure.

### 2.8  Waveshare 8-Channel RS-485 Relay Board — Load & Energy Management

**Device:** Waveshare Modbus RTU 8-ch Relay Module (RS-485 interface)
**Interface:** RS-485 Modbus RTU via Waveshare 8-Ch RS485 Gateway, port RS-485/8 (TCP 4001)
**IP:** 192.168.88.12 (gateway port RS-485/8), TCP 4001, slave 1
**Status: COMMISSIONED — all 8 coils verified 2026-06-19 (HW-13 ✅)**

**Modbus coil addressing:**
- Data type: discrete output coils (FC 01 read / FC 05 write)
- Addresses: **0-based PDU — requires `-0` flag with mbpoll for writes**
- Register 0 = coil 1, register 1 = coil 2, etc.
- Read all coils: `mbpoll -m tcp -a 1 -t 0 -r 1 -c 8 192.168.88.12 -p 4001`
- Write coil 1 ON: `mbpoll -m tcp -a 1 -t 0 -r 0 -0 192.168.88.12 -p 4001 -- 1`
- Write coil 1 OFF: `mbpoll -m tcp -a 1 -t 0 -r 0 -0 192.168.88.12 -p 4001 -- 0`
- Full 8-channel cycle test (relay_test.sh) passed 2026-06-19
- **NOTE:** Initial commissioning incorrectly documented as 1-based without `-0`. Corrected 2026-06-28 after live wiring test.

**Relay configuration — all Normally Open (NO):**
Coil energised (1) = contact closed = load active. Coil de-energised (0) = contact open = load off /
fallback. Fail-safe direction on any fault: all loads off. HSR1-25 rated 100% duty cycle —
continuous energisation not a concern.

**Complete coil assignment — NC (Normally Closed) wired:**
Coil de-energised (0) = contact closed = load ON (normal state).
Coil energised (1) = contact open = load OFF (shed state).
Fail-safe on comms/power loss: loads remain ON. This is intentional for shore power loads
that have no fallback — losing the microwave or water heater on a relay board failure is
acceptable; having them unexpectedly drop is not.

| Coil | Register (-0) | Load | Contact type | Normal state | Shed state |
|---|---|---|---|---|---|
| 1 | r 0 | Water heater AC | HSR1-25 NC wired | Coil OFF = load ON | Coil ON = load OFF |
| 2 | r 1 | Microwave AC | HSR1-25 NC wired | Coil OFF = load ON | Coil ON = load OFF |
| 3 | r 2 | Fridge AC | HSR1-25 NC wired | Coil OFF = load ON | Future — Phase 4 tank run |
| 4 | r 3 | Spare | — | — | Future use |
| 5 | r 4 | EVO-2212 BMS charge inhibit | Direct NO contact | Coil OFF = charging allowed | Coil ON = charge inhibit |
| 6 | r 5 | Battery heater (120VAC seed mat) | Direct NC contact | — | HW-22 |
| 7 | r 6 | Spare | — | — | Future |
| 8 | r 7 | Spare | — | — | Future |

**Coils 3, 4, 7, 8 — Spare:**
These four channels are unassigned. HVAC control (furnace and A/C) is handled entirely
by the ESP32-S3 via the Dometic CCC serial bus — no relay board involvement. Coils 3 and
4 are available for future expansion.

**Coil 5 — EVO-2212 BMS charge inhibit:**
Wired to EVO-2212 front panel RJ-45 jack port 6 ("Battery Temp Sensor") — pins 1–4 (+) and pins 5–8
(−). EVO programmed BATTERY TYPE=1 (Lithium) activates this interface. Contact closed → EVO displays
"CHR STOP BY BMS", charging current drops to 0A. Inverting is unaffected. Contact open → normal
charging resumes. Stop-inverting via this contact is NOT used — EVO internal low-voltage cutoff
handles deep discharge.

**Coil 6 — Battery heater:**
Greenhouse seed mat ~20W, 120VAC. Direct relay contact switching (<1A, well within 10A contact
rating). ON at battery temp <10°C, OFF at >15°C (hysteresis).

---

### 2.10  RVTC Load & Energy Management Architecture

This section documents the complete tiered control logic governing all managed loads. The
architecture separates ESP32-autonomous protection (no HA dependency) from HA-orchestrated
intelligence.

**Design principles:**
- Physical protection must not depend on HA being up
- ESP32 holds last-known setpoints and executes all Tier 1 and 2 logic if HA is down
- HA adds intelligence, priority sequencing, logging, and dashboards on top
- A/C compressor is protected: minimum 5-minute software guard before restart; never hard-killed on
- 120VAC side
- Stop-inverting is never automated — EVO internal cutoffs handle deep discharge
- All thresholds provisional — expect tuning once system is live

**Power source context:**
The EVO-2212 is a true online UPS. It stays synchronised to grid or generator line frequency,
transfers to inverter in 1–3 ms on loss of AC input, and re-syncs and transfers back when AC
returns. Loads never see a power interruption. The trigger for load management is therefore EVO
operating mode (from Modbus status register), not AC voltage presence/absence.

**Tier 1 — Source-based protection (ESP32-autonomous, instant):**

Trigger: EVO-2212 Modbus status register = inverting mode (battery carrying the load)

Actions (simultaneous):
- Coil 1 ON → water heater off (contact opens, NC wired)
- Coil 2 ON → microwave off (contact opens, NC wired)
- ESP32 sends CCC off command → A/C controlled shutdown

Restore: EVO returns to passthrough/charging mode
- Coil 1 OFF → water heater on
- Coil 2 OFF → microwave on
- ESP32 sends CCC on command (after 5-minute guard) → A/C restart

**Tier 2 — Temperature-based protection (ESP32-autonomous):**

Battery charge inhibit:
- Trigger: EPEVER RTS temp <5°C OR >45°C (confirmed by EVO temp sensor)
- Action: Coil 5 closed → EVO charge inhibit ("CHR STOP BY BMS")
- Restore: Both sensors within range → coil 5 open
- Inverting unaffected throughout

Battery heater:
- Trigger: Battery temp <10°C
- Action: Coil 6 on → seed mat heater energised (120VAC)
- Off: Temp >15°C → coil 6 off
- Operates on any power source including inverter (mat is <20W, negligible battery draw)
- Prevents battery reaching charge-inhibit threshold in normal conditions

**Tier 3 — Overload protection (HA-orchestrated, grid/generator only):**

Active only when EVO is in passthrough mode (Tier 1 not triggered).

Trigger: KWS-303L current sustained above threshold for >30 seconds (debounce — ignore spikes).

Step sequencing — shed in priority order, wait between steps:

Grid overload (KWS-303L slave 1, reg 18):
- Trigger: >25A sustained 30s
- Step 1: Coil 1 ON (water heater off). Wait 60s. Re-measure.
- Step 2: If still >22A → coil 2 ON (microwave off). Wait 60s. Re-measure.
- Step 3: If still >20A AND A/C running → ESP32 CCC off command. Last resort only.
- Log event.
- Restore water heater: current <20A → coil 1 OFF
- Restore microwave: current <20A with WH restored → coil 2 OFF
- Restore A/C: current <18A sustained 3 min AND 5-minute guard elapsed → ESP32 CCC on

Generator overload (KWS-303L slave 2, reg 18):
- Trigger: >22A sustained 30s
- Step 1: Coil 1 ON (water heater off). Wait 60s.
- Step 2: If still >19A → coil 2 ON (microwave off). Wait 60s.
- Step 3: If still >17A AND A/C running → ESP32 CCC off command. Last resort.
  Log event.
- Restore thresholds: WH <18A, microwave <18A, A/C <16A sustained 3 min + 5-min guard

A/C shed rules (any Tier 3 condition):
- Never shed on a spike — 30s sustained minimum before A/C considered
- 5-minute software guard before any A/C restart (in addition to K1 hardware delay in unit)
- Every A/C shed logged to InfluxDB as a discrete event
- Never shed A/C via 120VAC interruption — always via CCC demand signal only

**Tier 4 — SOC-based protection (HA-orchestrated, inverter mode only):**

Active when EVO is inverting (Tier 1 already shed water heater and fridge).

Trigger: Battery SOC falling below threshold while on inverter (EPEVER Modbus SOC register).
- SOC threshold TBD — depends on confirmed battery bank capacity
- Action: ESP32 CCC off command → A/C controlled shutdown
- Restore: SOC recovers above upper threshold OR AC source returns (Tier 1 restore handles the
- latter)

**HA role in load management:**
HA is the correct place for Tier 3 and Tier 4 logic — it holds all sensor data simultaneously and
can make priority decisions. HA is also the climate entity for setpoint management and HVAC
scheduling. If HA is down: Tier 1 and Tier 2 execute autonomously via ESP32, A/C runs at last-known
setpoint, Tier 3/4 overload protection is inactive (acceptable — the EVO's own protections remain
active).

**Architecture exception — HA as actuator:**
RVTC's general design principle is HA as data consumer only. Load management and HVAC are
deliberate, bounded exceptions: HA writes to relay coils (via Modbus) and sends MQTT commands to the
ESP32 for Tier 3/4 and HVAC control. This is appropriate because HA is the only place where all data
streams (power, temperature, SOC, HVAC state) converge for intelligent decision-making.

### 2.9  SAMLUX EVO-2212 — Communications Confirmed

**Status:** Commissioned and addressing fully resolved 2026-06-17 — Modbus TCP/RTU communications
validated end-to-end via gateway RS-485/2.

**Connection:**
- Gateway channel: RS-485/2, IP 192.168.88.6, TCP 4001 (Section 2.6)
- Modbus slave/unit address: 1 (01H, manufacturer default — confirmed correct as-is)
- Serial settings on gateway: 9600 8N1 (matches EVO-series manual spec)

**Address convention — corrected later the same session (post mortem on a false lead):**
An initial block scan appeared to show every register shifted by +1 from the manual's
literal hex address, and that "+1 rule" was briefly documented and applied to the YAML.
It was wrong. Root cause: `mbpoll` defaults to classic Modicon-style 1-based reference
numbering and silently subtracts 1 from whatever is passed to `-r` before putting it on
the wire — the `-0` flag disables that and addresses the literal PDU register directly.
The initial polls omitted `-0`, so every address typed was actually being sent on the wire
one lower than intended, which looked exactly like a device-side +1 offset. Re-polling the
same three registers with `-0` returned the same real-world values one register address
lower, confirming there is **no real offset** — the manual's hex address, converted straight
to decimal, is the correct wire/PDU address, exactly as the manual's own 03H worked example
showed all along.

> **Takeaway for future Modbus work in this project:** when using `mbpoll`, always
> pass `-0` so its addressing matches both the manual and Home Assistant's `pymodbus`-based
> Modbus integration (which addresses literally by default). Skipping `-0` will look like
> a consistent off-by-one device quirk and is a known, common pitfall in the Modbus
> ecosystem (sometimes called the "Modbus Shuffle") — not specific to SAMLUX.

**Registers confirmed working (read-only, addresses are literal/direct, no offset):**

| Field | Address | Scale | Confirmed value | Cross-check |
|---|---|---|---|---|
| Voltage of Grid Input | 261 | ×0.01 V | 119.03 V | Matches known ~119 VAC |
| Input Current | 262 | ×0.01 A | 4.41 A | Matches known ~4 A load |
| Battery Voltage | 276 | ×0.001 V | 13.005 V | Consistent across two separate readings (13.03V, 13.005V) |

**Tooling:** `mbpoll` added to required packages and to the `common` Ansible role's package
list (Section 2.2, Section 6.3) — installed manually on the J45 for now, pending next
`common` role run.

**Home Assistant integration:** Drafted as `modbus_samlux.yaml`, managed manually for now
(same pattern as `weewx.conf`) rather than templated via Ansible — held outside this
repo's tracked config until the register list stabilizes.

**Scope decision:** Read-only telemetry registers only. The EVO-series also exposes a large block of
Read/Write configuration parameters (absorb voltage, equalization voltage, voltage cutoffs, GEN
timing, relay function, comm ID, etc.) — intentionally deferred. Programming/write registers will
not be touched until read-side polling is fully validated and trusted; this will be a separate,
later phase of work.

**Ansible role status:** The `samlux` role (RVTC Ansible Role Structure Document V0.1,
Section 5i) was blocked on OI-03 pending protocol confirmation. **OI-03 is now resolved**
(see Section 7.1) — protocol confirmed as Modbus RTU over RS-485 via the Waveshare gateway,
slave address 1, literal/direct addressing (no offset). Role design can proceed in principle
but is intentionally deferred until the read-only register set stabilizes and the
write-register scope is defined separately.

---

## 3  Network

### 3.1  IP Allocation

| IP           | Device           | Notes |
|---|---|---|
| 192.168.88.1 | MikroTik gateway | Primary router |
| 192.168.88.2 | Windows workstation | SSH client |
| 192.168.88.3 | Beelink J45 (enp1s0) | All services — primary IP |
| 192.168.88.4 | J45 WiFi (wlp3s0) | Disabled — autoconnect=no, radio off |
| 192.168.88.5 | Waveshare RS-485 gateway Ch-1 | EPEVER MPPT-60 — pending commissioning |
| 192.168.88.6 | Waveshare RS-485 gateway Ch-2 | SAMLUX EVO-2212 — commissioned 2026-06-17 |
| 192.168.88.7 | Waveshare RS-485 gateway Ch-3 | KWS-303L grid (slave 1) + generator (slave 2) — grid commissioned 2026-06-19 |
| 192.168.88.8 | Waveshare RS-485 gateway Ch-4 | ESP32-S3 Touch LCD thermostat panel (HW-20) — reserved, cable pending |
| 192.168.88.9 | Waveshare RS-485 gateway Ch-5 | Water sensors — Phase 5 |
| 192.168.88.10| Waveshare RS-485 gateway Ch-6 | GNSS E108-GN03G-485 — device in hand, pending install |
| 192.168.88.11| Waveshare RS-485 gateway Ch-7 | WN90LP weather station — shipped |
| 192.168.88.12| Waveshare RS-485 gateway Ch-8 | Waveshare 8-ch relay board — commissioned 2026-06-19 |
| 192.168.88.13–19 | — | Reserved — future wired devices |
| 192.168.88.20| ESP32-S3 IMU node (HW-17) | WiFi — levelling web page + MQTT secondary path; RS-485 Modbus slave on gateway port TBD |
| 192.168.88.21| ESP32-S3 Touch LCD thermostat (HW-20) | WiFi — reserved; primary connection is RS-485/4 (192.168.88.8) |
| 192.168.88.22| ESP32-S3 Water sensor node (HW-06) | WiFi — reserved; Phase 5 |
| 192.168.88.23–29 | — | Reserved — ESP32 WiFi nodes, future expansion |

> **NOTE — ESP32 WiFi address block:** 192.168.88.20–29 is reserved exclusively for ESP32 nodes
> with WiFi secondary paths. All are DHCP-reserved by MAC address in MikroTik. WiFi is a
> convenience/UI path only for all nodes in this block — RS-485 Modbus RTU is the primary wired
> connection for each. Static IPs set in sketch `WIFI_STATIC_IP` must match MikroTik DHCP
> reservation.

### 3.2  Pi-hole DNS (.lan records)

All local DNS records use `.lan` TLD. The `.local` TLD was abandoned due to mDNS/Avahi conflicts.
**Always use `http://` prefix** — bare `.lan` names are intercepted as search queries.

| Domain | IP | Notes |
|---|---|---|
| weewx.lan | 192.168.88.3 | nginx reverse proxy — Belchertown skin |
| grafana.lan | 192.168.88.3 | nginx reverse proxy |
| influxdb.lan | 192.168.88.3 | nginx reverse proxy |
| homeassistant.lan | 192.168.88.3 | nginx reverse proxy |
| pihole.lan | 192.168.88.3 | nginx reverse proxy (no password) |
| imu.lan | 192.168.88.20 | ESP32-S3 IMU node — levelling web page direct (no nginx proxy) |

### 3.3  Web UIs

| Service | Internal URL | Notes |
|---|---|---|
| WeeWX | http://weewx.lan | Belchertown skin (dark mode) |
| Grafana | http://grafana.lan | Dashboard needs rebuilding (OI-16) |
| InfluxDB | http://influxdb.lan | |
| Home Assistant | http://homeassistant.lan | Onboarding not yet complete (OI-15) |
| Pi-hole | http://pihole.lan | |
| IMU / Levelling | http://imu.lan | ESP32-S3 direct — heading, pitch, roll |
| WeeWX (club LAN) | http://wifi.solsante.com:8080 | via club router + MikroTik dst-nat |

### 3.4  MikroTik Router

Config file: `config/rv-mikrotik-config.rsc` (updated 2026-06-09, ether8 + pinhole fixes)
DNS: Primary 192.168.88.3 (Pi-hole), secondary 8.8.8.8. DHCP hands Pi-hole IP to all clients.

**External WeeWX access path:**
```
wifi.solsante.com:8080 → club router → MikroTik rogers-wan:80 → dst-nat → 192.168.88.3:80 → nginx → WeeWX
```

> **NOTE:** Updated RSC committed but not yet loaded onto physical router — router is live and
> working, do not touch until a planned maintenance window. Pending changes in the committed RSC:
> - ether8 fix
> - pinhole fix
> - DHCP pool changed from `192.168.88.10-254` to `192.168.88.100-254` (splits address space:
>   .1–.99 static by design, .100–.254 dynamic for transient clients)

---

## 4  Docker Stack

> **CRITICAL:** Always run `docker compose up/down` from `~/RV-total-control/` — this is
> the canonical compose file location. Running from `/data/docker/volumes/` puts containers
> on the wrong network (`volumes_default` instead of `rvtc_net`) and breaks inter-container DNS.

**Docker network:** `rvtc_net`
**Compose file:** `~/RV-total-control/docker-compose.yml`

### 4.1  Running Containers

| Container | Image | Port(s) | Volume / Notes |
|---|---|---|---|
| mosquitto | eclipse-mosquitto | 1883 | /data/docker/volumes/mosquitto |
| influxdb | influxdb:2 | 8086 | /data/docker/volumes/influxdb |
| grafana | grafana/grafana | 3000 | /data/docker/volumes/grafana — user: 472:472 |
| rtl433 | hertzg/rtl_433:latest | — | SN 1024 (Blog V3) — primary |
| rtl433b | hertzg/rtl_433:latest | — | SN 00000001 (clone) — secondary |
| weewx | felddy/weewx | — | /data/docker/volumes/weewx |
| nginx | nginx:alpine | 80 | weewx public_html (ro) + nginx.conf |
| homeassistant | ghcr.io/home-assistant/home-assistant | 8123 | /data/docker/volumes/homeassistant |
| pihole | pihole/pihole | 8880 (web), 53 (DNS) | /data/docker/volumes/pihole — listeningMode=all |

### 4.2  rtl_433 Container Configuration

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

- WeeWX subscribes to `rtl_433/+/events` — wildcard receives from both containers
- Both containers decode the same sensors — duplicate packets to WeeWX are benign; deduplication is
- a Phase 7 concern
- `+` wildcard is valid in MQTT subscribe but **not** in publish topics
- `-M si` does not convert Acurite 5n1 field names — they always publish `temperature_F` and `rain_in`

### 4.3  Grafana Notes

- Dashboard lost after reboot 2026-06-09 due to volume permissions issue
- Fix applied: `user: "472:472"` in docker-compose.yml
- If dashboard missing after restart: `sudo chown -R 472:472 /data/docker/volumes/grafana`
- Dashboard still needs rebuilding (OI-16)

---

## 5  WeeWX Configuration

### 5.1  Key Settings

| Setting | Value |
|---|---|
| Config (host) | /data/docker/volumes/weewx/weewx.conf |
| Config (container) | /data/weewx.conf |
| Management | Manual on host — copy committed to config/weewx.conf in repo |
| Driver | MQTTSubscribeDriver — subscribes to rtl_433/+/events |
| Station | ve7cbh, 48.6686N, 123.6002W, 46m |
| Units | METRICWX (°C, mm, m/s) via StdConvert target_unit = METRICWX |
| Archive interval | 2.5 min (150 seconds) |
| Time zone | America/Vancouver |
| Skin | Belchertown (dark mode) — output at /data/public_html/belchertown |
| InfluxDB writer | Custom influxdb2.py at /data/docker/volumes/weewx/bin/user/ |
| InfluxDB target | host=influxdb, org=rvtc, bucket=rvtc, measurement=weewx |
| PyEphem | Installed — civil twilight and extended celestial data available |
| ID filter | filter_out_message_when = 291 (excludes Port Renfrew unit) |

### 5.2  Field Mappings (MQTTSubscribeDriver)

```ini
[[[[temperature_F]]]]
    name = outTemp
    units = degree_F          # StdConvert handles F→C automatically

[[[[humidity]]]]
    name = outHumidity

[[[[wind_avg_km_h]]]]
    name = windSpeed
    units = km_per_hour

[[[[wind_dir_deg]]]]
    name = windDir

[[[[rain_in]]]]
    ignore = false
    name = rain
    units = inch
    contains_total = true     # CRITICAL — Acurite 5n1 sends cumulative bucket counts
```

> **CRITICAL:** `contains_total = true` is essential for rain. Without it every cumulative
> reading adds to the total, producing phantom rain accumulation. The ID filter
> (`filter_out_message_when = 291`) is set but not yet tested under live rain conditions.

### 5.3  Database

```
Archive DB (host): /data/docker/volumes/weewx/archive/weewx.sdb
sqlite3 is on the host — not inside the WeeWX container
```

**Useful queries:**
```bash
# Recent archive records
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime,'unixepoch','localtime') as ts, rain, rainRate FROM archive ORDER BY dateTime DESC LIMIT 20;"

# Daily rain summary
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime,'unixepoch','localtime') as ts, sum, max, count FROM archive_day_rain ORDER BY dateTime DESC LIMIT 14;"
```

**Rebuild daily summaries after archive edits:**
```bash
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=YYYY-MM-DD --yes
```

> **NOTE:** InfluxDB bucket flushed 2026-06-03 — clean metric data from ~15:35 UTC onward only.
> WeeWX SQLite archive retains full history.

### 5.4  Known WeeWX Issues

- **OI-32:** Upstream bug — `contains_total=true` + hardware fault → corrupted
  archive_day_rain → silent stats failure. Bug report pending.
- **HW-14:** Rain gauge physical inspection at club still required.
- ID filter (`filter_out_message_when = 291`) not yet tested under live rain conditions.

---

## 6  Ansible & Repository

### 6.1  Configuration Files

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

### 6.2  group_vars / host_vars

- `group_vars/all/all.yml` — all non-sensitive variables
- `group_vars/all/vault.yml` — ansible-vault encrypted, contains:
  - vault_influxdb_user / vault_influxdb_password
  - vault_grafana_user / vault_grafana_password
  - vault_pihole_user / vault_pihole_password
  - vault_influxdb_token
- `host_vars/localhost.yml` — J45-specific overrides
  - **NOTE:** filename must match inventory hostname (`localhost`, not `rvtc` or `ve7cbh-control`)

### 6.3  Roles

| Role | Purpose / Notes |
|---|---|
| common | OS baseline, Docker idempotency, UFW firewall, WiFi disable, dvb_usb blacklist, rtl-sdr + sqlite3 + mbpoll |
| mosquitto | Eclipse Mosquitto MQTT broker |
| influxdb | InfluxDB 2.x time-series database |
| grafana | Grafana dashboards — user 472:472 baked in |
| rtl433 | rtl_433 containers — primary and secondary dongle setup |
| weewx | WeeWX weather engine — weewx.conf managed manually on host |
| nginx | Reverse proxy for all .lan domains |
| homeassistant | Home Assistant — onboarding and MQTT integration pending (OI-15) |
| pihole | Pi-hole DNS — listeningMode=all required |

### 6.4  Repository Structure

```
RV-total-control/
├── ansible.cfg
├── config/
│   ├── Mikrotik Failover.md
│   ├── nginx.conf                       # committed 2026-06-09
│   ├── rv-mikrotik-config.rsc           # updated 2026-06-09
│   ├── rv-mikrotik-config_ether8_fix.rsc
│   ├── rvtc-ambient.yml
│   ├── temp_press_flash.yml
│   └── weewx.conf                       # committed 2026-06-09
├── docker-compose.yml                   # canonical — always run from here
├── docs/
│   └── [session context and summary files]
├── group_vars/all/
│   ├── all.yml
│   └── vault.yml
├── host_vars/
│   └── localhost.yml
├── inventories/production/
│   └── hosts.ini
├── roles/
│   ├── common/
│   ├── mosquitto/
│   ├── influxdb/
│   ├── grafana/
│   ├── rtl433/
│   ├── weewx/
│   ├── nginx/
│   ├── homeassistant/
│   └── pihole/
├── phase2.yml
├── site.yml
└── README.md
```

### 6.5  Key Paths

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root — **always run docker compose from here** |
| `~/RV-total-control/docker-compose.yml` | Canonical compose file |
| `~/.vault_pass` | Ansible Vault password — chmod 600, never committed |
| `/data/docker/volumes` | All Docker volume data |
| `/data/docker/volumes/weewx/weewx.conf` | WeeWX live config |
| `/data/docker/volumes/weewx/bin/user/influxdb2.py` | Custom InfluxDB writer |
| `/data/docker/volumes/weewx/archive/weewx.sdb` | WeeWX SQLite archive |
| `/data/docker/volumes/grafana` | Grafana data — must be owned 472:472 |
| `/etc/udev/rules.d/99-rtlsdr.rules` | RTL-SDR udev rules (MODE=0666 override) |
| `/etc/modprobe.d/rtlsdr.conf` | dvb_usb_rtl28xxu blacklist |
| `/etc/apt/sources.list.d/docker.list` | Docker repo — trixie hardcoded (not gigi) |

### 6.6  Known Issues

- **LMDE Docker repo:** `$VERSION_CODENAME` returns `gigi` on LMDE —
  docker.list must hardcode `trixie`
- **GitHub auth:** PAT stored in `~/.git-credentials` via credential.helper store
- **Passwordless sudo:** `/etc/sudoers.d/ve7cbh` — required for Ansible `become: true`
- **host_vars naming:** Must match inventory hostname — file is `host_vars/localhost.yml`
- **weewx.conf:** Managed manually on host. Edit directly and `docker restart weewx`
- **SAMLUX register map:** Full Modbus register map held locally under NDA — never paste into chat
- or commit to repo

---

## 7  Open Items & Backlog

### 7.1  Software / Configuration

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| OI-03 | 3 | SAMLUX 2212 protocol confirmation | ✅ Closed | Originally tracked in RVTC Ansible Role Structure Document V0.1 (Section 8) as blocking the `samlux` role. Resolved 2026-06-17 — confirmed Modbus RTU over RS-485 via Waveshare gateway RS-485/2, slave address 1; +1 register address offset discovered and documented (Section 2.9). `samlux` role design now unblocked, deferred pending stable register list and separate scoping of write/programming registers |
| OI-15 | 2-3 | Home Assistant onboarding | ✅ Closed | Container up — setup wizard + MQTT integration not done |
| OI-16 | 2 | Grafana weather dashboard | ✅ Closed | Lost after reboot 2026-06-09 — needs rebuilding |
| OI-18 | 3 | ESPHome Ansible role | 🟡 Open | nginx block in place; role to be created |
| OI-19 | 2-3 | MQTT Explorer | 🟡 Open | May be superseded by Phase 7 fusion UI |
| OI-20 | 3 | HA multi-site linking | 🟡 Open | VPN prerequisite |
| OI-21 | 3+ | VOIP / PBX inter-site | 🟡 Open | Prerequisite: OI-20 |
| OI-24 | 3 | Load & energy management — full tiered automation | 🟡 Open | Architecture fully locked 2026-06-19 — see Section 2.10. Four tiers: (1) ESP32-autonomous source-based (inverter mode → shed WH+fridge+A/C); (2) ESP32-autonomous temperature-based (charge inhibit + battery heater); (3) HA-orchestrated overload (grid/gen current thresholds, sequential shed WH→fridge→A/C last resort); (4) HA-orchestrated SOC-based (A/C shed on battery depletion while inverting). HA modbus_relay.yaml and ESP32 firmware still to be written. Prerequisites: HW-18, HW-20, HW-21, HW-22 |
| OI-25 | 7 | Phase 7 Sensor Fusion | 🟡 Open | Python fusion service, normalised MQTT schema |
| OI-29 | 3 | GNSS-driven WeeWX position | 🟡 Open | Unblocked 2026-06-29 — HW-10 commissioned. GNSS position available in HA via GPSD integration. |
| OI-30 | 3 | RV position display — moving map on cab display and imu.lan page | 🟡 Open | GNSS position (HW-10) published by J45 to MQTT topics `rvtc/sensors/gnss/latitude` and `rvtc/sensors/gnss/longitude`. Two consumers: (1) IMU web page (`http://imu.lan/`) adds position and a moving map — ESP32 subscribes to GNSS MQTT topics and serves them via `/api/imu` JSON endpoint alongside heading/pitch/roll; (2) cab display in tow vehicle browses `http://imu.lan/` over RV MikroTik WiFi while driving — same page, same data. Map tile rendering TBD: Leaflet.js with cached tiles for offline use, or live tiles when data available. Update rate 1 Hz — adequate for moving map. Prerequisites: HW-10 commissioned, GNSS MQTT topics publishing, IMU node (HW-17) on network. |
| OI-32 | — | WeeWX upstream bug report | 🟡 Open | contains_total=true + hardware fault → silent rain stats failure |
| OI-33 | 3 | Club bridge Pi | 🟡 Open | rtl_433 + WireGuard at club → home J45 hub; prereq: OI-20 |
| OI-34 | 7 | GNSS geofence source inhibit | 🟡 Open | Suppress RV 5n1 when at club; prereq: HW-10, OI-33, Phase 7 |
| OI-35 | 7 | Make weewx webpage dynamicly update.  Requires mqtt websockets enabled in mosquitto broker |🟡 Open |
| OI-36 | 7 | WN90LP wind direction true-north correction pipeline | 🟡 Open | IMU (HW-17) heading → Phase 7 fusion layer → rotation offset applied to WN90LP raw windDir → publish corrected `rvtc/sensors/weather/windDir_true`. IMU node publishes heading via both Modbus RTU (wired primary, gateway poll) and MQTT over WiFi (1 Hz convenience path). Prerequisites: HW-17 commissioned, hard-iron calibration complete (MQTT status = OK), Phase 7 fusion layer. |
| OI-37 | 2/3 | Portainer container management UI | 🟡 Open | Single-pane Docker visibility across containers; consider portainer.lan via nginx; agent mode could later span home J45 + club bridge Pi (OI-33) |
| OI-38 | 3 | ESP32-S3 Touch LCD thermostat — firmware + HA climate integration | 🟡 Open | Replaces failed Dometic OEM thermostat. Arduino framework (not ESPHome — microsecond timing required for CCC pulse train). MQTT to J45 for HA integration. Controls: furnace demand and A/C demand via Dometic CCC yellow wire pulse train. Runs Tier 1/2 protection logic autonomously. Touchscreen shows temp, setpoint, mode, source, SOC, shed status. SSH accessible for manual setpoint override when HA is down. Prerequisite: HW-20 cable run, HW-21, HW-22. |
| OI-39 | 3 | ESP32-S3 Modbus polling — direct reads from EVO/EPEVER/KWS for autonomous protection | 🟡 Open | ESP32 must poll EVO-2212 mode register, EPEVER SOC + RTS temp, KWS-303L grid voltage directly via Modbus TCP to make Tier 1/2 decisions without HA. Polling intervals and register list to be defined at firmware design stage. |
| OI-40 | 3 | GNSS NMEA TCP bridge — OsmAnd external GPS for Android cab display | 🟡 Open | Small Python container on J45 subscribes to `rvtc/sensors/gnss/latitude`, `longitude`, `speed`, `heading` MQTT topics and reformats to NMEA-0183 `$GPRMC` sentences published to a TCP socket on 192.168.88.3:10110. OsmAnd on Android 5" cab display connects to socket over RV MikroTik WiFi and uses it as external GPS source (OsmAnd development plugin — native TCP NMEA support on Android). Prerequisite: HW-10 commissioned and GNSS MQTT topics publishing. Register map of E108-GN03G-485 must be checked at commissioning to confirm available fields (lat, long, speed, course, fix quality, satellite count). Separate from OI-30 (imu.lan map page) — both consume the same GNSS MQTT topics. |

### 7.2  Hardware / Physical Install

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| HW-01 | 3 | Install Waveshare RS485 gateway | ✅ Closed | **IN HAND** — network up, RS-485/2 (SAMLUX) confirmed live 2026-06-17 (Section 2.9); remaining channels pending cabling/commissioning |
| HW-02 | 3 | Build RS-485 cables | ✅ Closed | For SAMLUX EVO-2212 + EPEVER MPPT |
| HW-03 | 3 | Install 4×100W PV panels | ✅ Closed | Get solar data flowing before full array |
| HW-04 | 3 | Wire 9 PV panels (3S×3P ~36V) | ✅ Closed  | Complete solar system |
| HW-05 | 3/5 | Source barometric pressure sensor | ✅ Closed | Covered by WN90LP (HW-16) |
| HW-06 | 5 | Build ESP32 sensor node | 🟡 Open | Pulse water meter, turbidity, pressure ×2, flow |
| HW-07 | 4/5 | Design tank monitoring sensors | 🟡 Open | Sensor types and mounting TBD |
| HW-08 | 3 | Source/install KWS-303L — grid | ✅ Closed | AC power meter, grid input; RS-485 port 3 |
| HW-09 | 3 | Source/install KWS-303L — generator | 🟡 Open | Set to Modbus slave 2 on bench before install. Shares RS-485/3 (192.168.88.7) with grid meter (slave 1) — single RS-485 pair into power cabinet. Generator AC wiring not yet installed. |
| HW-10 | 3 | Install GNSS E108-GN03G-485 | ✅ Closed | Commissioned 2026-06-29. NMEA TCP on 192.168.88.10:4001. gpsd on J45 at 0.0.0.0:2947 (socket drop-in override). gpsd auto-detected u-blox binary protocol. HA GPSD integration live — 3D fix, 21 satellites, Lat/Lon/Mode/Speed/Time all updating. Antenna in non-ideal interior location — roof mount deferred, fix quality acceptable (HDOP 0.6–0.8). |
| HW-12 | — | Replace spare Acurite 5n1 | ✅ Closed | 
| HW-13 | 3 | Waveshare 8-ch RS-485 Modbus relay board — shore power load management | ✅ Closed | Commissioned 2026-06-19 — all 8 coils verified, cycle test passed. Coil 1 = water heater, coil 2 = microwave. **NC wired** (coil ON = load OFF). **0-based addressing with `-0` flag** for mbpoll writes. Port 4001, slave 1, IP 192.168.88.12. HSR1-25 physical wiring complete 2026-06-28. |
| HW-14 | — | Rain gauge inspection/repair | ✅ Closed | 
| HW-15 | 3 | Install POE-SW802-DIN PoE switch | ✅ Closed | Powers Waveshare gateway and bay devices |
| HW-16 | 3 | Ecowitt WN90LP RS-485 Modbus weather station | 🟡 Open | Shipped inc wind, temp, humidity, rain, UV, light, barometric pressure — Waveshare RS-485/7, IP 192.168.88.11, TCP 4001 — closes HW-05 |
| HW-17 | 3/7 | diymore 10-axis IMU (L3GD20 + LSM303D) | 🟡 Open | **Ordered 2026-06-12** — magnetometer heading reference for true-north wind direction correction and map orientation; I²C to ESP32-S3 ESPHome node; one-time hard-iron calibration required; Phase 7 fusion layer consumer |
| HW-18 | 3 | Install HSR1-25 25A NC-wired relay × 2 — water heater AC (coil 1) and microwave AC (coil 2) | ✅ Closed | Wired to NC contact — coil de-energised = load ON (fail-safe: loads stay on if relay board loses power). Coil 1 = water heater (register 0 with -0), coil 2 = microwave (register 1 with -0). Fridge deferred to coil 3, Phase 4 tank sensor run. Driven by Waveshare 8-ch relay board (HW-13 ✅). Physical wiring complete and tested 2026-06-28. |
| HW-19 | 3 | Install 12VDC-5VDC DC-DC converter to power waveshare 8 channel relay board. (Device in hand)
| HW-20 | 3 | ESP32-S3 Touch LCD 4.3 — RV thermostat panel replacement | 🟡 Open | Dometic OEM digital thermostat failed (C$250 replacement cost). Replacement: ESP32-S3 Touch LCD 4.3 running Arduino framework + MQTT. Wall-mounted at existing thermostat location. 12VDC already present. RS-485 back to gateway RS-485/4 (192.168.88.8) via ~13 m DMX cable (140Ω shielded twisted pair). Runs Tier 1 and Tier 2 protection autonomously — SSH accessible for manual setpoint override when HA is down. |
| HW-21 | 3 | Wire EVO-2212 BMS charge inhibit to Waveshare relay board coil 5 | 🟡 Open | RJ-45 plug to EVO front panel port 6 ("Battery Temp Sensor") — pins 1–4 (+) and pins 5–8 (−) to relay board coil 5 NO contact. Potential-free contact closure. EVO must be programmed BATTERY TYPE=1 (Lithium) before wiring. Confirm with mbpoll coil 5 write before connecting to EVO. |
| HW-22 | 3 | Install battery heater (greenhouse seed mat) + wire to coil 6 | 🟡 Open | ~20W 120VAC seed mat mounted under battery bank. Coil 6 NO contact switches 120VAC directly (<1A). Temp thresholds: ON <10°C, OFF >15°C. Temp source: EPEVER RTS register (primary), EVO temp sensor (cross-validation). |

### 7.3  Design / Documentation

| ID | Phase | Item | Status | Notes |
|---|---|---|---|---|
| DD-01 | 3 | System wiring drawing | 🟡 Open | Full system diagram |
| DD-02 | 5 | ESP32 sensor node scope definition | 🟡 Open | Sensor types TBD |
| DD-03 | 7 | Phase 7 sensor fusion architecture document | 🟡 Open | Topic schema, source types, staleness model |
| DD-04 | — | Offline-first audit — self-host all fonts/assets on `.lan` pages | 🟡 Open | RVTC.lan pages must work with zero internet (off-grid is the normal operating condition, not the exception). Found 2026-06-30: draft RVTC landing page used `@import url('https://fonts.googleapis.com/...')` for JetBrains Mono / Inter — fails offline. Action: download and self-host font files (J45 or relevant container), replace all external CDN `@import`/`<link>` references across every custom page (Lovelace dashboards, imu.lan, RVTC landing page) with local copies. Also applies to any JS libs / map tile sources (cross-ref OI-30). See Section 9.3 design-standards note. |

---

## 8  Session Log

### 2026-05-27
Full Phase 2 scaffolding complete. Ansible common role live. `group_vars/all`, `host_vars/localhost`, `site.yml` all created and tested.

### 2026-05-28
Full core stack deployed: Mosquitto, InfluxDB, Grafana, rtl_433, WeeWX, nginx, Home Assistant,
Pi-hole. Acurite 5n1 (ID 1111) live via rtl_433 → MQTT → WeeWX. Full data chain confirmed.

### 2026-05-29
WeeWX → InfluxDB integration working. nginx reverse proxy live with all .lan domains. Pi-hole DNS
operational. MikroTik pinhole configured for external WeeWX access. Grafana RVTC Weather dashboard
built.

### 2026-05-30
Backlog formalised. ESPHome ambient sensor YAML built. Grafana dashboard constructed. Seasons skin
CSS cosmetic fix (OI-14 ✅).

### 2026-05-31
Waveshare RS485 gateway ordered. mosquitto-clients installed. dvb_usb_rtl28xxu conflict and WiFi IP
conflict diagnosed. Steve departing for Port Renfrew.

### 2026-06-02  (Port Renfrew — Starlink)
Stack confirmed fully live from campsite. Mobile Acurite 5n1 (ID 291, Channel C) decoding. Phase 7
Sensor Fusion architecture scoped.

### 2026-06-03  (Port Renfrew — Starlink)
influxdb2.py unit conversion fix (was writing Fahrenheit as Celsius). InfluxDB bucket flushed for
clean data restart. Rain sensor disabled pending investigation.

### 2026-06-05  (Port Renfrew — Starlink)
Rain sensor cumulative fix: `contains_total = true` applied. Root cause confirmed — Acurite 5n1 sends cumulative bucket counts, not incremental rain. Phantom rain accumulation eliminated.

### 2026-06-07  (Port Renfrew — Starlink)
sqlite3 installed on host. archive_day_rain corruption diagnosed and fixed (rebuild-daily). Local DNS migrated `.local` → `.lan` across all configs. Avahi/mDNS conflict with `.local` confirmed as root cause.

### 2026-06-09  (Home base — Rogers)
- Returned from Port Renfrew — trailering caused WeeWX data gap
- Full WeeWX/rtl_433 diagnosis: four simultaneous bugs found — wrong compose directory (network isolation), hardcoded USB path, invalid MQTT publish topic (`+` wildcard), wrong field name mappings (`temperature_C`/`rain_mm` → actual `temperature_F`/`rain_in`)
- RTL-SDR Blog V3 (HW-11) received — antenna missing, could not commission
- Old clone dongle confirmed working as temporary primary
- dvb_usb_rtl28xxu blacklist applied and baked into Ansible common role (OI-23 ✅)
- OI-22, OI-23, OI-26, OI-27, OI-17, OI-28, OI-31 all closed ✅
- Belchertown skin installed with dark mode; PyEphem active
- Grafana user permissions fix applied (472:472 in compose)
- MikroTik RSC updated (ether8 + pinhole fixes)
- **Phase 2 complete — Phase 3 active**

### 2026-06-10  (Home base — Rogers)
- RTL-SDR Blog V3 (SN 1024, R820T): antenna fitted, confirmed on Windows, swapped into J45 as
- primary dongle
- Clone (SN 00000001, R828D) retained and commissioned as secondary — rtl433b container added to
- docker-compose.yml
- Key finding: clone contains R828D tuner (higher spec than assumed); confirmed with `rtl_eeprom`
- Both containers pin by serial via `-d` flag
- Dual dongle confirmed: both decoding Acurite 5n1 ID 1111 independently; duplicate packets benign
- Grafana wind speed chart confirms dual dongle improvement — data density visibly doubles from
- ~08:00 onward
- docker-compose.yml committed and pushed (85b7357)
- OI-33 added: Club bridge Pi (rtl_433 + WireGuard → home J45 hub)
- OI-34 added: GNSS geofence source inhibit
- Club bridge topology agreed: club Pi → home J45 only; RV always subscribes to home hub
- **WN90LP RS-485 Modbus weather station ordered (HW-16)** — ultrasonic anemometer + piezoelectric
- rain + barometric pressure + temp/humidity/UV/light — Waveshare RS-485/7 — closes HW-05

### 2026-06-12  (Home base — Rogers)
- IMU module ordered (HW-17): diymore 10-axis L3GD20 + LSM303D — C$10.18
- Primary use case: magnetometer heading reference for true-north wind direction correction on
- WN90LP (HW-16)
- Secondary use cases: transit shock logging, levelling feedback
- Integration path agreed: I²C → ESP32-S3 ESPHome node → MQTT → Phase 7 fusion layer applies rotation offset to WN90LP windDir → publishes `rvtc/sensors/weather/windDir_true`
- Compass-boxing argument validated: ~2 m standoff above steel chassis on aluminium frame; one-time
- hard-iron calibration sufficient
- OI-36 added: WN90LP wind direction true-north correction pipeline (prerequisite: HW-17 + Phase 7
- fusion)
- Section 2.7 added to project reference documenting IMU hardware and integration rationale

### 2026-06-13  (Home base — Rogers)
- DT-R016 16-channel Ethernet Modbus TCP relay controller reviewed and scoped for RVTC
- Confirmed: Ethernet Modbus TCP interface — WiFi present but will not be configured (wired-first
- policy)
- Confirmed: Wiegand D0/D1 input terminals present; card UID readable via Modbus holding register —
- reserved for future use
- Confirmed: previously tested on home HA instance — Modbus register map known
- Load shedding scope defined: shore power presence/absence (KWS-303L) drives two relay channels via
- binary HA automation — water heater and fridge revert to LPG when shore power absent
- HSR1-25 25A NC relay × 2 ordered (HW-18) — one per load
- HW-13 updated: scope is now DT-R016 commission + 2-channel load shed integration
- OI-24 updated: simplified to binary shore-power-loss automation; no threshold management
- Section 2.8 added: DT-R016 hardware and integration documentation
- Section 2.5 updated: DT-R016 and HSR1-25 added to monitored/controlled systems list

### 2026-06-16  (Home base — Rogers)
- DT-R016 found inoperative on bench test — retired from RVTC scope
- Replacement ordered: Waveshare 8-channel relay board, RS-485 Modbus RTU interface (no standalone
- Ethernet/IP of its own) — wired into Waveshare RS-485 gateway port RS-485/8, IP 192.168.88.12,
- TCP 4001
- HW-13 updated to reflect new device, ordered, RS-485-based
- HW-18 updated — driven by Waveshare relay board instead of DT-R016
- IP map updated: 192.168.88.6 (previously reserved for DT-R016) freed — relay board has no
- dedicated IP
- Section 2.6 RS-485 port table updated — port 8 now assigned to load-shed relay board (was spare)
- Section 2.8 rewritten for the new device — channel spares reduced from 14 to 6 (8-ch board vs
- 16-ch DT-R016); Wiegand capability dropped (not required, was DT-R016-specific)
- OI-37 added: Portainer container management UI for single-pane Docker visibility; potential future
- agent-mode link to club bridge Pi (OI-33)
- **Correction:** load-shed logic was mistakenly documented as a binary shore-power-presence
- automation. Confirmed restored to the original three-condition model: shore power absent → shed
- both; grid >25A → shed water heater (restore <20A); generator >22A → shed water heater (restore
- <18A). Fridge relay only responds to the shore-absent condition. Threshold values are
- provisional and expected to be tuned once the system is live and tested.

### 2026-06-17  (Home base — Rogers)
- **Correction:** Waveshare 8-port RS-485 gateway addressing scheme fixed throughout document. The
- gateway is effectively two separate Modbus TCP devices in one enclosure — every channel answers
- on **TCP 4001**, channels are distinguished by **IP only** (192.168.88.5–12). Earlier drafts had
- incorrectly assigned per-port TCP numbers (4002 for SAMLUX, 4006 for GNSS, 4007 for WN90LP, 4008
- for the load-shed relay board) — all corrected to 4001. Section 2.6 port table column headers
- also fixed (IP and TCP were mislabeled/swapped). Section 2.8 relay board entry corrected: it
- does receive a dedicated IP via gateway port 8 (192.168.88.12) — "no dedicated IP" language
- removed.
- SAMLUX EVO-2212 commissioning started: TCP reachability confirmed (`nc -zv 192.168.88.6 4001` succeeded). Gateway config verified against device — TCP Server mode, 9600/8/N/1 serial settings match EVO-series spec sheet, Protocol = Modbus TCP to RTU. EVO-2212 default Modbus slave/unit address confirmed as 1 (01H, per manual). Noted minor housekeeping item: gateway's Destination IP/DNS field is set to 192.168.1.3 — stale value on a different subnet, inert in TCP Server mode but should be cleared/corrected to avoid confusion if Work Mode ever changes.
- `mbpoll` added to required packages (not yet installed on J45) — needed for direct Modbus-level probing ahead of HA integration. **Added to `common` role package list** so it's provisioned by Ansible rather than manual `apt install`; until the role is re-run, install manually with `sudo apt install mbpoll`.
- mbpoll installed manually (`sudo apt install mbpoll`) and used to probe the EVO-2212 directly — slave 1, register 1 answered (raw 2094), confirming the bus, wiring, and gateway bridging all work end to end.
- **SAMLUX EVO-2212 communications fully confirmed.** A 10-register block scan (259–268) initially appeared to show a consistent +1 offset between the manual's hex addresses and the actual wire register. Further testing traced this to an `mbpoll` tooling artifact, not a real device offset (see below) — once corrected, three registers confirmed working with literal/direct addressing: Voltage of Grid Input (261, 119.03 V), Input Current (262, 4.41 A), Battery Voltage (276, 13.005 V). Full detail in new Section 2.9.
- Drafted `modbus_samlux.yaml` for Home Assistant — read-only telemetry sensors only. Write/programming registers (charge profile, voltage cutoffs, etc.) explicitly deferred to a later, separate pass once read-side polling is fully trusted.
- **OI-03 closed** (see Section 7.1) — SAMLUX protocol confirmed, `samlux` Ansible role design unblocked (deferred until register list stabilizes).
- **Correction (same session):** the initial "+1 register offset" finding above was wrong. Root cause: `mbpoll` defaults to 1-based Modicon-style reference numbering and subtracts 1 from the typed `-r` value before sending it on the wire; the `-0` flag disables this and addresses the register literally. The block-scan polls omitted `-0`, making every register look shifted by exactly one — a known, common Modbus tooling pitfall (the "Modbus Shuffle"), not a SAMLUX-specific quirk. Re-confirmed all three working registers with `mbpoll -0`, getting the values shown above (literal/direct addresses, no offset).
- Lesson for future Modbus work: always pass `-0` with `mbpoll` so its addressing matches both the manual and Home Assistant's `pymodbus`-based Modbus integration.

### 2026-06-19  (Home base — Rogers)
- **KWS-303L register map completed and documented** — community reverse-engineered (manufacturer
- does not publish). Primary sources: Alexey Baldin (baldale/kws-303l) and
- BieleckiLtd/KWS-303L-ESPHome YAML. Full map produced as Word document
- (KWS-303L_Register_Map_RVTC.docx).
- **KWS-303L grid meter (RS-485/3, slave 1) commissioned via mbpoll** — live readings confirmed:
- 119.30 V, 4.571 A, 505.5 W, 60.00 Hz, 26°C, no alarms, relay ON. Two corrections identified from
- live data:
  - **Parity confirmed Even** (not None as previously noted — gateway serial config already correct)
  - **Active Power gain confirmed 10** (multiply 0.1), not 100 as in original source table — raw
  5055 / 10 = 505.5 W consistent with load. Register map document updated accordingly.
- **KWS-303L gateway port corrected to 4001** — port had been inadvertently left at 502 from initial
- setup; corrected in gateway config. All RVTC devices now consistently on TCP 4001.
- **KWS-303L consolidation decided** — both meters (grid + generator) onto single RS-485/3 port
- (192.168.88.7). Grid meter = slave 1 (already set). Generator meter = slave 2 (to be set on
- bench before install). Single RS-485 pair into power cabinet — cleaner wiring, one gateway port
- freed.
- **RS-485/4 (192.168.88.8) re-assigned** — freed from generator meter, now reserved for ESP32-S3
- Touch LCD thermostat panel (HW-20).
- **Waveshare 8-ch relay board (RS-485/8) commissioned** — all 8 coils confirmed via mbpoll coil scan (`-t 0` coil data type, 1-based addressing, no `-0` flag needed). Port 4001 confirmed as working (port 502 also responds — 4001 used per RVTC standard). Full 8-channel cycle test (relay_test.sh, pairs 1&2/3&4/5&6/7&8) passed — all relays clicking correctly. **HW-13 closed.**
- **Relay NO logic decided** — HSR1-25 relays wired Normally Open, not NC as originally scoped. Coil
- energised = AC load connected; coil de-energised = LPG fallback. Fail-safe direction correct
- (comms/power loss → loads off). 100% duty cycle rating not a concern. Section 2.8 and OI-24
- updated throughout.
- **Channel assignment confirmed** — coil 1 = water heater AC, coil 2 = fridge AC, coils 3–8 spare
- (2 earmarked for thermostat furnace/A/C relay outputs).
- **Dometic RV thermostat failed** — OEM replacement C$250. Decision: replace with ESP32-S3 Touch
- LCD 4.3 running ESPHome (HW-20 added). Dometic uses 3-wire CCC serial bus (+12V, GND, yellow);
- new design bypasses the CCC bus entirely and drives furnace/A/C directly via Waveshare relay
- board spare channels. RS-485 comms back to gateway RS-485/4 via ~13 m DMX cable (140Ω shielded
- twisted pair — adequate at this distance). 12VDC already present at panel location.
- **OI-38 added** — ESP32-S3 Touch LCD thermostat ESPHome YAML and HA climate integration.

### 2026-06-19 continued — HVAC, battery management, and load logic design session

- **HVAC architecture locked** — Dometic 59516.531 A/C confirmed cooling-only, no heat pump. All
- 120VAC safety interlocks (hi/lo pressure cutout, OL protector, compressor delay relay K1)
- self-contained in A/C unit. RVTC controls only the 12VDC CCC demand signals. 6-pin CCC connector
- pins carry 120VAC to compressor/fan — do not intercept. RVTC uses Waveshare relay board coil
- contacts to ground-switch the 12VDC furnace demand (Blue wire) and A/C demand (Yellow wire)
- signals on the CCC connector. Coils 3 and 4 must be mutually exclusive. Compressor short-cycle
- delay K1 is hardware inside the A/C unit — no ESPHome interlock required, but 5-minute software
- guard added in firmware as belt-and-suspenders.
- **ESP32 firmware decision** — Arduino framework (not ESPHome) required because CCC pulse train generation needs microsecond-precision `delayMicroseconds()` timing that ESPHome cannot provide. Same approach confirmed working by community (HA forum, JerryM, Dec 2024 — Dometic Modbus thermostat replacement). ESP32 publishes all state to MQTT for HA consumption. SSH accessible for manual setpoint when HA is down.
- **ESP32 as hardened real-time controller** — ESP32 polls EVO-2212, EPEVER, and KWS-303L directly
- via Modbus TCP and executes Tier 1 and Tier 2 protection autonomously. HA adds Tier 3/4
- intelligence and UI. If HA is down, protection continues, HVAC holds last setpoint, life goes
- on.
- **EVO-2212 behaviour confirmed (from manual)** — true online UPS, synchronised to line frequency,
- 1–3 ms transfer to inverter, seamless to all loads. Load management trigger is EVO operating
- mode register, not AC voltage.
- **EVO BMS interface confirmed** — Section 5.11.2 of EVO-2212 manual. Potential-free contact
- closure on RJ-45 port 6 (Battery Temp Sensor jack). EVO BATTERY TYPE must be programmed = 1
- (Lithium). Contact closed → CHR STOP BY BMS (charging stops, inverting continues).
- Stop-inverting function exists but is NOT automated in RVTC — EVO internal cutoffs handle deep
- discharge.
- **Battery chemistry confirmed: LiFePO4** — charge inhibit thresholds: <5°C (lower) and >45°C
- (upper). Battery heater thresholds: ON <10°C, OFF >15°C. Both ESP32-autonomous.
- **Battery temperature sensing** — EPEVER RTS register (primary, always live on DC power) +
- EVO-2212 temp sensor register (cross-validation). Inhibit on either out of range, resume when
- both in range.
- **Battery heater** — greenhouse seed mat ~20W 120VAC. Switched directly by relay board coil 6 NO
- contact (<1A, within 10A rating). No external relay needed.
- **Complete coil assignment locked** — coil 1 = water heater AC, 2 = fridge AC, 3 = furnace demand,
- 4 = A/C demand, 5 = EVO BMS charge inhibit, 6 = battery heater, 7–8 = spare.
- **Full tiered load management architecture locked** — documented in new Section 2.10. Four tiers:
- source-based (ESP32), temperature-based (ESP32), overload (HA), SOC-based (HA).
- **HW-21 added** — EVO BMS charge inhibit wiring
- **HW-22 added** — battery heater install and wiring
- **OI-38 updated** — Arduino framework, autonomous protection, SSH fallback
- **OI-39 added** — ESP32 Modbus polling register list for autonomous operation

### 2026-06-21  (Home base — Rogers)
- **IMU node firmware redesigned** — original NMEA-over-RS-485 simplex output replaced. NMEA has
  no consumer in the RVTC stack (Waveshare gateway speaks Modbus, not NMEA; J45 has no NMEA
  listener). ESPHome also dropped — LSM303D requires hard-iron calibration constants that ESPHome
  cannot hold, and the levelling web page requires Arduino framework `WebServer`.
- **Three independent output channels defined (see Section 2.7):**
  - RS-485 Modbus RTU slave (ID 10, 9600 8N1) — wired primary, authoritative for Phase 7 fusion.
    J45 polls holding registers 0–2 (heading/pitch/roll, ×10 scaled int16) via Waveshare gateway,
    identical pattern to EPEVER/SAMLUX/KWS-303L. Gateway port and IP TBD — assign at commissioning.
  - MQTT over WiFi at 1 Hz — convenience secondary path. WiFi is a deliberate, bounded exception
    to the wired-first policy: levelling display is UI only, no control or protection dependency.
    WiFi loss has zero effect on the Modbus path. Topics: `rvtc/sensors/imu/heading/pitch/roll/status`.
  - Built-in web page on port 80 — self-contained levelling display served directly from the ESP32.
    Auto-refreshes at 1 Hz via JavaScript fetch to `/api/imu` JSON endpoint. No app required —
    works on any browser including phone and cab display on MikroTik LAN.
- **Hard-iron calibration placeholders added** — `HARD_IRON_X/Y/Z` constants set to 0.0 pending
  one-time calibration procedure. MQTT status topic publishes `UNCALIBRATED` until populated.
  Heading must not be used for OI-36 wind direction correction until calibration is complete.
- **DE/RE direction control added** — Pin 16 drives RS-485 transceiver DE/RE for proper
  half-duplex operation, replacing the always-transmit tie to 5V. Allows shared bus expansion.
- **OI-36 updated** — prerequisites now explicitly include hard-iron calibration complete.
- **Section 2.7 rewritten** to reflect Arduino framework, three-channel output architecture,
  Modbus register map, and calibration workflow.
- **IMU_config.md updated** — full production sketch with all three output paths, web page HTML,
  MQTT publish, Modbus slave, calibration procedure, and gateway port config table.
- **ESP32 WiFi address block reserved** — 192.168.88.20–29 allocated exclusively to ESP32 nodes
  with WiFi secondary paths. IMU node (HW-17) = 192.168.88.20. Touch LCD thermostat (HW-20) =
  192.168.88.21 (reserved, primary connection remains RS-485/4). Water sensor node (HW-06) =
  192.168.88.22 (reserved, Phase 5). .23–.29 spare. Block .13–.19 left free for future wired
  devices. All reservations to be set by MAC address in MikroTik DHCP.
- **Pi-hole DNS record added** — `imu.lan` → 192.168.88.20. Web UIs table updated.
- **Section 3.1 IP table updated** — ESP32 block documented with policy note.
- **MikroTik DHCP pool change** — RSC updated: pool start moved from .10 to .100, giving a clean
  split (.1–.99 static by design, .100–.254 dynamic). RSC committed but router not reflashed —
  router is live and working, change deferred to next planned maintenance window along with ether8
  and pinhole fixes.
- **OI-40 added** — GNSS NMEA TCP bridge for OsmAnd on Android 5" cab display. Python container
  on J45 subscribes to GNSS MQTT topics, reformats to NMEA-0183 `$GPRMC`, publishes to TCP socket
  192.168.88.3:10110. OsmAnd connects over RV MikroTik WiFi as external GPS source via development
  plugin. Prerequisite: HW-10 commissioned. E108-GN03G-485 register map to be checked at
  commissioning.

### 2026-06-28  (Home base — Rogers)
- **Power failure recovery** — after power restoration all Docker containers came back
  cleanly (up 16 min) but `epever_mqtt` bridge was failing with Modbus "No response
  received". Root cause: EPEVER uses hex register addresses (0x3100 = decimal 12544) —
  confirmed with `mbpoll -m tcp -a 1 -t 3 -r 12544 -c 1 -0 192.168.88.5 -p 4001` which
  returned 6921 (69.21V PV, confirming device live). Bridge restarted cleanly.
- **Telegraf inverter block fixed** — `operating_mode_text` string topic ("charging",
  "inverter" etc.) was causing `strconv.ParseFloat` errors in Telegraf `mqtt_consumer`,
  blocking ALL measurements including solar and grid. Root cause: `data_format = "value"`
  / `data_type = "float"` attempts to parse every subscribed topic payload as a float.
  Previously the EVO was in a numeric-text mode that Telegraf silently dropped; after
  power failure it entered active charging mode publishing the string "charging" which
  triggered continuous errors. Fix: replaced wildcard topic `rvtc/sensors/inverter/#`
  with an explicit list of all numeric topics, permanently excluding
  `operating_mode_text`. `telegraf_solar.conf` updated and committed.
- **Relay coil 2 reassigned — microwave replaces fridge** — fridge (300W) isolation
  requires taking down the RVTC control node (shared circuit). Microwave (1200W) is a
  cleaner, more impactful shed target with no consequences when interrupted. Coil 2
  reassigned to microwave AC. Coil 3 reserved for fridge AC — to be wired during Phase 4
  tank sensor run when relay wire can be bundled into the same cable run. Section 2.8
  coil table, Section 2.5 HW-18 entry, and Section 2.10 Tier 3 shed sequence all updated.
- **EVO-2212 operating mode 2 confirmed as Charging** — previously mapped as "inverter"
  in `samlux_mqtt.py`. Corrected: mode 2 = Charging (on grid, battery charging +
  passthrough). Mode 3 = Inverting (on battery, Tier 1 trigger) — to be confirmed on
  next grid outage. `OPERATING_MODES` dict in `samlux_mqtt.py` updated. `INV_MODE_MAP`
  in `index.html` updated to match.
- **EVO-2212 Power tab added to rvtc.lan** — `index.html` updated with EVO-2212 section
  in Power tab: operating mode hero (colour-coded), input/output/battery data, four
  temperature sensors, fan speed, error code. Layout tuned for both 1920×1080 and
  1280×720 screens using compact fixed-height Row 3. All three data sources (solar, grid,
  inverter) now on 2s fetch intervals.
- **Latency root-caused and resolved** — end-to-end display latency reduced from 15–18s
  to ~6s worst case: `kws_mqtt.py` was polling generator meter (slave 2, not yet
  installed) causing 5s timeouts × 8 registers per cycle. Fix: `GENERATOR_ENABLED =
  False`. Poll interval reduced to 2s. Telegraf agent `interval` and `flush_interval`
  confirmed already at 2s. Page refresh confirmed at 2s. Flux query range tightened from
  `-3m` to `-30s`.
- **EPEVER Modbus slave address reset on power failure** — EPEVER reverted from slave 2
  to factory default slave 1 after complete AC power loss. Root cause: voltage spike /
  EMI from EVO-2212 during power restoration caused NVRAM corruption in EPEVER firmware
  (known issue per EPEVER community). Fix: `epever_mqtt.py` MODBUS_SLAVE updated to 1.
  The RS485-1M2S splitter (HW-23) and termination resistor (120Ω at EPEVER end) are
  mitigation items — add when HW-23 installed. **Post-power-failure procedure:** check
  EPEVER slave address first; reprogram to 2 via MT50 if reset to 1, then update script.
- **Relay coils 1 and 2 wired and tested** — HSR1-25 relays wired to NC contact (not NO
  as originally planned). Coil de-energised = contact closed = load ON. Coil energised =
  contact open = load OFF. Fail-safe: loads remain ON if relay board loses power —
  correct for shore power loads with no fallback. Coil 1 = water heater, coil 2 =
  microwave. Both tested via mbpoll — confirmed working.
- **Relay board addressing corrected** — initial commissioning documented as 1-based
  without `-0` flag. Live testing confirmed **0-based addressing with `-0` flag required
  for writes**. Read (status): `mbpoll -m tcp -a 1 -t 0 -r 1 -c 8 192.168.88.12 -p 4001`.
  Write coil 1 ON: `mbpoll -m tcp -a 1 -t 0 -r 0 -0 192.168.88.12 -p 4001 -- 1`.
  Section 2.8 corrected throughout. OI-24 HA automation must use 0-based coil addressing.
- **HW-18 closed** ✅ — water heater and microwave relay wiring complete and tested.

### 2026-06-29  (Home base — Rogers)

- **HA native Modbus integration for relay board abandoned — shell_command solution implemented** (full detail in `RVTC_SessionLog_20260629.md`)
  - pymodbus 3.11.2 holds a persistent TCP connection; Waveshare gateway drops idle connections — produces "No response received" on every write. Not fixable without patching pymodbus.
  - Solution: `relay.py` written using Python stdlib only — constructs raw Modbus TCP FC05 frame, opens fresh TCP connection per call, sends frame, closes. Identical behaviour to mbpoll.
  - Deployed to `/config/relay.py` in HA container (`/data/docker/volumes/homeassistant/relay.py` on host).
  - `shell_command` block added to `configuration.yaml` — `relay_N_on` / `relay_N_off` for all 8 coils. Confirmed working — relay audibly clicks, physical load responds.
  - `modbus: !include modbus-relay.yaml` commented out in `configuration.yaml`.
  - `/usr/bin/mbpoll` volume mount in `docker-compose.yml` — to be removed at next compose edit.
  - OI-24 Tier 3 automation can now proceed using `shell_command.relay_N_on/off` as actuator primitives. Coil state must be tracked via HA `input_boolean` helpers — no read-back available via this method.
  - Section 2.8 note added: HA native Modbus integration not used; pymodbus persistent connection incompatible with Waveshare gateway. See session log 2026-06-29.

- **GNSS E108-GN03G-485 commissioned — HW-10 ✅**
  - Device confirmed streaming clean NMEA0183 over TCP on 192.168.88.10:4001 (`nc` test — all sentence types present, 3D fix, 19–21 satellites, HDOP 0.6).
  - `gpsd` and `gpsd-clients` installed on J45 (`sudo apt install gpsd gpsd-clients`).
  - `/etc/default/gpsd` configured: `DEVICES="tcp://192.168.88.10:4001"`, `GPSD_OPTIONS="-n -G"`, `START_DAEMON="true"`.
  - gpsd systemd uses socket activation — socket unit was binding loopback only (127.0.0.1:2947); HA container on `rvtc_net` could not reach it.
  - Fix: drop-in override created at `/etc/systemd/system/gpsd.socket.d/override.conf` — adds `ListenStream=0.0.0.0:2947` and `ListenStream=[::]:2947`. Confirmed `0.0.0.0:2947` after `systemctl daemon-reload && restart gpsd.socket && restart gpsd`.
  - gpsd auto-detected u-blox binary protocol from the E108 — switched from NMEA0183 driver to u-blox driver; fix quality unaffected (3D fix maintained throughout).
  - HA GPSD integration configured: host `192.168.88.3`, port `2947`. After initial connection hiccup settled: Latitude 48.668604924, Longitude -123.600066795, Mode 3D Fix, 21 total / 19 used satellites, Speed, Climb, Time all live.
  - Antenna currently in non-ideal location — roof mount deferred. Fix quality acceptable: HDOP 0.6–0.8, Est Pos Err ~10–12m, 16–21 satellites tracked.
  - `ANTENNA OPEN` `$GPTXT` sentence present on every epoch — active antenna supervision circuit seeing passive antenna. Cosmetic only, no effect on fix.
  - **TODO (Ansible):** Add gpsd socket override to `common` role — `roles/common/files/gpsd-socket-override.conf` + copy task to `/etc/systemd/system/gpsd.socket.d/override.conf` + `systemctl daemon-reload` handler. Required to survive a full rebuild.

- **OI-29, OI-30, OI-40 unblocked** — GNSS position live in HA. MQTT publishing pipeline, moving map, and OsmAnd NMEA bridge can proceed when ready.

### Next Session — Phase 3 Priorities
1. Wire coil 5 (EVO BMS charge inhibit) — RJ-45 plug to EVO port 6, pins 1+5 (HW-21)
2. Install battery heater and wire to coil 6 (HW-22)
3. Fish DMX cable to thermostat location — RS-485/4 (HW-20)
4. Generator meter — set slave 2 on bench, wire onto RS-485/3 shared bus (HW-09)
5. Install RS485-1M2S splitter + termination resistor on RS-485/1 (HW-23) — prevents EPEVER slave address reset on power failure
6. HA `shell_command` relay automation — Tier 3 load-shed logic (OI-24) — use 0-based coil addressing
7. Remove `/usr/bin/mbpoll` volume mount from `docker-compose.yml`
8. Add gpsd socket override to `common` Ansible role
9. Rebuild Grafana weather dashboard (OI-16)
10. WN90LP commissioning when received (HW-16)
11. Portainer container management UI (OI-37)

---

## 9  Architecture Notes

### 9.1  Phase 7 — Sensor Fusion

A normalised MQTT sensor bus with a fusion/arbitration layer that assigns the best available source
to each logical field, with configurable priority ordering and automatic fallback when a source goes
stale.

**Planned source types:**
- RTL-SDR (dual dongles SN 1024 + SN 00000001) — independent receivers, same 433 MHz sensors
- ESPHome nodes — publish directly to MQTT
- Modbus devices via Waveshare gateway — EPEVER, SAMLUX, KWS-303L, water sensors
- GNSS receiver (HW-10, E108-GN03G-485)
- IMU / magnetometer (HW-17, L3GD20 + LSM303D) — heading reference for wind direction true-north
- correction and map orientation
- External APIs — e.g. Environment Canada as fallback weather source

**Key design decisions to resolve:**
1. Normalised MQTT topic schema — proposed: `rvtc/sensors/{source_id}/{field}`
2. Staleness timeout — will differ by source type
3. Sanity checking — e.g. reject outTemp = 80°C
4. UI approach — live source discovery, per-field priority assignment
5. Implementation — Python fusion service (new container + Flask API)
6. Duplicate packet handling — deduplicate by (sensor_id, timestamp); arbitrate by signal quality or
source priority

**Consumers:** WeeWX (via fused MQTT topic), Home Assistant, Grafana.

### Phase 7 Open Question — HA's Role in Actuation (raised 2026-06-30)

After implementing Tier 3 (Section 2.10) in HA, a broader architecture question surfaced: should
load management / actuation logic live in HA at all, or should it move to a standalone Python
controller (same family as `kws_mqtt.py`/`epever_mqtt.py`/`samlux_mqtt.py`) that subscribes to the
existing MQTT sensor topics and writes to relays directly — with HA reduced to a pure display/
manual-control-surface role, or removed from the loop entirely for this function?

**Deliberately not resolved yet** — decision deferred until Tier 3 has been live-tested and run
for a meaningful period under HA, so the choice is evidence-based (operational cost, reliability,
maintainability in practice) rather than reactive to any one session's friction. Implementation
friction during initial setup (YAML structure, schema changes) is a one-time cost and explicitly
NOT a factor in this decision — the criterion is what's most seamless and intuitive for any user
operating the finished system day to day, not setup difficulty.

Candidate alternative architecture, if HA is found to be the wrong fit for actuation specifically:
- Standalone `load_controller.py` service — subscribes to existing `rvtc/sensors/grid/#`,
  `rvtc/sensors/generator/#`, `rvtc/sensors/inverter/#` MQTT topics already being published, runs
  the Tier 3/4 state machine as plain Python, writes to relays directly (same connection pattern as
  `relay.py`/`kws_relay.py`)
- Manual controls become MQTT publishes from a lightweight page on `rvtc.lan` (an extension of the
  existing `index.html`/`rvtc_index.html` work), using Mosquitto's websocket support — no backend
  API server needed
- HA's role would narrow to: display (already works, since HA already consumes the same MQTT
  topics for dashboards), and possibly nothing else for this subsystem
- Open question within this question: does removing actuation from HA undermine the Section 9.4
  rationale (HA as the place where all data streams converge for decisions) — or does a standalone
  controller subscribing to the same MQTT topics achieve the same convergence without HA's config
  overhead?

To revisit once Tier 3 has real operating history.

---


### 9.2  Club Bridge Topology (OI-33 / OI-34)

- Small always-on Pi at Solsante Club: rtl_433 + WireGuard
- Pi connects to home HA Yellow only — never directly to RV
- Home HA Yellow Mosquitto is the hub — RV subscribes to home regardless of location
- When RV is at club: GNSS geofence (OI-34) detects position match → fusion layer suppresses RV 5n1
- (ID 1111) → club station becomes authoritative source
- When RV is remote: club bridge feeds weather data to home J45 → forwarded to RV via VLAN
- Reuses OI-20 VPN infrastructure (WireGuard). Prerequisite: HW-10

### 9.3  Engineering Standards & Design Philosophy

The RV Total Control (RVTC) architecture rejects fragile consumer electronics conventions in favour
of industrial-grade and marine-grade robustness. Because no single engineering standard covers a
mobile, containerized smart environment, RVTC draws from proven frameworks across the automation,
maritime, and automotive industries:

- **Signal Integrity & Noise Immunity:** Long analog sensor runs use 4–20 mA current loops
- consistent with industrial process instrumentation practice (ref. IEC 60381-1). Digital sensor
- buses utilize EIA-485 (RS-485 Modbus RTU) differential signalling. All signal lines use
- twisted-pair shielded cabling to mitigate electromagnetic interference (EMI).
- **Electrical Safety & Grounding:** The power and grounding architecture follows marine and RV
- industry best practice (ref. ABYC E-11, NFPA 1192) — single-point grounding at all enclosures to
- eliminate ground loops and prevent galvanic corrosion.
- **Environmental Ruggedness:** Equipment placement and enclosure selection account for the thermal
- cycling, shock, and vibration demands of a mobile vehicle environment operating off-grid (ref.
- SAE J1455).
- **Data & Software Architecture:** Telemetry transport uses ISO/IEC 20922 (MQTT), feeding a
- decoupled, containerized data pipeline (InfluxDB/Grafana) that mirrors the functional layering
- principles of industrial automation systems (ref. ISA-95).

These cross-disciplinary design principles ensure the system remains resilient against the harsh
electrical noise, vibration, and environmental demands of extended off-grid travel.

> **Note:** RVTC is a private build and does not claim conformance or certification against any of
> the referenced standards. IEC 60381-1, ABYC E-11, NFPA 1192, SAE J1455, and ISA-95 are cited as
> engineering guidance and design benchmarks only.

**Offline-first requirement for `.lan` pages (added 2026-06-30):** Internet connectivity at the RV
is not guaranteed (Starlink/cellular dependent, sometimes absent entirely off-grid). Every page
served on the RVTC.lan domain — Lovelace dashboards, the IMU page, the planned RVTC landing page,
and any future custom HTML — must render and function correctly with zero internet access. This
means no `@import` or `<link>` references to external CDNs for fonts, icons, JS libraries, or map
tiles (e.g. `fonts.googleapis.com`). All such assets must be downloaded once and self-hosted
on-device (J45 or the relevant ESP32/container), with pages referencing the local copy. This applies
retroactively — any existing page found using an external font/asset CDN should be flagged and
fixed. See OI-30 (map tiles) which already anticipated this for Leaflet; the same rule now applies
project-wide, not just to that one page. Tracked as DD-04 (Section 7.3).

### 9.4  HA as Actuator — Bounded Exception

RVTC's general design principle is that HA consumes data and does not actuate. Load management
(OI-24) and HVAC (OI-38) are deliberate, bounded exceptions to this principle.

HA is the correct actuator for Tier 3 (overload) and Tier 4 (SOC) logic because it is the only place
where all relevant data streams converge simultaneously — grid current, generator current, battery
SOC, A/C state, furnace state, time of day. Putting that logic anywhere else would require
duplicating data or accepting a less-informed decision.

The exception is strictly bounded: HA writes to relay coils via Modbus for overload management, and
sends MQTT commands to the ESP32 for setpoint and mode changes. All physical safety protection (Tier
1 and 2) remains in the ESP32 and is HA-independent. If HA is down or broken, the RV continues to
operate safely.
