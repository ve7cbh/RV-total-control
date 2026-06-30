# RVTC — Session Notes 2026-06-30
## Tier 3 Load Shed Implementation + KWS-303L Manual Grid/Generator Disconnect

---

### Summary

This session implemented Tier 3 (HA-orchestrated overload protection) per the existing Section
2.10 spec, added manual override switches for water heater/microwave shedding, and added a
previously-undocumented capability: the KWS-303L meters' own internal disconnect relay (register
63), used for manual grid/generator connect-disconnect independent of overload logic — e.g. for
maintenance or to force the RV off grid power and onto solar/battery.

A recurring class of bug consumed a large share of the session: HA's `!include` mechanism requires
the included file to contain only the *contents* of the key it's assigned to, not the key itself.
This bit automations.yaml, helpers.yaml (twice — input_boolean and input_number both), and the
original switch file, each time producing a different but related YAML error. Documented in full
below as a standing gotcha for future file additions.

---

### Part 1 — Tier 3 Overload Load Shed (HA-orchestrated)

Implements Section 2.10's Tier 3 grid/generator overload sequencing using existing live sensors —
no new hardware reads were needed; `sensor.grid_current`, `sensor.generator_current`, and
`sensor.samlux_operating_mode_text` were already live in HA via the existing MQTT bridge scripts.

**Files added:**
- `helpers_input_boolean.yaml` — `coil1_energised`, `coil2_energised` (actual relay state
  tracking, since shell_command writes have no read-back), `tier3_ac_shed_enabled` (gate for the
  stubbed A/C step), `manual_shed_water_heater`, `manual_shed_microwave` (manual override switches)
- `helpers_input_number.yaml` — `tier3_ac_restore_timer_grid`, `tier3_ac_restore_timer_gen`
  (reserved for the A/C restore step once HW-20 is live; unused for now)
- `scripts.yaml` additions — `tier3_grid_overload_response`, `tier3_grid_restore`,
  `tier3_generator_overload_response`, `tier3_generator_restore`
- `automations.yaml` additions — trigger automations for grid/generator overload entry (30s
  debounce per spec) and restore-check automations (run every minute), plus two automations
  wiring the manual override switches to the relays

**Behaviour implemented:**
- Steps 1 (water heater) and 2 (microwave) fully live for both grid and generator, with the
  thresholds, debounce, and step delays specified in Section 2.10
- Step 3 (A/C shed via ESP32 CCC command) is deliberately **stubbed** — RS-485/4 / HW-20
  thermostat is not wired yet, so there's no climate entity or confirmed MQTT topic. Gated behind
  `input_boolean.tier3_ac_shed_enabled` (currently off); TODOs left in `scripts.yaml` marking
  exactly where the climate entity check and `mqtt.publish` call go once HW-20 is live
- Tier 3 gated off entirely whenever `sensor.samlux_operating_mode_text` reads "inverting" (Tier 1
  already shed these loads in that case)
- Manual override switches (`manual_shed_water_heater`, `manual_shed_microwave`) force-shed
  immediately on toggle-on, and on toggle-off hand control back to the Tier 3 restore scripts
  (which only actually restore if current is genuinely back under threshold — manual release
  cannot force a restore during a real overload)
- All four restore script branches check the matching manual override is off before un-shedding,
  so Tier 3's per-minute restore check cannot silently override a manual shed

**Known accepted limitation:** coil 1/2 state (and the manual override toggles) are shared between
the grid and generator scripts — there's no per-source tracking of which condition caused a shed.
Confirmed acceptable: switching from grid to generator requires going through the inverter and a
manual physical changeover that takes minutes at minimum, so the two sources never compete for the
same coil state in practice.

**Dashboard:** new "Manual Control" view added to the "Load Control" Lovelace dashboard
(`manual_control_dashboard.yaml`) — Manual Load Shed card (real toggles for water heater/microwave)
and a Coil Status card (glance-type, read-only icons, NOT togglable — avoids the earlier confusion
where the status-tracking `input_boolean`s could be flipped by hand with no effect).

**Not yet done (deferred to next session):**
- Switches for the KWS grid/generator disconnect (Part 2 below) have not yet been added to the
  dashboard — planned for tomorrow
- Live bench test of the actual Tier 3 automatic trigger (forcing real current over threshold)
  has not been performed — only the manual override path has been tested live

---

### Part 2 — KWS-303L Manual Grid/Generator Disconnect (new feature, not in original spec)

Discovered while reviewing KWS-303L telemetry pages: the meter has its own internal disconnect
relay (register 63, read/write, holding register, 0-based literal addressing — same convention
confirmed for every other register on this meter). This is **separate from the Waveshare relay
board** — it's a contact inside the meter itself, in series with the whole grid (or generator)
feed.

**Use case:** deliberate manual disconnect for maintenance, or to force the RV off paid grid power
and onto solar/battery — not an automated overload response, and not part of Tier 3.

**Addressing confirmed via mbpoll 2026-06-30:**
```bash
mbpoll -m tcp -a 1 -t 4 -r 63 -0 192.168.88.7 -p 4001 -c 1
```
Returned `1` while grid was actively under load (489W) — confirms **1 = connected, 0 =
disconnected**, no inverted logic (unlike the Waveshare NC relay coils, which did require working
out an inversion).

**Important caveat from the KWS-303L register map doc:** writing 1 remotely does NOT clear an
active alarm condition the way the physical front-panel switch does. Alarms must be cleared on the
meter itself.

**Files added:**
- `kws_relay.py` — write script, deployed to `/home/ve7cbh/RV-total-control/config/` (host-side,
  **not** inside the HA container — this script is called by HA's shell_command, which executes
  inside the container, but the file itself lives alongside `relay.py` at
  `/data/docker/volumes/homeassistant/`, mapped to `/config/` in-container). Same fresh-connection-
  per-call pattern as `relay.py`; deliberately does not share a connection with `kws_mqtt.py`'s
  persistent polling connection.
- `kws_mqtt.py` — patched to add register 63 to `KWS_REGISTERS`, publishing
  `rvtc/sensors/grid/relay_state` and `rvtc/sensors/generator/relay_state` (the latter inert until
  `GENERATOR_ENABLED = True` and the meter is physically installed). Note: this file lives at
  `/home/ve7cbh/RV-total-control/config/kws_mqtt.py` per its systemd `ExecStart` path — **not**
  inside the HA container's volume. Briefly broke the service mid-session when accidentally moved
  into a subdirectory; restored to the exact path the unit file expects.
- `mqtt_sensors.yaml` — added explicit `Grid Relay State` / `Generator Relay State` MQTT sensor
  definitions (this install uses explicit sensor definitions throughout, no MQTT discovery)
- `configuration.yaml` — added `grid_relay_on/off`, `generator_relay_on/off` shell_command entries;
  added a `template:` block (see below) defining `switch.grid_connection` and
  `switch.generator_connection`
- `scripts.yaml` — added `kws_grid_connect` (alarm-checked: blocks reconnect and raises a
  persistent_notification if `sensor.grid_alarm_code` is nonzero, since remote ON can't clear
  alarms) and `kws_grid_disconnect`

**Template switch schema note:** initially built using the legacy `switch: platform: template`
format (matching the pattern used for the relay board write side). HA flagged this as deprecated
and the entities never actually registered. Rebuilt using the modern `template:` integration
schema (`template: - switch: - turn_on: ... default_entity_id: ...`) per HA's own repair-item
instructions. Confirmed working end-to-end: `switch.grid_connection` reflects live
`sensor.grid_relay_state`, both connect and disconnect tested live, alarm-gating confirmed.

**Confirmed live-tested:** disconnect, alarm-gated reconnect (initially blocked incorrectly due to
a string-vs-numeric comparison bug — `sensor.grid_alarm_code` reads `"0.0"`, not exactly `"0"`,
fixed by switching the condition to a numeric template comparison), and reconnect after fix. Both
directions confirmed working.

**Not yet done:**
- Generator-side switch (`switch.generator_connection`) is wired identically but untestable until
  the generator meter is physically installed (HW-09) — currently calls shell_command directly
  with no alarm-check script; add the same alarm-aware pattern as grid once that meter is live.  
  This will only be done if the generator has command start and stop functionality.
- Dashboard card for grid/generator connection (drafted, not yet added to the Load Control
  dashboard — planned for tomorrow alongside the Tier 3 manual switches)

---

### Standing Gotcha — `!include` wrapping-key pattern

Recurring source of errors this session, worth flagging for all future config file additions:

When `configuration.yaml` has `some_key: !include some_file.yaml`, the file's content must be
**only what goes inside `some_key`** — it must NOT itself contain a `some_key:` line. This bit:

- `automations.yaml` — pasted content included a stray `automation:` wrapper line
- `helpers.yaml` → split into `helpers_input_boolean.yaml` / `helpers_input_number.yaml` — both
  initially kept their own `input_boolean:`/`input_number:` wrapper key, causing double-nesting
  (`input_boolean.input_boolean.coil1_energised` instead of `input_boolean.coil1_energised`)
- The original `kws_relay_switches.yaml` attempt hit the same pattern in reverse — the *editor*
  (Lovelace dashboard YAML, and later the switch file) needed the wrapping key
  (`views:` / none at all) and didn't have it

**Rule of thumb going forward:** before adding content to any `!include`d file, check whether the
file already starts with the same key name that the `configuration.yaml` line assigns it to — if
so, delete that line and de-indent everything below it by the same amount.

**Process improvement adopted mid-session:** rather than asking for manual nano paste + indent
adjustment (consistently error-prone given dyslexia-related transposition, per the project's own
working-style note), switched to providing exact `cat >> file << 'EOF' ... EOF` heredoc commands
for multi-line additions, and `python3` find-and-replace scripts (with an explicit "pattern not
found, aborting" safety check) for precise in-place edits. Both proved far more reliable than
manual indent-matching for the rest of the session. **Recommend this as the default approach for
all future config file edits**, not just as a fallback.

---

### File inventory — all files touched this session

| File | Location | Change |
|---|---|---|
| `helpers_input_boolean.yaml` | `/data/docker/volumes/homeassistant/` | New |
| `helpers_input_number.yaml` | `/data/docker/volumes/homeassistant/` | New |
| `scripts.yaml` | `/data/docker/volumes/homeassistant/` | Appended (Tier 3 + KWS scripts) |
| `automations.yaml` | `/data/docker/volumes/homeassistant/` | Appended (Tier 3 + manual shed) |
| `manual_control_dashboard.yaml` | reference / Lovelace | New view added to Load Control dashboard |
| `kws_relay.py` | `/data/docker/volumes/homeassistant/` | New |
| `kws_mqtt.py` | `/home/ve7cbh/RV-total-control/config/` | Patched — register 63 added |
| `mqtt_sensors.yaml` | `/data/docker/volumes/homeassistant/` | Appended — 2 new sensor entries |
| `configuration.yaml` | `/data/docker/volumes/homeassistant/` | Appended — shell_command, template block |

**Note on `kws303l` subdirectory:** briefly created during this session when `kws_mqtt.py` was
moved by mistake; file was restored to its correct path. Confirm the empty `kws303l/` directory
under `/home/ve7cbh/RV-total-control/config/` has been removed (housekeeping, not urgent).

---

### Next Session Priorities (additions to existing list)

1. Add manual shed switches (water heater/microwave) and grid/generator connection switches to the
   Load Control dashboard's Manual Control view together — currently the Tier 3 switches are live
   on the dashboard but the KWS connect/disconnect switches are not yet added anywhere
2. Live bench test of actual Tier 3 automatic trigger — force real current over the grid threshold
   and confirm the full sequenced shed/restore behaves as designed (only the manual override path
   has been tested so far)
3. Remove the empty `kws303l/` directory (housekeeping)
4. Consider adding the same alarm-aware connect/disconnect pattern to the generator switch once
   HW-09 (generator meter) is physically installed
5. (Carried over from 2026-06-29) Wire coil 5, install battery heater/coil 6, fish DMX cable for
   HW-20, install generator meter, install RS485-1M2S splitter, remove `/usr/bin/mbpoll` volume
   mount, add gpsd socket override to Ansible role, rebuild Grafana weather dashboard, WN90LP
   commissioning, Portainer
6. **New (2026-06-30):** Draft RVTC landing page pulls fonts (JetBrains Mono, Inter) via a
   `fonts.googleapis.com` `@import` — will fail with no internet, which is the normal off-grid
   condition for this project, not an edge case. Download the font files and self-host them
   alongside the page; same check needed for any other custom `.lan` page using external CDN
   assets (fonts, icons, JS, map tiles). Tracked as DD-04 in the project reference (Section 7.3),
   with a standing rule added to Section 9.3.

---
*Session notes prepared 2026-06-30 — append to Section 8 session log in project reference. Also
update Section 2.10 with a brief note on the new KWS manual disconnect capability, and Section 2.6
(gateway table, RS-485/3 row) to mention register 63 if a dedicated KWS-303L sub-section is ever
broken out.*
