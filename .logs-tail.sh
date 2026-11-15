#!/bin/bash
# Tail all Nova/Shruti service logs into one place.
# Each subprocess writes to ~/Desktop/south\ park/Hackathons/devhacks2026/.logs/
set -e
REPO="/Users/sd17/Desktop/south park/Hackathons/devhacks2026"
LOGS="$REPO/.logs"
mkdir -p "$LOGS"

echo "=== Nova service log aggregator starting $(date '+%H:%M:%S') ==="
echo "  bridge:  $LOGS/bridge.log"
echo "  tunnel:  $LOGS/tunnel.log"
echo "  canvas:  $LOGS/canvas.log"
echo "  nova:    $LOGS/nova-electron.log  (macOS Console → launch Nova.app with this script instead of double-click to capture)"
echo

# Follow all the logs that exist. Missing ones get a placeholder so tail -f doesn't bail.
for f in bridge tunnel canvas nova-electron; do
  [ -f "$LOGS/$f.log" ] || echo "(no $f log yet — service may not be writing here)" > "$LOGS/$f.log"
done

exec tail -F "$LOGS/bridge.log" "$LOGS/tunnel.log" "$LOGS/canvas.log" "$LOGS/nova-electron.log"
