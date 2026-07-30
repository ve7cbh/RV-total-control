#!/bin/bash
# set_imu_heading.sh — thin wrapper around set_imu_heading.py.
#
# Usage:
#   ./set_imu_heading.sh 137
#       (137 = the vehicle's current true heading in degrees)
#
# The real logic lives in the Python script -- this just gives you a plain
# command to run, matching the "simple script" framing rather than typing
# `python3 /full/path/...` every time.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <current_true_heading_degrees>"
    exit 1
fi

python3 "${SCRIPT_DIR}/set_imu_heading.py" "$1"
