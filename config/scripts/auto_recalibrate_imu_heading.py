#!/usr/bin/env python3
"""
auto_recalibrate_imu_heading.py — corrects day-to-day heading drift
(gyro/magnetometer, temperature-dependent) while the trailer is confirmed
stationary, without needing a human to re-read a compass every day.

Safety model, the whole point of this script: it NEVER invents a heading.
It only ever re-applies the same true_heading_at_set value a human already
confirmed via set_imu_heading.py -- and only if GPS shows the trailer
hasn't moved since that calibration. If position can't be confirmed
unchanged (moved, no prior position on record, or a bad/missing GPS fix
right now), this script does nothing and marks needs_init -- it does NOT
guess, and does NOT blindly reapply a heading that might now be wrong.

MOVE_THRESHOLD_KM is deliberately much tighter than
update_weewx_station_location.py's 5km -- that script only cares "which
town's forecast to show," this one cares "has the vehicle's orientation
possibly changed," which movement of even a few dozen metres (repositioned
within a campsite, backed up, turned around) could invalidate.

CHANGED 2026-08-18: switched from a direct Modbus read on the 485-4 gateway
to reading imu_mqtt.py's published MQTT topics instead. This script runs
unattended off a systemd timer (daily, plus ~10 minutes after every boot),
so it can fire at any time -- including while imu_mqtt.py is mid-poll.
imu_mqtt.py now does 7 separate Modbus transactions per 0.5s poll cycle
(APRS-related fields added since this script was first written), which
gives a second, independent connection to the same gateway a much bigger
window to land mid-transaction and get a garbled response. Confirmed live
2026-08-18: this script's daily timer collided with a manual
set_imu_heading.py run, producing exactly that failure. Matches the
project's architecture rule (System Reference Section 1) that imu_mqtt.py
is the sole adaptor for this device -- imu_gps_heading_autoset.py already
established the MQTT-based pattern this script now follows too.

Since MQTT 'heading' is already offset-corrected (not raw Yaw), the raw
Yaw needed to re-derive the offset is recovered as:
    raw_yaw = (mqtt_heading - current_offset_deg) % 360
using the offset currently on record in imu_heading_state.json -- same
derivation set_imu_heading.py uses.

Intended to run daily via a systemd timer, only while parked.

Usage:
    python3 auto_recalibrate_imu_heading.py
"""

import json
import math
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
IMU_TOPIC_BASE = "rvtc/sensors/imu"
GPS_TOPIC_BASE = "rvtc/sensors/gps"

STATE_FILE = "/home/ve7cbh/RV-total-control/config/scripts/imu_heading_state.json"

# Much tighter than the 5km used for the weewx.conf/forecast location
# updater -- heading validity cares about metres, not "which town."
MOVE_THRESHOLD_KM = 0.1  # 100 metres

MQTT_WAIT_SECONDS = 10   # how long to wait for a fresh heading + position
                          # sample before giving up rather than guessing

REQUIRED_FIELDS = ("heading", "latitude", "longitude")

_lock = threading.Lock()
_cache = {f: None for f in REQUIRED_FIELDS}


# ── MQTT plumbing -- same pattern as set_imu_heading.py ──────────────────

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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if all(_cache[f] is not None for f in REQUIRED_FIELDS):
                return dict(_cache)
        time.sleep(0.1)
    with _lock:
        return dict(_cache)


def get_current_sample(timeout: float = MQTT_WAIT_SECONDS) -> dict:
    """Connects, waits for a fresh heading + GPS position sample, then
    disconnects. Returns the sample dict (fields may be None on timeout)."""
    client = mqtt.Client(
        client_id="rvtc-auto-recalibrate-imu",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
    client.loop_start()
    sample = _wait_for_sample(timeout)
    client.loop_stop()
    client.disconnect()
    return sample


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main() -> int:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Couldn't read {STATE_FILE}: {e} -- nothing to recalibrate against, doing nothing.")
        return 1

    true_heading = state.get("true_heading_at_set")
    last_lat = state.get("latitude_at_set")
    last_lon = state.get("longitude_at_set")
    current_offset = float(state.get("offset_deg", 0.0))

    if true_heading is None:
        print("No true_heading_at_set on record -- run set_imu_heading.py manually first.")
        return 1
    if last_lat is None or last_lon is None:
        print("No position on record for the last calibration (it predates position-capture,")
        print("or GPS failed at set-time) -- can't confirm 'hasn't moved.'")
        print("Doing nothing. Run set_imu_heading.py manually once to establish a baseline.")
        return 1

    try:
        sample = get_current_sample()
    except OSError as e:
        print(f"Couldn't connect to MQTT broker at {MQTT_HOST}:{MQTT_PORT}: {e}")
        return 1

    missing = [f for f in REQUIRED_FIELDS if sample[f] is None]
    if missing:
        print(f"Didn't get fresh {', '.join(missing)} from MQTT within {MQTT_WAIT_SECONDS}s.")
        print("Is imu_mqtt.py running? (systemctl status imu_mqtt) -- can't confirm position")
        print("or read a current heading, doing nothing.")
        return 1

    cur_lat, cur_lon = sample["latitude"], sample["longitude"]

    dist = haversine_km(last_lat, last_lon, cur_lat, cur_lon)
    if dist >= MOVE_THRESHOLD_KM:
        print(f"Moved {dist * 1000:.0f}m since last calibration (threshold {MOVE_THRESHOLD_KM * 1000:.0f}m) --")
        print("heading may no longer be valid. NOT auto-recalibrating.")
        state["needs_init"] = True
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print("Marked needs_init=True. Run set_imu_heading.py manually with the current true heading.")
        return 0

    print(f"Moved {dist * 1000:.1f}m since last calibration -- within {MOVE_THRESHOLD_KM * 1000:.0f}m threshold, safe to recalibrate.")

    # MQTT 'heading' is already offset-corrected -- recover raw Yaw the same
    # way set_imu_heading.py does, so the drift-corrected offset below is
    # computed on an apples-to-apples basis with a manual calibration.
    raw_yaw_deg = (sample["heading"] - current_offset) % 360
    offset_deg = (true_heading - raw_yaw_deg) % 360

    state.update({
        "needs_init": False,
        "offset_deg": round(offset_deg, 2),
        "raw_yaw_at_set": round(raw_yaw_deg, 2),
        # true_heading_at_set, latitude_at_set, longitude_at_set intentionally
        # left as-is -- they still describe the human-confirmed ground truth
        # this recalibration is anchored to, not this script's own read.
        "recalibrated_utc": datetime.now(timezone.utc).isoformat(),
    })

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Raw Yaw right now:  {raw_yaw_deg:.2f}°")
    print(f"Re-anchored to:     {true_heading:.2f}° (unchanged, from last manual calibration)")
    print(f"New offset stored:  {offset_deg:.2f}°")
    return 0


if __name__ == "__main__":
    sys.exit(main())
