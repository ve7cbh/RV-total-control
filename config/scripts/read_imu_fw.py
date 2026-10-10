python3 -c "
import socket
def crc16(d):
    crc=0xFFFF
    for b in d:
        crc^=b
        for _ in range(8):
            crc=(crc>>1)^0xA001 if crc&1 else crc>>1
    return crc
req=bytes([0x50,0x03,0x00,0x2E,0x00,0x01]); c=crc16(req); req+=bytes([c&0xFF,(c>>8)&0xFF])
s=socket.create_connection(('192.168.88.8',4001),timeout=2); s.sendall(req)
r=s.recv(256); print('VERSION = 0x%04X (%d)' % ((r[3]<<8)|r[4], (r[3]<<8)|r[4]))
"