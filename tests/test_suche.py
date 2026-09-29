"""Der Volltextindex.

Zwei Dinge sind hier teuer, wenn sie falsch sind: eine Nutzereingabe, die die
FTS5-Syntax trifft und die Abfrage abbrechen laesst, und ein zweiter Indexlauf,
der stillschweigend alles noch einmal liest. Beides hat einen eigenen Test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatterdome.kern.suche import Suchindex, _frage, index_datei
from chatterdome.kern.transkripte import ClaudeQuelle, CodexQuelle


def _claude(wurzel: Path, sitzung: str, saetze: list[tuple[str, str]]) -> None:
    """Schreibt ein Transkript mit (Rolle, Text)-Paaren."""
    ziel = wurzel / "projekt" / f"{sitzung}.jsonl"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeilen = [
        {
            "type": rolle,
            "timestamp": "2026-08-24T10:00:00Z",
            "sessionId": sitzung,
            "message": {"content": [{"type": "text", "text": text}]},
        }
        for rolle, text in saetze
    ]
    ziel.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def index(tmp_path: Path) -> Suchindex:
    return Suchindex(tmp_path / "suche.db")


class TestAbfrage:
    def test_zerlegt_in_woerter(self) -> None:
        assert _frage("roter faden") == '"roter" AND "faden"*'

    def test_leere_eingabe_gibt_leere_abfrage(self) -> None:
        """FTS5 wirft bei einer leeren Abfrage - der Aufrufer muss das erkennen."""
        assert _frage("   ") == ""
        assert _frage('"*(') == ""

    @pytest.mark.parametrize("eingabe", ['fehler"', "AND", "*", "a OR b", "NEAR(x y)", "-"])
    def test_syntax_der_eingabe_bricht_nichts(
        self, index: Suchindex, tmp_path: Path, eingabe: str
    ) -> None:
        """Genau diese Zeichen wuerden eine durchgereichte Abfrage abbrechen lassen."""
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("assistant", "Der Fehler lag im Glob")])
        index.aktualisiere([ClaudeQuelle(wurzel)])

        # Zusicherung ist die Abwesenheit einer Ausnahme, nicht der Treffer.
        assert isinstance(index.suche(eingabe), list)


class TestIndexlauf:
    def test_findet_ueber_beide_quellen(self, index: Suchindex, tmp_path: Path) -> None:
        claude = tmp_path / "claude"
        codex = tmp_path / "codex" / "2026" / "01" / "03"
        _claude(claude, "s1", [("user", "Wie war das mit dem Fahrtenbuch")])
        codex.mkdir(parents=True)
        (codex / "rollout-a.jsonl").write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "timestamp": "2026-01-03T10:00:00Z",
                    "payload": {"id": "c1", "cwd": "C:/REPOS/x"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "event_msg",
                    "timestamp": "2026-01-03T10:01:00Z",
                    "payload": {"type": "agent_message", "message": "Das Fahrtenbuch ist fertig"},
                }
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        index.aktualisiere([ClaudeQuelle(claude), CodexQuelle(tmp_path / "codex")])
        treffer = index.suche("fahrtenbuch")

        assert {t.agent for t in treffer} == {"claude", "codex"}

    def test_zweiter_lauf_fasst_nichts_an(self, index: Suchindex, tmp_path: Path) -> None:
        """Ohne diese Ersparnis wartet der Reiter bei jedem Oeffnen Sekunden."""
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("assistant", "Der erste Satz")])
        quellen = [ClaudeQuelle(wurzel)]

        erste = index.aktualisiere(quellen)
        zweite = index.aktualisiere(quellen)

        assert erste.neu == 1
        assert zweite.neu == 0
        assert zweite.aktualisiert == 0
        assert zweite.unveraendert == 1

    def test_geaenderte_datei_wird_neu_gelesen(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        quellen = [ClaudeQuelle(wurzel)]
        _claude(wurzel, "s1", [("assistant", "Vorher stand hier Kirsche")])
        index.aktualisiere(quellen)

        _claude(wurzel, "s1", [("assistant", "Jetzt steht hier Pflaume")])
        zweite = index.aktualisiere(quellen)

        assert zweite.aktualisiert == 1
        assert index.suche("pflaume") != []
        # Der alte Inhalt darf nicht als Karteileiche zurueckbleiben.
        assert index.suche("kirsche") == []

    def test_geloeschte_datei_verschwindet(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        quellen = [ClaudeQuelle(wurzel)]
        _claude(wurzel, "s1", [("assistant", "Ein Satz ueber Zwetschgen")])
        index.aktualisiere(quellen)

        (wurzel / "projekt" / "s1.jsonl").unlink()
        zweite = index.aktualisiere(quellen)

        assert zweite.entfernt == 1
        assert index.suche("zwetschgen") == []

    def test_subagenten_kommen_mit(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("assistant", "Hauptsitzung")])
        unter = wurzel / "projekt" / "s1" / "subagents"
        unter.mkdir(parents=True)
        (unter / "agent-a.jsonl").write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-08-24T10:05:00Z",
                    "sessionId": "s1",
                    "isSidechain": True,
                    "message": {"content": [{"type": "text", "text": "Nebenlaeufig geprueft"}]},
                }
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        index.aktualisiere([ClaudeQuelle(wurzel)])
        treffer = index.suche("nebenlaeufig")

        assert len(treffer) == 1
        assert treffer[0].subagent is True
        assert treffer[0].sitzung == "s1"


class TestSuchen:
    def test_ausschnitt_zeichnet_den_treffer_aus(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("assistant", "Der Glob lag eine Ebene zu flach")])
        index.aktualisiere([ClaudeQuelle(wurzel)])

        treffer = index.suche("glob")

        assert "[b]Glob[/b]" in treffer[0].ausschnitt
        assert treffer[0].zeile == 1
        assert treffer[0].rolle == "assistant"

    def test_umlaute_werden_normalisiert(self, index: Suchindex, tmp_path: Path) -> None:
        """koln findet Köln - das ist der Zweck von remove_diacritics."""
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("user", "Ein Gruß aus Köln an die Prüfung")])
        index.aktualisiere([ClaudeQuelle(wurzel)])

        assert index.suche("koln") != []
        assert index.suche("prufung") != []

    def test_agentenfilter(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("assistant", "Ein Wort")])
        index.aktualisiere([ClaudeQuelle(wurzel)])

        assert index.suche("wort", agenten=["claude"]) != []
        assert index.suche("wort", agenten=["codex"]) == []

    def test_ohne_index_keine_ausnahme(self, tmp_path: Path) -> None:
        """Vor dem ersten Lauf gibt es keine Datei - das ist kein Fehler."""
        assert Suchindex(tmp_path / "gibtsnicht.db").suche("egal") == []

    def test_bestand_zaehlt_dateien_und_stuecke(self, index: Suchindex, tmp_path: Path) -> None:
        wurzel = tmp_path / "claude"
        _claude(wurzel, "s1", [("user", "eins"), ("assistant", "zwei")])
        index.aktualisiere([ClaudeQuelle(wurzel)])

        assert index.bestand() == (1, 2)


class TestOrt:
    def test_index_liegt_bei_den_einstellungen(self, tmp_path: Path) -> None:
        """Die autouse-Fixture verlegt VERZEICHNIS - der Index muss mitwandern.

        Als Modulkonstante waere der Pfad beim Import eingefroren, und der Test
        wuerde in Michaels echtem Verzeichnis schreiben.
        """
        assert index_datei().parent == tmp_path
