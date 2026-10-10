# RAK4631 Companion Radio Firmware — MeshCore, button-pin fix

Compiled firmware for a WisBlock RAK4631 stack (RAK4631 core + GPS + LCD +
RAK13800 Ethernet/PoE, no physical user button besides reset), used as a
MeshCore "companion radio" station reachable by the Meshy app.

## The bug this fixes

Upstream `meshcore-dev/MeshCore`'s `RAK_4631_companion_radio_{usb,ble,ethernet}`
PlatformIO envs (`variants/rak4631/platformio.ini`) define `PIN_USER_BTN=9` and
`PIN_USER_BTN_ANA=31`, assuming a physical button is wired to those pins. On
this hardware (no such button), those pins float and get misread as a
sustained long-press within the first 8 seconds of boot, which silently drops
the firmware into "CLI Rescue" mode (`MyMesh::enterCLIRescue()`,
`examples/companion_radio/ui-new/UITask.cpp`). Once in that mode,
`MyMesh::loop()` stops calling `checkSerialInterface()` — the shared,
transport-agnostic companion-protocol dispatcher — for the rest of that boot.
That breaks USB, BLE, and Ethernet identically: the device accepts a
connection at the transport level but never responds to any companion
protocol frame (not even `CMD_APP_START`), so apps like Meshy see a connection
that just times out.

Filed upstream as [meshcore-dev/MeshCore#3400](https://github.com/meshcore-dev/MeshCore/issues/3400).

**Fix**: remove `PIN_USER_BTN`/`PIN_USER_BTN_ANA` from all three
`RAK_4631_companion_radio_*` envs — see `platformio.ini.patch`. Confirmed
working end-to-end (manual `CMD_APP_START`/`RESP_CODE_SELF_INFO` round trip,
then a full Meshy sync) on the Ethernet build; USB and BLE build clean with
the same patch but haven't been flash-tested yet.

## Contents

| File | What it is |
|---|---|
| `RAK_4631_companion_radio_ethernet.zip` | Adafruit nRF52 DFU package — **currently flashed and running** as the station's MeshCore companion node (Ethernet/PoE, reachable over TCP port 5000, DHCP hostname `WIZnet174C8D`, MAC `02:92:1f:17:4c:8d`, currently `192.168.88.240`). |
| `RAK_4631_companion_radio_usb.zip` | Same fix, USB-transport companion build. Not yet flash-tested. |
| `RAK_4631_companion_radio_ble.zip` | Same fix, BLE-transport companion build. Not yet flash-tested. |
| `platformio.ini.patch` | The exact diff against upstream `variants/rak4631/platformio.ini` that produced these builds. |
| `UPSTREAM_COMMIT.txt` | The upstream `meshcore-dev/MeshCore` commit these were built from. |

## Rebuilding

```
git clone https://github.com/meshcore-dev/MeshCore.git
cd MeshCore
git apply /path/to/platformio.ini.patch
pip install platformio
python -m platformio run -e RAK_4631_companion_radio_ethernet   # or _usb / _ble
# output: .pio/build/<env>/firmware.zip
```

## Flashing (serial DFU, Adafruit nRF52 bootloader)

```
pip install adafruit-nrfutil
adafruit-nrfutil --verbose dfu serial \
  --package RAK_4631_companion_radio_<env>.zip \
  -p /dev/ttyACM0 -b 115200 --singlebank -t 1200
```

`-t 1200` performs the 1200bps touch-reset to enter the bootloader first; the
device automatically reboots into the new application firmware once the
transfer completes.
