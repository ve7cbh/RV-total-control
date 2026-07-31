#!/usr/bin/env python3
"""
update_weewx_station_location.py — keeps weewx.conf's [Station]
latitude/longitude in sync with the WitMotion's live GPS position (HW-27,
485-4), since this is an RV and the physical station moves.

Why this matters: WeeWX uses [Station] latitude/longitude for sunrise/
sunset calculations, NOAA report headers, and station metadata -- these go
stale the moment the trailer relocates if nothing updates them. Confirmed
2026-07-31: the value already in weewx.conf (48.8868, -123.6001) doesn't
quite match what's been used for the ECCC forecast widget (48.691,
-123.585) -- close, but drifted. This script becomes the authoritative,
GPS-driven source going forward.

Reads GPS directly over Modbus (same fresh-connection-per-poll pattern as
every other RVTC bridge script, self-contained copy per the project's
established style -- see imu_mqtt.py) rather than via MQTT, so this
doesn't depend on Mosquitto or imu_mqtt.py being up to run.

Only edits weewx.conf -- and only restarts WeeWX -- if the position has
moved more than MOVE_THRESHOLD_KM since the last confirmed update. Parked
GPS jitter (typically tens of metres) never triggers anything; a genuine
relocation does. Last confirmed position is cached in a small state file
(same pattern as imu_heading_state.json) so this comparison survives
across runs.

A bad or absent GPS fix is treated as "do nothing this run," never as
"jump to 0,0" or some other nonsense value -- see read_gps_position()'s
sanity checks (fix-quality heuristic + a rough Canada bounding box).

Not yet wired up: this state file's lat/lon would also be the natural
input for auto-selecting the nearest ECCC forecast site as the trailer
travels (the "auto position update" feature discussed alongside this one)
-- deliberately left for a separate pass rather than building both at
once.

Usage:
    python3 update_weewx_station_location.py
"""

import json
import math
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

# ── Config -- GPS read, register addresses must match imu_mqtt.py ───────
GATEWAY_HOST = "192.168.88.8"   # 485-4
GATEWAY_PORT = 4001
SLAVE_ADDR = 0x50
SOCKET_TIMEOUT = 2.0

GPS_LONLAT_REG_START = 0x49   # LonL, LonH, LatL, LatH
GPS_LONLAT_REG_COUNT = 4
GPS_SVDOP_REG_START = 0x55    # SVNUM, PDOP, HDOP
GPS_SVDOP_REG_COUNT = 3

# Same fix-quality heuristic as imu_mqtt.py's gps/fix_ok -- no documented
# fix-valid bit exists on this module, this is best-effort.
FIX_MIN_SATELLITES = 4
FIX_MAX_HDOP = 5.0

# Rough bounding box for Canada -- a reading outside this is treated as a
# bad fix rather than "the trailer teleported."
CANADA_LAT_RANGE = (41.0, 84.0)
CANADA_LON_RANGE = (-141.0, -52.0)

WEEWX_CONF_PATH = "/data/docker/volumes/weewx/weewx.conf"
STATE_PATH = "/home/ve7cbh/RV-total-control/config/weewx_location_state.json"

# Don't touch weewx.conf (or restart WeeWX) for GPS jitter while parked --
# only for a genuine move. Typical stationary GPS drift is tens of metres;
# 5 km comfortably clears that with margin.
MOVE_THRESHOLD_KM = 5.0


# ── Modbus RTU-over-TCP framing -- self-contained copy, matching the
# project's per-script style (see imu_mqtt.py's own docstring on this)
# rather than a shared import. ───────────────────────────────────────────

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


def nmea_to_deg(raw: int) -> float:
    sign = -1 if raw < 0 else 1
    raw = abs(raw)
    degrees = raw // 10000000
    minutes = (raw % 10000000) / 100000
    return sign * (degrees + minutes / 60)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def read_gps_position():
    """Returns (lat, lon). Raises ValueError with a human-readable reason
    if the reading looks unusable -- caller should treat that as
    "do nothing this run," not as a position update."""
    lonlat_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, GPS_LONLAT_REG_START, GPS_LONLAT_REG_COUNT
    )
    lon_raw = to_s32((lonlat_regs[1] << 16) | lonlat_regs[0])  # LonH<<16 | LonL
    lat_raw = to_s32((lonlat_regs[3] << 16) | lonlat_regs[2])  # LatH<<16 | LatL
    lon = nmea_to_deg(lon_raw)
    lat = nmea_to_deg(lat_raw)

    svdop_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, GPS_SVDOP_REG_START, GPS_SVDOP_REG_COUNT
    )
    satellites = svdop_regs[0]
    hdop = svdop_regs[2] / 100

    if satellites < FIX_MIN_SATELLITES or not (0 < hdop <= FIX_MAX_HDOP):
        raise ValueError(f"fix looks unreliable (satellites={satellites}, hdop={hdop})")
    if not (CANADA_LAT_RANGE[0] <= lat <= CANADA_LAT_RANGE[1]):
        raise ValueError(f"latitude {lat} outside expected range -- treating as bad fix")
    if not (CANADA_LON_RANGE[0] <= lon <= CANADA_LON_RANGE[1]):
        raise ValueError(f"longitude {lon} outside expected range -- treating as bad fix")

    return lat, lon


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_state(lat: float, lon: float) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump({
            "latitude": lat,
            "longitude": lon,
            "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, indent=2)


def update_weewx_conf(lat: float, lon: float) -> None:
    """Edits latitude/longitude in place. Aborts with no changes written
    if either line isn't found exactly once -- same "pattern not found"
    safety discipline as the skin.conf editors used earlier tonight."""
    with open(WEEWX_CONF_PATH) as f:
        content = f.read()

    new_content, n_lat = re.subn(
        r"^(\s*latitude\s*=\s*)[-\d.]+", rf"\g<1>{lat:.4f}",
        content, count=1, flags=re.MULTILINE,
    )
    if n_lat != 1:
        raise RuntimeError(f"Expected exactly 1 'latitude =' line, found {n_lat} -- aborting, no changes written")

    new_content, n_lon = re.subn(
        r"^(\s*longitude\s*=\s*)[-\d.]+", rf"\g<1>{lon:.4f}",
        new_content, count=1, flags=re.MULTILINE,
    )
    if n_lon != 1:
        raise RuntimeError(f"Expected exactly 1 'longitude =' line, found {n_lon} -- aborting, no changes written")

    with open(WEEWX_CONF_PATH, "w") as f:
        f.write(new_content)


def main() -> int:
    try:
        lat, lon = read_gps_position()
    except (OSError, ValueError) as e:
        print(f"Couldn't get a usable GPS position: {e}")
        return 1

    state = load_state()
    if state is not None:
        dist = haversine_km(state["latitude"], state["longitude"], lat, lon)
        if dist < MOVE_THRESHOLD_KM:
            print(f"Moved {dist:.2f} km since last confirmed position -- below "
                  f"{MOVE_THRESHOLD_KM} km threshold, no change.")
            return 0
        print(f"Moved {dist:.2f} km since last confirmed position -- updating weewx.conf.")
    else:
        print("No prior state found -- treating this as the first run, updating weewx.conf.")

    backup_path = f"{WEEWX_CONF_PATH}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(WEEWX_CONF_PATH, backup_path)
    print(f"Backed up weewx.conf to {backup_path}")

    try:
        update_weewx_conf(lat, lon)
    except RuntimeError as e:
        print(str(e))
        return 1

    save_state(lat, lon)
    print(f"Updated weewx.conf: latitude={lat:.4f}, longitude={lon:.4f}")

    try:
        subprocess.run(["docker", "restart", "weewx"], check=True)
        print("Restarted weewx container.")
    except subprocess.CalledProcessError as e:
        print(f"weewx.conf was updated but the restart failed ({e}) -- restart it manually.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
