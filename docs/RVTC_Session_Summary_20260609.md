# RVTC Session Summary — 2026-06-09

## Session Goals
- Diagnose WeeWX not updating (several days of no data)
- Complete Phase 2 open items
- Transition to Phase 3

---

## Work Completed This Session

### WeeWX / rtl_433 — Full diagnosis and fix

**Root cause (multi-part):**

1. **Wrong compose file location** — the docker stack was being run from `/data/docker/volumes/docker-compose.yml` (a recovered/incomplete copy) instead of `~/RV-total-control/docker-compose.yml`. This placed containers on different Docker networks (`volumes_default` vs `data_default` vs `rvtc_net`), so the rtl433 container could not reach the mosquitto container by hostname.

2. **Hardcoded USB device path** — compose file had `/dev/bus/usb/001/006` hardcoded. The dongle enumerates at a different device number after every disconnect/reconnect (due to repeated plug/unplug during diagnosis). Fixed by passing the entire USB bus: `/dev/bus/usb:/dev/bus/usb`.

3. **Invalid MQTT publish topic** — compose file had `events=rtl_433/+/events`. The `+` character is an MQTT wildcard and is invalid in a publish topic. Fixed to `events=rtl_433/rtl433/events`.

4. **Wrong field name mappings in weewx.conf** — `temperature_C` and `rain_mm` were mapped but rtl_433 (all versions tested: 25.02, 25.12) publishes `temperature_F` and `rain_in`. WeeWX `StdConvert` with `target_unit = METRICWX` handles F→C and inch→mm conversion automatically once the field names are correct. Fixed mappings to `temperature_F` (units = degree_F) and `rain_in` (units = inch). `contains_total = true` retained on rain_in.

5. **dvb_usb_rtl28xxu kernel module** — loaded on boot and claimed the RTL-SDR before rtl_433 could open it. Resolved by blacklist (see OI-23 below).

6. **Grafana not started** — container was missing from the running stack after reboot, causing nginx to fail (`host not found in upstream "grafana"`). Started manually; root cause was incomplete stack startup from wrong compose file location.

**Key diagnostic findings:**
- rtl_433 host binary (25.02) decoded Acurite 5n1 correctly throughout — dongle hardware is fine
- PLL not locked warning on R828D tuner is benign — has always been present and does not affect reception
- RTL-SDR Blog V3 (HW-11) confirmed received and working — R828D tuner, SN 00000001 (factory default)
- Old clone dongle (R820T) confirmed failing — USB enumeration instability, not software

**Fix sequence:**
```bash
# Run stack from correct compose file
cd ~/RV-total-control
docker stop $(docker ps -q)
docker rm $(docker ps -aq)
docker compose up -d

# Fix USB passthrough in docker-compose.yml
devices:
  - /dev/bus/usb:/dev/bus/usb

# Fix MQTT topic
command: ["-M", "si", "-F", "mqtt://mosquitto:1883,retain=1,events=rtl_433/rtl433/events"]

# Fix weewx.conf field mappings
[[[[temperature_F]]]]
    name = outTemp
    units = degree_F
[[[[rain_in]]]]
    ignore = false
    name = rain
    units = inch
    contains_total = true
```

**Result:** WeeWX live and archiving correctly. Temperature in °C, rain in mm (via StdConvert), wind in m/s.

---

### rtl_433 field names — confirmed behaviour

Both Acurite 5n1 units (ID 1111 Channel A and ID 291 Channel C) publish:
- `temperature_F` (not `temperature_C`)
- `rain_in` (not `rain_mm`)
- `wind_avg_km_h` ✅
- `humidity` ✅

rtl_433 does not perform unit conversion regardless of version or `-M si` flag — the Acurite 5n1 decoder hardcodes field names. Previous belief that `rain_mm` was published was incorrect; the `contains_total = true` fix at Port Renfrew was valid and necessary, but the field name was always `rain_in`.

---

### Rain sensor — status update

ID 291 (Port Renfrew unit) was brought indoors for testing and physically shaken during handling, legitimately incrementing the tipping bucket. Rain accumulation seen during testing was real bucket tips, not a sensor fault. Unit inspected — no reed switch fault found. Rain behaviour at Port Renfrew was entirely due to missing `contains_total = true`. HW-14 remains open for physical inspection of the rain gauge at the club, but the sensor itself is not suspected faulty.

---

### ID filter added to weewx.conf

Added `filter_out_message_when = 291` to the `[[[[id]]]]` stanza to exclude the Port Renfrew unit when both are in range. Filter was not tested under rain conditions — will verify next rain event.

---

### MikroTik RSC — two fixes applied

See separate session for details. Two changes committed to `config/rv-mikrotik-config.rsc` (dated 2026-06-09):
1. Removed `ether8` from LAN interface list
2. Removed redundant forward-chain WeeWX pinhole (dst-nat rule handles all WeeWX access)

---

### Phase 2 OI items completed

| OI | Item | Resolution |
|---|---|---|
| OI-22 | WiFi autoconnect fix | Added to Ansible common role: `nmcli radio wifi off` + `autoconnect=no` for both connections |
| OI-23 | dvb_usb_rtl28xxu blacklist | Blacklist file created manually + baked into Ansible common role |
| OI-27 | rtl-sdr package in Ansible | Added `rtl-sdr` and `sqlite3` to `common_packages` in role defaults |
| OI-17 | weewx.conf saved to config/ | `config/weewx.conf` committed to repo |
| OI-28 | Belchertown skin installed | Installed via `weectl extension install`; dark mode enabled via on-page toggle |
| OI-31 | nginx .local → .lan | nginx.conf updated; `config/nginx.conf` committed to repo |

---

### Grafana user fix

Added `user: "472:472"` to grafana service in docker-compose.yml — prevents volume ownership issues on reboot. Grafana dashboard was lost after this reboot (permissions issue before fix applied); will need to be rebuilt.

---

### Belchertown skin

Installed and serving at `http://weewx.lan/belchertown`. Dark mode enabled via on-page toggle. nginx root updated to `/usr/share/nginx/html/belchertown`. Seasons skin remains installed but is no longer the default served page.

---

## Issues Resolved

- WeeWX not updating — fully resolved (network isolation + USB path + MQTT topic + field names)
- dvb_usb_rtl28xxu module conflict — resolved (blacklist applied)
- nginx serving default page instead of WeeWX — resolved
- Grafana volume permissions — resolved (user: 472:472 in compose)

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| OI-17 | Ansible weewx role cleanup | ✅ Complete — weewx.conf saved to config/; manual management accepted |
| OI-22 | WiFi autoconnect fix | ✅ Complete — Ansible common role |
| OI-23 | dvb_usb_rtl28xxu blacklist | ✅ Complete — Ansible common role |
| OI-27 | rtl-sdr package in Ansible | ✅ Complete — common role defaults |
| OI-28 | Belchertown / PyEphem | ✅ Complete — Belchertown installed with dark mode; civil twilight already in template |
| OI-31 | nginx .local → .lan | ✅ Complete — nginx.conf updated and committed |
| HW-11 | RTL-SDR Blog V3 | ✅ Received and working — R828D tuner confirmed |
| HW-14 | Rain sensor inspection | Still open — sensor behaviour now better understood; physical inspection at club still required |

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| Grafana dashboard | Lost after reboot/permissions fix — needs rebuilding |
| Rain ID filter | `filter_out_message_when = 291` added but not tested under rain conditions |
| Rain stats accuracy | Will revisit after HW-14 resolved and next rain event with correct field mappings |
| WeeWX upstream bug report | OI-32 still open |

---

## Next Session — Phase 3

1. Waveshare RS-485 gateway commissioning (HW-01) — device in hand
2. EPEVER MPPT60 Modbus integration (RS-485/1, TCP 4001)
3. SAMLUX EVO-2212 inverter Modbus integration (RS-485/2, TCP 4002)
4. Solar panel wiring (HW-03/HW-04)
5. Home Assistant onboarding — MQTT integration (OI-15)
6. Rebuild Grafana dashboard (OI-16)
7. WeeWX upstream bug report (OI-32)
