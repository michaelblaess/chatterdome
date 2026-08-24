"""Volltextsuche ueber alle Transkripte - SQLite mit FTS5.

Der Index liegt neben den Einstellungen unter ``~/.claude-sanctuary/suche.db`` und
ist jederzeit wegwerfbar: er enthaelt nichts, was nicht auch in den Transkripten
steht. Geloescht wird er beim naechsten Lauf neu aufgebaut.

**Inkrementell ueber die Dateizeit.** Je Datei stehen Aenderungszeit und Groesse
in einer Nebentabelle. Ein zweiter Lauf ohne neue Sitzungen fasst deshalb keine
einzige Datei an. Das ist noetig, weil ein Volldurchlauf ueber Michaels Bestand
Sekunden kostet und niemand beim Oeffnen eines Reiters darauf wartet.

**Was NICHT im Index steht:** Werkzeugaufrufe und deren Ausgaben. Sie machen den
Grossteil der Zeichen aus, und was darin steht - Dateiinhalte, Befehlsausgaben -
findet man besser dort, wo es herkommt. Gesucht wird in dem, was gesagt wurde.

**Grenze bei der Umlautbehandlung.** Der Tokenizer ``unicode61 remove_diacritics 2``
setzt Umlaute auf ihren Grundbuchstaben zurueck, ``koln`` findet also ``Koeln``.
Das scharfe s bleibt davon unberuehrt: ``grusse`` findet ``Gruesse`` NICHT.
Gemessen am 24.08.2026 gegen SQLite 3.50.4.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from claude_sanctuary.kern import einstellungen
from claude_sanctuary.kern.transkripte import Transkript, Transkriptquelle, alle_quellen

SCHEMA = """
CREATE TABLE IF NOT EXISTS dateien (
    pfad     TEXT PRIMARY KEY,
    agent    TEXT NOT NULL,
    sitzung  TEXT NOT NULL,
    subagent INTEGER NOT NULL DEFAULT 0,
    mtime    REAL NOT NULL,
    groesse  INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS stuecke USING fts5(
    text,
    pfad UNINDEXED,
    agent UNINDEXED,
    sitzung UNINDEXED,
    rolle UNINDEXED,
    zeile UNINDEXED,
    ts UNINDEXED,
    subagent UNINDEXED,
    tokenize="unicode61 remove_diacritics 2"
);
"""

WORT = re.compile(r"[\w]+", re.UNICODE)
"""Nur Wortzeichen. Alles andere - Anfuehrungszeichen, Klammern, Sternchen -
ist FTS5-Syntax und wuerde bei einer Nutzereingabe zum Fehler fuehren."""


@dataclass(frozen=True, slots=True)
class Treffer:
    """Eine Fundstelle mit allem, was zum Anspringen noetig ist."""

    agent: str
    sitzung: str
    pfad: Path
    zeile: int
    rolle: str
    ts: datetime | None
    ausschnitt: str
    """Der Fundtext mit ``[b]``-Auszeichnung um die Treffer - fertig fuer Rich."""

    subagent: bool = False


@dataclass(slots=True)
class Bilanz:
    """Was ein Indexlauf getan hat."""

    geprueft: int = 0
    neu: int = 0
    aktualisiert: int = 0
    entfernt: int = 0
    stuecke: int = 0
    dauer_s: float = 0.0

    @property
    def unveraendert(self) -> int:
        return self.geprueft - self.neu - self.aktualisiert


def index_datei() -> Path:
    """Der Ort des Index - zur LAUFZEIT gelesen, nicht beim Import.

    Als Modulkonstante waere der Pfad beim Import eingefroren und liesse sich in
    Tests nicht mehr umhaengen. Die autouse-Fixture verlegt ``VERZEICHNIS``, und
    nur so wandert der Index mit.
    """
    return einstellungen.VERZEICHNIS / "suche.db"


def _frage(eingabe: str) -> str:
    """Uebersetzt eine Nutzereingabe in eine FTS5-Abfrage.

    FTS5 hat eine eigene Syntax: ein unpaariges Anfuehrungszeichen oder ein
    fuehrendes ``*`` bricht die Abfrage mit einem Fehler ab. Statt zu escapen
    wird die Eingabe deshalb auf Woerter reduziert, jedes einzeln in
    Anfuehrungszeichen gesetzt und mit UND verknuepft - das letzte Wort als
    Praefix, damit die Suche schon beim Tippen etwas findet.

    Gibt eine leere Zeichenkette zurueck, wenn nichts Suchbares uebrig bleibt.
    Der Aufrufer muss das pruefen: eine leere Abfrage ist bei FTS5 ein Fehler,
    kein leeres Ergebnis.
    """
    woerter = WORT.findall(eingabe)
    if not woerter:
        return ""
    teile = [f'"{w}"' for w in woerter[:-1]]
    teile.append(f'"{woerter[-1]}"*')
    return " AND ".join(teile)


def _zeitpunkt(roh: str | None) -> datetime | None:
    if not roh:
        return None
    try:
        wert = datetime.fromisoformat(roh)
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=UTC)


class Suchindex:
    """Der Volltextindex ueber alle Transkriptquellen."""

    def __init__(self, datei: Path | None = None) -> None:
        self.datei = datei if datei is not None else index_datei()
        self._angelegt = False
        # Nur EIN Schreiber. Ein Thread-Worker laesst sich nicht abbrechen:
        # startet die Oberflaeche den Aufbau zweimal (Tastenkuerzel UND
        # Reiterwechsel), laufen beide zu Ende und treffen sich in der Datei.
        # SQLite meldet dann "database is locked", und zwar genau beim ersten
        # Oeffnen des Reiters. Die Sperre haelt das aus dem Kern heraus, statt
        # sich auf die Aufrufdisziplin der Oberflaeche zu verlassen.
        self._schreibsperre = threading.Lock()

    def _verbindung(self, schreibend: bool = False) -> sqlite3.Connection:
        """Eine Verbindung zum Index.

        ``executescript(SCHEMA)`` bei JEDEM Verbindungsaufbau war ein Fehler:
        auch ein ``CREATE TABLE IF NOT EXISTS`` nimmt eine Schreibsperre. Sucht
        der Anwender, waehrend der Indexlauf im Hintergrund noch schreibt,
        treffen zwei Schreiber aufeinander und SQLite meldet ``database is
        locked`` - im Betrieb genau dann, wenn der Reiter zum ersten Mal
        geoeffnet wird. Das Anlegen passiert deshalb nur einmal je Instanz und
        nur auf einem schreibenden Weg.
        """
        if schreibend:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
        # Der Zeitablauf faengt die kurzen Ueberschneidungen ab, die trotz WAL
        # bleiben - eine Schreibsperre gilt immer nur fuer einen Schreiber.
        verbindung = sqlite3.connect(self.datei, timeout=30.0)
        if schreibend and not self._angelegt:
            # WAL erlaubt Lesen waehrend des Schreibens. Ohne das sperrt der
            # Indexlauf die Suche fuer seine ganze Dauer aus.
            verbindung.execute("PRAGMA journal_mode=WAL")
            verbindung.executescript(SCHEMA)
            self._angelegt = True
        return verbindung

    def aktualisiere(
        self,
        quellen: Sequence[Transkriptquelle] | None = None,
        melde: Callable[[int, int], None] | None = None,
    ) -> Bilanz:
        """Bringt den Index auf den Stand der Dateien.

        :param quellen: die zu lesenden Quellen, oder None fuer alle vorhandenen.
        :param melde: Rueckruf ``(erledigt, gesamt)`` fuer eine Fortschrittsanzeige.
        """
        from time import monotonic

        start = monotonic()
        bilanz = Bilanz()
        liste = list(quellen) if quellen is not None else alle_quellen()

        with self._schreibsperre, closing(self._verbindung(schreibend=True)) as verbindung:
            bekannt = {
                pfad: (mtime, groesse)
                for pfad, mtime, groesse in verbindung.execute(
                    "SELECT pfad, mtime, groesse FROM dateien"
                )
            }
            gesehen: set[str] = set()
            alle_dateien = [(q, t) for q in liste for t in q.dateien()]

            for nummer, (quelle, transkript) in enumerate(alle_dateien, start=1):
                schluessel = str(transkript.pfad)
                gesehen.add(schluessel)
                bilanz.geprueft += 1
                try:
                    zustand = transkript.pfad.stat()
                except OSError:
                    continue
                vorher = bekannt.get(schluessel)
                if vorher is not None and vorher == (zustand.st_mtime, zustand.st_size):
                    if melde is not None:
                        melde(nummer, len(alle_dateien))
                    continue

                if vorher is None:
                    bilanz.neu += 1
                else:
                    bilanz.aktualisiert += 1
                    verbindung.execute("DELETE FROM stuecke WHERE pfad = ?", (schluessel,))

                bilanz.stuecke += self._schreibe(verbindung, quelle, transkript)
                verbindung.execute(
                    "INSERT OR REPLACE INTO dateien VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        schluessel,
                        transkript.agent,
                        transkript.sitzung,
                        int(transkript.subagent),
                        zustand.st_mtime,
                        zustand.st_size,
                    ),
                )
                verbindung.commit()
                if melde is not None:
                    melde(nummer, len(alle_dateien))

            # Verschwundene Dateien austragen. Ohne das liefert die Suche
            # Treffer in Transkripten, die es nicht mehr gibt.
            verschwunden = set(bekannt) - gesehen
            for schluessel in verschwunden:
                verbindung.execute("DELETE FROM stuecke WHERE pfad = ?", (schluessel,))
                verbindung.execute("DELETE FROM dateien WHERE pfad = ?", (schluessel,))
            bilanz.entfernt = len(verschwunden)
            verbindung.commit()

        bilanz.dauer_s = monotonic() - start
        return bilanz

    def _schreibe(
        self, verbindung: sqlite3.Connection, quelle: Transkriptquelle, transkript: Transkript
    ) -> int:
        zeilen = [
            (
                stueck.text,
                str(transkript.pfad),
                transkript.agent,
                transkript.sitzung,
                stueck.rolle,
                stueck.zeile,
                stueck.ts.isoformat() if stueck.ts else "",
                int(transkript.subagent),
            )
            for stueck in quelle.texte(transkript)
        ]
        if zeilen:
            verbindung.executemany(
                "INSERT INTO stuecke (text, pfad, agent, sitzung, rolle, zeile, ts, subagent)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                zeilen,
            )
        return len(zeilen)

    def suche(
        self, eingabe: str, *, grenze: int = 60, agenten: Iterable[str] | None = None
    ) -> list[Treffer]:
        """Sucht im Index. Eine Eingabe ohne Wortzeichen liefert nichts.

        Sortiert wird nach der Bewertung von FTS5, nicht nach Zeit: wer sucht,
        will den besten Treffer sehen, nicht den juengsten.
        """
        frage = _frage(eingabe)
        if not frage or not self.datei.is_file():
            return []
        auswahl = list(agenten) if agenten is not None else []
        bedingung = ""
        werte: list[object] = [frage]
        if auswahl:
            bedingung = f" AND agent IN ({','.join('?' * len(auswahl))})"
            werte.extend(auswahl)
        werte.append(grenze)

        with closing(self._verbindung()) as verbindung:
            try:
                zeilen = verbindung.execute(
                    "SELECT snippet(stuecke, 0, '[b]', '[/b]', ' ... ', 14),"
                    " pfad, agent, sitzung, rolle, zeile, ts, subagent"
                    " FROM stuecke WHERE stuecke MATCH ?"
                    f"{bedingung} ORDER BY rank LIMIT ?",
                    werte,
                ).fetchall()
            except sqlite3.OperationalError:
                # Bleibt als Netz, obwohl _frage die Syntax schon zaehmt: eine
                # Abfrage darf die Oberflaeche nie mitreissen.
                return []

        return [
            Treffer(
                agent=agent,
                sitzung=sitzung,
                pfad=Path(pfad),
                zeile=int(zeile),
                rolle=rolle,
                ts=_zeitpunkt(ts),
                ausschnitt=" ".join(ausschnitt.split()),
                subagent=bool(subagent),
            )
            for ausschnitt, pfad, agent, sitzung, rolle, zeile, ts, subagent in zeilen
        ]

    def bestand(self) -> tuple[int, int]:
        """Dateien und Textstuecke im Index - fuer die Fusszeile des Reiters."""
        if not self.datei.is_file():
            return 0, 0
        with closing(self._verbindung()) as verbindung:
            try:
                dateien = verbindung.execute("SELECT count(*) FROM dateien").fetchone()[0]
                stuecke = verbindung.execute("SELECT count(*) FROM stuecke").fetchone()[0]
            except sqlite3.OperationalError:
                # Datei da, Tabellen noch nicht - der erste Lauf legt sie an.
                return 0, 0
        return int(dateien), int(stuecke)

    def leere(self) -> None:
        """Wirft den Index weg. Der naechste Lauf baut ihn neu auf."""
        for endung in ("", "-wal", "-shm"):
            kandidat = Path(str(self.datei) + endung)
            if kandidat.exists():
                kandidat.unlink()
