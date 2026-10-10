#!/usr/bin/env python3
"""
meshcore_name_resolver.py — RVTC adaptor: decode MeshCore ADVERT packets
into a pubkey -> friendly-name directory, published back onto Mosquitto.

Why this exists: the observer's packets topic gives us pubkeys (in
neighbours, in path hops), but never names -- those only exist inside
ADVERT packet payloads, which are never decoded by the observer firmware
itself (it just forwards raw bytes). This subscribes to the SAME
meshcore/DUQ/+/packets topic Telegraf reads, filters for packet_type "4"
(ADVERT) specifically, and decodes the payload locally.

ADVERT payload layout (verified against a known-good decoded example
from the meshcoredecoder project before trusting it on real data):
    bytes   0-31   Ed25519 public key
    bytes  32-35   timestamp, uint32 little-endian
    bytes  36-99   Ed25519 signature (unused here)
    byte      100  app_flags bitfield -- bit4 = location present,
                                          bit7 = name present
    bytes 101-108  latitude, longitude (int32 LE / 1e6 each) -- ONLY
                   present if app_flags bit4 is set
    bytes 109+ (or 101+ if no location)
                   name, UTF-8, no null terminator, runs to end of
                   payload -- ONLY present if app_flags bit7 is set

The payload itself is extracted from the packet's "raw" hex field using
payload_len (already present in every packet message) rather than
hand-parsing the packet header/transport-codes/path — much simpler and
avoids re-deriving logic MeshCore itself already computed for us.

Publishes (retained, so Telegraf gets the full known directory
immediately on every reconnect, not just new adverts going forward):
    rvtc/meshcore/names/<pubkey>   {"pubkey", "name", "lat", "lon",
                                     "updated", "heard_by"}

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import json
import logging
import struct

import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883

PACKETS_TOPIC = "meshcore/DUQ/+/packets"
NAMES_TOPIC_PREFIX = "rvtc/meshcore/names"

ADVERT_PACKET_TYPE = "4"  # string -- MeshCore stringifies all numeric fields

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s meshcore_name_resolver: %(message)s",
)
log = logging.getLogger("meshcore_name_resolver")


def decode_advert_payload(payload: bytes):
    """Returns {"pubkey", "name", "lat", "lon"} or None if too short/malformed."""
    if len(payload) < 101:
        return None

    pubkey = payload[0:32].hex()
    app_flags = payload[100]
    has_location = bool(app_flags & 0x10)
    has_name = bool(app_flags & 0x80)

    offset = 101
    lat = lon = None
    if has_location:
        if len(payload) < offset + 8:
            return {"pubkey": pubkey, "name": None, "lat": None, "lon": None}
        lat = struct.unpack("<i", payload[offset:offset + 4])[0] / 1e6
        lon = struct.unpack("<i", payload[offset + 4:offset + 8])[0] / 1e6
        offset += 8

    name = None
    if has_name and len(payload) > offset:
        try:
            name = payload[offset:].decode("utf-8", errors="replace").strip()
        except Exception:
            name = None

    return {"pubkey": pubkey, "name": name, "lat": lat, "lon": lon}


def on_message(client, userdata, msg):
    try:
        rec = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    if rec.get("packet_type") != ADVERT_PACKET_TYPE:
        return

    raw_hex = rec.get("raw")
    payload_len_str = rec.get("payload_len")
    if not raw_hex or not payload_len_str:
        return

    try:
        payload_len = int(payload_len_str)
        raw_bytes = bytes.fromhex(raw_hex)
    except (ValueError, TypeError):
        log.warning("skip: bad raw/payload_len on %s", msg.topic)
        return

    if payload_len <= 0 or payload_len > len(raw_bytes):
        return

    payload = raw_bytes[-payload_len:]
    decoded = decode_advert_payload(payload)
    if not decoded or not decoded.get("name"):
        return  # nothing worth publishing (no name bit set, or too short)

    out = {
        "pubkey": decoded["pubkey"],
        "name": decoded["name"],
        "lat": decoded["lat"],
        "lon": decoded["lon"],
        "updated": rec.get("timestamp"),
        "heard_by": rec.get("origin"),
    }
    topic = f"{NAMES_TOPIC_PREFIX}/{decoded['pubkey']}"
    client.publish(topic, json.dumps(out), qos=0, retain=True)
    log.info("resolved %s -> %r", decoded["pubkey"][:12] + "...", decoded["name"])


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("connected, subscribing %s", PACKETS_TOPIC)
        client.subscribe(PACKETS_TOPIC)
    else:
        log.warning("connect failed, rc=%s", rc)


def main():
    client = mqtt.Client(client_id="rvtc-meshcore-name-resolver")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
