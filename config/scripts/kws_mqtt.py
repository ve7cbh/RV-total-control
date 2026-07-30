#!/usr/bin/env python3
"""
kws_mqtt.py — KWS-303L AC Power Meter Modbus → MQTT bridge
============================================================
RVTC Phase 3 — Grid and generator power data into the broker

Polls KWS-303L grid meter (slave 1) and generator meter (slave 2) via
Waveshare RS-485/3 gateway (Modbus TCP) and publishes all telemetry to
Mosquitto on the rvtc/sensors/grid/ and rvtc/sensors/generator/ topic
trees.

Connection:
  Gateway: 192.168.88.7:4001
  Grid meter:      Modbus slave 1
  Generator meter: Modbus slave 2
  Baud: 9600 8E1 (set on gateway port 3 — Even parity)

MQTT broker: 192.168.88.3:1883

Register map: KWS-303L_Register_Map_RVTC.docx (community reverse-engineered)
All addresses are literal/direct (0-based PDU) — same convention as
SAMLUX and EPEVER. Use -0 flag with mbpoll for equivalent manual polls.

Registers cluster into two contiguous blocks and are read one Modbus
transaction per block (rather than one transaction per field) to
minimise bus time per poll cycle.

Only one of grid/generator is normally powered at a time (RV runs on
either shore/grid power or the generator, not both). MODBUS_TIMEOUT is
kept short (0.5s) so that polling the currently-unpowered meter doesn't
stall the cycle — a dead meter simply won't respond, and a short timeout
keeps that cost small instead of eating the default multi-second
retry/timeout window. Connection-state logging only fires on
online/offline transitions, not on every failed poll, since one meter
being dark is the expected steady state roughly half the time.

Systemd service: config/kws_mqtt.service
Log: journal (see config/kws_mqtt.service — StandardOutput/StandardError=journal)

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
MODBUS_TIMEOUT = 0.5      # short on purpose — see module docstring

MQTT_HOST      = "192.168.88.3"
MQTT_PORT      = 1883
MQTT_RETAIN    = True

POLL_INTERVAL  = 2        # seconds

GENERATOR_ENABLED = True

LOG_LEVEL = logging.INFO

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("kws_mqtt")

# pymodbus has its own internal logger that logs retries/failures directly
# at ERROR level, independent of our LOG_LEVEL above — it propagates to the
# root logger and inherits our format, which makes it look like it's coming
# from this script. Turn it down so a dead meter doesn't spam the journal.
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

# ── Register map ──────────────────────────────────────────────────────────────
# (block, offset_within_block, scale, field_name, unit)
# Reference: KWS-303L_Register_Map_RVTC.docx
# Registers cluster into two contiguous blocks — read each block in one
# Modbus transaction, then slice fields out by their offset from the block start.

BLOCK1_START = 14   # covers registers 14–26 (voltage, current, power)
BLOCK1_COUNT = 13   # 26 - 14 + 1

BLOCK2_START = 48   # covers registers 48–63 (power_factor .. relay_state)
BLOCK2_COUNT = 16   # 63 - 48 + 1

KWS_REGISTERS = [
    (1,  14 - BLOCK1_START,  0.01,   "voltage",       "V"),   # reg 14
    (1,  18 - BLOCK1_START,  0.001,  "current",       "A"),   # reg 18
    (1,  26 - BLOCK1_START,  0.1,    "power",         "W"),   # reg 26
    (2,  48 - BLOCK2_START,  0.001,  "power_factor",  ""),    # reg 48
    (2,  51 - BLOCK2_START,  0.01,   "frequency",     "Hz"),  # reg 51
    (2,  55 - BLOCK2_START,  0.001,  "energy_kwh",    "kWh"), # reg 55
    (2,  60 - BLOCK2_START,  1.0,    "temperature",   "C"),   # reg 60
    (2,  62 - BLOCK2_START,  1.0,    "alarm_code",    ""),    # reg 62
    (2,  63 - BLOCK2_START,  1.0,    "relay_state",   ""),    # reg 63
]

# ── Per-meter connection state (for transition-only logging) ──────────────────

METER_ONLINE = {1: True, 2: True}

# ── Modbus helpers ─────────────────────────────────────────────────────────────

def read_block(client: ModbusTcpClient, address: int, count: int, slave: int):
    """Read a contiguous block of holding registers in one Modbus transaction.

    Catches connection-level exceptions (e.g. "No response received...
    CLOSING CONNECTION") as well as Modbus error responses, and returns
    None for either case. This keeps all failure handling flowing through
    poll_meter()'s transition-only logging instead of letting an exception
    propagate up and get logged unconditionally in main().
    """
    try:
        result = client.read_holding_registers(address, count=count, device_id=slave)
    except Exception as exc:
        log.debug("Modbus exception slave %d block @%d (count=%d): %s",
                  slave, address, count, exc)
        return None
    if result.isError():
        log.debug("Modbus error slave %d block @%d (count=%d): %s",
                  slave, address, count, result)
        return None
    return result.registers

# ── MQTT helper ───────────────────────────────────────────────────────────────

def publish(mqttc: mqtt.Client, topic_base: str, field: str, value):
    topic = f"{topic_base}/{field}"
    mqttc.publish(topic, str(value), retain=MQTT_RETAIN)
    log.debug("→ %s = %s", topic, value)

# ── Poll one meter ─────────────────────────────────────────────────────────────

def poll_meter(client: ModbusTcpClient, mqttc: mqtt.Client,
               slave: int, topic_base: str, label: str):
    errors = 0

    block1 = read_block(client, BLOCK1_START, BLOCK1_COUNT, slave)
    block2 = read_block(client, BLOCK2_START, BLOCK2_COUNT, slave)
    blocks = {1: block1, 2: block2}

    # Transition-only logging: only log when this meter's online/offline
    # status actually changes, not on every poll — one meter being dark
    # (no shore/grid power, or generator off) is the normal steady state.
    currently_online = any(b is not None for b in blocks.values())
    was_online = METER_ONLINE[slave]

    if currently_online and not was_online:
        log.info("%s: meter back online", label)
    elif not currently_online and was_online:
        log.warning("%s: meter not responding, suppressing further warnings until it returns", label)

    METER_ONLINE[slave] = currently_online

    for block_num, offset, scale, field, unit in KWS_REGISTERS:
        block = blocks[block_num]
        if block is None:
            errors += 1
            continue
        raw = block[offset]
        # Handle signed 16-bit (e.g. reg 55 shows as negative in mbpoll)
        if raw > 32767:
            raw = raw  # keep unsigned — values are all positive for this meter
        value = round(raw * scale, 3 if scale < 0.01 else 2 if scale < 0.1 else 1)
        publish(mqttc, topic_base, field, value)

    publish(mqttc, topic_base, "poll_errors", errors)

    # Only log a full per-poll line when the meter is expected to be live —
    # avoids an INFO/WARNING every single cycle while a meter is legitimately
    # unpowered (see transition logging above for that case instead).
    if currently_online:
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
    log.info("  Modbus timeout: %ss", MODBUS_TIMEOUT)

    mqttc = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="kws_mqtt_bridge",
        clean_session=True,
    )
    mqttc.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    mqttc.loop_start()

    modbus_client = ModbusTcpClient(
        host=MODBUS_HOST,
        port=MODBUS_PORT,
        timeout=MODBUS_TIMEOUT,
        retries=0,   # our own poll loop already retries every cycle —
                     # pymodbus's internal retries would otherwise stack
                     # multiple MODBUS_TIMEOUT waits on top of that
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

            # Generator meter — slave 2
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
