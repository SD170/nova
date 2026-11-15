#!/bin/bash
# Launch the Nova/Shruti avatar (Electron dev window with hot reload).
# Double-click from Finder or alias into your shell:
#   alias nova="~/Desktop/south\\ park/Hackathons/devhacks2026/drafts/shruti/app/launch.sh"
#
# Stops any prior vite/electron on :5173, then starts fresh.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# kill prior instances (vite dev server + electron) so we don't double-stack mics
lsof -ti :5173 | xargs -r kill 2>/dev/null || true
pkill -f "electron .$" 2>/dev/null || true

[ -d node_modules ] || npm install
[ -f .env ] || { echo "no .env — copy from .env.example and paste VAPI keys"; exit 1; }

exec npm run dev
