"""Diskussion zwischen Agenten, moderiert von Sanctuary.

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

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from claude_sanctuary.kern.lokale_quelle import LokaleQuelle

ABSENDER = "Sanctuary"
THEMA_TOPIC = "diskussion"

WOERTER_JE_BEITRAG = 120
"""Kurze Beitraege lesen sich live besser und halten den wachsenden Kontext klein."""

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


PRO = "pro"
CONTRA = "contra"

SEITEN = {
    PRO: "PRO: Du beantwortest die Frage mit Ja beziehungsweise stimmst der These zu.",
    CONTRA: "CONTRA: Du beantwortest die Frage mit Nein beziehungsweise widersprichst der These.",
}


@dataclass
class Teilnehmer:
    """Ein Agent in der Diskussion."""

    name: str
    rolle: str = ""
    """Freitext, der die Haltung ausschmueckt, etwa "Architekt im Konzern"."""
    seite: str = ""
    """``pro`` oder ``contra``. Nur im Format ``diskussion``, leer heisst: wird verteilt."""


@dataclass
class Beitrag:
    """Ein Wortbeitrag oder der Grund, warum er fehlt."""

    runde: int
    name: str
    text: str
    zeit: str
    art: str = "beitrag"
    """``vorbereitung``, ``beitrag``, ``schlusswort``, ``ausgelassen`` oder ``fehler``."""
    hinweis: str = ""
    """Vermerk des Moderators, etwa eine deutlich ueberschrittene Laenge."""


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
    beitraege: list[Beitrag] = field(default_factory=list)
    ende: str = ""
    """Warum die Diskussion endete, leer solange sie laeuft."""
    zusammenfassung: str = ""
    """Neutrale Zusammenfassung nach dem Ende, siehe ``zusammenfassen``."""

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
    """Der echte Kanal ueber den Kurzbefehl ``sanctuary``."""

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
        umfang = (f"Höchstens {WOERTER_JE_BEITRAG} Wörter, auf Deutsch, im Gesprächston, "
                  "keine Aufzählungen und keine Überschriften.")
    zeilen = [
        kopf,
        umfang,
        "",
        f'Thema: "{diskussion.thema}"',
        FORMATE[diskussion.format],
        f"Du bist {redner.name}. Mit Dir diskutieren: {andere}.",
        "Der Moderator Sanctuary gibt reihum das Wort: Du bekommst je Runde einen eigenen "
        "Auftrag mit dem bisherigen Verlauf. Das ist keine Wiederholung und keine Schleife.",
        "Nenne keine Kunden, Arbeitgeber, Firmen aus Deinem Umfeld und keine Personen - die "
        "Diskussion kann öffentlich gezeigt werden.",
    ]
    if redner.seite in SEITEN:
        gegner = [t.name for t in diskussion.teilnehmer if t.seite and t.seite != redner.seite]
        zeilen.append(f"Deine Seite ist {SEITEN[redner.seite]} Bleib dabei, auch wenn die "
                      f"Gegenseite gute Argumente bringt. Gegenseite: {', '.join(gegner)}.")
    if redner.rolle:
        zeilen.append(f"Deine Rolle: {redner.rolle}")
    eigene = [b.text for b in diskussion.beitraege
              if b.art == "vorbereitung" and b.name == redner.name]
    if eigene:
        zeilen.append("")
        zeilen.append("Deine Notizen aus der Vorbereitung (nur Du kennst sie):")
        zeilen += eigene
    bisher = [b for b in diskussion.beitraege if b.art in ("beitrag", "schlusswort")]
    if bisher:
        zeilen.append("")
        zeilen.append("Bisheriger Verlauf:")
        zeilen += [f"[{b.name}] {b.text}" for b in bisher]
    zeilen.append("")
    if schluss:
        zeilen.append("Was bleibt für Dich als Ergebnis? " + umfang)
    else:
        zeilen.append(("Geh auf das bisher Gesagte ein. " if bisher else
                       "Du eröffnest die Diskussion. ") + umfang)
    zeilen.append(
        "Benutze keine Werkzeuge ausser der Quittung und lies keine Dateien. Deinen Beitrag "
        "schickst Du ausschliesslich als Notiz der 200-Quittung auf diesen Auftrag, "
        "wörtlich und vollständig. Was nur in Deinem Fenster steht, erreicht niemanden."
    )
    return "\n".join(zeilen)


def vorbereitung(diskussion: Diskussion, redner: Teilnehmer) -> str:
    """Der Auftrag fuer die Vorbereitungsrunde. Rein und deterministisch.

    Recherche nur hier und nicht in jeder Runde: eine Runde mit Websuche
    dauert Minuten, und der Live-Charakter der Diskussion ginge verloren.
    """
    zeilen = [
        "Diskussion, Vorbereitung: Recherchiere für Deine Seite, bevor die Diskussion beginnt.",
        "Höchstens fünf Stichpunkte, je mit Quelle (URL). Höchstens 150 Wörter.",
        "",
        f'Thema: "{diskussion.thema}"',
        FORMATE[diskussion.format],
        f"Du bist {redner.name}.",
    ]
    if redner.seite in SEITEN:
        zeilen.append(f"Deine Seite ist {SEITEN[redner.seite]}")
    if redner.rolle:
        zeilen.append(f"Deine Rolle: {redner.rolle}")
    zeilen += [
        "Du darfst dafür WebSearch und WebFetch benutzen, sonst keine Werkzeuge, und lies "
        "keine lokalen Dateien. Suche aktuelle Fakten, keine Meinungsartikel allein.",
        "Nenne keine Kunden, Arbeitgeber, Firmen aus Deinem Umfeld und keine Personen - die "
        "Diskussion kann öffentlich gezeigt werden.",
        "Die Notizen bekommst nur Du in den folgenden Runden zurück. Schick sie "
        "ausschliesslich als Notiz der 200-Quittung auf diesen Auftrag.",
    ]
    return "\n".join(zeilen)


def _jetzt() -> str:
    return datetime.now().strftime("%H:%M:%S")


def moderieren(
    diskussion: Diskussion,
    kanal: Kanal,
    *,
    beim_beitrag: Callable[[Beitrag], None] | None = None,
    stopp: threading.Event | None = None,
    uhr: Callable[[], float] = time.monotonic,
    schlafen: Callable[[float], None] = time.sleep,
    frist: float = FRIST_SEKUNDEN,
    frist_recherche: float = FRIST_RECHERCHE_SEKUNDEN,
    takt: float = TAKT_SEKUNDEN,
) -> Diskussion:
    """Fuehrt die Diskussion reihum bis Rundenzahl, Zeit oder Stopp, dann die Schlussworte.

    :param beim_beitrag: wird nach jedem Eintrag im Protokoll aufgerufen, fuer die Live-Ansicht.
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

    def wort_geben(redner: Teilnehmer, runde: int, schluss: bool) -> None:
        kennung, fehler = kanal.senden(redner.name, anweisung(diskussion, redner, runde, schluss))
        if fehler:
            # Nicht erreichbar: faellt aus der Reihe, statt jede Runde erneut zu scheitern.
            eintragen(Beitrag(runde, redner.name, fehler, _jetzt(), "fehler"))
            aktiv.remove(redner)
            return
        abgabe = uhr() + frist
        while uhr() < abgabe:
            status, notiz = kanal.antwort(redner.name, kennung)
            if status == 200 and notiz.strip():
                art = "schlusswort" if schluss else "beitrag"
                text = notiz.strip()
                # Nicht kuerzen - ein abgeschnittener Satz waere schlimmer als ein
                # langer. Aber vermerken: im Probelauf kamen 253 statt 120 Woerter.
                wortgrenze = 60 if schluss else WOERTER_JE_BEITRAG
                woerter = len(text.split())
                zu_lang = woerter > wortgrenze * 1.5
                hinweis = f"{woerter} statt höchstens {wortgrenze} Wörter" if zu_lang else ""
                eintragen(Beitrag(runde, redner.name, text, _jetzt(), art, hinweis))
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
        abgabe = uhr() + frist_recherche
        while offen and uhr() < abgabe and not stopp.is_set():
            for name, kennung in list(offen.items()):
                status, notiz = kanal.antwort(name, kennung)
                if status is None:
                    continue
                del offen[name]
                if status == 200 and notiz.strip():
                    eintragen(Beitrag(0, name, notiz.strip(), _jetzt(), "vorbereitung"))
                else:
                    text = f"Vorbereitung: Quittung {status}" + (f": {notiz}" if notiz else "")
                    eintragen(Beitrag(0, name, text, _jetzt(), "fehler"))
            if offen:
                schlafen(takt)
        # Wer in der Vorbereitung schweigt, diskutiert trotzdem mit - nur ohne Notizen.
        for name in offen:
            grund = f"Vorbereitung ohne Ergebnis nach {frist_recherche:.0f} s"
            eintragen(Beitrag(0, name, grund, _jetzt(), "ausgelassen"))

    if diskussion.recherche:
        vorbereiten()

    ende = "1 Runde gespielt" if diskussion.runden == 1 else f"{diskussion.runden} Runden gespielt"
    for runde in range(1, diskussion.runden + 1):
        for redner in list(aktiv):
            if stopp.is_set():
                ende = "von Hand gestoppt"
                break
            if grenze is not None and uhr() >= grenze:
                ende = f"Zeit abgelaufen nach {diskussion.dauer_minuten:g} Minuten"
                break
            if redner in aktiv:
                wort_geben(redner, runde, schluss=False)
            if len(aktiv) < 2:
                ende = "weniger als zwei Teilnehmer erreichbar"
                break
        else:
            continue
        break

    # Schlussworte auch nach Zeitablauf, nicht aber nach einem Stopp von Hand -
    # wer stoppt, will, dass es aufhoert.
    if not stopp.is_set() and len(aktiv) >= 2:
        for redner in list(aktiv):
            wort_geben(redner, diskussion.runden, schluss=True)

    diskussion.ende = ende
    return diskussion


def zusammenfassung_auftrag(diskussion: Diskussion) -> str:
    """Der Auftrag an das Modell, das die Diskussion zusammenfasst. Rein und deterministisch.

    Bewusst ohne die Recherche-Notizen: zusammengefasst wird, was in der
    Diskussion gesagt wurde, nicht was jemand vorbereitet hat.
    """
    gesagt = [b for b in diskussion.beitraege if b.art in ("beitrag", "schlusswort")]
    zeilen = [
        "Fasse die folgende Diskussion neutral zusammen, auf Deutsch, höchstens 200 Wörter.",
        "Gliederung: je ein kurzer Absatz zu den Kernargumenten jeder Seite, dann wo die "
        "Teilnehmer sich einig waren, dann was offen blieb.",
        "Stütze Dich nur auf das Protokoll, ergänze keine eigenen Fakten und erkläre "
        "niemanden zum Sieger. Nenne keine Kunden, Firmen aus dem Umfeld oder Personen "
        "außer den Teilnehmernamen.",
        "Antworte nur mit der Zusammenfassung, ohne Einleitung und ohne Überschrift.",
        "",
        f'Thema: "{diskussion.thema}"',
    ]
    for t in diskussion.teilnehmer:
        seite = f" ({t.seite.upper()})" if t.seite else ""
        zeilen.append(f"Teilnehmer: {t.name}{seite}")
    zeilen.append("")
    for b in gesagt:
        kopf = "Schlusswort" if b.art == "schlusswort" else f"Runde {b.runde}"
        zeilen.append(f"[{b.name}, {kopf}] {b.text}")
    return "\n".join(zeilen)


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
    zeilen.append("")
    for b in diskussion.beitraege:
        if b.art == "beitrag":
            zeilen.append(f"**{b.name}** (Runde {b.runde}, {b.zeit}): {b.text}")
        elif b.art == "schlusswort":
            zeilen.append(f"**{b.name}**, Schlusswort ({b.zeit}): {b.text}")
        elif b.art == "vorbereitung":
            zeilen.append(f"**{b.name}**, Recherche ({b.zeit}):\n\n{b.text}")
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
