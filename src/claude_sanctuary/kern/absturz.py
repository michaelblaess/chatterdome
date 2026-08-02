"""Protokoll ueber Abstuerze und Sitzungsgrenzen.

WARUM DAS NOETIG IST: Der CrashGuard zeigt einen Traceback nur im Dialog.
Bleibt der Dialog aus, ist der Absturz nicht mehr nachvollziehbar - und genau
das ist am 02.08.2026 passiert.

Der entscheidende Teil ist die SITZUNGSKLAMMER, nicht der Traceback. Jeder
Start schreibt eine Zeile, jedes regulaere Ende ebenfalls. Damit lassen sich
drei Faelle unterscheiden, die vorher alle gleich aussahen:

- Startzeile, Traceback, Endzeile  -> Python-Fehler, die App hat ihn gesehen
- Startzeile, Endzeile             -> sauber beendet
- Startzeile, dann NICHTS          -> der Prozess wurde hart abgeraeumt

Ein Signalhandler allein wuerde den dritten Fall NICHT sehen: unter Windows
beendet ``process.kill(pid, 'SIGTERM')`` den Prozess ueber TerminateProcess,
und das liefert dem Ziel kein Signal, das man abfangen koennte. Die fehlende
Endzeile ist dort der einzige Beleg.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import platform
import signal
import traceback
from datetime import datetime
from types import FrameType

from claude_sanctuary.kern.einstellungen import VERZEICHNIS

PROTOKOLL = VERZEICHNIS / "fault.log"
"""Sammeldatei. Bewusst EINE Datei und kein Ordner voller Berichte - gesucht
wird darin immer von hinten, und ein Verzeichnis mit hundert Einzeldateien
beantwortet die Frage "was war beim letzten Mal" schlechter."""

GRENZE = 256 * 1024
"""Ab dieser Groesse wird vorn gekuerzt. Ohne Grenze waechst die Datei
unbemerkt weiter - ein Protokoll, das niemand aufraeumt, raeumt sich selbst."""

_offen = False
"""Wahr zwischen Start- und Endzeile. Verhindert eine Endzeile ohne Start,
wenn ``beobachte`` nie gelaufen ist (etwa im Test)."""


def notiere(anlass: str, text: str = "") -> None:
    """Haengt einen Eintrag mit Zeitstempel an das Protokoll an.

    :param anlass:
        Kurzwort fuer die Art des Eintrags, erscheint in der Kopfzeile.
    :param text:
        Ausfuehrliche Angaben, etwa ein Traceback. Darf leer bleiben.
    """
    with contextlib.suppress(OSError):
        PROTOKOLL.parent.mkdir(parents=True, exist_ok=True)
        _kuerzen()
        stempel = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        kopf = f"[{stempel}] {anlass} (PID {os.getpid()}, {platform.node()})\n"
        with PROTOKOLL.open("a", encoding="utf-8") as datei:
            datei.write(kopf + (f"{text.rstrip()}\n" if text else ""))


def _kuerzen() -> None:
    """Wirft die aeltere Haelfte weg, wenn die Datei zu gross geworden ist."""
    with contextlib.suppress(OSError):
        if not PROTOKOLL.exists() or PROTOKOLL.stat().st_size <= GRENZE:
            return
        inhalt = PROTOKOLL.read_text(encoding="utf-8", errors="replace")
        rest = inhalt[len(inhalt) // 2 :]
        # Erst ab der naechsten Kopfzeile weiterschreiben, sonst beginnt die
        # Datei mitten in einem Traceback.
        schnitt = rest.find("\n[")
        PROTOKOLL.write_text(rest[schnitt + 1 :] if schnitt >= 0 else rest, encoding="utf-8")


def absturz(fehler: BaseException) -> None:
    """Schreibt einen vollstaendigen Traceback ins Protokoll."""
    bericht = "".join(traceback.format_exception(type(fehler), fehler, fehler.__traceback__))
    notiere(f"Absturz: {type(fehler).__name__}", bericht)


def beobachte(version: str) -> None:
    """Klammert den Lauf: Startzeile jetzt, Endzeile beim Beenden.

    :param version:
        Programmversion, damit spaeter erkennbar ist, welcher Stand lief.
    """
    global _offen

    if _offen:
        return
    _offen = True
    notiere(f"Start v{version}")
    atexit.register(_ende, "regulaer beendet")

    # Auf Linux und macOS traegt das echte Erkenntnis: dort liefert ein
    # Abschuss tatsaechlich ein Signal. Unter Windows laeuft es meist ins
    # Leere - schaden kann es nicht, und senza ist ein Linux-Rechner.
    for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        nummer = getattr(signal, name, None)
        if nummer is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            signal.signal(nummer, _signal_handler)


def _signal_handler(nummer: int, _rahmen: FrameType | None) -> None:
    """Haelt fest, dass der Lauf von aussen abgebrochen wurde."""
    name = signal.Signals(nummer).name if nummer in set(signal.Signals) else str(nummer)
    _ende(f"durch {name} beendet")
    # Nicht weiterlaufen lassen: wer ein Signal schickt, will das Ende. Der
    # Exit-Code folgt der ueblichen Zaehlung 128 plus Signalnummer.
    os._exit(128 + nummer)


def _ende(anlass: str) -> None:
    """Schreibt die Endzeile - genau einmal je Lauf."""
    global _offen

    if not _offen:
        return
    _offen = False
    notiere(anlass)
