# RVTC — Session Notes 2026-07-06 (early morning)
## Manual Load Shed — Intermittent Failures, Root Cause Still Open (Restore-Check Race Suspected)

---

### Summary

Extended live troubleshooting session on the Manual Load Shed switches (water heater + microwave)
following on from the "microwave relay appeared broken" incident logged separately
(`RVTC_SessionLog_20260706_MicrowaveRelay.md`). That earlier incident was tentatively attributed to
a stale Developer Tools session. Tonight's session went much further and **ruled that explanation
out as the whole story** — the underlying issue is real, intermittent, and still unresolved.

**Do not treat this as fixed.** Both switches are working normally as of session end, but the
failure is confirmed intermittent, not resolved.

---

### What was proven solid tonight (ruled out, high confidence)

Through direct, systematic testing, the following were each independently confirmed working
correctly and are **not** the cause of the intermittent failures:

- The Waveshare relay board itself, wiring, and polarity — confirmed via direct `mbpoll` calls to
  the gateway (192.168.88.12:4001), both coils, both directions
- `relay.py` itself — confirmed via `docker exec homeassistant python3 /config/relay.py 0 1` (and
  `0 0`) run directly inside the HA container, bypassing HA's automation/service layer entirely —
  worked correctly, water heater relay clicked as expected
- The HA container's network path to the relay gateway — proven by the above
- HA's `shell_command` service registration and execution — confirmed via Developer Tools →
  Actions, manually typing `action: shell_command.relay_2_on` / `relay_1_on` directly (bypassing
  search/autocomplete) — both fired correctly and energised the relays
- The automations' YAML config (`Manual Shed - Water Heater` / `Manual Shed - Microwave`) —
  reviewed line by line, structurally correct and identical in pattern, correctly cross-referencing
  `relay_1_*` (water heater, coil 0) and `relay_2_*` (microwave, coil 1)
- A full trace capture (JSON export, 2026-07-06T07:59:53Z run) of the microwave shed automation
  shows the `choose` block correctly selecting branch 0 (shed), and
  `action/0/choose/0/sequence/0` (`shell_command.relay_2_on`) completing cleanly with correct
  parameters and no error, in ~165ms end to end

**Conclusion: the hardware, network, shell_command layer, and automation YAML are all sound.**
A theory suggesting "Developer Tools UI staleness" or a generic "UI/WebSocket blip" was raised
during this session and explicitly retracted — it does not fit the evidence and should not be
reused as an explanation without new supporting evidence.

### What was actually observed failing (the real symptom)

Precise, confirmed sequence from this session:
- **Microwave**: single press of the manual shed switch → correct result (power restored as
  expected). Worked correctly this time.
- **Water heater**: single press of the manual shed switch → **no effect whatsoever** — no relay
  action, and (based on prior trace evidence for the equivalent microwave case) this kind of
  "nothing happens" result would be expected to still show a clean trace if HA's automation layer
  ran at all. First press: nothing. Second press: worked correctly.

This is the second time in two sessions that a manual shed switch has behaved inconsistently with
no config change in between (see the separate 2026-07-06 microwave log for the first instance).

### Standing hypothesis — NOT YET CONFIRMED — a restore-check race condition

`automations.yaml` contains this pattern (shown for grid; generator has an identical twin):

```yaml
- alias: "Tier 3 - Grid Restore Check"
  trigger:
    - platform: time_pattern
      minutes: "/1"
  condition:
    - condition: or
      conditions:
        - condition: state
          entity_id: input_boolean.coil1_energised
          state: "on"
        - condition: state
          entity_id: input_boolean.coil2_energised
          state: "on"
  action:
    - service: script.tier3_grid_restore
```

This runs **unconditionally every 60 seconds** and only checks whether a coil is currently marked
energised — it has **no way to distinguish a coil energised by a genuine Tier 3 overload shed from
one energised by a manual override toggle**. The manual shed automations set
`input_boolean.coil1_energised` / `coil2_energised` to "on" as part of shedding a load (confirmed
in both automations' YAML). If `tier3_grid_restore` / `tier3_generator_restore` (contents not yet
reviewed — this is the critical missing piece) restore power whenever current is under threshold,
**without also checking whether `manual_shed_water_heater` / `manual_shed_microwave` is currently
on**, then a manual shed and an automatic restore-check are directly fighting over the same coil,
on a timer, with no error ever being raised by either side — because neither automation is doing
anything wrong from its own point of view.

This would fully explain the observed pattern: intermittent, timing-dependent, no trace/log
evidence of anything failing, "sometimes needs a second press," and would explain why this wasn't
caught earlier if testing tended to toggle a switch on and back off again quickly (before the
1-minute restore-check window could fire).

**This has NOT been confirmed.** `scripts.yaml`'s `tier3_grid_restore` and
`tier3_generator_restore` have not yet been reviewed to check whether they actually reference the
manual override input_booleans at all.

### What to check next time this recurs (do this before touching anything else)

1. **Check Logbook first, before re-testing anything** — look for `tier3_grid_restore` or
   `tier3_generator_restore` having fired, and for `coil1_energised`/`coil2_energised` changing
   state, around the same time as the failed switch press — even if you didn't touch those
   entities yourself. If either restore script ran within ~60 seconds of your manual toggle, that
   confirms the race directly.
2. **Get `tier3_grid_restore` and `tier3_generator_restore` from `scripts.yaml`** and check whether
   either references `input_boolean.manual_shed_water_heater` / `manual_shed_microwave` as a
   condition before restoring. Their absence would confirm the hypothesis outright without needing
   to catch it live at all.
3. If confirmed: the fix is to add a condition to both restore scripts (or the restore-check
   automations) — do not restore a coil if its corresponding manual-shed input_boolean is currently
   "on". This is a small, contained fix once confirmed.

### Explicitly retracted this session

A theory that this was a stale Developer Tools browser session, or a general UI/WebSocket
connectivity blip, was proposed and pushed back on correctly. It does not explain a press
registering literally zero effect with no trace and no log entry, and should not be reached for
again as an explanation without genuinely new supporting evidence.

### User decision

Both switches are working normally as of session end. Rather than continue chasing an
intermittent fault that isn't currently reproducing, the plan is: **wait for the next failure,
then check Logbook/traces from that specific moment** (per the steps above) rather than
re-running the same hours-long manual isolation process from scratch.

---

### Not yet done

- `scripts.yaml`'s `tier3_grid_restore` / `tier3_generator_restore` — not yet reviewed; this is
  the single highest-value next step whenever this is picked back up, confirmable without waiting
  for a live failure
- Confirm whether the water heater's restore-check race (if it exists) has the identical exposure
  as the microwave's, given both share the same `coil1_energised`/`coil2_energised` +
  time_pattern(/1 minute) restore-check pattern

---
*Session notes prepared 2026-07-06 — append to Section 8 session log in project reference,
immediately following the same-day microwave relay entry.*
