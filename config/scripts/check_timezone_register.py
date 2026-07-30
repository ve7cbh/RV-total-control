#!/usr/bin/env python3
"""
check_timezone_register.py — one-off diagnostic: read the WitMotion's
TIMEZONE register (0x6B) to check whether it's been set away from its
factory default (0x14 = UTC+8), which would explain why the on-chip
time block (YYMM~MS, 0x30-0x33) appears to track LOCAL time rather than
true UTC as its field name in the register map implies.

Read-only. Same fresh-connection-per-poll framing every other RVTC
Modbus bridge script uses.

Usage:
    ./check_timezone_register.py
"""

import socket

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
TIMEZONE_REG_ADDR = 0x6B
SOCKET_TIMEOUT = 2.0

# Register doc: value v (0x00-0x18) maps to UTC+(v-12) hours.
# 0x0C = UTC, 0x14 (factory default) = UTC+8, 0x05 = UTC-7.


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


def main() -> int:
    try:
        raw = read_register(GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, TIMEZONE_REG_ADDR)
    except (OSError, ValueError) as e:
        print(f"Couldn't read the TIMEZONE register: {e}")
        return 1

    offset_hours = raw - 12
    print(f"TIMEZONE register (0x6B) raw value: 0x{raw:04X} ({raw})")
    print(f"Decoded offset: UTC{offset_hours:+d}")
    if raw == 0x14:
        print("This is the factory default (UTC+8) -- not yet changed.")
    elif offset_hours == -7:
        print("This matches Nanaimo's UTC-7 -- consistent with the on-chip")
        print("time block reporting local time rather than true UTC.")
    else:
        print("Doesn't match the factory default or UTC-7 -- worth a second look.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
