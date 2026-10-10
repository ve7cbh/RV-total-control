#!/usr/bin/env python3
"""
eid041_raw_probe.py — one-off diagnostic: connects to the EID041's gateway
port, sends the exact read request from the manual's own worked example,
and prints EVERYTHING that comes back (not just the first few bytes) --
to check whether 0xFF 0xFB 0x01 (Telnet IAC WILL ECHO) is really being
sent before the actual Modbus response.

Usage:
    python3 eid041_raw_probe.py
"""

import socket
import time

GATEWAY_HOST = "192.168.88.16"   # serial-4
GATEWAY_PORT = 4001
SOCKET_TIMEOUT = 3.0

# The manual's own worked example request -- read temp+humidity, addr 1
REQUEST = bytes.fromhex("01040000000271CB")


def main():
    with socket.create_connection((GATEWAY_HOST, GATEWAY_PORT), timeout=SOCKET_TIMEOUT) as sock:
        sock.settimeout(SOCKET_TIMEOUT)

        # Read anything the gateway sends immediately on connect, BEFORE
        # we send our request -- if it's Telnet, negotiation often arrives
        # unprompted right after the TCP handshake.
        preamble = b""
        try:
            while True:
                chunk = sock.recv(256)
                if not chunk:
                    break
                preamble += chunk
        except socket.timeout:
            pass
        print(f"Bytes received BEFORE sending anything ({len(preamble)}): {preamble.hex(' ').upper()}")

        print(f"\nSending request: {REQUEST.hex(' ').upper()}")
        sock.sendall(REQUEST)

        time.sleep(0.5)  # give the device time to respond
        response = b""
        try:
            while True:
                chunk = sock.recv(256)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass
        print(f"\nBytes received AFTER sending request ({len(response)}): {response.hex(' ').upper()}")


if __name__ == "__main__":
    main()
