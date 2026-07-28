#!/usr/bin/env python3
"""
samlux_mqtt.py — SAMLUX EVO-2212 Inverter-Charger Modbus → MQTT bridge
========================================================================
RVTC Phase 3 — EVO-2212 data into the broker

Polls SAMLUX EVO-2212 via Waveshare RS-485/2 gateway (Modbus TCP)
and publishes all telemetry to Mosquitto on rvtc/sensors/inverter/

Connection:
  Gateway: 192.168.88.6:4001
  Slave:   1
  Baud:    9600 8N1 (set on gateway port 2 — not this script's concern)
  FC:      03 (holding registers)

MQTT broker: 192.168.88.3:1883
Topic base:  rvtc/sensors/inverter/

Systemd service: config/samlux_mqtt.service
Log: logs/samlux_mqtt.log

Register addresses: SAMLUX EVO-2212 manual (NDA — not committed to repo)
All addresses are literal/direct (0-based PDU) — no Modicon offset.
Use mbpoll with -0 flag for equivalent manual verification.

Signed registers (int16): invert/charge current, invert/charge watt,
battery current, external current, all temperatures.
Unsigned registers (uint16): everything else.

Dependencies:
  pip3 install pymodbus paho-mqtt --break-system-packages
"""

import time
import logging
import struct
from datetime import datetime, timezone

from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt

# ── Configuration ─────────────────────────────────────────────────────────────

MODBUS_HOST    = "192.168.88.6"
MODBUS_PORT    = 4001
MODBUS_SLAVE   = 1
MODBUS_TIMEOUT = 5

MQTT_HOST      = "192.168.88.3"
MQTT_PORT      = 1883
MQTT_BASE      = "rvtc/sensors/inverter"
MQTT_RETAIN    = True

POLL_INTERVAL  = 3        # seconds

LOG_LEVEL = logging.INFO

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("samlux_mqtt")

# ── Register map ──────────────────────────────────────────────────────────────
# (address, scale, field, unit, signed)
# All holding registers FC03, slave 1, literal/direct addressing

REGISTERS = [
    # address  scale    field                        unit     signed
    (256,      1.0,    "status_gen_input",           "",      False),
    (257,      0.01,   "freq_gen_input",             "Hz",    False),
    (258,      0.01,   "voltage_gen_input",          "V",     False),
    (259,      1.0,    "status_grid_input",          "",      False),
    (260,      0.01,   "freq_grid_input",            "Hz",    False),
    (261,      0.01,   "voltage_grid_input",         "V",     False),   # CONFIRMED 119.03V
    (262,      0.01,   "input_current",              "A",     False),   # CONFIRMED 4.41A
    (264,      1.0,    "input_va",                   "VA",    False),
    (266,      1.0,    "input_watt",                 "W",     False),
    (268,      0.01,   "output_frequency",           "Hz",    False),
    (269,      0.01,   "output_voltage",             "V",     False),
    (270,      0.01,   "invert_charge_current",      "A",     True),    # signed
    (272,      1.0,    "invert_charge_va",           "VA",    False),
    (274,      1.0,    "invert_charge_watt",         "W",     True),    # signed
    (276,      0.001,  "battery_voltage",            "V",     False),   # CONFIRMED 13.005V
    (277,      0.1,    "battery_current",            "A",     True),    # signed
    (278,      0.1,    "external_current",           "A",     True),    # signed
    (279,      0.1,    "battery_temperature",        "C",     True),    # signed, not used for LiFePO4
    (280,      0.1,    "transformer_temperature",    "C",     True),    # signed
    (281,      0.1,    "busbar_temperature",         "C",     True),    # signed
    (282,      0.1,    "heatsink_temperature",       "C",     True),    # signed
    (283,      1.0,    "fan_speed",                  "",      False),
    (284,      1.0,    "operating_mode",             "",      False),   # KEY for Tier 1 logic
    (285,      1.0,    "error_code",                 "",      False),
    (286,      1.0,    "charge_stage",               "",      False),
    (287,      0.01,   "firmware_version",           "",      False),
    (288,      0.001,  "compensating_voltage",       "V",     False),
]

# Operating mode decode (register 284) — key for Tier 1 load management
# Values from EVO-2212 manual — confirm against live readings

OPERATING_MODES = {
    0: "standby",       # confirmed — combined standby/fault per manufacturer doc
    1: "inverter",      # on battery — CONFIRMED live 2026-07-05 and 2026-07-21
    2: "charging",      # on grid, charging + passthrough — confirmed live
    3: "power_saving",  # confirmed per manufacturer doc — NOT "line" as previously guessed
}
   
# ── Modbus helpers ─────────────────────────────────────────────────────────────

def read_register(client: ModbusTcpClient, address: int, signed: bool) -> int | None:
    result = client.read_holding_registers(address, count=1, device_id=MODBUS_SLAVE)
    if result.isError():
        log.warning("Modbus error reg %d: %s", address, result)
        return None
    raw = result.registers[0]
    if signed and raw > 32767:
        raw -= 65536
    return raw

# ── MQTT helper ───────────────────────────────────────────────────────────────

def publish(mqttc: mqtt.Client, field: str, value):
    topic = f"{MQTT_BASE}/{field}"
    mqttc.publish(topic, str(value), retain=MQTT_RETAIN)
    log.debug("→ %s = %s", topic, value)

# ── Poll ──────────────────────────────────────────────────────────────────────

def poll_once(client: ModbusTcpClient, mqttc: mqtt.Client):
    errors = 0

    for address, scale, field, unit, signed in REGISTERS:
        raw = read_register(client, address, signed)
        if raw is None:
            errors += 1
            continue

        # Scale — use appropriate precision based on scale factor
        if scale == 1.0:
            value = raw
        elif scale < 0.01:
            value = round(raw * scale, 3)
        elif scale < 0.1:
            value = round(raw * scale, 2)
        else:
            value = round(raw * scale, 2)

        publish(mqttc, field, value)

        # Also publish decoded operating mode as text
        if field == "operating_mode":
            mode_text = OPERATING_MODES.get(int(raw), f"unknown_{raw}")
            publish(mqttc, "operating_mode_text", mode_text)

    publish(mqttc, "poll_errors", errors)

    if errors:
        log.warning("Poll completed with %d error(s)", errors)
    else:
        log.info("Poll OK — %s", datetime.now(timezone.utc).isoformat())

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("SAMLUX MQTT bridge starting")
    log.info("  Modbus: %s:%d  slave %d", MODBUS_HOST, MODBUS_PORT, MODBUS_SLAVE)
    log.info("  MQTT:   %s:%d  base %s", MQTT_HOST, MQTT_PORT, MQTT_BASE)
    log.info("  Poll interval: %ds", POLL_INTERVAL)

    mqttc = mqtt.Client(client_id="samlux_mqtt_bridge", clean_session=True)
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

            poll_once(modbus_client, mqttc)

        except Exception as exc:
            log.error("Poll exception: %s — retrying in %ds", exc, POLL_INTERVAL)
            try:
                modbus_client.close()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
