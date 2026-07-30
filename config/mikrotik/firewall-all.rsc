# 2026-07-07 13:22:36 by RouterOS 7.23.2
# software id = YYCP-3JA6
#
# model = CRS109-8G-1S-2HnD
# serial number = HD90855YGV8
/ip firewall connection tracking
set udp-timeout=10s
/ip firewall filter
add action=accept chain=input comment=\
    "defconf: accept established,related,untracked" connection-state=\
    established,related,untracked
add action=drop chain=input comment="defconf: drop invalid" connection-state=\
    invalid
add action=accept chain=input comment="defconf: accept ICMP" protocol=icmp
add action=accept chain=input comment=\
    "defconf: accept to local loopback (for CAPsMAN)" dst-address=127.0.0.1
add action=drop chain=input comment="defconf: drop all not coming from LAN" \
    in-interface-list=!LAN
add action=accept chain=forward comment="defconf: accept in ipsec policy" \
    ipsec-policy=in,ipsec
add action=accept chain=forward comment="defconf: accept out ipsec policy" \
    ipsec-policy=out,ipsec
add action=fasttrack-connection chain=forward comment="defconf: fasttrack" \
    connection-state=established,related
add action=accept chain=forward comment=\
    "defconf: accept established,related, untracked" connection-state=\
    established,related,untracked
add action=drop chain=forward comment="defconf: drop invalid" \
    connection-state=invalid
add action=drop chain=forward comment=\
    "defconf: drop all from WAN not DSTNATed" connection-nat-state=!dstnat \
    connection-state=new in-interface-list=WAN
add action=accept chain=input comment=\
    "defconf: accept established,related,untracked" connection-state=\
    established,related,untracked
add action=drop chain=input comment="defconf: drop invalid" connection-state=\
    invalid
add action=accept chain=input comment="defconf: accept ICMP" protocol=icmp
add action=accept chain=input comment=\
    "defconf: accept to local loopback (for CAPsMAN)" dst-address=127.0.0.1
add action=accept chain=input comment=\
    "HOME MODE: accept input from home LAN 192.168.0.0/21" in-interface=\
    rogers-wan src-address=192.168.0.0/21
add action=drop chain=input comment="defconf: drop all not coming from LAN" \
    in-interface-list=!LAN
add action=accept chain=forward comment="defconf: accept in ipsec policy" \
    ipsec-policy=in,ipsec
add action=accept chain=forward comment="defconf: accept out ipsec policy" \
    ipsec-policy=out,ipsec
add action=accept chain=forward comment=\
    "HOME MODE: forward home LAN 192.168.0.0/21 to RV LAN" in-interface=\
    rogers-wan src-address=192.168.0.0/21
add action=accept chain=forward comment=\
    "HOME MODE: forward RV LAN return traffic to home LAN" dst-address=\
    192.168.0.0/21 out-interface=rogers-wan
add action=fasttrack-connection chain=forward comment="defconf: fasttrack" \
    connection-state=established,related
add action=accept chain=forward comment=\
    "defconf: accept established,related,untracked" connection-state=\
    established,related,untracked
add action=drop chain=forward comment="defconf: drop invalid" \
    connection-state=invalid
add action=drop chain=forward comment=\
    "defconf: drop all from WAN not DSTNATed" connection-nat-state=!dstnat \
    connection-state=new in-interface-list=WAN
/ip firewall nat
add action=masquerade chain=srcnat comment=Rogers disabled=yes ipsec-policy=\
    out,none out-interface=rogers-wan out-interface-list=WAN
add action=masquerade chain=srcnat comment=starlink out-interface=\
    starlink-wan out-interface-list=WAN
add action=masquerade chain=srcnat comment="NAT for Rogers" disabled=yes \
    out-interface=rogers-wan
add action=masquerade chain=srcnat comment="NAT for Starlink" disabled=yes \
    out-interface=starlink-wan
add action=masquerade chain=srcnat comment=\
    "Rogers  disabled in HOME mode, enable for OFF-GRID" disabled=yes \
    ipsec-policy=out,none out-interface=rogers-wan out-interface-list=WAN
add action=masquerade chain=srcnat comment="Starlink  always enabled" \
    out-interface=starlink-wan out-interface-list=WAN
add action=masquerade chain=srcnat comment="Internet NAT  home mode" \
    dst-address=!192.168.0.0/21 out-interface=rogers-wan src-address=\
    192.168.88.0/24
add action=dst-nat chain=dstnat comment="Pinhole for Weewx port 80" dst-port=\
    80 in-interface=rogers-wan protocol=tcp to-addresses=192.168.88.3
