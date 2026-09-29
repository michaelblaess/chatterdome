"""Wo die Transkripte liegen und wie sie zu lesen sind - ohne jede Verdichtung.

Diese Schicht trennt das AUFFINDEN der Dateien vom Auswerten. Vorher stand beides
in ``statistik.py``, und genau daran ist die Subagenten-Luecke entstanden: der Glob
``*/*.jsonl`` trifft eine Ebene, die Subagenten liegen eine tiefer.

Die Pfadkarte stammt aus den Adaptern von iAmCorey/Wake (MIT, Rust, macOS-only)
und wurde am 24.08.2026 gegen RAINBOW geprueft. Sie steht hier vollstaendig,
damit eine spaetere Ergaenzung nicht neu recherchiert werden muss - gebaut sind
nur die beiden Quellen, die auf diesem Rechner Daten hatten:

===================  ==================================================  ========
Agent                Pfad                                                RAINBOW
===================  ==================================================  ========
Claude Code          ~/.claude/projects/<projekt>/<id>.jsonl             gebaut
Claude Subagenten    ~/.claude/projects/<projekt>/<id>/subagents/*.jsonl gebaut
Codex CLI            ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl        gebaut
Copilot              ~/.copilot/session-store.db                         leer
Cursor               ~/.cursor/projects                                  leer
Gemini               ~/.gemini/tmp/projects.json                         leer
Antigravity          ~/.gemini/antigravity-cli/conversation_summaries.db leer
Grok                 ~/.grok/sessions                                    leer
Kimi                 ~/.kimi-code/sessions                               leer
Kiro                 ~/.kiro/sessions/cli                                leer
Pi                   ~/.pi/agent/sessions                                leer
DeepSeek Harness     ~/.dsh/sessions                                     leer
===================  ==================================================  ========

Eine neue Quelle braucht ``dateien()``, ``anfragen()``, ``texte()`` und
``name()`` - mehr fragt weder die Statistik noch der Suchindex ab.

**Zwei Agenten, zwei Genauigkeiten.** Claude meldet die vier Verbrauchsarten je
Anfrage getrennt. Codex meldet nur ``input_tokens`` (den Cache-Anteil eingeschlossen),
``cached_input_tokens`` und ``output_tokens`` - ein Gegenstueck zur Cache-Erzeugung
gibt es dort nicht. Deshalb traegt jede Anfrage ihren ``agent``, und wer beide
zusammenzaehlt, muss wissen, dass ``cache_neu`` bei Codex strukturell 0 ist und
keine Aussage traegt.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CLAUDE = "claude"
CODEX = "codex"


@dataclass(slots=True)
class Anfrage:
    """Eine einzelne Anfrage an das Modell, wie sie im Transkript steht."""

    ts: datetime
    sitzung: str
    ordner: str
    frisch: int = 0
    cache_neu: int = 0
    cache_gelesen: int = 0
    aus: int = 0
    agent: str = CLAUDE
    subagent: bool = False
    """True fuer Anfragen aus einem Subagenten-Transkript (``isSidechain``).

    Der Verbrauch zaehlt zur Elternsitzung - ``sitzung`` traegt deren Id, nicht
    die des Subagenten.
    """
    art: str = ""
    """Agententyp bei Subagenten (aus der Metadatei), sonst leer."""

    @property
    def gesamt(self) -> int:
        return self.frisch + self.cache_neu + self.cache_gelesen + self.aus

    @property
    def echt(self) -> int:
        """Alles ausser der Cache-Lesung - also das, was neu verarbeitet wurde."""
        return self.frisch + self.cache_neu + self.aus


@dataclass(frozen=True, slots=True)
class Transkript:
    """Eine Transkriptdatei mit dem, was sich ohne Zerlegen ueber sie sagen laesst."""

    agent: str
    pfad: Path
    sitzung: str
    subagent: bool = False
    art: str = ""
    """Der Agententyp eines Subagenten (``general-purpose``, ``Explore``, ...).

    Steht in der ``*.meta.json`` neben der Transkriptdatei. Leer bei
    Haupttranskripten und bei Subagenten ohne Metadatei.
    """
    auftrag: str = ""
    """Die Aufgabenbeschreibung des Subagenten, ein lesbarer Titel.

    Ohne sie heisst ein Subagent in jeder Anzeige nur ``agent-abb2fa67d7c631703``.
    """
    tiefe: int = 0
    """Verschachtelungstiefe (``spawnDepth``). 0 fuer das Haupttranskript."""


@dataclass(frozen=True, slots=True)
class Textstueck:
    """Eine Nachricht, wie sie in den Suchindex geht."""

    ts: datetime | None
    rolle: str
    text: str
    zeile: int


def _zeitpunkt(roh: object) -> datetime | None:
    if not isinstance(roh, str) or not roh:
        return None
    try:
        wert = datetime.fromisoformat(roh.replace("Z", "+00:00"))
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=UTC)


def _zahl(roh: object) -> int:
    """Eine Zahl aus dem Transkript, oder 0. Fehlende Felder sind normal."""
    if isinstance(roh, bool) or not isinstance(roh, int | float | str):
        return 0
    try:
        return int(roh)
    except (TypeError, ValueError):
        return 0


def _text_aus_inhalt(roh: object) -> str:
    """Fasst den Textanteil einer Nachricht zusammen.

    Der Inhalt ist entweder eine Zeichenkette oder eine Liste von Bloecken. Nur
    Text- und Denkbloecke gehen mit - Werkzeugaufrufe und deren Ergebnisse wuerden
    den Index mit Dateiinhalten fluten, die woanders besser zu finden sind.
    """
    if isinstance(roh, str):
        return roh
    if not isinstance(roh, list):
        return ""
    teile: list[str] = []
    for block in roh:
        if isinstance(block, str):
            teile.append(block)
            continue
        if not isinstance(block, dict):
            continue
        art = block.get("type")
        if art == "text" and isinstance(block.get("text"), str):
            teile.append(block["text"])
        elif art == "thinking" and isinstance(block.get("thinking"), str):
            teile.append(block["thinking"])
        elif art in {"input_text", "output_text"} and isinstance(block.get("text"), str):
            teile.append(block["text"])
    return "\n".join(t for t in teile if t)


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


class ClaudeQuelle:
    """``~/.claude/projects`` - Haupttranskripte und Subagenten.

    Die Subagenten liegen unter ``<projekt>/<sitzung>/subagents/*.jsonl``. Ihre
    ``sessionId`` ist die der ELTERNSITZUNG, ebenso der Ordnername darueber -
    der Verbrauch laesst sich also der Sitzung zuordnen, die den Subagenten
    gestartet hat.
    """

    agent = CLAUDE

    def __init__(self, wurzel: Path) -> None:
        self.wurzel = wurzel

    def dateien(self) -> Iterator[Transkript]:
        if not self.wurzel.is_dir():
            return
        for datei in sorted(self.wurzel.glob("*/*.jsonl")):
            yield Transkript(CLAUDE, datei, datei.stem)
        # Eine Ebene tiefer, im Unterordner der jeweiligen Sitzung. Die Id kommt
        # aus dem Ordnernamen - der Dateiname traegt die des Subagenten.
        for datei in sorted(self.wurzel.glob("*/*/subagents/*.jsonl")):
            eltern = datei.parent.parent.name
            art, auftrag, tiefe = _subagent_meta(datei)
            yield Transkript(
                CLAUDE, datei, eltern, subagent=True, art=art, auftrag=auftrag, tiefe=tiefe
            )

    def anfragen(
        self, t: Transkript, ordnernamen: dict[str, str] | None = None
    ) -> Iterator[Anfrage]:
        """Liest die Modellanfragen einer Datei.

        Der Vorfilter auf die Zeichenkette spart das Zerlegen von rund zwei
        Dritteln der Zeilen. Eine unlesbare Zeile wird uebersprungen und nicht
        gemeldet: Transkripte werden waehrend des Lesens weitergeschrieben, eine
        halbe letzte Zeile ist normal.
        """
        merker = ordnernamen if ordnernamen is not None else {}
        # Ein logischer Antwortzug steht auf MEHREREN Zeilen, und jede wiederholt
        # denselben kumulativen Verbrauch. Wer pro Zeile summiert, zaehlt ihn
        # mehrfach - gemessen am 24.08.2026 ueber den Hauptbestand Faktor 2,25
        # (30,45 Mio statt 13,51 Mio Ausgabe-Token). Deshalb je requestId nur der
        # LETZTE Stand: er traegt den vollstaendigen Zug. Wer den ersten nimmt
        # (so macht es zoetrope), unterschaetzt bei Subagenten um das Siebenfache.
        letzte: dict[str, Anfrage] = {}
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for zeile in strom:
                    _claude_zeile(zeile, t, merker, letzte)
        except OSError:
            # Eine Datei, die gerade ersetzt wird, darf den Durchgang nicht
            # abbrechen - die bereits gelesenen Zuege sind trotzdem auswertbar.
            pass
        yield from letzte.values()

    def texte(self, t: Transkript) -> Iterator[Textstueck]:
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for nummer, zeile in enumerate(strom, start=1):
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict):
                        continue
                    rolle = satz.get("type")
                    if rolle not in {"user", "assistant"}:
                        continue
                    nachricht = satz.get("message")
                    if not isinstance(nachricht, dict):
                        continue
                    text = _text_aus_inhalt(nachricht.get("content")).strip()
                    if text:
                        yield Textstueck(_zeitpunkt(satz.get("timestamp")), rolle, text, nummer)
        except OSError:
            return

    def name(self, t: Transkript) -> tuple[str, str]:
        """Sitzung und Agentenname aus dem Kopf der Datei.

        Der Name steht als eigener Datensatz ``agent-name`` in den ersten Zeilen,
        mit dem Ordner als Zusatz (``Marga · BUERO_PC2``). Nur der Teil vor
        dem Trenner ist der Poolname. Die Zeilengrenze ist noetig: ohne sie liest
        die Funktion Hunderte Megabyte fuer eine Handvoll Zeichenketten.

        Die Sitzung kommt aus dem DATENSATZ, nicht aus dem Dateinamen - beide
        stimmen zwar meist ueberein, aber nicht zwingend. Gibt ``("", "")``
        zurueck, wenn kein Namensdatensatz im Kopf steht.
        """
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for nummer, zeile in enumerate(strom):
                    if nummer > 60:
                        break
                    if '"agent-name"' not in zeile:
                        continue
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict) or satz.get("type") != "agent-name":
                        continue
                    roh = str(satz.get("agentName") or "")
                    name = roh.split("·")[0].strip()
                    if not name:
                        continue
                    return str(satz.get("sessionId") or t.sitzung), name
        except OSError:
            return "", ""
        return "", ""


def _subagent_meta(transkript: Path) -> tuple[str, str, int]:
    """Liest ``<name>.meta.json`` neben einem Subagenten-Transkript.

    Claude legt neben jede Subagenten-Datei eine Metadatei mit ``agentType``,
    ``description``, ``toolUseId`` und ``spawnDepth``. Ohne sie heisst ein
    Subagent in jeder Anzeige nur nach seiner Kennung, und der Agententyp - die
    interessantere Groesse - fehlt ganz.

    Fehlt die Datei oder ist sie unlesbar, sind die Werte leer. Das ist kein
    Fehler: aeltere Bestaende haben sie nicht.
    """
    neben = transkript.with_suffix(".meta.json")
    try:
        roh = json.loads(neben.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "", "", 0
    if not isinstance(roh, dict):
        return "", "", 0
    return (
        str(roh.get("agentType") or ""),
        str(roh.get("description") or ""),
        _zahl(roh.get("spawnDepth")),
    )


def _ordnername(roh: object, merker: dict[str, str]) -> str:
    """Der letzte Pfadteil des Arbeitsverzeichnisses, zwischengespeichert.

    Ohne den Merker baut ein voller Durchgang Zehntausende Path-Objekte fuer eine
    Handvoll verschiedener Pfade - gemessen 7,7 s gegenueber 2,3 s mit.
    """
    if not roh:
        return ""
    schluessel = str(roh)
    name = merker.get(schluessel, "")
    if not name:
        name = Path(schluessel).name or schluessel
        merker[schluessel] = name
    return name


# ---------------------------------------------------------------------------
# Codex CLI
# ---------------------------------------------------------------------------


class CodexQuelle:
    """``~/.codex/sessions/YYYY/MM/DD/rollout-<zeit>-<id>.jsonl``.

    Aufbau: erste Zeile ``session_meta`` mit ``cwd`` und ``id``, danach
    ``response_item`` (Nachrichten) und ``event_msg``. Der Verbrauch steht in
    ``payload.type == "token_count"`` unter ``info.last_token_usage``.

    ``input_tokens`` schliesst dort den Cache-Anteil EIN - ``frisch`` ist die
    Differenz zu ``cached_input_tokens``. Ein Gegenstueck zur Cache-Erzeugung
    gibt es nicht, ``cache_neu`` bleibt deshalb 0 und traegt keine Aussage.
    """

    agent = CODEX

    def __init__(self, wurzel: Path) -> None:
        self.wurzel = wurzel

    def dateien(self) -> Iterator[Transkript]:
        if not self.wurzel.is_dir():
            return
        for datei in sorted(self.wurzel.rglob("rollout-*.jsonl")):
            yield Transkript(CODEX, datei, datei.stem)

    def _kopf(self, t: Transkript) -> tuple[str, str]:
        """Sitzungs-Id und Ordnername aus der ersten ``session_meta``-Zeile."""
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for nummer, zeile in enumerate(strom):
                    if nummer > 5:
                        break
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict) or satz.get("type") != "session_meta":
                        continue
                    nutz = satz.get("payload")
                    if not isinstance(nutz, dict):
                        continue
                    kennung = str(nutz.get("id") or t.sitzung)
                    roh = nutz.get("cwd")
                    return kennung, (Path(str(roh)).name if roh else "")
        except OSError:
            return t.sitzung, ""
        return t.sitzung, ""

    def anfragen(
        self, t: Transkript, ordnernamen: dict[str, str] | None = None
    ) -> Iterator[Anfrage]:
        sitzung, ordner = self._kopf(t)
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for zeile in strom:
                    if '"token_count"' not in zeile:
                        continue
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict):
                        continue
                    nutz = satz.get("payload")
                    if not isinstance(nutz, dict) or nutz.get("type") != "token_count":
                        continue
                    info = nutz.get("info")
                    letzte = info.get("last_token_usage") if isinstance(info, dict) else None
                    wann = _zeitpunkt(satz.get("timestamp"))
                    if wann is None or not isinstance(letzte, dict):
                        continue
                    ein = _zahl(letzte.get("input_tokens"))
                    zwischen = _zahl(letzte.get("cached_input_tokens"))
                    aus = _zahl(letzte.get("output_tokens"))
                    if ein == 0 and zwischen == 0 and aus == 0:
                        # Codex schreibt die Zeile auch ohne Bewegung. Eine
                        # Nullanfrage waere eine erfundene Anfrage.
                        continue
                    yield Anfrage(
                        ts=wann,
                        sitzung=sitzung,
                        ordner=ordner,
                        frisch=max(ein - zwischen, 0),
                        cache_gelesen=zwischen,
                        aus=aus,
                        agent=CODEX,
                    )
        except OSError:
            return

    def texte(self, t: Transkript) -> Iterator[Textstueck]:
        try:
            with t.pfad.open(encoding="utf-8", errors="replace") as strom:
                for nummer, zeile in enumerate(strom, start=1):
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict):
                        continue
                    nutz = satz.get("payload")
                    if not isinstance(nutz, dict):
                        continue
                    art = nutz.get("type")
                    if art == "message":
                        rolle = str(nutz.get("role") or "user")
                        text = _text_aus_inhalt(nutz.get("content"))
                    elif art in {"user_message", "agent_message"}:
                        rolle = "user" if art == "user_message" else "assistant"
                        text = str(nutz.get("message") or nutz.get("text") or "")
                    else:
                        continue
                    text = text.strip()
                    if text:
                        yield Textstueck(_zeitpunkt(satz.get("timestamp")), rolle, text, nummer)
        except OSError:
            return

    def name(self, t: Transkript) -> tuple[str, str]:
        """Codex kennt keine Agentennamen aus Michaels Pool."""
        return "", ""


Transkriptquelle = ClaudeQuelle | CodexQuelle


def _claude_zeile(
    zeile: str, t: Transkript, merker: dict[str, str], letzte: dict[str, Anfrage]
) -> None:
    """Traegt eine Transkriptzeile in ``letzte`` ein, wenn sie eine Modellanfrage ist."""
    if '"assistant"' not in zeile:
        return
    try:
        satz = json.loads(zeile)
    except (ValueError, TypeError):
        return
    if not isinstance(satz, dict) or satz.get("type") != "assistant":
        return
    wann = _zeitpunkt(satz.get("timestamp"))
    nachricht = satz.get("message")
    verbrauch = nachricht.get("usage") if isinstance(nachricht, dict) else None
    if wann is None or not isinstance(verbrauch, dict):
        return
    anfrage = Anfrage(
        ts=wann,
        sitzung=str(satz.get("sessionId") or t.sitzung),
        ordner=_ordnername(satz.get("cwd"), merker),
        frisch=_zahl(verbrauch.get("input_tokens")),
        cache_neu=_zahl(verbrauch.get("cache_creation_input_tokens")),
        cache_gelesen=_zahl(verbrauch.get("cache_read_input_tokens")),
        aus=_zahl(verbrauch.get("output_tokens")),
        agent=CLAUDE,
        subagent=t.subagent,
        art=t.art,
    )
    # Ohne Kennung bleibt nur die Zeile selbst - eine eigene,
    # nie kollidierende Schluesselung.
    kennung = satz.get("requestId") or (
        nachricht.get("id") if isinstance(nachricht, dict) else None
    )
    letzte[str(kennung) if kennung else f"zeile-{len(letzte)}"] = anfrage


def claude_anfragen_ab(pfad: Path, versatz: int) -> list[Anfrage]:
    """Die Modellanfragen einer Claude-Transkriptdatei ab einem Byte-Versatz.

    Fuer den Verbrauch einer Diskussion: der Versatz ist die Dateigroesse beim
    Start, gezaehlt wird also nur, was danach geschah. Binaer gelesen, weil ein
    Versatz in Bytes im Textmodus nicht verlaesslich anzuspringen ist. Eine
    halbe erste oder letzte Zeile scheitert am JSON und faellt heraus.
    """
    letzte: dict[str, Anfrage] = {}
    t = Transkript(CLAUDE, pfad, pfad.stem)
    try:
        with pfad.open("rb") as strom:
            strom.seek(versatz)
            for roh in strom:
                _claude_zeile(roh.decode("utf-8", errors="replace"), t, {}, letzte)
    except OSError:
        return []
    return list(letzte.values())


def claude_transkript(sitzung: str, wurzel: Path | None = None) -> Path | None:
    """Die Transkriptdatei einer Claude-Sitzung, None wenn (noch) keine da ist."""
    basis = wurzel if wurzel is not None else claude_wurzel()
    if not sitzung or not basis.is_dir():
        return None
    return next(iter(sorted(basis.glob(f"*/{sitzung}.jsonl"))), None)


def claude_wurzel() -> Path:
    return Path.home() / ".claude" / "projects"


def codex_wurzel() -> Path:
    return Path.home() / ".codex" / "sessions"


def alle_quellen(projekte: Path | None = None, codex: Path | None = None) -> list[Transkriptquelle]:
    """Alle Quellen, die auf diesem Rechner ueberhaupt Daten haben.

    Eine Quelle ohne Verzeichnis wird weggelassen statt leer mitgefuehrt - so
    bleibt jede Zaehlung ueber ``alle_quellen()`` eine Aussage ueber vorhandene
    Agenten und nicht ueber die Liste der unterstuetzten.
    """
    kandidaten: list[Transkriptquelle] = [
        ClaudeQuelle(projekte if projekte is not None else claude_wurzel()),
        CodexQuelle(codex if codex is not None else codex_wurzel()),
    ]
    return [q for q in kandidaten if q.wurzel.is_dir()]


def lies_anfragen(projekte: Path) -> Iterator[Anfrage]:
    """Alle Modellanfragen aus den Claude-Transkripten, Subagenten eingeschlossen.

    Signatur und Reihenfolge sind die der frueheren Fassung in ``statistik.py``.
    Neu ist allein, dass die Subagenten mitzaehlen.
    """
    quelle = ClaudeQuelle(projekte)
    ordnernamen: dict[str, str] = {}
    for t in quelle.dateien():
        yield from quelle.anfragen(t, ordnernamen)


def lies_namen(projekte: Path) -> dict[str, str]:
    """Sitzung auf Agentennamen, aus den Transkripten.

    Gemessen tragen 22 von 100 Transkripten einen Namen - der SessionStart-Hook
    ist juenger als der Bestand. Jede Auswertung darauf ist also eine Untergrenze
    und muss so beschriftet werden.

    Subagenten bleiben aussen vor: sie erben die Sitzung ihres Elternteils, und
    ihr Kopf traegt keinen eigenen Namensdatensatz.
    """
    namen: dict[str, str] = {}
    quelle = ClaudeQuelle(projekte)
    for t in quelle.dateien():
        if t.subagent:
            continue
        sitzung, name = quelle.name(t)
        if name:
            namen[sitzung] = name
    return namen
