#!/usr/bin/env bash
# Startet die Chatterdome-Oberflaeche aus dem Quellcode.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$root/.venv/bin/python" ]; then
    python="$root/.venv/bin/python"
else
    python="python3"
fi

exec "$python" -m chatterdome "$@"
