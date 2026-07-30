# RVTC `config/` Reorg — Handover Note for Claude Code

Written by chat-Claude for whichever Claude ends up executing this in VS Code.
Steve wants this run by an agent, not by hand — so this note is written as a
task brief for you, not just a summary for him. Read the whole thing before
touching anything; the "execution cautions" section at the bottom matters as
much as the checklist.

---

## 1. Decided since the original audit note

The original note (pasted below verbatim in Section 3) proposed a `bridges/`
or `adaptors/` subdirectory for the Python Modbus→MQTT scripts. **That's been
superseded — the directory will be named `config/scripts/`.** This has been
planned for a while on Steve's end; don't second-guess it or revert to the
older naming if you find the draft note lying around in the repo.

## 2. New files from this session that need a home in the reorg

These didn't exist when the original audit note was written, so factor them
into the file→location mapping before moving anything:

- `gps_nmea_bridge.py` + `gps_nmea_bridge.service` — new bridge, MQTT →
  NMEA sentences → HF5142B serial-1, for an APRS radio. Currently deployed
  and running (`systemctl status gps_nmea_bridge` should show active).
- `imu_mqtt.py` — updated this session: added GPS altitude/course/speed/
  UTC-time/fix-heuristic fields for APRS, fixed the paho-mqtt
  `callback_api_version` deprecation warning. Currently deployed and running.
- `imu_mqtt.service` — fixed twice this session: (1) `StartLimitIntervalSec`
  moved from `[Service]` to `[Unit]`; (2) `ExecStart` repointed from a
  stray, never-tracked `imu_mqtt.py` at the repo root to the real, tracked
  `config/imu_mqtt.py` — see Section 3 for the full story, this took the
  IMU offline in production before it was caught. Currently deployed and
  confirmed working.
- `check_timezone_register.py` — one-off diagnostic (reads WitMotion
  register `0x6B`). Confirmed the on-chip time block reports local time,
  not UTC (TIMEZONE register = `0x05`/UTC-7), which `imu_mqtt.py`'s UTC
  calculation now corrects for. Decide during the reorg whether this stays
  as a permanent diagnostic tool or gets deleted now that its one job is
  done and its finding is baked into `imu_mqtt.py`'s logic/comments.

## 3. CONFIRMED (was a hunch — now resolved): symlink convention had drifted

Update, post-handover: this bit the IMU offline in production before the
reorg even started, so it's already been diagnosed and fixed. Leaving the
full account here since it confirms the pattern the original hunch was
worried about.

**What happened:** `imu_mqtt.service`'s `ExecStart` pointed at
`/home/ve7cbh/RV-total-control/imu_mqtt.py` (repo root). That file was
**never tracked in git** — `git log` shows no history for it at all, and
`git status` shows nothing about its disappearance either, because git
never knew it existed. It was a stray, out-of-band copy sitting outside
version control, separate from `config/imu_mqtt.py` (the file this session
actually edited, tested, and redeployed all along). At some point the
root-level copy vanished — cause unknown and *not discoverable from git*,
since it was never in git to begin with — and the service started
crash-looping (`can't open file ... No such file or directory`,
`status=2/INVALIDARGUMENT`) until the mismatch was caught.

**Fix applied:** `imu_mqtt.service`'s `ExecStart` now points at
`/home/ve7cbh/RV-total-control/config/imu_mqtt.py` — the real, tracked,
actually-maintained copy — matching the stated "everything runs from
`config/`" convention. Confirmed working after `daemon-reload` + restart.

**Two more loose ends this surfaced, worth resolving during the reorg
rather than leaving to rot:**

- **`config/imu_hdg/imu_mqtt.py` is a second, separate copy** of this
  script sitting in a different subfolder. Decide which copy is
  authoritative (almost certainly `config/imu_mqtt.py`, the one that's
  actually been maintained) and delete or archive the other — don't leave
  two copies where a future accidental redeploy could pick the stale one.
- **`config/imu_hdg/Microsoft.Services.Store.winmd` shows as deleted** in
  `git status`. This is Windows Store/OneDrive sync metadata, not an RVTC
  config file — harmless, but a sign this subfolder may have picked up
  junk from however the repo gets mirrored to a Windows machine. Worth a
  general look at `config/imu_hdg/` and `config/rvtc-imu/` (both "already
  exists" folders per the original structure) to make sure they don't
  have more of this kind of stray content before folding them into the
  new layout.

**Bigger-picture lesson for the reorg itself:** the original hunch — "check
every `*.service` file's `ExecStart` against where its script actually
lives, this may not be isolated" — turned out to be exactly right. Treat
that as a confirmed requirement for step 1 of the reorg's execution, not
an optional nice-to-have: audit **every** service's `ExecStart`/
`WorkingDirectory` against the real, tracked location of its script before
moving anything, the same way this one had silently drifted.

## 4. Carried over from the original audit note — still open

Verbatim from Steve's note, nothing here has been resolved yet:

- **Confirm SNMP data (Mikrotik/printer/NAS) is actually showing in
  Grafana right now** — none of `telegraf_snmp.conf` /
  `telegraf_rvtc_snmp.conf` / `telegraf_snmp_rvtc.conf` are mounted in the
  current `docker-compose.yml`, so this may be a real gap, not just
  duplicate files.
- **Grep `roles/` (Ansible) for references to `config/` filenames** —
  `docker-compose.yml` and systemd units aren't the only places a path can
  be hardcoded; Ansible template/copy tasks could reference old paths too.
- **Confirm safe to delete:** the four `modbus_*.yaml` files (dead since
  HA's native Modbus was abandoned 2026-06-29 — pymodbus/Waveshare
  incompatibility) and `MQTT-Explorer-Setup-0.4.0-beta.6.exe` (installer,
  not a config file).
- **`rtl433`/`rtl433b` service blocks are still fully defined in
  `docker-compose.yml`, just unused** — a bare `docker compose up -d`
  would resurrect them. Delete the blocks, don't just leave them dormant.
- **`gps_mqtt.py` and `relay_test.sh` live at the repo root**, not in
  `config/` like every other bridge script — decide if they move too.

## 5. Proposed structure (naming updated per Section 1)

```
config/
├── scripts/          # Python Modbus→MQTT + NMEA bridge scripts, .service units
├── telegraf/         # telegraf*.conf
├── homeassistant/     # automations/helpers/scripts/mqtt_sensors/dashboards
├── mikrotik/          # .rsc files, Mikrotik-Failover.md
├── nginx/             # nginx.conf, rvtc_index.html, index.html
├── grafana/           # dashboard JSONs
├── Tank_Mon/          # already exists
├── rvtc-imu/          # already exists
├── i2c/               # already exists
└── docs/              # IMU_config.md, patch instructions, main.pdf
```

## 6. Execution cautions

- **Don't delete anything** (`modbus_*.yaml`, the installer `.exe`, the
  `rtl433`/`rtl433b` docker-compose blocks) until the three open audit
  questions in Section 4 are answered. If it's not clear from grepping the
  repo, ask Steve rather than assuming — deletion is the one step here
  that isn't easily reversible.
- **This touches every service's systemd unit**, not just the ones changed
  today. Moving a script without updating its unit's `ExecStart`/
  `WorkingDirectory` will silently break that bridge the next time it
  restarts (or immediately, if you also restart it). Build the complete
  file→new-location mapping as a table first; don't move-as-you-go.
- **After any move:** `sudo systemctl daemon-reload`, restart, then
  `journalctl -u <service> -n 20 --no-pager` for **every** affected
  service — not just the one you're focused on — before moving to the
  next file. Confirm a clean start (no missing-file errors, no
  `DeprecationWarning` lines reappearing) each time.
- **Recreate symlinks** pointing into `config/` as needed after the real
  files move; verify with `ls -la config/scripts/` that nothing is
  dangling.
- **Preserve this session's fixes** — the paho-mqtt `callback_api_version`
  fix in both `imu_mqtt.py` and `gps_nmea_bridge.py`, and the
  `StartLimitIntervalSec` `[Unit]`-section fix in `imu_mqtt.service`. A
  careless copy from an older git commit or backup could silently revert
  any of these.
- **Steve has dyslexia with transpositional errors** (documented in
  `RVTC_System_Reference.md` Section 10) — for any multi-file rename/move,
  prefer scripted `mv`/`ln -s` commands with an explicit
  "source exists / destination doesn't already exist" check over manual
  one-by-one moves, and double-check any hand-typed path before running it.

## 7. Suggested order of operations

1. **Before anything else:** audit every `*.service` file's `ExecStart`/
   `WorkingDirectory` against the real, tracked location of its script.
   This isn't precautionary — it already caused a production outage this
   session (see Section 3). Confirmed method: compare each unit's
   `ExecStart` path against `git log --follow -- <path>`; if git has no
   history for that path, it's not the real file, no matter how recently
   it was edited on disk.
2. Answer the three open audit questions (Section 4) — they determine
   what gets deleted vs. moved, so resolve them before step 3.
3. Build the full file → new-location mapping as a table. Include every
   file discussed in Sections 2 and 3 alongside the original list.
4. Move files.
5. Recreate/repoint symlinks.
6. Update every affected systemd unit's `ExecStart`/`WorkingDirectory`.
7. `daemon-reload` + restart each affected service **one at a time**,
   confirming clean logs before touching the next.
8. If the directory layout changed enough to matter, update
   `RVTC_System_Reference.md` and the Ansible Role Structure doc to match
   — both are meant to describe current reality, not the pre-reorg state.
