#!/usr/bin/env python3
"""Generate rvtc_system.kicad_sch -- RVTC whole-system block diagram (KiCad 8).

Block-diagram style, like docs/archive/rvtc_imu_hookup.kicad_sch: graphic
rectangles, polylines and text only -- no symbols, no nets, no ERC meaning.
Facts are taken from docs/RVTC_System_Reference_2_15.md (Sections 3-7).
Produced the base layout only -- the .kicad_sch is hand-edited after that,
so re-running this OVERWRITES those edits. Write to a different file if needed.
"""
import re
import uuid
from pathlib import Path

OUT = Path(__file__).with_name("rvtc_system.kicad_sch")
REV, DATE = "A", "2026-10-12"

# colours (r g b) -- stroke, fill
FIELD = ((0, 70, 160), (225, 236, 252))
GATEWAY = ((0, 120, 60), (226, 245, 232))
NET = ((110, 40, 140), (240, 228, 248))
HOST = ((60, 60, 60), (250, 250, 250))
DOCKER = ((0, 110, 140), (226, 244, 248))
PENDING = ((150, 150, 150), (245, 245, 245))
REMOTE = ((170, 90, 0), (253, 240, 222))

items = []
NL = chr(10)


def u():
    return str(uuid.uuid4())


def rect(x1, y1, x2, y2, style, width=0.3, dash="solid"):
    (sr, sg, sb), (fr, fg, fb) = style
    items.append(
        f'  (rectangle (start {x1} {y1}) (end {x2} {y2})\n'
        f'    (stroke (width {width}) (type {dash}) (color {sr} {sg} {sb} 1))\n'
        f'    (fill (type color) (color {fr} {fg} {fb} 1))\n'
        f'    (uuid "{u()}")\n  )')


def line(pts, width=0.3, color=(40, 40, 40), dash="solid", arrow=True):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    r, g, b = color
    items.append(
        f'  (polyline (pts {xy})\n'
        f'    (stroke (width {width}) (type {dash}) (color {r} {g} {b} 1))\n'
        f'    (fill (type none))\n    (uuid "{u()}")\n  )')
    if arrow:  # filled arrowhead on the last segment
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        dx, dy = x1 - x0, y1 - y0
        n = (dx * dx + dy * dy) ** 0.5
        dx, dy = dx / n, dy / n
        L, W = 2.0, 0.9
        bx, by = x1 - dx * L, y1 - dy * L
        tri = [(x1, y1), (bx - dy * W, by + dx * W), (bx + dy * W, by - dx * W), (x1, y1)]
        xy = " ".join(f"(xy {x:.2f} {y:.2f})" for x, y in tri)
        items.append(
            f'  (polyline (pts {xy})\n'
            f'    (stroke (width 0.1) (type solid) (color {r} {g} {b} 1))\n'
            f'    (fill (type outline))\n    (uuid "{u()}")\n  )')


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


def block(x1, y1, x2, y2, title, sub, style, dash="solid"):
    rect(x1, y1, x2, y2, style, dash=dash)
    cx = (x1 + x2) / 2
    text(title, cx, y1 + 4, 1.5, bold=True, color=style[0])
    if sub:
        text(sub, cx, y1 + 4 + 2.4 + 1.1 * sub.count("\n"), 1.15)


# ---------------------------------------------------------------- data
# (device, device note, link label, gateway title, gateway address, pending?)
WAVESHARE = [
    ("EPEVER MPPT60", "solar charger + MT50 (1M2S tap)", "485-1", ".5:4001", False),
    ("SAMLUX EVO-2212", "inverter / charger", "485-2", ".6:4001", False),
    ("KWS-303L x2", "grid + generator meters", "485-3", ".7:4001", False),
    ("WitMotion WTGAHRS3", "GPS-IMU (HW-27)", "485-4", ".8:4001", False),
    ("Water sensors", "pressure / filter dP / turbidity - Phase 5", "485-5", ".9:4001", True),
    ("WN90LP", "weather station", "485-6", ".10:4001", False),
    ("JSY-MK-229", "300 A battery shunt (HW-24)", "485-7", ".11:4001", False),
    ("Waveshare 8-ch relay", "load shed: water heater, microwave", "485-8", ".12:4001", False),
]
HF = [  # (device, note, port, address, link type, pending?)
    ("APRS radio / tracker", "NMEA $GPRMC/$GPGGA in", "serial-1", ".13:4001", "RS-232", False),
    ("HVAC ESP32-S3 relay brd", "+ Touch-LCD-5 via UART - not wired", "serial-2", ".14:4001", "RS-485", True),
    ("Ebyte EID041-G01S", "enclosure temp/RH (HW-32)", "serial-4", ".16:4001", "RS-485", False),
]
ADAPTORS = [  # (script, what it does) -- two text columns, KiCad font is proportional
    ("epever_mqtt.py", "-> solar/#"),
    ("samlux_mqtt.py", "-> inverter/#"),
    ("kws_mqtt.py", "-> grid/#, generator/#"),
    ("imu_mqtt.py", "-> imu/#  (2 Hz)"),
    ("WN90_mqtt.py", "-> weather/#  (raw)"),
    ("battery_current_mqtt.py", "-> battery_current/#"),
    ("eid041_mqtt.py", "-> enclosure/#"),
    ("gps_nmea_bridge.py", "imu/gps -> NMEA -> serial-1"),
    ("imu_web.py", ":8090 leveling page (imu.lan)"),
    ("relay.py", "<- HA shell_command -> 485-8"),
    ("meshcore_name_resolver.py", "ADVERTs -> meshcore/names/+"),
]
ADAPTOR_NOTES = [
    "Modbus RTU frame + CRC16 over raw TCP,",
    "one fresh socket per poll",
    "(gps_nmea_bridge: one persistent socket)",
]

# ---------------------------------------------------------------- layout
text("RV Total Control (RVTC) - System Block Diagram", 12, 14, 2.5, bold=True, justify="left")
text("Sensor -> Adaptor -> Mosquitto -> Telegraf -> InfluxDB -> Subscribers.  "
     "No direct DB writers.", 12, 19, 1.4, justify="left")

DX1, DX2 = 12, 82        # field devices
GX1, GX2 = 100, 140      # gateways
RX1, RX2 = 156, 170      # MikroTik / LAN
H_X1, H_X2 = 182, 330    # host
row_y = [25 + 20 * i for i in range(8)] + [190, 210, 230]

text("FIELD DEVICES", (DX1 + DX2) / 2, 23, 1.3, bold=True, color=FIELD[0])
text("RS-485 / SERIAL GATEWAYS", (GX1 + GX2) / 2, 23, 1.3, bold=True, color=GATEWAY[0])

# Waveshare: one 8-port unit, one IP per port
rect(GX1, 25, GX2, 180, GATEWAY)
text("Waveshare 8-port", (GX1 + GX2) / 2, 27.8, 1.5, bold=True, color=GATEWAY[0])
text("RS-485 to Ethernet, Protocol: None", (GX1 + GX2) / 2, 30.6, 1.0)
for i, (dev, note, bus, addr, pend) in enumerate(WAVESHARE):
    y = row_y[i]
    cy = y + 7.5
    block(DX1, y, DX2, y + 15, dev, note, PENDING if pend else FIELD,
          dash="dash" if pend else "solid")
    line([(DX2, cy), (GX1, cy)], arrow=False)
    text("RS-485", (DX2 + GX1) / 2, cy - 1.3, 1.0)
    text(f"{bus}  192.168.88{addr}", GX1 + 2, cy + 1.5, 1.15, justify="left")
    line([(GX2, cy), (RX1, cy)], arrow=False, color=NET[0])
    text("ether6", (GX2 + RX1) / 2, cy - 1.3, 1.0, color=NET[0])

# HF5142B: one 4-port box
hy1, hy2 = 182, 245
rect(GX1, hy1, GX2, hy2, GATEWAY)
text("HF5142B", (GX1 + GX2) / 2, hy1 + 3.5, 1.5, bold=True, color=GATEWAY[0])
text("4-port, NOT isolated", (GX1 + GX2) / 2, hy1 + 6.5, 1.1)
for j, (dev, note, port, addr, link, pend) in enumerate(HF):
    y = row_y[8 + j]
    cy = y + 7.5
    block(DX1, y, DX2, y + 15, dev, note, PENDING if pend else FIELD,
          dash="dash" if pend else "solid")
    line([(DX2, cy), (GX1, cy)], arrow=False)
    text(link, (DX2 + GX1) / 2, cy - 1.3, 1.0)
    text(f"{port}  {addr}", GX1 + 2, cy + 1, 1.15, justify="left")
text("serial-3 .15 - free", GX1 + 2, hy2 - 2.5, 1.0, justify="left", color=PENDING[0])
line([(GX2, 213.5), (RX1, 213.5)], arrow=False, color=NET[0])
text("ether4", (GX2 + RX1) / 2, 212.2, 1.0, color=NET[0])

# MikroTik / RV LAN
rect(RX1, 25, RX2, 245, NET)
text("MikroTik CRS109  -  192.168.88.1  -  RV LAN 192.168.88.0/24 (bridge)",
     (RX1 + RX2) / 2, 135, 1.6, bold=True, angle=90, color=NET[0])

# Host
rect(H_X1, 25, H_X2, 245, HOST, width=0.45)
text("Beelink J45  -  ve7cbh-control  -  192.168.88.3", (H_X1 + H_X2) / 2, 29.5, 1.6, bold=True)
text("LMDE 7 (Debian trixie)  -  root sdb3 /  -  data sda /data", (H_X1 + H_X2) / 2, 33, 1.1)

# adaptors
AX1, AX2, AY1, AY2 = 186, 244, 38, 126
rect(AX1, AY1, AX2, AY2, FIELD)
text("Bridge adaptors (systemd)", (AX1 + AX2) / 2, AY1 + 4, 1.5, bold=True, color=FIELD[0])
text("config/scripts/  -  topics under rvtc/sensors/", (AX1 + AX2) / 2, AY1 + 7, 1.0)
for k, (script, what) in enumerate(ADAPTORS):
    text(script, AX1 + 2, AY1 + 13 + 5 * k, 1.05, justify="left")
    text(what, AX1 + 27, AY1 + 13 + 5 * k, 1.05, justify="left")
for k, note in enumerate(ADAPTOR_NOTES):
    text(note, AX1 + 2, AY1 + 75 + 3.5 * k, 1.0, justify="left", color=(90, 90, 90))
line([(RX2, 100), (AX1, 100)], color=NET[0])
text("ether4", (RX2 + AX1) / 2, 98.7, 1.0, color=NET[0])

# docker
DKX1, DKX2, DKY1, DKY2 = 250, 326, 38, 241
rect(DKX1, DKY1, DKX2, DKY2, HOST, dash="dash")
text("Docker stack  (docker-compose.yml)", (DKX1 + DKX2) / 2, DKY1 + 4, 1.5, bold=True)
L1, L2, R1, R2 = 253, 286, 291, 323


def svc(col, y, title, sub, h=15):
    x1, x2 = (L1, L2) if col == 0 else (R1, R2)
    block(x1, y, x2, y + h, title, sub, DOCKER)


svc(0, 46, "mosquitto", ":1883 MQTT\n:9001 websocket")
svc(0, 72, "telegraf", "mqtt_consumer\ntelegraf_*.conf (per file)")
svc(0, 98, "influxdb", ":8086\norg/bucket rvtc")
svc(0, 124, "grafana", ":3000  history")
svc(1, 46, "weewx", "raw in, corrected out\nTrueWind, Belchertown, CWOP")
svc(1, 72, "homeassistant", ":8123  live display\nautomation, load shed")
svc(1, 124, "nginx", ":80 *.lan reverse proxy\n:8801 ext -> weewx.lan")
svc(1, 150, "pihole", ":53 DNS (*.lan -> .3)\n:8880 admin")
svc(1, 176, "portainer", ":9000")

line([(AX2, 51), (L1, 51)])                                   # adaptors -> broker
text("publish", (AX2 + L1) / 2, 49.7, 1.0)
line([(269.5, 61), (269.5, 72)])                               # broker -> telegraf
line([(269.5, 87), (269.5, 98)])                               # telegraf -> influx
line([(269.5, 113), (269.5, 124)])                             # influx -> grafana
line([(L2, 50.5), (R1, 50.5)])                                 # broker -> weewx (raw)
line([(R1, 56.5), (L2, 56.5)])                                 # weewx -> broker (corrected)
line([(L2, 59.5), (288.5, 59.5), (288.5, 79.5), (R1, 79.5)])   # broker -> HA
line([(R1 + 4, 87), (R1 + 4, AY1 + 58), (AX2, AY1 + 58)],
     dash="dash", color=FIELD[0])                              # HA -> relay.py
text("shell_command", 278, AY1 + 56.7, 1.0, color=FIELD[0])

text("Not persisted:", L1, 146, 1.1, bold=True, justify="left")
text("imu/# is live-only (by design)", L1, 149.5, 1.05, justify="left")
text("weather: telegraf takes the", L1, 155, 1.05, justify="left")
text("corrected topic only", L1, 158.5, 1.05, justify="left")
text("battery: json topic only", L1, 164, 1.05, justify="left")
text("meshcore/DUQ/+/*: published by", L1, 169.5, 1.05, justify="left")
text("the nodes themselves (no bridge)", L1, 173, 1.05, justify="left")

# right column: clients, home via VPN, WAN
EX1, EX2 = 342, 408
block(EX1, 25, EX2, 52, "LAN clients / browsers",
      "*.lan -> Pi-hole DNS -> nginx :80\nrvtc.lan: InfluxDB HTTP\n+ live MQTT over ws :9001",
      REMOTE)
line([(EX1, 40), (334, 40), (334, 131.5), (R2, 131.5)], color=REMOTE[0])
block(EX1, 57, EX2, 98, "Other RV LAN hosts",
      NL.join([".2  VE7CBH-RV workstation (ether4)", ".4  DS223 NAS (ether5)",
               ".20 printer   .21 Fanvil X4G phone", ".22 TL-SG108PE PoE switch (ether4)",
               ".23 Motorola phone   .24 WP-820 (wlan1)", ".254 Sonoff S31 plug (dynamic, wlan1)"]),
      HOST)
block(EX1, 105, EX2, 140, "Home site (via VPN)",
      "TP-Link ER605  192.168.0.1\nLAN 192.168.0.0/24\nHome HA 192.168.0.125\nHome Pi 192.168.0.3",
      REMOTE)
block(EX1, 196, EX2, 236, "WAN (MikroTik)",
      "rogers-wan: club / site wired\nstarlink-wan: Starlink (CGNAT)\nmanual HOME / AWAY NAT mode\n"
      "dst-nat :8801 -> .3 (weewx)\nrv.malacat.ca (MikroTik DDNS)",
      REMOTE)
line([(375, 196), (375, 140)], color=REMOTE[0])
text("IPsec IKEv2 AES-256 / DH14", 377, 165, 1.1, justify="left")
text("-> home.malacat.ca", 377, 168.5, 1.1, justify="left")
line([(168, 245), (168, 251), (375, 251), (375, 236)], color=NET[0])
text("uplink", 250, 249.7, 1.0)

# MeshCore: TCP/IP straight onto the LAN, no serial gateway (IPs from MikroTik DHCP leases)
block(DX1, 249, DX2, 265, "MeshCore Observer VE7CBH-RVTC  .25",
      "LilyGo T-Beam, WiFi (wlan1)" + NL + "MQTT DUQ -> :1883 + public observer map", FIELD)
line([(DX2, 257), (159, 257), (159, 245)], color=NET[0])
text("WiFi - TCP/IP", 120, 255.7, 1.0)
block(DX1, 269, DX2, 285, "MeshCore companion  .26",
      "RAK4631 + RAK13800 (WIZnet), ether4" + NL + "TCP <-> Meshy app", FIELD)
line([(DX2, 277), (165, 277), (165, 245)], color=NET[0])
text("Ethernet - TCP/IP", 120, 275.7, 1.0)

# legend
LGX, LGY = 182, 255
rect(LGX, LGY, 300, 287, HOST, width=0.2)
text("Legend", LGX + 2, LGY + 3.5, 1.4, bold=True, justify="left")
for k, (st, lbl, dash) in enumerate([
        (FIELD, "field device / adaptor", "solid"), (GATEWAY, "serial-to-Ethernet gateway", "solid"),
        (NET, "network / router", "solid"), (DOCKER, "docker container", "solid"),
        (REMOTE, "external / remote site", "solid"), (PENDING, "planned / not yet wired", "dash")]):
    x = LGX + 3 + (k % 2) * 58
    y = LGY + 7 + (k // 2) * 5
    rect(x, y, x + 6, y + 3, st, width=0.25, dash=dash)
    text(lbl, x + 8, y + 1.5, 1.1, justify="left")
text("Arrow = data direction.  Gateway IPs are 192.168.88.x, port 4001.",
     LGX + 3, LGY + 25.5, 1.0, justify="left")
text("Source: RVTC_System_Reference_2_15.md", LGX + 3, LGY + 29, 1.0, justify="left")

# page 2: power sheet, as a hierarchical sheet symbol (double-click to open)
ROOT = u()
items.append(f'''  (sheet (at 343 172) (size 26 14) (fields_autoplaced yes)
    (stroke (width 0.3) (type solid) (color 180 0 0 1))
    (fill (color 253 230 230 1))
    (uuid "{u()}")
    (property "Sheetname" "Electrical" (at 343 171.3 0)
      (effects (font (size 1.4 1.4) bold) (justify left bottom))
    )
    (property "Sheetfile" "rvtc_power.kicad_sch" (at 343 186.6 0)
      (effects (font (size 1.1 1.1)) (justify left top))
    )
    (instances
      (project "rvtc_system"
        (path "/{ROOT}" (page "2"))
      )
    )
  )''')
text("power side: page 2", 356, 179, 1.1)

# ---------------------------------------------------------------- write
sch = f'''(kicad_sch (version 20231120) (generator "rvtc_system_gen") (generator_version "8.0")
  (uuid "{ROOT}")
  (paper "USLedger")
  (title_block
    (title "RVTC System Block Diagram")
    (date "{DATE}")
    (rev "{REV}")
    (company "RVTC - VE7CBH")
    (comment 1 "Block-diagram style - not a manufacturable schematic")
    (comment 2 "Base layout: generate_rvtc_system_sch.py; hand-edited after - re-running overwrites")
  )
  (lib_symbols)
{chr(10).join(items)}
  (sheet_instances
    (path "/" (page "1"))
  )
)
'''
# Layout above is drawn on A3 coordinates; 11x17 (USLedger) is 17.6 mm shorter,
# so compress y toward the top border. Font sizes are untouched.
S = 0.935
sch = re.sub(r"\((at|start|end|xy) ([-\d.]+) ([-\d.]+)",
             lambda m: f"({m.group(1)} {m.group(2)} {10 + (float(m.group(3)) - 10) * S:.3f}", sch)
sch = re.sub(r"(\(sheet \(at [-\d.]+ [-\d.]+\) \(size [-\d.]+) ([-\d.]+)\)",
             lambda m: f"{m.group(1)} {float(m.group(2)) * S:.3f})", sch)
OUT.write_text(sch, encoding="utf-8")
print(f"wrote {OUT} ({len(items)} items)")
