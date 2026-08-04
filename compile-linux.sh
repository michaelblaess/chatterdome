#!/usr/bin/env bash
# Baut die Sanctuary-Oberflaeche zu einer eigenstaendigen Linux-Binary.
#
# Nuitka --standalone, also ein Ordner statt einer selbstentpackenden Datei.
# Voraussetzungen auf der Baumaschine: gcc, patchelf, python3-dev.
#
# Ergebnis: dist/claude-sanctuary/sanctuary-tui
#           dist/claude-sanctuary-vX.Y.Z-linux-x86_64.tar.gz
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
entry="$root/src/claude_sanctuary/__main__.py"
init_py="$root/src/claude_sanctuary/__init__.py"
out_dir="$root/dist"
dist_dir="$out_dir/claude-sanctuary"

for werkzeug in gcc patchelf; do
    command -v "$werkzeug" >/dev/null 2>&1 || {
        echo "Fehlt: $werkzeug (sudo apt install gcc patchelf python3-dev)" >&2
        exit 1
    }
done

# Portables sed statt 'grep -oP' - BSD-grep kennt kein -P, und dasselbe
# Skript soll auf macOS unveraendert laufen.
version="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' "$init_py")"
[ -n "$version" ] || { echo "Konnte __version__ nicht aus $init_py lesen" >&2; exit 1; }

# VOR der Python-Ermittlung: bei einem frischen Checkout (CI) gibt es noch
# keine .venv, sonst kompiliert Nuitka die falsche Umgebung. --inexact
# laesst zusaetzlich installierte Pakete wie Nuitka selbst stehen.
if command -v uv >/dev/null 2>&1; then
    echo "Gleiche die Umgebung mit uv.lock ab..."
    uv sync --extra dev --inexact --project "$root"
fi

if [ -x "$root/.venv/bin/python" ]; then
    python="$root/.venv/bin/python"
else
    python="python3"
fi

# Nuitka ist Werkzeug, keine Laufzeitabhaengigkeit - bei Bedarf nachziehen.
if ! "$python" -m nuitka --version >/dev/null 2>&1; then
    echo "Nuitka fehlt in der Umgebung - installiere..."
    uv pip install --python "$python" nuitka
fi

echo "Kompiliere claude-sanctuary v$version..."
rm -rf "$dist_dir"
started=$(date +%s)

"$python" -m nuitka \
    --standalone \
    --assume-yes-for-downloads \
    --remove-output \
    --include-package=claude_sanctuary \
    --include-package-data=claude_sanctuary \
    --include-package=textual_image \
    --output-dir="$out_dir" \
    --output-filename=sanctuary-tui \
    "$entry"

# Nuitka benennt den Ordner nach dem Hauptmodul.
[ -d "$out_dir/__main__.dist" ] && mv "$out_dir/__main__.dist" "$dist_dir"

# Selbsttest gegen die FERTIGE Binary: ein gruener Compile beweist nicht,
# dass Sprachdateien und Layout mitgekommen sind.
echo "Selbsttest..."
ausgabe="$("$dist_dir/sanctuary-tui" --version 2>&1)"
case "$ausgabe" in
    *"$version"*) echo "  $ausgabe" ;;
    *) echo "Selbsttest lieferte '$ausgabe', erwartet wurde $version" >&2; exit 1 ;;
esac

elapsed=$(( $(date +%s) - started ))
tarball="$out_dir/claude-sanctuary-v$version-linux-x86_64.tar.gz"
rm -f "$tarball"
# tar statt zip: es bewahrt das Ausfuehrungsrecht der Binary.
tar -czf "$tarball" -C "$out_dir" claude-sanctuary

echo "Fertig in ${elapsed}s"
echo "  Archiv: $tarball"
echo "  Start:  $dist_dir/sanctuary-tui"
