#!/usr/bin/env python3
"""
imu_mqtt.py — WitMotion WTGAHRS3-485 (HW-27) bridge for RVTC's unified MQTT namespace.

Replaces two things that are now obsolete:
  - modbus_imu.yaml (Home Assistant polling this device directly via a
    `modbus:` block). HA stays a consumer only, same as every other RVTC
    sensor — the Waveshare gateway drops idle pymodbus connections, the
    exact failure mode System Reference Section 8 already documents for
    the early epever/samlux attempts. This script opens a fresh socket
    per poll and closes it, never holding a persistent connection open.
  - gps_mqtt.py / gps_mqtt.service (separate gpsd-fed GPS bridge). This
    unit's own onboard GPS registers (Lon/Lat/SVNUM/HDOP) replace that
    path — validated against the bench capture on 2026-07-25 (CRC-clean
    across 13 frames, Lon/Lat matched the known Nanaimo location to 5-6
    decimal places).

Publishes:
    rvtc/sensors/imu/heading            true heading, degrees (0-360) -- raw
                                         Yaw with the stored offset applied,
                                         see set_imu_heading.py
    rvtc/sensors/imu/heading_needs_init true/false -- true means the offset
                                         hasn't been (re)established since the
                                         last suspected power cycle, so the
                                         heading value above shouldn't be
                                         trusted. Consumers (index.html,
                                         HA) should surface this as a warning
                                         rather than silently showing a
                                         possibly-wrong heading.
    rvtc/sensors/imu/pitch              degrees, vehicle nose-up positive
    rvtc/sensors/imu/roll               degrees, vehicle
    rvtc/sensors/imu/status             "OK" (placeholder for future health checks)
    rvtc/sensors/imu/availability       "online" / "offline" (LWT)
    rvtc/sensors/gps/latitude
    rvtc/sensors/gps/longitude
    rvtc/sensors/gps/satellites_used
    rvtc/sensors/gps/hdop

    -- Added for APRS (basic NMEA-equivalent fields) --
    rvtc/sensors/gps/altitude_m         GPS altitude, metres (GPSHeight, 0x4D)
    rvtc/sensors/gps/course_deg         GPS course over ground, degrees
                                         (GPSYAW, 0x4E) -- this is the GPS
                                         module's own course solution, NOT
                                         the WitMotion's magnetic Yaw. Don't
                                         confuse with rvtc/sensors/imu/heading.
    rvtc/sensors/gps/speed_kmh          GPS ground speed, km/h (GPSVL/GPSVH,
                                         0x4F/0x50, 32-bit)
    rvtc/sensors/gps/utc_time           ISO-ish "YYYY-MM-DD HH:MM:SS.mmm",
                                         true UTC. Computed from the on-chip
                                         time block (YYMM/DDHH/MMSS/MS,
                                         0x30-0x33) MINUS the module's own
                                         TIMEZONE register offset (0x6B).
                                         CONFIRMED 2026-07-30: TIMEZONE read
                                         back as 0x05 (UTC-7), and the
                                         on-chip time block was tracking
                                         Nanaimo LOCAL time, not UTC as its
                                         field names in the register map
                                         imply -- the module applies its own
                                         TIMEZONE offset internally before
                                         exposing that block. This code
                                         subtracts the offset back out to
                                         recover true UTC. If TIMEZONE is
                                         ever changed on the unit (or the RV
                                         changes time zones and someone
                                         updates it to keep local displays
                                         convenient), this still self-corrects
                                         since the offset is re-read every
                                         poll -- but re-verify against a
                                         known-good UTC source if the numbers
                                         ever look wrong, same as any other
                                         derived field here.
    rvtc/sensors/gps/chip_local_time    ISO-ish local-time string, straight
                                         off the on-chip block with no offset
                                         correction applied. Published mainly
                                         as a diagnostic so a future "the
                                         time looks wrong" report has both
                                         numbers to compare, not just the
                                         corrected one.
    rvtc/sensors/gps/fix_ok             bool -- best-effort heuristic only.
                                         The register map has no documented
                                         "fix valid" bit. Currently:
                                         svnum > 3 AND hdop < 5.0 (hdop unit
                                         per datasheet: HDOP[15:0]/100).
                                         Treat as a placeholder needing bench
                                         validation, same as the other
                                         unverified GPS items already
                                         flagged in the System Reference
                                         (OI-36 territory) -- not a
                                         guaranteed 2D/3D fix indicator.

Depends on a heading offset established by set_imu_heading.py, and on
imu_heading_state.json being marked needs_init=true at every host boot by
imu_needs_init_on_boot.service -- see those files for the full mechanism.

NOT persisted to InfluxDB by design for the pose fields — System Reference
Section 9: "nobody needs a queryable history of past pitch/roll/heading,
only the live value." No telegraf_imu.conf needed for those.
GPS position: the old gpsd-based path never had a telegraf_gps.conf either
(Section 4's config list doesn't include one), so this isn't a carry-over
decision to persist it — if you want position history, that's a fresh
call, not something this script assumes for you.

** AXIS SWAP — read this before touching register addresses **
Bench-tested 2026-07-25 with the unit mounted Y-axis-forward (direction of
travel). Physically rolling the unit (rotation about the fore-aft axis —
a real vehicle "roll") moved the WitMotion's own "Pitch" register (0x3E),
not its "Roll" register (0x3D). The chip's internal axis labels do not
match vehicle convention on this mounting:

    vehicle ROLL   == WitMotion "Pitch" register, address 0x3E
    vehicle PITCH  == WitMotion "Roll"  register, address 0x3D
    vehicle YAW/heading == WitMotion "Yaw" register, address 0x3F  (unaffected)

If the physical mounting orientation ever changes, redo the bench test —
tip the unit about each axis and watch which raw register moves — before
trusting this mapping again. Do not "fix" the swap below back to matching
the datasheet names; it's intentional.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import json
import logging
import socket
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────────────────────────────
GATEWAY_HOST = "192.168.88.8"     # 485-4, per System Reference Section 3
GATEWAY_PORT = 4001

SLAVE_ADDR = 0x50   # WitMotion default device address (IICADDR register 0x1A).
                     # Change here (and via IICADDR on the unit itself) if you
                     # readdress it to match the original slave-10 plan from
                     # the retired IMU_config.md.

ANGLE_REG_START = 0x3D   # Roll, Pitch, Yaw are three contiguous registers
ANGLE_REG_COUNT = 3

GPS_LONLAT_REG_START = 0x49   # LonL, LonH, LatL, LatH
GPS_LONLAT_REG_COUNT = 4

GPS_SVDOP_REG_START = 0x55    # SVNUM, PDOP, HDOP
GPS_SVDOP_REG_COUNT = 3

# -- Added for APRS --
GPS_ALT_COURSE_REG_START = 0x4D   # GPSHeight, GPSYAW
GPS_ALT_COURSE_REG_COUNT = 2

GPS_SPEED_REG_START = 0x4F        # GPSVL, GPSVH (32-bit, low word first)
GPS_SPEED_REG_COUNT = 2

TIME_REG_START = 0x30             # YYMM, DDHH, MMSS, MS
TIME_REG_COUNT = 4

TIMEZONE_REG_ADDR = 0x6B          # module's own UTC-offset register, applied
                                   # internally to the block above -- see
                                   # docstring, confirmed 2026-07-30

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
IMU_TOPIC_BASE = "rvtc/sensors/imu"
GPS_TOPIC_BASE = "rvtc/sensors/gps"
AVAILABILITY_TOPIC = f"{IMU_TOPIC_BASE}/availability"

# Written by set_imu_heading.py (manual init) and by
# imu_needs_init_on_boot.service (sets needs_init=true at every host boot --
# see that unit's comments for why this is a reasonable but imperfect proxy
# for the IMU itself losing power). Re-read every poll cycle rather than
# cached once, so a manual re-init while this script is already running
# takes effect on the very next publish, not after a restart.
HEADING_STATE_FILE = "/home/ve7cbh/RV-total-control/config/scripts/imu_heading_state.json"

# Best-effort "does the GPS have a usable fix" heuristic -- see docstring
# caveat above. No documented fix-valid bit exists in the register map.
FIX_MIN_SATELLITES = 4
FIX_MAX_HDOP = 5.0

POLL_INTERVAL_SECONDS = 0.5   # 2 Hz -- plenty for a leveling display. 9600 baud
                               # leaves headroom to go faster later if it ever
                               # feels sluggish while actively jacking the trailer.
SOCKET_TIMEOUT = 2.0
RETRY_SECONDS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s imu_mqtt: %(message)s",
)
log = logging.getLogger("imu_mqtt")


# ── Modbus RTU-over-TCP framing ──────────────────────────────────────────
# Fresh connection per poll, closed immediately after — see System Reference
# Section 8: this is the pattern every RVTC bridge uses specifically because
# pymodbus's persistent connections get dropped idle by the Waveshare gateway.

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
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # CRC low byte first


def read_registers(host: str, port: int, slave: int, start_reg: int, count: int):
    """Opens a fresh socket, sends one FC03 request, returns a list of
    unsigned 16-bit register values. Raises rather than returning
    partial/bad data silently on any framing or CRC problem."""
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


def to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def to_s32(v: int) -> int:
    return v - 4294967296 if v >= 2147483648 else v


def load_heading_state() -> dict:
    """Returns {"needs_init": bool, "offset_deg": float}. Missing or
    unreadable file is treated as needs_init -- fail toward "don't trust
    the heading" rather than toward "assume it's fine"."""
    try:
        with open(HEADING_STATE_FILE) as f:
            data = json.load(f)
        return {
            "needs_init": bool(data.get("needs_init", True)),
            "offset_deg": float(data.get("offset_deg", 0.0)),
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return {"needs_init": True, "offset_deg": 0.0}


def nmea_to_deg(raw: int) -> float:
    """Doc format: ddmm.mmmmm, packed *10^7 into a signed 32-bit int."""
    sign = -1 if raw < 0 else 1
    raw = abs(raw)
    degrees = raw // 10000000
    minutes = (raw % 10000000) / 100000
    return sign * (degrees + minutes / 60)


# ── MQTT ──────────────────────────────────────────────────────────────────

def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id="rvtc-imu-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.will_set(AVAILABILITY_TOPIC, payload="offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
    return client


def publish(client: mqtt.Client, topic: str, value) -> None:
    if value is None:
        return
    client.publish(topic, payload=value, retain=False)


# ── Poll cycle ────────────────────────────────────────────────────────────

def poll_once(client: mqtt.Client) -> None:
    # Angles: Roll(0x3D), Pitch(0x3E), Yaw(0x3F) -- three contiguous registers.
    angle_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, ANGLE_REG_START, ANGLE_REG_COUNT
    )
    witmotion_roll = to_s16(angle_regs[0]) / 32768 * 180   # 0x3D -- this is vehicle PITCH
    witmotion_pitch = to_s16(angle_regs[1]) / 32768 * 180  # 0x3E -- this is vehicle ROLL
    witmotion_yaw = to_s16(angle_regs[2]) / 32768 * 180    # 0x3F -- heading, unaffected

    raw_heading_deg = witmotion_yaw if witmotion_yaw >= 0 else witmotion_yaw + 360
    vehicle_pitch_deg = witmotion_roll    # axis swap applied -- see module docstring
    vehicle_roll_deg = witmotion_pitch    # axis swap applied -- see module docstring

    # Apply the software heading offset -- see set_imu_heading.py's docstring
    # for why this exists (the WitMotion has no "set heading to X" register).
    heading_state = load_heading_state()
    corrected_heading_deg = (raw_heading_deg + heading_state["offset_deg"]) % 360

    publish(client, f"{IMU_TOPIC_BASE}/heading", round(corrected_heading_deg, 1))
    publish(client, f"{IMU_TOPIC_BASE}/heading_needs_init", heading_state["needs_init"])
    publish(client, f"{IMU_TOPIC_BASE}/pitch", round(vehicle_pitch_deg, 2))
    publish(client, f"{IMU_TOPIC_BASE}/roll", round(vehicle_roll_deg, 2))
    publish(client, f"{IMU_TOPIC_BASE}/status", "OK")

    # GPS: Lon/Lat block.
    lonlat_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, GPS_LONLAT_REG_START, GPS_LONLAT_REG_COUNT
    )
    lon_raw = to_s32((lonlat_regs[1] << 16) | lonlat_regs[0])  # LonH<<16 | LonL
    lat_raw = to_s32((lonlat_regs[3] << 16) | lonlat_regs[2])  # LatH<<16 | LatL
    publish(client, f"{GPS_TOPIC_BASE}/longitude", round(nmea_to_deg(lon_raw), 6))
    publish(client, f"{GPS_TOPIC_BASE}/latitude", round(nmea_to_deg(lat_raw), 6))

    # GPS: satellite count / HDOP.
    svdop_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, GPS_SVDOP_REG_START, GPS_SVDOP_REG_COUNT
    )
    satellites_used = svdop_regs[0]
    hdop = svdop_regs[2] / 100
    publish(client, f"{GPS_TOPIC_BASE}/satellites_used", satellites_used)
    publish(client, f"{GPS_TOPIC_BASE}/hdop", round(hdop, 2))

    # -- Added for APRS --

    # GPS altitude + course over ground.
    alt_course_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR,
        GPS_ALT_COURSE_REG_START, GPS_ALT_COURSE_REG_COUNT,
    )
    gps_altitude_m = to_s16(alt_course_regs[0]) / 10
    gps_course_deg = alt_course_regs[1] / 100
    publish(client, f"{GPS_TOPIC_BASE}/altitude_m", round(gps_altitude_m, 1))
    publish(client, f"{GPS_TOPIC_BASE}/course_deg", round(gps_course_deg, 2))

    # GPS ground speed -- 32-bit, low word (GPSVL) then high word (GPSVH).
    speed_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, GPS_SPEED_REG_START, GPS_SPEED_REG_COUNT
    )
    speed_raw = to_s32((speed_regs[1] << 16) | speed_regs[0])  # GPSVH<<16 | GPSVL
    gps_speed_kmh = speed_raw / 1000
    publish(client, f"{GPS_TOPIC_BASE}/speed_kmh", round(gps_speed_kmh, 2))

    # On-chip time block -- this is LOCAL time, not UTC, despite the
    # register map's field names implying otherwise. Confirmed 2026-07-30:
    # TIMEZONE (0x6B) read back as 0x05 (UTC-7) and the block matched
    # Nanaimo local time to the minute. Read TIMEZONE every cycle (cheap,
    # one register) so this keeps working if the offset is ever changed.
    time_regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, TIME_REG_START, TIME_REG_COUNT
    )
    yymm, ddhh, mmss, ms = time_regs
    year = 2000 + (yymm & 0xFF)
    month = (yymm >> 8) & 0xFF
    day = ddhh & 0xFF
    hour = (ddhh >> 8) & 0xFF
    minute = mmss & 0xFF
    second = (mmss >> 8) & 0xFF

    chip_local_str = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}.{ms:03d}"
    publish(client, f"{GPS_TOPIC_BASE}/chip_local_time", chip_local_str)

    tz_raw = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR, TIMEZONE_REG_ADDR, 1
    )[0]
    tz_offset_hours = tz_raw - 12
    try:
        chip_local_dt = datetime(year, month, day, hour, minute, second, ms * 1000)
        true_utc_dt = chip_local_dt - timedelta(hours=tz_offset_hours)
        utc_str = true_utc_dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{ms:03d}"
    except ValueError:
        # Time block hasn't been populated yet (e.g. no fix since boot) --
        # publish nothing rather than a bogus date.
        utc_str = None
    publish(client, f"{GPS_TOPIC_BASE}/utc_time", utc_str)

    # Best-effort fix heuristic -- see docstring caveat, no documented
    # fix-valid bit exists on this module.
    fix_ok = (satellites_used >= FIX_MIN_SATELLITES) and (hdop <= FIX_MAX_HDOP) and (hdop > 0)
    publish(client, f"{GPS_TOPIC_BASE}/fix_ok", fix_ok)

    # TODO — true heading (OI-36, wind direction correction).
    # WitMotion's Yaw is magnetic heading only; no declination is applied
    # on-device. Deviation (vehicle's own magnetic influence) is handled
    # once via the unit's own Magnetic Field calibration after final
    # mounting -- that's a hardware-side fix, not something this script
    # touches. Declination (true-vs-magnetic-north, varies by location)
    # still needs a magnetic model (e.g. pygeomag) fed the Lon/Lat above.
    # Left as a stub rather than a guess: publishing an uncorrected
    # "true_heading" would be worse than not publishing one at all.


def run() -> None:
    client = make_mqtt_client()
    while True:
        try:
            poll_once(client)
            client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
        except (OSError, ValueError) as e:
            log.warning(f"poll failed ({e}); retrying in {RETRY_SECONDS}s")
            client.publish(AVAILABILITY_TOPIC, payload="offline", retain=True)
            time.sleep(RETRY_SECONDS)
            continue
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped")
