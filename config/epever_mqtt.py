#!/usr/bin/env python3
"""
epever_mqtt.py — EPEVER MPPT60 Modbus → MQTT bridge
=====================================================
RVTC Phase 3 — Solar data into the broker

Polls EPEVER MPPT60 via Waveshare RS-485 gateway (Modbus TCP)
and publishes all telemetry to Mosquitto on the rvtc/sensors/solar/
topic tree.  This gets solar data flowing into InfluxDB immediately,
independent of HA onboarding status.

Connection:
  Gateway: 192.168.88.5:4001
  Slave:   1
  Baud:    115200 (gateway serial config — not this script's concern)

MQTT broker: 192.168.88.3:1883 (Mosquitto on J45)

Topic schema: rvtc/sensors/solar/<field>
  Consistent with Phase 7 normalised MQTT schema (Section 9.1)

Run:
  python3 epever_mqtt.py
  # or daemonise:
  nohup python3 epever_mqtt.py >> /var/log/epever_mqtt.log 2>&1 &

Dependencies:
  pip3 install pymodbus paho-mqtt  (or pip3 install pymodbus paho-mqtt --break-system-packages)

To run as a Docker container, see Dockerfile.epever_mqtt in this repo.

Register reference (EPEVER Tracer AN / BN series, literal PDU addresses):
  All holding registers, FC 03. Addresses are 0-based PDU (no Modicon offset).
  Match mbpoll with -0 flag and HA pymodbus (which also addresses literally).
"""

import time
import json
import logging
import struct
from datetime import datetime, timezone

from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt

# ── Configuration ─────────────────────────────────────────────────────────────

MODBUS_HOST = "192.168.88.5"
MODBUS_PORT = 4001
MODBUS_SLAVE = 1
MODBUS_TIMEOUT = 5        # seconds

MQTT_HOST = "192.168.88.3"
MQTT_PORT = 1883
MQTT_TOPIC_BASE = "rvtc/sensors/solar"
MQTT_RETAIN = True        # retain last value so dashboard always shows something

POLL_INTERVAL = 3        # seconds between full register reads

LOG_LEVEL = logging.INFO

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("epever_mqtt")

# ── Register map ──────────────────────────────────────────────────────────────
# (address, count, scale, field_name, unit)
# For 32-bit registers count=2; raw = (regs[1] << 16) | regs[0]  (low word first)

SINGLE_REGISTERS = [
    # address  scale    field                          unit
    (12544,    0.01,   "pv_voltage",                  "V"),
    (12545,    0.01,   "pv_current",                  "A"),
    (12548,    0.01,   "battery_voltage",              "V"),
    (12549,    0.01,   "charging_current",             "A"),
    (12556,    0.01,   "load_voltage",                 "V"),
    (12557,    0.01,   "load_current",                 "A"),
    (12560,    0.01,   "battery_temperature",          "C"),
    (12561,    0.01,   "controller_temperature",       "C"),
    (12570,    1.0,    "battery_soc",                  "%"),
    (12800,    1.0,    "charging_status_raw",          ""),
    (12801,    1.0,    "battery_status_raw",           ""),
]

DOUBLE_REGISTERS = [
    # address  scale    field                          unit
    (12546,    0.01,   "pv_power",                    "W"),    # 0x3102-3103
    (12550,    0.01,   "charging_power",              "W"),    # 0x3106-3107
    (13068,    0.01,   "daily_energy_kwh",            "kWh"),  # 0x330C-330D
    (13074,    0.01,   "total_energy_kwh",            "kWh"),  # 0x3312-3313
]

# ── Charging status decode ─────────────────────────────────────────────────────
# D3-D2 of register 0x3200 — these are the bits that indicate charge stage

CHARGE_STAGE = {0: "none", 1: "float", 2: "boost", 3: "equalization"}

def decode_charging_status(raw: int) -> dict:
    """Decode 0x3200 charging equipment status register into named fields."""
    input_voltage_status = (raw >> 14) & 0x03
    charge_stage_code    = (raw >> 2)  & 0x03
    load_on              = bool((raw >> 4) & 0x01)
    charging_running     = bool((raw >> 1) & 0x01)
    controller_running   = bool(raw & 0x01)
    return {
        "input_voltage_status": input_voltage_status,
        "charge_stage":         CHARGE_STAGE.get(charge_stage_code, "unknown"),
        "load_on":              load_on,
        "charging_running":     charging_running,
        "controller_running":   controller_running,
    }

# ── Modbus helpers ─────────────────────────────────────────────────────────────

def read_single(client: ModbusTcpClient, address: int, slave: int) -> int | None:
    result = client.read_input_registers(address, count=1, device_id=slave)
    if result.isError():
        log.warning("Modbus error reading address %d: %s", address, result)
        return None
    return result.registers[0]

def read_double(client: ModbusTcpClient, address: int, slave: int) -> int | None:
    """Read two contiguous registers and combine as 32-bit (low word first)."""
    result = client.read_input_registers(address, count=2, device_id=slave)
    if result.isError():
        log.warning("Modbus error reading address %d+1: %s", address, result)
        return None
    low, high = result.registers[0], result.registers[1]
    return (high << 16) | low

# ── MQTT helpers ──────────────────────────────────────────────────────────────

def publish(mqttc: mqtt.Client, field: str, value, unit: str = ""):
    topic = f"{MQTT_TOPIC_BASE}/{field}"
    # Publish scalar value as plain string for easy Grafana/HA consumption
    payload = f"{value}"
    mqttc.publish(topic, payload, retain=MQTT_RETAIN)
    log.debug("→ %s = %s %s", topic, payload, unit)

def publish_json(mqttc: mqtt.Client, suffix: str, data: dict):
    topic = f"{MQTT_TOPIC_BASE}/{suffix}"
    mqttc.publish(topic, json.dumps(data), retain=MQTT_RETAIN)
    log.debug("→ %s = %s", topic, data)

# ── Main poll loop ─────────────────────────────────────────────────────────────

def poll_once(modbus_client: ModbusTcpClient, mqttc: mqtt.Client):
    timestamp = datetime.now(timezone.utc).isoformat()
    errors = 0

    # Single 16-bit registers
    for address, scale, field, unit in SINGLE_REGISTERS:
        raw = read_single(modbus_client, address, MODBUS_SLAVE)
        if raw is None:
            errors += 1
            continue
        value = round(raw * scale, 2 if scale < 1 else 0)
        publish(mqttc, field, value, unit)

        # Also decode status register into named sub-topics
        if field == "charging_status_raw":
            pass
#             decoded = decode_charging_status(raw)
#             for k, v in decoded.items():
#                 publish(mqttc, k, v)

    # Double 32-bit registers
    for address, scale, field, unit in DOUBLE_REGISTERS:
        raw = read_double(modbus_client, address, MODBUS_SLAVE)
        if raw is None:
            errors += 1
            continue
        value = round(raw * scale, 2)
        publish(mqttc, field, value, unit)

    # Derived: PV power = pv_voltage × pv_current (cross-check against register)
    # (just logged, not published separately — register value is authoritative)

    # Health heartbeat
    # publish(mqttc, "last_updated", timestamp)
    publish(mqttc, "poll_errors", errors)

    if errors:
        log.warning("Poll completed with %d register error(s)", errors)
    else:
        log.info("Poll OK — %s", timestamp)


def main():
    log.info("EPEVER MQTT bridge starting")
    log.info("  Modbus: %s:%d  slave %d", MODBUS_HOST, MODBUS_PORT, MODBUS_SLAVE)
    log.info("  MQTT:   %s:%d  base topic %s", MQTT_HOST, MQTT_PORT, MQTT_TOPIC_BASE)
    log.info("  Poll interval: %ds", POLL_INTERVAL)

    # MQTT client
    mqttc = mqtt.Client(client_id="epever_mqtt_bridge", clean_session=True)
    mqttc.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    mqttc.loop_start()

    # Modbus client — persistent TCP connection, reconnect on error
    modbus_client = ModbusTcpClient(
        host=MODBUS_HOST,
        port=MODBUS_PORT,
        timeout=MODBUS_TIMEOUT,
    )

    while True:
        try:
            if not modbus_client.is_socket_open():
                log.info("Connecting to Modbus gateway…")
                modbus_client.connect()

            poll_once(modbus_client, mqttc)

        except Exception as exc:
            log.error("Poll exception: %s — will retry in %ds", exc, POLL_INTERVAL)
            try:
                modbus_client.close()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
