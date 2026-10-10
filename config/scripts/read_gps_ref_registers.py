#!/usr/bin/env python3
"""
read_gps_ref_registers.py — one-off diagnostic: reads back the WitMotion's
raw LonL/LonH/LatL/LatH registers (0x49-0x4C) directly, individually and
combined, to check whether the longitude error (~39km east, minutes field
looks roughly 10x too small) comes from the chip's own raw register
content or from imu_mqtt.py's decode math.

Why this is needed: nmea_to_deg() and the LonH<<16|LonL combining logic
in imu_mqtt.py both check out by hand against a known-correct worked
example -- so before assuming either of those is wrong, the next step is
reading what the chip is actually putting in these registers right now
and hand-checking THAT against a known true position, same discipline as
every other mystery on this device (axis swap, TIMEZONE offset). Don't
guess twice.

Same safe pattern as read_imu_ref_registers.py: stops imu_mqtt.service
before touching the device directly, restarts it afterward via
try/finally regardless of outcome.

Usage:
    python3 read_gps_ref_registers.py
"""

import socket
import subprocess
import sys
import time

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

LONL_REG = 0x49
LONH_REG = 0x4A
LATL_REG = 0x4B
LATH_REG = 0x4C
SVNUM_REG = 0x55   # satellite count, read alongside as a sanity check --
                    # if this looks wrong too, the whole GPS block may be
                    # misaligned, not just longitude specifically


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


def to_s32(v: int) -> int:
    return v - 4294967296 if v >= 2147483648 else v


def nmea_to_deg(raw: int) -> float:
    """Doc format: ddmm.mmmmm, packed *10^7 into a signed 32-bit int --
    same formula as imu_mqtt.py's own nmea_to_deg()."""
    sign = -1 if raw < 0 else 1
    raw = abs(raw)
    degrees = raw // 10000000
    minutes = (raw % 10000000) / 100000
    return sign * (degrees + minutes / 60)


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

            raws = {}
            for label, reg in [
                ("LonL (0x49)", LONL_REG),
                ("LonH (0x4A)", LONH_REG),
                ("LatL (0x4B)", LATL_REG),
                ("LatH (0x4C)", LATH_REG),
                ("SVNUM (0x55)", SVNUM_REG),
            ]:
                raw, diag = read_register(sock, SLAVE_ADDR, reg)
                if raw is None:
                    print(f"{label}: READ FAILED -- {diag}")
                    raws[label] = None
                    continue
                raws[label] = raw
                print(f"{label}: raw=0x{raw:04X} ({raw})")

            print()
            if None not in (raws.get("LonL (0x49)"), raws.get("LonH (0x4A)")):
                lon_raw = to_s32((raws["LonH (0x4A)"] << 16) | raws["LonL (0x49)"])
                lon_deg = nmea_to_deg(lon_raw)
                print(f"Combined LonH<<16|LonL = {lon_raw}  ->  nmea_to_deg = {lon_deg:.6f}")
                print(f"  (as ddmm.mmmmm this packs as: {lon_raw / 10000000:.7f} -- "
                      f"degrees={lon_raw // 10000000}, minutes={(lon_raw % 10000000) / 100000:.5f})")

            if None not in (raws.get("LatL (0x4B)"), raws.get("LatH (0x4C)")):
                lat_raw = to_s32((raws["LatH (0x4C)"] << 16) | raws["LatL (0x4B)"])
                lat_deg = nmea_to_deg(lat_raw)
                print(f"Combined LatH<<16|LatL = {lat_raw}  ->  nmea_to_deg = {lat_deg:.6f}")
                print(f"  (as ddmm.mmmmm this packs as: {lat_raw / 10000000:.7f} -- "
                      f"degrees={lat_raw // 10000000}, minutes={(lat_raw % 10000000) / 100000:.5f})")

            print("\nCompare against a known true position (phone/handheld GPS): "
                  "(lat/lon in decimal degrees)")

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
