#!/usr/bin/env python3
"""
kws_mqtt.py — KWS-303L AC Power Meter Modbus → MQTT bridge
============================================================
RVTC Phase 3 — Grid and generator power data into the broker

Polls KWS-303L grid meter (slave 1) and optionally generator meter
(slave 2) via Waveshare RS-485/3 gateway (Modbus TCP) and publishes
all telemetry to Mosquitto on the rvtc/sensors/grid/ and
rvtc/sensors/generator/ topic trees.

Connection:
  Gateway: 192.168.88.7:4001
  Grid meter:      Modbus slave 1
  Generator meter: Modbus slave 2 (set on bench before install)
  Baud: 9600 8E1 (set on gateway port 3 — Even parity)

MQTT broker: 192.168.88.3:1883

Register map: KWS-303L_Register_Map_RVTC.docx (community reverse-engineered)
All addresses are literal/direct (0-based PDU) — same convention as
SAMLUX and EPEVER. Use -0 flag with mbpoll for equivalent manual polls.

Systemd service: config/kws_mqtt.service
Log: logs/kws_mqtt.log

Dependencies:
  pip3 install pymodbus paho-mqtt --break-system-packages
"""

import time
import logging
from datetime import datetime, timezone

from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt

# ── Configuration ─────────────────────────────────────────────────────────────

MODBUS_HOST    = "192.168.88.7"
MODBUS_PORT    = 4001
MODBUS_TIMEOUT = 5

MQTT_HOST      = "192.168.88.3"
MQTT_PORT      = 1883
MQTT_RETAIN    = True

POLL_INTERVAL  = 10        # seconds

# Set to True once generator meter is physically wired and slave 2 confirmed
GENERATOR_ENABLED = False

LOG_LEVEL = logging.INFO

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("kws_mqtt")

# ── Register map ──────────────────────────────────────────────────────────────
# (address, scale, field_name, unit)
# Reference: KWS-303L_Register_Map_RVTC.docx

KWS_REGISTERS = [
    # address  scale    field               unit
    (14,       0.01,   "voltage",           "V"),     # Active Voltage
    (18,       0.001,  "current",           "A"),     # Active Current
    (26,       0.1,    "power",             "W"),     # Active Power — gain=10 confirmed
    (48,       0.001,  "power_factor",      ""),      # Power Factor 0–1
    (51,       0.01,   "frequency",         "Hz"),    # Active Frequency
    (55,       0.001,  "energy_kwh",        "kWh"),   # Consumed Energy (cumulative)
    (60,       1.0,    "temperature",       "C"),     # Internal NTC temperature
    (62,       1.0,    "alarm_code",        ""),      # 0=none,1=OV,2=UV,4=OC,32=OT
]

# ── Modbus helper ──────────────────────────────────────────────────────────────

def read_register(client: ModbusTcpClient, address: int, slave: int) -> int | None:
    result = client.read_holding_registers(address, count=1, device_id=slave)
    if result.isError():
        log.warning("Modbus error slave %d reg %d: %s", slave, address, result)
        return None
    return result.registers[0]

# ── MQTT helper ───────────────────────────────────────────────────────────────

def publish(mqttc: mqtt.Client, topic_base: str, field: str, value):
    topic = f"{topic_base}/{field}"
    mqttc.publish(topic, str(value), retain=MQTT_RETAIN)
    log.debug("→ %s = %s", topic, value)

# ── Poll one meter ─────────────────────────────────────────────────────────────

def poll_meter(client: ModbusTcpClient, mqttc: mqtt.Client,
               slave: int, topic_base: str, label: str):
    errors = 0
    for address, scale, field, unit in KWS_REGISTERS:
        raw = read_register(client, address, slave)
        if raw is None:
            errors += 1
            continue
        # Handle signed 16-bit (e.g. reg 55 shows as negative in mbpoll)
        if raw > 32767:
            raw = raw  # keep unsigned — values are all positive for this meter
        value = round(raw * scale, 3 if scale < 0.01 else 2 if scale < 0.1 else 1)
        publish(mqttc, topic_base, field, value)

    publish(mqttc, topic_base, "poll_errors", errors)
    if errors:
        log.warning("%s poll: %d error(s)", label, errors)
    else:
        log.info("%s poll OK", label)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("KWS MQTT bridge starting")
    log.info("  Modbus: %s:%d", MODBUS_HOST, MODBUS_PORT)
    log.info("  MQTT:   %s:%d", MQTT_HOST, MQTT_PORT)
    log.info("  Generator meter: %s", "enabled" if GENERATOR_ENABLED else "disabled")
    log.info("  Poll interval: %ds", POLL_INTERVAL)

    mqttc = mqtt.Client(client_id="kws_mqtt_bridge", clean_session=True)
    mqttc.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    mqttc.loop_start()

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

            # Grid meter — slave 1
            poll_meter(modbus_client, mqttc,
                       slave=1,
                       topic_base="rvtc/sensors/grid",
                       label="Grid")

            # Generator meter — slave 2 (enable when physically installed)
            if GENERATOR_ENABLED:
                poll_meter(modbus_client, mqttc,
                           slave=2,
                           topic_base="rvtc/sensors/generator",
                           label="Generator")

        except Exception as exc:
            log.error("Poll exception: %s — retrying in %ds", exc, POLL_INTERVAL)
            try:
                modbus_client.close()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
