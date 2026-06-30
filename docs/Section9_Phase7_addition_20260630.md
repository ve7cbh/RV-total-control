# Addition to RVTC_Project_Reference — Section 9.1 (Phase 7 — Sensor Fusion)
#
# Insert this new subsection immediately after 9.1 and before 9.2 (Club Bridge
# Topology), i.e. right before the line:
#   ### 9.2  Club Bridge Topology (OI-33 / OI-34)

---

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
