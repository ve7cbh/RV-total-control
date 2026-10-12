#!/usr/bin/env python3
"""Generate rvtc_power.kicad_sch -- RVTC electrical (power) block diagram, KiCad 8.

Page 2 of the rvtc_system project (the data/network diagram is page 1).
Block-diagram style: graphic rectangles, polylines and text only.
Topology follows the Cougar 27-8 interconnection drawing (2020), updated with
what System Reference 2.15 documents for this trailer. Anything not documented
is marked "?" for hand completion.

Produced the base layout only -- the .kicad_sch is hand-edited after that,
so re-running this OVERWRITES those edits. Write to a different file if needed.
"""
import uuid
from pathlib import Path

OUT = Path(__file__).with_name("rvtc_power.kicad_sch")
REV, DATE = "A", "2026-10-12"
NL = chr(10)

# box styles: (stroke rgb, fill rgb)
PV = ((200, 110, 0), (255, 243, 220))
DC = ((180, 0, 0), (253, 230, 230))
BAT = ((60, 60, 60), (235, 235, 235))
AC = ((120, 70, 20), (245, 236, 224))
RVTC = ((0, 70, 160), (225, 236, 252))
PLAIN = ((60, 60, 60), (250, 250, 250))
PENDING = ((150, 150, 150), (245, 245, 245))

# line colours
C_PV, C_POS, C_NEG, C_AC, C_DATA = (230, 130, 0), (200, 0, 0), (0, 0, 0), (130, 80, 20), (0, 70, 160)

items = []


def u():
    return str(uuid.uuid4())


def rect(x1, y1, x2, y2, style, width=0.3, dash="solid"):
    (sr, sg, sb), (fr, fg, fb) = style
    items.append(
        f'  (rectangle (start {x1} {y1}) (end {x2} {y2})\n'
        f'    (stroke (width {width}) (type {dash}) (color {sr} {sg} {sb} 1))\n'
        f'    (fill (type color) (color {fr} {fg} {fb} 1))\n'
        f'    (uuid "{u()}")\n  )')


def line(pts, color, width=0.5, dash="solid"):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    r, g, b = color
    items.append(
        f'  (polyline (pts {xy})\n'
        f'    (stroke (width {width}) (type {dash}) (color {r} {g} {b} 1))\n'
        f'    (fill (type none))\n    (uuid "{u()}")\n  )')


def text(s, x, y, size=1.27, bold=False, justify=None, angle=0, color=None):
    s = s.replace('"', '\\"').replace("\n", "\\n")
    font = f"(size {size} {size})"
    if bold:
        font += " bold"
    if color:
        font += " (color {} {} {} 1)".format(*color)
    just = f" (justify {justify})" if justify else ""
    items.append(
        f'  (text "{s}" (exclude_from_sim no) (at {x} {y} {angle})\n'
        f'    (effects (font {font}){just})\n    (uuid "{u()}")\n  )')


def block(x1, y1, x2, y2, title, sub, style, dash="solid", lines=()):
    """Box with a centred title, optional centred subtitle, optional left-justified list."""
    rect(x1, y1, x2, y2, style, dash=dash)
    cx = (x1 + x2) / 2
    text(title, cx, y1 + 4, 1.5, bold=True, color=style[0])
    y = y1 + 4
    if sub:
        n = sub.count("\n")
        text(sub, cx, y1 + 6.4 + 1.1 * n, 1.15)
        y = y1 + 7.5 + 2.2 * n
    for k, s in enumerate(lines):
        text(s, x1 + 2.5, y + 4.5 + 3.4 * k, 1.1, justify="left")


def label(s, x, y, color, size=1.0):
    text(s, x, y, size, color=color)


# ---------------------------------------------------------------- header
text("RV Total Control (RVTC) - Electrical Block Diagram", 12, 14, 2.5, bold=True, justify="left")
text("12 V LiFePO4 house system, 30 A shore / generator, inverter/charger.  "
     "\"?\" = not yet documented, fill in by hand.", 12, 19, 1.4, justify="left")

# ---------------------------------------------------------------- PV
block(15, 26, 75, 44, "Roof PV array", "? panels x ? W" + NL + "Voc ? V  /  Isc ? A", PV)
line([(45, 44), (45, 52)], C_PV)
block(15, 52, 75, 68, "PV combiner + disconnect ?", "breaker / fuse ? A", PV)
line([(75, 60), (95, 60)], C_PV)
label("PV", 85, 58.7, C_PV)

# ---------------------------------------------------------------- charge controller
block(95, 26, 150, 64, "EPEVER MPPT60", "60 A MPPT, 12 V", DC, lines=[
    "LiFePO4 'User' profile",
    "absorb 14.20 / float 13.70 V",
    "(2026-07-29, still being tuned)",
    "capacity setting 600 Ah",
    "data: 485-1 (epever_mqtt.py)"])
block(95, 70, 150, 82, "MT50 remote", "on 485-1 via RS485-1M2S tap", RVTC)
line([(122.5, 70), (122.5, 64)], C_DATA, width=0.3, dash="dash")
line([(150, 40), (175, 40)], C_POS)
label("fuse ? A", 162.5, 38.7, C_POS)

# ---------------------------------------------------------------- DC bus
BX1, BX2, BY1, BY2 = 175, 195, 26, 200
rect(BX1, BY1, BX2, BY2, DC, width=0.45)
text("12 V DC distribution  -  +/- bus bars ?", (BX1 + BX2) / 2, (BY1 + BY2) / 2, 1.6,
     bold=True, angle=90, color=DC[0])

# DC load centre (OEM)
block(15, 92, 75, 150, "DC load centre (OEM ?)", "fused branch circuits ?", DC, lines=[
    "Lights ?",
    "LP furnace (call from HVAC brd) ?",
    "Fridge ?",
    "CO / LP detector ?",
    "Water pump ?",
    "Slide / jacks ?",
    "Tank monitor ?",
    "Battery heaters HW-22 (planned)"])
line([(75, 121), (BX1, 121)], C_POS)
label("12 V  fuse ? A", 125, 119.7, C_POS)

# ---------------------------------------------------------------- battery bank
rect(15, 200, 85, 252, BAT, width=0.45)
text("House battery bank  12 V", 50, 204, 1.5, bold=True)
text("LiFePO4, 2 batteries in parallel ?", 50, 207.5, 1.1)
for k, y in enumerate((211, 231)):
    block(19, y, 81, y + 17, f"LiFePO4 #{k + 1}  ? Ah", "internal BMS" + NL + "heater HW-22 / temp HW-31 planned", BAT)
line([(85, 214), (100, 214)], C_POS)
line([(85, 242), (100, 242)], C_NEG)
block(100, 206, 145, 222, "Main fuse ? A", "+ battery disconnect ?", DC)
block(100, 234, 145, 250, "300 A shunt (HW-24)", "JSY-MK-229, neg. leg" + NL + "data: 485-7", RVTC)
line([(145, 214), (180, 214), (180, BY2)], C_POS)
line([(145, 242), (190, 242), (190, BY2)], C_NEG)
label("+12 V", 162, 212.7, C_POS)
label("negative", 162, 240.7, C_NEG)
line([(165, 242), (165, 256)], C_NEG)
block(140, 256, 190, 272, "Single point of ground ?", "chassis bond ? / gauge ?", PLAIN)

text("BMS disconnect drops the whole 12 V side,", 92, 190, 1.05, justify="left", color=DC[0])
text("including the J45 (known, accepted).", 92, 193.5, 1.05, justify="left", color=DC[0])

# ---------------------------------------------------------------- RVTC 12 V loads
block(205, 26, 270, 112, "RVTC 12 V loads", "own fused feed ? A  -  all RVTC kit is 12 V", RVTC, lines=[
    "Beelink J45 control PC",
    "MikroTik CRS109 router",
    "TL-SG108PE PoE switch",
    "Waveshare RS-485 gateways x8",
    "Waveshare 8-ch relay board",
    "  HW-19 12->5 V DC-DC (planned)",
    "HF5142B serial gateway ?",
    "RS-485 sensors (WN90, IMU, EID041...) ?",
    "HVAC ESP32-S3 boards (12 V run exists)",
    "MeshCore nodes ?",
    "Starlink ?",
    "Supply: direct / DC-DC / PoE ?"])
line([(BX2, 60), (205, 60)], C_POS)
label("fuse ? A", 200, 58.7, C_POS)

# ---------------------------------------------------------------- inverter / charger
block(205, 138, 270, 176, "SAMLUX EVO-2212", "inverter / charger, 12 V", AC, lines=[
    "inverter ? W, charger ? A",
    "AC in: shore / gen",
    "AC out: load centre ?",
    "data: 485-2 (samlux_mqtt.py)"])
line([(BX2, 157), (205, 157)], C_POS, width=0.7)
label("fuse ? A / ? AWG", 200.5, 155.7, C_POS, size=0.9)

# ---------------------------------------------------------------- AC inlets
block(285, 26, 338, 46, "Shore inlet 30 A", "KWS-303L grid meter (485-3)" + NL + "connect/disconnect: planned", AC)
block(352, 26, 405, 46, "Generator inlet ? A", "KWS-303L gen meter (485-3)" + NL + "generator ? W", AC)
line([(311.5, 46), (311.5, 56)], C_AC)
line([(378.5, 46), (378.5, 56)], C_AC)
block(300, 56, 390, 72, "Shore / generator transfer ?", "auto transfer switch, or EVO AC-in priority ?", AC)
line([(300, 64), (280, 64), (280, 146), (270, 146)], C_AC)
label("120 VAC in", 289, 62.7, C_AC)

# ---------------------------------------------------------------- AC load centre
block(290, 96, 352, 202, "AC load centre (OEM ?)", "main ? A  -  fed from EVO AC out ?", AC, lines=[
    "Water heater (electric) ?",
    "Microwave ?",
    "Rooftop A/C ?",
    "Outlets ?",
    "GFCI ?",
    "Converter ? (EVO charges)",
    "Sub-panel / inverter-only ?"])
line([(270, 166), (290, 166)], C_AC)
label("120 VAC out", 280, 164.7, C_AC)

for (y1, y2, title, sub, style, dash) in [
    (96, 116, "Load-shed relays", "Waveshare 8-ch (485-8), NC wiring" + NL + "coil 0 water heater, coil 1 microwave", RVTC, "solid"),
    (121, 141, "Dometic 579 rooftop A/C", "ESP32-S3 relay board: compressor," + NL + "fan hi / lo, furnace call", AC, "solid"),
    (146, 166, "Winter heater plug 1", "1800 W ESPHome plug, ~15 A" + NL + "must fit the load-shed scheme", AC, "solid"),
    (171, 195, "RVTC 120 VAC loads", "2 x J45 monitors" + NL + "(1 via HDMI-over-Cat5e)" + NL + "J45 speakers", RVTC, "solid"),
]:
    block(360, y1, 408, y2, title, sub, style, dash=dash)
    line([(352, (y1 + y2) / 2), (360, (y1 + y2) / 2)], C_AC)

block(360, 205, 408, 225, "Winter heater plug 2", "external extension cord -" + NL + "NOT on 30 A service, NOT on KWS", PENDING, dash="dash")

# ---------------------------------------------------------------- legend
LGX, LGY = 200, 236
rect(LGX, LGY, 300, 287, PLAIN, width=0.2)
text("Legend", LGX + 2, LGY + 3.5, 1.4, bold=True, justify="left")
for k, (c, lbl, dash) in enumerate([
        (C_PV, "PV DC (array to controller)", "solid"),
        (C_POS, "+12 V DC", "solid"),
        (C_NEG, "negative / ground", "solid"),
        (C_AC, "120 VAC", "solid"),
        (C_DATA, "RS-485 data (see page 1)", "dash")]):
    y = LGY + 8 + 4.5 * k
    line([(LGX + 3, y), (LGX + 13, y)], c, width=0.5 if dash == "solid" else 0.3, dash=dash)
    text(lbl, LGX + 16, y, 1.1, justify="left")
text("Lines are block-level: one line = the circuit, not each conductor.", LGX + 3, LGY + 33, 1.0, justify="left")
text("Blue boxes = RVTC kit.  \"?\" = fill in by hand.", LGX + 3, LGY + 36.5, 1.0, justify="left")
text("Layout after Cougar 27-8 drawing (2020-01-31).", LGX + 3, LGY + 40, 1.0, justify="left")

# ---------------------------------------------------------------- write
sch = f'''(kicad_sch (version 20231120) (generator "rvtc_power_gen") (generator_version "8.0")
  (uuid "{u()}")
  (paper "A3")
  (title_block
    (title "RVTC Electrical Block Diagram")
    (date "{DATE}")
    (rev "{REV}")
    (company "RVTC - VE7CBH")
    (comment 1 "Block-diagram style - not a wiring or manufacturable schematic")
    (comment 2 "Base layout: generate_rvtc_power_sch.py; hand-edited after - re-running overwrites")
  )
  (lib_symbols)
{NL.join(items)}
)
'''
OUT.write_text(sch, encoding="utf-8")
print(f"wrote {OUT} ({len(items)} items)")
