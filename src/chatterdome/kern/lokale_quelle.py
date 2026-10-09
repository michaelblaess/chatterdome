"""Anbindung an den Kurzbefehl ``chatterdome``.

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
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from chatterdome.kern import umgebung
from chatterdome.kern.modelle import (
    Agent,
    Auftrag,
    Bestand,
    Busbestand,
    Ereignis,
    Namenspool,
)

ZEITGRENZE = 25.0
"""Sekunden. Eine Mesh-Abfrage ueber SSH braucht spuerbar laenger als eine lokale."""

UPDATE_GRENZE = 300.0
"""Sekunden fuer die Aktualisierung. Ein Paketmanager laedt herunter, entpackt
und schreibt - mit 25 Sekunden waere jeder zweite Lauf ein falscher Fehlschlag."""


def _repo_wurzel() -> Path:
    """Wurzel des Chatterdome-Repos, ausgehend von dieser Datei."""
    return Path(__file__).resolve().parents[3]


def finde_befehl() -> list[str]:
    """Ermittelt, wie ``chatterdome`` aufzurufen ist.

    Erst der Kurzbefehl aus dem PATH, sonst der Direktaufruf ueber node. Der
    Rueckfall ist noetig, weil ``~/.local/bin`` in einer nicht-interaktiven
    Shell fehlen kann - genau die Falle, die auch beim Mesh-Aufruf zuschlaegt.

    Unter Windows ist der Kurzbefehl ``chatterdome.CMD``, und den nimmt diese
    Funktion NICHT: eine Batch-Datei laeuft ueber cmd.exe, und cmd schneidet
    ein Argument am ersten Zeilenumbruch ab. Belegt am 28.09.2026 - von jedem
    mehrzeiligen Auftrag stand im Bus nur die erste Zeile, bei der Diskussion
    ebenso wie beim Rundruf der Oberflaeche.
    """
    kurz = shutil.which("chatterdome")
    if kurz and not kurz.lower().endswith((".cmd", ".bat")):
        return [kurz]
    skript = _repo_wurzel() / "bin" / "chatterdome.mjs"
    node = shutil.which("node") or "node"
    return [node, str(skript)]


class LokaleQuelle:
    """Fragt den Kurzbefehl auf diesem Rechner ab."""

    def __init__(self, befehl: list[str] | None = None) -> None:
        self._befehl = befehl if befehl is not None else finde_befehl()

    # -- oeffentlich ----------------------------------------------------

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        """Alle sichtbaren Agenten.

        :param tokens:
            Auch den Verbrauch ermitteln. Bewusst abschaltbar: dafuer liest der
            Operator jedes Transkript VOLLSTAENDIG statt nur die letzten Zeilen
            (gemessen 194 ms je Datei gegen 3 ms). Im Sekundentakt waere das
            Verschwendung, deshalb holt die Oberflaeche es nur auf Zuruf.
        """
        args = ["status", "--json"]
        if mesh:
            args.append("--mesh")
        if tokens:
            args.append("--tokens")
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
            systeme: dict[str, str] = {}
            hier = _rechnername().upper()
            eigenes_system = ""
            anmeldung = ""
            claude = ""
            for zweig in zweige:
                name = str(zweig.get("rechner") or zweig.get("host") or "?")
                system = str(zweig.get("system") or "")
                if system:
                    systeme[name] = system
                if name.upper() == hier:
                    eigenes_system = system
                    anmeldung = str(zweig.get("anmeldung") or "")
                    claude = str(zweig.get("claudeVersion") or "")
                agenten.extend(
                    LokaleQuelle._agent(e, name, system) for e in zweig.get("instanzen", [])
                )
                if zweig.get("fehler"):
                    probleme.append(f"{zweig.get('host', name)}: {zweig['fehler']}")
            return Bestand(
                rechner=_rechnername(),
                zeit=zeit,
                agenten=agenten,
                fehler=probleme,
                system=eigenes_system,
                anmeldung=anmeldung,
                claude_version=claude,
                systeme=systeme,
            )

        name = str(zweige or _rechnername())
        system = str(roh.get("system") or "")
        return Bestand(
            rechner=name,
            zeit=zeit,
            agenten=[LokaleQuelle._agent(e, name, system) for e in roh.get("instanzen", [])],
            fehler=[str(p) for p in roh.get("fehler", []) if p],
            system=system,
            anmeldung=str(roh.get("anmeldung") or ""),
            claude_version=str(roh.get("claudeVersion") or ""),
            systeme={name: system} if system else {},
        )

    def namen(self) -> Namenspool:
        roh, _fehler = self._json(["names", "--json"])
        if roh is None:
            return Namenspool()
        return Namenspool(
            motiv=str(roh.get("motiv", "")),
            namen=[str(n) for n in roh.get("namen", [])],
            frei=[str(n) for n in roh.get("frei", [])],
            reserviert=[str(n) for n in roh.get("reserviert", [])],
            vergeben={str(k): str(v) for k, v in (roh.get("vergeben") or {}).items()},
        )

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[Auftrag]:
        befehl = ["history", name, "--json"]
        # Der Name allein genuegt nicht, er wird neu vergeben. Ohne Sitzung
        # stand unter "Charlene" der Verlauf aller frueheren Traeger.
        if session_id:
            befehl += ["--session", session_id]
            if seit:
                befehl += ["--since", seit]
        roh, _fehler = self._json(befehl)
        if roh is None:
            return []
        return [self._auftrag(e) for e in roh.get("auftraege", [])]

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        """Alles, was im Bus dieses Rechners liegt.

        Bewusst ein eigener Befehl und nicht ``verlauf`` mit leerem Namen: die
        Frage "was liegt ueberhaupt im Bus" beantwortet keine Sicht, die vorher
        einen Gespraechspartner verlangt.
        """
        befehl = ["log", "--json"]
        if grenze > 0:
            befehl += ["--limit", str(grenze)]
        roh, fehler = self._json(befehl)
        if roh is None:
            return Busbestand(fehler=fehler or "")
        return Busbestand(
            rechner=str(roh.get("rechner", "")),
            zeit=str(roh.get("zeit", "")),
            verfall_stunden=int(roh.get("verfall_stunden") or 0),
            auftraege=[self._auftrag(e) for e in roh.get("auftraege", [])],
        )

    def senden(
        self,
        an: str,
        text: str,
        *,
        topic: str = "",
        quittung: bool = False,
        host: str = "",
        von: str = "",
    ) -> str:
        """Legt einen Auftrag ab.

        :param host:
            Rechner des Empfaengers. Ohne die Angabe muss der Bus ihn ueber
            eine Mesh-Abfrage suchen - gemessen 1,4 s gegenueber 0,1 s.
            Die Oberflaeche kennt ihn aus der Tabelle und gibt ihn deshalb mit.
        :param von:
            Absendername. Noetig, weil die Oberflaeche keine Claude-Sitzung
            ist: ohne CLAUDE_CODE_SESSION_ID stand als Absender "unbekannt".
        """
        args = ["send", an, text]
        if topic:
            args += ["--topic", topic]
        if host:
            args += ["--host", host]
        if von:
            args += ["--from", von]
        if quittung:
            args.append("--expect-receipt")
        return self._still(args)

    def senden_mit_kennung(
        self, an: str, text: str, *, topic: str = "", host: str = "", von: str = ""
    ) -> tuple[str, str]:
        """Legt einen Auftrag mit Quittungswunsch ab und liefert dessen Kennung.

        Wer auf die Antwort warten will, braucht die Kennung - ``senden``
        verwirft die Ausgabe. Der Bus nennt sie in der Erfolgszeile als
        ``(id <kennung>)``, eine JSON-Ausgabe hat ``send`` nicht.

        :returns: ``(kennung, "")`` bei Erfolg, sonst ``("", grund)``.
        """
        args = ["send", an, text, "--expect-receipt"]
        if topic:
            args += ["--topic", topic]
        if host:
            args += ["--host", host]
        if von:
            args += ["--from", von]
        lauf, fehler = self._lauf(args)
        if lauf is None:
            return "", fehler
        ausgabe = _ohne_farbe(lauf.stdout)
        treffer = re.search(r"\(id ([0-9a-zA-Z_-]+)\)", ausgabe)
        if treffer is None:
            return "", f"Keine Auftragskennung in der Antwort: {ausgabe.strip()[:200]}"
        return treffer.group(1), ""

    def stoppen(self, name: str) -> str:
        # --force unterdrueckt die Rueckfrage; die Oberflaeche hat vorher
        # gefragt. Hier stand einmal "--ja", das der Operator nicht kennt -
        # er stellte die Rueckfrage dann trotzdem und las sie vom Terminal
        # der Oberflaeche. Beleg und Absicherung siehe _lauf().
        return self._still(["stop", name, "--force"])

    def neustarten_fern(self, rechner: str, session_id: str, cwd: str = "") -> str:
        """Setzt eine Sitzung auf einem ANDEREN Rechner in einem Fenster fort.

        Lokal macht das die Oberflaeche selbst ueber starte_resume, weil sie
        dort die Terminalwahl des Anwenders kennt. Ueber Rechnergrenzen geht es
        nur ueber das dortige CLI: ein Fenster braucht einen Desktop, und den
        hat eine ssh-Sitzung nicht (Einzelheiten in skills/operator/neustart.mjs).

        Der Aufruf dauert - er wartet auf die Rueckmeldung des Zielrechners -
        und gehoert deshalb in einen Thread.

        :returns: Leer bei Erfolg, sonst der Grund.
        """
        if not session_id:
            # Kein t() hier: der Kern bleibt UI-frei. Derselbe Wortlaut wie im
            # CLI, damit beide Wege dasselbe sagen.
            return "Ohne Sitzungskennung gibt es nichts fortzusetzen."
        args = ["restart", "--session", session_id, "--host", rechner]
        if cwd:
            args += ["--cwd", cwd]
        return self._still(args)

    def bildschirmfoto(self, rechner: str = "") -> tuple[str, str]:
        """Nimmt den Bildschirm eines Rechners auf.

        Ohne Rechnernamen den eigenen. Der Aufruf dauert - lokal unter einer
        Sekunde, ueber das Tailnet rund zweieinhalb (gemessen gegen senza) -
        und gehoert deshalb in einen Thread.

        :returns: (Pfad, Fehlermeldung). Genau eines von beiden ist gefuellt.
        """
        args = ["shot", "--json"]
        if rechner:
            args.insert(1, rechner)
        roh, fehler = self._json(args)
        if roh is None:
            return "", fehler
        if roh.get("fehler"):
            return "", str(roh["fehler"])
        return str(roh.get("pfad", "")), ""

    def aktualisiere_claude(self, rechner: str = "", verfahren: str = "claude") -> tuple[str, str]:
        """Aktualisiert Claude Code, hier oder auf einem anderen Rechner.

        Das Verfahren wird bewusst MITGEGEBEN und nicht erraten: nur der
        Anwender weiss, wie installiert wurde. Ein geratenes Verfahren waere
        schlimmer als keins - winget meldet auf einer npm-Installation
        Erfolg und aendert nichts.

        :returns: (Version, Fehlermeldung). Genau eines von beiden ist gefuellt.
        """
        args = ["update", "--method", verfahren, "--json"]
        if rechner:
            args.insert(1, rechner)
        roh, fehler = self._json(args, grenze=UPDATE_GRENZE)
        if roh is None:
            return "", fehler
        if not roh.get("ok"):
            return "", str(roh.get("ausgabe") or "Aktualisierung fehlgeschlagen")
        return str(roh.get("version", "")), ""

    # -- intern ---------------------------------------------------------

    def _lauf(
        self, args: list[str], grenze: float = ZEITGRENZE
    ) -> tuple[subprocess.CompletedProcess[str] | None, str]:
        """Startet ein Kommando und faengt die beiden Startfehler ab.

        WICHTIG IST HIER ``stdin=DEVNULL``. Ohne die Angabe erbt der
        Unterprozess die Standardeingabe - und das ist bei einer TUI das
        Terminal, auf dem die Oberflaeche selbst laeuft. Ein Kommando, das
        eine Rueckfrage stellt, haengt dann seinen Zeileneditor in genau
        diesen Eingabestrom: zwei Leser an einem Terminal, die Rueckfrage
        mitten im Bild, Steuerzeichen ueberall. Belegt am 02.08.2026 - der
        Stop schickte ein "--ja", das der Operator nicht kennt, worauf der
        wie vorgesehen nachfragte. Mit DEVNULL bekommt er sofort EOF und
        bricht ab, statt die Oberflaeche zu kapern.
        """
        try:
            lauf = subprocess.run(  # fester Befehl, keine Shell
                [*self._befehl, *args],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                creationflags=umgebung.EIGENE_KONSOLE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=grenze,
                check=False,
            )
        except FileNotFoundError:
            return None, f"Befehl nicht gefunden: {' '.join(self._befehl)}"
        except subprocess.TimeoutExpired:
            return None, f"Zeitueberschreitung nach {grenze:.0f} s"
        if lauf.returncode != 0:
            roh = (lauf.stderr or lauf.stdout or "").strip().splitlines()
            # Ohne das Entfernen der Farbcodes stuenden die Steuerzeichen
            # spaeter woertlich in der Meldung und im Protokoll.
            zeilen = [z for z in (_ohne_farbe(r).strip() for r in roh) if z]
            return None, _kernfehler(zeilen) or f"Exit-Code {lauf.returncode}"
        return lauf, ""

    def _json(
        self, args: list[str], grenze: float = ZEITGRENZE
    ) -> tuple[dict[str, Any] | None, str]:
        """Fuehrt ein Kommando aus und liest dessen JSON-Ausgabe."""
        lauf, fehler = self._lauf(args, grenze)
        if lauf is None:
            return None, fehler
        try:
            return json.loads(lauf.stdout), ""
        except json.JSONDecodeError as ausnahme:
            return None, f"Antwort ist kein JSON: {ausnahme}"

    def _still(self, args: list[str]) -> str:
        """Fuehrt ein Kommando aus, dessen Ausgabe nicht gebraucht wird."""
        return self._lauf(args)[1]

    @staticmethod
    def _agent(e: dict[str, Any], hier: str, system: str = "") -> Agent:
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
            version=e.get("version"),
            system=system or None,
            letztes_tool=e.get("letztesTool"),
            letzte_zeit=str(e.get("letzteZeit") or ""),
            aufgabe=e.get("aufgabe"),
            cwd=str(e.get("cwd") or ""),
            nach_compact=bool(e.get("nachCompact", False)),
            erreichbar=bool(e.get("erreichbar", True)),
        )

    @staticmethod
    def _auftrag(e: dict[str, Any]) -> Auftrag:
        # Wer wo sitzt: Der Auftrag wurde auf "von_host" abgeschickt, der
        # Empfaenger arbeitet auf "host" - und von dort kommt die Quittung.
        # Traegt die Quittung einen eigenen Rechner, gilt der.
        ab_host = str(e.get("von_host") or "")
        ziel_host = str(e.get("host") or "")
        verlauf = [
            Ereignis(
                art="auftrag",
                ts=str(e.get("erstellt", "")),
                von=str(e.get("von", "")),
                an=str(e.get("an", "")),
                text=str(e.get("text", "")),
                zustand=str(e.get("zustand", "")),
                host=ab_host,
                an_host=ziel_host,
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
                    host=str(q.get("host") or ziel_host),
                    # Die Quittung laeuft den Weg zurueck: sie geht an den
                    # Rechner, von dem der Auftrag kam.
                    an_host=str(q.get("an_host") or ab_host),
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
            # or "" statt str(): die Spalten stehen als null in der Datenbank,
            # und str(None) waere die Zeichenkette "None".
            an_session=str(e.get("an_session") or ""),
            bindung=str(e.get("bindung") or ""),
            host=ziel_host,
            von_host=ab_host,
        )


FARBCODE = re.compile(r"\x1b\[[0-9;]*m")

STACKZEILE = re.compile(r"^at\s")
"""Zeile eines Aufrufstapels - traegt die Fundstelle, nie die Ursache."""

FEHLERZEILE = re.compile(r"\w*(Error|Exception)\s*:")
"""Die Zeile, die den Fehler BENENNT: ``Error:``, ``TypeError:``, ``ValueError:``."""


def _ohne_farbe(text: str) -> str:
    """Entfernt ANSI-Farbcodes aus einer Meldung."""
    return FARBCODE.sub("", text)


def _kernfehler(zeilen: list[str]) -> str:
    """Waehlt aus einer mehrzeiligen Ausgabe die aussagekraeftige Zeile.

    Node stellt einem Fehler die FUNDSTELLE voran, nicht die Ursache::

        node:internal/modules/cjs/loader:1520
          throw err;
          ^

        Error: Cannot find module 'C:\\...\\bin\\chatterdome.mjs'
            at Module._resolveFilename (node:internal/modules/cjs/loader:1517:15)

    Wer blind die erste Zeile nimmt, protokolliert ``loader:1520`` und
    verliert genau die Zeile, um die es geht. Belegt am 12.08.2026: der
    Kurzbefehl zeigte nach einem Ordnerwechsel ins Leere, und im Protokoll
    stand nur die Fundstelle - die Ursache musste von Hand nachgestellt
    werden.

    Bleibt keine benannte Fehlerzeile uebrig, gilt weiter die erste Zeile.
    """
    ohne_rahmen = [z for z in zeilen if z != "^" and not STACKZEILE.match(z)]
    benannt = next((z for z in ohne_rahmen if FEHLERZEILE.search(z)), "")
    if benannt:
        return benannt
    return ohne_rahmen[0] if ohne_rahmen else ""


def _rechnername() -> str:
    """Name dieses Rechners - nur als Rueckfall, wenn die Abfrage scheitert."""
    return platform.node() or "?"
