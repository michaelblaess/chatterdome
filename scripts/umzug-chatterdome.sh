#!/usr/bin/env bash
# Umzug claude-sanctuary -> chatterdome auf diesem Rechner (Linux, macOS).
#
# Aufruf aus dem ALTEN Ordner, nachdem der neue Stand gezogen ist:
#   git pull
#   bash scripts/umzug-chatterdome.sh
#
# Vorher Claude-Sitzungen und Sanctuary schliessen, die im Ordner laufen - unter
# Linux geht das Umbenennen zwar trotzdem, die laufenden Prozesse arbeiten dann
# aber mit einem Pfad weiter, den es nicht mehr gibt.
#
# Schritte wie in umzug-chatterdome.ps1: Ordner, Remote, .venv, setup, bootstrap.
# Der Datenordner ~/.claude-sanctuary wird beim ersten Start kopiert, nicht hier.
set -euo pipefail

# Bash haelt die Skriptdatei waehrend des Laufs offen. Unter Windows (Git Bash)
# laesst sich ein Ordner mit offener Datei nicht umbenennen - am 29.09.2026 im
# Probelauf mit "Permission denied" gescheitert. Deshalb erst eine Kopie
# ausserhalb des Repos starten.
if [ -z "${UMZUG_REPO:-}" ]; then
    kopie="$(mktemp)"
    cp "$0" "$kopie"
    UMZUG_REPO="$(cd "$(dirname "$0")/.." && pwd)" exec bash "$kopie" "$@"
fi
repo="$UMZUG_REPO"
eltern="$(dirname "$repo")"
neu="$eltern/chatterdome"

if [ "$(basename "$repo")" != "chatterdome" ]; then
    if [ -e "$neu" ]; then
        echo "Es gibt schon $neu - bitte erst nachsehen, was dort liegt." >&2
        exit 1
    fi
    cd "$eltern"
    mv "$repo" "$neu"
    echo "[OK]   Ordner: $repo -> $neu"
else
    echo "[OK]   Ordner heisst schon chatterdome"
fi

url="$(git -C "$neu" remote get-url origin)"
case "$url" in
    *claude-sanctuary*)
        neue_url="${url//claude-sanctuary/chatterdome}"
        git -C "$neu" remote set-url origin "$neue_url"
        echo "[OK]   Remote: $neue_url"
        ;;
    *) echo "[OK]   Remote: $url" ;;
esac

# Die .venv enthaelt den alten Pfad in ihren Startdateien.
rm -rf "$neu/.venv"
bash "$neu/setup.sh"
bash "$neu/bootstrap.sh"

echo ""
echo "Umzug fertig. Neue Shell oeffnen, dann:"
echo "  cd $neu"
echo "  chatterdome status"
echo "  ./run.sh"
