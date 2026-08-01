"""Anbindung an den Kurzbefehl ``sanctuary``.

WARUM UEBER EINEN UNTERPROZESS UND NICHT DIREKT AUF DIE DATENBANK: Der Bus
wird ausschliesslich von Node beschrieben. Der Kommentarkopf von
``speicher.mjs`` haelt die Messung fest, die dazu gefuehrt hat - acht parallele
Schreiber, reines Node ohne Verlust, reines Python 240 von 3.200 Zeilen weg.
Solange die Uebergangsphase laeuft und zusaetzlich in die alten JSONL-Dateien
geschrieben wird, bleibt Node der einzige Schreiber.

Nebeneffekt: die Schnittstelle ist bereits die, die spaeter eine REST-Fassung
bekommt - Kommando rein, JSON raus.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from claude_sanctuary.kern.modelle import Agent, Auftrag, Bestand, Ereignis

ZEITGRENZE = 25.0
"""Sekunden. Eine Mesh-Abfrage ueber SSH braucht spuerbar laenger als eine lokale."""


def _repo_wurzel() -> Path:
    """Wurzel des Sanctuary-Repos, ausgehend von dieser Datei."""
    return Path(__file__).resolve().parents[3]


def finde_befehl() -> list[str]:
    """Ermittelt, wie ``sanctuary`` aufzurufen ist.

    Erst der Kurzbefehl aus dem PATH, sonst der Direktaufruf ueber node. Der
    Rueckfall ist noetig, weil ``~/.local/bin`` in einer nicht-interaktiven
    Shell fehlen kann - genau die Falle, die auch beim Mesh-Aufruf zuschlaegt.
    """
    kurz = shutil.which("sanctuary")
    if kurz:
        return [kurz]
    skript = _repo_wurzel() / "bin" / "sanctuary.mjs"
    node = shutil.which("node") or "node"
    return [node, str(skript)]


class LokaleQuelle:
    """Fragt den Kurzbefehl auf diesem Rechner ab."""

    def __init__(self, befehl: list[str] | None = None) -> None:
        self._befehl = befehl if befehl is not None else finde_befehl()

    # -- oeffentlich ----------------------------------------------------

    def bestand(self, *, mesh: bool = False) -> Bestand:
        args = ["status", "--json"]
        if mesh:
            args.append("--mesh")
        roh, fehler = self._json(args)
        if roh is None:
            return Bestand(rechner=_rechnername(), zeit="", fehler=[fehler])
        return self._bestand_aus(roh)

    @staticmethod
    def _bestand_aus(roh: dict[str, Any]) -> Bestand:
        """Liest beide Ausgabeformate des Operators.

        ACHTUNG, die beiden unterscheiden sich grundlegend:

        - lokal: ``{rechner: "NAME", zeit, instanzen: [...]}``
        - mesh:  ``{zeit, rechner: [{host, rechner, instanzen, fehler}]}``

        Bei Mesh ist ``rechner`` also eine Liste und ``instanzen`` fehlt oben
        ganz. Wer nur den lokalen Fall liest, bekommt im Mesh-Betrieb still
        eine leere Liste - genau das ist passiert.
        """
        zeit = str(roh.get("zeit", ""))
        zweige = roh.get("rechner")

        if isinstance(zweige, list):
            agenten: list[Agent] = []
            probleme: list[str] = []
            for zweig in zweige:
                name = str(zweig.get("rechner") or zweig.get("host") or "?")
                agenten.extend(
                    LokaleQuelle._agent(e, name) for e in zweig.get("instanzen", [])
                )
                if zweig.get("fehler"):
                    probleme.append(f"{zweig.get('host', name)}: {zweig['fehler']}")
            return Bestand(rechner=_rechnername(), zeit=zeit, agenten=agenten, fehler=probleme)

        hier = str(zweige or _rechnername())
        return Bestand(
            rechner=hier,
            zeit=zeit,
            agenten=[LokaleQuelle._agent(e, hier) for e in roh.get("instanzen", [])],
            fehler=[str(p) for p in roh.get("fehler", []) if p],
        )

    def verlauf(self, name: str) -> list[Auftrag]:
        roh, _fehler = self._json(["verlauf", name, "--json"])
        if roh is None:
            return []
        return [self._auftrag(e) for e in roh.get("auftraege", [])]

    def senden(self, an: str, text: str, *, topic: str = "", quittung: bool = False) -> str:
        args = ["send", an, text]
        if topic:
            args += ["--topic", topic]
        if quittung:
            args.append("--erwartet-quittung")
        return self._still(args)

    def stoppen(self, name: str) -> str:
        # --ja unterdrueckt die Rueckfrage; die Oberflaeche hat vorher gefragt.
        return self._still(["stop", name, "--ja"])

    # -- intern ---------------------------------------------------------

    def _json(self, args: list[str]) -> tuple[dict[str, Any] | None, str]:
        """Fuehrt ein Kommando aus und liest dessen JSON-Ausgabe."""
        try:
            lauf = subprocess.run(  # fester Befehl, keine Shell
                [*self._befehl, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=ZEITGRENZE,
                check=False,
            )
        except FileNotFoundError:
            return None, f"Befehl nicht gefunden: {' '.join(self._befehl)}"
        except subprocess.TimeoutExpired:
            return None, f"Zeitueberschreitung nach {ZEITGRENZE:.0f} s"

        if lauf.returncode != 0:
            meldung = (lauf.stderr or lauf.stdout or "").strip().splitlines()
            return None, meldung[0] if meldung else f"Exit-Code {lauf.returncode}"
        try:
            return json.loads(lauf.stdout), ""
        except json.JSONDecodeError as fehler:
            return None, f"Antwort ist kein JSON: {fehler}"

    def _still(self, args: list[str]) -> str:
        """Fuehrt ein Kommando aus, dessen Ausgabe nicht gebraucht wird."""
        try:
            lauf = subprocess.run(  # fester Befehl, keine Shell
                [*self._befehl, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=ZEITGRENZE,
                check=False,
            )
        except FileNotFoundError:
            return f"Befehl nicht gefunden: {' '.join(self._befehl)}"
        except subprocess.TimeoutExpired:
            return f"Zeitueberschreitung nach {ZEITGRENZE:.0f} s"
        if lauf.returncode != 0:
            meldung = (lauf.stderr or lauf.stdout or "").strip().splitlines()
            return meldung[0] if meldung else f"Exit-Code {lauf.returncode}"
        return ""

    @staticmethod
    def _agent(e: dict[str, Any], hier: str) -> Agent:
        return Agent(
            name=str(e.get("name", "?")),
            status=str(e.get("status", "")),
            rechner=str(e.get("rechner", hier)),
            pid=e.get("pid"),
            session_id=str(e.get("sessionId", "")),
            selbst=bool(e.get("selbst", False)),
            laufzeit_ms=int(e.get("laufzeit") or 0),
            gespraech_ms=int(e.get("gespraech") or 0),
            fortgesetzt=bool(e.get("fortgesetzt", False)),
            post=int(e.get("post") or 0),
            kontext=int(e.get("kontext") or 0),
            tokens=int(e.get("tokens") or 0),
            cache_gelesen=int(e.get("cacheGelesen") or 0),
            modell=e.get("modell"),
            letztes_tool=e.get("letztesTool"),
            aufgabe=e.get("aufgabe"),
            cwd=str(e.get("cwd") or ""),
            nach_compact=bool(e.get("nachCompact", False)),
            erreichbar=bool(e.get("erreichbar", True)),
        )

    @staticmethod
    def _auftrag(e: dict[str, Any]) -> Auftrag:
        verlauf = [
            Ereignis(
                art="auftrag",
                ts=str(e.get("erstellt", "")),
                von=str(e.get("von", "")),
                an=str(e.get("an", "")),
                text=str(e.get("text", "")),
                zustand=str(e.get("zustand", "")),
            )
        ]
        for q in e.get("quittungen", []):
            verlauf.append(
                Ereignis(
                    art="quittung",
                    ts=str(q.get("ts", "")),
                    von=str(q.get("von", "")),
                    an=str(q.get("an", "")),
                    text=str(q.get("notiz") or ""),
                    zustand=str(q.get("zustand", "")),
                    status=q.get("status"),
                    notiz=str(q.get("notiz") or ""),
                )
            )
        return Auftrag(
            auftrag_id=str(e.get("auftrag_id", "")),
            zustand=str(e.get("zustand", "")),
            von=str(e.get("von", "")),
            an=str(e.get("an", "")),
            topic=str(e.get("topic", "")),
            text=str(e.get("text", "")),
            erstellt=str(e.get("erstellt", "")),
            geaendert=str(e.get("geaendert", "")),
            quittung_erwartet=bool(e.get("quittung_erwartet")),
            verlauf=verlauf,
        )


def _rechnername() -> str:
    """Name dieses Rechners - nur als Rueckfall, wenn die Abfrage scheitert."""
    return platform.node() or "?"
