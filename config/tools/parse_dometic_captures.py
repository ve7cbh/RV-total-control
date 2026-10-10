#!/usr/bin/env python3
"""
parse_dometic_captures.py — Dometic thermostat comms-wire capture parser (RVTC project)

Parses raw PulseView UART text exports (Export > Annotations, format:
"start-end UART: RX data: <value>" per line) into frames, majority-votes each
byte position to filter decode noise, and decodes the fields confirmed so far.

Usage:
    python3 parse_dometic_captures.py file1.txt [file2.txt ...]

Confirmed fields (see handover note for full history/evidence):
  - Byte 1: frame ID, always 0x9F/0x1F (LIN-style ID 0x1F, parity bits noisy)
  - Byte 2, bits [5:4]: mode field
        11 = OFF, 10 = COOL, 01 = HEAT, 00 = FAN-only
  - Byte 3: stored COOL setpoint, mode-independent (broadcast in every frame
        regardless of active mode). CONFIRMED as a lookup table, 20-28 degC,
        NOT a continuous formula -- an alternation/formula hypothesis was
        tested and disproven with a full sweep. See COOL_SETPOINT_TABLE below
        and the handover note for the full history/evidence. Treat byte3 as
        "stored COOL setpoint reading", NOT "active setpoint" (it holds the
        last COOL setpoint even while in HEAT/FAN/OFF mode).
  - Frame "family": frames vary between a shape containing a fixed 0xFA
        landmark byte and one without it. Not yet fully understood (see
        "Two-frame-family theory" in the handover note) -- this script flags
        which family a frame belongs to but does not assume field positions
        are comparable across families.

NOT yet confirmed / left for the person to interpret:
  - HEAT setpoint field (candidate: byte after FA landmark, in has-FA frames)
  - "Byte after FA" was briefly thought to be a shared dynamic temp field;
        walked back to "dynamic, likely sensed temp/duty-linked" -- do not
        treat as setpoint.
  - Checksum formula (last byte before the next break) -- unknown.
  - Fan speed -- confirmed ABSENT from normal frame content across many
        independent captures (Auto/High/Low all produce identical frames).
"""

import re
import sys
from collections import Counter

MODE_MAP = {0b11: 'OFF', 0b10: 'COOL', 0b01: 'HEAT', 0b00: 'FAN'}
FRAME_GAP_THRESHOLD = 300_000  # ticks; bigger than intra-frame gaps, smaller
                                 # than the ~1.8M-tick gap between repeats

# Confirmed byte3 -> stored-COOL-setpoint lookup table, 20-28 degC.
# 20-23 follows byte3 = 159 - 4*(degC-20); 24-28 does NOT continue that rule
# or any simple alternation -- confirmed irregular by direct sweep. Every
# value below has been independently reproduced at least once, including
# under active compressor operation, so this is treated as real data, not
# noise. Extend this table (don't guess a formula) if new setpoints are
# captured outside 20-28.
COOL_SETPOINT_TABLE = {
    '9F': 20, '9B': 21, '97': 22, '93': 23,
    '95': 25, '9D': 27, '99': 28,
    # '91' deliberately omitted here -- see COOL_SETPOINT_AMBIGUOUS below,
    # it maps to two different setpoints and must not be treated as single-valued.
}
# 26 degC decodes to the same byte as 24 (both '91') -- the device genuinely
# broadcasts identical bytes for these two different setpoints. This means
# byte3 alone CANNOT distinguish 24 degC from 26 degC. Reported as a set,
# not a single value, so callers don't silently pick the wrong one.
COOL_SETPOINT_AMBIGUOUS = {'91': (24, 26)}


def parse_file(path):
    """Returns a list of frames; each frame is a list of hex-string byte values
    in order (Start bit / Stop bit annotations are dropped)."""
    frames, cur, last_end = [], [], None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'(\d+)-(\d+) UART: RX data: (.+)', line)
            if not m:
                continue
            start, end, label = int(m.group(1)), int(m.group(2)), m.group(3)
            if label in ('Start bit', 'Stop bit'):
                continue
            if last_end is not None and start - last_end > FRAME_GAP_THRESHOLD:
                if cur:
                    frames.append(cur)
                cur = []
            cur.append(label)
            last_end = end
    if cur:
        frames.append(cur)
    return frames


def decode_mode(byte2_hex):
    try:
        val = int(byte2_hex, 16)
    except ValueError:
        return None
    bits54 = (val >> 4) & 0b11
    return MODE_MAP.get(bits54)


def cool_setpoint_from_byte3(byte3_hex):
    """Looks up the confirmed COOL setpoint table. Returns a tuple
    (result_str, is_ambiguous) -- result_str is either a single degree value,
    an ambiguous pair, or an "unknown" note for anything outside the
    confirmed 20-28 range. Does NOT extrapolate a formula past 23 degC --
    that was tried and disproven (see handover note)."""
    if byte3_hex in COOL_SETPOINT_AMBIGUOUS:
        pair = COOL_SETPOINT_AMBIGUOUS[byte3_hex]
        return f"AMBIGUOUS -- {pair[0]} or {pair[1]} degC (device broadcasts " \
               f"identical bytes for both, see handover note)", True
    if byte3_hex in COOL_SETPOINT_TABLE:
        return f"{COOL_SETPOINT_TABLE[byte3_hex]} degC", False
    return "not in confirmed 20-28 degC table -- see handover note", False


def has_fa_family(frame):
    return 'FA' in frame


def majority_vote_byte(frames, position):
    votes = Counter(fr[position] for fr in frames if len(fr) > position)
    if not votes:
        return None, 0
    return votes.most_common(1)[0]


def analyze_file(path):
    frames = parse_file(path)
    print(f"=== {path} ===")
    print(f"  {len(frames)} frames parsed")

    if not frames:
        print("  (no frames found -- check export format)")
        return

    # Majority-vote the full frame tuple (most reliable single signal)
    tuples = Counter(tuple(fr) for fr in frames)
    top_frame, top_count = tuples.most_common(1)[0]
    print(f"  Most common full frame (x{top_count}): {' '.join(top_frame)}")

    # Majority-vote byte 2 (mode) and byte 3 (COOL setpoint) independently,
    # since frame family shifts can make the "most common full frame" less
    # reliable than voting each meaningful byte position on its own.
    byte2, byte2_count = majority_vote_byte(frames, 1)
    byte3, byte3_count = majority_vote_byte(frames, 2)

    mode = decode_mode(byte2) if byte2 else None
    setpoint_str, ambiguous = cool_setpoint_from_byte3(byte3) if byte3 else (None, False)

    print(f"  Mode field (byte 2, majority x{byte2_count}): {byte2} -> {mode}")
    if byte3:
        print(f"  Stored COOL setpoint (byte 3, majority x{byte3_count}): "
              f"{byte3} -> {setpoint_str}")

    fam_counts = Counter(has_fa_family(fr) for fr in frames)
    print(f"  Frame family split: has-FA={fam_counts.get(True, 0)}, "
          f"no-FA={fam_counts.get(False, 0)}")
    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        analyze_file(path)


if __name__ == '__main__':
    main()
