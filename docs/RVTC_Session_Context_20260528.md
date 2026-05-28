# RVTC Session Summary — 2026-05-28

## Tasks Completed

Phase 2 Tasks 8–13 — full core stack deployed and live.

---

## Containers Running

| Container | Purpose | Port |
|---|---|---|
| Mosquitto | MQTT broker | 1883 |
| InfluxDB | Time-series database | 8086 |
| Grafana | Dashboards | 3000 |
| rtl_433 | Acurite 5n1 weather station receiver | — |
| WeeWX | Weather data processing | — |
| nginx | Serves WeeWX public_html | 80 |
| Home Assistant | Automation / HMI | 8123 |
| Pi-hole | DNS / ad blocking | 8880 (web), 53 (DNS) |

---

## Issues Resolved

- **group_vars/vault.yml not loading** — fixed by converting `group_vars/` to a directory (`group_vars/all/`) so both `all.yml` and `vault.yml` are loaded automatically
- **WeeWX permissions** — container runs as uid 1000; volume directory must be owned by 1000:1000 before first run
- **WeeWX MQTTSubscribe driver** — `time` field from rtl_433 JSON requires `ignore = true` per-field entry, not `filter_out`
- **rtl_433 JSON output** — `-F mqtt://` without `devices=` flag publishes full JSON to `rtl_433/<id>/events` topic
- **Pi-hole DNS not responding to external queries** — `dns.listeningMode` must be set to `all`; set via `FTLCONF_dns_listeningMode: "all"` env var in the Ansible role

---

## MikroTik Changes — Made in Winbox, Not Yet in RSC

| Item | Change |
|---|---|
| IP → DNS → Servers | `192.168.88.3` (primary), `8.8.8.8` (secondary) |
| IP → DHCP Server → Networks → DNS Servers | `192.168.88.3` |

**Action required:** Update `config/rv-mikrotik-config.rsc` to reflect these changes.

---

## Pending Items

| Item | Notes |
|---|---|
| MikroTik RSC update | Reflect DNS changes made in Winbox |
| MikroTik dst-nat rule | Forward port 80 from club LAN → 192.168.88.3:80 for WeeWX external access |
| WeeWX metric units | `unit_system = metricwx` in `[StdReport]` → `[[Defaults]]` in weewx.conf — currently displaying °F |
| Home Assistant onboarding | Initial setup wizard, MQTT integration, Mosquitto add-on config |
| WeeWX → InfluxDB | WeeWX currently writing to SQLite only — InfluxDB extension install and config pending |
| Session context document | Update `docs/RVTC_Session_Context.md` to reflect Phase 2 complete |

---

## Next Session

Phase 2 wrap-up:
1. WeeWX metric units fix
2. WeeWX → InfluxDB integration
3. Home Assistant onboarding and MQTT integration
4. Update session context document

Then Phase 3 planning — Power integration (EPEVER MPPT60 + SAMLUX EVO-2212 via HF5142B Modbus).


