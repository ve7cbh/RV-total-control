#!/usr/bin/env python3
"""
battery_current_mqtt.py — RVTC adaptor for the JSY-MK-229 300A battery current
shunt (HW-24), on RS-485 bus 485-7 (Waveshare gateway, 192.168.88.11:4001).

Follows the standard RVTC bridge-script pattern:
  - Fresh TCP connection per poll (Waveshare gateways, not the persistent-
    connection pattern used for serial-1's NMEA passthrough).
  - Raw Modbus RTU frames sent straight over the TCP socket — Waveshare's
    RTU-over-TCP passthrough, NOT Modbus-TCP/MBAP framing. Do not wrap
    requests in an MBAP header.
  - Flat MQTT topics under rvtc/sensors/battery_current/#, matching
    WN90_mqtt.py's raw-topic convention rather than a single aggregate JSON
    blob.

Device notes (JSY-MK-229 manual v1.4):
  - Factory default: Modbus address 1, 9600 8N1, all 4-byte register pairs
    are big-endian unsigned, high word first.
  - Reads registers 0x0100-0x011D in a single 03H request (30 registers /
    60 bytes) — covers voltage, current, active/reactive/apparent power,
    power factor, frequency, active/reactive energy, AC/DC mode, power
    direction, and split positive/negative (charge/discharge) energy.
  - The device needs its own 12-36VDC on V+/G to respond on Modbus at all —
    that's separate from the L+/N- DC voltage-under-test lines. If V+/G
    isn't powered yet, this script will just time out and retry, which is
    expected, not a bug.

Requires: paho-mqtt (pip install paho-mqtt --break-system-packages, if not
already present from the other bridge scripts).
"""

import logging
import socket
import struct
import time
import json

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_IP = "192.168.88.11"   # 485-7, per RVTC System Reference Section 3
GATEWAY_PORT = 4001
MODBUS_ADDR = 1                # factory default; confirm on-device if changed
SOCKET_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 1.0

MQTT_BROKER = "localhost"      # mosquitto container publishes 1883 on the host
MQTT_PORT = 1883
MQTT_CLIENT_ID = "battery_current_mqtt"
MQTT_TOPIC_BASE = "rvtc/sensors/battery_current"

START_REGISTER = 0x0100
REGISTER_COUNT = 0x1E          # 30 registers, 0x0100..0x011D inclusive

LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("battery_current_mqtt")


# ---------------------------------------------------------------------------
# Modbus RTU (CRC16 + raw frame construction, per JSY-MK-229 manual Section 4)
# ---------------------------------------------------------------------------

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_request(addr: int, start_reg: int, count: int) -> bytes:
    body = struct.pack(">BBHH", addr, 0x03, start_reg, count)
    crc = crc16_modbus(body)
    # CRC is appended low byte first, per spec.
    return body + struct.pack("<H", crc)


def parse_read_response(resp: bytes, addr: int, expected_words: int) -> bytes:
    """Validate and return the raw register payload bytes."""
    if len(resp) < 5:
        raise ValueError(f"response too short ({len(resp)} bytes)")

    if resp[0] != addr:
        raise ValueError(f"address mismatch: got {resp[0]}, expected {addr}")

    func = resp[1]
    if func & 0x80:
        err_code = resp[2] if len(resp) > 2 else None
        raise ValueError(f"slave returned exception, error code {err_code}")
    if func != 0x03:
        raise ValueError(f"unexpected function code {func:#x}")

    byte_count = resp[2]
    expected_bytes = expected_words * 2
    if byte_count != expected_bytes:
        raise ValueError(
            f"byte count mismatch: device reported {byte_count}, "
            f"expected {expected_bytes}"
        )

    payload = resp[3:3 + byte_count]
    crc_received = resp[3 + byte_count: 5 + byte_count]
    crc_calc = crc16_modbus(resp[:3 + byte_count])
    if crc_received != struct.pack("<H", crc_calc):
        raise ValueError("CRC mismatch")

    return payload


def poll_registers(addr: int, start_reg: int, count: int) -> bytes:
    """Open a fresh TCP connection, send one RTU read request, return payload."""
    request = build_read_request(addr, start_reg, count)
    with socket.create_connection(
        (GATEWAY_IP, GATEWAY_PORT), timeout=SOCKET_TIMEOUT_S
    ) as sock:
        sock.settimeout(SOCKET_TIMEOUT_S)
        sock.sendall(request)
        # Expected reply length: addr+func+bytecount+payload+crc
        expected_len = 3 + (count * 2) + 2
        resp = b""
        deadline = time.monotonic() + SOCKET_TIMEOUT_S
        while len(resp) < expected_len and time.monotonic() < deadline:
            chunk = sock.recv(256)
            if not chunk:
                break
            resp += chunk
    return parse_read_response(resp, addr, count)


# ---------------------------------------------------------------------------
# Register decoding
# ---------------------------------------------------------------------------

def reg_offset(register: int) -> int:
    """Byte offset into the payload for a given absolute register address."""
    return (register - START_REGISTER) * 2


def u32(payload: bytes, register: int) -> int:
    """Unsigned 4-byte value for the register pair starting at `register`."""
    off = reg_offset(register)
    return struct.unpack(">I", payload[off:off + 4])[0]


def u16(payload: bytes, register: int) -> int:
    """Unsigned 2-byte value for the single register at `register`."""
    off = reg_offset(register)
    return struct.unpack(">H", payload[off:off + 2])[0]


def decode(payload: bytes) -> dict:
    """payload is the raw 60-byte block for registers 0x0100..0x011D."""
    voltage = u32(payload, 0x0100) / 10000.0          # V
    current = u32(payload, 0x0102) / 10000.0          # A
    active_power = u32(payload, 0x0104) / 10000.0     # W
    reactive_power = u32(payload, 0x0106) / 10000.0   # var
    apparent_power = u32(payload, 0x0108) / 10000.0   # VA
    power_factor = u32(payload, 0x010A) / 1000.0
    frequency = u32(payload, 0x010C) / 100.0          # Hz
    active_energy = u32(payload, 0x010E) / 1000.0     # kWh
    reactive_energy = u32(payload, 0x0110) / 1000.0   # kvarh
    supply_mode_raw = u32(payload, 0x0112)            # 1=AC, 2=DC

    active_dir_raw = u16(payload, 0x0114)             # single register
    reactive_dir_raw = u16(payload, 0x0115)           # single register

    positive_active_energy = u32(payload, 0x0116) / 1000.0   # kWh
    negative_active_energy = u32(payload, 0x0118) / 1000.0   # kWh
    positive_reactive_energy = u32(payload, 0x011A) / 1000.0  # kvarh
    negative_reactive_energy = u32(payload, 0x011C) / 1000.0  # kvarh

    supply_mode = {1: "AC", 2: "DC"}.get(supply_mode_raw, f"unknown({supply_mode_raw})")
    direction = "charging" if active_dir_raw == 1 else "discharging"
    signed_current = current if active_dir_raw == 1 else -current
    signed_power = active_power if active_dir_raw == 1 else -active_power

    return {
        "voltage": round(voltage, 3),
        "current": round(current, 3),
        "current_signed": round(signed_current, 3),
        "power": round(active_power, 3),
        "power_signed": round(signed_power, 3),
        "reactive_power": round(reactive_power, 3),
        "apparent_power": round(apparent_power, 3),
        "power_factor": round(power_factor, 3),
        "frequency": round(frequency, 2),
        "active_energy_total": round(active_energy, 3),
        "reactive_energy_total": round(reactive_energy, 3),
        "active_energy_positive": round(positive_active_energy, 3),
        "active_energy_negative": round(negative_active_energy, 3),
        "reactive_energy_positive": round(positive_reactive_energy, 3),
        "reactive_energy_negative": round(negative_reactive_energy, 3),
        "supply_mode": supply_mode,
        "direction": direction,
        "active_power_direction_raw": active_dir_raw,
        "reactive_power_direction_raw": reactive_dir_raw,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    client.loop_start()

    log.info(
        "Starting battery_current_mqtt: gateway %s:%s, modbus addr %s, "
        "poll every %ss",
        GATEWAY_IP, GATEWAY_PORT, MODBUS_ADDR, POLL_INTERVAL_S,
    )

    consecutive_failures = 0

    try:
        while True:
            start = time.monotonic()
            try:
                payload = poll_registers(MODBUS_ADDR, START_REGISTER, REGISTER_COUNT)
                fields = decode(payload)
                for key, value in fields.items():
                    client.publish(f"{MQTT_TOPIC_BASE}/{key}", value, retain=False)
                # Aggregate JSON on its own topic, for Telegraf's mqtt_consumer
                # (json data_format) — the flat per-field topics above are for
                # MQTT Explorer / Home Assistant, not meant to be re-parsed by
                # Telegraf. See config/telegraf/telegraf_battery.conf.
                client.publish(
                    f"{MQTT_TOPIC_BASE}/json", json.dumps(fields), retain=False
                )
                if consecutive_failures:
                    log.info("Recovered after %d failed poll(s)", consecutive_failures)
                consecutive_failures = 0
                log.debug("Published: %s", fields)
            except (OSError, ValueError) as exc:
                consecutive_failures += 1
                # Common and expected while V+/G is unpowered: connection
                # refused / timed out / no response. Log at WARNING, not
                # ERROR, until it's been failing a long time.
                level = logging.WARNING if consecutive_failures < 12 else logging.ERROR
                log.log(level, "Poll failed (%d in a row): %s", consecutive_failures, exc)

            elapsed = time.monotonic() - start
            time.sleep(max(0.0, POLL_INTERVAL_S - elapsed))
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
