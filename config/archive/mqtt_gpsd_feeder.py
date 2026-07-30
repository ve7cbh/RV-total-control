#!/usr/bin/env python3
"""
mqtt_gpsd_feeder.py — feeds gpsd from Mosquitto instead of a hardware GPS.

Why this exists: the packet-radio TNC (Direwolf) beacons position via its
built-in `GPSD` config directive, which expects a normal gpsd instance on
localhost:2947. Rather than wiring a second physical GPS antenna just for
the radio, this script re-publishes the WitMotion's already-validated
position data (via imu_mqtt.py -> rvtc/sensors/gps/#) as synthesized NMEA
sentences, written into a pty that gpsd is configured to treat as its
"device". gpsd itself and Direwolf's config are both unmodified from a
normal GPS-hardware setup — only gpsd's device path changes, from a real
/dev/ttyUSBx to this script's virtual one.

    Mosquitto (rvtc/sensors/gps/#)
        -> this script (subscriber, NMEA synthesizer)
            -> pty (fixed symlink path, see PTY_SYMLINK below)
                -> gpsd (DEVICES= that symlink in /etc/default/gpsd)
                    -> Direwolf's GPSD directive (unmodified)

Sentences sent: GGA, GLL, VTG.
    GGA is included because GLL alone doesn't carry a fix-quality/mode
    field, and gpsd (and Direwolf's fix-mode gating) may need GGA or GSA
    to consider the feed a valid fix -- confirmed by testing, not assumed.

** Known gaps, deliberately not papered over: **
  - Altitude is not currently published by imu_mqtt.py (the WitMotion's
    GPSHeight register aliased the magnetic-field HZ register bit-for-bit
    during bench testing -- see 2026-07-25 session -- so it's untrusted
    until re-checked). GGA's altitude field is sent blank until that's
    resolved; gpsd tolerates a blank altitude field.
  - Course and speed (VTG) are sent blank for the same reason: WitMotion's
    GPSYAW register aliased HZ during the same bench test, so course-over-
    ground isn't wired into imu_mqtt.py yet. Once it's been road-validated
    (see the outdoor-drive-test discussion) and imu_mqtt.py publishes
    rvtc/sensors/gps/course_deg and .../speed_knots, this script picks
    them up automatically -- no changes needed here, just start publishing
    those topics upstream.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import logging
import os
import pty
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────────────────────────────
MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
GPS_TOPIC_BASE = "rvtc/sensors/gps"

# Fixed, stable path for gpsd's DEVICES= line to point at. The pty's real
# /dev/pts/N number changes every run, so this symlink is recreated to
# point at whatever pts device this run actually got.
PTY_SYMLINK = "/tmp/rvtc_fake_gps"

SEND_INTERVAL_SECONDS = 1.0   # gpsd/Direwolf expect a steady ~1Hz stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s mqtt_gpsd_feeder: %(message)s",
)
log = logging.getLogger("mqtt_gpsd_feeder")

# Latest known values, updated by MQTT callbacks, read by the sentence
# writer thread. None means "not yet received" -- sentences reflect that
# honestly (blank fields) rather than guessing.
state = {
    "latitude": None,
    "longitude": None,
    "satellites_used": None,
    "hdop": None,
    "altitude_m": None,     # not currently published upstream -- see docstring
    "course_deg": None,     # not currently published upstream -- see docstring
    "speed_knots": None,    # not currently published upstream -- see docstring
}
state_lock = threading.Lock()


# ── NMEA helpers ──────────────────────────────────────────────────────────

def nmea_checksum(sentence_body: str) -> str:
    """sentence_body excludes the leading '$' and the trailing '*checksum'."""
    cs = 0
    for ch in sentence_body:
        cs ^= ord(ch)
    return f"{cs:02X}"


def with_checksum(sentence_body: str) -> str:
    return f"${sentence_body}*{nmea_checksum(sentence_body)}\r\n"


def deg_to_nmea_lat(lat: float):
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60
    return f"{degrees:02d}{minutes:07.4f}", hemi


def deg_to_nmea_lon(lon: float):
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60
    return f"{degrees:03d}{minutes:07.4f}", hemi


def utc_time_field() -> str:
    now = datetime.now(timezone.utc)   # NTP-disciplined system clock, per plan
    return now.strftime("%H%M%S.00")


# ── Sentence builders ────────────────────────────────────────────────────

def build_gga(s: dict) -> str:
    t = utc_time_field()
    lat_str, lat_hemi = deg_to_nmea_lat(s["latitude"])
    lon_str, lon_hemi = deg_to_nmea_lon(s["longitude"])
    sats = s["satellites_used"] if s["satellites_used"] is not None else ""
    hdop = f'{s["hdop"]:.1f}' if s["hdop"] is not None else ""
    alt = f'{s["altitude_m"]:.1f}' if s["altitude_m"] is not None else ""
    fix_quality = 1 if s["satellites_used"] not in (None, 0) else 0
    body = (
        f"GPGGA,{t},{lat_str},{lat_hemi},{lon_str},{lon_hemi},"
        f"{fix_quality},{sats},{hdop},{alt},M,,M,,"
    )
    return with_checksum(body)


def build_gll(s: dict) -> str:
    t = utc_time_field()
    lat_str, lat_hemi = deg_to_nmea_lat(s["latitude"])
    lon_str, lon_hemi = deg_to_nmea_lon(s["longitude"])
    status = "A"  # data valid -- we only build this sentence when lat/lon are known
    body = f"GPGLL,{lat_str},{lat_hemi},{lon_str},{lon_hemi},{t},{status},A"
    return with_checksum(body)


def build_vtg(s: dict) -> str:
    course = f'{s["course_deg"]:.1f}' if s["course_deg"] is not None else ""
    speed_kn = f'{s["speed_knots"]:.1f}' if s["speed_knots"] is not None else ""
    speed_kmh = f'{s["speed_knots"] * 1.852:.1f}' if s["speed_knots"] is not None else ""
    body = f"GPVTG,{course},T,,M,{speed_kn},N,{speed_kmh},K,A"
    return with_checksum(body)


# ── MQTT ──────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    log.info(f"connected to Mosquitto (rc={rc}), subscribing to {GPS_TOPIC_BASE}/#")
    client.subscribe(f"{GPS_TOPIC_BASE}/#")


def on_message(client, userdata, msg):
    field = msg.topic.rsplit("/", 1)[-1]
    if field not in state:
        return  # topic we don't understand yet -- ignore rather than guess
    try:
        value = float(msg.payload.decode())
    except ValueError:
        return
    with state_lock:
        state[field] = value


def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(client_id="rvtc-mqtt-gpsd-feeder")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


# ── pty setup ─────────────────────────────────────────────────────────────

def setup_pty() -> int:
    """Creates the pty pair, points PTY_SYMLINK at the slave side, and
    returns the master fd this script writes NMEA sentences to."""
    master_fd, slave_fd = pty.openpty()
    slave_path = os.ttyname(slave_fd)

    if os.path.islink(PTY_SYMLINK) or os.path.exists(PTY_SYMLINK):
        os.remove(PTY_SYMLINK)
    os.symlink(slave_path, PTY_SYMLINK)

    log.info(f"pty ready: {slave_path} -> symlinked at {PTY_SYMLINK}")
    log.info(f"point gpsd's DEVICES= at {PTY_SYMLINK}")
    return master_fd


# ── Main loop ─────────────────────────────────────────────────────────────

def run() -> None:
    make_mqtt_client()
    master_fd = setup_pty()

    while True:
        with state_lock:
            snapshot = dict(state)

        if snapshot["latitude"] is None or snapshot["longitude"] is None:
            log.info("no position yet -- waiting for rvtc/sensors/gps data")
            time.sleep(SEND_INTERVAL_SECONDS)
            continue

        sentences = build_gga(snapshot) + build_gll(snapshot) + build_vtg(snapshot)
        try:
            os.write(master_fd, sentences.encode("ascii"))
        except OSError as e:
            # Nothing has opened the slave end yet (gpsd not started/pointed
            # at it) -- harmless, just keep producing sentences for whenever
            # it does connect.
            log.debug(f"write to pty failed (no reader yet?): {e}")

        time.sleep(SEND_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("stopped")
