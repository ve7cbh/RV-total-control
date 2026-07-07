# RVTC — Session Notes 2026-07-05
## EVO-2212 Operating Mode Mapping Correction + Unexplained Control-Node Reboot

---

### Summary

Confirmed and fixed a wrong `operating_mode` mapping for the SAMLUX EVO-2212 that had been an
open item since 2026-06-28 (mode 2 = Charging was confirmed then; mode 1/3 were still guesses).
Separately, the control node (`ve7cbh-control`, running HA, MQTT, Telegraf, nginx, etc. in Docker)
lost power and cold-booted mid-session, in close time proximity to inverter/grid transfer testing.
Root cause not confirmed — noted as an open item, not closed.

---

### Part 1 — EVO-2212 `operating_mode` mapping corrected (OI item from 2026-06-28, now resolved)

**Background:** On 2026-06-28, mode 2 was confirmed as "Charging" via a real charging event. Mode
3 was *guessed* to be "Inverting" based on typical inverter status ordering, explicitly flagged
as unconfirmed pending the next real grid outage.

**Live test 2026-07-05:** User observed the dashboard displaying "Line" while genuinely on
battery (KWS-303L grid current 0.000A, EVO Batt A 41–61A discharge, Out V/Hz normal) — i.e. a real
mismatch between actual state and displayed state. Captured raw register value via:
```bash
mosquitto_sub -h localhost -t 'rvtc/sensors/inverter/operating_mode' -v
```
Confirmed:
- **Mode 1 = Inverting** (on battery) — raw value captured live during an actual battery-only
  condition
- **Mode 2 = Charging** (on grid) — re-confirmed, unchanged from 6/28
- **Mode 3** — previously assumed to be "Inverting"; that assumption is now disproven. True meaning
  unconfirmed, reopened as an open item (possibly "Line"/passthrough-without-charging, but this is
  a guess, not yet observed live)
- Modes 0 (Standby), 4 (Bypass), 5 (Fault) — never confirmed, remain guesses

**Files corrected (`OPERATING_MODES` dict and `INV_MODE_MAP` swapped to match confirmed values):**
- `samlux_mqtt.py` (`/home/ve7cbh/RV-total-control/config/`) — `OPERATING_MODES` dict corrected,
  mode 1→"inverter", mode 3→"line" (unconfirmed), comments updated to reflect confirmed vs.
  guessed status per key
- `index.html` (`/data/docker/volumes/nginx/rvtc/`) — `INV_MODE_MAP` swapped to match: mode 1 now
  renders "Inverting" (badge-boost/solar colour), mode 3 now renders "Line" (badge-float/green)

**Verified working live (both directions), post-fix, via dashboard screenshots:**
- On battery: dashboard correctly shows amber **"INVERTING"**, matching real battery discharge
- On grid: dashboard correctly shows green **"CHARGING"**, matching real grid draw

**Process note:** edits made via the established `python3` heredoc find-and-replace pattern
(exact old/new string blocks, "PATTERN NOT FOUND — aborting" safety check), consistent with the
2026-06-30 session's recommendation. Both edits succeeded on first attempt.

**Still open:**
- Mode 3 ("line" label, unconfirmed) — needs a real observation of the EVO in grid-passthrough
  without active charging (e.g. battery already full while on grid) to confirm
- Modes 0, 4, 5 — no live confirmation opportunity yet; leave as-is until observed

---

### Part 2 — Control node unexplained reboot during testing (root cause open, not resolved)

**Observed:** Mid-session, immediately after running `sudo systemctl restart samlux_mqtt`, the SSH
session dropped (`client_loop: send disconnect: Connection reset`). Reconnecting showed a new
kernel version running (`6.12.94+deb13` vs. the prior session's `6.12.90+deb13.1`) — the host had
rebooted, not just the one service. The Docker nginx container came back automatically but
required a manual `docker restart nginx` to serve correctly; all containers reattached to the
bridge network simultaneously per `dmesg` (consistent with full host reboot, not a single
container restart). Several Modbus gateways (EPEVER, SAMLUX, KWS-303L) logged `UFW BLOCK` entries
immediately post-boot — read as normal transient noise from in-flight TCP sessions that didn't
survive the reboot, not a separate fault.

**Ruled out:**
- **`samlux_mqtt.py` itself** — `journalctl -u samlux_mqtt` shows continuous clean `Poll OK`
  messages with no errors, gaps, or exceptions right up to the last line before the boot ends.
  The restart command itself has no plausible mechanism to reboot the host.
- **Scheduled/automatic OS update reboot** — no `unattended-upgrades` log exists on this host at
  all (not installed/configured to auto-reboot). The most recent kernel install
  (`linux-image-6.12.94+deb13-amd64`) was a manual `apt upgrade` on **2026-06-30 at 17:05** — five
  days before this reboot — so a pending-kernel-install auto-reboot doesn't fit the timing.
- **Clean/deliberate shutdown** — `journalctl -b -1 -e` (the boot immediately prior) ends abruptly
  mid-stream on normal operational log lines (`Poll OK`, `Grid poll OK`), with no
  `systemd-shutdown`, unmount, or power-off target messages of any kind. This is the signature of
  a hard power loss to the box, not an intentional reboot.

**Correlated but NOT confirmed as causal:**
- Boot -1 ends at **11:59:39 PDT**, ~3 seconds after the `systemctl restart samlux_mqtt` command's
  sudo session closed (11:59:35) — and squarely within the window the user was actively testing
  grid↔inverter transfer on the EVO-2212 (dashboard screenshots at 11:59 and 12:04 show the
  transition being exercised).
- **Important caveat (raised by user, correctly):** the EVO-2212 is a UPS-rated inverter/charger;
  a compliant transfer should complete in single-digit-to-low-double-digit milliseconds — far
  below what would cold-boot a PC-class device with normal PSU hold-up capacitance. If the EVO
  performed to spec, source transfer alone does not explain a full reboot, and this correlation
  should not be treated as a confirmed cause.
- The EVO-2212 does not maintain an event log (fault codes only, no historical record). Dashboard
  Error Code read **"None"** in both post-incident screenshots. **Checked same day: front panel
  also shows no latched fault code.** This doesn't rule out a transient fault that self-cleared
  before being checked, but it's a second clean read (dashboard + panel), which weakens the case
  for the EVO itself having faulted during the transfer.

**Status: root cause NOT determined.** Do not treat the transfer-event correlation as confirmed
causal. With the EVO now checked clean on both dashboard and front panel, the balance of evidence
leans slightly away from "EVO faulted during transfer" and toward either a marginal connection/PSU
issue specific to the J45's own power path, or an unrelated coincident event elsewhere in the RV —
neither yet confirmed.

**Planned mitigation (structural, independent of root cause):**
- J45 currently runs on 120VAC; project plan is to migrate it to 12VDC as the build progresses
- Additionally considering a DC-DC power supply ahead of the J45 specifically to buffer against
  wider system voltage swings, regardless of source
- Neither of these should be treated as "fixing" this specific incident — they're planned
  resilience improvements. If the true root cause is unrelated to power quality (e.g. a genuine
  kernel/hardware fault), a DC-DC buffer would not prevent recurrence.

**Recommended for next occurrence:**
1. Note exact time of the drop and cross-reference against `journalctl -b -1 -e` on next boot
   before doing anything else
2. If it recurs during another deliberate transfer test, consider scoping a multimeter/logger on
   the J45's incoming 120VAC during the transfer to directly observe whether a dropout actually
   occurs and how long it lasts, rather than inferring from side effects
3. Given the EVO checked clean this time, focus troubleshooting on the J45's own power path first
   if it happens again (cord, connector, PSU) rather than re-suspecting the EVO by default

---

### File inventory — files touched this session

| File | Location | Change |
|---|---|---|
| `samlux_mqtt.py` | `/home/ve7cbh/RV-total-control/config/` | `OPERATING_MODES` dict corrected (modes 1/3 swapped) |
| `index.html` | `/data/docker/volumes/nginx/rvtc/` | `INV_MODE_MAP` corrected (modes 1/3 swapped) |

---

### Next Session Priorities (additions to existing list)

1. Confirm mode 3 ("line," unconfirmed) by observing EVO in grid-passthrough while not actively
   charging (e.g. battery already full)
2. If reboot recurs: check EVO front panel for latched fault before anything else; capture
   `journalctl -b -1 -e` promptly
3. Evaluate DC-DC power supply for the J45 as a planned resilience upgrade (separate from, not a
   substitute for, root-causing this incident)
4. (Carried over) KWS grid/generator disconnect switches still not added to Load Control
   dashboard; live bench test of Tier 3 automatic trigger still outstanding; remove empty
   `kws303l/` directory

---
*Session notes prepared 2026-07-05 — append to Section 8 session log in project reference.*
