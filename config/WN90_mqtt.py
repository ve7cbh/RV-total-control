#!/usr/bin/env python3
"""
WN90_mqtt.py — Ecowitt WN90LP (WS90) Modbus RTU-over-TCP -> MQTT bridge

Polls the WN90LP weather sensor through a Waveshare RS-485-to-Ethernet
gateway and publishes readings to Mosquitto, following the same
direct-poll bridge pattern as epever_mqtt.py / samlux_mqtt.py / kws_mqtt.py.

Publishes BOTH:
  - flat per-field topics under rvtc/sensors/weather/{field}   (unified namespace)
  - one combined JSON payload under rvtc/sensors/weather/json  (for WeeWX's
    MQTTSubscribeDriver, which expects one JSON blob per topic)

Reference: WS90ModbusRTU_V1_0_6.pdf, registers 0165H-016DH
Confirmed working 2026-07-16 bench bring-up (see RVTC doc, HW-16 / 2026-07-16 log)

NOTE (temporary, as of 2026-07-16): sensor is bench-wired to 485-6
(192.168.88.10:4001), NOT its nominal 485-7 (192.168.88.11). Update
GATEWAY_IP below once the permanent 485-7 run is in place.
"""

import json
import time
import logging

from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt

# --- Modbus / gateway config ---
GATEWAY_IP = '192.168.88.10'   # TEMPORARY - bench connection on 485-6, see note above
GATEWAY_PORT = 4001
SLAVE_ADDRESS = 144            # 0x90 - Ecowitt WN90LP/WS90 default
START_REGISTER = 0x0165
REGISTER_COUNT = 9
POLL_INTERVAL_SEC = 3          # matches sensor's own ~2s internal refresh cadence for wind 
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 0.5

# --- MQTT config ---
MQTT_HOST = 'localhost'        # container/service name on rvtc_net
MQTT_PORT = 1883
MQTT_BASE_TOPIC = 'rvtc/sensors/weather'
MQTT_JSON_TOPIC = f'{MQTT_BASE_TOPIC}/json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('WN90_mqtt')

INVALID = 0xFFFF


def val_or_none(raw, transform):
    return None if raw == INVALID else transform(raw)


def decode(registers):
    light, uvi, temp_raw, humi, wind, gust, wdir, rain, pressure = registers
    light_lux = val_or_none(light, lambda v: round(v * 10, 1))
    return {
        'light_lux':        light_lux,
        'solarRadiation':   None if light_lux is None else round(light_lux / 126, 1),  # indicator only, not calibrated
        'uvi':              val_or_none(uvi, lambda v: round(v / 10, 1)),
        'outTemp':          val_or_none(temp_raw, lambda v: round((v - 400) / 10, 1)),
        'outHumidity':      val_or_none(humi, lambda v: v),
        'windSpeed':        val_or_none(wind, lambda v: round(v * 0.1, 1)),
        'windGust':         val_or_none(gust, lambda v: round(v * 0.1, 1)),
        'windDir':          val_or_none(wdir, lambda v: v),
        'rain_total_mm':    val_or_none(rain, lambda v: round(v * 0.1, 1)),
        'barometer':        val_or_none(pressure, lambda v: round(v * 0.1, 1)),
        'time': int(time.time()),
    }

def read_weather(client):
    for attempt in range(1, MAX_RETRIES + 1):
        result = client.read_holding_registers(
            address=START_REGISTER,
            count=REGISTER_COUNT,
            device_id=SLAVE_ADDRESS,
        )
        if not result.isError():
            return result.registers
        log.warning("Read attempt %d failed: %s", attempt, result)
        time.sleep(RETRY_BACKOFF_SEC)
    return None


def publish(mqttc, data):
    # Combined JSON blob - primary consumer is WeeWX's MQTTSubscribeDriver
    mqttc.publish(MQTT_JSON_TOPIC, json.dumps(data), qos=0, retain=False)

    # Flat per-field topics - unified namespace, for Telegraf/HA/anything else
    for field, value in data.items():
        if field == 'time' or value is None:
            continue
        mqttc.publish(f'{MQTT_BASE_TOPIC}/{field}', value, qos=0, retain=False)


def main():
    modbus_client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=1)
    if not modbus_client.connect():
        log.error("Could not connect to gateway at %s:%s", GATEWAY_IP, GATEWAY_PORT)
        return

    mqttc = mqtt.Client(client_id='wn90_mqtt', protocol=mqtt.MQTTv311)
    mqttc.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    mqttc.loop_start()

    log.info("WN90_mqtt bridge started - polling every %ss", POLL_INTERVAL_SEC)

    try:
        while True:
            registers = read_weather(modbus_client)
            if registers:
                data = decode(registers)
                publish(mqttc, data)
                log.info("Published: %s", data)
            else:
                log.error("Read failed after %d retries - skipping this cycle", MAX_RETRIES)
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        mqttc.loop_stop()
        mqttc.disconnect()
        modbus_client.close()


if __name__ == '__main__':
    main()
