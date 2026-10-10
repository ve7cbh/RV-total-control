#!/usr/bin/env python3
"""
gps_nmea_geoclue.py

RVTC adaptor: Mosquitto (rvtc/sensors/gps/#) -> NMEA-0183 -> Unix socket
for GeoClue2's [network-nmea] source (nmea-socket=/run/gps-share.sock).

Pattern match with gps_nmea_bridge.py (MQTT -> NMEA -> APRS serial):
same broker topic, same sentence types ($GPGGA/$GPRMC), same
reconnect-on-failure philosophy. This script is a second, independent
consumer of the same broker topic -- it does not touch or depend on
gps_nmea_bridge.py in any way, consistent with "subscribers read; they
don't get a private pipe from any sensor" (Section 1 of the RVTC
System Reference).

Fail-safe behaviour (matches imu_mqtt.py / TrueWindService convention):
if the GPS feed goes stale (>STALE_SECONDS since last message) or
fix_ok is false, sentences are still emitted (GeoClue expects a steady
stream) but marked with fix quality 0 / status V, never a stale fix
presented as current.
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ---- Configuration -----------------------------------------------------
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "rvtc/sensors/gps/#"

SOCKET_PATH = "/run/gps-share/gps-share.sock"  # inside the RuntimeDirectory
                                                 # systemd creates for this
                                                 # service (see .service file)
                                                 # -- ve7cbh can't write
                                                 # directly at /run/ top level
SOCKET_PERMS = 0o666  # local-only IPC on a single-user trusted host; no
                       # need for tighter perms on a machine with no
                       # other untrusted local users

SENTENCE_HZ = 1.0
STALE_SECONDS = 30  # matches the imu_mqtt.py 2Hz/"gap >30s means it's
                     # down" convention used elsewhere in RVTC

RECONNECT_DELAY = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("gps_nmea_geoclue")

# ---- Shared GPS state ----------------------------------------------------
state_lock = threading.Lock()
state = {
    "latitude": None,
    "longitude": None,
    "altitude_m": None,
    "speed_kmh": None,
    "course_deg": None,
    "satellites_used": None,
    "hdop": None,
    "fix_ok": False,
    "utc_time": None,
    "last_update": 0.0,
}


def nmea_checksum(sentence_body: str) -> str:
    """XOR checksum of everything between '$' and '*', as two hex digits."""
    cs = 0
    for ch in sentence_body:
        cs ^= ord(ch)
    return f"{cs:02X}"


def to_nmea_lat(lat: float) -> tuple:
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:07.4f}", hemi


def to_nmea_lon(lon: float) -> tuple:
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:07.4f}", hemi


def parse_utc(utc_time_str):
    """RVTC publishes utc_time like '2026-09-15 19:22:14.204'."""
    try:
        return datetime.strptime(utc_time_str, "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


def build_sentences(s: dict) -> list:
    """Build $GPGGA and $GPRMC from current state. Always returns two
    sentences -- with fix quality 0 / status V if data is stale or
    fix_ok is false, never a stale fix presented as current."""
    now = time.time()
    fresh = (now - s["last_update"]) <= STALE_SECONDS
    have_fix = bool(s["fix_ok"]) and fresh and s["latitude"] is not None

    dt = parse_utc(s["utc_time"]) if s["utc_time"] else None
    if dt is None:
        dt = datetime.now(timezone.utc)
    hhmmss = dt.strftime("%H%M%S.") + f"{dt.microsecond // 10000:02d}"
    ddmmyy = dt.strftime("%d%m%y")

    if have_fix:
        lat_str, lat_hemi = to_nmea_lat(s["latitude"])
        lon_str, lon_hemi = to_nmea_lon(s["longitude"])
        fix_quality = "1"
        sats = f"{int(s['satellites_used']):02d}" if s["satellites_used"] is not None else ""
        hdop = f"{s['hdop']:.1f}" if s["hdop"] is not None else ""
        alt = f"{s['altitude_m']:.1f}" if s["altitude_m"] is not None else ""
        speed_knots = f"{s['speed_kmh'] * 0.539957:.1f}" if s["speed_kmh"] is not None else "0.0"
        course = f"{s['course_deg']:.1f}" if s["course_deg"] is not None else "0.0"
        status = "A"
    else:
        lat_str, lat_hemi = "0000.0000", "N"
        lon_str, lon_hemi = "00000.0000", "E"
        fix_quality = "0"
        sats = "00"
        hdop = ""
        alt = ""
        speed_knots = "0.0"
        course = "0.0"
        status = "V"

    gga_body = (
        f"GPGGA,{hhmmss},{lat_str},{lat_hemi},{lon_str},{lon_hemi},"
        f"{fix_quality},{sats},{hdop},{alt},M,0.0,M,,"
    )
    rmc_body = (
        f"GPRMC,{hhmmss},{status},{lat_str},{lat_hemi},{lon_str},{lon_hemi},"
        f"{speed_knots},{course},{ddmmyy},,,"
    )

    gga = f"${gga_body}*{nmea_checksum(gga_body)}\r\n"
    rmc = f"${rmc_body}*{nmea_checksum(rmc_body)}\r\n"
    return [gga, rmc]


# ---- MQTT side -------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to mosquitto at %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe(MQTT_TOPIC)
    else:
        log.error("MQTT connect failed, rc=%s", rc)


def on_message(client, userdata, msg):
    field = msg.topic.rsplit("/", 1)[-1]
    payload = msg.payload.decode("utf-8", errors="replace").strip()

    with state_lock:
        try:
            if field == "latitude":
                state["latitude"] = float(payload)
            elif field == "longitude":
                state["longitude"] = float(payload)
            elif field == "altitude_m":
                state["altitude_m"] = float(payload)
            elif field == "speed_kmh":
                state["speed_kmh"] = float(payload)
            elif field == "course_deg":
                state["course_deg"] = float(payload)
            elif field == "satellites_used":
                state["satellites_used"] = int(payload)
            elif field == "hdop":
                state["hdop"] = float(payload)
            elif field == "fix_ok":
                state["fix_ok"] = payload.strip().lower() == "true"
            elif field == "utc_time":
                state["utc_time"] = payload
            else:
                return  # ignore fields we don't care about (chip_local_time, etc.)
        except ValueError:
            log.warning("Could not parse %s=%r", field, payload)
            return

        state["last_update"] = time.time()


def mqtt_thread():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            client.loop_forever()
        except Exception as exc:
            log.warning("MQTT connection lost/failed (%s), retrying in %ss", exc, RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)


# ---- Unix socket side -------------------------------------------------------
def handle_client(conn: socket.socket, addr):
    log.info("GeoClue connected on %s", SOCKET_PATH)
    period = 1.0 / SENTENCE_HZ
    try:
        while True:
            with state_lock:
                s = dict(state)
            for sentence in build_sentences(s):
                conn.sendall(sentence.encode("ascii"))
            time.sleep(period)
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        conn.close()
        log.info("GeoClue disconnected")


def socket_server_thread():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, SOCKET_PERMS)
    srv.listen(4)
    log.info("Listening for GeoClue on %s", SOCKET_PATH)

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    finally:
        srv.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)


def main():
    t_mqtt = threading.Thread(target=mqtt_thread, daemon=True)
    t_mqtt.start()

    # Socket server runs on the main thread so a fatal bind error
    # surfaces immediately and systemd sees a real non-zero exit.
    socket_server_thread()


if __name__ == "__main__":
    main()
