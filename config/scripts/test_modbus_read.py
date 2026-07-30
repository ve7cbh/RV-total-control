#!/usr/bin/env python3
"""
Test read of the IMU node's Modbus holding registers, through the
Waveshare gateway (192.168.88.8:4001, Modbus TCP-to-RTU, confirmed in the
gateway's own config page: 9600 8N1, TCP Server mode).

Registers (per main.cpp): 0=heading, 1=pitch, 2=roll — all int16, x10 scaled.
Slave/device ID: 10 (MODBUS_SLAVE_ID in main.cpp).
"""

from pymodbus.client import ModbusTcpClient

GATEWAY_IP = "192.168.88.8"
GATEWAY_PORT = 4001
SLAVE_ID = 10

client = ModbusTcpClient(GATEWAY_IP, port=GATEWAY_PORT, timeout=5)

if not client.connect():
    print(f"FAILED to open TCP connection to {GATEWAY_IP}:{GATEWAY_PORT}")
    exit(1)

print(f"Connected to gateway at {GATEWAY_IP}:{GATEWAY_PORT}, querying slave ID {SLAVE_ID}...")

result = client.read_holding_registers(address=0, count=3, device_id=SLAVE_ID)

if result.isError():
    print(f"Modbus error response: {result}")
    print("This means the TCP connection worked, but the request itself failed —")
    print("check the slave ID matches (10), and that the gateway's serial settings")
    print("(9600 8N1) actually match what the ESP32 is transmitting at.")
else:
    heading_raw, pitch_raw, roll_raw = result.registers
    # Registers are signed int16, but pymodbus returns them as unsigned by
    # default — convert negative values back correctly (>32767 means negative).
    def to_signed(v):
        return v - 65536 if v > 32767 else v

    heading = to_signed(heading_raw) / 10.0
    pitch = to_signed(pitch_raw) / 10.0
    roll = to_signed(roll_raw) / 10.0

    print(f"SUCCESS — real Modbus data received:")
    print(f"  Heading: {heading:.1f} deg")
    print(f"  Pitch:   {pitch:+.1f} deg")
    print(f"  Roll:    {roll:+.1f} deg")

client.close()
