# RVTC — Session Notes 2026-07-05 (evening) / 2026-07-06 (morning)
## Manual Shed — Microwave Relay Appeared Non-Functional, Then Worked With No Config Change

---

### Summary

`shell_command.relay_2_on` (microwave shed) appeared completely broken during live testing —
absent from Developer Tools → Actions entirely, unlike the working `relay_1_on`/`relay_1_off`
(water heater). A full HA core restart was performed as the presumed fix. Immediately after
restart, Developer Tools → Actions still showed no `relay_2_on`, with no visible change. Session
was abandoned at that point (fatigue). The following morning, with no further config changes made,
the microwave manual shed toggle worked correctly in both directions.

**This is logged as a known failure mode of the HA/Developer-Tools workflow, not a resolved and
understood bug** — the underlying cause is inferred, not confirmed, and reliability data point
carries forward to the standing Section 9.1 Phase 7 question (HA's suitability for actuation).

---

### Timeline

1. Manual Shed dashboard toggle for microwave observed to have no effect; water heater toggle
   (identical automation pattern, different coil) worked correctly.
2. Diagnosed hardware/register layer first, per standard "confirm don't guess" discipline:
   - `relay.py`'s first CLI argument confirmed to be a literal 0-based coil number (read directly
     from source)
   - `configuration.yaml` confirmed: `relay_1_on/off` → coil 0 (water heater), `relay_2_on/off` →
     coil 1 (microwave) — naming is 1-indexed-sounding but maps to 0-based coils; misleading but
     internally consistent
   - Direct `mbpoll` testing on coil 1 confirmed the relay itself, wiring, and polarity are correct
     (value 1 = shed/off, value 0 = restore/on — an inverted relay, consistent with the Waveshare
     NC-wiring quirk already documented from 2026-06-30)
   - `automations.yaml` reviewed: both water heater and microwave automations are structurally
     identical and correctly cross-referenced (water heater → `relay_1_*`, microwave →
     `relay_2_*`) — **no config bug found at the automation or shell_command definition level**
3. With hardware, wiring, and config all confirmed correct, the fault had to be in HA's runtime
   registration of the shell_command action itself. Confirmed via Developer Tools → Actions:
   `relay_1_off` appeared and worked; `relay_2_on` **did not appear as a selectable action at all**
   — not a failed call, a genuinely nonexistent service from HA's perspective.
4. Hypothesis: `shell_command:` entries are only registered at HA core startup/full restart, not
   on a YAML reload — a full restart was performed as the fix.
5. **Full restart completed. `relay_2_on` still did not appear in Developer Tools → Actions.**
   Session ended here (user fatigue) with the problem apparently unresolved despite the presumed
   fix.
6. Logs from the restart window (`2026-07-05 18:55:53` onward) reviewed the next day: **no error,
   warning, or any mention whatsoever of `shell_command`, `relay_2`, or a failed service
   registration.** Unrelated entries only (HACS custom-integration warning, Bluetooth capability
   warning, one MQTT sensor value-type warning for `sensor.wind_direction`). A malformed or
   failed-to-register shell_command entry would be expected to log loudly; total silence is
   consistent with a clean, successful load at that restart.
7. The following morning, with **zero config changes made in between**, the microwave manual shed
   toggle worked correctly in both directions via the dashboard.

### Leading explanation (NOT confirmed — inferred from indirect evidence only)

The Developer Tools → Actions page loads its list of available services once, when that browser
tab/session is loaded. If the same tab (or an HA frontend session predating the restart) was used
to check for `relay_2_on` immediately after restarting, it may have been displaying a **stale,
pre-restart service list** rather than actually re-querying HA post-restart. Under this theory,
`relay_2_on` was successfully registered at the 18:55:53 restart the whole time — the tool used to
check for it just hadn't refreshed. This fits every piece of evidence gathered (silent/clean logs
at restart time, working automation the next day with no changes, prior confirmation that
automations.yaml and configuration.yaml were both already correct before the restart even
happened).

**This has NOT been proven.** No test was performed with a deliberately fresh/hard-refreshed
Developer Tools session immediately after the restart to confirm this theory directly. It remains
the most plausible explanation, not a demonstrated one.

### Standing rule adopted (regardless of root cause)

**After any HA restart intended to pick up new or changed `shell_command:` entries, verify via a
hard-refreshed or newly-opened Developer Tools tab — not a tab that was already open before the
restart — before concluding the fix did or didn't work.** Cheap to do, would have resolved this
same night if followed at the time.

### Reliability note (carried forward, not resolved here)

Filed as a data point against Section 9.1's open Phase 7 question — whether load-shed actuation
belongs in HA at all, versus a standalone Python controller with no UI-caching layer between a
state change and a relay write. This incident does not prove HA is unsuitable; it does add a real
instance of "looked broken, wasted significant troubleshooting time, root cause remains unconfirmed"
to the evidence Section 9.1 explicitly says to accumulate before deciding. No action taken on that
decision now — revisit per the existing Phase 7 criteria (after Tier 3 has real operating history).

---

### Not yet done

- Root cause of the apparent restart-then-still-broken-then-fixed sequence remains unconfirmed.
  If this recurs, test with a hard-refreshed Developer Tools tab immediately post-restart to
  either confirm or rule out the stale-session theory directly.
- `sensor.wind_direction` MQTT value-type warning (Acurite 5n1 message type 56 lacking a direction
  field, likely only present on message type 49 per 2026-06-30 notes) — not investigated, logged
  here so it isn't lost.
- HACS custom-integration and Bluetooth NET_ADMIN/NET_RAW warnings — informational only, no action
  needed unless Bluetooth integration is actually in use.

---
*Session notes prepared 2026-07-06 — append to Section 8 session log in project reference.*
