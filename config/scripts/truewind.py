# Copyright 2026, RVTC
"""
truewind.py — WeeWX service that corrects the WN90LP's trailer-relative
wind direction to true (compass) direction, using the WitMotion IMU's
live heading published over MQTT.

Why this is needed: WN90_mqtt.py's windDir is relative to however the
sensor is physically bolted to the trailer, not to true north. For a
fixed weather station you calibrate that alignment once at install and
it's good forever. For a trailer that moves, that one-time alignment
breaks every time you relocate -- windDirTrue = (windDirRelative +
imu_heading) % 360, and imu_heading has to be live and trustworthy for
this to mean anything. Confirmed 2026-08-01 this is genuinely needed
(WN90LP has no compass of its own that self-corrects for this).

Why here, in WeeWX, not in WN90_mqtt.py: matches the project's own stated
architecture principle -- corrections happen once, in the adaptor, before
the broker. WeeWX already plays exactly this role for weather data
(StdWXCalculate derives barometer/dewpoint/heatindex the same way, on the
same NEW_LOOP_PACKET event this service hooks). It also gets the
correction into InfluxDB/Grafana for free: user.mqtt.MQTT republishes
whatever's in the record with no [[[inputs]]] whitelist configured, so a
new packet field just flows straight through the existing pipeline with
zero changes needed to weewx.conf's [[MQTT]] block or mqtt.py itself.

Field naming: this OVERWRITES windDir in place with the true-north value
(matching how StdWXCalculate corrects fields in place, not alongside
parallel "corrected" copies) -- every existing Belchertown/Grafana view
already keyed on windDir starts showing true wind with no further changes
needed. The original relative value is preserved as windDirRelative
specifically so a future "why does this look wrong" question can tell a
bad IMU heading apart from bad raw sensor data.

Fails safe, not silent, and completely rather than partially: if the
IMU's own heading_needs_init flag is true, if no heading has ever been
received, or if the last update is older than HEADING_STALE_SECONDS
(imu_mqtt.py publishes at 2Hz -- a real gap this long means it's down),
windDir, windSpeed, AND windGust are ALL set to None for that packet --
not just left uncorrected. A trailer-relative windDir passed through
unmodified would look like a perfectly valid true-compass reading to
Wunderground/PWSWeather/CWOP/AWEKAS and any other external consumer; a
silently wrong number is worse than a visible gap. This service never
guesses a heading it isn't confident in, and never lets a correction it
can't vouch for reach anything downstream.

Install: this file goes in WeeWX's user/ extension directory
(/data/bin/user/ inside the container, /data/docker/volumes/weewx/bin/user/
on the host), and user.truewind.TrueWindService must be added to
weewx.conf's [Engine][[Services]] process_services list -- see
set_truewind_service.py for the scripted, idempotent version of that edit.

Rollback: remove user.truewind.TrueWindService from process_services and
restart the weewx container. windDir reverts to raw/relative immediately;
nothing else in this file touches any other part of WeeWX's config or data.
"""

import logging
import threading
import time

import weewx
from weewx.engine import StdService

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
HEADING_TOPIC = "rvtc/sensors/imu/heading"
NEEDS_INIT_TOPIC = "rvtc/sensors/imu/heading_needs_init"

# imu_mqtt.py publishes at 2 Hz -- a real gap this long means the bridge
# itself is down, not just normal jitter between packets.
HEADING_STALE_SECONDS = 30


class TrueWindService(StdService):
    def __init__(self, engine, config_dict):
        super(TrueWindService, self).__init__(engine, config_dict)

        self._lock = threading.Lock()
        self._heading = None
        self._heading_needs_init = True   # fail toward "don't trust" until told otherwise
        self._last_heading_update = None

        self._mqtt_client = mqtt.Client(
            client_id="weewx-truewind",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        try:
            self._mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            self._mqtt_client.loop_start()
        except OSError as e:
            # Don't let a broker hiccup at WeeWX startup crash the engine --
            # log it and keep going uncorrected (new_loop_packet's own
            # staleness check will keep windDir passed-through as-is until
            # a connection eventually succeeds, if ever).
            log.warning("TrueWindService: initial MQTT connect failed (%s); "
                        "will retry via paho's own reconnect logic", e)

        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)
        log.info("TrueWindService initialized, subscribing to %s", HEADING_TOPIC)

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties=None):
        if reason_code != 0:
            log.warning("TrueWindService MQTT connect failed: %s", reason_code)
            return
        client.subscribe(HEADING_TOPIC)
        client.subscribe(NEEDS_INIT_TOPIC)
        log.info("TrueWindService subscribed to %s and %s", HEADING_TOPIC, NEEDS_INIT_TOPIC)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        with self._lock:
            if msg.topic == HEADING_TOPIC:
                try:
                    self._heading = float(payload)
                    self._last_heading_update = time.monotonic()
                except ValueError:
                    pass
            elif msg.topic == NEEDS_INIT_TOPIC:
                self._heading_needs_init = payload.lower() in ("true", "1")

    def new_loop_packet(self, event):
        packet = event.packet
        wind_dir_relative = packet.get('windDir')
        if wind_dir_relative is None:
            return   # no wind reading this packet at all -- nothing to correct or suppress

        with self._lock:
            heading = self._heading
            needs_init = self._heading_needs_init
            last_update = self._last_heading_update

        reason = None
        if heading is None:
            reason = "no IMU heading received yet"
        elif needs_init:
            reason = "IMU flagged needs_init"
        elif last_update is None or (time.monotonic() - last_update) > HEADING_STALE_SECONDS:
            reason = f"IMU heading stale (>{HEADING_STALE_SECONDS}s)"

        if reason is not None:
            # Fail safe means ALL wind data stops, not just direction --
            # left uncorrected, windDir would look like a perfectly valid
            # true-compass reading to Wunderground/PWSWeather/CWOP/AWEKAS
            # and every other external consumer. A silently wrong number
            # is worse than a visible gap. Suppress the whole wind picture
            # together (direction, speed, gust) rather than half of it,
            # since a direction-less speed reading is just as misleading
            # to anything correlating the two.
            packet['windDir'] = None
            packet['windSpeed'] = None
            packet['windGust'] = None
            log.warning("TrueWindService: %s -- suppressing all wind data this packet", reason)
            return

        packet['windDirRelative'] = wind_dir_relative
        packet['windDir'] = (wind_dir_relative + heading) % 360.0

    def shutDown(self):
        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        except Exception:
            pass
