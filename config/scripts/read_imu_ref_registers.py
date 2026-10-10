#!/usr/bin/env python3
"""
read_imu_ref_registers.py — one-off diagnostic: reads back the WitMotion's
XREFROLL (0x79) and YREFPITCH (0x7A) registers directly, to check what's
actually stored there after zero_imu_pitch_roll.py's write.

Why this is needed: that write completed cleanly (unlock, both writes, and
save all echoed correctly, with imu_mqtt.service stopped to rule out any
collision) -- but the resulting pitch/roll didn't move toward zero at all,
just changed to different, seemingly unrelated values. That means either
(a) the values didn't actually persist the way expected, or (b) these
registers don't do what the manual's own subtraction example implied, or
(c) something else entirely. Reading back what's really stored is the
next diagnostic step before writing anything else -- don't guess twice.

Same safe pattern as zero_imu_pitch_roll.py: stops imu_mqtt.service before
touching the device directly, restarts it afterward via try/finally
regardless of outcome.

Usage:
    python3 read_imu_ref_registers.py
"""

import socket
import subprocess
import sys
import time

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

XREFROLL_REG = 0x79
YREFPITCH_REG = 0x7A
ANGLE_ROLL_REG = 0x3D   # live Roll output, for comparison
ANGLE_PITCH_REG = 0x3E  # live Pitch output, for comparison


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


def read_register(sock: socket.socket, slave: int, reg_addr: int):
    """Returns (raw_value, diagnostic). raw_value is None on failure."""
    body = bytes([slave, 0x03, (reg_addr >> 8) & 0xFF, reg_addr & 0xFF, 0x00, 0x01])
    crc = crc16_modbus(body)
    request = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    expected_len = 3 + 2 + 2

    sock.sendall(request)
    response = b""
    try:
        while len(response) < expected_len:
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk
    except socket.timeout:
        pass

    if len(response) == 0:
        return None, f"no response (timeout) -- sent: {request.hex(' ').upper()}"
    if len(response) == 5 and response[1] == (0x03 | 0x80):
        return None, f"Modbus EXCEPTION, code 0x{response[2]:02X}"
    if len(response) != expected_len:
        return None, f"unexpected length {len(response)}, received: {response.hex(' ').upper()}"
    if response[0] != slave or response[1] != 0x03:
        return None, f"unexpected header: {response[:3].hex()}"

    data = response[3:5]
    recv_crc = response[5:7]
    calc_crc = crc16_modbus(response[:5])
    if recv_crc[0] != (calc_crc & 0xFF) or recv_crc[1] != ((calc_crc >> 8) & 0xFF):
        return None, "CRC mismatch"

    raw = (data[0] << 8) | data[1]
    return raw, ""


def to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def stop_imu_mqtt() -> bool:
    result = subprocess.run(["sudo", "systemctl", "stop", "imu_mqtt"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Couldn't stop imu_mqtt.service: {result.stderr.strip()}")
        return False
    time.sleep(1)
    return True


def start_imu_mqtt() -> bool:
    result = subprocess.run(["sudo", "systemctl", "start", "imu_mqtt"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Couldn't restart imu_mqtt.service: {result.stderr.strip()}")
        print("Start it manually: sudo systemctl start imu_mqtt")
        return False
    return True


def main() -> int:
    print("Stopping imu_mqtt.service...")
    if not stop_imu_mqtt():
        return 1
    print("Stopped.\n")

    try:
        with socket.create_connection((GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_TIMEOUT) as sock:
            sock.settimeout(SOCKET_TIMEOUT)

            for label, reg in [
                ("XREFROLL (0x79)", XREFROLL_REG),
                ("YREFPITCH (0x7A)", YREFPITCH_REG),
                ("live Roll (0x3D)", ANGLE_ROLL_REG),
                ("live Pitch (0x3E)", ANGLE_PITCH_REG),
            ]:
                raw, diag = read_register(sock, SLAVE_ADDR, reg)
                if raw is None:
                    print(f"{label}: READ FAILED -- {diag}")
                    continue
                signed = to_s16(raw)
                deg = signed / 32768 * 180
                print(f"{label}: raw=0x{raw:04X} ({raw}), signed={signed}, as-degrees={deg:.2f}°")
    except (OSError, ValueError) as e:
        print(f"Modbus read failed: {e}")
    finally:
        print("\nRestarting imu_mqtt.service...")
        if not start_imu_mqtt():
            print("MANUAL ACTION NEEDED: start it yourself with 'sudo systemctl start imu_mqtt'")
            return 1
        print("Restarted.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
