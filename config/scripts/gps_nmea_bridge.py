#!/usr/bin/env python3
"""
gps_nmea_bridge.py — republishes RVTC's MQTT GPS data as standard NMEA 0183
sentences ($GPRMC / $GPGGA) on the HF5142B serial gateway, for an attached
APRS tracker/radio.

This runs the opposite direction from every other RVTC bridge script:
those go sensor -> Modbus -> MQTT. This one goes MQTT -> NMEA text -> serial
gateway -> APRS hardware. Source data comes entirely from imu_mqtt.py's
rvtc/sensors/gps/* topics (WitMotion WTGAHRS3-485 on 485-4) -- see that
script and RVTC_System_Reference.md Section 3/7 for where those numbers
originate and their caveats (fix_ok is a heuristic, not a real fix-valid
bit; utc_time is derived by subtracting the module's own TIMEZONE register
offset from its on-chip local-time block, confirmed 2026-07-30).

Gateway port:
    serial-1 on the HF5142B, 192.168.88.13:4001 (per System Reference
    Section 3 -- nothing else was plugged into any of serial-1..4 at time
    of writing, so this starts there. Trivial to move: change GATEWAY_HOST
    below to serial-2/3/4's IP if serial-1 is ever needed for something
    else -- no other logic depends on which port this is.

Connection model:
    Unlike the Waveshare Modbus gateways (fresh connection per poll,
    because pymodbus-style persistent connections get dropped idle -- see
    System Reference Section 8), the HF5142B does raw serial pass-through,
    not Modbus. This script holds ONE persistent TCP connection and streams
    sentences continuously, since that's the natural shape for a live NMEA
    feed. Reconnects with backoff on any socket failure. If this gateway
    turns out to also drop idle connections, that would show up as
    reconnect-loop log spam -- watch for that early on.

Gateway-side config (NOT controlled by this script):
    serial-1's baud rate / parity / stop bits must be set via the HF5142B's
    own web UI to match whatever the APRS radio/TNC expects on its NMEA
    input -- commonly 4800 baud, 8N1, but check the radio's manual. This
    script only controls what bytes go over the TCP socket; the gateway
    is responsible for turning that into physical serial output at the
    configured line settings.

Sentences emitted, once per OUTPUT_INTERVAL_SECONDS:
    $GPRMC,hhmmss.sss,A|V,ddmm.mmmm,N|S,dddmm.mmmm,E|W,speed_kn,course,ddmmyy,,,*CS
    $GPGGA,hhmmss.sss,ddmm.mmmm,N|S,dddmm.mmmm,E|W,fixq,numsats,hdop,alt,M,,,,*CS

    Status/fix-quality logic: if the GPS data feeding this hasn't been
    updated within STALE_AFTER_SECONDS, or fix_ok is currently false,
    sentences still go out on schedule (so a listener can tell the bridge
    itself is alive) but marked void ('V') / fix quality 0 rather than
    replaying old coordinates as if they were a current fix. Geoid
    separation is left blank in GGA -- the WitMotion register map doesn't
    document a geoid-separation field to source it from, so this doesn't
    invent one.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import logging
import socket
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────────────────────────────
MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
GPS_TOPIC_BASE = "rvtc/sensors/gps"
IMU_AVAILABILITY_TOPIC = "rvtc/sensors/imu/availability"

GATEWAY_HOST = "192.168.88.13"   # serial-1 on the HF5142B -- see docstring
GATEWAY_PORT = 4001

OUTPUT_INTERVAL_SECONDS = 1.0     # standard NMEA/APRS cadence
STALE_AFTER_SECONDS = 5.0         # no update within this long -> void/invalid
SOCKET_CONNECT_TIMEOUT = 3.0
RECONNECT_BACKOFF_SECONDS = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s gps_nmea_bridge: %(message)s",
)
log = logging.getLogger("gps_nmea_bridge")


# ── Shared state, updated by MQTT callbacks, read by the output thread ──
_state_lock = threading.Lock()
_state = {
    "latitude": None,
    "longitude": None,
    "altitude_m": None,
    "course_deg": None,
    "speed_kmh": None,
    "utc_time": None,       # "YYYY-MM-DD HH:MM:SS.mmm"
    "fix_ok": False,
    "satellites_used": None,
    "hdop": None,
    "imu_available": False,
}
_last_updated = {}   # field name -> time.monotonic() of last MQTT update


def _set_state(field: str, value) -> None:
    with _state_lock:
        _state[field] = value
        _last_updated[field] = time.monotonic()


def _get_state_snapshot() -> dict:
    with _state_lock:
        return dict(_state), dict(_last_updated)


# ── NMEA formatting helpers ───────────────────────────────────────────────

def nmea_checksum(sentence_body: str) -> str:
    """sentence_body is everything between '$' and '*', exclusive."""
    cksum = 0
    for ch in sentence_body:
        cksum ^= ord(ch)
    return f"{cksum:02X}"


def to_nmea_lat(lat: float) -> tuple[str, str]:
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:07.4f}", hemi


def to_nmea_lon(lon: float) -> tuple[str, str]:
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:07.4f}", hemi


def parse_utc(utc_str: str):
    """Returns a datetime or None if utc_str is missing/malformed."""
    if not utc_str:
        return None
    try:
        return datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def build_sentences(state: dict, data_is_fresh: bool) -> list[str]:
    """Returns a list of complete NMEA sentence strings (with checksum and
    trailing CRLF), or [] if there isn't enough data yet to say anything
    meaningful (e.g. nothing received since startup)."""
    utc_dt = parse_utc(state.get("utc_time"))
    lat = state.get("latitude")
    lon = state.get("longitude")

    if utc_dt is None or lat is None or lon is None:
        return []   # nothing sensible to send yet

    valid = bool(data_is_fresh and state.get("fix_ok"))
    status_char = "A" if valid else "V"
    fix_quality = "1" if valid else "0"

    hhmmss = utc_dt.strftime("%H%M%S") + f".{utc_dt.microsecond // 1000:03d}"
    ddmmyy = utc_dt.strftime("%d%m%y")

    lat_str, lat_hemi = to_nmea_lat(lat)
    lon_str, lon_hemi = to_nmea_lon(lon)

    speed_kmh = state.get("speed_kmh") or 0.0
    speed_kn = speed_kmh / 1.852
    course = state.get("course_deg") or 0.0

    rmc_body = (
        f"GPRMC,{hhmmss},{status_char},{lat_str},{lat_hemi},"
        f"{lon_str},{lon_hemi},{speed_kn:.1f},{course:.1f},{ddmmyy},,,"
    )
    rmc = f"${rmc_body}*{nmea_checksum(rmc_body)}\r\n"

    numsats = state.get("satellites_used")
    hdop = state.get("hdop")
    altitude_m = state.get("altitude_m")
    numsats_str = f"{numsats:02d}" if numsats is not None else "00"
    hdop_str = f"{hdop:.1f}" if hdop is not None else ""
    alt_str = f"{altitude_m:.1f}" if altitude_m is not None else ""

    gga_body = (
        f"GPGGA,{hhmmss},{lat_str},{lat_hemi},{lon_str},{lon_hemi},"
        f"{fix_quality},{numsats_str},{hdop_str},{alt_str},M,,,,"
    )
    gga = f"${gga_body}*{nmea_checksum(gga_body)}\r\n"

    return [rmc, gga]


# ── MQTT ──────────────────────────────────────────────────────────────────

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    if reason_code != 0:
        log.warning(f"MQTT connect failed: {reason_code}")
        return
    client.subscribe(f"{GPS_TOPIC_BASE}/#")
    client.subscribe(IMU_AVAILABILITY_TOPIC)
    log.info("Subscribed to GPS topics")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    topic = msg.topic

    if topic == IMU_AVAILABILITY_TOPIC:
        _set_state("imu_available", payload == "online")
        return

    field = topic.rsplit("/", 1)[-1]
    if field not in _state:
        return   # not one of the fields we care about

    if field == "utc_time":
        _set_state(field, payload if payload != "None" else None)
    elif field == "fix_ok":
        _set_state(field, payload.strip().lower() in ("true", "1"))
    elif field in ("satellites_used",):
        try:
            _set_state(field, int(payload))
        except ValueError:
            pass
    else:
        try:
            _set_state(field, float(payload))
        except ValueError:
            pass


def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id="rvtc-gps-nmea-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


# ── Serial gateway output ─────────────────────────────────────────────────

def output_loop() -> None:
    sock = None
    while True:
        if sock is None:
            try:
                sock = socket.create_connection(
                    (GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_CONNECT_TIMEOUT
                )
                sock.settimeout(SOCKET_CONNECT_TIMEOUT)
                log.info(f"Connected to serial gateway {GATEWAY_HOST}:{GATEWAY_PORT}")
            except OSError as e:
                log.warning(
                    f"Couldn't connect to {GATEWAY_HOST}:{GATEWAY_PORT} ({e}); "
                    f"retrying in {RECONNECT_BACKOFF_SECONDS}s"
                )
                time.sleep(RECONNECT_BACKOFF_SECONDS)
                continue

        state, last_updated = _get_state_snapshot()
        now = time.monotonic()
        critical_fields = ("latitude", "longitude", "utc_time", "fix_ok")
        data_is_fresh = all(
            field in last_updated and (now - last_updated[field]) <= STALE_AFTER_SECONDS
            for field in critical_fields
        )

        sentences = build_sentences(state, data_is_fresh)
        if sentences:
            try:
                for sentence in sentences:
                    sock.sendall(sentence.encode("ascii"))
            except OSError as e:
                log.warning(f"Write to serial gateway failed ({e}); reconnecting")
                try:
                    sock.close()
                except OSError:
                    pass
                sock = None
                continue
        else:
            log.debug("No GPS data yet -- skipping this cycle")

        time.sleep(OUTPUT_INTERVAL_SECONDS)


def main() -> None:
    make_mqtt_client()
    output_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped")
