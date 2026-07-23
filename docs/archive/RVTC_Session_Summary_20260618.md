# RVTC Session Summary — 2026-06-18

**Location:** Home base — Rogers
**Phase:** 3 Active — Power Integration

---

## Session Goals
- Commission remaining RS-485 devices via `mbpoll -0` polling
- Document consistency audit on project reference
- Capture architecture decisions arising from review

---

## Work Completed This Session

### RS-485 Device Commissioning — Direct Poll Confirmation

Three additional RS-485 channels confirmed live via direct `mbpoll -0` polling (same method used for SAMLUX EVO-2212 commissioning on 2026-06-17). No data flowing to Mosquitto yet — these are connectivity confirmations only.

| Device | Port | IP | TCP | Result |
|---|---|---|---|---|
| EPEVER MPPT60 | RS-485/1 | 192.168.88.5 | 4001 | ✅ Registers responding — baud 115200 |
| KWS-303L grid meter | RS-485/3 | 192.168.88.7 | 4001 | ✅ Registers responding |
| Waveshare 8-ch relay board | RS-485/8 | 192.168.88.12 | 4001 | ✅ Coil registers responding |

**Note — EPEVER baud rate:** 115200 is set because the MPPT60 shares the RS-485 bus with its OEM remote control panel, which runs at that rate.

**Relay board power supply issue identified:** The EPEVER MPPT controller does not have sufficient current reserve to drive the relay board under multi-relay load conditions. DC-DC converter (HW-19, device in hand) added to backlog for installation before the relay board can be put into service.

---

### Document Consistency Audit

Full consistency review of `RVTC_Project_Reference_20260618.md` completed. Corrections made:

| Location | Issue | Fix |
|---|---|---|
| §2.4 | HW-12 still showed "replacement pending" | Updated to reflect HW-12 closed |
| §2.5 / §3.1 | MPPT-60 vs MPPT60 inconsistency | Standardised to MPPT60 throughout |
| §2.6 | HW-01 status showed "commissioning next session" | Updated to "✅ In service — HW-01 closed" |
| §2.6 | Port table had no Status column | Status column added for all 8 ports |
| §2.8 | "192.168.88.6 is now free" — wrong, it is the SAMLUX IP | Removed stale note |
| §3.1 | IP table had no notes for Ch-3 through Ch-8 | Notes populated for all 12 entries |
| §5.4 | HW-14 listed as open known issue | Removed — HW-14 is closed |
| §7.1 OI-03 | Referenced "+1 register offset" that was corrected | Updated to "literal/direct addressing, no offset" |
| §8 Next Session | Stale priorities from prior session | Updated to current outstanding items |

---

### Architecture Decision — Publish/Subscribe Bus

**Decision:** Mosquitto is the single, central data bus for the entire RVTC system. Every sensor connects to Mosquitto via a thin software adaptor. Every consumer (HA, WeeWX, InfluxDB, Grafana, Phase 7 fusion) subscribes to Mosquitto for the data it needs. No consumer owns or mediates any part of the data pipeline.

This is a proven pattern from defence-grade systems where every sensor and system node is an independent producer or consumer on a common message bus and no single node owns the pipeline.

```
Sensor <==> Adaptor <==> Mosquitto (broker) <==> Consumers
```

**Consequence for Home Assistant:** HA is a consumer and automation engine. It must never sit between a sensor and the broker. An HA update, restart, or misconfiguration must not create a data gap or break sensor ingestion.

**Adaptor by source type:**

| Source | Adaptor | Status |
|---|---|---|
| 433 MHz sensors | rtl_433 container | ✅ In place |
| ESPHome nodes | ESPHome native MQTT publish | ✅ In place |
| Modbus RS-485 via Waveshare gateway | Gateway native MQTT (preferred) or modbus2mqtt container | 🟡 OI-38 |
| GNSS, WN90LP | Gateway MQTT or dedicated parser | 🟡 Pending hardware install |

**OI-38 opened:** Confirm whether the Waveshare RS-485 gateway's native MQTT capability can poll Modbus registers on a schedule and publish directly to Mosquitto. If yes, no additional container is needed for the entire Modbus device fleet. Priority investigation for next session.

---

### Architecture Decision — Load Protection Controller

**Decision:** Load shedding is a **protection function**, not a Home Assistant automation. It must operate independently of HA, Mosquitto availability, and the J45 software stack.

**Data source change:** The KWS-303L grid meters are replaced by the **SAMLUX EVO-2212** as the data source for all shed decisions. The EVO-2212 has full visibility of system state across all operating modes — shore power, generator, and battery-only. The KWS-303L grid meter is only relevant when shore power is present; the RV is not always on shore power.

**Control flow:**
```
SAMLUX EVO-2212
  <==> RS-485 adaptor <==> Mosquitto
                               <==> Protection controller (dedicated — subscribes to EVO-2212 topics)
                                        — evaluates shed thresholds in dedicated logic
                                        — drives Waveshare relay board via direct Modbus TCP
                               <==> HA (visibility and dashboard only — no control authority)
                               <==> InfluxDB (historical record)
```

**Shed conditions (thresholds provisional):**
1. No AC input on EVO-2212 → open both relay channels → water heater and fridge revert to LPG
2. AC input current >25A → open water heater relay → restore <20A. Fridge unaffected.
3. Generator current >22A → open water heater relay → restore <18A. Fridge unaffected.

**Implementation TBD (DD-04):** Options are a dedicated ESPHome node, a systemd service on the J45, or a standalone microcontroller. Must not depend on HA or any other consumer being alive.

---

## Open Items Status Changes

| ID | Item | Change |
|---|---|---|
| OI-24 | Load protection controller | 🟡 Reframed — renamed from "shore power load management"; data source changed to EVO-2212; HA removed from control path |
| OI-38 | Waveshare gateway native MQTT | 🟡 New — priority investigation for next session |
| DD-04 | Load protection controller design | 🟡 New — implementation options to be evaluated |
| HW-19 | DC-DC converter for relay board power | 🟡 Added — device in hand, install required before relay board commissioning |

---

## Documents Updated This Session

| File | Changes |
|---|---|
| RVTC_Project_Reference_20260618.md | Consistency audit fixes throughout; §2.6 port table Status column added; §2.8 rewritten for protection controller architecture; §3.1 IP table notes populated; §9 restructured — 9.1 publish/subscribe bus architecture added; OI-24 reframed; OI-38 added; DD-04 added; HW-19 added; session log updated |

---

## Next Session — Phase 3 Priorities

1. **OI-38** — Investigate Waveshare gateway native MQTT capability; confirm whether it can serve as the Modbus adaptor layer
2. **HW-19** — Install DC-DC converter to resolve relay board power supply issue
3. **HW-09** — Complete generator AC wiring for KWS-303L generator meter
4. **HW-10** — Install and integrate GNSS E108-GN03G-485, Waveshare RS-485/6
5. **HW-03 / HW-04** — Solar panel wiring
6. **OI-15** — Home Assistant onboarding and MQTT integration
7. **OI-16** — Rebuild Grafana weather dashboard
8. **HW-16** — WN90LP commissioning when unit arrives
9. **HW-13** — Record Waveshare relay board Modbus coil addresses at commissioning
10. **OI-32** — WeeWX upstream bug report
11. **OI-37** — Consider Portainer deployment

---

## How to Resume This Project in a New Claude Session

Share `RVTC_Project_Reference_20260618.md` at the start of the session. That document is the project memory — it contains full hardware inventory, network config, software stack, open items, and session history. No other context is needed.
