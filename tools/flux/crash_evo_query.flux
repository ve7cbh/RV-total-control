// RVTC — SAMLUX EVO state leading up to each host crash/reboot
//
// Companion to crash_voltage_query.flux. Battery voltage itself came back
// flat across all three crash windows (no sag, no dropout) -- this pulls
// EVO-side signals instead, to check for a mode transition, fault code, or
// unstable status bitmask lining up with the crash timing. The EVO sits in
// series with the battery bus (Owner's Manual: its own Hall-effect current
// sensor is inline at its Battery +/- terminals), so an internal relay
// event or transient there could disturb the whole shared DC bus without
// necessarily showing up as a battery voltage sag at 1Hz sampling.
//
// Same three crash timestamps as crash_voltage_query.flux (confirmed
// against `journalctl --list-boots`, 2026-08-20):
//   boot -3 tail (Aug17->Aug18 crash): 2026-08-18T19:55:22Z
//   boot -2 tail (Aug18->Aug19 crash): 2026-08-19T23:10:01Z
//   boot -1 tail (Aug19 crash):        2026-08-20T03:00:03Z

import "date"

crash1 = 2026-08-18T19:55:22Z
crash2 = 2026-08-19T23:10:01Z
crash3 = 2026-08-20T03:00:03Z

window = 15m

crashWindow = (crashTime, label) =>
  from(bucket: "rvtc")
    |> range(start: date.sub(d: window, from: crashTime), stop: date.add(d: 1s, to: crashTime))
    |> filter(fn: (r) => r._measurement == "inverter")
    |> filter(fn: (r) =>
        r._field == "operating_mode" or
        r._field == "charge_stage" or
        r._field == "error_code" or
        r._field == "status_grid_input" or
        r._field == "status_gen_input")
    |> set(key: "crash_event", value: label)

union(tables: [
  crashWindow(crashTime: crash1, label: "boot -3 tail (Aug17->Aug18 crash)"),
  crashWindow(crashTime: crash2, label: "boot -2 tail (Aug18->Aug19 crash)"),
  crashWindow(crashTime: crash3, label: "boot -1 tail (Aug19 crash)"),
])
|> sort(columns: ["crash_event", "_field", "_time"])
|> keep(columns: ["crash_event", "_field", "_time", "_value"])
