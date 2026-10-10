#!/usr/bin/env python3
"""
test_imu_reset.py — carefully tests the WitMotion's SAVE=0x0001 ("Reset")
command, which Steve recalls zeroing heading/pitch/roll on a Windows bench
tool -- distinct from the SAVE=0x0000 ("Save") command
zero_imu_pitch_roll.py already uses, and from SAVE=0x00FF ("Reboot").

Why the caution: the manual gives this only a one-word label, no detail on
scope. "Reset" language on devices like this often means a genuine
factory reset -- Modbus address, baud rate, parity, everything -- not a
scoped "just zero the angles" operation. If it changes address/baud,
imu_mqtt.py loses the ability to talk to the device at all, a much bigger
problem than a wrong pitch/roll reading.

Mitigating factor, not a guarantee: every script in this project assumes
address 0x50 / 9600 baud / no parity -- the WitMotion's own documented
factory defaults. If Reset restores factory settings, it's very likely
landing back on the values already in use. This script still snapshots
those settings before touching anything, requires a typed confirmation
before sending SAVE=0x0001, and verifies communication immediately
afterward at the SAME address rather than assuming success.

If communication is lost after this (this script can't reach the device
at 0x50/9600 anymore): the device likely needs to be found again at
whatever address/baud it landed on -- check the manual's default value
table first (address 1-255, but WT-series often defaults to 0x50) before
assuming anything is physically broken.

Usage:
    python3 test_imu_reset.py
"""

import socket
import subprocess
import sys
import time

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

KEY_REG = 0x69
UNLOCK_VALUE = 0xB588
SAVE_REG = 0x00
RESET_VALUE = 0x0001

# Hold registers worth snapshotting before touching anything -- these are
# exactly what would break communication if they changed.
ADDR_REG = 0x0A
BAUD_REG = 0x0B
PARITY_REG = 0x3D

ROLL_ANGLE_REG = 0x3D
PITCH_ANGLE_REG = 0x3E
YAW_ANGLE_REG = 0x3F

# Reset may take longer to complete internally than a plain Save --
# generous wait before trying to talk to the device again.
POST_RESET_WAIT_SECONDS = 5


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
        return None, "no response (timeout)"
    if len(response) == 5 and response[1] == (0x03 | 0x80):
        return None, f"Modbus EXCEPTION, code 0x{response[2]:02X}"
    if len(response) != expected_len:
        return None, f"unexpected length {len(response)}: {response.hex(' ').upper()}"
    if response[0] != slave or response[1] != 0x03:
        return None, f"unexpected header: {response[:3].hex()}"

    data = response[3:5]
    recv_crc = response[5:7]
    calc_crc = crc16_modbus(response[:5])
    if recv_crc[0] != (calc_crc & 0xFF) or recv_crc[1] != ((calc_crc >> 8) & 0xFF):
        return None, "CRC mismatch"

    return (data[0] << 8) | data[1], ""


def write_single_register(sock: socket.socket, slave: int, reg_addr: int, value: int):
    body = bytes([slave, 0x06, (reg_addr >> 8) & 0xFF, reg_addr & 0xFF, (value >> 8) & 0xFF, value & 0xFF])
    crc = crc16_modbus(body)
    request = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    sock.sendall(request)
    response = b""
    try:
        while len(response) < len(request):
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk
    except socket.timeout:
        pass

    if response == request:
        return True, ""
    if len(response) == 0:
        return False, "no response (timeout)"
    return False, f"response didn't match -- received: {response.hex(' ').upper()}"


def to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def snapshot(sock: socket.socket, label: str):
    print(f"\n--- {label} ---")
    values = {}
    for name, reg in [
        ("address", ADDR_REG), ("baud_code", BAUD_REG), ("parity_code", PARITY_REG),
        ("roll", ROLL_ANGLE_REG), ("pitch", PITCH_ANGLE_REG), ("yaw", YAW_ANGLE_REG),
    ]:
        raw, diag = read_register(sock, SLAVE_ADDR, reg)
        if raw is None:
            print(f"  {name}: READ FAILED -- {diag}")
            values[name] = None
            continue
        if name in ("roll", "pitch", "yaw"):
            deg = to_s16(raw) / 32768 * 180
            print(f"  {name}: {deg:.2f}°")
            values[name] = deg
        else:
            print(f"  {name}: {raw} (0x{raw:04X})")
            values[name] = raw
    return values


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
    print("Stopped.")

    before = {}
    reset_sent = False
    still_reachable = True

    try:
        with socket.create_connection((GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_TIMEOUT) as sock:
            sock.settimeout(SOCKET_TIMEOUT)
            before = snapshot(sock, "BEFORE reset")

            print("\n" + "=" * 60)
            print("About to send SAVE=0x0001 (Reset) to the WitMotion.")
            print("This is UNDOCUMENTED beyond a one-word label -- it may reset")
            print("only angles, or it may factory-reset address/baud/everything.")
            print(f"Snapshotted settings above so we have something to compare against.")
            print("=" * 60)
            answer = input("\nType 'yes' to proceed, anything else to abort: ").strip().lower()

            if answer != "yes":
                print("Aborted -- nothing sent to the device.")
                return 0

            ok, diag = write_single_register(sock, SLAVE_ADDR, KEY_REG, UNLOCK_VALUE)
            if not ok:
                print(f"Unlock failed: {diag} -- aborting before sending reset.")
                return 1
            print("Unlocked.")

            ok, diag = write_single_register(sock, SLAVE_ADDR, SAVE_REG, RESET_VALUE)
            reset_sent = True
            if ok:
                print("Reset command sent and echoed correctly.")
            else:
                print(f"Reset write didn't echo cleanly: {diag}")
                print("(This alone doesn't mean it failed -- a real reset might drop the")
                print("connection before it can echo. Checking communication next either way.)")
    except (OSError, ValueError) as e:
        print(f"Modbus error: {e}")
        reset_sent = True   # can't be sure it wasn't sent -- treat as sent for safety

    if reset_sent:
        print(f"\nWaiting {POST_RESET_WAIT_SECONDS}s before checking if the device is still reachable...")
        time.sleep(POST_RESET_WAIT_SECONDS)

        try:
            with socket.create_connection((GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_TIMEOUT) as sock:
                sock.settimeout(SOCKET_TIMEOUT)
                after = snapshot(sock, f"AFTER reset (still at address 0x{SLAVE_ADDR:02X})")
                if after.get("address") is None:
                    still_reachable = False
        except OSError as e:
            print(f"\nCouldn't even open a connection: {e}")
            still_reachable = False

        if not still_reachable:
            print("\n*** DEVICE NOT REACHABLE at the expected address/baud after reset. ***")
            print("It may have changed address or baud rate. Check the manual's default")
            print("value table (address is typically still 0x50, baud 9600 = code 1) and")
            print("try scanning, before assuming anything is physically broken.")

    print("\nRestarting imu_mqtt.service...")
    if not start_imu_mqtt():
        print("MANUAL ACTION NEEDED: start it yourself with 'sudo systemctl start imu_mqtt'")
        return 1
    print("Restarted.")

    if reset_sent and still_reachable:
        print("\nCheck heading/pitch/roll in MQTT Explorer now to see the actual effect.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
