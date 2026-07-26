#!/usr/bin/env python3
"""
gps_mqtt.py — GPS bridge for RVTC's unified MQTT namespace.

Publishes to: rvtc/sensors/gps/{field}   (flat scalar payload per topic,
matching the rest of the fleet: rvtc/sensors/solar/pv_voltage, etc.)

Architecture note (deliberate departure from the other bridge scripts):
samlux_mqtt.py / epever_mqtt.py / kws_mqtt.py each poll their device's Modbus
gateway directly, because nothing else on the bus is already doing that job.
GPS is different: gpsd is already running on this host, already the sole
TCP client of the serial gateway at 192.168.88.10:4001, and already doing the
NMEA/UBX parsing, fix-quality arbitration, and device-activation retry logic
(see 2026-07-07 session — gpsd came up before the gateway was ready and just
needed a restart once the gateway was reachable). Opening a second raw
connection to 192.168.88.10:4001 from this script would create a second
competing client on a gateway that other RVTC bridges already treat as
single-consumer-only, and would throw away gpsd's fix arbitration for no
reason. So this script is a client of gpsd's own protocol (port 2947,
localhost) rather than a second poller of the raw device — consistent with
"HA is a data consumer, never a poller" (Section 1.4), just one layer up:
gpsd is the poller here, and this script is a consumer of gpsd.

Requires:
    sudo apt install python3-gps      # gpsd's own Python client bindings
    pip3 install paho-mqtt --break-system-packages
"""

import json
import logging
import time

import paho.mqtt.client as mqtt
from gps import gps, WATCH_ENABLE, WATCH_JSON

# ── Config ────────────────────────────────────────────────────────────────
GPSD_HOST = "localhost"
GPSD_PORT = 2947

MQTT_HOST = "192.168.88.3"   # RVTC unified Mosquitto broker, no auth (per 1.2/1.4)
MQTT_PORT = 1883
TOPIC_BASE = "rvtc/sensors/gps"
AVAILABILITY_TOPIC = f"{TOPIC_BASE}/availability"

MIN_PUBLISH_INTERVAL = 1.0  # seconds; gpsd streams ~1Hz, don't publish faster than that
GPSD_RETRY_SECONDS = 5       # how long to wait before retrying a dropped gpsd connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s gps_mqtt: %(message)s",
)
log = logging.getLogger("gps_mqtt")


# ── MQTT setup ────────────────────────────────────────────────────────────
def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(client_id="rvtc-gps-bridge")
    client.will_set(AVAILABILITY_TOPIC, payload="offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
    return client


def publish(client: mqtt.Client, field: str, value) -> None:
    if value is None:
        return
    client.publish(f"{TOPIC_BASE}/{field}", payload=value, retain=False)


# ── gpsd report handling ─────────────────────────────────────────────────
def handle_tpv(client: mqtt.Client, report) -> None:
    """TPV = Time-Position-Velocity report."""
    mode = getattr(report, "mode", 0)  # 0=unknown, 1=no fix, 2=2D, 3=3D
    publish(client, "fix_mode", mode)

    if mode < 2:
        # No usable fix yet — don't publish stale/garbage lat-lon.
        return

    publish(client, "latitude", getattr(report, "lat", None))
    publish(client, "longitude", getattr(report, "lon", None))
    publish(client, "altitude_m", getattr(report, "alt", None))
    publish(client, "time_utc", getattr(report, "time", None))

    speed_ms = getattr(report, "speed", None)
    if speed_ms is not None:
        publish(client, "speed_kmh", round(speed_ms * 3.6, 2))

    publish(client, "track_deg", getattr(report, "track", None))


def handle_sky(client: mqtt.Client, report) -> None:
    """SKY = satellite/DOP report."""
    publish(client, "hdop", getattr(report, "hdop", None))

    satellites = getattr(report, "satellites", None)
    if satellites is not None:
        used = sum(1 for sat in satellites if getattr(sat, "used", False))
        publish(client, "satellites_used", used)
        publish(client, "satellites_visible", len(satellites))


# ── Main loop ─────────────────────────────────────────────────────────────
def run() -> None:
    mqtt_client = make_mqtt_client()

    while True:
        try:
            log.info(f"Connecting to gpsd at {GPSD_HOST}:{GPSD_PORT}")
            session = gps(host=GPSD_HOST, port=GPSD_PORT)
            session.stream(WATCH_ENABLE | WATCH_JSON)
            log.info("Connected to gpsd, streaming reports")

            last_publish = 0.0
            for report in session:
                now = time.monotonic()
                report_class = getattr(report, "class", None)

                if report_class == "TPV":
                    if now - last_publish >= MIN_PUBLISH_INTERVAL:
                        handle_tpv(mqtt_client, report)
                        last_publish = now
                elif report_class == "SKY":
                    handle_sky(mqtt_client, report)

        except (ConnectionRefusedError, BrokenPipeError, OSError) as e:
            mqtt_client.publish(AVAILABILITY_TOPIC, payload="offline", retain=True)
            log.warning(f"Lost connection to gpsd ({e}); retrying in {GPSD_RETRY_SECONDS}s")
            time.sleep(GPSD_RETRY_SECONDS)
            mqtt_client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)

        except StopIteration:
            mqtt_client.publish(AVAILABILITY_TOPIC, payload="offline", retain=True)
            log.warning(f"gpsd stream ended; retrying in {GPSD_RETRY_SECONDS}s")
            time.sleep(GPSD_RETRY_SECONDS)
            mqtt_client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped")
