#!/usr/bin/env python3
"""
zero_imu_pitch_roll.py — "warm boot" for the WitMotion's pitch/roll: takes
whatever it's currently reading and makes THAT the new zero, without
touching heading calibration or requiring a physical power cycle.

Why this exists: after remounting the IMU in its permanent home (2026-08-01,
"more or less level... within 0.5 degrees"), pitch/roll should read ~0/0
for the current physical mounting. Rather than a real power-cycle "warm
boot," this uses the WitMotion's own XREFROLL/YREFPITCH registers
(0x79/0x7A) -- confirmed against the original Modbus manual's own worked
example (roll=2 deg -> XREFROLL=364=0x016C, byte-for-byte CRC match) before
this script was written.

This is deliberately temporary/coarse, matching what Steve described: a
real leveling + mount-shimming pass is planned later. Re-running this
script after that pass will re-zero against whatever the shimmed mount
reads at that point -- nothing here is a one-time-only operation.

Does NOT touch heading calibration -- that offset lives entirely in
imu_heading_state.json, never on the device, so this can't disturb it
either way regardless of what these registers do internally.

FIRST TIME WRITING TO THIS DEVICE: every prior WitMotion interaction this
project has done was read-only. Writing requires the unlock sequence the
manual's own opening instructions describe (KEY=0xB588 to register 0x69,
then the actual write, then SAVE, all within the device's 10-second
unlock window) -- verified the framing is correct against real worked
examples (the unlock and SAVE commands both byte-for-byte match the
manual's own examples), but the write itself hadn't been tried against
real hardware before this script's first run.

CHANGED 2026-08-01, after the first real attempt failed with no useful
diagnostic ("didn't echo correctly", no visibility into what actually
came back): two fixes. (1) write_single_register() now returns and prints
the actual raw bytes on any failure, including detecting a real 5-byte
Modbus exception response as distinct from a garbled/collided one, so a
failure is diagnosable instead of a dead end. (2) rather than risk
another race against imu_mqtt.py's continuous 2Hz poll (same collision
category already found and fixed twice elsewhere tonight), this script
now STOPS imu_mqtt.service before writing and restarts it afterward --
guaranteed via try/finally even if the write fails partway through, so
the sensor bridge is never left down because of a failed write attempt.
The "before" pitch/roll reading has to happen BEFORE the stop (nothing
would be publishing to read from otherwise); "after" happens once
imu_mqtt.service is confirmed restarted.

Requires passwordless sudo for systemctl (matches how you've been running
sudo commands all night) -- if that's not configured, the stop/start
calls will fail cleanly with a clear message rather than hanging.

Does NOT touch heading calibration -- that offset lives entirely in
imu_heading_state.json, never on the device, so this can't disturb it
either way regardless of what these registers do internally.

Usage:
    python3 zero_imu_pitch_roll.py
"""

import socket
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
PITCH_TOPIC = "rvtc/sensors/imu/pitch"
ROLL_TOPIC = "rvtc/sensors/imu/roll"
WAIT_TIMEOUT_SECONDS = 10

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

KEY_REG = 0x69
UNLOCK_VALUE = 0xB588
XREFROLL_REG = 0x79
YREFPITCH_REG = 0x7A
SAVE_REG = 0x00
SAVE_VALUE = 0x0000   # save without rebooting

# How long to wait after writing before re-checking via MQTT -- long
# enough for imu_mqtt.py to publish at least one fresh reading (2 Hz).
VERIFY_DELAY_SECONDS = 2


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


def build_write_single_register(slave: int, reg_addr: int, value: int) -> bytes:
    body = bytes([
        slave, 0x06,
        (reg_addr >> 8) & 0xFF, reg_addr & 0xFF,
        (value >> 8) & 0xFF, value & 0xFF,
    ])
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def write_single_register(sock: socket.socket, slave: int, reg_addr: int, value: int):
    """Returns (success: bool, diagnostic: str). On success, diagnostic is
    empty. On failure, diagnostic describes exactly what was received so
    the real cause can be diagnosed rather than guessed at."""
    request = build_write_single_register(slave, reg_addr, value)
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
        return False, "no response at all (timeout) -- sent: " + request.hex(' ').upper()

    # A real Modbus exception response is 5 bytes: slave, function|0x80,
    # exception_code, CRClo, CRChi -- distinctly different from a garbled
    # echo, worth telling apart.
    if len(response) == 5 and response[1] == (0x06 | 0x80):
        return False, (
            f"Modbus EXCEPTION response, code 0x{response[2]:02X} -- "
            f"sent: {request.hex(' ').upper()}, received: {response.hex(' ').upper()}"
        )

    return False, (
        f"response didn't match request -- sent: {request.hex(' ').upper()}, "
        f"received ({len(response)} bytes): {response.hex(' ').upper()}"
    )


def deg_to_ref_register(deg: float) -> int:
    """Confirmed against the manual's own example: roll=2deg -> 364=0x016C."""
    raw = round(deg * 32768 / 180)
    return raw & 0xFFFF


def wait_for_fresh_pitch_roll():
    got = {}
    lock = threading.Lock()
    event = threading.Event()

    def on_connect(client, userdata, connect_flags, reason_code, properties=None):
        client.subscribe(PITCH_TOPIC)
        client.subscribe(ROLL_TOPIC)

    def on_message(client, userdata, msg):
        try:
            value = float(msg.payload.decode("utf-8", errors="replace"))
        except ValueError:
            return
        with lock:
            got[msg.topic] = value
            if PITCH_TOPIC in got and ROLL_TOPIC in got:
                event.set()

    client = mqtt.Client(
        client_id="rvtc-zero-imu-pitch-roll",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()

    got_it = event.wait(timeout=WAIT_TIMEOUT_SECONDS)
    client.loop_stop()
    client.disconnect()

    if not got_it:
        with lock:
            missing = [t for t in (PITCH_TOPIC, ROLL_TOPIC) if t not in got]
        raise TimeoutError(f"Didn't receive fresh values for: {', '.join(missing)}")

    with lock:
        return got[PITCH_TOPIC], got[ROLL_TOPIC]


def stop_imu_mqtt() -> bool:
    result = subprocess.run(
        ["sudo", "systemctl", "stop", "imu_mqtt"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Couldn't stop imu_mqtt.service: {result.stderr.strip()}")
        return False
    # Brief buffer so any in-flight poll/socket is fully closed before we
    # open our own connection to the same gateway.
    time.sleep(1)
    return True


def start_imu_mqtt() -> bool:
    result = subprocess.run(
        ["sudo", "systemctl", "start", "imu_mqtt"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Couldn't restart imu_mqtt.service: {result.stderr.strip()}")
        print("Start it manually: sudo systemctl start imu_mqtt")
        return False
    return True


def main() -> int:
    try:
        pitch_before, roll_before = wait_for_fresh_pitch_roll()
    except (OSError, TimeoutError) as e:
        print(f"Couldn't get a fresh reading from imu_mqtt.py over MQTT: {e}")
        print("Is imu_mqtt.service running? (systemctl status imu_mqtt)")
        return 1

    print(f"Current pitch: {pitch_before:.2f}°, roll: {roll_before:.2f}° -- these become the new zero.")

    # AXIS SWAP -- confirmed 2026-08-01, matching imu_mqtt.py's own
    # documented bench-test finding (2026-07-25): the device's raw
    # registers are mounted with vehicle ROLL == WitMotion's own "Pitch"
    # register (0x3E), and vehicle PITCH == WitMotion's own "Roll"
    # register (0x3D). imu_mqtt.py swaps these before publishing to MQTT
    # -- which means XREFROLL/YREFPITCH (which act on the device's RAW,
    # unswapped registers) need the swap applied in the OPPOSITE
    # direction from what a naive reading of the MQTT field names would
    # suggest. First attempt got this backwards; confirmed via
    # read_imu_ref_registers.py showing the written values landed on the
    # wrong physical axis. Do not "fix" this back to the naive mapping.
    xrefroll_val = deg_to_ref_register(pitch_before)    # 0x79 acts on raw 0x3D == vehicle pitch
    yrefpitch_val = deg_to_ref_register(roll_before)    # 0x7A acts on raw 0x3E == vehicle roll

    print("\nStopping imu_mqtt.service so nothing else is polling this device during the write...")
    if not stop_imu_mqtt():
        return 1
    print("Stopped.")

    write_failed = False
    try:
        with socket.create_connection((GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_TIMEOUT) as sock:
            sock.settimeout(SOCKET_TIMEOUT)

            ok, diag = write_single_register(sock, SLAVE_ADDR, KEY_REG, UNLOCK_VALUE)
            if not ok:
                print(f"Unlock write failed: {diag}")
                write_failed = True
            else:
                print("Unlocked.")

                ok, diag = write_single_register(sock, SLAVE_ADDR, XREFROLL_REG, xrefroll_val)
                if not ok:
                    print(f"XREFROLL write failed: {diag}")
                    write_failed = True
                else:
                    print(f"XREFROLL written: {xrefroll_val} (0x{xrefroll_val:04X})")

                    ok, diag = write_single_register(sock, SLAVE_ADDR, YREFPITCH_REG, yrefpitch_val)
                    if not ok:
                        print(f"YREFPITCH write failed: {diag}")
                        write_failed = True
                    else:
                        print(f"YREFPITCH written: {yrefpitch_val} (0x{yrefpitch_val:04X})")

                        ok, diag = write_single_register(sock, SLAVE_ADDR, SAVE_REG, SAVE_VALUE)
                        if not ok:
                            print(f"SAVE write failed: {diag}")
                            print("(XREFROLL/YREFPITCH were written but may not persist across power loss.)")
                            write_failed = True
                        else:
                            print("Saved.")
    except (OSError, ValueError) as e:
        print(f"Modbus write failed: {e}")
        write_failed = True
    finally:
        # Restart imu_mqtt no matter what happened above -- never leave the
        # sensor bridge down because a write attempt failed.
        print("\nRestarting imu_mqtt.service...")
        if not start_imu_mqtt():
            print("MANUAL ACTION NEEDED: start it yourself with 'sudo systemctl start imu_mqtt'")
            return 1
        print("Restarted.")

    if write_failed:
        print("\nWrite sequence failed (see above) -- nothing was necessarily changed on the device.")
        return 1

    print(f"\nWaiting {VERIFY_DELAY_SECONDS}s for imu_mqtt.py to publish a fresh reading...")
    time.sleep(VERIFY_DELAY_SECONDS)

    try:
        pitch_after, roll_after = wait_for_fresh_pitch_roll()
    except (OSError, TimeoutError) as e:
        print(f"Write sequence completed, but couldn't verify afterward: {e}")
        print("Check pitch/roll manually in MQTT Explorer.")
        return 1

    print(f"Pitch after: {pitch_after:.2f}° (was {pitch_before:.2f}°)")
    print(f"Roll after:  {roll_after:.2f}° (was {roll_before:.2f}°)")
    if abs(pitch_after) < 0.3 and abs(roll_after) < 0.3:
        print("Looks zeroed. If this doesn't match what you physically see, don't trust it --")
        print("come back and report the numbers above.")
    else:
        print("Doesn't look zeroed -- report these numbers back before trusting the leveling display.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
