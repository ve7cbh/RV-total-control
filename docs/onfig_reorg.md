** config folder reorg


This is a job for a fresh mind - not now.  Put this into a note that we will attack tomorrow

Good call — this has grown past "quick reorg" into a real audit (dead rtl_433 service defs, a possibly-broken SNMP path, three untracked reference layers to check). Here's the note for tomorrow:

TODO — config/ directory reorg + cleanup audit

Before moving any files, confirm:

Is SNMP data (Mikrotik/printer/NAS) actually showing in Grafana right now? — none of telegraf_snmp.conf / telegraf_rvtc_snmp.conf / telegraf_snmp_rvtc.conf are mounted in the current docker-compose.yml, so this may be a real gap, not just duplicate files.
Grep roles/ (Ansible) for references to config/ filenames — docker-compose.yml and systemd units aren't the only places a path can be hardcoded; Ansible template/copy tasks could be too.
Confirm safe to delete: the four modbus_*.yaml files (dead since HA's native Modbus was abandoned 2026-06-29 — pymodbus/Waveshare incompatibility) and MQTT-Explorer-Setup-0.4.0-beta.6.exe (installer, not a config).

Also found, separate from the reorg itself:

rtl433/rtl433b service blocks are still fully defined in docker-compose.yml, just unused — a bare docker compose up -d would resurrect them. Delete the blocks, not just leave them dormant.
gps_mqtt.py and relay_test.sh live at the repo root, not in config/ like every other bridge script — decide if they move too.

Proposed subdirectory structure, pending the above:

config/
├── bridges/          # Python Modbus→MQTT scripts + .service units  **  this will be "adaptors/" 
├── telegraf/         # telegraf*.conf
├── homeassistant/    # automations/helpers/scripts/mqtt_sensors/dashboards
├── mikrotik/         # .rsc files, Mikrotik-Failover.md
├── nginx/            # nginx.conf, rvtc_index.html, index.html
├── grafana/          # dashboard JSONs
├── Tank_Mon/         # already exists
├── rvtc-imu/         # already exists
├── i2c/              # already exists
└── docs/             # IMU_config.md, patch instructions, main.pdf

