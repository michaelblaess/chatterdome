#!/usr/bin/env bash
# Richtet die Entwicklungsumgebung fuer die Sanctuary-Oberflaeche ein.
# Mehrfach aufrufbar.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v uv >/dev/null 2>&1 || {
    echo "uv fehlt. Installation: https://docs.astral.sh/uv/" >&2
    exit 1
}

if [ ! -d "$root/.venv" ]; then
    echo "Lege .venv an..."
    uv venv --project "$root"
fi

echo "Installiere Abhaengigkeiten..."
uv pip install --python "$root/.venv/bin/python" -e "$root[dev]"

echo "Fertig. Start mit ./run.sh"
