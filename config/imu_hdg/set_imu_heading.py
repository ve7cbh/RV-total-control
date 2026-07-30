#!/usr/bin/env python3
"""
set_imu_heading.py — establishes the WitMotion's heading offset (HW-27).

Why this exists: the WitMotion has no "set heading to X" register. Its only
heading-related calibration command (CALSW = 0x04) zeroes the CURRENT
physical orientation to 0 -- not useful for a trailer you can't re-point to
face a specific direction. So instead of a device-side calibration, this
script establishes a software offset: it reads the unit's raw (uncorrected)
Yaw right now, compares it to the true heading you tell it the vehicle is
actually facing, and stores the difference. imu_mqtt.py applies that offset
to every subsequent Yaw reading before publishing.

Usage:
    ./set_imu_heading.py 137
        (137 = the vehicle's current true heading in degrees, 0-360,
        read off a phone compass, a road's known bearing, a chart, etc.)

This clears the "needs_init" flag that gets set at every host boot (see
imu_needs_init_on_boot.service) -- a reasonable but imperfect proxy for the
IMU itself having lost power, since they're expected to share a 12V supply.
Not foolproof: if the IMU is ever on a separately switched circuit from the
J45, this boot-flag heuristic won't catch an IMU-only power cycle. Flagging
that honestly rather than pretending the detection is airtight.

Requires being run on a host that can reach the Waveshare gateway directly
(same network as imu_mqtt.py assumes).
"""

import json
import socket
import sys
from datetime import datetime, timezone

# ── Config -- must match imu_mqtt.py exactly ─────────────────────────────
GATEWAY_HOST = "192.168.88.8"     # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
YAW_REG_ADDR = 0x3F     # single register, not the 3-register Roll/Pitch/Yaw
                        # block -- this script only needs Yaw
SOCKET_TIMEOUT = 2.0

STATE_FILE = "/home/ve7cbh/RV-total-control/config/imu_heading_state.json"


# ── Modbus read (single register) -- same framing as imu_mqtt.py ────────
# Kept as a self-contained copy rather than a shared import, matching the
# project's existing per-script style (epever_mqtt.py, samlux_mqtt.py, etc.
# are each independent files too). If this ever needs changing, check
# imu_mqtt.py's copy too -- they should stay in sync.

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def read_register(host: str, port: int, slave: int, reg_addr: int) -> int:
    body = bytes([slave, 0x03, (reg_addr >> 8) & 0xFF, reg_addr & 0xFF, 0x00, 0x01])
    crc = crc16_modbus(body)
    request = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    expected_len = 3 + 2 + 2

    with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as sock:
        sock.sendall(request)
        response = b""
        while len(response) < expected_len:
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk

    if len(response) != expected_len:
        raise ValueError(f"short response: got {len(response)} bytes, expected {expected_len}")
    if response[0] != slave or response[1] != 0x03:
        raise ValueError(f"unexpected header: {response[:3].hex()}")

    byte_count = response[2]
    data = response[3:3 + byte_count]
    recv_crc = response[3 + byte_count:3 + byte_count + 2]
    calc_crc = crc16_modbus(response[:3 + byte_count])
    if recv_crc[0] != (calc_crc & 0xFF) or recv_crc[1] != ((calc_crc >> 8) & 0xFF):
        raise ValueError("CRC mismatch")

    return (data[0] << 8) | data[1]


def to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: set_imu_heading.py <current_true_heading_degrees>")
        return 1

    try:
        true_heading = float(sys.argv[1]) % 360
    except ValueError:
        print(f"'{sys.argv[1]}' isn't a number")
        return 1

    try:
        raw_reg = read_register(GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, YAW_REG_ADDR)
    except (OSError, ValueError) as e:
        print(f"Couldn't read the IMU's Yaw register: {e}")
        print("Is the WitMotion powered and wired to the 485-4 gateway?")
        return 1

    raw_yaw_deg = to_s16(raw_reg) / 32768 * 180
    raw_yaw_deg = raw_yaw_deg % 360

    offset_deg = (true_heading - raw_yaw_deg) % 360

    state = {
        "needs_init": False,
        "offset_deg": round(offset_deg, 2),
        "raw_yaw_at_set": round(raw_yaw_deg, 2),
        "true_heading_at_set": round(true_heading, 2),
        "set_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Raw Yaw right now:     {raw_yaw_deg:.2f}°")
    print(f"Set as true heading:   {true_heading:.2f}°")
    print(f"Offset stored:         {offset_deg:.2f}°")
    print(f"needs_init cleared. State written to {STATE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
