"""Diskussion zwischen Agenten, moderiert von Chatterdome.

WARUM EIN MODERATOR MIT REDERECHT und nicht "jeder schickt an alle": Geht ein
Beitrag an alle anderen, antworten alle gleichzeitig, und jede Antwort erzeugt
wieder mehrere. Nach wenigen Runden reden alle durcheinander, und jede
geweckte Sitzung kostet einen vollen Durchlauf. Hier ist immer genau eine
Sitzung aktiv: der Moderator gibt einem Redner das Wort, wartet auf dessen
Quittung und gibt es weiter.

Der Moderator ist Code, keine Claude-Sitzung. Er kostet keine Tokens, kann
nicht abschweifen, und gleiche Eingaben ergeben gleiche Anweisungen - das
macht die Diskussion als Showcase wiederholbar.

Der Kern bleibt UI-frei. Den Bus erreicht er ueber das Protokoll ``Kanal``,
damit die Tests ohne echte Sitzungen auskommen.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from chatterdome import i18n
from chatterdome.kern.lokale_quelle import LokaleQuelle

ABSENDER = "Chatterdome"
MODERATOR = "Moderator"
"""So heissen Hinweise des Anwenders im Verlauf, den die Redner bekommen."""
THEMA_TOPIC = "diskussion"

WOERTER_JE_BEITRAG = 80
"""Kurze Beitraege lesen sich wie ein Gespraech. Mit 120 kamen Referate mit Fazit."""

KEINE_RECHERCHE = "KEINE RECHERCHE"
"""Erste Zeile einer Vorbereitung, deren Websuche gescheitert ist.

Am 28.09.2026 scheiterten alle elf Suchaufrufe zweier Agenten an einem Ausfall der
Freigabepruefung ("auto mode classifier gave no verdict"). Die Agenten schrieben
trotzdem Notizen, und im Chat sah alles geprueft aus.
"""

STIL = (
    "So klingt ein Beitrag: wie in einem echten Streitgespräch. Geh direkt auf den "
    "letzten Beitrag ein, bring genau EIN Argument, gern mit einer Rückfrage. Kein "
    "Fazit, keine Zusammenfassung, keine Wiederholung von bereits Gesagtem, keine "
    "Aufzählungen, keine Überschriften."
)
"""Gegen die Referate aus den ersten Laeufen. Michael: "keine Zusammenfassungen im
Chat, sondern wirklich eine Diskussion"."""

FRIST_SEKUNDEN = 240.0
"""So lange wartet der Moderator auf einen Beitrag, dann gilt die Runde als ausgelassen."""

FRIST_RECHERCHE_SEKUNDEN = 600.0
"""Die Vorbereitung mit Websuche darf deutlich laenger dauern als ein Beitrag."""

TAKT_SEKUNDEN = 3.0
"""Abstand zwischen zwei Blicken auf die Quittung."""

FORMATE = {
    "diskussion": (
        "Eine Diskussion mit Pro und Contra. Vertritt Deine Rolle mit Argumenten, geh auf "
        "die anderen ein und widersprich, wo Du anderer Meinung bist."
    ),
    "team": (
        "Eine Team-Diskussion. Ihr sollt gemeinsam zu einem Ergebnis kommen: greift gute "
        "Vorschläge auf, benennt Schwächen und bringt die Sache voran."
    ),
}


MODELLE = ("", "haiku", "sonnet", "opus")
"""Kurznamen, die ``claude --model`` annimmt (am 28.09.2026 mit haiku und sonnet
geprueft). Leer heisst: die Voreinstellung von Claude Code."""

VORGABE_MODELL = "sonnet"
"""Fuer eine Unterhaltungsdiskussion reicht Sonnet, und Opus frisst Tokens."""


SACHLICH = "sachlich"

STIMMUNGEN = {
    SACHLICH: "",
    "fair": (
        "Ton der Diskussion: fair und respektvoll. Erkenne den stärksten Punkt der "
        "Gegenseite ausdrücklich an, bevor Du widersprichst, und gib zu, wo sie recht hat."
    ),
    "aggressiv": (
        "Ton der Diskussion: angriffslustig und scharf. Zugespitzte Formulierungen, kein "
        "Zugeständnis, hart in der Sache. Keine Beleidigungen - angegriffen wird das "
        "Argument, nicht der Redner."
    ),
    "unfair": (
        "Ton der Diskussion: unfair, mit rhetorischen Tricks. Strohmann, Zuspitzung ins "
        "Absurde, Whataboutism, Themenwechsel, wenn es eng wird. Erfinde dabei keine Fakten "
        "und beleidige niemanden - unfair ist die Rhetorik, nicht der Umgang."
    ),
}
"""Die Stimmung einer Diskussion als Zeile der Anweisung. ``sachlich`` setzt nichts
dazu, das ist das Verhalten vor dieser Auswahl. Als Showcase gedacht: dasselbe Thema
liest sich je Stimmung anders."""

WOERTER_JE_ENTSCHEIDUNG = 50

ENTSCHEIDUNG = "ENTSCHEIDUNG"
"""So beginnt eine Stimme in der Abstimmung. In derselben Zeile wie die Begruendung,
nicht in einer eigenen: eine mehrzeilige Quittung kann abgeschnitten werden, siehe
``absaetze``."""

PRO = "pro"
CONTRA = "contra"

SEITEN = {
    PRO: "PRO: Du beantwortest die Frage mit Ja beziehungsweise stimmst der These zu.",
    CONTRA: "CONTRA: Du beantwortest die Frage mit Nein beziehungsweise widersprichst der These.",
}


@dataclass
class Verbrauch:
    """Tokens einer Diskussion, getrennt nach dem, was sie kosten.

    ``neu`` ist frische Eingabe plus Cache-Erzeugung, ``cache`` die billige
    Cache-Lesung, ``aus`` die Ausgabe - dieselbe Trennung wie in der Statistik.
    """

    neu: int = 0
    cache: int = 0
    aus: int = 0

    def __add__(self, anderer: Verbrauch) -> Verbrauch:
        return Verbrauch(self.neu + anderer.neu, self.cache + anderer.cache,
                         self.aus + anderer.aus)

    @property
    def echt(self) -> int:
        """Alles ausser der Cache-Lesung."""
        return self.neu + self.aus

    @property
    def gesamt(self) -> int:
        return self.neu + self.cache + self.aus


@dataclass
class Teilnehmer:
    """Ein Agent in der Diskussion."""

    name: str
    rolle: str = ""
    """Freitext, der die Haltung ausschmueckt, etwa "Architekt im Konzern"."""
    seite: str = ""
    """``pro`` oder ``contra``. Nur im Format ``diskussion``, leer heisst: wird verteilt."""
    ohne_recherche: str = ""
    """Grund, wenn die Recherche in der Vorbereitung gescheitert ist."""
    sitzung: str = ""
    """Sitzungskennung, sobald bekannt - fuer den Verbrauch aus dem Transkript."""
    modell: str = ""
    """Das Modell, mit dem die Sitzung tatsaechlich lief, laut Bestand. Leer wenn unbekannt."""


@dataclass
class Beitrag:
    """Ein Wortbeitrag oder der Grund, warum er fehlt."""

    runde: int
    name: str
    text: str
    zeit: str
    art: str = "beitrag"
    """``vorbereitung``, ``beitrag``, ``schlusswort``, ``entscheidung``, ``moderator``,
    ``ausgelassen`` oder ``fehler``. ``moderator`` ist ein Hinweis, den der Anwender beim
    Fortsetzen mitgibt, ``entscheidung`` eine Stimme in der Abstimmung am Ende."""
    hinweis: str = ""
    """Vermerk des Moderators, etwa eine deutlich ueberschrittene Laenge."""
    seite: str = ""
    """Seite des Redners, damit die Anzeige ihn einordnen kann, ohne nachzuschlagen."""
    ungeprueft: bool = False
    """Der Redner wollte recherchieren und konnte nicht - seine Fakten sind nicht live geprueft."""


@dataclass
class Diskussion:
    """Was der Dialog oder der Kurzbefehl festlegt, dazu das Protokoll."""

    thema: str
    teilnehmer: list[Teilnehmer]
    format: str = "diskussion"
    runden: int = 3
    recherche: bool = False
    """Vor Runde 1 eine Vorbereitung, in der jeder im Web recherchieren darf."""
    dauer_minuten: float = 0.0
    """0 heisst: nur die Runden begrenzen."""
    positionen: tuple[str, str] = ("", "")
    """Benannte Positionen fuer PRO und CONTRA, etwa ("Unity", "Godot").

    Leer heisst Ja und Nein. Mit Namen geht auch ein Entweder-oder-Thema wie
    "Unity oder Godot?", bei dem Ja und Nein nichts bedeuten.
    """
    schlussworte: bool = False
    """Eine Schlussrunde. Vorgabe aus: die Schlussworte waren faktisch Zusammenfassungen."""
    beitraege: list[Beitrag] = field(default_factory=list)
    ende: str = ""
    """Warum die Diskussion endete, leer solange sie laeuft."""
    zusammenfassung: str = ""
    """Neutrale Zusammenfassung nach dem Ende, siehe ``zusammenfassen``."""
    beginn: str = ""
    """Zeitpunkt des ersten Starts als ISO-Text, gesetzt vom Ablauf."""
    verbrauch: Verbrauch = field(default_factory=Verbrauch)
    kennung: int = 0
    """Nummer im Archiv, 0 solange nicht gespeichert."""
    ohne_kontext: bool = False
    """Frische Sitzungen ohne eigene CLAUDE.md - gilt auch beim Fortsetzen."""
    modell: str = ""
    """Gewaehltes Modell (``haiku``, ``sonnet``, ``opus``), leer fuer die Voreinstellung.

    Gilt fuer frisch gestartete Sitzungen und die Zusammenfassung. Laufende
    Agenten behalten ihr Modell - welches sie hatten, steht je ``Teilnehmer``.
    """
    stimmung: str = SACHLICH
    """Der Ton der Beitraege, ein Schluessel aus ``STIMMUNGEN``."""
    entscheidung: bool = False
    """Am Ende stimmt jeder ab, und die Zusammenfassung nennt das Ergebnis.

    Ohne das liefen Diskussionen 15 Runden lang, ohne dass etwas herauskam
    (Michael, 08.10.2026). Die Abstimmung kommt nach den Runden und auch nach
    Zeitablauf, nicht aber nach einem Stopp von Hand.
    """

    @property
    def gespielte_runden(self) -> int:
        """Hoechste Runde mit einem Eintrag, 0 vor dem ersten Beitrag."""
        return max((b.runde for b in self.beitraege
                    if b.art in ("beitrag", "ausgelassen", "fehler") and b.runde > 0),
                   default=0)

    def pruefen(self) -> str:
        """Liefert den ersten Grund, warum die Diskussion nicht starten kann."""
        if not self.thema.strip():
            return "Es fehlt ein Thema."
        if len(self.teilnehmer) < 2:
            return "Eine Diskussion braucht mindestens zwei Teilnehmer."
        namen = [t.name.lower() for t in self.teilnehmer]
        if len(set(namen)) != len(namen):
            return "Ein Teilnehmer steht doppelt in der Liste."
        if self.format not in FORMATE:
            return f"Unbekanntes Format '{self.format}', erlaubt: {', '.join(FORMATE)}."
        if self.runden < 1:
            return "Es braucht mindestens eine Runde."
        if self.stimmung not in STIMMUNGEN:
            return f"Unbekannte Stimmung '{self.stimmung}', erlaubt: {', '.join(STIMMUNGEN)}."
        if self.format == "diskussion":
            falsch = [t.name for t in self.teilnehmer if t.seite and t.seite not in SEITEN]
            if falsch:
                return f"Unbekannte Seite bei {', '.join(falsch)}, erlaubt: pro, contra."
            seiten = {t.seite for t in self.teilnehmer}
            # Vor dem Verteilen darf eine Seite noch offen sein - dann fuellt
            # seiten_verteilen sie auf, und die Pruefung haelt trotzdem.
            if "" not in seiten and not {PRO, CONTRA} <= seiten:
                return "Eine Diskussion braucht mindestens eine PRO- und eine CONTRA-Stimme."
        return ""

    def position(self, seite: str) -> str:
        """Die Position einer Seite in Worten, fuer Anweisung und Anzeige."""
        pro, contra = self.positionen
        if seite == PRO:
            return pro.strip() or "Ja"
        if seite == CONTRA:
            return contra.strip() or "Nein"
        return ""

    def seiten_verteilen(self) -> None:
        """Teilt Teilnehmern ohne Seite abwechselnd PRO und CONTRA zu.

        Abwechselnd heisst: immer die Seite, die gerade schwaecher besetzt ist,
        bei Gleichstand PRO. So bekommt eine vorgegebene Seite ihren Gegenpart.
        """
        if self.format != "diskussion":
            return
        for teilnehmer in self.teilnehmer:
            if teilnehmer.seite:
                continue
            pro = sum(1 for t in self.teilnehmer if t.seite == PRO)
            contra = sum(1 for t in self.teilnehmer if t.seite == CONTRA)
            teilnehmer.seite = CONTRA if pro > contra else PRO


class Kanal(Protocol):
    """Der Weg zu den Agenten. In echt der Bus, in den Tests eine Attrappe."""

    def senden(self, an: str, text: str) -> tuple[str, str]:
        """Legt einen Auftrag ab, liefert ``(kennung, fehler)``."""
        ...

    def antwort(self, an: str, kennung: str) -> tuple[int | None, str]:
        """Liefert die abschliessende Quittung ``(status, notiz)``, sonst ``(None, "")``."""
        ...


class BusKanal:
    """Der echte Kanal ueber den Kurzbefehl ``chatterdome``."""

    def __init__(self, quelle: LokaleQuelle, host: str) -> None:
        self._quelle = quelle
        self._host = host

    def senden(self, an: str, text: str) -> tuple[str, str]:
        return self._quelle.senden_mit_kennung(
            an, text, topic=THEMA_TOPIC, host=self._host, von=ABSENDER
        )

    def antwort(self, an: str, kennung: str) -> tuple[int | None, str]:
        for auftrag in self._quelle.verlauf(an):
            if auftrag.auftrag_id != kennung:
                continue
            # 202 heisst "angenommen", der Beitrag kommt erst mit der 200.
            # Alles ab 400 ist ebenfalls abschliessend.
            for ereignis in reversed(auftrag.verlauf):
                status = ereignis.status
                if ereignis.art == "quittung" and status is not None and status != 202:
                    return status, ereignis.notiz
        return None, ""


def anweisung(diskussion: Diskussion, redner: Teilnehmer, runde: int, schluss: bool) -> str:
    """Baut den Auftrag an den Redner. Rein und deterministisch.

    Die erste Zeile unterscheidet jeden Auftrag sichtbar vom vorigen. Am
    28.09.2026 begann jeder Auftrag mit derselben Themenzeile, und beide
    Agenten hielten die dritte Runde fuer eine Schleife ("Dritter identischer
    Auftrag", Quittung 208) - der Bus bringt ihnen genau diese Wachsamkeit bei.
    """
    andere = ", ".join(t.name for t in diskussion.teilnehmer if t.name != redner.name)
    if schluss:
        kopf = "Diskussion, Schlussrunde: Du bist dran mit Deinem Schlusswort."
        umfang = "Höchstens 60 Wörter."
    else:
        kopf = (f"Diskussion, Runde {runde} von {diskussion.runden}: Du bist dran, "
                "ein neuer Beitrag ist erbeten.")
        umfang = f"Höchstens {WOERTER_JE_BEITRAG} Wörter, auf Deutsch, im Gesprächston."
    zeilen = [
        kopf,
        umfang,
        STIL,
        "",
        _themenzeile(diskussion),
        FORMATE[diskussion.format],
        f"Du bist {redner.name}. Mit Dir diskutieren: {andere}.",
        "Der Moderator Chatterdome gibt reihum das Wort: Du bekommst je Runde einen eigenen "
        "Auftrag mit dem bisherigen Verlauf. Das ist keine Wiederholung und keine Schleife.",
        "Nenne keine Kunden, Arbeitgeber, Firmen aus Deinem Umfeld und keine Personen - die "
        "Diskussion kann öffentlich gezeigt werden.",
    ]
    if redner.seite in SEITEN:
        zeilen.append(_seite_text(diskussion, redner) + " Bleib dabei, auch wenn die "
                      "Gegenseite gute Argumente bringt.")
    if redner.rolle:
        zeilen.append(f"Deine Rolle: {redner.rolle}")
    if STIMMUNGEN.get(diskussion.stimmung):
        zeilen.append(STIMMUNGEN[diskussion.stimmung])
    if diskussion.entscheidung and not schluss:
        zeilen.append(_ziel_text(diskussion, runde))
    eigene = [b.text for b in diskussion.beitraege
              if b.art == "vorbereitung" and b.name == redner.name]
    if eigene:
        zeilen.append("")
        zeilen.append("Deine Notizen aus der Vorbereitung (nur Du kennst sie):")
        zeilen += eigene
    bisher = [b for b in diskussion.beitraege if b.art in ("beitrag", "schlusswort", "moderator")]
    if bisher:
        zeilen.append("")
        zeilen.append("Bisheriger Verlauf:")
        zeilen += [f"[{MODERATOR}] {b.text}" if b.art == "moderator" else f"[{b.name}] {b.text}"
                   for b in bisher]
        if any(b.art == "moderator" for b in bisher):
            zeilen.append("")
            zeilen.append(f"Einträge mit [{MODERATOR}] sind neue Informationen des Moderators. "
                          "Sie stimmen, nimm sie ernst und geh darauf ein, wo sie Deine "
                          "Position berühren.")
    zeilen.append("")
    if schluss:
        zeilen.append("Was bleibt für Dich als Ergebnis? " + umfang)
    else:
        zeilen.append(("Antworte jetzt auf den letzten Beitrag. " if bisher else
                       "Du eröffnest die Diskussion mit Deinem stärksten Argument. ") + umfang)
    zeilen.append(
        "Benutze keine Werkzeuge ausser der Quittung und lies keine Dateien. Deinen Beitrag "
        "schickst Du ausschliesslich als Notiz der 200-Quittung auf diesen Auftrag, "
        "wörtlich und vollständig. Was nur in Deinem Fenster steht, erreicht niemanden."
    )
    return "\n".join(zeilen)


def _themenzeile(diskussion: Diskussion) -> str:
    """Das Thema als Zeile eines Auftrags.

    Bei PRO und CONTRA ist es eine Frage, und die Seiten sind Antworten darauf
    (Michael, 08.10.2026) - so heisst es dann auch.
    """
    wort = "Frage" if diskussion.format == "diskussion" else "Thema"
    return f'{wort}: "{diskussion.thema}"'


def _ziel_text(diskussion: Diskussion, runde: int) -> str:
    """Die Zielvorgabe einer Diskussion, die mit einer Entscheidung enden soll."""
    ziel = (f"Ziel: Nach Runde {diskussion.runden} wird abgestimmt, am Ende steht eine "
            "Entscheidung. Arbeite darauf hin und mach keine neuen Baustellen auf.")
    if runde < diskussion.runden:
        return ziel
    if diskussion.format == "team":
        return (f"{ziel} Das ist die letzte Runde: nenne den konkreten Vorschlag, den Du "
                "mittragen würdest.")
    return f"{ziel} Das ist die letzte Runde: bring das Argument, das den Ausschlag geben soll."


def abstimmung(diskussion: Diskussion, redner: Teilnehmer) -> str:
    """Der Auftrag fuer die Abstimmung am Ende. Rein und deterministisch.

    Jeder stimmt fuer sich: die Stimmen der anderen stehen nicht im Verlauf,
    sonst schloesse sich der Zweite dem Ersten an. Im Format ``diskussion``
    legt der Redner seine Seite ab - mit "Bleib dabei" im Ohr stimmte sonst
    jeder fuer die eigene Seite, und es stuende immer unentschieden.
    """
    zeilen = [
        "Diskussion, Abstimmung: Die Runden sind vorbei, jetzt wird entschieden.",
        f"Höchstens {WOERTER_JE_ENTSCHEIDUNG} Wörter, auf Deutsch, in einer einzigen Zeile.",
        "",
        _themenzeile(diskussion),
        f"Du bist {redner.name}.",
    ]
    if diskussion.format == "diskussion" and redner.seite in SEITEN:
        pro, contra = diskussion.position(PRO), diskussion.position(CONTRA)
        zeilen.append(
            f'Du hast in der Diskussion die Antwort "{diskussion.position(redner.seite)}" '
            "vertreten. Leg "
            "diese Rolle jetzt ab: es zählt Dein ehrliches Urteil nach den Argumenten, die "
            "gefallen sind, auch wenn es gegen Deine Seite ausfällt."
        )
        wahl = f'eine der beiden Antworten: "{pro}" oder "{contra}"'
    else:
        wahl = "der Vorschlag, den das Team umsetzen soll, in einem Satz"
    bisher = [b for b in diskussion.beitraege if b.art in ("beitrag", "schlusswort", "moderator")]
    zeilen.append("")
    zeilen.append("Verlauf der Diskussion:")
    zeilen += [f"[{MODERATOR}] {b.text}" if b.art == "moderator" else f"[{b.name}] {b.text}"
               for b in bisher]
    zeilen += [
        "",
        f'Beginne mit "{ENTSCHEIDUNG}: " und nenne dahinter {wahl}. Begründe danach kurz. '
        'Eine Enthaltung oder "kommt darauf an" gilt nicht.',
        "Benutze keine Werkzeuge ausser der Quittung und lies keine Dateien. Deine Stimme "
        "schickst Du ausschliesslich als Notiz der 200-Quittung auf diesen Auftrag, "
        "wörtlich und vollständig. Was nur in Deinem Fenster steht, erreicht niemanden.",
    ]
    return "\n".join(zeilen)


def _seite_text(diskussion: Diskussion, redner: Teilnehmer) -> str:
    """Welche Position der Redner vertritt und wer dagegen steht."""
    gegenseite = CONTRA if redner.seite == PRO else PRO
    gegner = ", ".join(t.name for t in diskussion.teilnehmer if t.seite == gegenseite)
    if any(p.strip() for p in diskussion.positionen):
        return (f'Deine Antwort auf die Frage: "{diskussion.position(redner.seite)}". Die '
                f'Gegenantwort "{diskussion.position(gegenseite)}" vertritt {gegner}.')
    return f"Deine Seite ist {SEITEN[redner.seite]} Gegenseite: {gegner}."


def vorbereitung(diskussion: Diskussion, redner: Teilnehmer) -> str:
    """Der Auftrag fuer die Vorbereitungsrunde. Rein und deterministisch.

    Recherche nur hier und nicht in jeder Runde: eine Runde mit Websuche
    dauert Minuten, und der Live-Charakter der Diskussion ginge verloren.
    """
    zeilen = [
        "Diskussion, Vorbereitung: Recherchiere für Deine Seite, bevor die Diskussion beginnt.",
        "Höchstens fünf Stichpunkte, je mit Quelle (URL). Höchstens 150 Wörter.",
        "",
        _themenzeile(diskussion),
        FORMATE[diskussion.format],
        f"Du bist {redner.name}.",
    ]
    if redner.seite in SEITEN:
        zeilen.append(_seite_text(diskussion, redner))
    if redner.rolle:
        zeilen.append(f"Deine Rolle: {redner.rolle}")
    zeilen += [
        "Du darfst dafür WebSearch und WebFetch benutzen, sonst keine Werkzeuge, und lies "
        "keine lokalen Dateien. Suche aktuelle Fakten, keine Meinungsartikel allein.",
        "Scheitert ein Aufruf mit \"classifier gave no verdict\", ist das ein vorübergehender "
        "Ausfall: versuch es einmal erneut. Kommst Du trotzdem an keine Quelle, beginne Deine "
        f"Notiz mit der Zeile \"{KEINE_RECHERCHE}: <Grund>\" und erfinde keine Quellen.",
        "Nenne keine Kunden, Arbeitgeber, Firmen aus Deinem Umfeld und keine Personen - die "
        "Diskussion kann öffentlich gezeigt werden.",
        "Die Notizen bekommst nur Du in den folgenden Runden zurück. Schick sie "
        "ausschliesslich als Notiz der 200-Quittung auf diesen Auftrag.",
    ]
    return "\n".join(zeilen)


_SATZENDE = re.compile(r'(?<=[.!?])\s+(?=["„»A-ZÄÖÜ])')

_KEIN_SATZENDE = {"bzw.", "ca.", "vgl.", "nr.", "dr.", "prof.", "ggf.", "evtl.", "inkl.",
                  "sog.", "bspw.", "etc.", "usw.", "st.", "mio.", "mrd."}
"""Abkuerzungen, nach denen oft ein Grossbuchstabe folgt, ohne dass ein Satz endet."""


def _saetze(text: str) -> list[str]:
    """Zerlegt einen Absatz in Saetze.

    Kein Satzende sind ein einzelner Buchstabe ("z. B."), eine Ordnungszahl
    ("am 3. Oktober") und die Abkuerzungen aus ``_KEIN_SATZENDE``.
    """
    saetze: list[str] = []
    anfang = 0
    for treffer in _SATZENDE.finditer(text):
        davor = text[anfang:treffer.start()].split()
        wort = davor[-1] if davor else ""
        kern = wort.rstrip(".!?")
        if (wort.endswith(".") and (len(kern) <= 1 or kern.isdigit()
                                    or wort.lower() in _KEIN_SATZENDE)):
            continue
        saetze.append(text[anfang:treffer.start()])
        anfang = treffer.end()
    saetze.append(text[anfang:])
    return saetze


ABSATZ_AB_WOERTERN = 40
"""Kuerzere Beitraege bleiben ein Absatz."""


def absaetze(text: str) -> list[str]:
    """Teilt einen Beitrag fuer die Anzeige in Absaetze.

    Eigene Zeilenumbrueche des Redners bleiben. Ein langer Block ohne Umbruch
    wird an der Satzgrenze geteilt, die der Mitte am naechsten liegt - so hat
    Michael es am 28.09.2026 in einem Bildschirmfoto markiert. Den Agenten
    wird das bewusst nicht aufgetragen: eine mehrzeilige Quittung koennte
    ueber einen .cmd-Wrapper am ersten Umbruch abgeschnitten werden.
    """
    bloecke = [b.strip() for b in text.splitlines() if b.strip()]
    ergebnis: list[str] = []
    for block in bloecke:
        saetze = _saetze(block)
        woerter = len(block.split())
        if woerter < ABSATZ_AB_WOERTERN or len(saetze) < 2:
            ergebnis.append(block)
            continue
        bisher = 0
        beste, abstand = 1, float(woerter)
        for i, satz in enumerate(saetze[:-1], start=1):
            bisher += len(satz.split())
            if abs(bisher - woerter / 2) < abstand:
                beste, abstand = i, abs(bisher - woerter / 2)
        ergebnis.append(" ".join(saetze[:beste]))
        ergebnis.append(" ".join(saetze[beste:]))
    return ergebnis


def _jetzt() -> str:
    return datetime.now().strftime("%H:%M:%S")


def endegrund(schluessel: str, vorgabe: str, **werte: object) -> str:
    """Der Grund, aus dem eine Diskussion endete, in der Sprache der Oberflaeche.

    Ohne geladene Sprache (etwa im Kommandozeilenwerkzeug) liefert ``i18n.t`` den
    Schluessel zurueck, dann gilt die deutsche Vorgabe.

    :param schluessel: Sprachschluessel des Grunds.
    :param vorgabe: deutscher Text mit denselben Platzhaltern.
    :param werte: Werte fuer die Platzhalter.
    :returns: der uebersetzte Grund.
    """
    text = i18n.t(schluessel, **werte)
    return vorgabe.format(**werte) if text == schluessel else text


def moderieren(
    diskussion: Diskussion,
    kanal: Kanal,
    *,
    beim_beitrag: Callable[[Beitrag], None] | None = None,
    beim_wort: Callable[[Teilnehmer, int], None] | None = None,
    beim_vorbereiten: Callable[[list[Teilnehmer]], None] | None = None,
    stopp: threading.Event | None = None,
    uhr: Callable[[], float] = time.monotonic,
    schlafen: Callable[[float], None] = time.sleep,
    frist: float = FRIST_SEKUNDEN,
    frist_recherche: float = FRIST_RECHERCHE_SEKUNDEN,
    takt: float = TAKT_SEKUNDEN,
) -> Diskussion:
    """Fuehrt die Diskussion reihum bis Rundenzahl, Zeit oder Stopp, dann die Schlussworte.

    :param beim_beitrag: wird nach jedem Eintrag im Protokoll aufgerufen, fuer die Live-Ansicht.
    :param beim_wort: wird gerufen, bevor ein Redner das Wort bekommt (Runde 0 = Schlusswort).
    :param beim_vorbereiten: bekommt die Teilnehmer, deren Recherche gerade beginnt.
    :param stopp: von aussen gesetzt, beendet die Diskussion nach dem laufenden Beitrag.
    :returns: dieselbe Diskussion mit gefuelltem Protokoll und ``ende``.
    """
    diskussion.seiten_verteilen()
    grund = diskussion.pruefen()
    if grund:
        diskussion.ende = grund
        return diskussion

    stopp = stopp or threading.Event()
    beginn = uhr()
    grenze = beginn + diskussion.dauer_minuten * 60 if diskussion.dauer_minuten > 0 else None
    aktiv = list(diskussion.teilnehmer)

    def eintragen(beitrag: Beitrag) -> None:
        diskussion.beitraege.append(beitrag)
        if beim_beitrag is not None:
            beim_beitrag(beitrag)

    def wort_geben(redner: Teilnehmer, runde: int, schluss: bool,
                   abstimmen: bool = False) -> None:
        if beim_wort is not None:
            beim_wort(redner, 0 if schluss or abstimmen else runde)
        auftrag = (abstimmung(diskussion, redner) if abstimmen
                   else anweisung(diskussion, redner, runde, schluss))
        kennung, fehler = kanal.senden(redner.name, auftrag)
        if fehler:
            # Nicht erreichbar: faellt aus der Reihe, statt jede Runde erneut zu scheitern.
            eintragen(Beitrag(runde, redner.name, fehler, _jetzt(), "fehler"))
            aktiv.remove(redner)
            return
        abgabe = uhr() + frist
        while uhr() < abgabe:
            status, notiz = kanal.antwort(redner.name, kennung)
            if status == 200 and notiz.strip():
                art = ("entscheidung" if abstimmen else
                       "schlusswort" if schluss else "beitrag")
                text = notiz.strip()
                # Nicht kuerzen - ein abgeschnittener Satz waere schlimmer als ein
                # langer. Aber vermerken: im Probelauf kamen 253 statt 120 Woerter.
                wortgrenze = (WOERTER_JE_ENTSCHEIDUNG if abstimmen else
                              60 if schluss else WOERTER_JE_BEITRAG)
                woerter = len(text.split())
                zu_lang = woerter > wortgrenze * 1.5
                hinweis = f"{woerter} statt höchstens {wortgrenze} Wörter" if zu_lang else ""
                eintragen(Beitrag(runde, redner.name, text, _jetzt(), art, hinweis,
                                  seite=redner.seite,
                                  ungeprueft=bool(redner.ohne_recherche)))
                return
            if status is not None:
                text = f"Quittung {status}" + (f": {notiz}" if notiz else " ohne Beitrag")
                eintragen(Beitrag(runde, redner.name, text, _jetzt(), "fehler"))
                return
            if stopp.is_set():
                eintragen(Beitrag(runde, redner.name, "abgebrochen", _jetzt(), "ausgelassen"))
                return
            schlafen(takt)
        grund = f"keine Antwort nach {frist:.0f} s"
        eintragen(Beitrag(runde, redner.name, grund, _jetzt(), "ausgelassen"))

    def vorbereiten() -> None:
        # Parallel: in der Vorbereitung redet niemand mit niemandem, also muss
        # auch niemand auf den anderen warten.
        offen: dict[str, str] = {}
        for redner in list(aktiv):
            kennung, fehler = kanal.senden(redner.name, vorbereitung(diskussion, redner))
            if fehler:
                eintragen(Beitrag(0, redner.name, fehler, _jetzt(), "fehler"))
                aktiv.remove(redner)
            else:
                offen[redner.name] = kennung
        if beim_vorbereiten is not None and offen:
            beim_vorbereiten([t for t in aktiv if t.name in offen])
        nach_name = {t.name: t for t in aktiv}
        abgabe = uhr() + frist_recherche
        while offen and uhr() < abgabe and not stopp.is_set():
            for name, kennung in list(offen.items()):
                status, notiz = kanal.antwort(name, kennung)
                if status is None:
                    continue
                del offen[name]
                teilnehmer = nach_name[name]
                if status == 200 and notiz.strip():
                    text = notiz.strip()
                    erste = text.splitlines()[0].strip()
                    if erste.upper().startswith(KEINE_RECHERCHE):
                        teilnehmer.ohne_recherche = erste[len(KEINE_RECHERCHE):].strip(" :-")
                        hinweis = "Recherche gescheitert, Fakten nicht live geprüft"
                    else:
                        hinweis = ""
                    eintragen(Beitrag(0, name, text, _jetzt(), "vorbereitung", hinweis,
                                      seite=teilnehmer.seite,
                                      ungeprueft=bool(teilnehmer.ohne_recherche)))
                else:
                    teilnehmer.ohne_recherche = f"Quittung {status}"
                    text = f"Vorbereitung: Quittung {status}" + (f": {notiz}" if notiz else "")
                    eintragen(Beitrag(0, name, text, _jetzt(), "fehler", seite=teilnehmer.seite))
            if offen:
                schlafen(takt)
        # Wer in der Vorbereitung schweigt, diskutiert trotzdem mit - nur ohne Notizen.
        for name in offen:
            nach_name[name].ohne_recherche = "keine Antwort"
            grund = f"Vorbereitung ohne Ergebnis nach {frist_recherche:.0f} s"
            eintragen(Beitrag(0, name, grund, _jetzt(), "ausgelassen",
                              seite=nach_name[name].seite))

    # Beim Fortsetzen steht die Vorbereitung schon im Protokoll, die Notizen
    # gehen weiter in jede Anweisung. Und es geht nach der letzten Runde weiter.
    erste_runde = diskussion.gespielte_runden + 1
    if diskussion.recherche and erste_runde == 1:
        vorbereiten()

    ende = (endegrund("discussion.end_round", "1 Runde gespielt") if diskussion.runden == 1
            else endegrund("discussion.end_rounds", "{runden} Runden gespielt",
                           runden=diskussion.runden))
    for runde in range(erste_runde, diskussion.runden + 1):
        for redner in list(aktiv):
            if stopp.is_set():
                ende = endegrund("discussion.end_stopped", "von Hand gestoppt")
                break
            if grenze is not None and uhr() >= grenze:
                ende = endegrund("discussion.end_time", "Zeit abgelaufen nach {minuten} Minuten",
                                 minuten=f"{diskussion.dauer_minuten:g}")
                break
            if redner in aktiv:
                wort_geben(redner, runde, schluss=False)
            if len(aktiv) < 2:
                ende = endegrund("discussion.end_too_few",
                                 "weniger als zwei Teilnehmer erreichbar")
                break
        else:
            continue
        break

    # Schlussworte nur auf Wunsch, dann auch nach Zeitablauf, nicht aber nach
    # einem Stopp von Hand - wer stoppt, will, dass es aufhoert.
    if diskussion.schlussworte and not stopp.is_set() and len(aktiv) >= 2:
        for redner in list(aktiv):
            wort_geben(redner, diskussion.runden, schluss=True)

    # Die Abstimmung zuletzt, unter denselben Bedingungen wie die Schlussworte.
    if diskussion.entscheidung and len(aktiv) >= 2:
        for redner in list(aktiv):
            if stopp.is_set():
                break
            wort_geben(redner, diskussion.runden, schluss=False, abstimmen=True)

    diskussion.ende = ende
    return diskussion


def hinweis_anhaengen(diskussion: Diskussion, text: str) -> Beitrag | None:
    """Haengt einen Hinweis des Anwenders an, etwa neue Fakten beim Fortsetzen.

    Er steht hinter der letzten gespielten Runde und geht mit dem Verlauf an
    jeden folgenden Redner. Leerer Text haengt nichts an.

    Auch waehrend einer laufenden Diskussion ("Reinrufen"): der Moderator
    liest ``beitraege`` fuer jede neue Anweisung, der Hinweis erreicht also den
    naechsten Redner. ``list.append`` ist unter CPython atomar, der Faden des
    Moderators sieht die Liste davor oder danach, nie halb.

    :returns: der angehaengte Eintrag, None bei leerem Text.
    """
    if not text.strip():
        return None
    beitrag = Beitrag(diskussion.gespielte_runden, MODERATOR, text.strip(), _jetzt(), "moderator")
    diskussion.beitraege.append(beitrag)
    return beitrag


def zusammenfassung_auftrag(diskussion: Diskussion) -> str:
    """Der Auftrag an das Modell, das die Diskussion zusammenfasst. Rein und deterministisch.

    Bewusst ohne die Recherche-Notizen: zusammengefasst wird, was in der
    Diskussion gesagt wurde, nicht was jemand vorbereitet hat.
    """
    gesagt = [b for b in diskussion.beitraege if b.art in ("beitrag", "schlusswort", "moderator")]
    stimmen = abgegebene_stimmen(diskussion)
    zeilen = [
        "Fasse die folgende Diskussion neutral zusammen, auf Deutsch, höchstens "
        f"{250 if stimmen else 200} Wörter.",
        "Gliederung: je ein kurzer Absatz zu den Kernargumenten jeder Seite, dann wo die "
        "Teilnehmer sich einig waren, dann was offen blieb.",
    ]
    if stimmen:
        zeilen.append(
            'Schließe mit einem eigenen Absatz, der mit "Entscheidung:" beginnt: das Ergebnis '
            "der Abstimmung mit dem Stimmenverhältnis und dem Grund, der den Ausschlag gab. "
            "Bei Gleichstand entscheidest Du nach der Stärke der Argumente im Protokoll und "
            "sagst dazu, dass es ein Stichentscheid ist. Ein Unentschieden gibt es nicht."
        )
    zeilen += [
        "Stütze Dich nur auf das Protokoll und ergänze keine eigenen Fakten. "
        + ("" if stimmen else "Erkläre niemanden zum Sieger. ")
        + "Nenne keine Kunden, Firmen aus dem Umfeld oder Personen außer den Teilnehmernamen.",
        "Antworte nur mit der Zusammenfassung, ohne Einleitung und ohne Überschrift.",
    ]
    if STIMMUNGEN.get(diskussion.stimmung):
        zeilen.append(f'Der Ton war vorgegeben ("{diskussion.stimmung}") und gehört zur '
                      "Aufgabe der Teilnehmer: bewerte ihn nicht.")
    zeilen += [
        "",
        _themenzeile(diskussion),
    ]
    for t in diskussion.teilnehmer:
        seite = f" ({t.seite.upper()})" if t.seite else ""
        zeilen.append(f"Teilnehmer: {t.name}{seite}")
    zeilen.append("")
    for b in gesagt:
        if b.art == "moderator":
            zeilen.append(f"[{MODERATOR}, neue Information] {b.text}")
            continue
        kopf = "Schlusswort" if b.art == "schlusswort" else f"Runde {b.runde}"
        zeilen.append(f"[{b.name}, {kopf}] {b.text}")
    if stimmen:
        zeilen.append("")
        zeilen += [f"[{b.name}, Abstimmung] {b.text}" for b in stimmen]
    return "\n".join(zeilen)


def abgegebene_stimmen(diskussion: Diskussion) -> list[Beitrag]:
    """Die Stimmen der letzten Abstimmung.

    Nur die nach dem letzten Wortbeitrag: wird eine entschiedene Diskussion
    fortgesetzt, stehen die alten Stimmen noch im Protokoll, gelten aber nicht mehr.
    """
    letzter = max((i for i, b in enumerate(diskussion.beitraege)
                   if b.art in ("beitrag", "schlusswort")), default=-1)
    return [b for b in diskussion.beitraege[letzter + 1:] if b.art == "entscheidung"]


def zusammenfassen(diskussion: Diskussion, modell: Callable[[str], tuple[str, str]]) -> str:
    """Laesst die Diskussion zusammenfassen und legt das Ergebnis in ``zusammenfassung``.

    Ein neutraler Aufruf statt eines Teilnehmers: wer mitdiskutiert hat, fasst
    parteiisch zusammen.

    :param modell: bekommt den Auftrag, liefert ``(text, fehler)``.
    :returns: Leer bei Erfolg, sonst der Grund.
    """
    if not any(b.art in ("beitrag", "schlusswort") for b in diskussion.beitraege):
        return "Es gibt keine Beiträge, die sich zusammenfassen liessen."
    text, fehler = modell(zusammenfassung_auftrag(diskussion))
    if fehler:
        return fehler
    if not text.strip():
        return "Das Modell hat eine leere Zusammenfassung geliefert."
    diskussion.zusammenfassung = text.strip()
    return ""


def als_markdown(diskussion: Diskussion) -> str:
    """Das Protokoll zum Nachlesen und Teilen."""
    zeilen = [f"# {diskussion.thema}", ""]

    def beschreibung(t: Teilnehmer) -> str:
        zusatz = ", ".join(x for x in (t.seite.upper(), t.rolle) if x)
        return f"{t.name} ({zusatz})" if zusatz else t.name

    zeilen.append("Teilnehmer: " + ", ".join(beschreibung(t) for t in diskussion.teilnehmer))
    zeilen.append(f"Modell: {diskussion.modell or 'Voreinstellung'}")
    if diskussion.stimmung != SACHLICH:
        zeilen.append(f"Stimmung: {diskussion.stimmung}")
    zeilen.append("")
    for b in diskussion.beitraege:
        if b.art == "beitrag":
            zeilen.append(f"**{b.name}** (Runde {b.runde}, {b.zeit}): {b.text}")
        elif b.art == "schlusswort":
            zeilen.append(f"**{b.name}**, Schlusswort ({b.zeit}): {b.text}")
        elif b.art == "entscheidung":
            zeilen.append(f"**{b.name}**, Abstimmung ({b.zeit}): {b.text}")
        elif b.art == "vorbereitung":
            zeilen.append(f"**{b.name}**, Recherche ({b.zeit}):\n\n{b.text}")
        elif b.art == "moderator":
            zeilen.append(f"> **{MODERATOR}** ({b.zeit}): {b.text}")
        else:
            zeilen.append(f"_{b.name}, Runde {b.runde}: {b.text}_")
        if b.hinweis:
            zeilen.append(f"_Moderator: {b.hinweis}_")
        zeilen.append("")
    if diskussion.ende:
        zeilen.append(f"_Ende: {diskussion.ende}_")
    if diskussion.zusammenfassung:
        zeilen += ["", "## Zusammenfassung", "", diskussion.zusammenfassung]
    return "\n".join(zeilen) + "\n"
