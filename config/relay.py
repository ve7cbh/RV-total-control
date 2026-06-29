#!/usr/bin/env python3
import sys
import socket
import struct

def write_coil(host, port, slave, coil, value):
    # Build Modbus TCP frame
    transaction_id = 0x0001
    protocol_id = 0x0000
    unit_id = slave
    function_code = 0x05  # Write Single Coil
    coil_value = 0xFF00 if value else 0x0000
    
    pdu = struct.pack('>BBHH', unit_id, function_code, coil, coil_value)
    mbap = struct.pack('>HHH', transaction_id, protocol_id, len(pdu))
    frame = mbap + pdu
    
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(frame)
        s.recv(256)

if __name__ == '__main__':
    # Usage: relay.py <coil 0-7> <0|1>
    coil = int(sys.argv[1])
    value = int(sys.argv[2])
    write_coil('192.168.88.12', 4001, 1, coil, value)
