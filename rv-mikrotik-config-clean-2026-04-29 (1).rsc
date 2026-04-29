# ============================================================
# MikroTik CRS109-8G-1S-2HnD  —  RV Router Config
# Model  : CRS109-8G-1S-2HnD
# Serial : HD90855YGV8
# Date   : 2026-04-29
# Author : VE7CBH
#
# CHANGES FROM PREVIOUS VERSION (2026-04-28)
#   - REMOVED bad static route "gateway=rogers-wan" (no next-hop IP)
#     was overriding DHCP-learned route and blocking internet
#   - DHCP client add-default-route=yes now manages default route
#     automatically — no static default route needed
#   - REMOVED duplicate/redundant NAT rules (old rules 0,2,3,4)
#   - RETAINED Internet NAT home mode rule (src-address scoped)
#   - RETAINED Starlink masquerade (always enabled)
#   - Rogers masquerade remains DISABLED for home mode
#
# OPERATING MODES
#   HOME     : Rogers NAT disabled — RV subnet (192.168.88.0/24)
#              visible as real subnet on home LAN (192.168.0.0/21)
#              Home router needs static route:
#                Destination : 192.168.88.0/24
#                Gateway     : <rogers-wan DHCP IP>
#                              (check: /ip dhcp-client print)
#              Internet traffic from RV subnet masqueraded via
#              "Internet NAT home mode" rule — home LAN excluded
#
#   OFF-GRID : Enable Rogers masquerade — both WANs masquerade
#              Starlink auto-fails over at distance=2
#
# MODE TOGGLE (run from terminal):
#   Off-grid : /ip firewall nat set [find comment=Rogers] disabled=no
#   Home     : /ip firewall nat set [find comment=Rogers] disabled=yes
#
# FAILOVER
#   Rogers   : primary  (distance=1, add-default-route=yes)
#   Starlink : failover (distance=2, add-default-route=yes)
#   Both use check-gateway via DHCP lease management
# ============================================================

# ------------------------------------------------------------
# BRIDGE INTERFACES
# ------------------------------------------------------------
/interface bridge
add admin-mac=18:FD:74:C7:2C:39 auto-mac=no comment=defconf name=bridge
add admin-mac=18:FD:74:C7:2C:40 auto-mac=no name=passthrough

# ------------------------------------------------------------
# WIRELESS
# ------------------------------------------------------------
/interface wireless
set [ find default-name=wlan1 ] band=2ghz-b/g/n channel-width=20/40mhz-XX \
    disabled=no distance=indoors frequency=auto installation=indoor \
    mode=ap-bridge ssid=VE7CBH_Mikrotik wireless-protocol=802.11

# ------------------------------------------------------------
# ETHERNET — rename WAN ports
# ------------------------------------------------------------
/interface ethernet
set [ find default-name=ether1 ] name=rogers-wan
set [ find default-name=ether2 ] name=starlink-wan

# ------------------------------------------------------------
# INTERFACE LISTS
# ------------------------------------------------------------
/interface list
add comment=defconf name=WAN
add comment=defconf name=LAN

# ------------------------------------------------------------
# WIRELESS SECURITY
# ------------------------------------------------------------
/interface wireless security-profiles
set [ find default=yes ] authentication-types=wpa-psk,wpa2-psk \
    mode=dynamic-keys supplicant-identity=MikroTik \
    wpa-pre-shared-key=2511670E4400 wpa2-pre-shared-key=2511670E4400

# ------------------------------------------------------------
# DHCP POOL
# ------------------------------------------------------------
/ip pool
add name=dhcp ranges=192.168.88.10-192.168.88.254

# ------------------------------------------------------------
# DHCP SERVER
# ------------------------------------------------------------
/ip dhcp-server
add address-pool=dhcp disabled=no interface=bridge name=defconf

# ------------------------------------------------------------
# BRIDGE PORTS
# ------------------------------------------------------------
/interface bridge port
add bridge=bridge comment=defconf interface=ether3
add bridge=bridge comment=defconf interface=ether4
add bridge=bridge comment=defconf interface=ether5
add bridge=bridge comment=defconf interface=ether6
add bridge=bridge comment=defconf interface=ether7
add bridge=passthrough comment=defconf interface=ether8
add bridge=bridge comment=defconf interface=sfp1
add bridge=bridge comment=defconf interface=wlan1
add bridge=passthrough interface=WAN

# ------------------------------------------------------------
# NEIGHBOR DISCOVERY
# ------------------------------------------------------------
/ip neighbor discovery-settings
set discover-interface-list=LAN

# ------------------------------------------------------------
# INTERFACE LIST MEMBERS
# ------------------------------------------------------------
/interface list member
add interface=ether3 list=LAN
add interface=ether4 list=LAN
add interface=ether5 list=LAN
add interface=ether6 list=LAN
add interface=ether7 list=LAN
add interface=ether8 list=LAN
add interface=sfp1 list=LAN
add comment=rogers-wan interface=rogers-wan list=WAN
add interface=bridge list=LAN
add comment=Starlink-Failover interface=starlink-wan list=WAN

# ------------------------------------------------------------
# IP ADDRESSING
# ------------------------------------------------------------
/ip address
add address=192.168.88.1/24 comment=defconf interface=bridge \
    network=192.168.88.0

# ------------------------------------------------------------
# DHCP CLIENTS
# NOTE: add-default-route=yes — DHCP manages the default route
#       automatically. No static default route required.
#       Rogers = distance 1 (primary)
#       Starlink = distance 2 (failover)
# ------------------------------------------------------------
/ip dhcp-client
add disabled=no interface=rogers-wan \
    comment="Rogers Primary WAN DHCP" \
    add-default-route=yes \
    default-route-distance=1 \
    use-peer-dns=yes \
    use-peer-ntp=yes
add disabled=no interface=starlink-wan \
    comment="Starlink Failover WAN DHCP" \
    add-default-route=yes \
    default-route-distance=2 \
    use-peer-dns=no \
    use-peer-ntp=no

# ------------------------------------------------------------
# DHCP SERVER NETWORKS
# ------------------------------------------------------------
/ip dhcp-server network
add address=192.168.88.0/24 comment=defconf \
    dns-server=192.168.88.1 \
    gateway=192.168.88.1

# ------------------------------------------------------------
# DNS
# ------------------------------------------------------------
/ip dns
set allow-remote-requests=yes servers=1.1.1.1,8.8.8.8

/ip dns static
add address=192.168.88.1 comment=defconf name=router.lan

# ------------------------------------------------------------
# FIREWALL FILTER
# ------------------------------------------------------------
/ip firewall filter

# --- Accept established/related/untracked ---
add action=accept chain=input \
    comment="defconf: accept established,related,untracked" \
    connection-state=established,related,untracked

# --- Drop invalid ---
add action=drop chain=input \
    comment="defconf: drop invalid" \
    connection-state=invalid

# --- Accept ICMP ---
add action=accept chain=input \
    comment="defconf: accept ICMP" \
    protocol=icmp

# --- Accept loopback ---
add action=accept chain=input \
    comment="defconf: accept to local loopback (for CAPsMAN)" \
    dst-address=127.0.0.1

# --- HOME MODE: accept management from home LAN ---
add action=accept chain=input \
    comment="HOME MODE: accept input from home LAN 192.168.0.0/21" \
    src-address=192.168.0.0/21 \
    in-interface=rogers-wan

# --- Drop all other input not from LAN ---
add action=drop chain=input \
    comment="defconf: drop all not coming from LAN" \
    in-interface-list=!LAN

# --- Forward: accept IPsec ---
add action=accept chain=forward \
    comment="defconf: accept in ipsec policy" \
    ipsec-policy=in,ipsec

add action=accept chain=forward \
    comment="defconf: accept out ipsec policy" \
    ipsec-policy=out,ipsec

# --- HOME MODE: home LAN <-> RV LAN forwarding ---
add action=accept chain=forward \
    comment="HOME MODE: forward home LAN to RV LAN" \
    src-address=192.168.0.0/21 \
    in-interface=rogers-wan

add action=accept chain=forward \
    comment="HOME MODE: forward RV LAN return to home LAN" \
    dst-address=192.168.0.0/21 \
    out-interface=rogers-wan

# --- Fasttrack established/related ---
add action=fasttrack-connection chain=forward \
    comment="defconf: fasttrack" \
    connection-state=established,related

# --- Accept established/related/untracked forward ---
add action=accept chain=forward \
    comment="defconf: accept established,related,untracked" \
    connection-state=established,related,untracked

# --- Drop invalid forward ---
add action=drop chain=forward \
    comment="defconf: drop invalid" \
    connection-state=invalid

# --- Drop unsolicited WAN inbound ---
add action=drop chain=forward \
    comment="defconf: drop all from WAN not DSTNATed" \
    connection-nat-state=!dstnat \
    connection-state=new \
    in-interface-list=WAN

# ------------------------------------------------------------
# FIREWALL NAT
#
# Rule 0: Rogers masquerade — DISABLED in home mode
#         Enable for off-grid: /ip firewall nat set [find comment=Rogers] disabled=no
# Rule 1: Starlink masquerade — always enabled
# Rule 2: Internet NAT home mode — masquerades RV subnet internet
#         traffic only; excludes home LAN (192.168.0.0/21)
# ------------------------------------------------------------
/ip firewall nat

add action=masquerade chain=srcnat \
    comment="Rogers" \
    disabled=yes \
    ipsec-policy=out,none \
    out-interface=rogers-wan

add action=masquerade chain=srcnat \
    comment="Starlink" \
    out-interface=starlink-wan

add action=masquerade chain=srcnat \
    comment="Internet NAT home mode" \
    src-address=192.168.88.0/24 \
    dst-address=!192.168.0.0/21 \
    out-interface=rogers-wan

# ------------------------------------------------------------
# ROUTING
# NOTE: No static default routes. DHCP clients manage default
#       routes automatically via add-default-route=yes.
#       Rogers distance=1 (primary), Starlink distance=2 (failover)
# ------------------------------------------------------------

# ------------------------------------------------------------
# LCD
# ------------------------------------------------------------
/lcd
set time-interval=hour

/lcd interface pages
set 0 interfaces=\
    rogers-wan,starlink-wan,ether3,ether4,ether5,ether6,ether7,ether8,sfp1

# ------------------------------------------------------------
# SYSTEM
# ------------------------------------------------------------
/system clock
set time-zone-name=America/Vancouver

# ------------------------------------------------------------
# MAC SERVER
# ------------------------------------------------------------
/tool mac-server
set allowed-interface-list=LAN

/tool mac-server mac-winbox
set allowed-interface-list=LAN

# ============================================================
# END OF CONFIG
# ============================================================
