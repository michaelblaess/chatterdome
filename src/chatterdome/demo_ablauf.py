"""Der Diskussionsablauf des Demo-Modus: dieselbe Moderation, erfundene Antworten.

Gegenstueck zu ``debatte_ablauf.ausfuehren`` mit derselben Signatur. Es startet
keine Sitzung und ruft kein Modell auf: die frischen Teilnehmer kommen aus den
freien Namen der ``DemoQuelle``, die Beitraege aus ``demo_texte.skript_fuer``. Die
Moderation selbst - Runden, Rednerwechsel, Vorbereitung, Schlussworte - ist
die echte aus ``kern.debatte``, nur der Kanal ist ausgetauscht. Die Anzeige
sieht also genau das, was sie bei einer echten Diskussion saehe.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from chatterdome.debatte_ablauf import ZUSAMMENFASSUNG_LAEUFT, Ergebnis, ablage
from chatterdome.i18n import current_language
from chatterdome.kern.debatte import (
    CONTRA,
    ENTSCHEIDUNG,
    PRO,
    Beitrag,
    Diskussion,
    Teilnehmer,
    Verbrauch,
    abstimmung,
    als_markdown,
    endegrund,
    moderieren,
    vorbereitung,
    zusammenfassen,
)
from chatterdome.kern.demo_quelle import DemoQuelle
from chatterdome.kern.demo_texte import DemoSkript, skript_fuer
from chatterdome.kern.diskussionsarchiv import Diskussionsarchiv

ANTWORTZEIT = 4.0
"""So lange "denkt" ein Teilnehmer, bevor sein Beitrag kommt - Zeit fuer die Animation."""

RECHERCHEZEIT = 6.0

TAKT = 0.5
"""Abstand, in dem die Moderation nach einer Antwort sieht. Echt sind es 3 s."""

VERBRAUCH_JE_BEITRAG = Verbrauch(neu=36_000, cache=180_000, aus=850)


class DemoKanal:
    """Antwortet mit dem Skript, nach einer kleinen Denkpause."""

    def __init__(self, diskussion: Diskussion, skript: DemoSkript,
                 antwortzeit: float = ANTWORTZEIT, recherchezeit: float = RECHERCHEZEIT,
                 uhr: Callable[[], float] = time.monotonic) -> None:
        self._diskussion = diskussion
        self._skript = skript
        self._antwortzeit = antwortzeit
        self._recherchezeit = recherchezeit
        self._uhr = uhr
        self._offen: dict[str, tuple[float, str]] = {}
        self._gesagt: dict[str, int] = {}
        self._zaehler = 0

    def _redner(self, name: str) -> Teilnehmer:
        return next(t for t in self._diskussion.teilnehmer if t.name == name)

    def _seite(self, redner: Teilnehmer) -> str:
        if redner.seite:
            return redner.seite
        # Im Team-Format gibt es keine Seiten - abwechselnd aus beiden Stapeln.
        return CONTRA if self._diskussion.teilnehmer.index(redner) % 2 else PRO

    def _stimme(self, redner: Teilnehmer) -> str:
        """Jeder stimmt fuer die eigene Seite - die Demo erfindet kein Umdenken."""
        contra = self._seite(redner) == CONTRA
        schluss = self._skript.schluss_contra if contra else self._skript.schluss_pro
        return f"{ENTSCHEIDUNG}: {self._diskussion.position(self._seite(redner))}. {schluss}"

    def _text(self, redner: Teilnehmer) -> str:
        if redner.name not in self._gesagt:
            # Beim Fortsetzen stehen fruehere Beitraege schon im Protokoll.
            self._gesagt[redner.name] = sum(
                1 for b in self._diskussion.beitraege
                if b.name == redner.name and b.art == "beitrag"
            )
        bisher = self._gesagt[redner.name]
        self._gesagt[redner.name] = bisher + 1
        contra = self._seite(redner) == CONTRA
        if bisher >= self._diskussion.runden:
            return self._skript.schluss_contra if contra else self._skript.schluss_pro
        stapel = self._skript.contra if contra else self._skript.pro
        return stapel[bisher % len(stapel)]

    def senden(self, an: str, text: str) -> tuple[str, str]:
        redner = self._redner(an)
        self._zaehler += 1
        kennung = f"demo-disk-{self._zaehler}"
        if text == vorbereitung(self._diskussion, redner):
            antwort, dauer = self._skript.vorbereitung, self._recherchezeit
        elif text == abstimmung(self._diskussion, redner):
            antwort, dauer = self._stimme(redner), self._antwortzeit
        else:
            antwort, dauer = self._text(redner), self._antwortzeit
        self._offen[kennung] = (self._uhr() + dauer, antwort)
        return kennung, ""

    def antwort(self, an: str, kennung: str) -> tuple[int | None, str]:
        fertig_ab, text = self._offen.get(kennung, (0.0, ""))
        if not text or self._uhr() < fertig_ab:
            return None, ""
        return 200, text


def ausfuehren(
    diskussion: Diskussion,
    neu: list[Teilnehmer],
    *,
    ohne_eigenen_kontext: bool = False,
    wiederbeleben: list[Teilnehmer] | None = None,
    melden: Callable[[str], None] = lambda _text: None,
    beim_beitrag: Callable[[Beitrag], None] | None = None,
    beim_wort: Callable[[Teilnehmer, int], None] | None = None,
    beim_start: Callable[[Diskussion], None] | None = None,
    beim_verbrauch: Callable[[Verbrauch], None] | None = None,
    beim_vorbereiten: Callable[[list[Teilnehmer]], None] | None = None,
    stopp: threading.Event | None = None,
    quelle: Any = None,
    archiv: Diskussionsarchiv | None = None,
    protokoll: Path | None = None,
    zaehler: Any = None,
    antwortzeit: float = ANTWORTZEIT,
    recherchezeit: float = RECHERCHEZEIT,
    takt: float = TAKT,
) -> Ergebnis:
    """Spielt eine Diskussion ab. Blockiert, gehoert in einen Thread.

    Die Parameter bis ``zaehler`` entsprechen ``debatte_ablauf.ausfuehren``,
    ``zaehler`` bleibt ungenutzt. Die letzten drei verkuerzen die Pausen im Test.
    """
    stopp = stopp or threading.Event()
    archiv = archiv or Diskussionsarchiv()
    skript = skript_fuer(diskussion.thema, current_language())
    demo = quelle if isinstance(quelle, DemoQuelle) else None
    ordner = ablage()
    if not diskussion.beginn:
        diskussion.beginn = datetime.now().isoformat(timespec="seconds")
        diskussion.ohne_kontext = ohne_eigenen_kontext

    def sichern(protokoll_pfad: str = "") -> None:
        archiv.speichern(diskussion, protokoll_pfad)

    def nach_beitrag(beitrag: Beitrag) -> None:
        diskussion.verbrauch = diskussion.verbrauch + VERBRAUCH_JE_BEITRAG
        sichern()
        if beim_beitrag is not None:
            beim_beitrag(beitrag)
        if beim_verbrauch is not None:
            beim_verbrauch(diskussion.verbrauch)

    frisch: list[str] = []
    try:
        anzahl = len(neu) + len(wiederbeleben or [])
        if anzahl:
            melden(f"{anzahl} Sitzung(en) gestartet, warte auf die Namen ...")
            if stopp.wait(1.5):
                diskussion.ende = endegrund("discussion.end_stopped", "von Hand gestoppt")
                return Ergebnis(diskussion, fehler="Vor dem Start gestoppt.")
            freie = demo.freie_namen() if demo is not None else []
            for teilnehmer in wiederbeleben or []:
                if demo is not None:
                    demo.aufnehmen(teilnehmer.name)
                frisch.append(teilnehmer.name)
            for nummer, vorlage in enumerate(neu, start=1):
                name = freie.pop(0) if freie else f"Nova{nummer}"
                if demo is not None:
                    demo.aufnehmen(name)
                frisch.append(name)
                diskussion.teilnehmer.append(Teilnehmer(name, vorlage.rolle, vorlage.seite))
        for teilnehmer in diskussion.teilnehmer:
            teilnehmer.modell = teilnehmer.modell or "claude-sonnet-5-5"

        namen = ", ".join(t.name for t in diskussion.teilnehmer)
        melden(f'Diskussion: "{diskussion.thema}" mit {namen}')
        sichern()
        if beim_start is not None:
            beim_start(diskussion)
        kanal = DemoKanal(diskussion, skript, antwortzeit, recherchezeit)
        moderieren(diskussion, kanal, beim_beitrag=nach_beitrag, beim_wort=beim_wort,
                   beim_vorbereiten=beim_vorbereiten, stopp=stopp, takt=takt)
    finally:
        if demo is not None and frisch:
            demo.entlassen(frisch)

    if any(b.art in ("beitrag", "schlusswort") for b in diskussion.beitraege):
        melden(ZUSAMMENFASSUNG_LAEUFT)
        stopp.wait(min(2.0, antwortzeit))
        zusammenfassen(diskussion, lambda _auftrag: (skript.zusammenfassung, ""))
    if beim_verbrauch is not None:
        beim_verbrauch(diskussion.verbrauch)

    datei = protokoll or ordner / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    datei.write_text(als_markdown(diskussion), encoding="utf-8", newline="\n")
    sichern(str(datei))
    return Ergebnis(diskussion, protokoll=datei)
