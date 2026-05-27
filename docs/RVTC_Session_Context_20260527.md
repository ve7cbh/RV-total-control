# RVTC Session Context Document
**Last Updated:** May 27, 2026  
**Purpose:** Feed this to Claude at the start of each session to restore project context instantly.

---

## Project Identity

| Item | Value |
|---|---|
| Project | RV Total Control (RVTC) |
| Owner | Steve Bradshaw (ve7cbh) |
| GitHub | https://github.com/ve7cbh/RV-total-control |
| Status | Phase 1 Complete — Phase 2 Ready to start |

---

## Hardware

| Item | Specification |
|---|---|
| Host | Beelink J45 |
| CPU | Intel Pentium J4205 (4-core) |
| RAM | 8 GB |
| Root drive | /dev/sda — 256 GB — mounted / |
| Data drive | /dev/sdb — 640 GB — mounted /data |
| OS | Linux Mint LMDE (Debian trixie base) |
| Hostname | ve7cbh-control |
| Primary user | ve7cbh |
| Access | SSH from Windows workstation |
| Modbus Gateway | Hi-Flying HF5142B — 4-port RS-485 to Ethernet, Modbus RTU/TCP |

---

## Software Installed on J45

| Package | Version |
|---|---|
| Docker CE | Latest (Compose v5.1.4) |
| Ansible | core 2.19.4 |
| Python | 3.13.5 |
| Git | 2.47.3 |

---

## Repository Structure (current state)

```
RV-total-control/
├── ansible.cfg                          # interpreter_python + vault_password_file
├── config/
│   ├── Mikrotik Failover.md
│   └── rv-mikrotik-config.rsc
├── docs/
│   ├── RVTC_System_Architecture_V0.1.docx
│   ├── RVTC_Ansible_Role_Structure_V0.1.docx
│   └── RVTC_Phase1_Build_Log.docx
├── group_vars/                          # Phase 2 — create all.yml
├── host_vars/                           # Phase 2 — create rvtc.yml
├── inventories/
│   └── production/
│       └── hosts.ini                    # localhost ansible_connection=local
├── roles/                               # Phase 2 — build common role first
├── site.yml                             # Phase 2 — master playbook stub
├── phase2.yml                           # Phase 2 — core stack playbook
├── .gitattributes
└── README.md
```

---

## Ansible Configuration

**ansible.cfg** (repo root):
```ini
[defaults]
interpreter_python = /usr/bin/python3.13
vault_password_file = ~/.vault_pass
```

**~/.vault_pass:**
- Plain text file on J45
- chmod 600
- Never committed to Git
- Contains Ansible Vault password

**inventories/production/hosts.ini:**
```ini
[rvtc]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3.13
```

**Verify with:**
```bash
cd ~/RV-total-control
ansible rvtc -i inventories/production/hosts.ini -m ping
```

---

## Engineering Standards

- Single-point grounding at all instrument enclosures
- Twisted-pair / shielded cable for all analog runs
- 4–20 mA current loop for analog runs exceeding 10 m
- RS-485 Modbus RTU for all digital sensor buses
- TBx-n terminal block wiring convention
- Navy-standard protocols throughout
- All documentation version-controlled in GitHub

---

## HF5142B Modbus Gateway — Port Allocation

Single IP address. Each RS-485 port maps to a separate TCP port number (default 4001–4004). Configured via web interface. Each port independently configurable for baud rate and framing.

| Port | TCP Port | Bus | Device(s) | Phase |
|---|---|---|---|---|
| RS-485/1 | 4001 | Power — Solar | EPEVER MPPT60 | 3 |
| RS-485/2 | 4002 | Power — Inverter | SAMLUX EVO-2212 | 3 |
| RS-485/3 | 4003 | Water sensors | Pressure + Filter ΔP + Turbidity | 5 |
| RS-485/4 | 4004 | Spare | Propane load cells TBD or future | 4/— |

Supports native Modbus RTU→TCP and MQTT publish. MQTT publish capability used for water/ESPHome integration in Phase 5.

---

## Planned Docker Stack

| Container | Purpose | Phase |
|---|---|---|
| Mosquitto | MQTT broker — standalone container | 2 |
| InfluxDB | Time-series database | 2 |
| Grafana | Dashboards and trending | 2 |
| WeeWX | 433 MHz weather sensors | 2 |
| Home Assistant | Automation, HMI, alerting | 2 |
| Pi-hole | DNS / ad blocking | 2 |
| EPEVER integration | Solar MPPT60 Modbus RS-485 via HF5142B | 3 |
| SAMLUX integration | Inverter-charger Modbus RS-485 via HF5142B | 3 |
| ESPHome tanks node | Tank level + battery temp DS18B20 sensing ESP32-S3 | 4 |
| ESPHome water node | Water inlet monitoring ESP32-S3 | 5 |

**Docker network name:** `rvtc_net`  
**Deploy order within Phase 2:** Mosquitto → InfluxDB → Grafana → WeeWX → Home Assistant → Pi-hole

---

## Monitored & Controlled Systems

**Power:**
- EPEVER MPPT60 solar charge controller — Modbus RS-485 — read only
- SAMLUX EVO-2212 inverter-charger — Modbus RS-485 — read only — charge control via hardware BMS input circuit

**Battery Charge Protection — Hardware Circuit:**

Fail-safe design: charging is INHIBITED by default. Circuit must be actively energised to permit charging.

| Item | Detail |
|---|---|
| Sensors | 3× NTC thermistor on battery bank — 2-of-3 voting comparator circuit (LM393) |
| Logic | Comparator output energises relay coil. NC contacts feed EVO-2212 BMS input. |
| Fail-safe | Power loss / sensor fault / cold = relay de-energised = NC closed = charge stopped |
| Charge permit threshold | ~5°C battery temp (TBD — comparator reference voltage) |
| EVO-2212 BMS input | RJ-45 jack "Battery Temp Sensor" (connector 6). Pins 1–4 = SSR+, Pins 5–8 = SSR− |
| EVO programming required | BATTERY TYPE must be set to 1=Lithium to activate BMS input function |
| EVO display when active | CHR STOP BY BMS |
| RVTC software role | Monitor + log only. Alert when charge inhibited. No Modbus writes for charge control. |
| Monitoring sensors | 3× DS18B20 co-located with NTC thermistors — on Phase 4 ESPHome node |
| Sensor placement | Negative end / centre / positive end of battery bank |

**Battery Heaters:**

| Item | Detail |
|---|---|
| Control | Standalone analogue thermostatic outlet — no RVTC involvement |
| Enable setpoint | ~10°C ambient |
| Target battery temp | ~20°C |
| RVTC role | None — monitoring only via DS18B20 sensors |

**Tanks:**
- Fresh, Grey1, Grey2, Black — exterior sensors on plastic tanks — ESPHome node Phase 4
- Propane — 2 × 30 lb tanks — load cell method — HF5142B RS-485 port 4

**Water Inlet (Solsante V1.5 subset — club demo):**
- Supply pressure (0–0.6 MPa) — RS-485 Modbus — HF5142B port 3
- Filter ΔP (0–0.1 MPa pair) — RS-485 Modbus — HF5142B port 3
- Flow rate (pulse-output meter) — ESPHome node Phase 5
- Turbidity (Seeed S-DTS210-01 RS-485 Modbus) — HF5142B port 3
- Enclosure temperature (DS18B20) — ESPHome node Phase 5

**Weather:**
- 433 MHz sensor network via WeeWX + RTL-SDR — native InfluxDB driver

---

## SAMLUX Data Sharing — Future Consideration

| Item | Detail |
|---|---|
| Requestor | Samlex America Inc. |
| Request | Operational field data from EVO-2212 in real-world RV deployment |
| Format wanted | SQL |
| Age of request | ~5 years (informal) |
| Export path | InfluxDB → SQL confirmed viable via Telegraf or CSV pipeline |
| Action | Re-contact Samlex when EVO-2212 integration is live. Confirm interest, schema, agreement. |
| NDA note | EVO-2212 Modbus register map held locally under NDA. Never paste into chat. |

---

## Project Phases

| Phase | Title | Status |
|---|---|---|
| 0 | Architecture & Design | ✅ Complete |
| 1 | Beelink J45 Build | ✅ Complete |
| 2 | Core Stack Deployment | 🔄 Next |
| 3 | Power Integration | ⏳ Pending |
| 4 | Tank & Propane Sensing | ⏳ Pending |
| 5 | Water Monitoring | ⏳ Pending |
| 6 | Baseline & Handover | ⏳ Pending |

---

## Open Items

**All pre-Phase 2 blocking items resolved. No open items.**

| ID | Item | Decision |
|---|---|---|
| OI-01 | Database | ✅ InfluxDB |
| OI-02 | MQTT broker | ✅ Mosquitto standalone container |
| OI-03 | SAMLUX protocol | ✅ RS-485 Modbus RTU — read only + hardware BMS charge interlock |
| OI-04 | EPEVER USB adapter | ✅ Eliminated — HF5142B handles it |
| OI-05 | Ansible Vault key | ✅ ~/.vault_pass chmod 600 referenced in ansible.cfg |
| OI-06 | Docker network name | ✅ rvtc_net |
| OI-07 | site.yml structure | ✅ Per-phase playbooks imported by master site.yml |
| OI-08 | Battery temp sensor | ✅ 3× NTC voting circuit + 3× DS18B20 monitoring |
| OI-09 to OI-13 | Interlock service items | ✅ Eliminated — replaced by hardware BMS circuit |

---

## Phase 2 — First Tasks

1. Create `~/.vault_pass` on J45 — chmod 600
2. Update `ansible.cfg` — add `vault_password_file = ~/.vault_pass`
3. Create `group_vars/all.yml` — global variables (rvtc_data_path, rvtc_timezone, docker network: rvtc_net, etc.)
4. Create `host_vars/rvtc.yml` — J45-specific overrides
5. Create `site.yml` — master playbook importing phase playbooks
6. Create `phase2.yml` — Phase 2 playbook stub
7. Write and test `common` role — OS baseline, Docker idempotency, UFW firewall
8. Deploy stack roles one at a time — Mosquitto → InfluxDB → Grafana → WeeWX → HA → Pi-hole

---

## Key Paths on J45

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root — all commands run from here |
| `~/.vault_pass` | Ansible Vault password — chmod 600, never committed |
| `/data` | 640 GB data drive — Docker volumes go here |
| `/home/ve7cbh` | User home on root drive |
| `/etc/apt/sources.list.d/docker.list` | Docker repo — hardcoded trixie (not gigi) |

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo must use `trixie` codename hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE and causes a 404. See Phase 1 Build Log.
- **GitHub auth:** PAT stored in `~/.git-credentials` via credential.helper store. No sudo needed for docker commands (ve7cbh in docker group).
- **Reference repo:** geerlingguy/internet-pi kept as clean upstream reference only — not a dependency.
- **Solsante V1.5 PDD:** Water monitoring subset used for club demo. Full PDD covers 6 hilltop water systems at Solsante Club.
- **SAMLUX register map:** Full Modbus register map held locally under NDA. Never paste into chat. Physical interface and framing details confirmed from non-confidential pages. Integration role will be written with register address placeholders — Steve inserts actual addresses locally before deployment.
- **XRDP / D-Bus fix:** `export $(dbus-launch)` added as first line of `/etc/xrdp/startwm.sh`. Isolates D-Bus between local (:0) and remote (:10+) X11 sessions so they don't conflict.
- **J45 power management:** Modified to never sleep.
- **X11 background:** Suitable background image created for X11 session.

## Network Allocation

| IP | Device |
|---|---|
| 192.168.88.1 | MikroTik gateway |
| 192.168.88.2 | Windows workstation |
| 192.168.88.3 | Beelink J45 — eth0 (primary) |
| 192.168.88.4 | Open — candidate: J45 WiFi interface (wlan0) |
| 192.168.88.5 | HF5142B Modbus gateway |