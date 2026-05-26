# RV Total Control (RVTC)

**Author:** Steve Bradshaw (ve7cbh)  
**Status:** Phase 0 — Architecture & Design  
**Last Updated:** May 26, 2026

---

## Overview

RV Total Control is an integrated monitoring, control, and data-collection platform for a recreational vehicle. The system runs on a Beelink J45 mini-PC under Linux Mint LMDE and is fully deployed via Ansible automation with all services containerised under Docker Compose.

The project provides:

- **Solar power monitoring and control** — EPEVER MPPT60 charge controller via Modbus RS-485
- **Inverter-charger monitoring** — SAMLUX 2212
- **RV tank level monitoring** — Fresh, Grey 1, Grey 2, Black water tanks
- **Propane level monitoring** — 2 × 30 lb tanks
- **Fresh water inlet monitoring** — pressure, filter condition, flow rate, turbidity (subset of Solsante Water Monitoring V1.5 — used as club demonstration)
- **Weather and environment** — 433 MHz sensor network via WeeWX
- **DNS and ad blocking** — Pi-hole
- **Dashboards and trending** — Grafana + InfluxDB/TimescaleDB
- **Home automation and alerting** — Home Assistant

---

## Hardware

| Item | Specification |
|---|---|
| Host computer | Beelink J45 |
| CPU | Intel Pentium J4205 (4-core) |
| RAM | 8 GB |
| Root drive | 256 GB SSD |
| Data drive | 640 GB SSD |
| OS | Linux Mint LMDE (Debian-based) |
| Edge nodes | ESP32-S3 (ESPHome firmware) — water node, tank node |

---

## Repository Structure

```
RV-total-control/
├── config/               # Device configuration files (MikroTik, etc.)
├── docs/                 # Project documentation
├── group_vars/           # Ansible group variables
├── host_vars/            # Ansible host-specific variables
├── inventories/          # Ansible inventory files
├── roles/                # Ansible roles (one subfolder per role)
└── README.md             # This file
```

---

## Documentation

| Document | Location |
|---|---|
| System Architecture Document (V0.1) | `docs/RVTC_System_Architecture_V0.1.docx` |
| MikroTik RV Failover Configuration | `config/README.md` |

---

## Ansible Stack

All services are deployed via Ansible playbooks. Anticipated roles:

| Role | Purpose |
|---|---|
| `common` | OS baseline, Docker engine, firewall |
| `pihole` | DNS and ad blocking |
| `weewx` | 433 MHz weather sensor ingest |
| `homeassistant` | Automation, HMI, alerting |
| `influxdb` / `timescaledb` | Time-series data store (TBD) |
| `grafana` | Dashboards and trending |
| `mqtt` | Mosquitto broker (TBD) |
| `epever` | EPEVER MPPT60 Modbus RS-485 integration |
| `samlux` | SAMLUX 2212 inverter-charger integration |
| `esphome-water` | Water inlet sensor node firmware and config |
| `esphome-tanks` | Tank level sensor node firmware and config |

Full role structure will be documented in Phase 0 before any playbook development begins.

---

## Reference

- **geerlingguy/internet-pi** — retained as a clean upstream reference for Ansible + Docker Compose patterns. Not a dependency; RVTC is an independent project.

---

## Project Phases

| Phase | Title | Status |
|---|---|---|
| 0 | Architecture & Design | 🔄 In progress |
| 1 | Beelink J45 Build | ⏳ Pending |
| 2 | Core Stack Deployment | ⏳ Pending |
| 3 | Power Integration | ⏳ Pending |
| 4 | Tank & Propane Sensing | ⏳ Pending |
| 5 | Water Monitoring | ⏳ Pending |
| 6 | Baseline & Handover | ⏳ Pending |
