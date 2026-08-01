#!/usr/bin/env python3
"""
eid041_mqtt.py — Ebyte EID041-G01S temperature/humidity bridge (equipment
enclosure, where the J45 lives), for RVTC's unified MQTT namespace.

Hardware: Ebyte EID041-G01S (SHT30 sensor variant), RS-485, Modbus RTU.
Wired 2026-07-31 into serial-4 on the HF5142B general-purpose serial
gateway (192.168.88.16:4001) rather than the Waveshare 485-x array --
the enclosure sits right next to the HF5142B, so a 20cm cable made more
sense than a 3m run to the nearest free Waveshare port. Single device on
this line (point-to-point, not a shared bus), so the factory-default
Modbus address (1) was left as-is -- no collision risk the way the KWS
meters had.

Same fresh-connection-per-poll pattern as every other RVTC Modbus bridge
(see System Reference Section 8) -- not because this gateway is known to
drop idle connections the way the Waveshare units do (unconfirmed either
way for the HF5142B), but for consistency with the rest of the fleet
rather than assuming this one gateway behaves differently without
evidence.

Register map (confirmed against the manual's own worked examples,
including a byte-for-byte CRC check, before this script was written):
    0x0000  Input register, FC 0x04, int16, x0.1 = actual °C
            (two's complement for negative -- e.g. 0xFF9B = -10.1°C)
    0x0001  Input register, FC 0x04, uint16, x0.1 = actual %RH
This script reads both in a single 2-register request starting at 0x0000
-- the exact request the manual itself demonstrates
(01 04 00 00 00 02 71 CB), just automated.

Publishes:
    rvtc/sensors/enclosure/temperature_c
    rvtc/sensors/enclosure/humidity_pct
    rvtc/sensors/enclosure/status         "OK" (placeholder for future health checks)
    rvtc/sensors/enclosure/availability   "online" / "offline" (LWT)

NOT YET added to a telegraf_*.conf -- per the System Reference's own
documented gotcha, a new Telegraf source needs both a new config file AND
a new bind-mount line in docker-compose.yml, then `docker compose up -d
telegraf` (a plain `docker restart` won't pick up a new mount). Deciding
whether/how to persist this to InfluxDB is a deliberate separate step,
not bundled into this bridge script.

Requires:
    pip3 install paho-mqtt --break-system-packages
"""

import logging
import socket
import time

import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────────────────────────────
GATEWAY_HOST = "192.168.88.16"   # serial-4, HF5142B
GATEWAY_PORT = 4001

SLAVE_ADDR = 0x01   # factory default -- single device on this line, no
                     # conflict risk, left unchanged

TEMP_HUMIDITY_REG_START = 0x0000
TEMP_HUMIDITY_REG_COUNT = 2   # temp (0x0000) + humidity (0x0001) in one request

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
TOPIC_BASE = "rvtc/sensors/enclosure"
AVAILABILITY_TOPIC = f"{TOPIC_BASE}/availability"

POLL_INTERVAL_SECONDS = 30   # enclosure conditions change slowly -- no
                              # need for the IMU's 2 Hz cadence here
SOCKET_TIMEOUT = 2.0
RETRY_SECONDS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s eid041_mqtt: %(message)s",
)
log = logging.getLogger("eid041_mqtt")


# ── Modbus RTU-over-TCP framing -- self-contained copy, matching the
# project's existing per-script style (see imu_mqtt.py's own docstring on
# this) rather than a shared import. CRC verified byte-for-byte against
# the EID041 manual's own worked examples before this script was written.

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_read_request(slave: int, start_reg: int, count: int) -> bytes:
    body = bytes([
        slave, 0x04,  # function 0x04 = read input registers
        (start_reg >> 8) & 0xFF, start_reg & 0xFF,
        (count >> 8) & 0xFF, count & 0xFF,
    ])
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def drain_socket(sock: socket.socket, timeout: float = 0.3) -> bytes:
    """Reads and discards whatever's immediately available, up to `timeout`
    seconds of silence. Used to clear the HF5142B's unprompted Telnet
    negotiation preamble (confirmed 2026-07-31: FF FB 01 / FF FB 03 /
    FF FB 00 / FF FE 01 / FF FD 00 arrive right after connect, before any
    real serial data) -- this port runs a Telnet server on its TCP side
    regardless of the web UI's "Protocol" setting, which only governs the
    serial-side interpretation, not this transport-layer framing."""
    sock.settimeout(timeout)
    drained = b""
    try:
        while True:
            chunk = sock.recv(256)
            if not chunk:
                break
            drained += chunk
    except socket.timeout:
        pass
    return drained


def read_registers(host: str, port: int, slave: int, start_reg: int, count: int):
    request = build_read_request(slave, start_reg, count)
    expected_len = 3 + (count * 2) + 2

    total_expected = len(request) + expected_len  # echo, then the real response

    with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as sock:
        drain_socket(sock)   # clear the Telnet negotiation preamble first
        sock.settimeout(SOCKET_TIMEOUT)
        sock.sendall(request)
        response = b""
        while len(response) < total_expected:
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk

    # This gateway echoes whatever we send (Telnet WILL ECHO, unanswered by
    # us -- confirmed 2026-07-31) -- strip that echo off the front before
    # treating the remainder as the actual device response.
    if response.startswith(request):
        response = response[len(request):]

    if len(response) != expected_len:
        raise ValueError(f"short response: got {len(response)} bytes, expected {expected_len}")
    if response[0] != slave or response[1] != 0x04:
        raise ValueError(f"unexpected header: {response[:3].hex()}")

    byte_count = response[2]
    data = response[3:3 + byte_count]
    recv_crc = response[3 + byte_count:3 + byte_count + 2]
    calc_crc = crc16_modbus(response[:3 + byte_count])
    if recv_crc[0] != (calc_crc & 0xFF) or recv_crc[1] != ((calc_crc >> 8) & 0xFF):
        raise ValueError("CRC mismatch")

    return [(data[i] << 8) | data[i + 1] for i in range(0, byte_count, 2)]


def to_s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


# ── MQTT ──────────────────────────────────────────────────────────────────

def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id="rvtc-eid041-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.will_set(AVAILABILITY_TOPIC, payload="offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
    return client


def publish(client: mqtt.Client, topic: str, value) -> None:
    if value is None:
        return
    client.publish(topic, payload=value, retain=False)


# ── Poll cycle ────────────────────────────────────────────────────────────

def poll_once(client: mqtt.Client) -> None:
    regs = read_registers(
        GATEWAY_HOST, GATEWAY_PORT, SLAVE_ADDR,
        TEMP_HUMIDITY_REG_START, TEMP_HUMIDITY_REG_COUNT,
    )
    temp_c = to_s16(regs[0]) / 10
    humidity_pct = regs[1] / 10

    publish(client, f"{TOPIC_BASE}/temperature_c", round(temp_c, 1))
    publish(client, f"{TOPIC_BASE}/humidity_pct", round(humidity_pct, 1))
    publish(client, f"{TOPIC_BASE}/status", "OK")


def run() -> None:
    client = make_mqtt_client()
    while True:
        try:
            poll_once(client)
            client.publish(AVAILABILITY_TOPIC, payload="online", retain=True)
        except (OSError, ValueError) as e:
            log.warning(f"poll failed ({e}); retrying in {RETRY_SECONDS}s")
            client.publish(AVAILABILITY_TOPIC, payload="offline", retain=True)
            time.sleep(RETRY_SECONDS)
            continue
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped")
