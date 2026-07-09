# RVTC — Consolidated Reference Document

**Version 1.1** — supersedes Version 1.0. Changes in this revision: SOC/power
web-panel smoothing, GPS bridge deployment, RouterOS v7 upgrade, Telegraf/SNMP
monitoring framework, IMU node build (HW-25, corrected to RS-485-primary
architecture), and a full reconciliation of the RS-485 gateway addressing
table (Section 5.5) against live hardware — see [Part 4](#part-4--chronological-session-log)
for session-by-session detail.

*Rationalized from session notes dated 2026-06-26 through 2026-07-06. This document
merges: `RVTC_Session_Summary_20260626.md`, `Section9_Phase7_addition_20260630.md`,
`RVTC_SessionLog_Addendum_20260702_UnifiedNamespace.md`,
`RVTC_SessionLog_20260706_MicrowaveRelay.md`, `RVTC_SessionLog_20260706_LoadShedRace.md`,
and the 2026-07-06 chat session covering the EPEVER SOC investigation.
Updated 2026-07-07 with the SOC/power web-panel smoothing, GPS bridge, RouterOS
v7 upgrade, and Telegraf/SNMP deployment sessions, and 2026-07-09 with the IMU
node build — see [Part 4](#part-4--chronological-session-log)
for full detail.*

*Purpose: one searchable document instead of five+ separate files. Organized by
**topic** (Parts 1–3) for "what's the current state / how do I fix this" lookups,
with the full **chronological log** preserved (Part 4) for "what actually happened
and in what order" lookups. Use the Index at the end to jump straight to a keyword.*

---

## How to Use This Document

- **Need to know how something currently works, or the status of an open question?**
  → Part 1 (Architecture) or Part 3 (Backlog)
- **Debugging something that's misbehaved before?** → Part 2 (Known Issues)
- **Need the full story / exact commands / exact evidence from a specific session?**
  → Part 4 (Chronological Log)
- **Need a register address, IP, or coil number?** → Part 5 (Reference Tables)
- **Just have a keyword?** → Index at the bottom

This doc is written to merge into the existing `RVTC_Project_Reference` at its
established section numbers where noted (Section 8 = session log, Section 9.x =
architecture). Where this doc says "Section 9.1," "Section 8," etc., that refers to
the master reference doc's numbering, not this document's own headers.

---

## Table of Contents

- [Part 1 — Current Architecture](#part-1--current-architecture)
  - [1.1 Data Flow Overview](#11-data-flow-overview)
  - [1.2 Unified Namespace (MQTT)](#12-unified-namespace-mqtt)
  - [1.3 InfluxDB / Telegraf Persistence Layer](#13-influxdb--telegraf-persistence-layer)
  - [1.4 Home Assistant's Role — Data Consumer Only](#14-home-assistants-role--data-consumer-only)
  - [1.5 RS-485 / Modbus Gateway Topology](#15-rs-485--modbus-gateway-topology)
  - [1.6 Open Question — HA's Role in Actuation (Phase 7)](#16-open-question--has-role-in-actuation-phase-7)
  - [1.7 Network / Router Topology (MikroTik)](#17-network--router-topology-mikrotik)
- [Part 2 — Known Issues & Root Causes](#part-2--known-issues--root-causes)
  - [2.1 EPEVER Battery SOC Swings — RESOLVED](#21-epever-battery-soc-swings--resolved)
  - [2.2 Manual Load Shed Intermittent Failures — SUSPECTED CAUSE, UNCONFIRMED](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed)
  - [2.3 Microwave Relay Missing from Dev Tools — LEADING THEORY, UNCONFIRMED](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed)
  - [2.4 Unidentified rtl_433 Devices — UNRESOLVED, NOT YET INVESTIGATED](#24-unidentified-rtl_433-devices--unresolved-not-yet-investigated)
  - [2.5 MikroTik Improper Reboot (Jun 27, 2026) — UNCONFIRMED CAUSE, NOT YET INVESTIGATED](#25-mikrotik-improper-reboot-jun27-2026--unconfirmed-cause-not-yet-investigated)
  - [2.6 Duplicate Firewall/NAT Rule Sets — PARTIALLY RESOLVED 2026-07-06](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06)
- [Part 3 — Backlog](#part-3--backlog)
  - [3.1 Hardware](#31-hardware)
  - [3.2 Software](#32-software)
- [Part 4 — Chronological Session Log](#part-4--chronological-session-log)
  - [2026-06-09 — MikroTik Router Configuration (ether8 fix, NOT YET DEPLOYED)](#2026-06-09--mikrotik-router-configuration-ether8-fix-prepared--not-yet-deployed)
  - [2026-06-26 — HA Onboarding, SAMLUX Bridge, Telegraf](#2026-06-26--ha-onboarding-samlux-bridge-telegraf)
  - [2026-06-30 — Phase 7 Question Raised](#2026-06-30--phase-7-question-raised)
  - [2026-07-02 — Unified Namespace Architecture Decision](#2026-07-02--unified-namespace-architecture-decision)
  - [2026-07-05/06 — Microwave Relay Incident](#2026-0705-06--microwave-relay-incident)
  - [2026-07-06 (early AM) — Load Shed Race Investigation](#2026-07-06-early-am--load-shed-race-investigation)
  - [2026-07-06 — EPEVER SOC / MT50 / RS485-1M2S Investigation](#2026-07-06--epever-soc--mt50--rs485-1m2s-investigation)
- [Part 5 — Reference Tables](#part-5--reference-tables)
  - [5.1 Device / Gateway Inventory](#51-device--gateway-inventory)
  - [5.2 SAMLUX EVO-2212 Key Registers](#52-samlux-evo-2212-key-registers)
  - [5.3 EPEVER Key Registers](#53-epever-key-registers)
  - [5.4 Relay / Coil Mapping](#54-relay--coil-mapping)
  - [5.5 RS-485 Bus / Gateway IP Addressing](#55-rs-485-bus--gateway-ip-addressing)
- [Index](#index)

---

## Part 1 — Current Architecture

### 1.1 Data Flow Overview

```
Device → RS-485 → Waveshare gateway → Modbus TCP → Python bridge → MQTT → HA
                                                                  → Telegraf → InfluxDB → Grafana
```

Core principle (reaffirmed 2026-06-26, formalized 2026-07-02): **HA is a data
consumer, never a poller.** All device polling happens in standalone Python bridge
scripts (`samlux_mqtt.py`, `epever_mqtt.py`, `kws_mqtt.py`, etc.), each running as
its own systemd service, publishing to `rvtc/sensors/{source}/{field}` on Mosquitto.
HA, Telegraf, and any future consumer subscribe to MQTT — none of them poll Modbus
directly except the bridge scripts.

### 1.2 Unified Namespace (MQTT)

Decided 2026-07-02. One Mosquitto broker is the live data bus for everything.
Topic schema: `rvtc/sensors/{source}/{field}`, flat scalar payload per topic
(e.g. `rvtc/sensors/solar/pv_voltage 69.22`) — already in the right shape for
generic ingestion, confirmed via payload audit.

Weather (`rtl_433 → WeeWX → InfluxDB`) and power (`Modbus bridges → MQTT → HA`)
were, until 2026-07-02, two disconnected lanes sharing one broker rather than one
real pipeline — power data dead-ended at HA with nothing writing it to InfluxDB.
Grafana had no visibility into grid current, battery SOC, inverter mode, or Tier
3/4 state, and Section 2.8's intent ("every A/C shed logged to InfluxDB as a
discrete event") was never actually wired. The unified-namespace work closes this.

**Do not point Telegraf at raw `rtl_433/#`.** WeeWX already does unit conversion,
`contains_total` rain handling, and ID filtering that a naive raw ingest would not
reproduce. Correct approach (Phase 3, not yet scheduled): use the `weewx-mqtt`
extension so WeeWX publishes its already-corrected readings to
`rvtc/sensors/weather/{field}`, and Telegraf only ever touches normalized topics.

**Documented exception — IMU node publishes real-time-only, not persisted
(2026-07-09).** Every other device on the bus gets picked up by Telegraf and
written to InfluxDB. The IMU (`rvtc/sensors/imu/#` — heading/pitch/roll/bounce)
is a deliberate exception: nobody needs a queryable history of "what was our
pitch three weeks ago," so it's intentionally *not* wired into any
`telegraf_*.conf`. If this ever shows up as "missing" data during a future
Telegraf review, that's expected — don't add it back without a real reason to.

**Correction (2026-07-09):** an earlier draft of this note incorrectly framed
the IMU as a WiFi-only exception to the RS-485 convention. That was wrong —
RS-485 Modbus RTU is the IMU's primary, authoritative path (dedicated gateway
port RS-485/4, `192.168.88.8:4001`), same as every other bus device. WiFi/MQTT
and the local web page are secondary/convenience paths only, matching the
project's general RS-485-for-everything-critical design. See [5.1](#51-device--gateway-inventory)
for the node itself.

### 1.3 InfluxDB / Telegraf Persistence Layer

Implementation plan (see [Part 4 — 2026-07-02](#2026-07-02--unified-namespace-architecture-decision)
for full commands/config):

- **Phase 1** — add `mqtt.publish` calls alongside relay writes in Tier 3 shed/restore
  scripts (`scripts.yaml`) → `rvtc/events/tier3/...`. Not yet drafted; do after Phase 2 confirms.
- **Phase 2** — new Telegraf container + new InfluxDB bucket `rvtc_unified`
  (isolated from the working WeeWX `rvtc` bucket), generic `mqtt_consumer` input
  subscribing to `rvtc/sensors/#`, `processors.pivot` to reshape into wide rows.
  Known caveat: pivot merges on identical tags **and** identical timestamp — a
  15-field burst from one source may land as several narrow rows rather than one
  wide row per poll. Queryable either way; check actual shape before assuming a
  redesign is needed.
- **Phase 3** — weather via `weewx-mqtt` (see 1.2 above).
- **Phase 4** — burn in Telegraf alongside the existing `influxdb2.py` script for a
  few days, compare, then retire `influxdb2.py` and point Grafana at `rvtc_unified`.
  WeeWX's own SQLite archive is untouched throughout.
- **Phase 5** — write up Section 9.5 (Data Flow Architecture) once Phase 2 is
  actually running and confirmed.

**Status as of 2026-07-07: Phase 2 deployed and confirmed live**, though not
exactly as originally planned — see below. Phase 1 (Tier 3 shed/restore event
publishing) still not implemented.

**Deployment deviated from the original plan in two ways, both worth knowing
before touching this again:**

1. **Telegraf runs as a native systemd service on the host (`telegraf.service`),
   not in a Docker container.** The original plan assumed a "new Telegraf
   container" sharing a Docker Compose network with Mosquitto/InfluxDB, so the
   per-source configs (`telegraf_solar.conf`, `telegraf_grid.conf`,
   `telegraf_snmp.conf`) were originally written using Docker service-name
   hostnames (`tcp://mosquitto:1883`, `http://influxdb:8086`). Deployed as a
   bare-host service instead, those hostnames don't resolve — Docker
   service-name DNS only exists inside the Compose network, not on the host or
   via Pi-hole. **Symptom:** `dial tcp: lookup mosquitto on 192.168.88.3:53: no
   such host` (or `influxdb`), agent crash-loops or output silently fails to
   write. **Fix:** use the real LAN IP (`192.168.88.3`) with the appropriate
   port for both the `mqtt_consumer` input `servers` and the `influxdb_v2`
   output `urls` in every config. If a container-based Telegraf is ever
   deployed instead, this would need reverting.
2. **Bucket is `rvtc`, not the planned `rvtc_unified`.** No separate bucket was
   created — Telegraf writes into the same bucket WeeWX/`influxdb2.py` already
   use. Works fine in practice; just don't go looking for `rvtc_unified`, it
   was never created.

**Configs actually deployed** (all in `/etc/telegraf/telegraf.d/`, loaded
together into one agent process per the standard Debian `telegraf.d` drop-in
convention):

| Config file | Input | Notes |
|---|---|---|
| `telegraf_solar.conf` | `mqtt_consumer` on `rvtc/sensors/solar/#` and a fixed list of `rvtc/sensors/inverter/*` topics | Includes a `processors.regex` step extracting `solar_field` from the topic name |
| `telegraf_grid.conf` | `mqtt_consumer` on `rvtc/sensors/grid/#` | |
| `telegraf_snmp.conf` | `inputs.snmp` (3×) — MikroTik router, Synology DS223 NAS, Brother MFC-L2710DW printer | See [5.1](#51-device--gateway-inventory) for polled devices/OIDs-by-category. IP phones (Fanvil, Grandstream) identified as SNMP-capable but not yet responding — likely need SNMP enabled in their own admin UI, not yet done. |

All three confirmed writing successfully via `journalctl -u telegraf` showing
`Loaded outputs: influxdb_v2 (3x)` with no `E!` lines, and cross-checked live
against `mosquitto_sub -h 192.168.88.3 -t 'rvtc/sensors/#' -v` showing solar,
grid, inverter, and GPS all publishing concurrently.

### 1.4 Home Assistant's Role — Data Consumer Only

HA onboarded 2026-06-26 (OI-15, closed). MQTT integration only — no Modbus
integration in HA. An earlier attempt to use HA's native Modbus integration
(`modbus: !include`) caused transaction ID collisions with the Python bridge
scripts (two Modbus masters contending for the same gateway) and was removed.
The `modbus/` directory was deleted from the HA config volume; the old Modbus YAML
files are kept in `~/RV-total-control/config/` for reference only, not loaded.

76 MQTT sensor entities currently defined across EPEVER (15), Grid KWS-303L (9),
Generator KWS-303L (7, unavailable pending install), and SAMLUX (17, some higher
counts reported later — reconfirm actual count before quoting it as current).

### 1.5 RS-485 / Modbus Gateway Topology

**Two physically and logically separate RS-485/Modbus paths exist — do not
conflate them:**

**A. SAMLUX EVO-2212** has its own dedicated Waveshare Modbus TCP gateway at
`192.168.88.12:4001`, polled directly by `samlux_mqtt.py` (10s interval, 27
registers). No shared bus, no EPEVER traffic on this line. Confirmed
(2026-07-06) that SAMLUX does **not** need to be added to the EPEVER's
RS485-1M2S module — it has its own independent path entirely.

**B. EPEVER MPPT60 controller** has its own separate RS-485 line, extended via an
**EPEVER RS485-1M2S Extension Module** (official EPEVER accessory, manual v1.2
confirmed 2026-07-06). This module is a **passive multi-drop electrical tap, not
an active bus arbitrator** — it has no collision detection, queuing, or
arbitration logic. It physically parallels two "master-port" connectors
(⑧/⑨, wired to the controller/inverter) with two independent "slave-port"
connectors (④/⑤, wired to monitoring devices — MT50, PC software, WiFi/Bluetooth
modules).

  ⚠️ **Naming trap:** EPEVER's manual calls the controller-facing ports "master
  port" and the monitoring-facing ports "slave port" — this describes *physical
  position*, not Modbus protocol roles. In actual Modbus terms, the EPEVER
  controller is the **slave** (it responds to polls); MT50 and the Python bridge
  script are both Modbus **masters** (they issue polls). Don't let the module's
  port labels be misread as a statement about which device is the real Modbus master.

  EPEVER's own documented compatibility table lists "controller + two
  simultaneous monitors" (e.g. MT75+WiFi, Bluetooth+WiFi) as a normal supported
  configuration, not a workaround — so running MT50 + the Python bridge script
  concurrently on this module is within spec. Two independent Modbus masters can
  still theoretically issue overlapping polls and collide, since the module
  doesn't arbitrate — but this is a normal, typically self-recovering RS-485
  condition (timeout/retry), not a design flaw, and matches EPEVER's own intended
  use case for this accessory.

  Auxiliary power note: scenario table shows external battery power is only
  required for the monitoring side when *only* the controller or *only* the
  inverter is connected upstream (not both) — relevant only if a second
  controller/inverter is added to this same module later.

  **This module is genuinely at capacity (confirmed 2026-07-09) — not just
  "currently occupied."** The only way to add another device to it would be
  a second *master* connector; there's no room for another slave-side tap.
  Worth knowing before anyone eyes this module for a future device the way
  the IMU briefly was.

**C. KWS-303L meters (grid + generator)** — grid KWS-303L is on RS-485/3
(`192.168.88.7:4001`), confirmed connected and tested. The generator KWS-303L
will be **bundled onto that same port** once physically installed, rather than
given its own dedicated gateway port — decided because the two meters are
installed right next to each other, inside the same AC breaker box, making a
shared line the practical physical wiring choice. Confirmed 2026-07-09; this
had been decided earlier but never made it into this consolidated document
until now.

**Spare capacity for future devices (noted 2026-07-09):** an HF5142 serial
port server is still on hand — RS-232/RS-485/RS-422 to Ethernet, **not
isolated**. Distinct from the 8-port Waveshare gateway array covered above:
broader protocol support (RS-232 and RS-422 in addition to RS-485), useful if
a future device needs a protocol the Waveshare array doesn't handle, or once
those 8 ports are genuinely full rather than just mostly-allocated. The
"non-isolated" note matters — unlike an isolated gateway, a ground loop or
voltage fault on a connected device's serial line could affect the HF5142 (or
whatever it's networked to) directly, worth keeping in mind when deciding
what gets connected to it versus what stays on the Waveshare array.

### 1.6 Open Question — HA's Role in Actuation (Phase 7)

Raised 2026-06-30, **deliberately unresolved**. Should Tier 1–4 load management
logic live in HA, or move to a standalone `load_controller.py` (same pattern as
the bridge scripts) subscribing to existing MQTT sensor topics and writing to
relays directly, with HA reduced to a pure display/manual-control surface (or
removed from actuation entirely)?

**Decision explicitly deferred** until Tier 3 has real live operating history —
evidence-based, not reactive to any one session's friction. Setup-time friction
(YAML structure, schema changes) is explicitly **not** a factor in this decision;
the criterion is day-to-day operational cost, reliability, and maintainability for
whoever runs the finished system.

Candidate alternative if HA is found unsuitable: standalone `load_controller.py`
subscribing to `rvtc/sensors/grid/#`, `rvtc/sensors/generator/#`,
`rvtc/sensors/inverter/#`, running the Tier 3/4 state machine in plain Python,
writing to relays directly (same pattern as `relay.py`/`kws_relay.py`). Manual
controls would become MQTT publishes from a lightweight page on `rvtc.lan` via
Mosquitto's websocket support — no backend API server needed.

**Evidence accumulated so far (does not resolve the question, just logged per the
Phase 7 criteria):**
- Microwave relay Dev Tools incident (2026-07-05/06) — root cause traced to
  something *upstream of HA* (see [2.3](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed)),
  not an HA fault per se.
- Load shed race condition (2026-07-06) — if confirmed, this **is** an HA-specific
  fault (automation timing/config), unlike the microwave incident.
- EPEVER SOC swings (2026-07-06) — root cause was upstream at the *sensor/
  controller* level (wrong battery profile), invisible to and unrelated to HA
  entirely. Logged as a data point that had nothing to do with HA, for contrast.

### 1.7 Network / Router Topology (MikroTik)

> ✅ **Deployment status (updated 2026-07-06): all three original deltas now
> genuinely confirmed live**, after an initial false-positive on one of them.
> The three targeted commands:
> ```
> /interface list member remove [find interface=ether8 list=LAN]
> /ip firewall filter remove [find comment="Pinhole: club LAN to RVTC WeeWX port 80"]
> /ip pool set [find name=dhcp] ranges=192.168.88.100-192.168.88.254
> ```
> **DHCP pool change — confirmed live and functioning.** System log shows
> `"pool dhcp changed by admin"` (2026-07-06 09:53); QuickSet confirms the range
> `192.168.88.100–192.168.88.254`; a client was observed receiving a real lease
> at `192.168.88.222` (inside the new range) minutes later.
>
> **`ether8` LAN-list removal — confirmed via system log.** `"interface list
> member removed by admin"`, same timestamp.
>
> **Firewall filter pinhole removal — initially failed silently, now genuinely
> fixed.** The original command searched for the exact comment
> `"Pinhole: club LAN to RVTC WeeWX port 80"`, but the live rule's actual
> comment lacked the `" port 80"` suffix — a RouterOS `find` with no match
> makes `remove` a silent no-op, so the first attempt did nothing despite
> returning no error. Caught via a live `/ip firewall filter print` export.
> **Corrected command was run 2026-07-06** —
> `/ip firewall filter remove [find comment="Pinhole: club LAN to RVTC WeeWX"]`
> — and confirmed removed via `/ip firewall filter print where comment~"WeeWX"`
> returning zero rows. This is now genuinely closed.
>
> **Separate finding from the same export, partially resolved: duplicate
> firewall/NAT rule sets.** See
> [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06)
> for full detail. The operationally important part is now resolved: the
> HOME/OFF-GRID mode-toggle command (`find comment=Rogers`) was confirmed via
> `print detail` to unambiguously target one specific rule, not any of its
> disabled duplicates — so the toggle script isn't at risk of silently hitting
> the wrong rule. A **new, separate finding** from that same check: the
> real Rogers masquerade rule is currently **enabled** (OFF-GRID-style NAT
> behavior), while the router's WAN address at the time looked like it was on
> a home network — worth confirming whether that mismatch is intentional. Full
> cleanup of the remaining dead-duplicate rules and the input/forward filter
> chain duplication is still open, but no longer urgent — see 2.6.

**Why the full `.rsc` file was not imported directly:** the file is structured
like a from-scratch build script (`comment=defconf` tags throughout), most
likely originally generated right after a full config wipe. It contains only
`add` commands, not the `remove`/`set` commands needed to undo what's already
present on a *running* router. Pasting it as-is onto the live device wouldn't
have removed `ether8` from `LAN` or deleted the old WeeWX pinhole (a script
can't remove what it never mentions) — and since firewall/NAT rules have no
uniqueness check, most `add` lines would have created **duplicate rules**
instead of applying cleanly. The targeted three-command approach above achieves
the identical end state without that risk.

**Unrelated finding, worth logging separately:** the terminal session used to
run these commands surfaced an unread system log entry —
`critical router was rebooted without proper shutdown, jun/27/2026 16:53:01`.
This predates all of this session's changes by more than a week and is
**unrelated to the ether8/pinhole/DHCP work** — logged at
[2.5](#25-mikrotik-improper-reboot-jun27-2026--unconfirmed-cause-not-yet-investigated)
since it's a standalone reliability data point, not resolved here.

**Hardware:** MikroTik CRS109-8G-1S-2HnD. Config revision dated 2026-06-09,
author VE7CBH, **applied live 2026-07-06** (see deployment status above).
Source file: `rv-mikrotik-config_ether8_fix.rsc`. Prior version
(`rv-mikrotik-config.rsc`, dated 2026-05-29 — what the router ran before
2026-07-06) reviewed 2026-07-06 — both files compared directly line-by-line,
not just inferred from the changelog comment.

**Confirmed by direct comparison between the two `.rsc` file versions:**
1. `ether8` removed from the `LAN` interface list member (prior version had
   `add interface=ether8 list=LAN`; current version omits it — ether8 sits only
   on the `passthrough` bridge, never joins `LAN`). **Applied live 2026-07-06,
   confirmed via system log.**
2. The `"Pinhole: club LAN to RVTC WeeWX port 80"` forward-chain filter rule
   (src `192.168.0.0/21` → dst `192.168.88.3:80`) is absent from the newer
   `.rsc` file's PINHOLES section — the file *specifies* removing it, matching
   the stated rationale (dst-nat handles it alone; the filter pinhole was never
   reached). **NOT actually removed live as of 2026-07-06** — the removal
   command failed silently due to a comment-text mismatch (the live rule's
   comment lacks " port 80"). Still present on the router — see the corrected
   command in the deployment status banner above and
   [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06).

**Undocumented third change found by comparison, applied live 2026-07-06:**
the DHCP pool range was narrowed from
`192.168.88.10–192.168.88.254` (prior) to `192.168.88.100–192.168.88.254`
(current) — i.e. addresses `.10` through `.99` were pulled out of the dynamic
pool. **Confirmed 2026-07-06:** this was done because the static
reservation/fixed-IP list was filling up under `.10–.99` as more sensors and
bridge devices (SAMLUX gateway, EPEVER gateway, KWS gateways, HA host, etc.)
were given fixed addresses — narrowing the dynamic pool's start avoided
collisions between DHCP-assigned leases and the growing reserved block.

**Earlier history, for context (from this file's own changelog, one version
further back — the 2026-04-29 config itself was not reviewed, only referenced):**
the 2026-05-29 version's own changelog states it added Pi-hole as primary DNS
(`192.168.88.3`, with `8.8.8.8` as fallback) and added both the WeeWX dst-nat
rule and the (now-removed) WeeWX filter pinhole. So the WeeWX external-access
path and Pi-hole DNS both date to 2026-05-29, one revision before the ether8 fix.

**Dual WAN, two operating modes:**

> ⚠️ **Real-world usage confirmed 2026-07-06 doesn't match the interface
> naming.** The names below (`rogers-wan`, `starlink-wan`) reflect original
> design intent, not necessarily current practice — see the corrected
> description underneath the table.

| WAN | Interface | Distance | As named in config | As actually used (confirmed 2026-07-06) |
|---|---|---|---|---|
| `rogers-wan` | ether1 | 1 (primary) | "Rogers cellular" | **Only ever connected at two fixed locations: home, or the club — always wired into an existing network there.** Confirmed 2026-07-06: this port is **never** used for a cellular connection. If cellular data is needed, it's handled entirely separately (e.g. via a phone's own hotspot), not through this router's WAN ports at all. The "Rogers cellular" naming reflects original design intent that was never actually carried out this way in practice. |
| `starlink-wan` | ether2 | 2 (failover) | "Starlink failover" | A physical RJ45 port on the side of the trailer, used for **everything away from home/club**: if the current site has its own wired internet, that gets plugged in here; if not, the Starlink dish's ethernet output goes here instead. Functionally this is an **"AWAY" port**, not Starlink-specific — it just happens that Starlink is the fallback when a site has no wired option, and the person using it is the only one who needs to remember that distinction. |

Both WAN DHCP clients use `add-default-route=yes` — **no static default routes
exist**; failover between whichever WAN is actually connected is handled
entirely by DHCP client distance values plus check-gateway. In practice, only
one of the two physical ports is ever connected at a time (home/club uses
`rogers-wan`; anywhere else uses the `starlink-wan`/AWAY port), so the
distance-based failover logic mostly doesn't come into play — whichever port
has a live cable is the one that gets a DHCP lease and a default route.

**HOME mode vs. OFF-GRID/"AWAY" mode** — this is a manually toggled pair of
states tied to *which port has a cable plugged in*, not an automatic failover
between two simultaneously-connected WANs:

- **HOME** (`rogers-wan` connected — always at home or the club): Rogers NAT
  (masquerade) is **disabled** per this design. The RV subnet
  (`192.168.88.0/24`) becomes visible as a real subnet on the home LAN
  (`192.168.0.0/21`) rather than being NAT'd away. Requires a static route on the
  **home** router: destination `192.168.88.0/24` → gateway = the Rogers WAN's
  DHCP-assigned IP (check via `/ip dhcp-client print` on the MikroTik). Internet
  traffic from the RV subnet is still masqueraded to the wider internet via the
  "Internet NAT home mode" rule, which explicitly excludes the home LAN range so
  home-to-RV traffic isn't accidentally NAT'd.

  > ✅ **Live double-NAT issue found, fixed, and confirmed 2026-07-06.** The
  > router was found running with Rogers masquerade enabled while connected to
  > the home/club network — a genuine double-NAT condition, contrary to this
  > design. Fixed via `/ip firewall nat set [find comment=Rogers] disabled=yes`;
  > confirmed via `print detail` showing rule 0 now flagged `X` (disabled).
  > VOIP phones confirmed still working correctly afterward — the double NAT
  > was not, in fact, needed for VOIP. Full history at
  > [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06).
- **OFF-GRID / "AWAY"** (`starlink-wan` port connected — anywhere other than
  home/club): Rogers masquerade is **enabled**. Confirmed 2026-07-06: despite
  the name, this mode covers *any* away-from-home connection through that
  physical port — a site's own wired internet, or the Starlink dish, whichever
  is available at that location. The name "OFF-GRID" in the original config
  comments and "AWAY" describe the same mode; "AWAY" is arguably the more
  accurate name for what this port actually does day to day, since it isn't
  Starlink-specific.

**Mode toggle (run from MikroTik terminal):**
```
Off-grid : /ip firewall nat set [find comment=Rogers] disabled=no
Home     : /ip firewall nat set [find comment=Rogers] disabled=yes
```

**Bridges — two, intentionally kept separate:**

- `bridge` — the main trusted LAN bridge. Ports: ether3–ether7, sfp1, wlan1.
  This bridge is the only one in the `LAN` interface list.
- `passthrough` — a **separate** bridge holding only `ether8`.

**ether8 / passthrough bridge — the specific fix this file documents:**
`ether8` was deliberately removed from the main LAN bridge and the `LAN`
interface list, and placed on its own `passthrough` bridge instead. Rationale
stated directly in the file: ether8 is on a dedicated passthrough path and **must
not be treated as a trusted LAN interface** by the firewall. Practically, this
means anything wired to ether8 does **not** inherit the LAN-trust firewall
posture (input accept-from-LAN rules, forward rules scoped to the `LAN` interface
list) that ether3–ether7/sfp1/wlan1 get.

**Purpose (confirmed 2026-07-06):** ether8 is currently **not connected to
anything** — it's reserved capacity, kept available in case a device needs to
reach a WAN directly, bypassing the MikroTik's routing/firewall/NAT entirely.
Nothing is planned for it; it's a just-in-case path. That's exactly why it was
pulled out of the LAN bridge and interface list in the first place — if
something is ever plugged in here, it's meant to have a raw, un-firewalled,
un-NAT'd path, not the RV's normal trusted-LAN posture. Worth remembering *why*
next time it's used: if a device ever does go on ether8, it should not be
assumed to have the same protections (drop-invalid, drop-unsolicited-WAN) as
everything else on the `bridge`/`LAN` side.

**Also fixed in this revision:** a redundant forward-chain firewall pinhole for
WeeWX port 80 (`src-address=192.168.0.0/21` → `dst 192.168.88.3:80`) was removed.
Per the changelog, this rule was never actually reached: in HOME mode the broader
HOME MODE forward rules match first, and in OFF-GRID mode the traffic arrives via
dst-nat so the pinhole's `src-address` condition never matches NAT'd WAN traffic
anyway. The dst-nat rule in the NAT table (below) fully handles WeeWX external
access on its own — the filter-chain pinhole was dead weight, not a second layer
of defense.

**DNS:** Pi-hole (`192.168.88.3`) is the primary DNS server for the RV subnet,
with `8.8.8.8` as secondary fallback — matches the DNS server note already logged
for the HA MQTT broker's host.

**Firewall structure (summary — see the `.rsc` file itself for exact rule order):**

- *Input chain*: accept established/related/untracked → drop invalid → accept
  ICMP → accept loopback → **(HOME MODE)** accept management from home LAN via
  `rogers-wan` → drop everything else not arriving from a LAN-list interface.
- *Forward chain*: fasttrack + accept established/related (hardware acceleration)
  → accept IPsec in/out → **(HOME MODE)** bidirectional accept between home LAN
  and RV LAN → drop invalid → drop unsolicited WAN inbound that wasn't dst-nat'd.

**NAT table:**

| Rule | Chain | Action | Purpose |
|---|---|---|---|
| "Rogers" | srcnat | masquerade | Disabled in HOME mode; toggled on for OFF-GRID |
| "Starlink" | srcnat | masquerade | Always enabled |
| "Internet NAT home mode" | srcnat | masquerade | Masquerades RV subnet's internet traffic only; excludes home LAN dest |
| "Pinhole: WeeWX port 80" | dstnat | dst-nat | `rogers-wan:80` → `192.168.88.3:80` — the sole mechanism for WeeWX external access |

**WeeWX external access path (end to end):**
```
Club LAN (http://wifi.solsante.com:8080)
  → club router forwards port 8080 → MikroTik rogers-wan:80
  → dst-nat → 192.168.88.3:80 → nginx → WeeWX
```

**Adding a new pinhole** (exposing a specific RV host to the home LAN) — documented
procedure directly in the config file:
```
/ip firewall filter
add action=accept chain=forward \
    comment="Pinhole: <description>" \
    src-address=192.168.0.0/21 \
    dst-address=<RV host IP>
```
Must be manually dragged above the drop rules in Winbox after adding — rule order
matters and isn't automatic.

**Addressing (confirmed live as of 2026-07-06):** RV subnet `192.168.88.0/24`
on the `bridge` interface (gateway `192.168.88.1`), DHCP pool
`192.168.88.100–192.168.88.254`. Wireless AP: `VE7CBH_Mikrotik`, 2.4GHz b/g/n.

**RouterOS upgraded 6.49.20 → 7.23.2, 2026-07-07.** Full binary backup
(`pre 7.x upgrade.backup`, cloud-uploaded) and `.rsc` export taken first.
Post-upgrade verification, all confirmed intact: DHCP reservations (all
`485-1` through `485-8` plus every other static lease), firewall rules,
dual-WAN recursive failover (tested by physically moving the club WAN feed
from the Rogers port to the Starlink port — default route correctly failed
over from distance-1 to distance-2). One transient false alarm during
testing: a route dialog briefly showed `192.168.1.0/24` resolving through
both `rogers-wan` and `starlink-wan` simultaneously — this was a stale
recursive-route cache artifact caught mid-swap, not an actual dual-connection
or switch-chip port-grouping issue; independently re-verified clean on both
WAN ports afterward. No config regressions found from the v6→v7 major-version
jump.

**Open items from this file:**
- Confirm the home/club router's static route (`192.168.88.0/24` → Rogers WAN
  IP) is actually configured, now that Rogers NAT is properly disabled and the
  RV subnet should be reaching the home LAN unmasqueraded — see
  [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06).
- Low-priority cosmetic cleanup of dead duplicate firewall/NAT rules — see
  [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06).
- Which of `485-1/2/4/5` is EPEVER vs. grid KWS-303L — see [5.5](#55-rs-485-bus--gateway-ip-addressing).
- Root cause of the 2026-06-27 improper-shutdown reboot — see
  [2.5](#25-mikrotik-improper-reboot-jun27-2026--unconfirmed-cause-not-yet-investigated).

---

## Part 2 — Known Issues & Root Causes

### 2.1 EPEVER Battery SOC Swings — RESOLVED

**Symptom:** Grafana Battery SOC trace showed a wide sinusoidal/sawtooth swing
(e.g. 37–89% observed 2026-07-06) that visibly widened whenever a load (inverter
draw, e.g. coffee maker) was placed on the system.

**Root cause (confirmed 2026-07-06):** The EPEVER MPPT60 controller's `battery_soc`
register (12570) is voltage-derived, not coulomb-counted — no current-integration
input feeds it. The controller had reverted to its **default flooded lead-acid
battery-type profile** rather than the correct **LiFePO4** profile (likely during/
after MT50 disconnection or a power cycle — exact trigger not confirmed). LiFePO4
has a very flat voltage curve through most of its usable range; a flooded-profile
curve maps a small IR-drop voltage sag (from inverter current draw pulling down
battery terminal voltage) onto a large apparent SOC swing, because the wrong curve
treats a flat plateau as a steep gradient.

**Fix applied:** Battery-type profile corrected to LiFePO4 via MT50 (required
plugging MT50 back in via the RS485-1M2S module — see [1.5](#15-rs-485--modbus-gateway-topology)).
SOC trace smoothed dramatically and immediately upon profile change.

**Not yet fully closed:**
- Why the profile reverted to flooded in the first place is unconfirmed — could be
  a factory default that was simply never explicitly set, or an actual reset
  triggered by a power event or the earlier HA/Modbus master conflict. If the
  latter, it could recur after a future power blip. **Recommend explicitly setting
  and re-verifying the profile after any future full power-down.**
  I should confirm: check this on next session and verify.
- Confirm the estimator has fully re-converged after a complete charge/discharge
  cycle, not just the initial ~20 minute settle observed.
- A secondary sawtooth pattern observed after the fix, with a data gap misread on
  first look as a flat "held steady" segment — the gap was later identified as the
  RS485 bus being intentionally disconnected during RS485-1M2S installation, not a
  real reading. **When reviewing this graph later, do not mistake that flat segment
  for a genuine SOC plateau.**
- The regular post-fix sawtooth (pre- and post-gap) still needs correlating against
  `load_current`/`charging_current` from the same window to confirm it's a real
  cyclic load (e.g. fridge compressor) rather than anything else. Not yet done.
- Some residual ripple under load is expected and correct even with the right
  profile (real IR drop still exists, just much smaller) — a moving-average
  overlay in Grafana is a reasonable visual smoothing choice for the dashboard,
  but no longer masks a wrong underlying number.
- **True fix for the underlying voltage-estimation limitation** (not just the
  profile mismatch) is HW-24, the DC shunt (400A, ordered) — coulomb counting is
  immune to instantaneous voltage sag from any device's current draw, unlike a
  voltage-curve estimate from either the EPEVER or the SAMLUX.

### 2.2 Manual Load Shed Intermittent Failures — SUSPECTED CAUSE, UNCONFIRMED

**Symptom:** Manual shed switches (water heater / microwave) intermittently have
no effect on first press, working correctly on a second press, with no config
change in between and no error in any trace/log.

**Standing hypothesis (NOT YET CONFIRMED):** A restore-check race condition.
`Tier 3 - Grid/Generator Restore Check` automations run unconditionally every 60
seconds and restore a coil whenever it's marked `energised`, without checking
whether the corresponding **manual** shed input_boolean
(`manual_shed_water_heater` / `manual_shed_microwave`) is currently on. A manual
shed and the automatic restore-check can end up fighting over the same coil on a
timer, with neither side raising an error because neither is "wrong" from its own
point of view.

**What's confirmed solid (ruled out as causes):** relay hardware/wiring/polarity,
`relay.py` itself (tested inside the HA container, bypassing HA entirely),
network path to the gateway, `shell_command` service registration/execution,
and the automations' YAML structure — all independently verified correct.

**Not yet done (highest-value next step):** Review `scripts.yaml`'s
`tier3_grid_restore` / `tier3_generator_restore` to check whether either
references the manual-shed input_booleans as a condition. Their absence would
confirm the hypothesis outright without needing to catch it live.

**If it recurs:** check Logbook *first*, before re-testing anything, for either
restore script firing within ~60s of the failed press. **Do not** re-run the full
hours-long manual isolation process from scratch.

**Explicitly retracted:** a theory that this was a stale Developer Tools/UI/
WebSocket blip — does not fit a press registering zero effect with no trace, and
should not be reused as an explanation without genuinely new evidence.

### 2.3 Microwave Relay Missing from Dev Tools — LEADING THEORY, UNCONFIRMED

**Symptom (2026-07-05 evening):** `shell_command.relay_2_on` (microwave)
completely absent from Developer Tools → Actions, unlike working `relay_1_*`
(water heater). Persisted even after a full HA core restart. Worked correctly the
next morning with zero config changes made in between.

**Leading explanation (NOT confirmed):** Developer Tools → Actions loads its
service list once per browser session/tab load. If the same tab was checked
immediately after restart, it may have shown a stale, pre-restart service list
rather than re-querying HA. Supported by: totally clean/silent logs at restart
time (no shell_command/relay_2 error or warning at all), and the fix "appearing"
overnight with no changes made.

**Standing rule adopted regardless of root cause:** After any HA restart intended
to pick up new/changed `shell_command:` entries, verify via a hard-refreshed or
newly-opened Developer Tools tab — not one already open before the restart —
before concluding the fix did or didn't work.

**Filed as a data point** for the Phase 7 HA-actuation-suitability question (see
[1.6](#16-open-question--has-role-in-actuation-phase-7)) — an instance of
"looked broken, wasted real troubleshooting time, root cause unconfirmed," not a
resolved bug.

### 2.4 Unidentified rtl_433 Devices — UNRESOLVED, NOT YET INVESTIGATED

Four `rtl_433/{mac}/availability` topics appeared during the 2026-07-02 payload
audit that don't correspond to either known rtl_433 container (`rtl433`,
`rtl433b`): `979a52e42f15`, `371c2d98fb4f`, `dd2487a13637`, `296813f2bc3e`.
Something else is publishing into the `rtl_433/` namespace.

**Action required before extending anything onto the `rtl_433/` topic tree:**
run `mosquitto_sub -h localhost -t 'rtl_433/+/availability' -v` and cross-reference
the MACs against `docker ps` and MikroTik DHCP leases.

### 2.5 MikroTik Improper Reboot (Jun 27, 2026) — UNCONFIRMED CAUSE, NOT YET INVESTIGATED

**Found 2026-07-06** as an unread system log entry surfaced during an unrelated
terminal session (applying the ether8/WeeWX-pinhole/DHCP-pool fixes — see
[1.7](#17-network--router-topology-mikrotik)):

```
critical router was rebooted without proper shutdown, jun/27/2026 16:53:01
```

This predates that session's changes by more than a week and is unrelated to
them — it's an independent reliability event that simply hadn't been noticed
until the log was viewed for another reason.

**Not yet investigated at all.** No cause has been proposed or ruled out. Worth
considering (not confirmed, purely candidate causes to check):
- A genuine power interruption to the router itself — worth checking whether
  this correlates with any other logged power event around the same date (e.g.
  Tier 3 shed activity, inverter mode changes, or a wider RV electrical event) —
  no such correlation has been checked yet.
- A router crash/hang unrelated to power (firmware issue, resource exhaustion)
  — RouterOS logs "improper shutdown" for any reboot that wasn't a clean
  `/system reboot` or `/system shutdown`, which includes both power loss and
  crashes; the log entry alone doesn't distinguish between them.

**What to check next, if this recurs or is investigated retroactively:**
- Full system log around `2026-06-27 16:53` for anything else logged just
  before the gap (last entry before the reboot) — may hint at cause.
- Cross-reference against SAMLUX/EPEVER/KWS MQTT data from the same timestamp,
  if retained in InfluxDB, to check whether the wider system also lost power at
  that moment or whether it was router-specific.
- Whether this has happened more than once — a single occurrence a week old is
  a low-urgency data point; a pattern would not be.

### 2.6 Duplicate Firewall/NAT Rule Sets — PARTIALLY RESOLVED 2026-07-06

**Found 2026-07-06** via a live `/ip firewall filter` + `/ip firewall nat`
export (`my-firewall-rules.rsc`), obtained while investigating why the WeeWX
pinhole removal (see [1.7](#17-network--router-topology-mikrotik)) hadn't
worked. **Not caused by anything in this week's session** — this appears to be
a pre-existing condition, likely accumulated over multiple historical config
imports.

**WeeWX pinhole — now actually removed.** The corrected command
(`/ip firewall filter remove [find comment="Pinhole: club LAN to RVTC WeeWX"]`)
was run 2026-07-06 and confirmed via `/ip firewall filter print where
comment~"WeeWX"` returning zero rows. This item from [1.7](#17-network--router-topology-mikrotik)
is now genuinely closed.

**What the export showed:**

- **Input filter chain:** two full, overlapping copies of the base
  accept/drop rule set (accept established/related/untracked, drop invalid,
  accept ICMP, accept loopback, drop-not-from-LAN). The second copy also
  includes the `"HOME MODE: accept input from home LAN"` rule that the first
  copy lacks — consistent with an older, pre-HOME-MODE base ruleset never
  having been cleared before a newer one (with HOME MODE added) was layered on
  top.
- **Forward filter chain:** same pattern — two full overlapping copies of the
  base ipsec/fasttrack/established/drop-invalid/drop-unsolicited-WAN rules. The
  second copy additionally included both HOME MODE bidirectional forward rules
  **and** the WeeWX pinhole (now removed, see above). **Still not deduplicated
  otherwise** — the two overlapping base rule sets in both input and forward
  chains remain as-is.
- **NAT table — Rogers rules confirmed via `print detail` 2026-07-06:**

  | # | Comment | State | Conditions |
  |---|---|---|---|
  | 0 | `Rogers` (exact) | **enabled** | `out-interface=rogers-wan`, `out-interface-list=WAN`, `ipsec-policy=out,none` |
  | 1 | `NAT for Rogers` | disabled | `out-interface=rogers-wan` only — no `out-interface-list`, no `ipsec-policy` (a broader match than rule 0/2 if ever enabled — would also NAT IPsec traffic, unlike the other two) |
  | 2 | `Rogers  disabled in HOME mode, enable for OFF-GRID` | disabled | identical conditions to rule 0 |

  **Starlink side of the NAT table not yet checked with the same `print
  detail` precision** — presumed to have an analogous 2–3 rule pattern based on
  the earlier full-file review, but not directly confirmed the way Rogers now
  is.

**Resolved — which rule the mode-toggle command actually targets:**

The documented HOME/OFF-GRID toggle procedure ([1.7](#17-network--router-topology-mikrotik))
is:
```
Off-grid : /ip firewall nat set [find comment=Rogers] disabled=no
Home     : /ip firewall nat set [find comment=Rogers] disabled=yes
```
`find comment=Rogers` is an exact-string match, and only rule 0 has that exact
comment — **confirmed 2026-07-06 via `print detail` that this is unambiguous.**
Rules 1 and 2 are inert, disabled, and never touched by the toggle script
regardless of duplication. The earlier concern that the toggle might be
silently hitting the wrong rule is resolved: **it isn't.** Rules 1 and 2 are
genuinely safe dead weight, not a live risk.

**RESOLVED 2026-07-06 — fix applied and confirmed working, correcting an
earlier back-and-forth that had gotten the design intent backwards.** Rule 0
(the real one, confirmed the sole rule the toggle script controls) was found
**enabled** (Rogers masquerade active) while connected to the home/club network
via `rogers-wan`. Per the documented architecture ([1.7](#17-network--router-topology-mikrotik)),
**HOME mode is specifically designed to run with this rule disabled** — that's
the entire point of HOME mode: avoiding a double-NAT situation (RV subnet →
MikroTik NAT → home/club router's own NAT → internet), which is itself a
common cause of VOIP registration/one-way-audio problems. Confirmed live via
`/ip firewall nat print detail where comment~"Rogers"`, checked twice, that
rule 0 showed no `disabled` flag before the fix. An earlier note in this doc
incorrectly called this "intentional, kept for VOIP" based on a
miscommunication — that was wrong and has been corrected here.

**Fix applied:**
```
/ip firewall nat set [find comment=Rogers] disabled=yes
```
**Confirmed via a third `print detail` check:** all three Rogers-related NAT
rules (0, 1, 2) now show the `X` (disabled) flag — rule 0 in particular, the
one that matters, is confirmed disabled. **VOIP phones (WP820, Fanvil — see
[5.5](#55-rs-485-bus--gateway-ip-addressing)) confirmed still working correctly
after the fix** — settles the open question definitively: double NAT was never
needed for VOIP to function; if anything, double NAT is a more common cause of
VOIP trouble than a cure for it.

**One remaining open item from this fix:** whether the home/club router
actually has the documented static route (`192.168.88.0/24` → Rogers WAN's
DHCP IP) configured, so the RV subnet is genuinely reachable from the home LAN
now that it's no longer masqueraded away — not yet independently confirmed,
only VOIP/general internet access has been checked.

**Remaining cleanup work (cosmetic, low priority):**
1. Remove the two dead Rogers duplicates (rules 1 and 2) — cosmetic/tidiness
   only at this point, not urgent.
2. Check Starlink's NAT rules with the same `print detail` precision to confirm
   the analogous pattern and rule out any live-vs-dead ambiguity there too.
3. Deduplicate the input/forward filter chains' overlapping base rule sets —
   get a full `print detail` for both chains first, confirm rule order and
   exact conditions don't meaningfully differ between the two copies, before
   removing either one.
4. Once cleaned up, consider giving the mode-toggle's target rule a more
   deliberately unique comment (it works fine as `Rogers` today only because
   nothing else happens to share that exact string — worth not relying on that
   by accident going forward).

---

## Part 3 — Backlog

### 3.1 Hardware

| ID | Item | Status |
|---|---|---|
| HW-03 | Install 4×100W PV panels | ✅ Closed |
| HW-04 | Wire 9 PV panels (3S×3P) | ✅ Closed |
| HW-09 | Generator meter — set slave 2 on bench, wire onto RS-485/3 (bundled with grid KWS, same port — see [1.5C](#15-rs-485--modbus-gateway-topology)) | Open — physical install pending; port/architecture decided |
| HW-10 | Install GNSS E108-GN03G-485 (RS-485/6, device in hand) | ✅ Closed 2026-07-07 — module replaced, `gps_mqtt.py` deployed and confirmed publishing |
| HW-13 | Waveshare 8-ch RS-485 relay board — load shed (RS-485/8) | ✅ Closed — confirmed connected and tested (surfaced 2026-07-09 via gateway addressing table; wasn't previously tracked in this doc's backlog) |
| HW-16 | Ecowitt WN90LP weather station (shipped — RS-485/7) | Open |
| HW-18 | HSR1-25 25A NO relay — water heater + fridge AC wiring | Open |
| HW-19 | 12V→5V DC-DC converter to power relay board | Open |
| HW-20 | ESP32-S3 Touch LCD thermostat — fish DMX cable, firmware | Open |
| HW-21 | Wire coil 5 — EVO BMS charge inhibit | Open |
| HW-22 | Install battery heater, wire coil 6 | Open |
| HW-23 | RS485-1M2S — reconnect MT50 | ✅ Closed 2026-07-06 — installed, MT50 reconnected, confirmed as a documented passive multi-drop tap (see [1.5](#15-rs-485--modbus-gateway-topology)) |
| HW-24 | DC shunt 400A RS-485 (ordered) | Open — see [2.1](#21-epever-battery-soc-swings--resolved), true fix for voltage-based SOC limitation |
| HW-25 | IMU node — NodeMCU ESP32 + Adafruit 10-DOF (LSM303DLHC/L3GD20/BMP180) + SH1106 OLED | In progress 2026-07-09 — firmware written, not yet flashed/bench-tested. Heading feeds future wind-direction true-north correction; local phone page shows live heading/pitch/roll/bounce. See [5.1](#51-device--gateway-inventory) |

### 3.2 Software

| ID | Item | Status |
|---|---|---|
| OI-15 | HA onboarding | ✅ Closed 2026-06-26 |
| OI-16 | Rebuild Grafana weather dashboard | Open |
| OI-18 | ESPHome Ansible role | Open |
| OI-24 | Load & energy management automation (Tier 1–4) | Open — blocked on HW-18/21/22 |
| OI-37 | Portainer container management UI | Open — flagged as quick win |
| OI-38 | ESP32-S3 thermostat firmware | Open |
| OI-39 | ESP32 Modbus polling register list | Open |
| — | ~~Apply `rv-mikrotik-config_ether8_fix.rsc` to the live MikroTik router~~ | ✅ Closed 2026-07-06 — applied via three targeted terminal commands rather than full `.rsc` import. See [1.7](#17-network--router-topology-mikrotik) |
| — | ~~Reconfirm MikroTik changes via `/ip pool print`/QuickSet~~ | ✅ DHCP pool + ether8/LAN-list removal confirmed live via system log + QuickSet. ⚠️ Firewall-filter-pinhole removal is CONFIRMED NOT applied — see next row |
| — | ~~Run corrected WeeWX filter-pinhole removal command~~ | ✅ Closed 2026-07-06 — corrected command run and confirmed removed via print |
| — | Clean up dead duplicate firewall/NAT rules on MikroTik | Open, low priority — confirmed cosmetic only; mode-toggle reliability risk ruled out. See [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06) |
| — | ~~Fix live double-NAT / disable Rogers masquerade while on home network~~ | ✅ Closed 2026-07-06 — `disabled=yes` applied, confirmed via print, VOIP phones confirmed still working. See [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06) |
| — | Confirm home/club router's static route to RV subnet is actually configured | Open — see [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06) |
| — | Investigate MikroTik improper-shutdown reboot (2026-06-27) | Open — see [2.5](#25-mikrotik-improper-reboot-jun27-2026--unconfirmed-cause-not-yet-investigated) |
| — | `tier3_grid_restore`/`tier3_generator_restore` review | Open — see [2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed), highest-value next debugging step |
| — | Confirm EPEVER SOC estimator fully re-converged after full cycle | Open — see [2.1](#21-epever-battery-soc-swings--resolved) |
| — | Correlate post-fix SOC sawtooth against load/charging current | Open — see [2.1](#21-epever-battery-soc-swings--resolved) |
| — | rtl_433 unknown MAC audit | Open — see [2.4](#24-unidentified-rtl_433-devices--unresolved-not-yet-investigated) |
| — | Telegraf/`rvtc_unified` bucket Phase 2 deployment | Status unconfirmed — check before assuming live |
| — | Phase 1 `mqtt.publish` additions to `scripts.yaml` | Not yet drafted |
| — | KWS grid/generator disconnect switches → Load Control dashboard | Open (carried from 2026-06-30) |
| — | Live bench test of Tier 3 automatic trigger | Still outstanding |
| — | Remove empty `kws303l/` directory | Open |
| — | Suppress default Telegraf system metrics noise (cpu/disk/mem) | Open, low priority |

---

## Part 4 — Chronological Session Log

### 2026-06-09 — MikroTik Router Configuration (ether8 fix, PREPARED — NOT YET DEPLOYED)

Full content consolidated at
[1.7](#17-network--router-topology-mikrotik). Config revision drafted for the
MikroTik CRS109-8G-1S-2HnD (VE7CBH). Prior version (2026-05-29) obtained and
directly compared 2026-07-06 — confirms two changes are correctly specified in
the newer file:
- `ether8` removed from the main LAN bridge/interface list and moved to its own
  `passthrough` bridge, so it will no longer be treated as a trusted LAN
  interface by the firewall once applied. Confirmed 2026-07-06: nothing is
  currently connected to it — it's reserved, just-in-case capacity for a future
  device that needs to reach a WAN directly, bypassing the MikroTik's routing/
  firewall/NAT entirely. Nothing planned; kept available on principle.
- A redundant forward-chain firewall pinhole for WeeWX port 80 removed — the
  existing dst-nat rule already handles WeeWX's external exposure on its own; the
  filter pinhole was never actually reached in either HOME or OFF-GRID mode.

**Additional undocumented change found by direct comparison** (not mentioned in
either file's own changelog): DHCP pool range narrowed from
`192.168.88.10–192.168.88.254` to `192.168.88.100–192.168.88.254`. Confirmed
2026-07-06: done because the static/fixed-IP reservation list under `.10–.99`
was filling up with the growing number of sensors and bridge devices (SAMLUX,
EPEVER, KWS gateways, HA host, etc.), so the dynamic pool's start was moved to
avoid collisions with that expanding reserved block.

**Deployment status (confirmed 2026-07-06, important): none of the above is
confirmed live on the router yet.** A QuickSet screenshot from the live device
shows the DHCP Server Range still at the *old* `.10–.254` value — meaning the
`ether8_fix` config was reviewed and its contents verified correct, but has not
actually been imported/applied to the physical router. **Action item added to
backlog** ([3.2](#32-software)): apply the config and reconfirm via
`/ip pool print` (or QuickSet) before treating any of this section as the live
architecture.

This session predates the earliest of the other consolidated session notes
(2026-06-26) — included here for completeness since the router underlies every
other subsystem's network path (MQTT broker reachability, WeeWX external access,
HA availability from outside the RV subnet, etc.).

### 2026-06-26 — HA Onboarding, SAMLUX Bridge, Telegraf

- HA onboarding wizard completed (OI-15 closed). Location: Nanaimo BC. MQTT
  integration added (broker `192.168.88.3:1883`, no auth).
- **Architecture correction:** HA's native Modbus integration was removed after
  causing transaction ID collisions with the Python bridge scripts on all three
  gateway IPs (two Modbus masters contending for one gateway). `modbus/` directory
  deleted from the HA config volume; old YAML kept in `~/RV-total-control/config/`
  for reference only. HA now consumes exclusively via MQTT.
- `samlux_mqtt.py` built and running as a systemd service, polling the SAMLUX
  EVO-2212 every 10s over its dedicated gateway, publishing 27 registers to
  `rvtc/sensors/inverter/#`. All values confirmed via `mosquitto_sub`. See
  [5.2](#52-samlux-evo-2212-key-registers) for the register table.
- Telegraf's `telegraf_solar.conf` updated with an `mqtt_consumer` block for the
  inverter topics. InfluxDB now has `weewx`, `solar`, `grid`, `inverter`
  measurements plus unfiltered system metrics (noise, not yet suppressed).
- `mqtt_sensors.yaml` built — 76 HA entities across EPEVER (15), Grid KWS-303L
  (9), Generator KWS-303L (7, unavailable — pending install), SAMLUX (17).
- Entity registry duplicate cleanup: deleted stale `core.entity_registry` file,
  restarted HA, entities repopulated cleanly from retained MQTT messages.
- Phase 3 hardware: PV panel install (HW-03) and wiring (HW-04) both closed —
  array producing.

### 2026-06-30 — Phase 7 Question Raised

Documented as an addition to Section 9.1 of the master reference doc. See
[1.6](#16-open-question--has-role-in-actuation-phase-7) for full content — the
question of whether HA should own Tier 1–4 actuation logic or hand it to a
standalone Python controller, deliberately deferred until Tier 3 has real
operating history.

### 2026-07-02 — Unified Namespace Architecture Decision

- Reviewed the full data pipeline against the project's "everything lands in one
  database" vision. Found weather (RTL-SDR → rtl_433 → WeeWX → InfluxDB) and power
  (Modbus bridges → MQTT → HA) were two disconnected lanes sharing a broker, not
  one pipeline — power data dead-ended at HA, InfluxDB blind to grid/battery/
  inverter/Tier-3-4 state.
- **Decision:** unified-namespace architecture — one broker as the live bus, one
  generic Telegraf subscriber persisting everything to InfluxDB, InfluxDB as
  single source of truth for history. See [1.2](#12-unified-namespace-mqtt) and
  [1.3](#13-influxdb--telegraf-persistence-layer) for the resulting architecture
  and phased plan.
- Phase 0 payload audit completed: confirmed `rvtc/sensors/{source}/{field}` flat
  scalar shape needs no reshaping. Flagged four unexplained `rtl_433/{mac}/
  availability` topics — see [2.4](#24-unidentified-rtl_433-devices--unresolved-not-yet-investigated).
- Full Phase 1–5 implementation plan drafted (commands, Telegraf config,
  docker-compose addition) — see [1.3](#13-influxdb--telegraf-persistence-layer).

### 2026-07-05/06 — Microwave Relay Incident

Full incident and leading theory documented at
[2.3](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed).
Diagnostic sequence (hardware → config → shell_command registration → restart →
logs → next-morning retest) confirmed hardware, wiring, config, and automation
YAML were all sound before landing on the Dev-Tools-staleness theory, which
remains unconfirmed. Adopted standing rule: verify shell_command changes via a
freshly opened Dev Tools tab after any relevant restart.

### 2026-07-06 (early AM) — Load Shed Race Investigation

Full investigation documented at
[2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed).
Extensive live testing ruled out relay hardware, `relay.py`, network path,
shell_command registration, and automation YAML as causes. Landed on the
restore-check race hypothesis (unconfirmed — `scripts.yaml`'s restore scripts not
yet reviewed). Decision: wait for next recurrence, check Logbook/traces from that
specific moment, rather than repeat the manual isolation process.

### 2026-07-06 — EPEVER SOC / MT50 / RS485-1M2S Investigation

- Grafana Battery SOC panel observed with sinusoidal ripple widening under
  inverter load (coffee maker). Discussed and ruled out RMS smoothing (RMS biases
  upward relative to a true mean for any non-negative noisy signal — a moving
  average/EMA is the statistically correct smoothing approach, not RMS).
- Identified likely cause: EPEVER's `battery_soc` register is voltage-derived,
  not coulomb-counted, so inverter-load-induced IR-drop on battery terminal
  voltage gets misread as SOC movement — worsened if the configured battery-type
  profile doesn't match actual LiFePO4 chemistry.
- MT50 had been disconnected due to an earlier Modbus master-conflict concern.
  Clarified that the user's RS485-1M2S extension module is EPEVER's own official
  accessory, specifically intended for this exact "controller + multiple
  simultaneous monitors" scenario — see [1.5](#15-rs-485--modbus-gateway-topology)
  for the full, manual-verified breakdown of what the module actually does
  (passive multi-drop tap, not an active arbitrator) and the master/slave naming
  trap in EPEVER's documentation.
- MT50 reconnected via the RS485-1M2S module (HW-23 closed). Controller found
  reverted to its **default flooded** battery-type profile. Corrected to
  **LiFePO4** — SOC trace smoothed immediately.
- Confirmed via screenshots: an initial ~15–20 minute re-convergence period after
  the profile change (37% low point), followed by a tighter, higher, and
  regularly-cycling band. A flat segment initially misread as a steady SOC
  plateau was identified as a genuine data gap — RS485 bus intentionally
  disconnected during physical installation of the RS485-1M2S module, not a real
  reading. Post-gap sawtooth still needs correlating against load current to
  confirm it's a real cyclic load (e.g. fridge compressor).
- Confirmed the SAMLUX does **not** need to be added to the EPEVER's RS485-1M2S
  module — it has its own separate dedicated gateway (`192.168.88.12:4001`),
  entirely independent of the EPEVER's RS-485 line.
- Full outstanding items from this session logged under
  [2.1](#21-epever-battery-soc-swings--resolved).

### 2026-07-07 — Grafana SOC/Power Smoothing, GPS Bridge, RouterOS v7 Upgrade, Telegraf/SNMP Deployment

- **Grafana dashboard smoothing carried over to the web panel.** The Grafana
  Battery SOC panel's `timedMovingAverage` win prompted the same treatment for
  `rvtc.lan`'s solar/battery web panel (`index.html`). Implemented as an
  in-browser trailing-average buffer per field (JS, no extra InfluxDB query) —
  90 samples (~3 min) for SOC, 30 samples (~1 min) for PV/charging power —
  rather than modifying the Flux query, since the panel's `queryInflux()`
  pulls every field generically per measurement including discrete state
  codes (`operating_mode`, `alarm_code`, etc.) that must never be averaged.
- **GPS replaced and wired end-to-end.** New u-blox module (multi-constellation
  GPS+BeiDou) gives a solid 3D fix (15-18 sats, HDOP ~0.6-0.8) through the
  existing `192.168.88.10:4001` TCP gateway. `gpsd.service` needed a manual
  restart after boot — it activated before the gateway was reachable and gave
  up rather than retrying (`device activation failed, freeing...`); confirmed
  via `gpspipe -w` showing `"devices":[]` until the restart. Wrote
  `gps_mqtt.py` as a client of `gpsd`'s own protocol (port 2947) rather than a
  second direct poller of the gateway — see [5.1](#51-device--gateway-inventory)
  for the reasoning. Deployed as `gps_mqtt.service`, confirmed publishing to
  `rvtc/sensors/gps/#`.
- **RouterOS upgraded 6.49.20 → 7.23.2.** Full detail, verification steps, and
  the one (resolved, false-alarm) routing anomaly at [1.7](#17-network--router-topology-mikrotik).
- **Telegraf deployed for the first time** — previously only existed as
  unwired `.conf` files in the repo; `telegraf` itself wasn't even installed.
  Also built a new SNMP polling framework (MikroTik, Synology NAS, Brother
  printer — phones pending) via `telegraf_snmp.conf`. Full detail, the
  Docker-hostname deployment gotcha (`mosquitto`/`influxdb` service names
  don't resolve from a bare-host Telegraf), and the actually-deployed config
  list at [1.3](#13-influxdb--telegraf-persistence-layer). End-to-end
  confirmed via `mosquitto_sub` showing solar/grid/inverter/GPS all
  publishing concurrently while Telegraf's own logs showed all three
  `influxdb_v2` outputs writing with no errors — first time the full
  unified-namespace pipeline (device → MQTT → Telegraf → InfluxDB) has been
  verified live end to end since the architecture was decided on 2026-07-02.

### 2026-07-09 — IMU Node Build (HW-25)

- **Parts on the bench:** NodeMCU ESP32-WROOM-32, Adafruit 10-DOF breakout
  (LSM303DLHC accel+mag, L3GD20 gyro, BMP180 baro — a close functional match
  for the originally-scoped diymore 10-axis IMU, plus a bonus barometer/altimeter
  not currently wired into anything), a 1.3" I2C OLED (SH1106 driver — flagged
  before wiring, since 1.3" modules are SH1106 the vast majority of the time,
  not the more common SSD1306 used on 0.96" modules; wrong driver library
  gives a shifted/garbled display rather than a blank one), a TTL-to-RS485
  level shifter (not used in the end — see below), and a 12V→5V converter for
  power.
- **Architecture decided: WiFi + MQTT direct, not RS-485.** Explicit,
  deliberate exception to the project's RS-485-for-everything convention —
  reasoning captured at [1.2](#12-unified-namespace-mqtt). Data is
  real-time-only (heading/pitch/roll/bounce), never persisted to InfluxDB,
  and the node also hosts its own local phone-facing status page directly —
  routing through an RS-485 gateway/bridge hop would've added complexity for
  no benefit here.
- **Firmware written** (not yet flashed/bench-tested) as a PlatformIO C++
  project — repo `rvtc-imu/`. Reuses Adafruit's own proven tilt-compensated
  heading/pitch/roll math from their example sketch rather than reinventing
  sensor fusion. Publishes to `rvtc/sensors/imu/{heading,pitch,roll,heave,availability}`
  every 250ms, drives the OLED with the same four values, and serves a
  self-contained dark-themed status page at the node's own IP — no external
  CDN references anywhere (`fonts`, JS libraries, etc. all inline), consistent
  with the project's offline-first requirement for `.lan`/local pages.
- **"Heave" is a bounce-intensity proxy, not true integrated displacement.**
  A raw MEMS accelerometer drifts too badly to integrate cleanly into a real
  heave-in-meters figure the way a marine-grade IMU or GPS-aided system
  could. What's actually implemented: rolling peak-to-peak of the
  gravity-compensated vertical (Z) acceleration over a ~2s window, in g's —
  answers "how rough is it right now," not "how many inches did we move."
  Worth remembering if this number is ever compared against a real heave
  sensor's output.
- **Still open:** flash and bench-test the firmware; confirm OLED I2C address
  (assumed `0x3C`, some SH1106 boards use `0x3D`); one-time magnetometer
  hard-iron calibration, which needs to happen with the unit mounted in its
  final trailer location, not on the bench, since mounting position affects
  magnetic interference.

**Correction, same day:** the build above was initially designed WiFi-only,
based on a misreading of "WiFi for convenience" as "WiFi instead of RS-485"
rather than "WiFi in addition to RS-485." `IMU_config.md` surfaced shortly
after — the node's actual, previously-written design doc — making clear
RS-485 Modbus RTU is the primary/authoritative path, with WiFi/MQTT/web as
secondary. Firmware rebuilt accordingly: Modbus RTU slave (holding registers
0-2, heading/pitch/roll ×10 scaled int16) as primary, `heading`/`pitch`/`roll`/
`heave`/`status` over MQTT and a local leveling-themed web page as secondary.
Also corrected: an assumption that the RS-485 bus was full (all 8 ports
"already allocated") turned out wrong — RS-485/4 (`192.168.88.8:4001`) was
already reserved specifically for the IMU, confirmed against a live gateway
addressing screenshot. That same screenshot prompted a full reconciliation of
[5.5](#55-rs-485-bus--gateway-ip-addressing) against the doc's previously
stale/unconfirmed entries — see that section for the corrected table,
including the KWS grid/generator port-bundling decision (finally consolidated
into [1.5C](#15-rs-485--modbus-gateway-topology) after being "buried in the
notes" per the user) and one still-unresolved conflict over SAMLUX's actual
gateway IP that needs checking against `samlux_mqtt.py` directly.

---

## Part 5 — Reference Tables

### 5.1 Device / Gateway Inventory

| Device | Connection | Gateway / IP | Bridge Script | Service | MQTT Topic Base |
|---|---|---|---|---|---|
| SAMLUX EVO-2212 (inverter) | RS-485 bus 8 (`485-8`) | Waveshare @ `192.168.88.12:4001` | `samlux_mqtt.py` | `samlux_mqtt.service` | `rvtc/sensors/inverter/#` |
| EPEVER MPPT60 (solar controller) | RS-485 bus 1 (`485-1`), via RS485-1M2S module (shared with MT50) | `192.168.88.5:4001` — confirmed connected and tested (baud 115200) | `epever_mqtt.py` | `epever_mqtt.service` | `rvtc/sensors/solar/#` |
| KWS-303L (grid) | RS-485 bus 3 (`485-3`) | `192.168.88.7:4001` — confirmed connected and tested | `kws_mqtt.py` | `kws_mqtt.service` | `rvtc/sensors/grid/#` |
| KWS-303L (generator) | RS-485 bus 3 (`485-3`) — **bundled onto the same port as grid KWS**, not a separate bus; both meters live in the same AC breaker box (decided earlier, consolidated into this doc 2026-07-09) | `192.168.88.7:4001` (shared with grid) | `kws_mqtt.py` | `kws_mqtt.service` | `rvtc/sensors/generator/#` |
| GNSS E108-GN03G-485 | RS-485 bus 6 (`485-6`, confirmed via HW-10 cross-reference) | `192.168.88.10:4001` — TCP serial gateway, module replaced 2026-07-06/07 with a working u-blox unit | `gps_mqtt.py` — **not a direct gateway poller**; runs as a client of the host's own `gpsd` (port 2947), which is already gpsd's single TCP client of the gateway. Deliberate departure from the direct-poll pattern used by the other bridges — see script header comment for reasoning. | `gps_mqtt.service` | `rvtc/sensors/gps/#` (`latitude`, `longitude`, `altitude_m`, `speed_kmh`, `track_deg`, `time_utc`, `fix_mode`, `hdop`, `satellites_used`, `satellites_visible`, `availability`) |
| Ecowitt WN90LP weather station | RS-485 bus 7 (`485-7`, confirmed via HW-16 cross-reference) | `192.168.88.11` (reserved; device shipped, not yet installed — HW-16 open) | *(not yet written — HW-16 open)* | — | *(likely `rvtc/sensors/weather/#`, pending `weewx-mqtt`)* |
| MT50 remote | RS485-1M2S slave port, shares EPEVER line | n/a (direct RS-485, not TCP) | n/a | n/a | n/a |
| IMU node — NodeMCU ESP32 + Adafruit 10-DOF + SH1106 OLED | RS-485 bus 4 (`485-4`) — **PRIMARY path**, dedicated gateway port (corrected 2026-07-09; an earlier draft this same day briefly and incorrectly assumed WiFi-only) | `192.168.88.8:4001` | `main.cpp` (PlatformIO, C++, not Python like the other bridges) — repo: `rvtc-imu/`. WiFi + MQTT + local web page are secondary/convenience paths only, matching [1.5](#15-rs-485--modbus-gateway-topology)'s general principle | *(runs as the ESP32's own firmware, no host-side systemd service)* | Modbus holding registers 0-2 (heading/pitch/roll, ×10 scaled int16) via RS-485; `rvtc/sensors/imu/#` (`heading`, `pitch`, `roll`, `heave`, `status`) via MQTT — **not persisted to InfluxDB**, real-time only |

**SNMP-monitored devices (2026-07-07)** — separate mechanism from the
MQTT-bridge devices above. These are polled directly by Telegraf's
`inputs.snmp` plugin (`telegraf_snmp.conf`) rather than via a Python bridge
script, since they're standard SNMP-capable IT hardware rather than
custom serial/Modbus gear needing protocol translation. No MQTT topic —
Telegraf writes straight to InfluxDB (`rvtc` bucket) for these.

| Device | IP | SNMP status | Measurements collected |
|---|---|---|---|
| MikroTik CRS109 router | `192.168.88.1` | Confirmed working | `sysUptime`; per-interface `ifInOctets`/`ifOutOctets`/`ifInErrors`/`ifOutErrors`/`ifOperStatus` for every ether port, `bridge`, `wlan1`, `rogers-wan`, `starlink-wan` |
| Synology DS223 NAS | `192.168.88.4` | Confirmed working | System + per-disk temperature, system status, per-volume status/total/used bytes, full per-disk SMART attribute table (reallocated sectors, power-on hours, spin retry count, etc.) |
| Brother MFC-L2710DW printer | `192.168.88.20` | Confirmed working | Drum level/capacity, lifetime page count |
| Fanvil 4XG phone | `192.168.88.21` | Not yet responding | — likely needs SNMP enabled in its own admin UI |
| Grandstream WP-820 phone | `192.168.88.24` | Not yet responding | — likely needs SNMP enabled in its own admin UI |

*(The TL-108PE switch at `.22` and the Motorola personal cell phone at `.23`
were deliberately excluded — the former is explicitly unmanaged with no SNMP
agent, the latter is a personal device, not fixed network infrastructure.)*

A discovery/reachability test script (`snmp_discovery.sh`) exists for testing
new SNMP targets with `snmpget`/`snmpwalk` before wiring them into
`telegraf_snmp.conf` — useful since printers and phones commonly ship with
SNMP disabled by default, and guessing at community strings blind wastes time.

**Confirmed 2026-07-06** via a `config/` directory listing — filenames above for
the EPEVER and KWS bridges are now exact rather than inferred.

**Confirmed 2026-07-06** via a DHCP leases screenshot — the router reserves a
static IP block (`192.168.88.5`–`.12`) labeled `485-1` through `485-8`, one per
physical RS-485 bus. This confirms the numbering scheme referenced elsewhere in
the backlog (HW-09 "RS-485/3", HW-10 "RS-485/6", HW-16 "RS-485/7") maps directly
to these reserved IPs. Full breakdown, including which buses are still
unidentified, at [5.5](#55-rs-485-bus--gateway-ip-addressing).

**Config files confirmed to exist in the directory listing but not yet described
anywhere in the session notes consolidated into this document** — worth a short
write-up next session so they don't stay undocumented. (`rv-mikrotik-config.rsc`
/ `rv-mikrotik-config_ether8_fix.rsc`, previously listed here, are now documented
in full at [1.7](#17-network--router-topology-mikrotik) and removed from this
gap list.)

| File | Likely purpose (unconfirmed — inferred from name only) |
|---|---|
| `kws_mqtt_patch_instructions.txt` | Some patch/fix applied to the KWS bridge — worth capturing *why* it was needed |
| `kws_relay.py` / `kws_relay_config.yaml` | Relay control for KWS-303L disconnect switches — likely the mechanism behind the still-open "KWS grid/generator disconnect switches → Load Control dashboard" backlog item |
| `modbus_samlux_clean.yaml`, `modbus-relay.yaml` (hyphenated, distinct from `modbus_relay.yaml`) | Naming similarity to already-tracked files — worth confirming these aren't stale/duplicate artifacts from the 2026-06-26 HA-Modbus-integration removal rather than active config |
| `grid_disconnect_dashboard_card.yaml` | HA dashboard card, presumably tied to the KWS disconnect switch backlog item |
| `IMU_config.md` | **Resolved 2026-07-09** — the IMU node's original design doc (RS-485-primary architecture, register map, hard-iron calibration procedure). Superseded a same-day misunderstanding where the node was briefly, incorrectly built as WiFi-only; corrected once this file surfaced. See [5.1](#51-device--gateway-inventory) and [2026-07-09 log](#2026-07-09--imu-node-build-hw-25). |
| `nginx.conf` | Reverse proxy config — likely fronting `rvtc_index.html`/`index.html`, not documented elsewhere |
| `rvtc_solar_dashboard.json`, `rvtc_ambient.yaml` | Additional dashboards beyond the ones named in session notes (Grafana weather dashboard, Load Control dashboard) |
| `telegraf_grid.conf` (separate from `telegraf_solar.conf`) | Suggests a per-source Telegraf config pattern — worth confirming whether this predates or coexists with the unified Telegraf/`rvtc_unified` plan from 2026-07-02 |
| `temp_press_flash.yml` | Unclear purpose from name alone |

*If any of these ring a bell, worth a quick note next session — future-you (or
this doc) has no record of what they do otherwise.*

### 5.2 SAMLUX EVO-2212 Key Registers

| Field | Topic | Sample Value |
|---|---|---|
| Grid Input Voltage | voltage_grid_input | 120.1 V |
| Grid Input Frequency | freq_grid_input | 59.94 Hz |
| Input Current | input_current | 2.16 A |
| Input Power | input_watt | 164 W |
| Output Voltage | output_voltage | 120.04 V |
| Output Frequency | output_frequency | 60.06 Hz |
| Battery Voltage | battery_voltage | 13.578 V |
| Battery Current | battery_current | 0.2 A |
| Transformer Temp | transformer_temperature | 25.0°C |
| Operating Mode (reg 284) | operating_mode | 1 (line/passthrough) |
| Operating Mode Text | operating_mode_text | "line" |

**Operating mode decode (register 284)** — critical for Tier 1 load management:
0 = standby, 1 = line (normal), **2 = inverter (on battery) — Tier 1 trigger**,
3 = bypass, 4 = battery_test, 5 = fault.

Signed register handling: int16 conversion applied for battery current, invert/
charge current/watt, and all temperature registers.

### 5.3 EPEVER Key Registers

```python
SINGLE_REGISTERS = [
    # address  scale    field                          unit
    (12544,    0.01,   "pv_voltage",                  "V"),
    (12545,    0.01,   "pv_current",                  "A"),
    (12548,    0.01,   "battery_voltage",              "V"),
    (12549,    0.01,   "charging_current",             "A"),
    (12556,    0.01,   "load_voltage",                 "V"),
    (12557,    0.01,   "load_current",                 "A"),
    (12560,    0.01,   "battery_temperature",          "C"),
    (12561,    0.01,   "controller_temperature",       "C"),
    (12570,    1.0,    "battery_soc",                  "%"),
    (12800,    1.0,    "charging_status_raw",          ""),
    (12801,    1.0,    "battery_status_raw",           ""),
]
```

⚠️ `battery_soc` (12570) is voltage-curve-derived, not coulomb-counted — see
[2.1](#21-epever-battery-soc-swings--resolved). Accuracy depends entirely on the
configured battery-type profile matching actual chemistry (must be **LiFePO4**,
not the default flooded profile).

### 5.4 Relay / Coil Mapping

| Relay entity | Coil (0-based) | Load | Notes |
|---|---|---|---|
| `relay_1_on` / `relay_1_off` | Coil 0 | Water heater | Naming is 1-indexed-sounding but maps to 0-based coil — misleading but internally consistent |
| `relay_2_on` / `relay_2_off` | Coil 1 | Microwave | Same pattern as above |

Both relays are **inverted** (Waveshare NC-wiring quirk, documented 2026-06-30):
value 1 = shed/off, value 0 = restore/on.

Manual shed automations (`Manual Shed - Water Heater`, `Manual Shed - Microwave`)
set `input_boolean.coil1_energised` / `coil2_energised` respectively as part of
shedding a load — this is the input the Tier 3 restore-check automations key off
of, and the suspected source of the race condition in
[2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed).

### 5.5 RS-485 Bus / Gateway IP Addressing

**Confirmed 2026-07-06** via a DHCP leases screenshot. The MikroTik reserves a
static IP block for RS-485 gateway hardware, labeled `485-1` through `485-8` —
one reservation per physical RS-485 bus, each presumably a Waveshare RS485-to-
Ethernet gateway (matching MAC OUI `04:EE:E8:xx:xx:xx` across all eight). This
scheme is also why the DHCP dynamic pool starts at `.100` rather than lower —
see [1.7](#17-network--router-topology-mikrotik).

| Bus label | Reserved IP | Device on this bus | Status |
|---|---|---|---|
| `485-1` | `192.168.88.5` | **Confirmed: EPEVER MPPT60** (Power — Solar) | ✅ Connected, tested (baud 115200) |
| `485-2` | `192.168.88.6` | **Confirmed: SAMLUX EVO-2212** (Power — Inverter) | ✅ Connected, tested |
| `485-3` | `192.168.88.7` | **Confirmed: KWS-303L, grid.** Generator KWS-303L will be bundled onto this same port once installed — see [1.5C](#15-rs-485--modbus-gateway-topology) | ✅ Connected, tested (grid); generator pending physical install |
| `485-4` | `192.168.88.8` | **Confirmed: IMU node** (HW-25) — Custom protocol (not standard Modbus register map of the other devices, own Phase 3 firmware) | 🟡 In progress — firmware written, not yet flashed |
| `485-5` | `192.168.88.9` | **Confirmed: Water sensors** — pressure + filter ΔP + turbidity | Pending Phase 5 |
| `485-6` | `192.168.88.10` | **Confirmed: GNSS E108-GN03G-485** | ✅ Installed and confirmed working (see [2026-07-07 log](#2026-07-07--grafana-socpower-smoothing-gps-bridge-routeros-v7-upgrade-telegrafsnmp-deployment)) — this table wasn't updated at the time; corrected now |
| `485-7` | `192.168.88.11` | **Confirmed: Ecowitt WN90LP weather station** | Shipped, not yet installed |
| `485-8` | `192.168.88.12` | **Confirmed: Waveshare 8-ch relay board** (HW-13, load shed) | ✅ Connected, tested |

**Resolved 2026-07-09 (re-confirmed via a second, matching gateway addressing
screenshot):** SAMLUX is genuinely on `485-2` (`.6:4001`); `.12` genuinely
belongs to the load-shed relay board (HW-13). This doc's earlier claim that
SAMLUX's gateway was `.12` was simply wrong.

**Action item, not yet confirmed:** if `samlux_mqtt.py` is actually configured
to point at `192.168.88.12:4001` (matching this doc's old, incorrect
assumption), it would currently be talking to the **relay board, not
SAMLUX** — a real functional problem, not just a documentation error. Check
the script's actual configured target IP directly and correct it to `.6` if
needed, rather than assuming this was purely a paperwork mistake.

**Other reservations visible in the same lease table, for completeness:**

| IP | Device | Notes |
|---|---|---|
| `192.168.88.2` | Router itself | Hostname `VE7CBH-...`, bound |
| `192.168.88.3` | `ve7cbh-c...` host | Bound — matches the already-documented MQTT broker / Pi-hole DNS / HA host address |
| `192.168.88.4` | `ve7cbh-c...` host | Reserved, waiting — second host on this naming pattern, purpose not yet confirmed |
| `192.168.88.18` / `.19` | Unlabeled dynamic devices | Bound (marked "D" for dynamic in the lease table, not static reservations) |
| `192.168.88.20` | Printer | Bound |
| `192.168.88.22` | WP820 IP Phone | Bound |
| `192.168.88.224` | Fanvil 4XG phone | Bound (dynamic pool range) |

**Open items:**
- Which of `485-1/2/4/5` corresponds to EPEVER's gateway and which (if any) is
  the grid KWS-303L meter is not yet confirmed — check `modbus_epever.yaml` /
  `modbus_relay.yaml` next time either is open, or power up each bus in turn and
  watch which reservation goes from "waiting" to "bound."
- Purpose of the second `ve7cbh-c...` host reservation at `.4` not yet confirmed.

---

## Index

**Actuation, HA's role in** → [1.6](#16-open-question--has-role-in-actuation-phase-7)

**Baud rate (RS485-1M2S)** → [1.5](#15-rs-485--modbus-gateway-topology)

**Battery profile / battery type (EPEVER)** → [2.1](#21-epever-battery-soc-swings--resolved), [5.3](#53-epever-key-registers)

**Coil mapping** → [5.4](#54-relay--coil-mapping)

**Coulomb counting / DC shunt (HW-24)** → [2.1](#21-epever-battery-soc-swings--resolved), [3.1](#31-hardware)

**Dev Tools staleness theory** → [2.3](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed)

**Deployment status (config vs. live) — MikroTik** → [1.7](#17-network--router-topology-mikrotik), [2026-06-09 log](#2026-06-09--mikrotik-router-configuration-ether8-fix-prepared--not-yet-deployed)

**DNS (Pi-hole)** → [1.7](#17-network--router-topology-mikrotik)

**DHCP pool range change (reserved-list growth)** → [1.7](#17-network--router-topology-mikrotik), [2026-06-09 log](#2026-06-09--mikrotik-router-configuration-ether8-fix-prepared--not-yet-deployed)

**Entity registry duplicates** → [2026-06-26 log](#2026-06-26--ha-onboarding-samlux-bridge-telegraf)

**ether8 / passthrough bridge** → [1.7](#17-network--router-topology-mikrotik)

**EPEVER register map** → [5.3](#53-epever-key-registers)

**Flooded profile (wrong battery-type setting)** → [2.1](#21-epever-battery-soc-swings--resolved)

**Gateway IPs / device inventory** → [5.1](#51-device--gateway-inventory), [5.5](#55-rs-485-bus--gateway-ip-addressing)

**Generator meter (HW-09)** → [3.1](#31-hardware)

**HA Modbus integration conflict (removed)** → [1.4](#14-home-assistants-role--data-consumer-only), [2026-06-26 log](#2026-06-26--ha-onboarding-samlux-bridge-telegraf)

**HOME mode / OFF-GRID mode (router)** → [1.7](#17-network--router-topology-mikrotik)

**Inverter mode decode** → [5.2](#52-samlux-evo-2212-key-registers)

**KWS-303L meters** → [1.5](#15-rs-485--modbus-gateway-topology), [5.1](#51-device--gateway-inventory)

**LiFePO4** → [2.1](#21-epever-battery-soc-swings--resolved)

**Load shed race condition** → [2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed)

**Master/slave naming trap (RS485-1M2S)** → [1.5](#15-rs-485--modbus-gateway-topology)

**Microwave relay incident** → [2.3](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed)

**MikroTik router / CRS109** → [1.7](#17-network--router-topology-mikrotik)

**MikroTik improper reboot (2026-06-27)** → [2.5](#25-mikrotik-improper-reboot-jun27-2026--unconfirmed-cause-not-yet-investigated)

**Duplicate firewall/NAT rules** → [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06)

**Modbus TCP gateway conflict** → [1.4](#14-home-assistants-role--data-consumer-only)

**MT50** → [1.5](#15-rs-485--modbus-gateway-topology), [2.1](#21-epever-battery-soc-swings--resolved)

**MQTT topic schema** → [1.2](#12-unified-namespace-mqtt)

**NAT / dst-nat / masquerade (router)** → [1.7](#17-network--router-topology-mikrotik)

**Pinhole (firewall)** → [1.7](#17-network--router-topology-mikrotik), [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06)

**Restore-check race hypothesis** → [2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed)

**RMS vs. moving average (SOC smoothing)** → [2026-07-06 log](#2026-07-06--epever-soc--mt50--rs485-1m2s-investigation)

**Rogers / Starlink WAN (actual usage vs. naming)** → [1.7](#17-network--router-topology-mikrotik)

**Double NAT / Rogers NAT fix (2026-07-06)** → [1.7](#17-network--router-topology-mikrotik), [2.6](#26-duplicate-firewallnat-rule-sets--partially-resolved-2026-07-06)

**Docker service-name DNS gotcha (Telegraf)** → [1.3](#13-influxdb--telegraf-persistence-layer)

**GPS / gpsd / gps_mqtt.py** → [5.1](#51-device--gateway-inventory), [2026-07-07 log](#2026-07-07--grafana-socpower-smoothing-gps-bridge-routeros-v7-upgrade-telegrafsnmp-deployment)

**IMU node (HW-25)** → [5.1](#51-device--gateway-inventory), [1.5](#15-rs-485--modbus-gateway-topology), [2026-07-09 log](#2026-07-09--imu-node-build-hw-25)

**KWS-303L grid/generator port bundling** → [1.5](#15-rs-485--modbus-gateway-topology)

**HF5142 serial gateway (spare capacity)** → [1.5](#15-rs-485--modbus-gateway-topology)

**RS-485 addressing table / SAMLUX IP conflict** → [5.5](#55-rs-485-bus--gateway-ip-addressing)

**RouterOS v6→v7 upgrade** → [1.7](#17-network--router-topology-mikrotik)

**SNMP monitoring (MikroTik/NAS/printer)** → [5.1](#51-device--gateway-inventory)

**SOC/power smoothing (web panel)** → [2026-07-07 log](#2026-07-07--grafana-socpower-smoothing-gps-bridge-routeros-v7-upgrade-telegrafsnmp-deployment)

**RS-485 bus numbering (485-1 through 485-8)** → [5.5](#55-rs-485-bus--gateway-ip-addressing)

**RS485-1M2S module** → [1.5](#15-rs-485--modbus-gateway-topology)

**rtl_433 unidentified devices** → [2.4](#24-unidentified-rtl_433-devices--unresolved-not-yet-investigated)

**SAMLUX register map** → [5.2](#52-samlux-evo-2212-key-registers)

**shell_command registration** → [2.3](#23-microwave-relay-missing-from-dev-tools--leading-theory-unconfirmed)

**SOC (State of Charge) swings** → [2.1](#21-epever-battery-soc-swings--resolved)

**Telegraf / InfluxDB pipeline** → [1.3](#13-influxdb--telegraf-persistence-layer)

**Tier 1 trigger (operating mode 2)** → [5.2](#52-samlux-evo-2212-key-registers)

**Tier 3 restore scripts** → [2.2](#22-manual-load-shed-intermittent-failures--suspected-cause-unconfirmed), [3.2](#32-software)

**Unified namespace architecture** → [1.2](#12-unified-namespace-mqtt)

**Voltage-derived SOC** → [2.1](#21-epever-battery-soc-swings--resolved), [5.3](#53-epever-key-registers)

**Waveshare gateway (SAMLUX)** → [1.5](#15-rs-485--modbus-gateway-topology), [5.1](#51-device--gateway-inventory)

**weewx-mqtt extension** → [1.2](#12-unified-namespace-mqtt)
