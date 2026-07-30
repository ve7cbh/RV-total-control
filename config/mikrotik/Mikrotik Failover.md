# MikroTik Failover Configuration

**Author:** Steve Bradshaw
**Hardware:** MikroTik CRS109-8G-1S-2HnD

---

## Overview

This RouterOS script configures a MikroTik CRS109-8G-1S-2HnD for graceful WAN failover
between two uplinks:

| Port | Source | NAT | Active When |
|------|--------|-----|-------------|
| Port 1 | Rogers / Club LAN WAN | **Disabled** | RV parked at Club or home |
| Port 2 | Starlink WAN | **Enabled** | Traveling off-grid |

NAT is **disabled on Port 1** to prevent double-NAT issues with VoIP phones in the trailer.
NAT is **enabled on Port 2** because Starlink requires it.

---

## Network Architecture

### MikroTik Subnet
- **LAN:** `192.168.88.0/24`
- **Reserved IP for MikroTik on home network:** `192.168.1.73`

### Upstream Router — UniFi Dream Machine Pro (UDM Pro)
- **Management subnet:** `192.168.1.0/24`
- A static route is configured on the UDM Pro pointing the MikroTik subnet
  back through the MikroTik:
  - **Destination:** `192.168.88.0/24`
  - **Next Hop:** `192.168.1.73`

This allows bidirectional traffic between the home LAN and the RV LAN without
requiring NAT on the Rogers uplink.

---

## UDM Pro Persistent Firewall Rules

Two persistent iptables rules are required on the UDM Pro to permit forwarded traffic
in both directions between the home LAN and the RV LAN. These are written to
`/data/on_boot.d/99-rv-lan-rules.sh` so they survive reboots:

```sh
#!/bin/sh
# RV LAN routing rules — persistent iptables entries
# Allows bidirectional traffic between home LAN and RV LAN (192.168.88.0/24)

iptables -I FORWARD 1 -s 192.168.88.0/24 -j ACCEPT
iptables -I FORWARD 2 -d 192.168.88.0/24 -j ACCEPT
```

> ⚠️ **Rule order is critical.**
> These rules use `iptables -I` (insert), which places them at specific positions
> in the FORWARD chain. If the rules are applied out of sequence, forwarding will
> break. The source rule **must** be inserted before the destination rule.
> Ask me how I know.

---

## Failover Behavior

The script implements graceful failover using routing metrics and/or recursive
route checks. Port 1 (Rogers / Club LAN) is the preferred uplink when available.
Port 2 (Starlink) is promoted automatically when Port 1 loses connectivity.

---

## Notes

- The MikroTik operates as a **routed segment** (not a double-NAT bridge) on
  the Rogers uplink, which preserves correct internal IP addressing for VoIP.
- Starlink's NAT requirement is handled entirely on Port 2; the home-side
  routing is unaffected.
- The UDM Pro static route and iptables rules are prerequisites — the MikroTik
  script alone is not sufficient without the upstream configuration in place.
