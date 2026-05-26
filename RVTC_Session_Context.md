# RVTC Session Context Document
**Last Updated:** May 26, 2026  
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
├── ansible.cfg                          # interpreter_python = /usr/bin/python3.13
├── config/
│   ├── Mikrotik Failover.md
│   └── rv-mikrotik-config.rsc
├── docs/
│   ├── RVTC_System_Architecture_V0.1.docx
│   ├── RVTC_Ansible_Role_Structure_V0.1.docx
│   └── RVTC_Phase1_Build_Log.docx
├── group_vars/                          # Empty — Phase 2
├── host_vars/                           # Empty — Phase 2
├── inventories/
│   └── production/
│       └── hosts.ini                    # localhost ansible_connection=local
├── roles/                               # Empty — Phase 2
├── .gitattributes
└── README.md
```

---

## Ansible Configuration

**ansible.cfg** (repo root):
```ini
[defaults]
interpreter_python = /usr/bin/python3.13
```

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

## Planned Docker Stack

| Container | Purpose | Phase |
|---|---|---|
| Pi-hole | DNS / ad blocking | 2 |
| WeeWX | 433 MHz weather sensors | 2 |
| Home Assistant | Automation, HMI, alerting | 2 |
| InfluxDB OR TimescaleDB | Time-series database (TBD — OI-01) | 2 |
| Grafana | Dashboards and trending | 2 |
| Mosquitto MQTT | Message broker (TBD — OI-02) | 2 |
| EPEVER integration | Solar MPPT60 Modbus RS-485 | 3 |
| SAMLUX integration | Inverter-charger (protocol TBD — OI-03) | 3 |
| ESPHome tanks node | Tank level sensing ESP32-S3 | 4 |
| ESPHome water node | Water inlet monitoring ESP32-S3 | 5 |

---

## Monitored & Controlled Systems

**Power:**
- EPEVER MPPT60 solar charge controller — Modbus RS-485
- SAMLUX 2212 inverter-charger — protocol TBD

**Tanks:**
- Fresh, Grey1, Grey2, Black — exterior sensors on plastic tanks
- Propane — 2 × 30 lb tanks — load cell method

**Water Inlet (Solsante V1.5 subset — club demo):**
- Supply pressure (0–0.6 MPa RS-485 transducer)
- Filter ΔP (0–0.1 MPa pair)
- Flow rate (pulse-output meter)
- Turbidity (Seeed S-DTS210-01 RS-485 Modbus)
- Enclosure temperature (DS18B20)

**Weather:**
- 433 MHz sensor network via WeeWX + RTL-SDR

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

## Open Items — Must Resolve Before Phase 2

| ID | Item | Decision needed |
|---|---|---|
| OI-01 | InfluxDB vs TimescaleDB | InfluxDB: lighter, native WeeWX. TimescaleDB: SQL joins. Pick one — only one role will be built. |
| OI-02 | MQTT broker | Standalone Mosquitto container vs Home Assistant built-in broker. |
| OI-03 | SAMLUX 2212 protocol | Physically inspect unit for RS-232 / Modbus / proprietary port. |
| OI-04 | EPEVER USB adapter | Confirm Linux driver on LMDE. May need udev rule for stable /dev path. |
| OI-05 | Ansible Vault key | Define where vault password is stored before any secrets committed. |
| OI-06 | Docker network name | Define single bridge network name for inter-container communication. |
| OI-07 | site.yml structure | Single playbook vs separate playbooks per phase/subsystem. |

---

## Phase 2 — First Tasks

1. Resolve OI-01 and OI-02
2. Create `group_vars/all.yml` — global variables (rvtc_data_path, rvtc_timezone, etc.)
3. Create `host_vars/rvtc.yml` — J45-specific overrides
4. Create `site.yml` — master playbook stub
5. Write and test `common` role — OS baseline, Docker idempotency, UFW firewall
6. Deploy core stack roles one at a time, testing after each

---

## Key Paths on J45

| Path | Purpose |
|---|---|
| `~/RV-total-control` | Ansible project root — all commands run from here |
| `/data` | 640 GB data drive — Docker volumes go here |
| `/home/ve7cbh` | User home on root drive |
| `/etc/apt/sources.list.d/docker.list` | Docker repo — hardcoded trixie (not gigi) |

---

## Known Issues / Notes

- **LMDE Docker repo fix:** Docker repo must use `trixie` codename hardcoded — `$VERSION_CODENAME` returns `gigi` on LMDE and causes a 404. See Phase 1 Build Log.
- **GitHub auth:** PAT stored in `~/.git-credentials` via credential.helper store. No sudo needed for docker commands (ve7cbh in docker group).
- **Reference repo:** geerlingguy/internet-pi kept as clean upstream reference only — not a dependency.
- **Solsante V1.5 PDD:** Water monitoring subset used for club demo. Full PDD covers 6 hilltop water systems at Solsante Club.
