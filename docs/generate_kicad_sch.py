#!/usr/bin/env python3
"""
Generates rvtc_imu_hookup.kicad_sch — a block-diagram-style KiCad schematic
for the IMU leveling node (HW-25).

IMPORTANT LIMITS, read before trusting this file:
  - Built programmatically with kiutils rather than hand-written, which
    avoids the most common hand-authoring mistakes (malformed S-expressions,
    bad UUIDs) — but this was never opened in actual KiCad to confirm it
    looks/behaves correctly, since KiCad isn't installed in the environment
    that generated it. Only verified to parse cleanly when read back with
    kiutils itself (see bottom of this script).
  - Blocks are generic labeled rectangles, not real component symbols from
    a KiCad library — there's no footprint here, so this isn't ready for a
    PCB layout on its own. It documents the wiring, nothing more.
  - Each connector line represents a signal *group* (e.g. "SDA, SCL" on one
    line), not individually routed conductors the way a fully accurate
    schematic would draw them.
Open this in KiCad's schematic editor first and sanity-check it before
relying on it for anything.
"""

import uuid
from kiutils.schematic import Schematic
from kiutils.items.common import Position, Effects, Font, PageSettings
from kiutils.items.schitems import Rectangle, Stroke, Fill, Text, Connection, LocalLabel
from kiutils.schematic import TitleBlock


def u():
    return str(uuid.uuid4())


def make_block(x1, y1, x2, y2, title, subtitle=None):
    """Returns (rectangle, [text items]) for one labeled block."""
    rect = Rectangle(
        start=Position(X=x1, Y=y1),
        end=Position(X=x2, Y=y2),
        stroke=Stroke(width=0.254, type="default"),
        fill=Fill(type="none"),
        uuid=u(),
    )
    cx = (x1 + x2) / 2
    texts = [
        Text(
            text=title,
            position=Position(X=cx, Y=y1 + 4, angle=0),
            effects=Effects(font=Font(height=1.6, width=1.6, bold=True)),
            uuid=u(),
        )
    ]
    if subtitle:
        texts.append(Text(
            text=subtitle,
            position=Position(X=cx, Y=y1 + 9, angle=0),
            effects=Effects(font=Font(height=1.2, width=1.2)),
            uuid=u(),
        ))
    return rect, texts


def make_wire(x1, y1, x2, y2):
    return Connection(
        type="wire",
        points=[Position(X=x1, Y=y1), Position(X=x2, Y=y2)],
        stroke=Stroke(width=0.152, type="solid"),
        uuid=u(),
    )


def make_label(text, x, y, angle=0):
    return LocalLabel(
        text=text,
        position=Position(X=x, Y=y, angle=angle),
        effects=Effects(font=Font(height=1.2, width=1.2)),
        uuid=u(),
    )


sch = Schematic()
sch.version = "20231120"
sch.generator = "kiutils-rvtc-imu"
sch.uuid = u()
sch.paper = PageSettings(paperSize="A4", portrait=False)
sch.titleBlock = TitleBlock(
    title="RVTC IMU Leveling Node - Hookup (HW-25)",
    date="2026-07-09",
    revision="A",
    company="RVTC",
    comments={1: "Block-diagram style - not a manufacturable schematic. See header comment in generator script."},
)

blocks = [
    # (x1, y1, x2, y2, title, subtitle)
    (20, 20, 70, 35, "DC-DC converter", "12V in to 5V out"),
    (100, 45, 170, 60, "ESP32-WROOM-32", "DevKit board"),
    (20, 80, 70, 95, "Adafruit 10-DOF", "SDA=21 SCL=22"),
    (90, 80, 140, 95, "SH1106 OLED 1.3in", "Shared I2C bus"),
    (160, 80, 210, 95, "RS-485 driver", "TX=17 RX=16 DE=4"),
    (160, 120, 210, 135, "Waveshare gateway", "Already installed - .8:4001"),
]

for (x1, y1, x2, y2, title, subtitle) in blocks:
    rect, texts = make_block(x1, y1, x2, y2, title, subtitle)
    sch.shapes.append(rect)
    sch.texts.extend(texts)

# Wires between block edges, matching the SVG hookup diagram sent earlier
wires = [
    (70, 27, 100, 50),     # DC-DC -> ESP32 (5V/GND)
    (110, 60, 45, 80),     # ESP32 -> IMU (I2C)
    (135, 60, 115, 80),    # ESP32 -> OLED (I2C, shared bus)
    (160, 60, 185, 80),    # ESP32 -> RS-485 driver (UART)
    (185, 95, 185, 120),   # RS-485 driver -> Waveshare gateway (A/B pair)
]
for (x1, y1, x2, y2) in wires:
    sch.graphicalItems.append(make_wire(x1, y1, x2, y2))

# Net labels on the wires that carry a shared/named signal group
sch.labels.append(make_label("I2C_SDA_SCL", 55, 88))
sch.labels.append(make_label("UART_TX_RX_DE", 148, 88))
sch.labels.append(make_label("RS485_A_B", 187, 107, angle=90))

out_path = "/home/claude/rvtc-imu/rvtc_imu_hookup.kicad_sch"
sch.to_file(out_path)
print(f"Wrote {out_path}")

# Self-check: re-parse the file we just wrote. This confirms the S-expression
# syntax is well-formed and kiutils itself can round-trip it — it does NOT
# confirm KiCad's own editor will accept it without complaint.
reloaded = Schematic.from_file(out_path)
print(f"Round-trip check OK: {len(reloaded.shapes)} shapes, "
      f"{len(reloaded.texts)} texts, {len(reloaded.graphicalItems)} wires, "
      f"{len(reloaded.labels)} labels")
