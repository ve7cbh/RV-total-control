#!/usr/bin/env python3
"""
gps_burst_capture.py — one-off diagnostic: rapid-fire consecutive raw reads
of the WitMotion's GPS Lon/Lat register block (0x49-0x4C), to test whether
the longitude bug is a single static defect or an intermittent torn-read
issue.

Why this is needed: two widely-spaced reads (read_gps_ref_registers.py,
~15 min apart) showed nearly identical malformed longitude (minutes field
>60 both times), which looked like a stable, static defect. But live
observation of the dashboard caught a THIRD, different wrong longitude
value flash by for a single refresh cycle -- a fixed defect wouldn't do
that. This script replicates imu_mqtt.py's exact read pattern (one single
4-register Modbus block read covering LonL/LonH/LatL/LatH together, same
as poll_once()) but rapidly and repeatedly, to see whether raw values:
  (a) are always identical/near-identical -> genuinely static defect
  (b) cluster into a small number of distinct groups -> consistent with
      the chip's internal registers being updated non-atomically, and
      reads occasionally catching a torn/mixed snapshot
  (c) vary continuously/randomly -> something else (e.g. real GPS
      solution instability), worth investigating separately

Default: 100 reads, 100ms apart (~10s total) -- fast enough to sample
several times within one likely 1Hz internal GPS update cycle, which is
exactly the window where a torn read would show up.

Same safe pattern as the other one-off IMU diagnostics: stops
imu_mqtt.service once before starting (not per-read -- that would be far
too slow for this), restarts it afterward via try/finally regardless of
outcome, including on Ctrl+C.

Usage:
    python3 gps_burst_capture.py [count] [interval_seconds]
    python3 gps_burst_capture.py 200 0.05
"""

import socket
import subprocess
import sys
import time
from collections import Counter

GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

GPS_LONLAT_REG_START = 0x49   # LonL, LonH, LatL, LatH -- same block,
GPS_LONLAT_REG_COUNT = 4      # same single read imu_mqtt.py's poll_once() does

DEFAULT_COUNT = 5000
DEFAULT_INTERVAL = 0.05


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


def build_read_request(slave: int, start_reg: int, count: int) -> bytes:
    body = bytes([
        slave, 0x03,
        (start_reg >> 8) & 0xFF, start_reg & 0xFF,
        (count >> 8) & 0xFF, count & 0xFF,
    ])
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def read_registers(host: str, port: int, slave: int, start_reg: int, count: int):
    """Fresh connection per read, matching every other bridge script's
    established pattern (see System Reference Section 8) -- one Modbus
    transaction, closed immediately. Returns list of ints, raises on any
    framing/CRC problem."""
    request = build_read_request(slave, start_reg, count)
    expected_len = 3 + (count * 2) + 2

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

    return [(data[i] << 8) | data[i + 1] for i in range(0, byte_count, 2)]


def to_s32(v: int) -> int:
    return v - 4294967296 if v >= 2147483648 else v


def nmea_to_deg(raw: int):
    """Returns (decimal_degrees, degrees, minutes, minutes_valid)."""
    sign = -1 if raw < 0 else 1
    araw = abs(raw)
    degrees = araw // 10000000
    minutes = (araw % 10000000) / 100000
    return sign * (degrees + minutes / 60), degrees, minutes, minutes < 60


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
    count = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COUNT
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_INTERVAL

    print(f"Capturing {count} reads, {interval*1000:.0f}ms apart (~{count*interval:.1f}s total)")
    print("Stopping imu_mqtt.service...")
    if not stop_imu_mqtt():
        return 1
    print("Stopped.\n")

    results = []  # list of (t, lon_deg, lon_dd, lon_mm, lon_valid, lon_raw_hex, lat_deg)
    errors = 0
    t0 = time.monotonic()

    try:
        for i in range(count):
            t = time.monotonic() - t0
            try:
                regs = read_registers(GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR,
                                       GPS_LONLAT_REG_START, GPS_LONLAT_REG_COUNT)
                lon_raw = to_s32((regs[1] << 16) | regs[0])
                lat_raw = to_s32((regs[3] << 16) | regs[2])
                lon_deg, lon_dd, lon_mm, lon_valid = nmea_to_deg(lon_raw)
                lat_deg, _, _, _ = nmea_to_deg(lat_raw)
                results.append((t, lon_deg, lon_dd, lon_mm, lon_valid,
                                 f"L={regs[0]:04X} H={regs[1]:04X}", lat_deg))
                flag = "" if lon_valid else "  <-- INVALID MINUTES"
                print(f"[{t:6.2f}s] lon={lon_deg:.6f}  (dd={lon_dd} mm={lon_mm:.4f}) "
                      f"raw(L={regs[0]:04X},H={regs[1]:04X})  lat={lat_deg:.6f}{flag}")
            except (OSError, ValueError) as e:
                errors += 1
                print(f"[{t:6.2f}s] READ FAILED -- {e}")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nInterrupted by user -- showing summary of what was captured so far.")

    finally:
        print("\nRestarting imu_mqtt.service...")
        if not start_imu_mqtt():
            print("MANUAL ACTION NEEDED: start it yourself with 'sudo systemctl start imu_mqtt'")

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*60}\nSUMMARY: {len(results)} successful reads, {errors} failed\n{'='*60}")
    if not results:
        return 1

    # Cluster by rounded longitude (4 decimal places ~= 11m) to see
    # whether values fall into a small number of distinct groups
    # (supports torn-read theory) vs. vary continuously (doesn't).
    rounded = [round(r[1], 4) for r in results]
    clusters = Counter(rounded)
    print(f"\nDistinct longitude clusters (rounded to 4dp, ~11m buckets):")
    for val, n in clusters.most_common():
        pct = 100 * n / len(results)
        print(f"  {val:>12.4f}  x{n:<4d} ({pct:.0f}%)")

    invalid_count = sum(1 for r in results if not r[4])
    print(f"\nReads with invalid (>60) minutes field: {invalid_count}/{len(results)}")

    if len(clusters) == 1:
        print("\n-> Single cluster: longitude was IDENTICAL (or near-identical) on every")
        print("   read. Consistent with a static/fixed defect, not a timing/tearing issue.")
    elif len(clusters) <= 5:
        print(f"\n-> {len(clusters)} distinct clusters: consistent with the torn-read hypothesis --")
        print("   a small number of specific bad register combinations, not random noise.")
    else:
        print(f"\n-> {len(clusters)} distinct values, mostly unclustered: doesn't fit a simple")
        print("   torn-read theory as neatly -- may be genuine GPS solution instability,")
        print("   or a more complex timing interaction. Worth a longer capture.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
