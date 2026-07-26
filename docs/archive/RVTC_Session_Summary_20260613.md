# RVTC Session Summary — 2026-06-13

## Session Goals
- Review DT-R016 relay controller suitability for load shedding
- Define scope of shore power load management
- Update project reference with new hardware and decisions

---

## Work Completed This Session

### DT-R016 Relay Controller — Scoped and accepted

**Background:**
The DT-R016 16-channel Ethernet/WiFi relay controller was on hand from a previous card reader project. Question raised: is it overkill for RVTC load shedding?

**Assessment:**
Channel count (16) is more than needed, but not a reason to reject it. The WiFi interface is present but will not be configured — Ethernet Modbus TCP is the only interface used, consistent with RVTC wired-first policy. The device speaks Modbus TCP natively and was previously tested on the home HA instance, so the register map is known.

**Wiegand capability noted:**
The DT-R016 has D0/D1 Wiegand 26-bit input terminals. Card UID is readable via a Modbus holding register — confirmed working in prior testing. This capability is documented for future reference but has no active role in the current scope.

**Decision:** Accept DT-R016 for RVTC. Commission via Ethernet Modbus TCP. WiFi not configured.

---

### Load shedding scope — Defined and simplified

**Background:**
OI-24 was originally written as "120VAC load shedding on solar" with a threshold-management concept. Discussion clarified the actual requirement.

**Defined scope:**
When shore power is absent, water heater and fridge are disconnected from AC and revert to LPG. When shore power is restored, AC resumes. This is a single binary automation — no current threshold management, no priority ordering, no card-driven mode selection.

**Control logic:**
```
KWS-303L grid meter (shore power present/absent)
  → HA binary automation
    → DT-R016 Modbus TCP (2 relay channels)
      → HSR1-25 25A NC relay × 2 (water heater AC, fridge AC)
```

The HSR1-25 relays are normally closed — loads remain on AC by default. Opening the relay coil disconnects AC; LPG takeover is passive (appliance behaviour, not software-controlled).

**HSR1-25 relays ordered (HW-18):** 2 × 25A NC relays, ordered 2026-06-13.

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| HW-13 | Shore power load management relay controller | 🟡 Open — updated: DT-R016 Ethernet Modbus TCP, in hand, commissioning Phase 3 |
| HW-18 | HSR1-25 25A NC relay × 2 | 🟡 Open — added to backlog, ordered 2026-06-13 |
| OI-24 | Shore power loss load shed | 🟡 Open — scope redefined: binary shore-power-presence automation, water heater + fridge only |

---

## Architecture Decisions Made

**Shore power load shedding (OI-24):**
- Trigger: KWS-303L grid meter reading zero (shore power absent)
- Action: open 2 × DT-R016 relay channels → disconnect water heater AC and fridge AC
- Appliances revert to LPG passively — no additional software control required
- Restore: shore power present → close relay channels → AC resumes
- No current threshold logic, no generator-mode differentiation at this stage

**DT-R016 integration policy:**
- Ethernet Modbus TCP only — WiFi capability disabled and not configured
- Map only the 2 active load relay coils in HA — unused channels left unmapped to avoid unnecessary InfluxDB writes
- Wiegand input register address to be recorded at commissioning for future reference
- 14 spare relay channels available for future expansion

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| Grafana dashboard | Still needs rebuilding (OI-16, carried) |
| Rain ID filter | `filter_out_message_when = 291` not yet tested under live rain conditions |
| HW-14 | Rain gauge physical inspection at club still required |
| MikroTik RSC | ether8 + pinhole fix RSC committed but not yet loaded onto physical router |
| DT-R016 Modbus register map | Coil addresses for load channels and Wiegand UID register to be recorded at commissioning |

---

## Documents Updated This Session

| File | Changes |
|---|---|
| RVTC_Project_Reference_20260613.md | Section 2.5 updated; Section 2.8 added (DT-R016); HW-13 updated; HW-18 added; OI-24 revised; session log added |

---

## Next Session — Phase 3

1. Waveshare RS-485 gateway commissioning (HW-01 — device in hand)
2. EPEVER MPPT60 Modbus integration (RS-485/1, TCP 4001)
3. SAMLUX EVO-2212 Modbus integration (RS-485/2, TCP 4002)
4. Solar panel wiring (HW-03 / HW-04)
5. Home Assistant onboarding — MQTT integration (OI-15)
6. Rebuild Grafana dashboard (OI-16)
7. WeeWX upstream bug report (OI-32)
8. WN90LP commissioning when received (HW-16 — ships after June 15)
9. DT-R016 commissioning — record Modbus coil addresses for load relay channels and Wiegand register (HW-13)
