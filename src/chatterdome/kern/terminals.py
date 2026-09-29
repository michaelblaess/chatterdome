"""Welche Terminals es gibt und wie man in ihnen etwas startet.

Bewusst getrennt vom Starter: Was auf einem Rechner ueberhaupt vorhanden ist,
ist eine Eigenschaft des Rechners und wird auch vom Einstellungsdialog
gebraucht - der soll nur anbieten, was es hier wirklich gibt.

DIE VORBEREITUNGSBEFEHLE LAUFEN UEBER EINE DATEI, nicht ueber die
Befehlszeile. Der Grund ist Michaels Anwendungsfall: auf dem Firmenrechner
stehen vor dem Start mehrere Zeilen Proxy-Einrichtung. Solche Zeilen enthalten
Anfuehrungszeichen, Gleichheitszeichen und Klammern, und sie muessten sonst
durch zwei Shells hindurch heil bleiben - erst die des Terminals, dann die des
Interpreters. Genau daran ist hier schon ein PowerShell-Aufruf ueber ssh
zerbrochen. Eine Datei kennt dieses Problem nicht.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

AUTOMATISCH = "auto"
"""Schluessel fuer "nimm das erste, das da ist"."""


@dataclass(frozen=True, slots=True)
class Terminal:
    """Ein Terminalprogramm und wie es eine Datei ausfuehrt."""

    schluessel: str
    name: str
    programm: str
    """Ausfuehrbare Datei, die im PATH gesucht wird."""

    system: str
    """``win32``, ``linux`` oder ``darwin``."""

    fenster: bool = True
    """Ob das Terminal ein Fenster oeffnet und dafuer eine Anzeige braucht."""

    @property
    def vorhanden(self) -> bool:
        """Wahr, wenn das Programm auf diesem Rechner gefunden wird."""
        if self.system != sys.platform:
            return False
        return shutil.which(self.programm) is not None


# Reihenfolge = Vorzug bei "automatisch". Windows Terminal steht vorn, weil es
# den Tab an ein bestehendes Fenster haengen kann statt ein neues zu oeffnen.
TERMINALS: tuple[Terminal, ...] = (
    Terminal("wt", "Windows Terminal", "wt", "win32"),
    Terminal("wezterm", "WezTerm", "wezterm", "win32"),
    Terminal("pwsh", "PowerShell 7", "pwsh", "win32"),
    Terminal("powershell", "Windows PowerShell", "powershell", "win32"),
    Terminal("cmd", "Eingabeaufforderung", "cmd", "win32"),
    Terminal("gnome-terminal", "GNOME Terminal", "gnome-terminal", "linux"),
    Terminal("konsole", "Konsole", "konsole", "linux"),
    Terminal("wezterm-linux", "WezTerm", "wezterm", "linux"),
    Terminal("alacritty", "Alacritty", "alacritty", "linux"),
    Terminal("kitty", "kitty", "kitty", "linux"),
    Terminal("xfce4-terminal", "Xfce Terminal", "xfce4-terminal", "linux"),
    Terminal("xterm", "xterm", "xterm", "linux"),
    # Ohne Fenster: der Agent laeuft in einer tmux-Sitzung im Hintergrund. Steht
    # hinten, damit mit Anzeige weiterhin ein echtes Fenster aufgeht.
    Terminal("tmux", "tmux", "tmux", "linux", fenster=False),
    Terminal("terminal-app", "Terminal", "open", "darwin"),
)


def anzeige_vorhanden() -> bool:
    """Ob ein Terminalfenster ueberhaupt aufgehen kann.

    Nur unter Linux eine Frage: ohne ``DISPLAY`` oder ``WAYLAND_DISPLAY`` - etwa in
    einem systemd-Dienst - gibt es keinen Bildschirm dafuer.
    """
    if sys.platform != "linux":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def verfuegbare() -> list[Terminal]:
    """Alle Terminals, die auf diesem Rechner tatsaechlich installiert sind."""
    return [t for t in TERMINALS if t.vorhanden]


def auswahl() -> list[tuple[str, str]]:
    """Eintraege fuer das Auswahlfeld: (Beschriftung, Schluessel)."""
    return [(t.name, t.schluessel) for t in verfuegbare()]


def finde(schluessel: str) -> Terminal | None:
    """Das Terminal zu einem Schluessel, oder None bei "automatisch"."""
    if not schluessel or schluessel == AUTOMATISCH:
        gefunden = verfuegbare()
        # Ohne Anzeige kann kein Fenster aufgehen - dann nur, was keins braucht.
        # Sonst startet der Browser-Zugang auf senza (Dienst ohne DISPLAY) ein
        # gnome-terminal, das still scheitert (Michaels Test am 15.09.2026).
        if not anzeige_vorhanden():
            gefunden = [t for t in gefunden if not t.fenster]
        return gefunden[0] if gefunden else None
    for kandidat in TERMINALS:
        if kandidat.schluessel == schluessel:
            return kandidat if kandidat.vorhanden else None
    return None


def startdatei(zeilen: list[str], ordner: str, endbefehl: list[str],
               powershell: bool = False) -> Path:
    """Schreibt ein Startskript und gibt dessen Pfad zurueck.

    :param zeilen:
        Vorbereitungsbefehle, eine je Zeile. Duerfen leer sein.
    :param ordner:
        Arbeitsverzeichnis, in das vor allem anderen gewechselt wird.
    :param endbefehl:
        Der eigentliche Startbefehl als Argumentliste.
    :param powershell:
        Wahr, wenn das Zielterminal PowerShell ist. Dann wird eine .ps1 mit
        PowerShell-Syntax geschrieben (``powershell -File`` lehnt eine .cmd ab),
        und die Vorbereitungsbefehle muessen ohnehin PowerShell sein.
    :returns:
        Pfad der erzeugten Datei. Jeder Aufruf bekommt eine eigene: bis
        28.09.2026 hiess sie immer ``start.cmd``, und drei Starts kurz
        hintereinander oeffneten dreimal den letzten Agenten - das Terminal
        liest die Datei erst, wenn der naechste Aufruf sie schon ueberschrieben
        hat. Dateien aelter als einen Tag raeumt der naechste Aufruf weg.
    """
    ordner_ = Path(tempfile.gettempdir()) / "chatterdome"
    ordner_.mkdir(parents=True, exist_ok=True)
    _alte_startdateien_weg(ordner_)

    if sys.platform == "win32" and powershell:
        pfad = _neue_startdatei(ordner_, ".ps1")
        start = "& " + " ".join(_zitat_ps(teil) for teil in endbefehl)
        inhalt = [f"Set-Location -LiteralPath {_zitat_ps(ordner)}", *zeilen, start]
        # BOM (utf-8-sig), damit PowerShell 5.1 Sonderzeichen richtig liest.
        # newline="": die Zeilenenden stehen schon im String. Ohne das macht
        # der Textmodus unter Windows aus jedem \r\n ein \r\r\n.
        pfad.write_text("\r\n".join(inhalt) + "\r\n", encoding="utf-8-sig", newline="")
        return pfad

    if sys.platform == "win32":
        pfad = _neue_startdatei(ordner_, ".cmd")
        start = " ".join(_zitat_win(teil) for teil in endbefehl)
        inhalt = ["@echo off", f'cd /d "{ordner}"', *zeilen, start]
        # newline="" wie oben - sonst landet \r\r\n in der .cmd.
        pfad.write_text("\r\n".join(inhalt) + "\r\n", encoding="utf-8", newline="")
        return pfad

    pfad = _neue_startdatei(ordner_, ".sh")
    inhalt = ["#!/usr/bin/env bash", f'cd "{ordner}" || exit 1', *zeilen,
              " ".join(_zitat_posix(t) for t in endbefehl)]
    # newline="\n": eine .sh vertraegt kein CRLF, auch nicht wenn sie
    # ausnahmsweise unter Windows erzeugt wird.
    pfad.write_text("\n".join(inhalt) + "\n", encoding="utf-8", newline="\n")
    pfad.chmod(pfad.stat().st_mode | stat.S_IXUSR)
    return pfad


def _neue_startdatei(ordner: Path, endung: str) -> Path:
    """Legt eine leere Startdatei mit eindeutigem Namen an."""
    kennung, pfad = tempfile.mkstemp(prefix="start-", suffix=endung, dir=ordner)
    os.close(kennung)
    return Path(pfad)


def _alte_startdateien_weg(ordner: Path, alter_sekunden: float = 86400.0) -> None:
    """Loescht Startdateien, die kein Terminal mehr braucht."""
    grenze = time.time() - alter_sekunden
    for datei in ordner.glob("start*.*"):
        try:
            if datei.stat().st_mtime < grenze:
                datei.unlink()
        except OSError:
            # Gerade von einem Terminal geoeffnet oder schon weg - beides egal.
            continue


def _zitat_win(text: str) -> str:
    """Setzt ein Argument fuer cmd in Anfuehrungszeichen, wenn noetig."""
    return f'"{text}"' if not text or " " in text else text


def _zitat_ps(text: str) -> str:
    """Setzt ein Argument fuer PowerShell in einfache Anfuehrungszeichen.

    In PowerShell wird ein einzelnes Anfuehrungszeichen durch Verdopplung
    maskiert. Einfache Quotes verhindern jede Variablen-Ersetzung.
    """
    return "'" + text.replace("'", "''") + "'"


def _zitat_posix(text: str) -> str:
    """Minimales Quoting fuer die Shell-Zeile."""
    if not text or any(zeichen in text for zeichen in " \t\"'$`\\"):
        return "'" + text.replace("'", "'\\''") + "'"
    return text


def ist_powershell(schluessel: str) -> bool:
    """Wahr, wenn der Terminal-Schluessel eine PowerShell meint."""
    return schluessel in _POWERSHELL_TERMINALS


_POWERSHELL_TERMINALS = frozenset({"pwsh", "powershell"})


def vorbereitung(werte: Mapping[str, object], powershell: bool = False) -> list[str]:
    """Setzt die Vorbereitungsschritte aus den Einstellungen zusammen.

    Skript zuerst, dann die einzelnen Zeilen - so kann ein hinterlegtes
    Skript die Grundlage legen und eine Zeile darueber noch etwas aendern.
    Es ist bewusst kein Entweder-Oder: beides zusammen zu erlauben kostet
    nichts und erspart die Frage, welches von beidem gewinnt.

    :param powershell:
        Wahr fuer ein PowerShell-Zielterminal - dann wird ein hinterlegtes
        Skript in PowerShell-Syntax aufgerufen.
    """
    schritte: list[str] = []
    skript = str(werte.get("terminal_skript", "")).strip()
    if skript:
        schritte.append(_skriptaufruf(skript, powershell))
    roh = str(werte.get("terminal_vorbereitung", ""))
    schritte.extend(z for z in (zeile.rstrip() for zeile in roh.splitlines()) if z.strip())
    return schritte


def _skriptaufruf(pfad: str, powershell: bool = False) -> str:
    """Baut die Zeile, die ein hinterlegtes Skript ausfuehrt."""
    if sys.platform == "win32":
        if powershell:
            # In PowerShell ruft der Call-Operator jede Datei auf; .cmd/.bat
            # laufen ueber cmd, .ps1 direkt.
            if pfad.lower().endswith((".cmd", ".bat")):
                return f"& cmd /c {_zitat_ps(pfad)}"
            return f"& {_zitat_ps(pfad)}"
        # call fuer .cmd/.bat, sonst kehrt die Steuerung nicht zurueck und
        # der eigentliche Start unterbleibt.
        if pfad.lower().endswith((".cmd", ".bat")):
            return f'call "{pfad}"'
        if pfad.lower().endswith(".ps1"):
            return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{pfad}"'
        return f'"{pfad}"'
    return f". {_zitat_posix(pfad)}"
