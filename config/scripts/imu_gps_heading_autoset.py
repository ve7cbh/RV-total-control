#!/usr/bin/env python3
"""
imu_gps_heading_autoset.py — automatically re-anchors the IMU heading
offset using GPS course-over-ground once you're moving at real driving
speed, so a fresh, GPS-backed baseline is ready the moment you stop --
no manual set_imu_heading.sh call needed after a road-trip move.

Why this exists: auto_recalibrate_imu_heading.py corrects DRIFT around an
EXISTING baseline, but deliberately refuses to create a NEW one after a
real move -- it just sets needs_init and stops (see that script's
docstring). This script is the other half: it watches GPS speed/course
while driving and commits a new baseline the moment you arrive, closing
the gap Steve identified 2026-08-01 -- "good enough for wind correction"
is the explicit bar here, not precision. If more accuracy is ever needed
than GPS course-over-ground provides, running set_imu_heading.sh by hand
with a real compass reading still works exactly as before and simply
overwrites whatever this script last committed.

CHANGED 2026-08-01, before ever running successfully: the first version of
this script polled the WitMotion's Modbus registers directly, on the same
gateway (485-4) imu_mqtt.py already continuously polls at 2Hz. RS-485 is
half-duplex and the Waveshare gateway doesn't arbitrate between multiple
TCP clients -- two independent pollers produced exactly what you'd expect:
garbled byte counts, CRC mismatches, timeouts (confirmed live, first
deploy). Rewritten to subscribe to MQTT instead -- imu_mqtt.py already
publishes everything needed (heading, gps/course_deg, gps/speed_kmh,
gps/latitude, gps/longitude, gps/fix_ok) at 2Hz. This also fits the
project's own stated architecture better: one adaptor per sensor, nothing
else talks to the device directly.

One consequence of using MQTT 'heading' instead of raw Yaw: 'heading' is
already offset-corrected by whatever offset was active when imu_mqtt.py
published it. To capture a GPS-derived sample that's still meaningful
after the offset changes, this script also reads the CURRENT offset_deg
from imu_heading_state.json (best-effort at time of commit) and derives
the new offset as: new_offset = old_offset + (gps_course_at_capture -
heading_at_capture). If the offset changed between capture and commit
(e.g. the daily drift-recalibrator fired in that exact window), this
could be off by whatever that change was -- an acceptable, very unlikely
edge case given the "ballpark" goal.

Why GPS course, not a single instantaneous sample: course-over-ground is
only meaningful with a real velocity vector behind it -- noisy or
meaningless near a standstill. This script only trusts samples taken
while genuinely underway (>= MOVING_THRESHOLD_KMH) with gps_fix_ok true,
always keeps the LATEST such sample (not an average), and only commits
once stopped continuously for STOP_DWELL_SECONDS -- long enough to
distinguish "arrived" from "stopped at a light."

CHANGED 2026-08-18 -- turn-after-last-sample safety check added.
Reproduced live: departed home base at a correct 056.7°, arrived at a new
campsite reading 322° instead of the actual ~5.1° parked orientation
(confirmed by manual compass calibration). Root cause: the access road's
speed limit (10 km/h in this case) never gets back above
MOVING_THRESHOLD_KMH, so the "last good sample" this script had to work
with was captured out on the highway, before the turn onto the access
road -- and possibly before further turns/maneuvering into the site
itself. The original "assumes travelling straight forward" limitation
(see below) wasn't a rare edge case, it's the normal shape of arriving
anywhere with a slow entrance road.

Fix: the IMU's own `heading` topic is already being read every cycle
regardless of GPS. If the trailer actually turned between the last good
sample and the moment of commit, the IMU heading will show that turn --
independent of GPS course, and available even during the low-speed gap
GPS course can't be trusted in. So the heading value is now captured
alongside the GPS sample at MOVING time (already was), and compared
against the *current* heading again right when a commit is about to
happen. If they've diverged by more than TURN_THRESHOLD_DEG, the
straight-line assumption behind this whole script is known to be false
for this stop -- so instead of committing a baseline built on a stale
pre-turn sample, the script backs off: no commit, and
imu_heading_state.json gets needs_init=True (same "don't guess, ask a
human" fallback auto_recalibrate_imu_heading.py already uses when it
can't confirm the trailer hasn't moved). The old true_heading_at_set /
offset_deg are left untouched so a human still has the last known-good
anchor to look at if useful, but the "needs_init" flag makes clear it
shouldn't be trusted for navigation until re-confirmed.

Honest limitation, still true even with the check above: it only catches
turns of at least TURN_THRESHOLD_DEG. A gentle drift onto a slightly
different heading during a slow, mostly-straight approach could still
slip through under that threshold. This is a backstop against exactly
the "arrived via a real turn on a slow road" failure mode observed
2026-08-18, not a guarantee of GPS-course accuracy in general.

State machine (checked every POLL_INTERVAL_SECONDS against the latest
MQTT-cached values), implemented as the pure function step():

    MOVING   speed >= MOVING_THRESHOLD_KMH and fix_ok
             -> record (heading, gps_course, timestamp) as last_good_sample
    STOPPED  speed < STOP_THRESHOLD_KMH, held continuously for
             STOP_DWELL_SECONDS with a last_good_sample no older than
             SAMPLE_MAX_AGE_SECONDS ->
                 if |current heading - last_good_sample heading| <=
                 TURN_THRESHOLD_DEG: commit a fresh imu_heading_state.json
                 else: block the commit, flag needs_init instead (turn
                 detected between sample and arrival)
    BETWEEN  ambiguous (parking-lot speeds) -> state held as-is

Requires:
    pip3 install paho-mqtt --break-system-packages

Usage:
    python3 imu_gps_heading_autoset.py
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
GPS_TOPIC_BASE = "rvtc/sensors/gps"
IMU_TOPIC_BASE = "rvtc/sensors/imu"

STATE_FILE = "/home/ve7cbh/RV-total-control/config/scripts/imu_heading_state.json"

MOVING_THRESHOLD_KMH = 20.0   # GPS course-over-ground is reliable well above this
STOP_THRESHOLD_KMH = 3.0      # below this, considered genuinely stopped
STOP_DWELL_SECONDS = 90       # must stay stopped this long before committing
SAMPLE_MAX_AGE_SECONDS = 600  # don't commit a sample older than 10 minutes
MQTT_STALE_SECONDS = 10       # if no fresh MQTT update in this long, treat as no data

# How much the IMU's own heading is allowed to have changed between the
# last GPS-course sample and the moment of commit before we no longer
# trust "the trailer travelled straight from there to here." 15° gives
# comfortable margin over normal magnetometer/gyro noise while still
# catching real turns onto/within a slow entrance road -- see the
# 2026-08-18 CHANGED note above for the failure this is guarding against.
TURN_THRESHOLD_DEG = 15.0

POLL_INTERVAL_SECONDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s imu_gps_autoset: %(message)s",
)
log = logging.getLogger("imu_gps_autoset")


# ── Shared state, updated by MQTT callbacks, read by the state-machine loop
_lock = threading.Lock()
_cache = {
    "heading": None, "course_deg": None, "speed_kmh": None,
    "latitude": None, "longitude": None, "fix_ok": None,
}
_last_updated = {}


def _set(field: str, value) -> None:
    with _lock:
        _cache[field] = value
        _last_updated[field] = time.monotonic()


def _snapshot():
    """Returns (cache_copy, all_fresh: bool) -- all_fresh is False if any
    required field hasn't updated recently or is still None."""
    with _lock:
        cache = dict(_cache)
        now = time.monotonic()
        required = ("heading", "course_deg", "speed_kmh", "latitude", "longitude", "fix_ok")
        all_fresh = all(
            cache.get(f) is not None
            and f in _last_updated
            and (now - _last_updated[f]) <= MQTT_STALE_SECONDS
            for f in required
        )
    return cache, all_fresh


def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    if reason_code != 0:
        log.warning(f"MQTT connect failed: {reason_code}")
        return
    client.subscribe(f"{GPS_TOPIC_BASE}/#")
    client.subscribe(f"{IMU_TOPIC_BASE}/heading")
    log.info("Subscribed to GPS + heading topics")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    field = msg.topic.rsplit("/", 1)[-1]

    if field == "fix_ok":
        _set("fix_ok", payload.strip().lower() in ("true", "1"))
        return
    if field == "heading":
        try:
            _set("heading", float(payload))
        except ValueError:
            pass
        return
    if field in ("course_deg", "speed_kmh", "latitude", "longitude"):
        try:
            _set(field, float(payload))
        except ValueError:
            pass


def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id="rvtc-imu-gps-autoset",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


def circular_diff_deg(a: float, b: float) -> float:
    """Smallest signed difference a-b, wrapped to (-180, 180]."""
    d = (a - b) % 360
    if d > 180:
        d -= 360
    return d


# ── Pure state-machine step -- kept pure and testable, now returns a third
# element for the turn-detected/blocked case ──────────────────────────────

def step(snap: dict, now: float, fsm: dict) -> tuple:
    """snap keys: heading (current IMU heading -- used both as the sample
    value while MOVING, and as the "heading now" comparison while
    STOPPED), course_deg, speed_kmh, fix_ok. fsm keys: last_good_sample
    (dict or None), stopped_since (float or None), committed_this_stop
    (bool). Returns (new_fsm, sample_to_commit or None, turn_blocked or
    None) -- turn_blocked is the rejected sample (with diagnostic fields
    added) when a commit was skipped because the heading moved too much
    since that sample was captured."""
    fsm = dict(fsm)
    sample_to_commit = None
    turn_blocked = None

    if snap["speed_kmh"] >= MOVING_THRESHOLD_KMH and snap["fix_ok"]:
        fsm["last_good_sample"] = {
            "heading_deg": snap["heading"],
            "course_deg": snap["course_deg"],
            "timestamp": now,
        }
        fsm["stopped_since"] = None
        fsm["committed_this_stop"] = False

    elif snap["speed_kmh"] < STOP_THRESHOLD_KMH:
        if fsm["stopped_since"] is None:
            fsm["stopped_since"] = now
        elif (not fsm["committed_this_stop"]
              and fsm["last_good_sample"] is not None
              and (now - fsm["last_good_sample"]["timestamp"]) <= SAMPLE_MAX_AGE_SECONDS
              and (now - fsm["stopped_since"]) >= STOP_DWELL_SECONDS):

            heading_delta = circular_diff_deg(snap["heading"], fsm["last_good_sample"]["heading_deg"])

            if abs(heading_delta) > TURN_THRESHOLD_DEG:
                turn_blocked = dict(fsm["last_good_sample"])
                turn_blocked["heading_now_deg"] = snap["heading"]
                turn_blocked["heading_delta_deg"] = round(heading_delta, 1)
            else:
                sample_to_commit = fsm["last_good_sample"]

            fsm["committed_this_stop"] = True

    # else: between thresholds -- hold state as-is, no change

    return fsm, sample_to_commit, turn_blocked


def _read_current_offset() -> float:
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get("offset_deg", 0.0)
    except (OSError, json.JSONDecodeError):
        return 0.0


def commit_new_baseline(sample: dict, current_lat: float, current_lon: float, current_heading: float) -> None:
    old_offset = _read_current_offset()
    # heading_deg already includes old_offset -- see module docstring for
    # why we derive the new offset this way rather than needing raw Yaw.
    new_offset = (old_offset + (sample["course_deg"] - sample["heading_deg"])) % 360

    state = {
        "needs_init": False,
        "offset_deg": round(new_offset, 2),
        "raw_yaw_at_set": None,  # not available via MQTT -- see docstring
        "true_heading_at_set": round(sample["course_deg"], 2),
        "latitude_at_set": round(current_lat, 6),
        "longitude_at_set": round(current_lon, 6),
        "set_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "gps_auto",
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    heading_delta = circular_diff_deg(current_heading, sample["heading_deg"])
    log.info(
        f"Committed GPS-derived heading: course={sample['course_deg']:.1f}°, "
        f"new_offset={new_offset:.1f}°, position={current_lat:.6f},{current_lon:.6f}, "
        f"heading drifted {heading_delta:+.1f}° between capture and commit "
        f"(within {TURN_THRESHOLD_DEG:.0f}° threshold)"
    )


def flag_needs_init_after_turn(turn_blocked: dict) -> None:
    """A turn was detected between the last GPS sample and arrival -- the
    straight-line assumption this script depends on doesn't hold for this
    stop. Don't commit a baseline built on stale data; instead mark
    needs_init so a human knows to re-anchor manually, same fallback
    auto_recalibrate_imu_heading.py uses when it can't confirm the
    trailer hasn't moved. Leaves any existing offset/true_heading in
    place -- not overwriting a possibly-still-useful old anchor, just
    flagging it as unconfirmed."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        state = {}

    state["needs_init"] = True

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    log.warning(
        "Skipped GPS auto-commit: heading changed %.1f° between the last "
        "moving sample (course=%.1f°) and arrival -- looks like a turn "
        "happened after GPS course could last be trusted (e.g. onto a "
        "slow entrance road). Marked needs_init=True; run "
        "set_imu_heading.py manually with a real compass/known bearing.",
        turn_blocked["heading_delta_deg"], turn_blocked["course_deg"],
    )


def run() -> None:
    make_mqtt_client()
    fsm = {"last_good_sample": None, "stopped_since": None, "committed_this_stop": False}
    last_moving_log = None  # throttle -- don't log every 3s poll while driving for hours

    while True:
        cache, all_fresh = _snapshot()
        if not all_fresh:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        snap = {
            "heading": cache["heading"], "course_deg": cache["course_deg"],
            "speed_kmh": cache["speed_kmh"], "fix_ok": cache["fix_ok"],
        }
        prev_stopped_since = fsm["stopped_since"]
        now = time.monotonic()
        fsm, sample_to_commit, turn_blocked = step(snap, now, fsm)

        # Breadcrumb while genuinely moving, throttled to ~once/30s -- so a
        # post-hoc log review can see the sample trail leading up to any
        # stop, without hours of drive time producing one line every 3s.
        if snap["speed_kmh"] >= MOVING_THRESHOLD_KMH and snap["fix_ok"]:
            if last_moving_log is None or (now - last_moving_log) >= 30:
                log.info(
                    "Moving: speed=%.1f km/h, gps_course=%.1f°, imu_heading=%.1f° "
                    "-- tracked as last_good_sample",
                    snap["speed_kmh"], snap["course_deg"], snap["heading"],
                )
                last_moving_log = now

        # The moment a dwell timer starts, log exactly which sample is now
        # in play for the eventual commit/skip decision -- this is the key
        # line for reconstructing "what did it think it knew" after the
        # fact, without needing to have watched it live.
        if fsm["stopped_since"] is not None and prev_stopped_since is None:
            if fsm["last_good_sample"] is not None:
                age_s = now - fsm["last_good_sample"]["timestamp"]
                log.info(
                    "Stopped -- dwell timer started. Last good sample: "
                    "gps_course=%.1f°, imu_heading_at_capture=%.1f°, captured %.0fs ago "
                    "(commit needs %.0fs continuous stop + sample age <= %.0fs)",
                    fsm["last_good_sample"]["course_deg"],
                    fsm["last_good_sample"]["heading_deg"], age_s,
                    STOP_DWELL_SECONDS, SAMPLE_MAX_AGE_SECONDS,
                )
            else:
                log.info(
                    "Stopped -- no valid GPS sample captured this leg "
                    "(never exceeded %.0f km/h with a fix since the last stop)",
                    MOVING_THRESHOLD_KMH,
                )

        if sample_to_commit is not None:
            commit_new_baseline(sample_to_commit, cache["latitude"], cache["longitude"], snap["heading"])
        elif turn_blocked is not None:
            flag_needs_init_after_turn(turn_blocked)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped")
