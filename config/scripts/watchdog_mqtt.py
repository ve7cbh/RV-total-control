#!/usr/bin/env python3
"""
watchdog_mqtt.py — RVTC MQTT adaptor health watchdog.

Why this exists: adaptors occasionally go quiet -- not often, not even
daily, but silently. A stuck Modbus read, an unhandled exception outside
an adaptor's own retry loop, a script that's still alive and still
connected to Mosquitto but has simply stopped calling publish() -- none of
that trips a plain MQTT Last Will/Testament, because the TCP connection to
the broker never actually drops. LWT only fires on a real disconnect, so
it catches "the process died" but not "the process is hung." This
watchdog catches both, by tracking when each adaptor's topic tree was last
heard from at all, not just whether its socket is open.

Design, matching the rest of RVTC's architecture (System Reference
Section 1): this is itself just another MQTT client -- a subscriber that
watches every other adaptor's topics, and a publisher that reports
staleness back to the same broker. It does not talk to Home Assistant,
InfluxDB, or Grafana directly -- each of those already consumes from
Mosquitto (HA via its MQTT integration's alert notifications, Telegraf via
a new telegraf_watchdog.conf if you want history), so wiring this in as
"yet another sensor-shaped adaptor" keeps the one-broker, no-private-pipes
rule intact rather than carving out a special case.

Per-adaptor silence thresholds are configured below (ADAPTORS dict)
rather than assumed uniform, because poll intervals differ a lot across
RVTC (IMU at 2Hz vs. weather at a much slower cadence). A few adaptors
(epever/samlux/kws) also mask partial failures behind an unconditionally-
published `poll_errors` field, and one of those (generator) is expected
to sit at max error count whenever the generator's simply off -- see the
ADAPTORS comments for how each case is actually handled, since it's not
uniform. Treat every threshold below as a starting point to tune against
real observed behavior, not a settled value.

Publishes (all retained, so a client that (re)subscribes gets current
state immediately without waiting for the next transition):
    rvtc/system/watchdog/<adaptor>          "ok" | "stale"
    rvtc/system/watchdog/availability       "online" / "offline" (LWT) --
                                             this script's own liveness,
                                             same convention as every
                                             adaptor it watches. Nothing
                                             watches the watchdog, but at
                                             least its own death is
                                             visible on a dashboard rather
                                             than silent.

Does NOT replace systemd's own Restart=on-failure on each adaptor's unit
-- that's still the right tool for "the process actually crashed," and
should already be set on every *_mqtt.service unit regardless of this
watchdog. This script exists specifically for the gap systemd can't see:
a process that's still running, still holding its socket open, and still
doing nothing.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import logging
import time

import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────────────────────────────
MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883

WATCHDOG_TOPIC_BASE = "rvtc/system/watchdog"
AVAILABILITY_TOPIC = f"{WATCHDOG_TOPIC_BASE}/availability"

CHECK_INTERVAL_SECONDS = 15   # how often to sweep for staleness
STARTUP_GRACE_SECONDS = 90    # don't alarm on anything until we've had a
                               # fair chance to hear from it after our own
                               # (re)start -- avoids a false "stale" burst
                               # for every adaptor every time the watchdog
                               # itself restarts

# One entry per adaptor. `topic_prefix` is matched against every incoming
# message topic (startswith) -- ANY message under that prefix counts as a
# sign of life, not just a dedicated availability/LWT topic, so this still
# works for adaptors that don't (yet) implement that convention.
# `max_silence` is in seconds -- tune these against real observed
# behavior, not the numbers below, which are first-guess starting points.
ADAPTORS = {
    # solar/inverter: epever_mqtt.py and samlux_mqtt.py publish a
    # `poll_errors` count unconditionally at the end of every cycle, EVEN
    # WHEN EVERY REGISTER FAILED -- so topic silence alone won't catch a
    # sensor that's failing 100% of its reads but still running.
    # `poll_errors_topic` below adds a second check: alarm if that count
    # stays nonzero for a sustained stretch, not just if the topic goes
    # quiet. See POLL_ERRORS_STREAK_SECONDS. Solar (controller) and
    # inverter are core RVTC components, expected to be present and
    # responding whenever the system itself is running -- unlike grid
    # below, there's no normal operating state where they're legitimately
    # dark, so a sustained error streak here is a real fault.
    "solar":     {"topic_prefix": "rvtc/sensors/solar/",     "max_silence": 60,
                  "poll_errors_topic": "rvtc/sensors/solar/poll_errors"},
    "inverter":  {"topic_prefix": "rvtc/sensors/inverter/",  "max_silence": 60,
                  "poll_errors_topic": "rvtc/sensors/inverter/poll_errors"},
    # Grid AND generator: kws_mqtt.py's own docstring says only one of
    # these is normally powered at a time -- and per direct confirmation,
    # no input power means the meter itself is functionally absent, not
    # malfunctioning (these meters draw their own operating power from
    # the line they measure, so no line power means no communication at
    # all, by design). That's true of BOTH meters, not just generator --
    # running off battery/solar alone with no shore power and no
    # generator running is normal, common RVTC operation, so `grid` going
    # dark is just as expected as `generator` going dark. poll_meter()
    # still publishes poll_errors every cycle regardless of meter power
    # state, so silence detection alone is fine for catching the one
    # fault that DOES matter here (the script/process itself dying) --
    # deliberately NOT tracking poll_errors for either, since a maxed-out
    # count is each meter's normal resting state whenever it's unpowered.
    "grid":      {"topic_prefix": "rvtc/sensors/grid/",      "max_silence": 60},
    "generator": {"topic_prefix": "rvtc/sensors/generator/", "max_silence": 60},
    "imu":       {"topic_prefix": "rvtc/sensors/imu/",       "max_silence": 30},
    "gps":       {"topic_prefix": "rvtc/sensors/gps/",       "max_silence": 30},
    "weather":   {"topic_prefix": "rvtc/sensors/weather/",   "max_silence": 120},
    # HW-32, confirmed via MQTT explorer + eid041_mqtt.py source 2026-08.
    # Poll interval not confirmed -- 120s is a placeholder, tune once
    # observed. HW-33's three additional units aren't in here yet --
    # pending confirmation of whether they'll share this prefix (address
    # as a sub-field) or each get their own (equipment_bay/cargo/tank).
    "enclosure": {"topic_prefix": "rvtc/sensors/enclosure/", "max_silence": 120},
}

# How long poll_errors must stay nonzero before alarming, for adaptors
# with poll_errors_topic set above. Longer than OFFLINE_DEBOUNCE_SECONDS
# on purpose -- a single bad Modbus transaction now and then is normal
# fleet noise (see kws_mqtt.py's own comments on this); this is meant to
# catch "has not gotten a clean read in minutes," not "missed one poll."
POLL_ERRORS_STREAK_SECONDS = 180

# Debounce for the fast path below: several adaptors (confirmed so far:
# imu_mqtt.py, eid041_mqtt.py) already publish their own explicit
# "offline" to a `.../availability` topic the moment a poll fails, ahead
# of their own internal retry. That's faster and more precise than
# waiting out this watchdog's own max_silence timer, so treat it as a
# priority signal -- but still debounce briefly, since these scripts
# retry on their own (RETRY_SECONDS-scale loops) and a single transient
# blip that self-heals in a few seconds shouldn't page anyone.
OFFLINE_DEBOUNCE_SECONDS = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s watchdog_mqtt: %(message)s",
)
log = logging.getLogger("watchdog_mqtt")


# ── State ─────────────────────────────────────────────────────────────────
start_time = time.monotonic()
last_seen = {name: None for name in ADAPTORS}       # None until first message
offline_since = {name: None for name in ADAPTORS}      # fast path, see on_message()
poll_errors_since = {name: None for name in ADAPTORS}  # nonzero-streak path, see on_message()

# Tracks the last state actually PUBLISHED for each adaptor: None (nothing
# published yet), "ok", or "stale". Deliberately not a simple in-alarm
# boolean -- with that, an adaptor that's healthy from the start never
# transitions FROM alarm, so it never gets a first "ok" published at all,
# and its topic just never comes into existence. Comparing against this
# instead means every adaptor gets an initial publish the first time it's
# evaluated, healthy or not, not just on a later change.
published_state = {name: None for name in ADAPTORS}


# ── MQTT callbacks ───────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc != 0:
        log.warning(f"connect failed, rc={rc}")
        return
    log.info("connected to broker, subscribing to rvtc/sensors/#")
    client.subscribe("rvtc/sensors/#")
    client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)


def on_message(client, userdata, msg):
    now = time.monotonic()
    try:
        payload = msg.payload.decode(errors="replace").strip().lower()
    except Exception:
        payload = ""

    for name, cfg in ADAPTORS.items():
        if not msg.topic.startswith(cfg["topic_prefix"]):
            continue

        # ANY message under this prefix is a sign the process is running
        # at all -- including an explicit "offline", which proves it's
        # still alive enough to run its own except-block. Feeds the
        # silence backstop in the main loop.
        last_seen[name] = now

        is_availability = msg.topic == f"{cfg['topic_prefix']}availability"
        if is_availability and payload == "offline":
            if offline_since[name] is None:
                offline_since[name] = now
        elif is_availability and payload == "online":
            offline_since[name] = None

        # poll_errors nonzero-streak: see ADAPTORS comment for why this
        # exists (epever/samlux/kws publish this unconditionally, masking
        # partial failures from plain silence detection).
        if msg.topic == cfg.get("poll_errors_topic"):
            try:
                errors = int(payload)
            except ValueError:
                errors = None
            if errors:
                if poll_errors_since[name] is None:
                    poll_errors_since[name] = now
            elif errors == 0:
                poll_errors_since[name] = None

    # No alarm raise/clear here on purpose -- see run()'s sweep. Deciding
    # alarm state from a snapshot of current conditions each sweep, rather
    # than reacting to individual messages, avoids exactly the bug this
    # replaced: a script that keeps publishing while still broken (see
    # poll_errors above) would otherwise clear its own alarm on its next
    # message even though nothing's actually fixed.


def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(client_id="rvtc-watchdog")
    client.will_set(AVAILABILITY_TOPIC, payload="offline", retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


# ── Main loop ─────────────────────────────────────────────────────────────

def run() -> None:
    client = make_mqtt_client()
    log.info(f"watchdog started, {STARTUP_GRACE_SECONDS}s grace period before first check")

    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        now = time.monotonic()
        elapsed_since_start = now - start_time

        for name, cfg in ADAPTORS.items():
            reasons = []

            off_since = offline_since[name]
            if off_since is not None and (now - off_since) > OFFLINE_DEBOUNCE_SECONDS:
                reasons.append(f"reporting offline for {now - off_since:.0f}s")

            err_since = poll_errors_since[name]
            if err_since is not None and (now - err_since) > POLL_ERRORS_STREAK_SECONDS:
                reasons.append(f"poll_errors nonzero for {now - err_since:.0f}s")

            seen = last_seen[name]
            if seen is None:
                if elapsed_since_start <= STARTUP_GRACE_SECONDS:
                    # Genuinely unknown state -- haven't heard from it, and
                    # haven't waited long enough to say that's abnormal
                    # either. Skip publishing anything this sweep rather
                    # than guessing "ok" from an absence of reasons that's
                    # really just an absence of evidence.
                    continue
                reasons.append(f"no data since watchdog start ({elapsed_since_start:.0f}s)")
            else:
                silence = now - seen
                if silence > cfg["max_silence"]:
                    reasons.append(f"silent for {silence:.0f}s (threshold {cfg['max_silence']}s)")

            was = published_state[name]
            state = "stale" if reasons else "ok"
            if state != was:
                published_state[name] = state
                client.publish(f"{WATCHDOG_TOPIC_BASE}/{name}", payload=state, retain=True)
                if state == "stale":
                    log.warning(f"{name}: {'; '.join(reasons)}")
                elif was == "stale":
                    log.info(f"{name}: recovered")
                else:
                    log.info(f"{name}: ok (first check)")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped")
