#!/usr/bin/env bash
# Baut die Sanctuary-Oberflaeche zu einer eigenstaendigen macOS-Binary.
#
# Voraussetzung: Xcode Command Line Tools (xcode-select --install).
# Kein .app-Bundle - das hier ist ein Terminalprogramm.
#
# Die Architektur haengt an der Baumaschine: ein Build auf Apple Silicon
# laeuft NICHT auf Intel (Rosetta uebersetzt nur in die andere Richtung).
# Deshalb steht sie im Archivnamen.
#
# Ergebnis: dist/claude-sanctuary/sanctuary-tui
#           dist/claude-sanctuary-vX.Y.Z-macos-<arch>.tar.gz
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
entry="$root/src/claude_sanctuary/__main__.py"
init_py="$root/src/claude_sanctuary/__init__.py"
out_dir="$root/dist"
dist_dir="$out_dir/claude-sanctuary"

command -v clang >/dev/null 2>&1 || {
    echo "Fehlt: clang (xcode-select --install)" >&2
    exit 1
}

version="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' "$init_py")"
[ -n "$version" ] || { echo "Konnte __version__ nicht aus $init_py lesen" >&2; exit 1; }

if command -v uv >/dev/null 2>&1; then
    echo "Gleiche die Umgebung mit uv.lock ab..."
    uv sync --extra dev --inexact --project "$root"
fi

if [ -x "$root/.venv/bin/python" ]; then
    python="$root/.venv/bin/python"
else
    python="python3"
fi

if ! "$python" -m nuitka --version >/dev/null 2>&1; then
    echo "Nuitka fehlt in der Umgebung - installiere..."
    uv pip install --python "$python" nuitka
fi

echo "Kompiliere claude-sanctuary v$version..."
rm -rf "$dist_dir"
started=$(date +%s)

nuitka_args=(
    --standalone
    --assume-yes-for-downloads
    --remove-output
    --include-package=claude_sanctuary
    --include-package-data=claude_sanctuary
    --include-package=textual_image
    --output-dir="$out_dir"
    --output-filename=sanctuary-tui
)

# Nuitka will hier ein natives .icns - ein PNG laesst es mit "Need to
# install 'imageio'" abbrechen. Fehlt die Datei, wird ohne Symbol gebaut.
if [ -f "$root/assets/icon.icns" ]; then
    nuitka_args+=(--macos-app-icon="$root/assets/icon.icns")
fi

"$python" -m nuitka "${nuitka_args[@]}" "$entry"

[ -d "$out_dir/__main__.dist" ] && mv "$out_dir/__main__.dist" "$dist_dir"

echo "Selbsttest..."
ausgabe="$("$dist_dir/sanctuary-tui" --version 2>&1)"
case "$ausgabe" in
    *"$version"*) echo "  $ausgabe" ;;
    *) echo "Selbsttest lieferte '$ausgabe', erwartet wurde $version" >&2; exit 1 ;;
esac

elapsed=$(( $(date +%s) - started ))
arch="$(uname -m)"
tarball="$out_dir/claude-sanctuary-v$version-macos-$arch.tar.gz"
rm -f "$tarball"
tar -czf "$tarball" -C "$out_dir" claude-sanctuary

echo "Fertig in ${elapsed}s"
echo "  Archiv: $tarball"
echo "  Start:  $dist_dir/sanctuary-tui"
echo
echo "Hinweis fuer Empfaenger: nach dem Download einmal"
echo "  xattr -dr com.apple.quarantine sanctuary-tui"
