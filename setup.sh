#!/usr/bin/env bash
# setup.sh - Haengt ~/.claude/skills/<name> auf dieses Repo (Linux/macOS)
#
# Verwendung:
#   git clone https://github.com/michaelblaess/chatterdome.git
#   cd chatterdome && ./setup.sh
#
# Die Skills liegen hier, damit die Anwendung ihr eigenes Repo hat. Fuer Claude
# Code aendert sich nichts: die Symlinks stellen sie an genau der Stelle
# bereit, an der sie vorher lagen, und die Hooks in claude-config zeigen
# unveraendert auf ~/.claude/skills/...
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$HOME/.claude/skills"
mkdir -p "$SKILL_DIR"

verlinke() {
    local name="$1"
    local ziel="$REPO_DIR/skills/$name"
    local link="$SKILL_DIR/$name"

    if [ ! -d "$ziel" ]; then
        echo "[SKIP] $name - Quelle fehlt: $ziel"
        return
    fi

    # Zeigt der Link schon hierher, ist nichts zu tun. Zeigt er woanders hin
    # (etwa noch auf claude-config), wird er ersetzt - das ist der Umzugsfall.
    if [ -L "$link" ]; then
        local alt
        alt="$(readlink "$link")"
        if [ "$alt" = "$ziel" ]; then
            echo "[OK]   $name - zeigt bereits hierher"
            return
        fi
        rm "$link"
        echo "[UM]   $name - war: $alt"
    elif [ -e "$link" ]; then
        # Echtes Verzeichnis: niemals loeschen, nur beiseite legen.
        mv "$link" "$link.vor-chatterdome"
        echo "[!]    $name war ein echtes Verzeichnis - gesichert als $name.vor-chatterdome"
    fi

    ln -s "$ziel" "$link"
    echo "[OK]   $name -> $ziel"
}

echo "Chatterdome - Setup"
echo "========================"
echo "Repo:   $REPO_DIR"
echo "Skills: $SKILL_DIR"
echo ""

verlinke operator
verlinke claude-bus

# --- Kurzbefehl "chatterdome" ins PATH-Verzeichnis ---
#
# Ein Wrapper statt eines Symlinks auf die .mjs: der Symlink wuerde zwar
# funktionieren, aber unter Git Bash auf Windows haengt die Ausfuehrbarkeit
# einer Datei ohne Endung am Shebang - der Wrapper ruft node ausdruecklich auf
# und ist damit ueberall gleich.
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
# "sanctuary" ist der alte Name und bleibt als Alias: andere Rechner rufen ihn
# ueber ssh auf, und deren Stand kann aelter sein als dieser.
for kurz in chatterdome sanctuary; do
    cat > "$BIN_DIR/$kurz" <<WRAPPER
#!/usr/bin/env bash
exec node "$REPO_DIR/bin/chatterdome.mjs" "\$@"
WRAPPER
    chmod +x "$BIN_DIR/$kurz"
    echo "[OK]   $kurz -> $BIN_DIR/$kurz"
done

echo ""
if ! command -v chatterdome >/dev/null 2>&1; then
    echo "HINWEIS: $BIN_DIR liegt nicht im PATH. Ergaenzen mit:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo ""
fi
echo "Fertig. Probe:"
echo "  chatterdome status"
echo "  chatterdome doctor"
