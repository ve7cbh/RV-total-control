# RVTC — Session Addendum 2026-07-02
## Architecture Rethink: Unified Namespace + Telegraf Persistence Layer

*Append to Section 8 (Session Log), following the 2026-06-30 Tier 3 / KWS entry. Also feeds a new
Section 9.5 (Data Flow Architecture) once implemented and confirmed working — see closing note.*

---

### Summary

Reviewed the actual data pipeline (source → collection → MQTT → storage → display) against the
project's stated vision that **all sensor data lands in one database**, with downstream processes
subscribing to and querying that database rather than each building its own path to storage.

Finding: the current pipeline is two disconnected lanes sharing one broker, not one pipeline.
Weather data (RTL-SDR → rtl_433 → WeeWX → InfluxDB → Grafana/Belchertown) is a closed loop. Power/
Modbus data (EPEVER/SAMLUX/KWS-303L → Python bridge scripts → MQTT → Home Assistant) dead-ends at
HA — nothing writes it to InfluxDB, so Grafana has no visibility into grid current, battery SOC,
inverter mode, or any Tier 3/4 state. This also means Section 2.8's stated intent ("every A/C shed
logged to InfluxDB as a discrete event") was never actually wired.

**Decision:** adopt a unified-namespace architecture — one MQTT broker as the live data bus, one
generic subscriber that persists everything to InfluxDB without per-source custom code, InfluxDB as
the single source of truth for history, and every consumer (HA, Grafana, future load controllers)
either subscribes to the broker for live data or queries InfluxDB for history. Nothing gets a
private, bespoke path to storage going forward.

This isn't a new direction so much as pulling forward and formalizing what Section 9.1 (Phase 7 —
Sensor Fusion) was already describing for the normalised `rvtc/sensors/{source}/{field}` topic
schema — the fusion/arbitration layer is still deferred, but the "everything lands in one place"
part doesn't need to wait for Phase 7.

---

### Phase 0 — Payload audit (completed 2026-07-02)

```bash
mosquitto_sub -h localhost -t 'rtl_433/#' -t 'rvtc/sensors/#' -v -C 20
```

**Confirmed:**
- `rvtc/sensors/{source}/{field}` — flat scalar payload per topic, e.g.
  `rvtc/sensors/solar/pv_voltage 69.22`. Already in the right shape for generic ingestion, no
  reshaping needed.
- `rtl_433/{rtl433,rtl433b}/events` — JSON payload, matches expected Acurite 5n1 fields. Acurite
  5n1 rotates between message types (56: temp/humidity/wind; 49: wind/rain) — a single physical
  reading is only fully reassembled across multiple messages. WeeWX already handles this
  correctly (Section 5.2); a naive ingest of raw `rtl_433/#` would NOT reproduce WeeWX's corrected
  values (unit conversion, `contains_total` rain handling, ID filter) — see Phase 3 below.

**Anomaly flagged, not yet resolved:** four `rtl_433/{mac}/availability` topics appeared
(`979a52e42f15`, `371c2d98fb4f`, `dd2487a13637`, `296813f2bc3e`) that don't correspond to either
known rtl_433 container (`rtl433`, `rtl433b` per `docker-compose.yml`). Something else is
publishing into the `rtl_433/` namespace.

**TODO before building anything further on the `rtl_433/` topic tree:**
```bash
mosquitto_sub -h localhost -t 'rtl_433/+/availability' -v
```
Cross-reference the MACs against `docker ps` and MikroTik DHCP leases. Don't extend Telegraf (or
anything else) to subscribe to `rtl_433/#` until this is understood — this is exactly the kind of
thing a unified namespace is supposed to surface.

---

### Target architecture

```
All sensor sources (weather, power, tanks, GNSS, IMU, ...)
        │
        ▼
Mosquitto — unified namespace (rvtc/sensors/{source}/{field})
        │
        ├──► Telegraf (generic MQTT → InfluxDB writer) ──► InfluxDB (single source of truth)
        │                                                        │
        │                                                        ▼
        │                                              Grafana / any query client
        │
        └──► Live subscribers (HA automations, live dashboards)
                    │
                    ▼
             Actuation only, via Modbus writes (relay.py / kws_relay.py)
             — result should publish back to MQTT (see Phase 1) so it's
               captured by Telegraf like any other reading
```

HA still subscribes to MQTT directly for anything time-critical (Tier 3 can't wait on a database
round-trip) — that doesn't change. What changes is that HA is no longer the *only* place that data
ends up.

---

### Implementation plan

**Phase 1 — Tier 3 event publish-back (small, closes a known gap)**

Add an `mqtt.publish` service call alongside the relay write in each shed/restore script in
`scripts.yaml`, e.g. `rvtc/events/tier3/grid_shed`. Zero risk to anything currently running.
Directly fulfils the Section 2.8 intent that was never wired. **Not yet drafted as exact YAML —
do next session once Phase 2 confirms the ingestion path works.**

**Phase 2 — Telegraf, deployed in parallel, touching nothing existing**

New bucket (isolates this from the working WeeWX → `rvtc` bucket path):
```bash
docker exec influxdb influx bucket create --name rvtc_unified --org rvtc
```

Config file:
```bash
mkdir -p /data/docker/volumes/telegraf
cat > /data/docker/volumes/telegraf/telegraf.conf << 'EOF'
[agent]
  interval = "10s"
  flush_interval = "10s"

[[outputs.influxdb_v2]]
  urls = ["http://influxdb:8086"]
  token = "$INFLUX_TOKEN"
  organization = "rvtc"
  bucket = "rvtc_unified"

[[inputs.mqtt_consumer]]
  servers = ["tcp://mosquitto:1883"]
  topics = ["rvtc/sensors/#"]
  data_format = "value"
  data_type = "float"
  name_override = "rvtc_sensors"

  [[inputs.mqtt_consumer.topic_parsing]]
    topic = "rvtc/sensors/+/+"
    tags = "_/_/source/_"
    fields = "_/_/_/field"

[[processors.pivot]]
  tag_key = "field"
  value_key = "value"
EOF
```

`docker-compose.yml` addition:
```yaml
  telegraf:
    image: telegraf:1.39
    container_name: telegraf
    restart: unless-stopped
    environment:
      - INFLUX_TOKEN=${VAULT_INFLUXDB_TOKEN}
    volumes:
      - /data/docker/volumes/telegraf/telegraf.conf:/etc/telegraf/telegraf.conf:ro
    depends_on:
      - mosquitto
      - influxdb
```

Deploy and verify:
```bash
cd ~/RV-total-control
docker compose up -d telegraf
docker logs -f telegraf
docker exec influxdb influx query 'from(bucket:"rvtc_unified") |> range(start:-5m)'
```

**Caveat to check once running, not assumed:** `processors.pivot` merges metrics sharing identical
tags AND identical timestamp. The `rvtc/sensors/solar/*` burst arrives as 14 separate MQTT
publishes with independently-timestamped payloads, so they may land as several narrow rows per
poll rather than one wide row. Still fully queryable either way — check the actual shape in
InfluxDB before assuming a redesign is needed; likely fix if it doesn't merge cleanly is
`collection_jitter`/time-rounding, not a rebuild.

**Phase 3 — weather: publish corrected values, don't re-ingest raw**

Do NOT point Telegraf at `rtl_433/#` directly — that would create a second, uncorrected copy of
weather data next to WeeWX's correct one (raw Fahrenheit, uncorrected cumulative rain counts,
no ID filter). Instead: use the `weewx-mqtt` extension so WeeWX publishes its already-corrected
readings out to `rvtc/sensors/weather/{field}`, and Telegraf only ever touches the normalized
topic — consistent with everything else in the unified namespace. Not yet scheduled.

**Phase 4 — burn-in and cutover**

Run `influxdb2.py` (existing) and Telegraf (new) in parallel for a few days, compare, then retire
`influxdb2.py` and point Grafana at `rvtc_unified`. WeeWX's SQLite archive is untouched throughout
— it stays WeeWX's internal working store for daily summaries, not a competing source of truth.

**Phase 5 — write it up**

Draft Section 9.5 (Data Flow Architecture) once Phase 2 is actually running and confirmed, not
before — document what's real, matching the rest of the reference doc's convention.

---

### Next Session Priorities (2026-07-03 morning)

1. Run the `rtl_433/{mac}/availability` audit — identify the four unaccounted-for devices before
   building anything further on that topic tree
2. Deploy Phase 2 (Telegraf + `rvtc_unified` bucket) per commands above; confirm data lands and
   check the pivot/timestamp merge behaviour against real data
3. If Phase 2 confirms clean, draft the Phase 1 `mqtt.publish` additions to `scripts.yaml`
4. (Carried over from 2026-06-30) KWS grid/generator disconnect switches still not added to Load
   Control dashboard; live bench test of Tier 3 automatic trigger still outstanding; remove empty
   `kws303l/` directory
