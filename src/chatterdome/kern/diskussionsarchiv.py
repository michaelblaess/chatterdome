"""Archiv der Diskussionen in SQLite.

Liegt neben den Einstellungen unter ``~/.chatterdome/diskussionen.db``.
Eine Diskussion wird beim Start angelegt und nach jedem Beitrag nachgefuehrt,
nicht erst am Ende - bricht Chatterdome mitten in der Diskussion ab, ist das
Gesagte trotzdem da und laesst sich fortsetzen.

Beim Speichern wird eine Diskussion immer VOLLSTAENDIG ersetzt (Teilnehmer und
Beitraege geloescht und neu geschrieben). Bei ein paar Dutzend Beitraegen ist
das billiger als jede Buchfuehrung darueber, was sich geaendert hat.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from chatterdome.kern import einstellungen
from chatterdome.kern.debatte import Beitrag, Diskussion, Teilnehmer, Verbrauch

_SCHEMA = """
CREATE TABLE IF NOT EXISTS diskussion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beginn TEXT NOT NULL,
    thema TEXT NOT NULL,
    format TEXT NOT NULL,
    runden INTEGER NOT NULL,
    recherche INTEGER NOT NULL,
    dauer_minuten REAL NOT NULL,
    position_pro TEXT NOT NULL,
    position_contra TEXT NOT NULL,
    schlussworte INTEGER NOT NULL,
    ohne_kontext INTEGER NOT NULL,
    ende TEXT NOT NULL,
    zusammenfassung TEXT NOT NULL,
    protokoll TEXT NOT NULL,
    tokens_neu INTEGER NOT NULL,
    tokens_cache INTEGER NOT NULL,
    tokens_aus INTEGER NOT NULL,
    modell TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS teilnehmer (
    diskussion INTEGER NOT NULL REFERENCES diskussion(id) ON DELETE CASCADE,
    nr INTEGER NOT NULL,
    name TEXT NOT NULL,
    rolle TEXT NOT NULL,
    seite TEXT NOT NULL,
    ohne_recherche TEXT NOT NULL,
    sitzung TEXT NOT NULL,
    modell TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (diskussion, nr)
);
CREATE TABLE IF NOT EXISTS beitrag (
    diskussion INTEGER NOT NULL REFERENCES diskussion(id) ON DELETE CASCADE,
    nr INTEGER NOT NULL,
    runde INTEGER NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    zeit TEXT NOT NULL,
    art TEXT NOT NULL,
    hinweis TEXT NOT NULL,
    seite TEXT NOT NULL,
    ungeprueft INTEGER NOT NULL,
    PRIMARY KEY (diskussion, nr)
);
"""

_NACHTRAEGE = (("diskussion", "modell"), ("teilnehmer", "modell"))
"""Spalten, die nach dem ersten Stand dazukamen. Eine Datei vom 28.09.2026 kennt
sie noch nicht - sie werden beim Oeffnen nachgetragen."""


@dataclass(frozen=True)
class Eintrag:
    """Eine Zeile der Uebersicht."""

    kennung: int
    beginn: str
    thema: str
    teilnehmer: tuple[str, ...]
    runden: int
    """Tatsaechlich gespielte Runden, nicht die geplanten."""
    ende: str
    tokens: int
    """Alles ausser der Cache-Lesung, wie ``Verbrauch.echt``."""
    modell: str = ""


def archiv_datei() -> Path:
    return einstellungen.VERZEICHNIS / "diskussionen.db"


class Diskussionsarchiv:
    """Liest und schreibt das Archiv. Jede Methode oeffnet ihre eigene Verbindung,
    damit der Ablauf aus seinem Thread schreiben kann, waehrend die Oberflaeche liest."""

    def __init__(self, datei: Path | None = None) -> None:
        self.datei = datei if datei is not None else archiv_datei()

    @contextmanager
    def _verbindung(self) -> Iterator[sqlite3.Connection]:
        self.datei.parent.mkdir(parents=True, exist_ok=True)
        verbindung = sqlite3.connect(self.datei, timeout=30.0)
        try:
            verbindung.execute("PRAGMA journal_mode=WAL")
            verbindung.execute("PRAGMA foreign_keys=ON")
            verbindung.executescript(_SCHEMA)
            for tabelle, spalte in _NACHTRAEGE:
                vorhanden = {z[1] for z in verbindung.execute(f"PRAGMA table_info({tabelle})")}
                if spalte not in vorhanden:
                    verbindung.execute(
                        f"ALTER TABLE {tabelle} ADD COLUMN {spalte} TEXT NOT NULL DEFAULT ''")
            with verbindung:
                yield verbindung
        finally:
            verbindung.close()

    def speichern(self, d: Diskussion, protokoll: str = "") -> int:
        """Legt die Diskussion an oder ersetzt sie. Setzt und liefert ``d.kennung``.

        :param protokoll: Pfad der Markdown-Datei, leer laesst einen vorhandenen stehen.
        """
        werte = (d.beginn, d.thema, d.format, d.runden, int(d.recherche), d.dauer_minuten,
                 d.positionen[0], d.positionen[1], int(d.schlussworte), int(d.ohne_kontext),
                 d.ende, d.zusammenfassung, d.verbrauch.neu, d.verbrauch.cache,
                 d.verbrauch.aus, d.modell)
        with self._verbindung() as db:
            if d.kennung:
                db.execute(
                    "UPDATE diskussion SET beginn=?, thema=?, format=?, runden=?, recherche=?,"
                    " dauer_minuten=?, position_pro=?, position_contra=?, schlussworte=?,"
                    " ohne_kontext=?, ende=?, zusammenfassung=?, tokens_neu=?,"
                    " tokens_cache=?, tokens_aus=?, modell=? WHERE id=?",
                    (*werte, d.kennung),
                )
            else:
                zeiger = db.execute(
                    "INSERT INTO diskussion (beginn, thema, format, runden, recherche,"
                    " dauer_minuten, position_pro, position_contra, schlussworte,"
                    " ohne_kontext, ende, zusammenfassung, tokens_neu, tokens_cache,"
                    " tokens_aus, modell, protokoll)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'')",
                    werte,
                )
                d.kennung = int(zeiger.lastrowid or 0)
            if protokoll:
                db.execute("UPDATE diskussion SET protokoll=? WHERE id=?", (protokoll, d.kennung))
            db.execute("DELETE FROM teilnehmer WHERE diskussion=?", (d.kennung,))
            db.executemany(
                "INSERT INTO teilnehmer (diskussion, nr, name, rolle, seite, ohne_recherche,"
                " sitzung, modell) VALUES (?,?,?,?,?,?,?,?)",
                [(d.kennung, i, t.name, t.rolle, t.seite, t.ohne_recherche, t.sitzung, t.modell)
                 for i, t in enumerate(d.teilnehmer)],
            )
            db.execute("DELETE FROM beitrag WHERE diskussion=?", (d.kennung,))
            db.executemany(
                "INSERT INTO beitrag VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(d.kennung, i, b.runde, b.name, b.text, b.zeit, b.art, b.hinweis, b.seite,
                  int(b.ungeprueft)) for i, b in enumerate(d.beitraege)],
            )
        return d.kennung

    def liste(self, anzahl: int = 50) -> list[Eintrag]:
        """Die letzten Diskussionen, neueste zuerst."""
        with self._verbindung() as db:
            zeilen = db.execute(
                "SELECT d.id, d.beginn, d.thema, d.ende, d.tokens_neu + d.tokens_aus, d.modell,"
                " (SELECT group_concat(name, '|') FROM"
                "   (SELECT name FROM teilnehmer WHERE diskussion=d.id ORDER BY nr)),"
                " (SELECT coalesce(max(runde), 0) FROM beitrag"
                "   WHERE diskussion=d.id AND art IN ('beitrag','ausgelassen','fehler'))"
                " FROM diskussion d ORDER BY d.beginn DESC, d.id DESC LIMIT ?",
                (anzahl,),
            ).fetchall()
        return [Eintrag(int(k), str(b), str(th), tuple(str(n or "").split("|")) if n else (),
                        int(r), str(e), int(tok), str(m))
                for k, b, th, e, tok, m, n, r in zeilen]

    def loeschen(self, kennung: int) -> bool:
        """Entfernt eine Diskussion samt Teilnehmern und Beitraegen. False, wenn es sie nicht gab.

        Das Markdown-Protokoll bleibt liegen - es ist eine Datei des Anwenders.
        """
        with self._verbindung() as db:
            db.execute("DELETE FROM beitrag WHERE diskussion=?", (kennung,))
            db.execute("DELETE FROM teilnehmer WHERE diskussion=?", (kennung,))
            return db.execute("DELETE FROM diskussion WHERE id=?", (kennung,)).rowcount > 0

    def laden(self, kennung: int) -> tuple[Diskussion, str] | None:
        """Die Diskussion samt Protokollpfad, None wenn es sie nicht gibt."""
        with self._verbindung() as db:
            kopf = db.execute(
                "SELECT beginn, thema, format, runden, recherche, dauer_minuten, position_pro,"
                " position_contra, schlussworte, ohne_kontext, ende, zusammenfassung,"
                " protokoll, tokens_neu, tokens_cache, tokens_aus, modell"
                " FROM diskussion WHERE id=?",
                (kennung,),
            ).fetchone()
            if kopf is None:
                return None
            teilnehmer = [
                Teilnehmer(n, r, s, o, z, m) for n, r, s, o, z, m in db.execute(
                    "SELECT name, rolle, seite, ohne_recherche, sitzung, modell FROM teilnehmer"
                    " WHERE diskussion=? ORDER BY nr", (kennung,))
            ]
            beitraege = [
                Beitrag(ru, n, tx, z, a, h, s, bool(u)) for ru, n, tx, z, a, h, s, u in db.execute(
                    "SELECT runde, name, text, zeit, art, hinweis, seite, ungeprueft"
                    " FROM beitrag WHERE diskussion=? ORDER BY nr", (kennung,))
            ]
        (beginn, thema, fmt, runden, recherche, dauer, pro, contra, schluss, ohne,
         ende, zusammenfassung, protokoll, neu, cache, aus, modell) = kopf
        d = Diskussion(
            thema=thema, teilnehmer=teilnehmer, format=fmt, runden=int(runden),
            recherche=bool(recherche), dauer_minuten=float(dauer), positionen=(pro, contra),
            schlussworte=bool(schluss), beitraege=beitraege, ende=ende,
            zusammenfassung=zusammenfassung, beginn=beginn,
            verbrauch=Verbrauch(int(neu), int(cache), int(aus)), kennung=kennung,
            ohne_kontext=bool(ohne), modell=modell,
        )
        return d, str(protokoll)
