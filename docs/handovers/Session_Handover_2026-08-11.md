# Session Handover — 2026-08-11

**Scope:** WitMotion GPS bug (closed), trailer↔home IPsec VPN (working, tested), Hantek 6022BL
scope bring-up (working), home Pi rebuild (IN PROGRESS — this is the urgent one).

---

## 🔴 URGENT / IN PROGRESS — home-pi rebuild

**Where things stand right now:** mid-flash, session ended before confirming completion.

**Hardware:** the home Pi is a **CM4 with onboard eMMC, no SD slot**. Original plan was
Windows + `rpiboot`, but that failed repeatedly (see below) — **pivoted to a Linux box
(`zabbixAspire-5333`) and that path is working.**

**What actually worked, after a lot of dead ends:**
- Windows `rpiboot` (both the bare `.exe` and, after correcting course, the real
  `rpiboot_setup.exe` installer) consistently failed at the second boot stage —
  `"Failed to read config descriptor"` / Device Manager showed `"Unknown USB Device (Device
  Descriptor Request Failed)"`. Tried: Zadig/WinUSB (wrong tool for this — undone), different
  cables, direct ports, a stronger read on the official docs. None of it was the real problem.
- **The real problem:** on the Linux box, running the **pre-existing Ubuntu-packaged `rpiboot`
  with no arguments** silently did a generic recovery handoff, not a mass-storage boot — it
  "succeeded" at the wrong thing, no error, nothing to fix.
- **The actual fix:** build `rpiboot` fresh from source and use the explicit mass-storage flag:
  ```bash
  git clone --recurse-submodules https://github.com/raspberrypi/usbboot
  cd usbboot && make
  sudo ./rpiboot -d mass-storage-gadget64
  ```
  Sequence: jumper fitted (`EMMC_DISABLE`/`nRPIBOOT`) → launch this → confirm it's waiting →
  connect USB → apply power. **This worked cleanly** — `dmesg` confirmed `USB Mass Storage
  device detected`, eMMC came up as **`/dev/sdc`** (29.1 GB, `sdc1` 256M boot + `sdc2` 28.9G
  root — standard Raspberry Pi OS layout, confirmed via `lsblk` before writing anything).
- Power was a live theory for a while (2A supply, works fine for 4 years of normal Pi-hole
  operation but plausibly marginal for the eMMC init current spike) — **turned out not to be
  the cause**. The Linux/correct-flag fix resolved it cleanly; never actually had to test a
  stronger supply. Worth remembering if any *other* CM4 boot issue comes up in the future, since
  the power theory itself was sound reasoning, just not what was happening here.

**Where it stopped:** Raspberry Pi Imager's GUI failed (`qt.qpa.xcb: could not connect to
display` — no X11 on this SSH session). Pivoted to CLI `dd` instead. Last command issued was
downloading a fresh Raspberry Pi OS Lite (64-bit) image:
```bash
wget -O raspios-lite.img.xz https://downloads.raspberrypi.com/raspios_lite_arm64_latest
```
**Not confirmed whether this download finished.** Next session should start by checking:
```bash
ls -la ~/raspios-lite.img.xz
```

**Remaining steps once the image is confirmed downloaded:**
```bash
xz -d -k raspios-lite.img.xz
sudo dd if=raspios-lite.img of=/dev/sdc bs=4M status=progress conv=fsync
sync
```
**Re-verify `/dev/sdc` is still the right target before writing** — re-run `lsblk` first,
same sanity check as before, since some time/reboots may have passed.

**Then — headless setup is still needed, since Imager's advanced-options GUI got skipped:**
mount `sdc1` (the boot partition) and manually create:
- an empty file named `ssh` (enables SSH on first boot)
- `userconf.txt` containing `username:hashed-password` (modern Raspberry Pi OS requires this
  instead of the old default `pi`/`raspberry` login — password needs to be pre-hashed with
  `openssl passwd -6`, not plaintext)

**Then:** unplug USB, remove the `EMMC_DISABLE`/`nRPIBOOT` jumper, power cycle. Should boot
fresh off eMMC as a real, network-reachable Pi.

**After first boot confirmed:**
```bash
sudo apt update && sudo apt full-upgrade   # clean Trixie-native install this time, should be simple
```
Then reinstall Pi-hole via the official install script. **No DNS cutover needed** — confirmed
this Pi was never actually in the home network's active DNS path to begin with, despite
originally thinking it was.

---

## ✅ Resolved this session

**WitMotion GPS longitude bug — closed.** Firmware `05821` (WitMotion's suggested downgrade)
confirmed fully correct via a 5000-sample rapid burst capture: 0 invalid reads, `LonH` stable
at the correct `0xB678` for the entire ~400s capture, ~4m accuracy against surveyed position.
Full package (burst capture, PC-software CSV, MQTT/WitMotion screenshots) already sent to
WitMotion support and not expected to need further action. **System Reference has been updated**
with the full resolution in Section 9 (Known Quirks) — delivered as a file this session, ready
to replace the working copy.

**Trailer↔home IPsec VPN — built, tested, and genuinely working.** MikroTik (trailer) ↔ TP-Link
ER605 V2 (home), IKEv2/AES-256/SHA-256-or-512/DH14 (home landed on SHA-512 by default click-path;
MikroTik config written to match SHA-256 — **worth double-checking both sides actually agree**,
this may need reconciling next session if not already caught). Home is Responder (`0.0.0.0`
remote gateway, since trailer's source IP varies between Club and Starlink WANs), trailer is
Initiator. DDNS: `home-rvtc.ddns.net` (No-IP Enhanced tier) confirmed live and correctly bound to
the ER605's `WAN/LAN2` interface. **Tested for real** — not just SA-established, but an actual
`ping 192.168.0.1` (23-39ms round trip) and a live Home Assistant dashboard load, both through
the tunnel from the trailer's LAN. PSK is `<redacted — see ~/rvtc-files/private/ on the host>` — stored
in this chat history, worth moving to a proper password manager / RVTC docs vault.

**Still open on the VPN thread, not urgent:**
- Club leg (UniFi UDM Pro ↔ home) — not built yet. UDM Pro's native Site-to-Site VPN only
  offers OpenVPN/IPsec (no WireGuard, despite what UniFi's own docs suggested before checking
  the actual device) — so this leg uses IPsec too, consistent with the rest.
- `malacat.ca` migration — domain is now **Active** (confirmed today). A CNAME
  (`home.malacat.ca → home-rvtc.ddns.net`) is already working as a friendly-name shortcut with
  zero propagation wait. Full Plus Managed DNS / nameserver delegation migration (for
  `home.malacat.ca`/`rv.malacat.ca` as real records, not just a CNAME) is still a future task,
  not started.
- Confirmed the tunnel still needs testing over the trailer's **Starlink** WAN specifically, not
  just Club — only tested on Club so far. (Reasoned through why this should work regardless —
  trailer is always the initiator, so CGNAT on Starlink doesn't block it — but not empirically
  confirmed yet.)

**Hantek 6022BL PulseView setup — working.** Two real, separate bugs, both resolved:
1. **Driver:** use the **`hantek-6xxx`** driver in PulseView's connect dialog, **not `fx2lafw`**
   — `fx2lafw` consistently failed to open the device even with a correct WinUSB/Zadig binding;
   `hantek-6xxx` worked immediately once selected.
2. **USB hub:** the scope was behind a hub, which silently stalled PulseView's firmware-upload
   step (0% CPU, no error, just hung) even though simple enumeration always looked fine through
   the hub. **Bypassing the hub — direct port on the machine — fixed it immediately.**
   Confirmed working with a clean captured calibration square wave (~996 Hz, matching a typical
   scope cal signal) on CH1. **Ready to actually capture the Dometic HVAC signal** whenever that
   work resumes — no outstanding blockers on the tooling side anymore.

---

## 📁 Files delivered this session
- `RVTC_System_Reference_2_3.md` (updated, WitMotion GPS quirk added to Section 9) — ready to
  replace the working copy in the project
