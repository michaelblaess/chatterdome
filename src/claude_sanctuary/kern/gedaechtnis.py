"""Analyse des Claude-Code-Gedaechtnisses - UI-frei, von TUI und Tests genutzt.

Das Gedaechtnis besteht aus zwei Teilen mit sehr verschiedenen Kosten:

``MEMORY.md`` ist der Index. Er liegt bei JEDEM Sitzungsstart vollstaendig im
Kontext. Jede Zeile darin kostet in jeder kuenftigen Sitzung.

Die Einzelnotizen kosten dagegen nur dann etwas, wenn sie wirklich abgerufen
werden - und das ist selten. Ueber den gesamten Transkriptbestand (385 MB,
117 Dateien, gemessen am 05.08.2026) waren es 42 Abrufe.

Daraus folgt die zentrale Aussage dieses Moduls: eine Notiz zu loeschen spart
am Kontext fast nichts, eine Zeile weniger im Index dagegen schon.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

INDEX_NAME = "MEMORY.md"
"""Der Index. Er traegt bewusst kein Frontmatter und ist keine Notiz."""

ZEICHEN_JE_TOKEN = 3.5
"""Schaetzfaktor fuer die Tokenrechnung.

Ohne Tokenizer ist kein exakter Wert zu haben. Fuer deutschsprachiges Markdown
liegt der Wert erfahrungsgemaess bei rund 3,5 Zeichen je Token. Jede Anzeige,
die darauf beruht, MUSS als Schaetzung beschriftet sein.
"""

BEKANNTE_TYPEN = ("user", "feedback", "project", "reference")
"""Die vier vorgesehenen Notizarten, in der Reihenfolge der Anleitung."""

_WIKILINK = re.compile(r"\[\[([a-z0-9_\-]+)\]\]", re.I)
_INDEX_VERWEIS = re.compile(r"\[([^\]]+)\]\(([a-z0-9_\-]+\.md)\)", re.I)
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_FELD = re.compile(r"^(name|description):\s*(.*)$", re.M)
_TYP = re.compile(r"^\s+type:\s*(\S+)\s*$", re.M)

_ERLEDIGT = re.compile(r"\b(abgeschlossen|erledigt)\b", re.I)
"""Hinweis darauf, dass eine Notiz einen fertigen Vorgang beschreibt.

Das ist ein VERDACHT, kein Befund - der Treffer kann auch in einer Regel
stehen ("erst pruefen, dann fertig melden"). Die Oberflaeche beschriftet das
entsprechend und leitet daraus keine Empfehlung ab.
"""

RECALL_MARKER = "<system-reminder>This memory is"
"""Der Hinweis, den Claude Code vor einen abgerufenen Eintrag setzt.

Das oeffnende Element gehoert zwingend dazu. Ohne dieses Element zaehlt sich
eine Auswertung selbst mit: sobald jemand in einer Sitzung die Transkripte nach
Abrufen durchsucht, landet die Ausgabe dieser Suche im laufenden Transkript und
enthaelt den blossen Satz "This memory is 4 days old" als Fundstelle. Genau das
ist am 05.08.2026 beim Bau dieses Moduls passiert - dieselbe Falle wie das
naive Suchen nach Dateinamen, nur eine Ebene tiefer.
"""

_RECALL_ENDE = "</system-reminder>"
_RECALL_NAME = re.compile(r"name:\s*([a-z][a-z0-9_\-]*)", re.I)
_RECALL_ALTER = re.compile(r"is (\d+) days? old")

_FENSTER = 400
"""Zeichen nach dem Hinweis, in denen das Frontmatter erwartet wird.

Enger Rahmen mit Absicht: der naechste ``name:`` weiter hinten im selben Satz
gehoert einer anderen Notiz und wuerde falsch zugeordnet.
"""


def normalisiere(name: str) -> str:
    """Vereinheitlicht einen Notiznamen fuer den Vergleich.

    Aeltere Abrufe tragen Bindestriche (``feedback-bash-heredoc-commit``),
    waehrend die Dateien heute Unterstriche fuehren. Ohne diese Angleichung
    fehlen die betroffenen Treffer ersatzlos.
    """
    return name.strip().lower().replace("-", "_")


def schaetze_tokens(zeichen: int) -> int:
    """Grobe Tokenzahl aus der Zeichenzahl. Siehe ZEICHEN_JE_TOKEN."""
    return int(zeichen / ZEICHEN_JE_TOKEN)


@dataclass(slots=True)
class Befund:
    """Ein Ergebnis der Gesundheitspruefung.

    Ein Befund benennt immer etwas nachpruefbar Falsches - eine fehlende Datei,
    einen Verweis ins Leere. Bewertungen ohne Datenlage stehen hier nicht.
    """

    art: str
    """Kennung der Pruefung, etwa ``waise`` oder ``toter_verweis``."""

    betrifft: str
    """Name der Notiz, um die es geht."""

    text: str
    """Beschreibung in der Sprache der Oberflaeche."""

    ernst: bool = True
    """Falsch bei blossen Hinweisen, die kein Fehler sind."""


@dataclass(slots=True)
class Notiz:
    """Eine einzelne Gedaechtnisdatei."""

    name: str
    datei: Path
    typ: str = ""
    beschreibung: str = ""
    zeilen: int = 0
    zeichen: int = 0

    im_index: bool = False
    """Wahr, wenn MEMORY.md auf diese Datei verweist."""

    index_text: str = ""
    """Die Zeile aus dem Index, ohne den Verweis selbst."""

    verweist_auf: list[str] = field(default_factory=list)
    """Ziele der [[Wikilinks]] in dieser Notiz, ohne Selbstbezug."""

    tote_verweise: list[str] = field(default_factory=list)
    """Wikilinks, zu denen es keine Datei gibt."""

    eingehend: list[str] = field(default_factory=list)
    """Notizen, die hierher verweisen. Wird beim Laden nachgetragen."""

    erledigt_verdacht: bool = False
    recalls: int = 0
    letzter_recall_tage: int | None = None

    @property
    def tokens(self) -> int:
        """Geschaetzte Tokenzahl dieser Notiz - faellt nur beim Abruf an."""
        return schaetze_tokens(self.zeichen)

    @property
    def isoliert(self) -> bool:
        """Wahr, wenn keine andere Notiz hierher verweist."""
        return not self.eingehend

    @property
    def name_weicht_ab(self) -> bool:
        """Wahr, wenn der Name im Kopf nicht zum Dateinamen passt.

        Kein Fehler, aber eine Stolperstelle: ein Abruf meldet den Namen aus
        dem Kopf, eine Suche im Verzeichnis findet den Dateinamen. Weichen sie
        ab, wird aus einer Notiz in Auswertungen leicht zweierlei.
        """
        return normalisiere(self.name) != normalisiere(self.datei.stem)

    @property
    def schluessel(self) -> str:
        """Eindeutige Kennung. Der Dateiname, denn auf den zeigt der Index."""
        return normalisiere(self.datei.stem)

    @property
    def aliase(self) -> set[str]:
        """Alle Namen, unter denen diese Notiz angesprochen werden kann."""
        return {self.schluessel, normalisiere(self.name)}

    @property
    def titel(self) -> str:
        """Beschriftung aus dem Index, ersatzweise der Name."""
        return self.index_text or self.name


@dataclass(slots=True)
class Recallbericht:
    """Was der Durchgang durch die Transkripte ergeben hat."""

    treffer: dict[str, int] = field(default_factory=dict)
    letztes_alter: dict[str, int] = field(default_factory=dict)
    """Notizname auf das im juengsten Abruf gemeldete Alter in Tagen."""

    bloecke: int = 0
    """Gefundene Abrufe insgesamt."""

    unzugeordnet: int = 0
    """Abrufe ohne erkennbaren Namen - etwa Ausschnitte ohne Frontmatter."""

    dateien: int = 0
    bytes: int = 0

    @property
    def zugeordnet(self) -> int:
        return sum(self.treffer.values())


@dataclass(slots=True)
class Gedaechtnis:
    """Der gesamte Bestand samt Index."""

    verzeichnis: Path
    notizen: list[Notiz] = field(default_factory=list)
    index_vorhanden: bool = False
    index_zeilen: int = 0
    index_zeichen: int = 0
    index_eintraege: int = 0
    """Verweise in MEMORY.md, die auf eine Datei zeigen."""

    unbekannte_index_verweise: list[str] = field(default_factory=list)
    """Verweise im Index, zu denen keine Datei existiert."""

    recall_bericht: Recallbericht | None = None
    """None, solange die Transkripte nicht durchgesehen wurden."""

    # -- Kennzahlen -----------------------------------------------------

    @property
    def anzahl(self) -> int:
        return len(self.notizen)

    @property
    def zeilen_gesamt(self) -> int:
        return sum(n.zeilen for n in self.notizen)

    @property
    def zeichen_gesamt(self) -> int:
        return sum(n.zeichen for n in self.notizen)

    @property
    def index_tokens(self) -> int:
        """Geschaetzte Last des Index - faellt in JEDER Sitzung an."""
        return schaetze_tokens(self.index_zeichen)

    @property
    def bestand_tokens(self) -> int:
        """Geschaetzte Last aller Notizen - faellt fast nie an."""
        return schaetze_tokens(self.zeichen_gesamt)

    @property
    def tokens_je_indexzeile(self) -> int:
        """Was eine einzelne Indexzeile im Schnitt je Sitzung kostet."""
        if self.index_eintraege <= 0:
            return 0
        return max(1, round(self.index_tokens / self.index_eintraege))

    @property
    def nach_typ(self) -> dict[str, int]:
        """Anzahl je Notizart, bekannte Arten zuerst und in fester Folge."""
        gezaehlt: dict[str, int] = {}
        for notiz in self.notizen:
            schluessel = notiz.typ or "?"
            gezaehlt[schluessel] = gezaehlt.get(schluessel, 0) + 1
        geordnet = {t: gezaehlt[t] for t in BEKANNTE_TYPEN if t in gezaehlt}
        for schluessel in sorted(gezaehlt):
            if schluessel not in geordnet:
                geordnet[schluessel] = gezaehlt[schluessel]
        return geordnet

    @property
    def waisen(self) -> list[Notiz]:
        """Notizen ohne Eintrag im Index - fuer Claude praktisch unsichtbar."""
        return [n for n in self.notizen if not n.im_index]

    @property
    def isolierte(self) -> list[Notiz]:
        """Notizen, auf die keine andere verweist."""
        return [n for n in self.notizen if n.isoliert]

    @property
    def erledigte(self) -> list[Notiz]:
        return [n for n in self.notizen if n.erledigt_verdacht]

    def groesste(self, anzahl: int = 5) -> list[Notiz]:
        return sorted(self.notizen, key=lambda n: n.zeilen, reverse=True)[:anzahl]

    def finde(self, name: str) -> Notiz | None:
        """Sucht eine Notiz ueber Dateinamen oder Namen aus dem Kopf."""
        gesucht = normalisiere(name)
        for notiz in self.notizen:
            if gesucht in notiz.aliase:
                return notiz
        return None

    def alle_namen(self) -> set[str]:
        """Jeden Namen, unter dem eine Notiz in Transkripten auftauchen kann."""
        namen: set[str] = set()
        for notiz in self.notizen:
            namen |= notiz.aliase
        return namen

    def befunde(self) -> list[Befund]:
        """Alle nachpruefbaren Maengel des Bestands.

        Bewusst nur Fehler, die sich belegen lassen. Ob eine Notiz "zu gross"
        oder "veraltet" ist, steht hier nicht - das waere geraten.
        """
        gefunden: list[Befund] = []
        for name in self.unbekannte_index_verweise:
            gefunden.append(
                Befund("toter_verweis", name, f"MEMORY.md verweist auf {name} - Datei fehlt")
            )
        for notiz in self.waisen:
            gefunden.append(
                Befund("waise", notiz.name, f"{notiz.name} steht in keiner Zeile von MEMORY.md")
            )
        for notiz in self.notizen:
            for ziel in notiz.tote_verweise:
                gefunden.append(
                    Befund("toter_wikilink", notiz.name, f"{notiz.name} verweist auf [[{ziel}]]")
                )
            if not notiz.typ:
                gefunden.append(Befund("ohne_typ", notiz.name, f"{notiz.name} hat kein type-Feld"))
            if notiz.name_weicht_ab:
                gefunden.append(
                    Befund(
                        "name_abweichung",
                        notiz.name,
                        f"{notiz.datei.name} traegt im Kopf den Namen {notiz.name}",
                        ernst=False,
                    )
                )
        return gefunden


# -- Laden --------------------------------------------------------------


def _lies(datei: Path) -> str:
    try:
        return datei.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _frontmatter(inhalt: str) -> tuple[str, str, str]:
    """Liefert name, description und type aus dem Kopf der Datei."""
    treffer = _FRONTMATTER.search(inhalt)
    if treffer is None:
        return "", "", ""
    kopf = treffer.group(1)
    felder = {schluessel: wert.strip() for schluessel, wert in _FELD.findall(kopf)}
    typ = _TYP.search(kopf)
    return (
        felder.get("name", ""),
        felder.get("description", "").strip("\"'"),
        typ.group(1) if typ else "",
    )


def _index_lesen(datei: Path) -> tuple[dict[str, str], list[str], int, int]:
    """Liest MEMORY.md und liefert Ziel-zu-Text, Reihenfolge, Zeilen, Zeichen."""
    inhalt = _lies(datei)
    if not inhalt:
        return {}, [], 0, 0
    eintraege: dict[str, str] = {}
    reihenfolge: list[str] = []
    for beschriftung, ziel in _INDEX_VERWEIS.findall(inhalt):
        name = normalisiere(Path(ziel).stem)
        if name not in eintraege:
            reihenfolge.append(name)
        eintraege[name] = beschriftung.strip()
    return eintraege, reihenfolge, len(inhalt.splitlines()), len(inhalt)


def lade_gedaechtnis(verzeichnis: Path) -> Gedaechtnis:
    """Liest ein Gedaechtnisverzeichnis vollstaendig ein.

    Der Recall-Bericht bleibt leer - er kostet einen Durchgang durch alle
    Transkripte und wird deshalb getrennt angefordert.
    """
    bestand = Gedaechtnis(verzeichnis=verzeichnis)
    if not verzeichnis.is_dir():
        return bestand

    index_datei = verzeichnis / INDEX_NAME
    bestand.index_vorhanden = index_datei.is_file()
    eintraege, _, zeilen, zeichen = _index_lesen(index_datei)
    bestand.index_zeilen = zeilen
    bestand.index_zeichen = zeichen
    bestand.index_eintraege = len(eintraege)

    vorhanden: dict[str, Notiz] = {}
    for datei in sorted(verzeichnis.glob("*.md")):
        if datei.name == INDEX_NAME:
            continue
        inhalt = _lies(datei)
        name, beschreibung, typ = _frontmatter(inhalt)
        # Der Dateiname ist die Identitaet, nicht der Name aus dem Kopf: der
        # Index verweist auf Dateien, und die beiden weichen im Bestand
        # tatsaechlich voneinander ab.
        schluessel = normalisiere(datei.stem)
        notiz = Notiz(
            name=name or datei.stem,
            datei=datei,
            typ=typ,
            beschreibung=beschreibung,
            zeilen=len(inhalt.splitlines()),
            zeichen=len(inhalt),
            im_index=schluessel in eintraege,
            index_text=eintraege.get(schluessel, ""),
            erledigt_verdacht=bool(_ERLEDIGT.search(inhalt)),
        )
        # Selbstbezug zaehlt nicht als Verweis - sonst waere keine Notiz isoliert.
        ziele = {normalisiere(z) for z in _WIKILINK.findall(inhalt)} - notiz.aliase
        notiz.verweist_auf = sorted(ziele)
        vorhanden[schluessel] = notiz

    # Ein Verweis darf den Dateinamen ODER den Namen aus dem Kopf nennen.
    register: dict[str, Notiz] = {}
    for notiz in vorhanden.values():
        for alias in notiz.aliase:
            register.setdefault(alias, notiz)

    for notiz in vorhanden.values():
        for ziel in notiz.verweist_auf:
            partner = register.get(ziel)
            if partner is None:
                notiz.tote_verweise.append(ziel)
            elif partner is not notiz:
                partner.eingehend.append(notiz.name)
    for notiz in vorhanden.values():
        notiz.eingehend = sorted(set(notiz.eingehend))

    bestand.notizen = sorted(vorhanden.values(), key=lambda n: n.name)
    bestand.unbekannte_index_verweise = sorted(set(eintraege) - set(vorhanden))
    return bestand


# -- Abrufe in den Transkripten -----------------------------------------


def _alle_texte(wert: Any) -> list[str]:
    """Sammelt alle Zeichenketten eines JSON-Werts in Dokumentreihenfolge.

    Die Reihenfolge ist wesentlich, nicht Geschmackssache: der Hinweis steht
    oft am Ende eines Textstuecks und der Inhalt der Notiz erst im naechsten.
    Ein Stapel wuerde die Stuecke umkehren, und der Inhalt stuende dann VOR
    seinem Hinweis - 24 von 66 Abrufen blieben so unzuordenbar (gemessen am
    05.08.2026 am echten Bestand).
    """
    gefunden: list[str] = []
    if isinstance(wert, str):
        gefunden.append(wert)
    elif isinstance(wert, dict):
        for teil in wert.values():
            gefunden.extend(_alle_texte(teil))
    elif isinstance(wert, list):
        for teil in wert:
            gefunden.extend(_alle_texte(teil))
    return gefunden


def _dokument(satz: Any) -> str:
    """Fuegt die Textstuecke eines Satzes zu einem durchsuchbaren Ganzen.

    Doppelte Stuecke fliegen raus - dieselbe Passage steht in manchen Saetzen
    zweimal, und ohne Bereinigung zaehlte derselbe Abruf doppelt.
    """
    gesehen: set[str] = set()
    teile: list[str] = []
    for text in _alle_texte(satz):
        if text in gesehen:
            continue
        gesehen.add(text)
        teile.append(text)
    return "\n".join(teile)


def zaehle_recalls(projekte: Path, namen: set[str]) -> Recallbericht:
    """Zaehlt, wie oft eine Notiz tatsaechlich in eine Sitzung geladen wurde.

    Ein blosses Suchen nach dem Dateinamen taugt dafuer NICHT: der Name steht
    auch in jeder Ausgabe von ``git diff`` oder ``ls``. Gezaehlt wird nur, was
    hinter dem Hinweis ``This memory is N days old`` steht.

    Der Bestand deckt nur die vorhandenen Transkripte ab. Aeltere Sitzungen
    koennen geloescht sein, das Ergebnis ist also eine Untergrenze.
    """
    bericht = Recallbericht()
    bekannt = {normalisiere(n) for n in namen}
    if not projekte.is_dir():
        return bericht

    for datei in sorted(projekte.rglob("*.jsonl")):
        bericht.dateien += 1
        try:
            bericht.bytes += datei.stat().st_size
        except OSError:
            continue
        try:
            with datei.open(encoding="utf-8", errors="replace") as strom:
                for roh in strom:
                    # Der Vorabtest auf der rohen Zeile spart das Auswerten von
                    # ueber 100.000 Zeilen, von denen nur ein Dutzend zaehlt.
                    if RECALL_MARKER not in roh:
                        continue
                    try:
                        satz = json.loads(roh)
                    except ValueError:
                        continue
                    _werte_block_aus(_dokument(satz), bekannt, bericht)
        except OSError:
            continue
    return bericht


def _werte_block_aus(text: str, bekannt: set[str], bericht: Recallbericht) -> None:
    """Sucht in einem Text alle Abrufhinweise und ordnet sie einer Notiz zu."""
    stelle = text.find(RECALL_MARKER)
    while stelle >= 0:
        bericht.bloecke += 1
        ende = text.find(_RECALL_ENDE, stelle)
        # Ohne schliessendes Element hinter dem Hinweis weitersuchen, statt
        # den Abruf aufzugeben - abgeschnittene Saetze haben kein Ende.
        beginn = ende if ende >= 0 else stelle + len(RECALL_MARKER)
        fenster = text[beginn : beginn + _FENSTER]
        name = _RECALL_NAME.search(fenster)
        schluessel = normalisiere(name.group(1)) if name else ""
        if schluessel and schluessel in bekannt:
            bericht.treffer[schluessel] = bericht.treffer.get(schluessel, 0) + 1
            alter = _RECALL_ALTER.search(text, stelle)
            if alter is not None:
                tage = int(alter.group(1))
                vorher = bericht.letztes_alter.get(schluessel)
                # Der kleinste Wert ist der juengste Abruf.
                if vorher is None or tage < vorher:
                    bericht.letztes_alter[schluessel] = tage
        else:
            # Ausschnitte ohne Frontmatter sind nicht zuzuordnen. Sie werden
            # ausgewiesen statt verschwiegen, sonst taeuscht die Summe.
            bericht.unzugeordnet += 1
        stelle = text.find(RECALL_MARKER, stelle + 1)


def uebernimm_recalls(bestand: Gedaechtnis, bericht: Recallbericht) -> None:
    """Traegt einen Recall-Bericht in die Notizen des Bestands ein."""
    bestand.recall_bericht = bericht
    for notiz in bestand.notizen:
        # Ueber alle Namen summieren: aeltere Abrufe koennen die Notiz unter
        # ihrem Kopfnamen fuehren, neuere unter dem Dateinamen.
        notiz.recalls = sum(bericht.treffer.get(alias, 0) for alias in notiz.aliase)
        alter = [
            bericht.letztes_alter[alias]
            for alias in notiz.aliase
            if alias in bericht.letztes_alter
        ]
        notiz.letzter_recall_tage = min(alter) if alter else None
