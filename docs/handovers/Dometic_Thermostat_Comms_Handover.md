# Dometic Thermostat — Comms Wire Reverse Engineering — Handover Note

**Date:** 2026-09-05
**Context:** RVTC project — single-wire comms line between Dometic thermostat and AC control board (relevant to HW-20 / OI-38, ESP32-S3 thermostat controller work).
**Tooling:** PulseView + Hantek 6022BE logic analyzer/scope, probing the COMMS wire at the thermostat end.

---

## Status: Protocol identified, decoding not yet trusted — pick back up here

The wire is **not** Dallas/Maxim 1-Wire, and plain async UART decoding gave inconsistent,
contradictory results across captures. The signal has now been correctly identified as
**LIN-like** (break-condition-framed serial), which explains the earlier inconsistencies.
**Stopped mid-verification of the LIN decode settings** — do not treat any byte values
below as final until that's confirmed (see "Immediate next step").

---

## Physical / electrical background (confirmed from RV forum research, not captured)

- Dometic 3-wire thermostats use **12V, ground, and a single proprietary comms wire**
  back to the AC unit's control board — not real Dallas 1-Wire, despite the "single wire"
  framing inviting that assumption.
- This matches what was found on the bus: a single-conductor serial link with its own
  framing convention, not a sensor-style 1-Wire bus.

## Dead ends / ruled out — don't re-chase these

- **Dallas/Maxim 1-Wire decoder**: produces plausible-looking bit/byte annotations but
  throws CRC/ROM-ID warnings throughout. Timing doesn't match 1-Wire's spec (60–120 µs
  slots, ~480 µs reset) at all. Ruled out.
- **Plain async UART @ 300 baud, no break/frame anchor**: gave clean-looking S...T byte
  decodes with occasional framing errors (FE) recurring at consistent points inside every
  byte. Cross-state comparisons using this method were **internally inconsistent** —
  e.g. OFF and "COOL 24°" shared an identical byte 1 (`0x63`), but "COOL 23°" (same mode,
  1° different) had a completely different byte 1 (`0xA1`), while its byte 2 matched OFF's
  byte 2 instead. This pattern (values matching across the *wrong* byte positions) was the
  clue that frame alignment was inconsistent between crops, not that the states themselves
  were doing something equally inconsistent.
- **The very first "single short glitch pulse" investigation** (0.875 µs pulse at the front
  of a capture): measured far too short to be meaningful on its own at the time, dismissed
  as line noise/ringing. In hindsight this was very likely a fragment of the real LIN break
  condition — the crop just didn't capture the whole thing. Not a wasted step; just
  superseded by the LIN finding below.
- **Fan speed (Low vs. High) is NOT distinguished by the plain-UART 3-byte reading.**
  Confirmed the fan audibly changes speed between captures, but the naive 3-byte decode
  (`0x23 / 0x41 / 0x1F`) came back byte-for-byte identical for both Low and High. This may
  turn out to be explained once the full LIN frame (8 data bytes, not 3) is decoded
  correctly — don't assume this dead end still holds once the LIN decode is verified.
- **Baud rate is not the problem.** Briefly suspected ~268 baud based on a long low-sample-
  rate capture decoding lots of `0x60/0xE6/0xFF` — but `0xFF` (all-ones) repeating like that
  is the signature of the decoder finding spurious "bytes" in idle-line gaps, not a real
  baud mismatch. 300 baud (as plain UART) and the *break-condition* framing are consistent
  with everything captured so far.

## Key finding — LIN-style framing

Using PulseView's **LIN** protocol decoder (not UART) on the same capture:

- The decoder correctly identifies **Break condition** fields between frames — a long,
  deliberate low pulse that plain-UART decoding has no concept of and was silently
  mis-framing around.
- Each frame carries an **ID byte with 2 parity bits** (LIN convention: bits 6:7 are parity
  over the ID). Example frame: raw ID byte `0x9F` → **ID = 0x1F** after stripping parity
  bits.
- **Parity check currently reads "P != 0" (fails)** on the one frame inspected so far. This
  is *expected* and not necessarily a problem — this bus almost certainly is not a fully
  spec-compliant LIN bus (no evidence of a proper LIN sync byte either); it's most likely a
  proprietary protocol that reuses LIN's break/ID/data/checksum *shape* without implementing
  official LIN parity. Don't chase this as an error — just confirm it's consistently
  "failing" the same way on every frame (that would support "proprietary, LIN-shaped, not
  real LIN" as the working theory) rather than sometimes passing.
- Each frame has **8 data bytes** (much richer than the 2–3 byte plain-UART slices worked
  with earlier), followed by a **checksum byte**, followed by the next break condition.

### Example frame captured (state at time of capture not logged — treat as structural example only, not a state reading)

```
Break | ID: 0x1F (P != 0) | D:0xCB D:0x97 D:0x14 D:0x7E D:0xD8 D:0x3E D:0xF2 D:0x3E | Checksum: (cut off) | Break
```

A second, wider capture (2M samples, 4MHz) was taken with the **LIN decoder options panel
open** to configure it properly — settings visible at the point of stopping:

| Setting | Value shown |
|---|---|
| Baud rate | 1250 *(likely being experimented with — not confirmed correct, see below)* |
| Data bits | 8 |
| Parity | none |
| Bit order | lsb-first |
| Data format | hex |
| Invert RX | yes |
| Invert TX | yes |
| Sample point | 50% |

**⚠️ The 1250 baud value in that screenshot has not been validated.** All prior confirmed
work (the plain-UART bytes that repeated consistently across captures) pointed to **300
baud**. Don't assume 1250 is correct just because it's what was in the box when the session
stopped — it may have been mid-adjustment. Re-derive or re-confirm baud rate under the LIN
decoder specifically before trusting any byte values from it.

## Baud rate — confirmed at 1245 (sweep completed, this is the split-the-difference result)

The baud-rate sweep flagged as unfinished earlier in this document **was completed**: low
edge found at 1208, high edge found at ≥1250, and **1245 is the split-the-difference
result** of that sweep — not a fallback or an approximation. All of today's captures (the
full COOL 20–25, FAN Auto/High/Low, HEAT 22–30, OFF batch, plus the thumb and furnace tests)
were taken at this confirmed rate, and the results bear it out: clean, consistent,
cross-validated multi-byte frames throughout (the COOL setpoint formula, the mode field, and
the HEAT setpoint field all lined up correctly across many independent captures). **Treat
1245 as the confirmed working baud rate going forward** — no further tuning needed unless
decode quality noticeably degrades in a future session (which would suggest genuine
oscillator drift over time, worth re-sweeping if it happens, rather than a wrong original
value).

## Immediate next step (pick up here)

1. Re-open the LIN decoder options on a clean, fully-margined capture (idle visible before
   the break and after the final checksum/next break).
3. ~~Confirm baud rate under the LIN decoder~~ — **done, see "Baud rate — confirmed at
   1245" above.** The sweep was completed (low edge 1208, high edge ≥1250) and 1245 is the
   split-the-difference result, validated across a full session of captures.
4. Redo the state-comparison captures **using the LIN decoder**,
   not plain UART:
   - OFF
   - COOL at 2–3 different setpoints, same fan mode (isolate temperature encoding)
   - Same mode/setpoint, two different fan speeds (retest whether Low vs. High actually
     differ once the full 8-byte frame is read correctly — the earlier "identical" result
     may have been an artifact of misaligned 3-byte slicing, not a real dead end)
   - HEAT, same setpoint as one of the COOL captures (isolate mode bits from setpoint bits)
4. Check whether **ID (0x1F in the one example above) stays constant** across all of the
   above, or changes. If constant → single broadcast frame carries full status, all state
   lives in the 8 data bytes + checksum. If it changes → thermostat may be using different
   IDs for different message/event types, and a lot of the earlier "3-byte" captures may
   have actually been a *different, shorter* frame type entirely, not a mis-sliced version
   of this one.
5. Once 2–3 full 8-byte frames are captured cleanly at different states, diff byte-by-byte
   the same way we were doing with the 3-byte reads — much better odds of getting clean,
   isolated bit/byte fields now that framing is anchored correctly on the break condition.

## Update — full-frame state captures (raw PulseView text exports, parsed programmatically)

A batch of 15 raw text exports (state-labeled by filename: OFF, COOL 20–25, FAN Auto/High/
Low, HEAT 22–26) were parsed with a script (`parse.py`, logic below) that groups decoded
bytes into frames by timestamp gap, then majority-votes each byte position across all
repeats within a file to filter out per-cycle decode noise rather than trusting any single
cycle. **`COOL_22.txt`'s first submission was a duplicate of `COOL_21.txt`** (confirmed
byte-for-byte via `diff`, off by only 3 leading lines from an earlier capture start point) —
a genuine redo was captured afterward and is what the findings below are based on.

### Confirmed findings

**Byte 1 — frame ID, constant.** Always decodes as `0x9F` (or `0x1F`, same value with the
LIN parity bits noisy) in every file, every state. Matches the ID=0x1F found in the original
LIN-decoder screenshot. Solid.

**Byte 2, bits [5:4] — mode field, confirmed.** Majority-voted correctly against the
filename in 13 of 15 original captures (the 2 misses were single noisy cycles, not a wrong
theory):

| Mode | Byte 2 | Bits [5:4] |
|---|---|---|
| FAN only | `0xCB` | `00` |
| HEAT | `0xDB` | `01` |
| COOL | `0xEB` | `10` |
| OFF | `0xFB` | `11` |

**Byte 3 — setpoint, confirmed linear in COOL mode.** Once COOL_22 was recaptured for real,
four clean, independent points line up exactly:

| Setpoint | Byte 3 | Decimal | Step |
|---|---|---|---|
| 20° | `0x9F` | 159 | — |
| 21° | `0x9B` | 155 | −4 |
| 22° | `0x97` | 151 | −4 |
| 23° | `0x93` | 147 | −4 |

Formula: **byte3 = 159 − 4×(°C − 20)**, at least over this range. This directly
**contradicts and replaces an earlier working theory** (floated mid-session, before the
COOL_22 redo) that byte 3 was sensed ambient/room temperature rather than the setpoint —
that theory was reasonable given the data available at the time (HEAT's byte 3 stayed flat
across 5 different filenames) but doesn't survive this clean 4-point linear COOL result.
Treat the ambient-temperature idea as retired unless new evidence revives it.

**Fan speed — reconfirmed absent from this frame, now via 3 full independent captures.**
FAN_AUTO, FAN_HIGH, FAN_LOW canonical frames are effectively identical
(`CB 93 52 FA Dx 3E F1 3E 05`, mode field constant, byte 3 constant at `0x93`). Whatever
distinguishes fan speed physically, it is not in this broadcast message. Not re-litigating
this unless a full-frame LIN capture (with checksum validated) says otherwise.

### Correction — byte 3 is the stored COOL setpoint, not "the active setpoint"

**Operational fact that resolved a lot of confusion:** the thermostat has a separate stored
setpoint per mode — a COOL setpoint and a HEAT setpoint — and switching modes does not
erase the one you're not currently using. **Byte 3 is specifically the stored COOL
setpoint**, broadcast in every frame regardless of which mode is currently active. This
explains every earlier "coincidence" that looked confusing:

- OFF and FAN captures both showed `0x93` (23°C) — because COOL had last been set to 23°,
  not because OFF/FAN "remember the last active setpoint" in some mode-agnostic sense.
- The original HEAT 22°–26° batch showed a flat `0x95` (~22.5°C) throughout — not because
  HEAT's setpoint wasn't changing, but because COOL's *stored* setpoint wasn't touched
  during that session. Byte 3 was accurately reporting COOL's setpoint the whole time; it
  was never the field being tested.
- The recent HEAT 30° w/ hot-cloth test showed `0x97` (23°C) — matches, since COOL had most
  recently been left at 23° from the earlier redo tests.

This does not invalidate the COOL setpoint formula (159 − 4×(°C−20), confirmed 20–23°) —
it just corrects the label from "the active setpoint" to "the stored COOL setpoint,
mode-independent."

### New finding — HEAT setpoint identified as a separate field

A clean sweep across HEAT 27°/28°/29°/30° (with byte 3 correctly holding steady at `0x97`
throughout, confirming the correction above) isolated a second, HEAT-specific setpoint byte,
using a similar linear convention to COOL's. The frame appears to come in **two distinct
tail shapes** (a genuine structural split, not noise — see the two-frame-family note below),
and the setpoint-tracking byte sits at a different position in each:

| Frame shape | 27° | 28° | 29° | 30° |
|---|---|---|---|---|
| "No-FA" shape (seen at 27°, 28°) | `BF` (191) | `BB` (187) | — | — |
| "Has-FA" shape (seen at 29°, 30°) | — | — | `DF` (223) | `DC` (220) |

Step size: **−4** (27→28) and **−3** (29→30, likely −4 with one unit of decode noise —
this frame shape has generally been the noisier of the two throughout this project). Both
consistent with the same roughly-4-units-per-degree convention COOL uses, just a separate
byte/base value.

**Confidence: solid but not airtight** — two adjacent-degree pairs, one clean, one nearly
clean. One more clean adjacent pair (ideally landing in the same frame shape twice) would
confirm this beyond doubt.

**False lead, worth remembering so it isn't re-chased:** the byte immediately after the mode
byte in each frame shape (`C2` in both the 27° and 28° "no-FA" captures) looked like an
obvious setpoint candidate at first glance but did not move between 27° and 28° — ruled out.

### Correction — the "byte after FA" field is dynamic, not setpoint-linked

A candidate field (the byte immediately following the `FA` landmark byte, in whichever
capture happened to land in the "has-FA" frame shape) briefly looked promising: it showed a
clean `+1` per degree step across both a COOL 23°→25° sweep (`C0`→`C1`→`C2`) and a HEAT
29°→32° sweep (`DC`→`DD`→`DF`), suggesting a shared, mode-agnostic setpoint-linked field.
**That theory doesn't survive a repeat test at the same setpoint.** Two separate COOL 23°
captures, taken at different points in the session (compressor freshly engaged in one; after
a fan-speed auto-step and compressor restart in the other), gave completely different values
for this byte — `C0` (192) vs `DE` (222) — while byte 3 (the confirmed setpoint field)
stayed identical at `93` in both. Since setpoint didn't move but this byte did, it isn't
setpoint-linked. **More consistent explanation: this byte tracks something dynamic** — most
likely sensed ambient/coil temperature, or a compressor/duty-cycle-linked value — and the
earlier `+1/°C` pattern was very likely a coincidence of that specific session (real cabin
temperature happened to trend in step with the setpoints being dialed through in quick
succession, since the room was actively responding during that test). Not disqualified as
interesting, just relabeled: **dynamic field, likely sensed temperature or duty-related,
not a setpoint.**

### Confirmed real behavior — sustained bus-low period on auto fan step-down

Observed once, described as normal operating behavior by the person running these tests: in
COOL mode with fan set to Auto, as the room temperature approaches the setpoint, the AC
steps its fan down to Low automatically. During this transition, one capture showed the
entire window (multiple seconds, no large idle gaps at all) decoding as continuous `0x00`
bytes with no break conditions and no normal frame structure — a sharp contrast to every
other capture, which all show clean periodic `break → ID → data → checksum` frames with
~1.8M-tick idle gaps between repeats. **This is very likely a real bus behavior tied to the
auto fan-speed step, not noise or a capture fault** — a follow-up capture taken shortly after
(once the compressor had restarted) showed completely normal framing resume cleanly, so
whatever happens during the transition is transient and self-recovering, not a lasting fault
condition. **Not yet fully characterized** — worth a future capture spanning before, during,
and after the transition (including the reverse: fan stepping back up from Low as the room
drifts away from setpoint) to see exactly how long the sustained-low period lasts and whether
it's consistent every time. Fan speed has never shown up as a discrete field in the normal
frame (see "Fan speed — reconfirmed absent" above) — this raises the possibility that fan
*transitions* (as opposed to steady-state fan speed) might be signaled by bus behavior rather
than by frame content, which would be a different kind of signal than anything else
characterized so far.

### Two-frame-family theory — now has real supporting evidence, not just a hunch

Multiple captures this session (Thumb vs Thumb2/3, the HEAT 27–30 sweep) show the frame's
tail arriving in two distinct shapes — one with an `FA` landmark byte in a fixed position,
one without — even when the mode and both setpoints are unchanged from one capture to the
next. The HEAT setpoint finding above is the strongest evidence yet that these aren't just
noisy variants of one frame: the same real-world quantity (HEAT setpoint) tracks correctly
in *both* shapes, just at a shifted byte position, which is much more consistent with two
genuinely different message layouts sharing the bus than with random corruption.
**Recommend treating this as confirmed enough to design around**: when isolating a new
field, check whether a byte's apparent instability is actually two consistent values sorted
by frame shape, rather than writing it off as noise.

### Open / unresolved — pick up here

1. ~~COOL 24° and 25° may not be noisy data so much as a different operating regime~~ —
   **fully resolved with a complete 20°–28° sweep.** The compressor-idle hypothesis was
   disproven (identical byte 3 values reproduced with the compressor genuinely running). A
   simple "alternates between two values" hypothesis was also tested and disproven — 27°
   and 28° produced entirely new values, not a repeat of the 24°–26° pair. **Final
   conclusion: byte 3 is a real, accurate, reproducible field, but past 23°C it is not a
   linear formula — it's most practically treated as a lookup table.** Full confirmed table
   below (all values independently reproduced at least once across multiple sessions,
   including under active compressor operation):

   | Setpoint | Byte 3 | Decimal |
   |---|---|---|
   | 20° | `9F` | 159 |
   | 21° | `9B` | 155 |
   | 22° | `97` | 151 |
   | 23° | `93` | 147 |
   | 24° | `91` | 145 |
   | 25° | `95` | 149 |
   | 26° | `91` | 145 (identical to 24°) |
   | 27° | `9D` | 157 |
   | 28° | `99` | 153 |

   20°–23° follows a clean linear rule (`159 − 4×(°C−20)`). 24°–28° does not continue that
   rule or any simple alternation — the lower nibble sequence across the full range
   (`F,B,7,3,1,5,1,D,9`) is evenly-spaced for 20°–23° then genuinely irregular after,
   with no obvious repeating structure spotted so far. No working theory for *why* it
   scrambles there (possible firmware quirk, internal representation change, or something
   else) — flagged as unexplained rather than guessed at. **This table is fully sufficient
   for decoding purposes as-is** — no further formula-hunting needed unless curiosity
   demands it. If control software is ever built against this field, use the table directly
   rather than assuming any value outside 20°–23° can be computed.

2. ~~HEAT's byte 3 sat flat at `0x95` across all 5 HEAT filenames (22°–26°)~~ — **resolved,
   see "Correction" section above**: byte 3 is the stored COOL setpoint, not HEAT's. The
   real HEAT setpoint field has since been found (see "New finding" section above);
   confirming it with one more clean adjacent-degree pair is the remaining task. **Update
   pending:** a fresh 6-point HEAT 27°–32° sweep has since been captured and analyzed
   conversationally, refining the candidate to the byte immediately after `FA` in the
   "has-FA" frame shape (clean `+1/°C` across three points: 29°→30°→32°) — but this hasn't
   been written into the note yet at the person's request, pending the COOL 24°–28°
   characterization above being finished first so both can go in together.

3. **Two different "backbone" byte patterns appear in the tail of the frame (positions
   4–6), even for the same nominal state.** Original COOL_21 capture: `52 FA D8...`.
   Redone COOL_21 capture: `B9 BB C4...`. Both gave the *same* correct byte-3 setpoint
   value (`0x9B`) despite the different backbone — so this isn't corrupting the setpoint
   read, but it's an unexplained structural difference worth understanding. Leading
   hypothesis: **this bus may carry two distinct interleaved frame/message types** (e.g. a
   query and a response, or two different devices' periodic broadcasts sharing the wire) —
   worth checking in one long continuous capture whether the backbone shape strictly
   alternates frame-by-frame (A, B, A, B…) rather than appearing randomly.

4. Positions 8 and 10 (the tail, including the likely checksum byte) remain noisy in nearly
   every file — with baud now confirmed at 1245 (not a residual tuning issue), this noise is
   more likely explained by the two-frame-family structure discovered later in this document,
   or genuine bus-level noise, rather than baud imprecision. Once the checksum formula is
   known, checksum validation would let bad frames be discarded automatically instead of
   relying on majority-vote-by-eye/script.

### Parsing method (for reuse)

Raw PulseView text exports (`start-end UART: RX data: <value>` per line) were parsed with a
Python script that:
- Strips `Start bit` / `Stop bit` lines, keeping only byte values in order.
- Splits into frames wherever the gap between one byte's end-timestamp and the next byte's
  start-timestamp exceeds a threshold (300,000 ticks worked well — comfortably bigger than
  intra-frame gaps, comfortably smaller than the ~1.8M-tick gap between repeats).
- Within each file, majority-votes each byte position (and the derived mode field) across
  all repeats, rather than trusting any single cycle — this is what let the mode field and
  the COOL setpoint formula emerge cleanly from otherwise noisy raw decodes.

Recommend capturing future state comparisons the same way: raw PulseView text export (Export
> Annotations, or equivalent) rather than screenshots, so this same script can be rerun
directly instead of transcribing frames by hand.

## General lessons worth carrying forward

- **Always leave idle margin on both sides of a capture window.** Several early captures
  were cropped right at the first Start bit, which risked hiding exactly the kind of
  frame-start marker (the break condition) that turned out to matter.
- **A decoder producing clean-looking output is not proof it's the right decoder.**
  Plain UART gave zero framing errors on plenty of captures while still producing
  internally-inconsistent results across states — the absence of decoder warnings isn't
  the same as the decode being correct.
- **Repeat-capture validation (same state, captured twice) is cheap and worth doing early**
  — it's what caught the byte-2 toggle-bit behavior and would likely have caught the
  frame-alignment problem sooner if used more systematically from the start.
