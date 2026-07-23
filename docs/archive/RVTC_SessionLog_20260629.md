# RVTC — Session Notes 2026-06-29
## Home Assistant Relay Integration — Waveshare 8-Ch Board via shell_command + relay.py

---

### Summary

This session completed the Home Assistant integration for the Waveshare 8-channel RS-485 relay
board (HW-13, RS-485/8, 192.168.88.12:4001). The native HA Modbus integration was attempted and
abandoned due to a confirmed pymodbus / Waveshare firmware incompatibility. A working alternative
was implemented using HA `shell_command` calling a custom Python script (`relay.py`) that sends
raw Modbus TCP writes directly.

---

### What Was Attempted — HA Native Modbus Integration

**File:** `/data/docker/volumes/homeassistant/modbus-relay.yaml`
**Included in configuration.yaml as:** `modbus: !include modbus-relay.yaml`

Initial YAML had a structural error — `modbus:` top-level key inside the included file created a
nested `modbus.modbus` structure. Corrected by removing the wrapper key and re-indenting the
entire file 2 spaces left (done with `sed -i 's/^  //' modbus-relay.yaml`). A subsequent edit
introduced a 1-space indent on `switches:` (should be 2) which triggered HA recovery mode —
corrected with `sed -i 's/^ switches:/  switches:/'`.

After structural fixes, all 8 entities appeared in HA (`switch.waveshare_relay_1` through
`switch.waveshare_relay_8`) and showed as available. However, toggling any relay produced no
physical result. Log showed:

```
ERROR [pymodbus.logging] No response received after 3 retries, continue with next request
ERROR [homeassistant.components.modbus] Pymodbus: waveshare_rtu_8ch: Error: device: 1 address: 0
      -> Modbus Error: [Input/Output] No response received after 3 retries
```

**Root cause:** pymodbus 3.11.2 (confirmed via `docker exec homeassistant python3 -c "import
pymodbus; print(pymodbus.__version__)"`) holds a persistent TCP connection to the gateway.
The Waveshare gateway drops idle connections after a short timeout. When pymodbus subsequently
sends a request on a stale connection the gateway has already closed on its side, it receives no
response. `ss -tn | grep 4001` confirmed an ESTABLISHED connection held open by the HA container.

mbpoll works because it opens a fresh TCP connection per command, sends the frame, and closes
immediately — the gateway is always ready for a new connection.

**Parameters tried and abandoned:**
- `delay: 3` — caused recovery mode (not a valid parameter in this HA version)
- `reconnect_delay: 0` / `reconnect_delay_max: 0` — no effect
- `close_comm_on_error: true` / `retry_on_empty: true` / `timeout: 1` — entities went unavailable
- `scan_interval: 0` — disables polling but HA still does an initial read on startup which fails
  and marks the device unavailable
- `verify_state: false` — not a valid HA Modbus schema parameter; caused "Invalid config" on load

**Conclusion:** pymodbus 3.x persistent connection behaviour is fundamentally incompatible with
the Waveshare gateway's connection handling. The native Modbus integration cannot be made to work
without patching pymodbus itself. The `modbus: !include modbus-relay.yaml` line has been
commented out in `configuration.yaml`.

---

### Solution — shell_command + relay.py

Since mbpoll works reliably, the approach is to call an equivalent command from HA's
`shell_command` integration. mbpoll is not available inside the Alpine Linux HA container
(`ghcr.io/home-assistant/home-assistant:stable` runs Alpine 3.22.2). Binding the host
`/usr/bin/mbpoll` binary into the container via a volume mount does not work — the host binary
is compiled for Debian (glibc) and cannot execute under Alpine (musl libc).

**Fix:** A small Python script (`relay.py`) was written that constructs and sends a raw Modbus
TCP Write Single Coil (FC 05) frame using only the Python standard library. No external
dependencies. The script opens a fresh TCP socket, sends the frame, reads the response, and
closes — identical behaviour to mbpoll.

**File location (in HA container):** `/config/relay.py`
**File location (on host):** `/data/docker/volumes/homeassistant/relay.py`

```python
#!/usr/bin/env python3
import sys
import socket
import struct

def write_coil(host, port, slave, coil, value):
    transaction_id = 0x0001
    protocol_id = 0x0000
    unit_id = slave
    function_code = 0x05  # Write Single Coil
    coil_value = 0xFF00 if value else 0x0000

    pdu = struct.pack('>BBHH', unit_id, function_code, coil, coil_value)
    mbap = struct.pack('>HHH', transaction_id, protocol_id, len(pdu))
    frame = mbap + pdu

    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(frame)
        s.recv(256)

if __name__ == '__main__':
    # Usage: relay.py <coil 0-7> <0|1>
    coil = int(sys.argv[1])
    value = int(sys.argv[2])
    write_coil('192.168.88.12', 4001, 1, coil, value)
```

**Usage:** `python3 /config/relay.py <coil> <value>`
- coil: 0-based (coil 1 = 0, coil 2 = 1, ... coil 8 = 7)
- value: 1 = energise, 0 = de-energise

**Verification:**
```bash
# From host — confirmed working:
python3 /data/docker/volumes/homeassistant/relay.py 0 1   # coil 1 ON
python3 /data/docker/volumes/homeassistant/relay.py 0 0   # coil 1 OFF

# From inside container — confirmed working:
docker exec homeassistant python3 /config/relay.py 0 1
docker exec homeassistant python3 /config/relay.py 0 0
```

---

### configuration.yaml — shell_command block

Added to `/data/docker/volumes/homeassistant/configuration.yaml`:

```yaml
shell_command:
  relay_1_on:  "python3 /config/relay.py 0 1"
  relay_1_off: "python3 /config/relay.py 0 0"
  relay_2_on:  "python3 /config/relay.py 1 1"
  relay_2_off: "python3 /config/relay.py 1 0"
  relay_3_on:  "python3 /config/relay.py 2 1"
  relay_3_off: "python3 /config/relay.py 2 0"
  relay_4_on:  "python3 /config/relay.py 3 1"
  relay_4_off: "python3 /config/relay.py 3 0"
  relay_5_on:  "python3 /config/relay.py 4 1"
  relay_5_off: "python3 /config/relay.py 4 0"
  relay_6_on:  "python3 /config/relay.py 5 1"
  relay_6_off: "python3 /config/relay.py 5 0"
  relay_7_on:  "python3 /config/relay.py 6 1"
  relay_7_off: "python3 /config/relay.py 6 0"
  relay_8_on:  "python3 /config/relay.py 7 1"
  relay_8_off: "python3 /config/relay.py 7 0"
```

Called from Developer Tools → Actions as `shell_command.relay_1_on` etc. Confirmed working —
relay audibly clicks, physical load responds.

---

### Persistence Note

`relay.py` lives in `/config/` which maps to the persistent HA volume
(`/data/docker/volumes/homeassistant/`). It will survive container restarts and HA image
updates. It will NOT be present if the volume is wiped and rebuilt from scratch — keep a copy
in the repository (`config/relay.py`).

The `/usr/bin/mbpoll:/usr/bin/mbpoll` volume mount added to `docker-compose.yml` during
troubleshooting is no longer needed and should be removed at the next compose edit.

---

### docker-compose.yml — cleanup required

Remove this line from the `homeassistant:` volumes block (no longer needed):

```yaml
    - /usr/bin/mbpoll:/usr/bin/mbpoll
```

---

### Section 2.8 — Note to add

Under the Modbus coil addressing block in Section 2.8, add:

> **NOTE — HA native Modbus integration not used:** pymodbus 3.x holds a persistent TCP
> connection to the Waveshare gateway. The gateway drops idle connections; pymodbus does not
> reconnect cleanly, producing "No response received" errors on every write. mbpoll works because
> it uses fresh connections per command. HA relay control is implemented via `shell_command` +
> `/config/relay.py` (raw Modbus TCP, Python stdlib only). See session log 2026-06-29.

---

### OI-24 Status Update

HA now has working relay write capability via `shell_command`. The `modbus_relay.yaml` approach
is abandoned. OI-24 automation work (Tier 3 overload logic) can proceed using
`shell_command.relay_N_on/off` as the actuator primitives. HA cannot read relay state via this
method — coil state must be tracked in HA input_boolean helpers or assumed from command history
if state feedback is required.

---
*Session notes prepared 2026-06-29 — append to Section 8 session log in project reference.*
