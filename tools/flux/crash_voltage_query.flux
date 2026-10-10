// RVTC — battery voltage leading up to each host crash/reboot
//
// Crash timestamps below are the actual LAST journald entry of each crashed
// boot session, cross-checked against `journalctl --list-boots` on
// 2026-08-20 (confirmed to match `journalctl -b -1/-2/-3 | tail`):
//
//   boot -3 (started Aug 17 15:27 PDT) -- last entry 2026-08-18 12:55:22 PDT
//   boot -2 (started Aug 18 12:54 PDT) -- last entry 2026-08-19 16:10:01 PDT
//   boot -1 (started Aug 19 18:04 PDT) -- last entry 2026-08-19 20:00:03 PDT
//
// Each window pulls the `window` duration before that timestamp so you can
// see the trend -- steady, sagging, or a hard dropout -- right up to the
// point logging stopped. Uses the HW-24 shunt's own voltage reading
// (battery_current measurement), the most direct "at the battery" source.

import "date"

crash1 = 2026-08-18T19:55:22Z   // boot -3 tail (Aug 17 15:27 crash)
crash2 = 2026-08-19T23:10:01Z   // boot -2 tail (Aug 18 12:54 crash)
crash3 = 2026-08-20T03:00:03Z   // boot -1 tail (Aug 19 18:04 crash)

window = 15m

crashWindow = (crashTime, label) =>
  from(bucket: "rvtc")
    |> range(start: date.sub(d: window, from: crashTime), stop: date.add(d: 1s, to: crashTime))
    |> filter(fn: (r) => r._measurement == "battery_current" and r._field == "voltage")
    |> set(key: "crash_event", value: label)

union(tables: [
  crashWindow(crashTime: crash1, label: "boot -3 tail (Aug17->Aug18 crash)"),
  crashWindow(crashTime: crash2, label: "boot -2 tail (Aug18->Aug19 crash)"),
  crashWindow(crashTime: crash3, label: "boot -1 tail (Aug19 crash)"),
])
|> sort(columns: ["crash_event", "_time"])
|> keep(columns: ["crash_event", "_time", "_value"])
