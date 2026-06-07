# RVTC Session Summary — 2026-06-07

## Session Goals
- Fix rain week/month/year stats not accumulating correctly after cumulative sensor fix (2026-06-05)

---

## Work Completed This Session

### Rain stats corruption — diagnosis and partial fix

**Root cause:** The `archive_day_rain` daily summary table and the raw `archive` table both contained phantom rain data from the hardware fault period (stuck float/reed switch), which predated the `contains_total = true` cumulative fix applied 2026-06-05. WeeWX builds week/month/year stats by summing `archive_day_rain`, so all longer-period totals were wildly wrong (~2383mm on June 5 alone).

**Tools installed:**
- `sqlite3` installed on host (`sudo apt install sqlite3`) — WeeWX container does not include it

**Diagnostic queries used:**
```bash
# Archive records
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, rain, rainRate FROM archive ORDER BY dateTime DESC LIMIT 20;"

# Daily summary table
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "SELECT datetime(dateTime, 'unixepoch', 'localtime') as ts, sum, max, count FROM archive_day_rain ORDER BY dateTime DESC LIMIT 14;"
```

**Fixes applied:**
1. Zeroed bogus `archive_day_rain` rows (all dates prior to 2026-06-06):
```bash
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "UPDATE archive_day_rain SET sum=0.0, max=0.0 WHERE dateTime < strftime('%s', '2026-06-06 00:00:00', 'utc');"
```

2. Zeroed phantom archive records for June 5 (09:30–18:52 UTC — the stuck-float period):
```bash
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "UPDATE archive SET rain=0.0, rainRate=0.0 WHERE dateTime >= strftime('%s', '2026-06-05 00:00:00', 'utc') AND dateTime < strftime('%s', '2026-06-05 18:52:00', 'utc');"
```

3. Zeroed a phantom June 7 spike (1.59mm at 10:17:30 — believed to be sensor fault):
```bash
sqlite3 /data/docker/volumes/weewx/archive/weewx.sdb \
  "UPDATE archive SET rain=0.0, rainRate=0.0 WHERE dateTime = strftime('%s', '2026-06-07 10:17:30', 'utc');"
```

4. Rebuilt daily summaries from corrected archive:
```bash
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=2026-06-05 --yes
docker exec weewx weectl database rebuild-daily --config=/data/weewx.conf --date=2026-06-07 --yes
docker restart weewx
```

**Notes on `weectl database rebuild-daily`:**
- `weewx.conf` inside the container is at `/data/weewx.conf` (volume root), not `/home/weewx/weewx.conf`
- Must pass `--yes` flag — command prompts for confirmation and fails with EOFError when stdin is not a TTY (i.e. via `docker exec`)
- `sqlite3` is not in the WeeWX container — run all queries from the host against `/data/docker/volumes/weewx/archive/weewx.sdb`

**Status after fix:** Rain totals improved but still showing elevated values (~121mm). Further investigation revealed the rain sensor is still actively firing — MQTT shows cumulative `rain_mm` continuing to increment. With light rain present at Port Renfrew, it is unclear whether the sensor is correctly measuring real rain or still malfunctioning. Deferred pending physical inspection at club (HW-14).

**OEM display reference:** 9.144mm over 3 days — useful ground-truth sanity check once sensor is repaired and re-enabled.

### Local DNS — .local → .lan migration
- `.local` TLD depends on mDNS/Avahi — works in browsers (which have their own mDNS resolver) but fails in terminal sessions (which use the standard DNS stack / Pi-hole)
- All local DNS records changed from `.local` to `.lan` — works correctly for both browser and terminal
- `.local` should not be used going forward

---

## Issues Resolved

- **archive_day_rain corruption** — phantom data zeroed, daily summaries rebuilt
- **sqlite3 missing** — installed on host
- **weectl config path** — confirmed `/data/weewx.conf` inside container

---

## Open Items Status Changes

| ID | Item | Status Change |
|---|---|---|
| HW-14 | Rain sensor inspection | Still open — sensor behaviour ambiguous under light rain; defer to club visit |
| OI-31 | Local DNS .local → .lan migration | Added ✅ Complete — all records updated in Pi-hole |

---

## Known Issues / Pending

| Item | Notes |
|---|---|
| Rain sensor | Still producing elevated readings — unclear if real rain or continued fault. OEM shows 9.144mm/3 days. Defer diagnosis to club — physical inspection required (HW-14) |
| Rain stats accuracy | WeeWX rain totals still not reconciling with OEM display — gap of ~6mm over 3 days. May be cumulative sensor calibration issue or ongoing phantom triggers. Revisit after HW-14 resolved. |
| WeeWX upstream bug report | The combination of `contains_total = true` + hardware fault → polluted `archive_day_rain` → broken week/month/year stats is a legitimate bug/documentation gap in WeeWX. No warning, no sanity check, fix not documented. Report to WeeWX GitHub issue tracker with diagnostic path and fix. |

---

## Next Session

1. Rain sensor physical inspection and repair at club (HW-14) — re-enable in WeeWX after fix
2. Home Assistant onboarding — MQTT integration, WeeWX entities (OI-15)
3. ESPHome Ansible role (OI-18)
4. Grafana cleanup — friendly legend names, auto-refresh, rename data source (OI-16)
5. WiFi autoconnect fix (OI-22)
6. dvb_usb_rtl28xxu blacklist (OI-23)
7. File WeeWX upstream bug report
