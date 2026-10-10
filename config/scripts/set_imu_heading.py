#!/usr/bin/env python3
"""
set_imu_heading.py — establishes the WitMotion's heading offset (HW-27).

Why this exists: the WitMotion has no "set heading to X" register. Its only
heading-related calibration command (CALSW = 0x04) zeroes the CURRENT
physical orientation to 0 -- not useful for a trailer you can't re-point to
face a specific direction. So instead of a device-side calibration, this
script establishes a software offset: it reads the unit's current heading
right now, compares it to the true heading you tell it the vehicle is
actually facing, and stores the difference. imu_mqtt.py applies that offset
to every subsequent Yaw reading before publishing.

CHANGED 2026-08-18: switched from a direct Modbus read on the 485-4 gateway
to reading imu_mqtt.py's published MQTT topics instead
(rvtc/sensors/imu/heading, rvtc/sensors/gps/latitude,
rvtc/sensors/gps/longitude). Reasoning: imu_mqtt.py polls that gateway
continuously at 2Hz, and as of the APRS-related additions does 7 separate
Modbus transactions per poll cycle -- a much bigger window than before for
another script's independent connection to land mid-transaction. This
script and auto_recalibrate_imu_heading.py were both opening their own
direct connections to the same gateway, which the Waveshare unit doesn't
arbitrate between. Confirmed live 2026-08-18: the daily auto-recalibrate
timer collided with a manual run of this script, producing a garbled
"expected 22 got 7"-style response -- not a wiring or device fault, just
two masters talking over each other. This also matches the project's own
architecture rule (System Reference Section 1): imu_mqtt.py is the sole
adaptor for this device, nothing else should talk to the gateway directly.
imu_gps_heading_autoset.py already established this MQTT-based pattern;
this script and auto_recalibrate_imu_heading.py now follow it too.

Since MQTT 'heading' is already offset-corrected (not raw Yaw), the raw
Yaw needed to compute a new offset is recovered as:
    raw_yaw = (mqtt_heading - current_offset_deg) % 360
using the offset currently on record in imu_heading_state.json -- the same
derivation imu_gps_heading_autoset.py already uses, just run in the other
direction (that script goes offset -> new offset from a GPS course sample;
this one goes offset -> raw Yaw from a human-confirmed compass heading).

Usage:
    ./set_imu_heading.py 137
        (137 = the vehicle's current true heading in degrees, 0-360,
        read off a phone compass, a road's known bearing, a chart, etc.)

Requires imu_mqtt.py to be running and publishing fresh values on the
broker -- this script waits up to MQTT_WAIT_SECONDS for a heading + GPS
position sample and fails rather than guessing if nothing fresh arrives.

This clears the "needs_init" flag that gets set at every host boot (see
imu_needs_init_on_boot.service) -- a reasonable but imperfect proxy for the
IMU itself having lost power, since they're expected to share a 12V supply.
Not foolproof: if the IMU is ever on a separately switched circuit from the
J45, this boot-flag heuristic won't catch an IMU-only power cycle. Flagging
that honestly rather than pretending the detection is airtight.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import json
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Config -- must match imu_mqtt.py's publish side ──────────────────────
MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
IMU_TOPIC_BASE = "rvtc/sensors/imu"
GPS_TOPIC_BASE = "rvtc/sensors/gps"

STATE_FILE = "/home/ve7cbh/RV-total-control/config/scripts/imu_heading_state.json"

MQTT_WAIT_SECONDS = 10   # how long to wait for a fresh heading + position
                          # sample before giving up rather than guessing

REQUIRED_FIELDS = ("heading", "latitude", "longitude")

_lock = threading.Lock()
_cache = {f: None for f in REQUIRED_FIELDS}


# ── MQTT plumbing ─────────────────────────────────────────────────────────

def _on_connect(client, userdata, connect_flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"MQTT connect failed: {reason_code}")
        return
    client.subscribe(f"{IMU_TOPIC_BASE}/heading")
    client.subscribe(f"{GPS_TOPIC_BASE}/latitude")
    client.subscribe(f"{GPS_TOPIC_BASE}/longitude")


def _on_message(client, userdata, msg):
    field = msg.topic.rsplit("/", 1)[-1]
    if field not in REQUIRED_FIELDS:
        return
    try:
        value = float(msg.payload.decode("utf-8", errors="replace"))
    except ValueError:
        return
    with _lock:
        _cache[field] = value


def _wait_for_sample(timeout: float) -> dict:
    """Blocks until heading + latitude + longitude have all arrived at
    least once, or timeout elapses. Returns a copy of the cache (any
    field may still be None if we timed out)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if all(_cache[f] is not None for f in REQUIRED_FIELDS):
                return dict(_cache)
        time.sleep(0.1)
    with _lock:
        return dict(_cache)


def _read_current_offset() -> float:
    try:
        with open(STATE_FILE) as f:
            return float(json.load(f).get("offset_deg", 0.0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0.0


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: set_imu_heading.py <current_true_heading_degrees>")
        return 1

    try:
        true_heading = float(sys.argv[1]) % 360
    except ValueError:
        print(f"'{sys.argv[1]}' isn't a number")
        return 1

    client = mqtt.Client(
        client_id="rvtc-set-imu-heading",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = _on_connect
    client.on_message = _on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
    except OSError as e:
        print(f"Couldn't connect to MQTT broker at {MQTT_HOST}:{MQTT_PORT}: {e}")
        return 1

    client.loop_start()
    sample = _wait_for_sample(MQTT_WAIT_SECONDS)
    client.loop_stop()
    client.disconnect()

    missing = [f for f in REQUIRED_FIELDS if sample[f] is None]
    if missing:
        print(f"Didn't get fresh {', '.join(missing)} from MQTT within {MQTT_WAIT_SECONDS}s.")
        print("Is imu_mqtt.py running? (systemctl status imu_mqtt)")
        return 1

    current_offset = _read_current_offset()
    # MQTT 'heading' is already offset-corrected -- recover raw Yaw so the
    # new offset is computed the same way the old direct-read version did.
    raw_yaw_deg = (sample["heading"] - current_offset) % 360
    offset_deg = (true_heading - raw_yaw_deg) % 360

    state = {
        "needs_init": False,
        "offset_deg": round(offset_deg, 2),
        "raw_yaw_at_set": round(raw_yaw_deg, 2),
        "true_heading_at_set": round(true_heading, 2),
        "latitude_at_set": round(sample["latitude"], 6),
        "longitude_at_set": round(sample["longitude"], 6),
        "set_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    }

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Raw Yaw right now:     {raw_yaw_deg:.2f}°")
    print(f"Set as true heading:   {true_heading:.2f}°")
    print(f"Offset stored:         {offset_deg:.2f}°")
    print(f"Position recorded:     {sample['latitude']:.6f}, {sample['longitude']:.6f}")
    print(f"needs_init cleared. State written to {STATE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
