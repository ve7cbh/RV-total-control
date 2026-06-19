#!/bin/bash
# KWS relay board test — cycles all 8 coils ON/OFF two at a time
# Waveshare 8-ch RS-485 relay board — 192.168.88.12, port 4001, slave 1
# Usage: ./relay_test.sh [delay_seconds]   default delay = 1s

HOST="192.168.88.12"
PORT="4001"
SLAVE="1"
DELAY="${1:-1}"

mbp() {
  local coil=$1
  local val=$2
  mbpoll -m tcp -a "$SLAVE" -p "$PORT" -t 0 -r "$coil" "$HOST" -- "$val" > /dev/null 2>&1
}

all_off() {
  for c in 1 2 3 4 5 6 7 8; do mbp "$c" 0; done
}

echo "================================================"
echo " Waveshare 8-ch Relay Board — Cycle Test"
echo " Host: $HOST  Port: $PORT  Slave: $SLAVE"
echo " Delay between steps: ${DELAY}s"
echo " Ctrl-C to abort"
echo "================================================"
echo

# Make sure we start clean
echo "Clearing all relays..."
all_off
sleep "$DELAY"

PAIRS=("1 2" "3 4" "5 6" "7 8")

for PASS in 1 2; do
  echo "--- Pass $PASS ---"
  for PAIR in "${PAIRS[@]}"; do
    read -r A B <<< "$PAIR"
    echo "  ON  → coils $A and $B"
    mbp "$A" 1
    mbp "$B" 1
    sleep "$DELAY"

    echo "  OFF → coils $A and $B"
    mbp "$A" 0
    mbp "$B" 0
    sleep "$DELAY"
  done
  echo
done

echo "All relays off — test complete."
all_off
