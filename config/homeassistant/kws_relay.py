#!/usr/bin/env python3
"""
kws_relay.py — write KWS-303L register 63 (internal disconnect relay)

Same pattern as relay.py: fresh TCP socket per call, no persistent
connection. This deliberately does NOT share a connection with
kws_mqtt.py, which holds its own persistent connection for polling —
keeping these separate avoids the two scripts fighting over one socket.

Usage: kws_relay.py <slave> <0|1>
  slave: 1 = grid meter, 2 = generator meter
  value: 1 = connect (closes the meter's internal relay), 0 = disconnect

Confirmed via mbpoll 2026-06-30: register 63 read back as 1 while grid
was actively under load — so 1 = connected, 0 = disconnected, no
inverted logic here (unlike the Waveshare NC relay coils).

NOTE — per the KWS-303L register map doc: writing 1 to this register
does NOT clear an active alarm condition the way the meter's physical
front-panel switch does. If alarm_code (register 62) is nonzero, the
meter may refuse reconnection or immediately re-trip. Clear the alarm
on the meter itself first if this is the case.
"""

import sys
import socket
import struct

GATEWAY_HOST = "192.168.88.7"
GATEWAY_PORT = 4001
RELAY_REGISTER = 63  # 0-based literal addressing, confirmed via mbpoll -0


def write_register(host, port, slave, register, value):
    transaction_id = 0x0001
    protocol_id = 0x0000
    unit_id = slave
    function_code = 0x06  # Write Single Holding Register

    pdu = struct.pack('>BBHH', unit_id, function_code, register, value)
    mbap = struct.pack('>HHH', transaction_id, protocol_id, len(pdu))
    frame = mbap + pdu

    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(frame)
        s.recv(256)


if __name__ == '__main__':
    # Usage: kws_relay.py <slave 1|2> <0|1>
    slave = int(sys.argv[1])
    value = int(sys.argv[2])
    write_register(GATEWAY_HOST, GATEWAY_PORT, slave, RELAY_REGISTER, value)
