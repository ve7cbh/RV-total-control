#!/usr/bin/env python3
"""
imu_web.py — RVTC mobile-first IMU status page (fulfills OI-42).

Replaces the old ESP32-published Time/Hdg/Pitch/Roll page. Subscribes to the
existing rvtc/sensors/imu/# MQTT feed (does NOT touch the WitMotion device
directly — see Section 9's standing rule: only imu_mqtt.py talks to that
device, everything else subscribes to MQTT) and serves a small, phone-
friendly HTML page over plain HTTP, no external dependencies beyond
paho-mqtt (already used by every other RVTC bridge script).

No nginx/Pi-hole changes required to use this tonight — it binds directly
on the host and is reachable at http://192.168.88.3:8090/ from any device
on the RV's LAN. Adding a friendly hostname (level.lan or similar) via
nginx + Pi-hole is a nice-to-have follow-up, not required for this to work.

Field detection is deliberately loose (substring match on the topic suffix)
because the exact topic path for the GPS time fields isn't pinned down in
the system reference doc — heading/pitch/roll are known-flat topics, but
utc_time/chip_local_time might be flat or nested under gps/. If the
detected "Time" field looks wrong, check the raw topic table at the bottom
of the page (or GET /data.json) to find the real key and adjust
TIME_KEY_HINTS below — one-line fix, no need to touch the MQTT side.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "rvtc/sensors/imu/#"
TOPIC_PREFIX = "rvtc/sensors/imu/"

# gps is a SIBLING of imu under rvtc/sensors, not nested inside it (confirmed
# from MQTT Explorer's actual topic tree: rvtc/sensors/gps/utc_time etc.) —
# subscribe to it separately and namespace its keys under "gps/" so the
# existing TIME_KEY_HINTS substring matching keeps working unchanged.
GPS_TOPIC = "rvtc/sensors/gps/#"
GPS_TOPIC_PREFIX = "rvtc/sensors/gps/"

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8090

# How stale data can get before the page flags it as such (seconds). The
# old ESP32 continuously published; this should behave the same way, so if
# imu_mqtt.py ever stalls, the page should say so rather than silently
# showing a frozen last-good reading.
STALE_AFTER_S = 10

# Loose matching for auto-detecting which topic suffix is which field.
# Order matters within HEADING/PITCH/ROLL — exact match preferred.
TIME_KEY_HINTS = ["utc_time", "chip_local_time", "time"]

state_lock = threading.Lock()
state = {}          # topic_suffix -> value (as received, string or number)
last_update = {}    # topic_suffix -> monotonic timestamp of last message
server_start = time.time()


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[imu_web] connected, rc={rc}, subscribing to {MQTT_TOPIC!r} and {GPS_TOPIC!r}", flush=True)
    client.subscribe(MQTT_TOPIC)
    client.subscribe(GPS_TOPIC)


def on_message(client, userdata, msg):
    if msg.topic.startswith(TOPIC_PREFIX):
        suffix = msg.topic[len(TOPIC_PREFIX):]
    elif msg.topic.startswith(GPS_TOPIC_PREFIX):
        suffix = "gps/" + msg.topic[len(GPS_TOPIC_PREFIX):]
    else:
        suffix = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace")
    # Try to store as a number where possible, keep as string otherwise
    # (e.g. direction-style text fields, raw time strings).
    try:
        value = float(payload)
        if value.is_integer():
            value = int(value)
    except ValueError:
        value = payload
    with state_lock:
        state[suffix] = value
        last_update[suffix] = time.monotonic()


def find_field(candidates):
    """Return (suffix, value) for the first suffix matching any candidate
    string (case-insensitive substring), preferring shorter/exact matches."""
    with state_lock:
        items = list(state.items())
    exact = [(k, v) for k, v in items if k.lower() in candidates]
    if exact:
        return exact[0]
    loose = [(k, v) for k, v in items for c in candidates if c in k.lower()]
    return loose[0] if loose else (None, None)


def build_snapshot():
    with state_lock:
        all_topics = dict(state)
        ages = {
            k: round(time.monotonic() - last_update[k], 1) for k in state
        }

    heading_key, heading_val = find_field(["heading", "hdg"])
    pitch_key, pitch_val = find_field(["pitch"])
    roll_key, roll_val = find_field(["roll"])
    course_key, course_val = find_field(["course_deg", "course"])
    speed_key, speed_val = find_field(["speed_kmh", "speed"])
    time_key, time_val = None, None
    for hint in TIME_KEY_HINTS:
        time_key, time_val = find_field([hint])
        if time_key:
            break

    time_source = "gps"
    if time_key is None:
        # No GPS time in the cache right now (no fix, or hasn't arrived
        # since this service last restarted) — fall back to the host's own
        # clock rather than showing a blank dash. Host is expected to be
        # NTP-synced; this is clearly labeled as a fallback in the UI.
        time_val = time.strftime("%H:%M:%S", time.gmtime())
        time_source = "host"

    def age_of(key):
        return ages.get(key)

    stale = not all_topics or (
        min(ages.values()) > STALE_AFTER_S if ages else True
    )

    return {
        "heading": {"key": heading_key, "value": heading_val, "age_s": age_of(heading_key)},
        "pitch": {"key": pitch_key, "value": pitch_val, "age_s": age_of(pitch_key)},
        "roll": {"key": roll_key, "value": roll_val, "age_s": age_of(roll_key)},
        "course": {"key": course_key, "value": course_val, "age_s": age_of(course_key)},
        "speed": {"key": speed_key, "value": speed_val, "age_s": age_of(speed_key)},
        "time": {"key": time_key, "value": time_val, "age_s": age_of(time_key), "source": time_source},
        "stale": stale,
        "all_topics": all_topics,
        "ages": ages,
        "server_uptime_s": round(time.time() - server_start, 0),
    }


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>RVTC IMU</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px;
    background: #0b0d10; color: #e8eaed;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-tap-highlight-color: transparent;
  }
  h1 {
    font-size: 1rem; font-weight: 600; letter-spacing: 0.04em;
    text-transform: uppercase; color: #8a929c; margin: 0 0 16px;
    text-align: center;
  }
  .grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  }
  .card {
    background: #16191d; border-radius: 14px; padding: 18px 12px;
    text-align: center; border: 1px solid #22262b;
  }
  .card.full { grid-column: 1 / -1; }
  .label {
    font-size: 0.8rem; color: #8a929c; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 6px;
  }
  .value {
    font-size: 2.6rem; font-weight: 700; font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .value.fallback { font-size: 1.3rem; color: #c9a04a; font-weight: 500; }
  .unit { font-size: 1.1rem; color: #8a929c; margin-left: 4px; }
  .sublabel { font-size: 0.75rem; color: #6b7280; margin-top: 4px; }
  .value.mismatch { color: #d1a33a; }
  .stale .value { color: #d15b5b; }
  #status-bar {
    text-align: center; font-size: 0.8rem; color: #8a929c; margin-top: 14px;
  }
  #status-bar.stale { color: #d15b5b; font-weight: 600; }
  details {
    margin-top: 20px; color: #8a929c; font-size: 0.8rem;
  }
  summary { cursor: pointer; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.78rem; }
  td { border-bottom: 1px solid #22262b; padding: 4px 6px; }
  td.k { color: #8a929c; }
  td.v { text-align: right; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <h1>RVTC &middot; IMU</h1>
  <div class="grid">
    <div class="card full" id="card-time">
      <div class="label">Time (UTC)</div>
      <div class="value" id="v-time">&ndash;</div>
    </div>
    <div class="card" id="card-heading">
      <div class="label">Heading</div>
      <div class="value" id="v-heading">&ndash;<span class="unit">&deg;</span></div>
    </div>
    <div class="card" id="card-course">
      <div class="label">GPS Course</div>
      <div class="value" id="v-course">&ndash;<span class="unit">&deg;</span></div>
      <div class="sublabel" id="v-speed">&ndash;</div>
    </div>
    <div class="card" id="card-pitch">
      <div class="label">Pitch</div>
      <div class="value" id="v-pitch">&ndash;<span class="unit">&deg;</span></div>
    </div>
    <div class="card" id="card-roll">
      <div class="label">Roll</div>
      <div class="value" id="v-roll">&ndash;<span class="unit">&deg;</span></div>
    </div>
  </div>
  <div id="status-bar">connecting&hellip;</div>

  <details>
    <summary>Raw topics (debug)</summary>
    <table id="raw-table"><tbody></tbody></table>
  </details>

<script>
function fmt(v) {
  if (v === null || v === undefined) return '\u2013';
  if (typeof v === 'number') return v.toFixed(1);
  return v;
}

// utc_time comes through as a full "YYYY-MM-DD HH:MM:SS.mmm" string (see
// the imu/gps/utc_time topic) — show just the clock portion big, keep the
// full value visible in the raw debug table below.
function fmtTime(v, source) {
  if (v === null || v === undefined) return '\u2013';
  let clock = v;
  if (typeof v === 'string') {
    const m = v.match(/(\\d{2}:\\d{2}:\\d{2})/);
    if (m) clock = m[1];
  } else {
    clock = fmt(v);
  }
  return source === 'host' ? clock + ' UTC (host, no GPS fix)' : clock + ' UTC';
}

// Smallest signed angular difference a-b, wrapped to (-180, 180] --
// mirrors circular_diff_deg() in imu_gps_heading_autoset.py.
function circDiff(a, b) {
  let d = (a - b) % 360;
  if (d > 180) d -= 360;
  if (d <= -180) d += 360;
  return d;
}

async function poll() {
  try {
    const res = await fetch('/data.json', {cache: 'no-store'});
    const d = await res.json();

    document.getElementById('v-time').textContent = fmtTime(d.time.value, d.time.source);
    document.getElementById('v-time').classList.toggle('fallback', d.time.source === 'host');
    document.getElementById('v-heading').innerHTML = fmt(d.heading.value) + '<span class="unit">&deg;</span>';
    document.getElementById('v-pitch').innerHTML = fmt(d.pitch.value) + '<span class="unit">&deg;</span>';
    document.getElementById('v-roll').innerHTML = fmt(d.roll.value) + '<span class="unit">&deg;</span>';
    document.getElementById('v-course').innerHTML = fmt(d.course.value) + '<span class="unit">&deg;</span>';

    // Speed sublabel doubles as a trustworthiness hint for the course
    // reading -- GPS course-over-ground is meaningless well below
    // driving speed (matches MOVING_THRESHOLD_KMH=20 in
    // imu_gps_heading_autoset.py, not an arbitrary UI-only number).
    const speedVal = d.speed.value;
    let speedNum = null;
    let speedLabel = '\u2013';
    if (typeof speedVal === 'number') {
      speedNum = speedVal;
      speedLabel = speedVal.toFixed(1) + ' km/h';
      if (speedVal < 20) speedLabel += ' \u2014 too slow for reliable course';
    }
    document.getElementById('v-speed').textContent = speedLabel;

    // Highlight Heading + Course together when they disagree by more than
    // 20\u00b0 while genuinely moving -- the exact live signal that would have
    // caught the Port McNeil incident in real time instead of after the fact.
    const headingEl = document.getElementById('v-heading');
    const courseEl = document.getElementById('v-course');
    let mismatch = false;
    if (typeof d.heading.value === 'number' && typeof d.course.value === 'number'
        && speedNum !== null && speedNum >= 20) {
      mismatch = Math.abs(circDiff(d.heading.value, d.course.value)) > 20;
    }
    headingEl.classList.toggle('mismatch', mismatch);
    courseEl.classList.toggle('mismatch', mismatch);

    const bar = document.getElementById('status-bar');
    if (d.stale) {
      bar.textContent = 'No fresh data \u2014 check imu_mqtt.service';
      bar.classList.add('stale');
    } else {
      bar.textContent = 'live';
      bar.classList.remove('stale');
    }

    const tbody = document.querySelector('#raw-table tbody');
    tbody.innerHTML = '';
    const topics = Object.keys(d.all_topics).sort();
    for (const k of topics) {
      const tr = document.createElement('tr');
      const age = d.ages[k] !== undefined ? d.ages[k].toFixed(0) + 's ago' : '';
      tr.innerHTML = '<td class="k">' + k + '</td><td class="v">' + d.all_topics[k] + ' <span style="color:#555">(' + age + ')</span></td>';
      tbody.appendChild(tr);
    }
  } catch (e) {
    document.getElementById('status-bar').textContent = 'connection lost';
    document.getElementById('status-bar').classList.add('stale');
  }
}
poll();
setInterval(poll, 1000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep systemd journal quiet; nothing interesting to log per-request

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/data.json":
            body = json.dumps(build_snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    client.loop_start()

    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print(f"imu_web serving on http://{HTTP_HOST}:{HTTP_PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
