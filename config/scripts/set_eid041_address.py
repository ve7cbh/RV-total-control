#!/usr/bin/env python3
"""
set_eid041_address.py — bench tool: reprograms an Ebyte EID041-G01S's
Modbus address via its Hold Register 0x000A, before wiring it onto a
shared RS-485 line with other EID041 units (or anything else).

Same pattern as the KWS-303L meters ("set slave 2 on bench, wire onto
RS-485/3" -- System Reference HW-09): do the address change on the bench,
on its own line at the factory-default address (1), BEFORE combining
multiple units onto one shared bus. Two devices both answering to
address 1 on the same line can't be told apart to fix afterward.

Write framing (function 0x06, write single register) verified against a
real confirmed example from a DIFFERENT device's manual before this
script was written -- the EID041 manual documents which register to write
but, unlike its read examples, doesn't give a worked write example of its
own. Standard Modbus write-single-register framing is device-agnostic, so
validating the framing logic itself against any correct real example is
sufficient; this doesn't mean the specific EID041 write has been tested
against real hardware yet -- that's what running this script on the bench
IS the test for.

Per the manual: "The change will take effect after restarting." This
script's write is only confirmed successful by the function-0x06 echo
response (the device accepted and wrote the register) -- but the device
keeps answering at its OLD address until power-cycled. This script does
NOT power-cycle anything for you; do that manually, then verify.

Usage:
    python3 set_eid041_address.py <gateway_host> <current_address> <new_address> [gateway_port]

Example -- reprogram a factory-default unit (address 1) to address 3,
on the gateway it's currently connected to for this bench test:
    python3 set_eid041_address.py 192.168.88.16 1 3
"""

import socket
import sys

ADDRESS_REG = 0x000A   # RS485 Bus Modbus Address/Station Number
SOCKET_TIMEOUT = 2.0
DEFAULT_PORT = 4001


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


def build_write_single_register(slave: int, reg_addr: int, value: int) -> bytes:
    body = bytes([
        slave, 0x06,
        (reg_addr >> 8) & 0xFF, reg_addr & 0xFF,
        (value >> 8) & 0xFF, value & 0xFF,
    ])
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def write_single_register(host: str, port: int, slave: int, reg_addr: int, value: int) -> bytes:
    """Returns the raw response bytes. Caller checks it echoes the request."""
    request = build_write_single_register(slave, reg_addr, value)
    with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as sock:
        sock.sendall(request)
        response = b""
        while len(response) < len(request):
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk
    return response


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        return 1

    host = sys.argv[1]
    try:
        current_addr = int(sys.argv[2])
        new_addr = int(sys.argv[3])
    except ValueError:
        print("current_address and new_address must be integers (1-255)")
        return 1
    port = int(sys.argv[4]) if len(sys.argv) == 5 else DEFAULT_PORT

    if not (1 <= current_addr <= 255) or not (1 <= new_addr <= 255):
        print("Addresses must be in range 1-255 per the EID041 manual")
        return 1

    request = build_write_single_register(current_addr, ADDRESS_REG, new_addr)
    print(f"Sending: {request.hex(' ').upper()}")

    try:
        response = write_single_register(host, port, current_addr, ADDRESS_REG, new_addr)
    except OSError as e:
        print(f"Couldn't reach the gateway: {e}")
        return 1

    print(f"Received: {response.hex(' ').upper()}")

    if response == request:
        print(f"\nWrite confirmed (response echoed the request exactly).")
        print(f"Device at address {current_addr} has been told to become address {new_addr}.")
        print(f"POWER-CYCLE THE DEVICE NOW -- the change doesn't take effect until it restarts.")
        print(f"After power-cycling, verify by reading Hold Register 0x000A at the NEW address")
        print(f"({new_addr}) -- if this device is now the only one you can reach at the old")
        print(f"address, and a working one answers at the new address, the change worked.")
    else:
        print(f"\nResponse didn't echo the request -- write NOT confirmed successful.")
        print(f"Check current_address is actually correct for this device (factory default")
        print(f"is 1), and that nothing else is on this line answering at that address too.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
