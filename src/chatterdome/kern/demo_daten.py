"""Legt die Daten des Demo-Modus im Demo-Zuhause an.

Geschrieben wird in genau den Formaten, die sonst Claude Code und Chatterdome
selbst erzeugen: Transkripte unter ``~/.claude/projects``, Notizen unter
``~/.claude/memory``, das Diskussionsarchiv und die Einstellungen unter
``~/.chatterdome``. Die Reiter lesen sie dann ueber ihren normalen Code-Weg -
getestet wird also die echte Anzeige, nur mit erfundenem Stoff.

Deterministisch bis auf die Uhrzeit: derselbe Zufallswert ergibt dieselben
Zahlen, die Zeitstempel haengen an ``jetzt``.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chatterdome.kern import einstellungen
from chatterdome.kern.debatte import Beitrag, Diskussion, Teilnehmer, Verbrauch, als_markdown
from chatterdome.kern.demo_texte import (
    AGENTEN,
    ARCHIV,
    GESPRAECHE,
    NOTIZEN,
    PROJEKTE,
    RECALLS,
    RECHNER_SYSTEME,
    WEITERE_NAMEN,
    sprache,
)
from chatterdome.kern.diskussionsarchiv import Diskussionsarchiv
from chatterdome.kern.umgebung import DEMO_RECHNER

ZUFALL = 29092026
"""Fester Startwert, damit jeder Demo-Start dieselben Zahlen zeigt."""

TAGE = 14
"""So weit reicht die erfundene Vorgeschichte zurueck, passend zum Statistikfenster."""

_NAMENSRAUM = uuid.UUID("5f0c3a52-7d1e-4d0a-9d6b-2f1c9b8e4a10")


def sitzung(name: str, nummer: int = 0) -> str:
    """Eine stabile Sitzungskennung fuer einen erfundenen Agenten."""
    return str(uuid.uuid5(_NAMENSRAUM, f"{name}-{nummer}"))


def arbeitsordner(rechner: str, projekt: str) -> str:
    """Der Arbeitsordner, wie ihn eine Sitzung auf diesem Rechner melden wuerde."""
    if rechner == "LAPTOP":
        return f"/Users/demo/projects/{projekt}"
    if rechner == "SERVER":
        return f"/home/demo/projects/{projekt}"
    return f"C:\\Users\\demo\\projects\\{projekt}"


def _ordner_schluessel(cwd: str) -> str:
    """So benennt Claude Code den Projektordner: alles ausser Buchstaben und Ziffern wird '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _stempel(wann: datetime) -> str:
    return wann.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class _Transkript:
    """Schreibt eine Transkriptdatei Zeile fuer Zeile."""

    def __init__(self, projekte: Path, name: str, sid: str, cwd: str, modell: str) -> None:
        ordner = projekte / _ordner_schluessel(cwd)
        ordner.mkdir(parents=True, exist_ok=True)
        self.datei = ordner / f"{sid}.jsonl"
        self.sid = sid
        self.cwd = cwd
        self.modell = modell
        self.zeilen: list[dict[str, Any]] = [
            {"type": "agent-name", "agentName": f"{name} · {DEMO_RECHNER}", "sessionId": sid}
        ]
        self._nummer = 0

    def _basis(self, art: str, wann: datetime) -> dict[str, Any]:
        return {"type": art, "timestamp": _stempel(wann), "sessionId": self.sid, "cwd": self.cwd}

    def frage(self, wann: datetime, text: str) -> None:
        zeile = self._basis("user", wann)
        zeile["message"] = {"role": "user", "content": text}
        self.zeilen.append(zeile)

    def antwort(self, wann: datetime, text: str, zufall: random.Random) -> None:
        self._nummer += 1
        zeile = self._basis("assistant", wann)
        zeile["requestId"] = f"req_demo_{self.sid[:8]}_{self._nummer}"
        inhalt: list[dict[str, Any]] = (
            [{"type": "text", "text": text}] if text
            else [{"type": "tool_use", "name": zufall.choice(["Read", "Edit", "Bash", "Grep"]),
                   "input": {}}]
        )
        zeile["message"] = {
            "id": f"msg_demo_{self.sid[:8]}_{self._nummer}",
            "role": "assistant",
            "model": self.modell,
            "content": inhalt,
            "usage": {
                "input_tokens": zufall.randint(20, 400),
                "cache_creation_input_tokens": zufall.randint(4_000, 26_000),
                "cache_read_input_tokens": zufall.randint(20_000, 180_000),
                "output_tokens": zufall.randint(250, 2_800),
            },
        }
        self.zeilen.append(zeile)

    def abruf(self, wann: datetime, notiz: str, tage: int) -> None:
        """Ein Memory-Abruf, wie Claude Code ihn in die Sitzung legt."""
        text = (f"<system-reminder>This memory is {tage} days old.</system-reminder>\n"
                f"---\nname: {notiz}\ndescription: demo\n---\n")
        self.frage(wann, text)

    def schreiben(self) -> None:
        self.datei.write_text(
            "".join(json.dumps(z, ensure_ascii=False) + "\n" for z in self.zeilen),
            encoding="utf-8", newline="\n",
        )


def _gespraech(t: _Transkript, projekt: str, lang: str, bis: datetime, anfragen: int,
               zufall: random.Random, *, mit_text: bool = True) -> None:
    """Fuellt ein Transkript mit Wortwechseln und Werkzeugzuegen, endend bei ``bis``.

    :param mit_text: False fuer reine Werkzeugzuege. Sonst stuende derselbe Satz in
        jeder frueheren Sitzung des Projekts, und die Suche zeigte ihn dutzendfach.
    """
    paare = GESPRAECHE[projekt][lang] if mit_text else []
    schritte = len(paare) + anfragen
    wann = bis - timedelta(minutes=2 * schritte)
    for frage, antwort in paare:
        t.frage(wann, frage)
        wann += timedelta(minutes=1)
        t.antwort(wann, antwort, zufall)
        wann += timedelta(minutes=1)
    for _ in range(anfragen):
        t.antwort(wann, "", zufall)
        wann += timedelta(minutes=2)


def _transkripte(zuhause: Path, lang: str, jetzt: datetime, zufall: random.Random) -> None:
    projekte = zuhause / ".claude" / "projects"
    # Die laufenden Sitzungen, damit Suche und Statistik ihre Namen kennen.
    for agent in AGENTEN:
        t = _Transkript(projekte, agent.name, sitzung(agent.name),
                        arbeitsordner(agent.rechner, agent.projekt), agent.modell)
        bis = jetzt - timedelta(minutes=agent.minuten_seit_aktiv)
        _gespraech(t, agent.projekt, lang, bis, zufall.randint(25, 60), zufall)
        t.schreiben()

    # Die Vorgeschichte: zwei bis vier Sitzungen am Tag ueber zwei Wochen.
    namen = [a.name for a in AGENTEN] + list(WEITERE_NAMEN)
    abrufe = [n for n, anzahl in RECALLS.items() for _ in range(anzahl)]
    nummer = 0
    for tag in range(1, TAGE):
        for _ in range(zufall.randint(2, 4)):
            nummer += 1
            name = zufall.choice(namen)
            projekt = zufall.choice(PROJEKTE)
            rechner = zufall.choice(list(RECHNER_SYSTEME))
            modell = zufall.choice(["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5",
                                    "claude-haiku-4-5"])
            t = _Transkript(projekte, name, sitzung(name, nummer),
                            arbeitsordner(rechner, projekt), modell)
            bis = jetzt - timedelta(days=tag, hours=zufall.randint(0, 10))
            if abrufe:
                t.abruf(bis - timedelta(hours=3), abrufe.pop(), tag)
            _gespraech(t, projekt, lang, bis, zufall.randint(10, 45), zufall,
                       mit_text=nummer % 5 == 0)
            t.schreiben()


def _notizen(zuhause: Path, lang: str) -> None:
    ordner = zuhause / ".claude" / "memory"
    ordner.mkdir(parents=True, exist_ok=True)
    index: list[str] = []
    for n in NOTIZEN:
        titel = n.titel_de if lang == "de" else n.titel_en
        beschreibung = n.beschreibung_de if lang == "de" else n.beschreibung_en
        text = n.text_de if lang == "de" else n.text_en
        inhalt = (f"---\nname: {n.name}\ndescription: {beschreibung}\nmetadata:\n"
                  f"  type: {n.typ}\n---\n\n{text}\n")
        (ordner / f"{n.name}.md").write_text(inhalt, encoding="utf-8", newline="\n")
        if n.im_index:
            index.append(f"- [{titel}]({n.name}.md) - {beschreibung}")
    (ordner / "MEMORY.md").write_text("\n".join(index) + "\n", encoding="utf-8", newline="\n")


def _archiv(zuhause: Path, lang: str, jetzt: datetime) -> None:
    ablage = zuhause / ".claude" / "bus" / DEMO_RECHNER / "diskussionen"
    ablage.mkdir(parents=True, exist_ok=True)
    archiv = Diskussionsarchiv()
    for vorlage in ARCHIV[lang]:
        beginn = (jetzt - timedelta(days=vorlage.tage_her)).astimezone()
        teilnehmer = [Teilnehmer(name, seite=seite, modell="claude-sonnet-5-5")
                      for name, seite in vorlage.teilnehmer]
        d = Diskussion(vorlage.thema, teilnehmer, format=vorlage.format,
                       runden=len(vorlage.runden), positionen=vorlage.positionen,
                       modell="sonnet")
        d.beginn = beginn.isoformat(timespec="seconds")
        wann = beginn
        for runde, texte in enumerate(vorlage.runden, start=1):
            for tn, text in zip(teilnehmer, texte, strict=True):
                wann += timedelta(seconds=40)
                d.beitraege.append(Beitrag(runde, tn.name, text,
                                           wann.isoformat(timespec="seconds"), seite=tn.seite))
        d.ende = "alle Runden gespielt" if lang == "de" else "all rounds played"
        d.zusammenfassung = vorlage.zusammenfassung
        d.verbrauch = Verbrauch(neu=38_000 * len(d.beitraege), cache=210_000 * len(d.beitraege),
                                aus=900 * len(d.beitraege))
        datei = ablage / f"{beginn:%Y%m%d-%H%M%S}.md"
        datei.write_text(als_markdown(d), encoding="utf-8", newline="\n")
        archiv.speichern(d, str(datei))


def _namenspool(zuhause: Path) -> None:
    """Eine Kopie des mitgelieferten Pools mit den Sternen als aktivem Motiv.

    Die lokale Ergaenzung (``namenspool.local.json``) bleibt bewusst draussen -
    dort stehen die eigenen Motive des Anwenders.
    """
    from chatterdome.kern.umgebung import demo_pool_datei

    quelle = Path(__file__).resolve().parents[3] / "skills" / "operator" / "namenspool.json"
    try:
        roh: dict[str, Any] = json.loads(quelle.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        roh = {"reserviert": ["Operator"], "pools": {}}
    pools = roh.setdefault("pools", {})
    if "sterne" not in pools:
        pools["sterne"] = {"motiv": "Sterne",
                           "namen": [a.name for a in AGENTEN] + list(WEITERE_NAMEN)}
    roh["aktiv"] = "sterne"
    ziel = demo_pool_datei()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(roh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def erzeugen(zuhause: Path, sprache_wert: str, jetzt: datetime | None = None) -> None:
    """Legt alle Demo-Daten an. Erwartet ein frisches, schon aktiviertes Demo-Zuhause.

    :param zuhause: das Heimatverzeichnis aus ``umgebung.demo_aktivieren``.
    :param sprache_wert: ``de`` oder ``en``, bestimmt die Inhalte.
    :param jetzt: Bezugszeit, nur fuer Tests von aussen zu setzen.
    """
    from chatterdome import haftung

    lang = sprache(sprache_wert)
    bezug = jetzt or datetime.now(UTC)
    zufall = random.Random(ZUFALL)
    _transkripte(zuhause, lang, bezug, zufall)
    _notizen(zuhause, lang)
    einstellungen.Einstellungen().speichern({"language": sprache_wert, "nur_lokal": False})
    haftung.festhalten()
    _archiv(zuhause, lang, bezug)
    _namenspool(zuhause)
