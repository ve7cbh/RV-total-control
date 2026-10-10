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

## Immediate next step (pick up here)

1. Re-open the LIN decoder options on a clean, fully-margined capture (idle visible before
   the break and after the final checksum/next break).
2. Confirm baud rate under the LIN decoder — try 300 first (matches everything validated
   under plain UART), and only move off it if framing/checksum doesn't validate cleanly.
3. Once settings are trusted, redo the state-comparison captures **using the LIN decoder**,
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

### Open / unresolved — pick up here

1. **COOL 24° (`0x91`=145) and COOL 25° (`0x95`=149) don't fit the −4/°C line**
   (predicted `0x8F`=143 and `0x8B`=139). Both of these files' raw per-cycle data was
   noticeably less consistent than 20–23 (COOL_25 in particular never produced two matching
   cycles at all — every repeat decoded slightly differently). **Treat 24° and 25° as
   unreliable, not as evidence the formula breaks down** — redo both the same tight,
   back-to-back way COOL_21/22 were redone.

2. **HEAT's byte 3 sat flat at `0x95` across all 5 HEAT filenames (22°–26°).** Given how
   clean the COOL linear result turned out to be, the likely explanations, in order of
   likelihood: (a) HEAT uses a different base/offset than COOL for the same linear formula
   — plausible, worth testing directly; (b) the thermostat's on-screen setpoint didn't
   actually change between some of those captures (worth double-checking display photos/
   memory from that session, if any); (c) HEAT genuinely encodes setpoint differently.
   **Redo 2–3 HEAT setpoints back-to-back, tightly spaced, the same way COOL_21/22 were
   redone**, and check whether the same −4-per-degree step (or some other constant step)
   shows up relative to whatever HEAT's baseline turns out to be.

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
   every file — consistent with residual baud-precision error accumulating later in longer
   frames (see the baud-rate section above, still not fully pinned down: confirmed working
   range 1208–1250, exact center not yet found). Once baud is nailed precisely, checksum
   validation (once the checksum formula is known) would let bad frames be discarded
   automatically instead of relying on majority-vote-by-eye/script.

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
