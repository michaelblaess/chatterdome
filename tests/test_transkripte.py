"""Die Quellenschicht: wo Transkripte liegen und was aus ihnen herausfaellt.

Der teuerste Fehler dieses Moduls war ein Glob, der eine Ebene zu flach lag und
die Subagenten uebersah - ohne Fehlermeldung, jahrelang. Deshalb pruefen die
Tests hier vor allem das AUFFINDEN, nicht das Rechnen: ein Bestand, in dem beide
Ebenen belegt sind, und Zusicherungen, die rot werden, sobald eine davon fehlt.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from claude_sanctuary.kern.transkripte import (
    CLAUDE,
    CODEX,
    ClaudeQuelle,
    CodexQuelle,
    alle_quellen,
    lies_anfragen,
    lies_namen,
)

JETZT = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _iso(stunden_vorher: float = 1.0) -> str:
    return (JETZT - timedelta(hours=stunden_vorher)).isoformat().replace("+00:00", "Z")


def _schreibe(ziel: Path, zeilen: list[dict[str, object]]) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8", newline="\n")


def _verbrauch(**werte: int) -> dict[str, object]:
    voll = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    voll.update(werte)
    return voll


def _claude_bestand(wurzel: Path) -> None:
    """Ein Projekt mit einer Hauptsitzung und einem Subagenten darunter."""
    _schreibe(
        wurzel / "projekt" / "s1.jsonl",
        [
            {"type": "agent-name", "agentName": "Marga · RAINBOW", "sessionId": "s1"},
            {
                "type": "assistant",
                "timestamp": _iso(2),
                "sessionId": "s1",
                "cwd": "C:/Repos/claude-sanctuary",
                "message": {"usage": _verbrauch(input_tokens=10, output_tokens=40)},
            },
        ],
    )
    _schreibe(
        wurzel / "projekt" / "s1" / "subagents" / "agent-abc.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": _iso(1),
                "sessionId": "s1",
                "isSidechain": True,
                "cwd": "C:/Repos/swatch-chronos",
                "message": {"usage": _verbrauch(input_tokens=5, output_tokens=7)},
            }
        ],
    )


class TestClaudeQuelle:
    def test_findet_beide_ebenen(self, tmp_path: Path) -> None:
        """Der alte Glob traf nur die obere - genau daran ist die Luecke entstanden."""
        _claude_bestand(tmp_path)

        gefunden = list(ClaudeQuelle(tmp_path).dateien())

        assert len(gefunden) == 2
        assert [t.subagent for t in gefunden] == [False, True]

    def test_subagent_erbt_die_elternsitzung(self, tmp_path: Path) -> None:
        """Sonst zaehlt der Verbrauch auf eine Sitzung, die es nicht gibt."""
        _claude_bestand(tmp_path)

        subagent = next(t for t in ClaudeQuelle(tmp_path).dateien() if t.subagent)

        assert subagent.sitzung == "s1"
        assert subagent.pfad.stem == "agent-abc"

    def test_anfragen_zaehlen_subagenten_mit(self, tmp_path: Path) -> None:
        _claude_bestand(tmp_path)

        gelesen = list(lies_anfragen(tmp_path))

        assert len(gelesen) == 2
        assert sum(a.aus for a in gelesen) == 47
        assert [a.subagent for a in gelesen] == [False, True]

    def test_subagent_traegt_seinen_eigenen_ordner(self, tmp_path: Path) -> None:
        """Ein Subagent kann in einem anderen Verzeichnis arbeiten als sein Elternteil."""
        _claude_bestand(tmp_path)

        gelesen = list(lies_anfragen(tmp_path))

        assert [a.ordner for a in gelesen] == ["claude-sanctuary", "swatch-chronos"]

    def test_namen_ueberspringen_subagenten(self, tmp_path: Path) -> None:
        """Ein Subagent hat keinen eigenen Poolnamen - er erbt die Sitzung."""
        _claude_bestand(tmp_path)

        assert lies_namen(tmp_path) == {"s1": "Marga"}

    def test_fehlendes_verzeichnis_ist_kein_fehler(self, tmp_path: Path) -> None:
        assert list(ClaudeQuelle(tmp_path / "weg").dateien()) == []
        assert list(lies_anfragen(tmp_path / "weg")) == []

    def test_texte_lassen_werkzeugaufrufe_weg(self, tmp_path: Path) -> None:
        """Werkzeugausgaben wuerden den Suchindex mit Dateiinhalten fluten."""
        _schreibe(
            tmp_path / "projekt" / "s2.jsonl",
            [
                {
                    "type": "assistant",
                    "timestamp": _iso(1),
                    "message": {
                        "content": [
                            {"type": "text", "text": "Der Befund steht fest"},
                            {"type": "tool_use", "name": "Bash", "input": {"cmd": "ls"}},
                        ]
                    },
                }
            ],
        )
        quelle = ClaudeQuelle(tmp_path)

        stuecke = [s for t in quelle.dateien() for s in quelle.texte(t)]

        assert len(stuecke) == 1
        assert stuecke[0].text == "Der Befund steht fest"
        assert stuecke[0].rolle == "assistant"


class TestZugDeduplizierung:
    """Ein Antwortzug steht auf mehreren Zeilen und wiederholt seinen Verbrauch.

    Gemessen am 24.08.2026 ueber den Hauptbestand: pro Zeile summiert ergaeben
    sich 30,45 Mio Ausgabe-Token, je Zug gezaehlt 13,51 Mio - Faktor 2,25. Der
    Wert ist KUMULATIV, deshalb gewinnt der letzte Stand.
    """

    def _zug(self, kennung: str, aus: int, stunden: float) -> dict[str, object]:
        return {
            "type": "assistant",
            "timestamp": _iso(stunden),
            "sessionId": "s1",
            "requestId": kennung,
            "message": {"usage": _verbrauch(output_tokens=aus)},
        }

    def test_zaehlt_je_zug_einmal(self, tmp_path: Path) -> None:
        _schreibe(
            tmp_path / "projekt" / "s1.jsonl",
            [self._zug("req-1", 10, 3), self._zug("req-1", 40, 2), self._zug("req-2", 7, 1)],
        )

        gelesen = list(lies_anfragen(tmp_path))

        assert len(gelesen) == 2
        assert sum(a.aus for a in gelesen) == 47

    def test_der_letzte_stand_gewinnt(self, tmp_path: Path) -> None:
        """Der Wert waechst waehrend des Zuges - der erste Stand ist unvollstaendig."""
        _schreibe(
            tmp_path / "projekt" / "s1.jsonl",
            [self._zug("req-1", 3, 3), self._zug("req-1", 28, 2)],
        )

        gelesen = list(lies_anfragen(tmp_path))

        assert [a.aus for a in gelesen] == [28]

    def test_zeilen_ohne_kennung_zaehlen_einzeln(self, tmp_path: Path) -> None:
        """Ohne requestId gibt es nichts zusammenzufassen - jede Zeile bleibt."""
        ohne = {
            "type": "assistant",
            "timestamp": _iso(1),
            "sessionId": "s1",
            "message": {"usage": _verbrauch(output_tokens=5)},
        }
        _schreibe(tmp_path / "projekt" / "s1.jsonl", [ohne, dict(ohne)])

        gelesen = list(lies_anfragen(tmp_path))

        assert len(gelesen) == 2
        assert sum(a.aus for a in gelesen) == 10

    def test_message_id_dient_als_rueckfall(self, tmp_path: Path) -> None:
        satz = {
            "type": "assistant",
            "timestamp": _iso(1),
            "sessionId": "s1",
            "message": {"id": "msg-1", "usage": _verbrauch(output_tokens=9)},
        }
        _schreibe(tmp_path / "projekt" / "s1.jsonl", [satz, dict(satz)])

        assert len(list(lies_anfragen(tmp_path))) == 1


class TestSubagentMetadaten:
    def _mit_meta(self, wurzel: Path, meta: dict[str, object] | None) -> None:
        ziel = wurzel / "projekt" / "s1" / "subagents" / "agent-a.jsonl"
        _schreibe(
            ziel,
            [
                {
                    "type": "assistant",
                    "timestamp": _iso(1),
                    "sessionId": "s1",
                    "message": {"usage": _verbrauch(output_tokens=3)},
                }
            ],
        )
        if meta is not None:
            ziel.with_suffix(".meta.json").write_text(
                json.dumps(meta), encoding="utf-8", newline="\n"
            )

    def test_liest_typ_auftrag_und_tiefe(self, tmp_path: Path) -> None:
        """Ohne die Metadatei heisst ein Subagent nur nach seiner Kennung."""
        self._mit_meta(
            tmp_path,
            {
                "agentType": "general-purpose",
                "description": "Domain-Namen recherchieren",
                "spawnDepth": 2,
            },
        )

        subagent = next(t for t in ClaudeQuelle(tmp_path).dateien() if t.subagent)

        assert subagent.art == "general-purpose"
        assert subagent.auftrag == "Domain-Namen recherchieren"
        assert subagent.tiefe == 2

    def test_typ_wandert_in_die_anfrage(self, tmp_path: Path) -> None:
        """Sonst laesst sich der Verbrauch nicht nach Agententyp aufschluesseln."""
        self._mit_meta(tmp_path, {"agentType": "Explore", "description": "x"})

        gelesen = list(lies_anfragen(tmp_path))

        assert [a.art for a in gelesen] == ["Explore"]

    def test_fehlende_metadatei_ist_kein_fehler(self, tmp_path: Path) -> None:
        """Aeltere Bestaende haben sie nicht."""
        self._mit_meta(tmp_path, None)

        subagent = next(t for t in ClaudeQuelle(tmp_path).dateien() if t.subagent)

        assert (subagent.art, subagent.auftrag, subagent.tiefe) == ("", "", 0)

    def test_kaputte_metadatei_ist_kein_fehler(self, tmp_path: Path) -> None:
        self._mit_meta(tmp_path, None)
        ziel = tmp_path / "projekt" / "s1" / "subagents" / "agent-a.meta.json"
        ziel.write_text("{kein json", encoding="utf-8", newline="\n")

        subagent = next(t for t in ClaudeQuelle(tmp_path).dateien() if t.subagent)

        assert subagent.art == ""


class TestCodexQuelle:
    def _sitzung(self, wurzel: Path, name: str, zeilen: list[dict[str, object]]) -> None:
        _schreibe(wurzel / "2026" / "01" / "03" / f"rollout-{name}.jsonl", zeilen)

    def test_frisch_ist_die_differenz_zum_zwischenspeicher(self, tmp_path: Path) -> None:
        """Codex zaehlt den Cache-Anteil in input_tokens MIT - Claude nicht."""
        self._sitzung(
            tmp_path,
            "a",
            [
                {
                    "type": "session_meta",
                    "timestamp": _iso(3),
                    "payload": {"id": "c1", "cwd": "C:/REPOS/schuldschein-generator"},
                },
                {
                    "type": "event_msg",
                    "timestamp": _iso(2),
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 4348,
                                "cached_input_tokens": 3072,
                                "output_tokens": 84,
                            }
                        },
                    },
                },
            ],
        )
        quelle = CodexQuelle(tmp_path)

        gelesen = [a for t in quelle.dateien() for a in quelle.anfragen(t)]

        assert len(gelesen) == 1
        assert gelesen[0].frisch == 1276
        assert gelesen[0].cache_gelesen == 3072
        assert gelesen[0].aus == 84
        assert gelesen[0].agent == CODEX
        assert gelesen[0].sitzung == "c1"
        assert gelesen[0].ordner == "schuldschein-generator"

    def test_cache_neu_bleibt_leer(self, tmp_path: Path) -> None:
        """Codex kennt kein Gegenstueck zur Cache-Erzeugung - eine Zahl waere erfunden."""
        self._sitzung(
            tmp_path,
            "b",
            [
                {"type": "session_meta", "timestamp": _iso(3), "payload": {"id": "c2"}},
                {
                    "type": "event_msg",
                    "timestamp": _iso(2),
                    "payload": {
                        "type": "token_count",
                        "info": {"last_token_usage": {"input_tokens": 10, "output_tokens": 2}},
                    },
                },
            ],
        )
        quelle = CodexQuelle(tmp_path)

        gelesen = [a for t in quelle.dateien() for a in quelle.anfragen(t)]

        assert gelesen[0].cache_neu == 0

    def test_nullzeile_wird_uebersprungen(self, tmp_path: Path) -> None:
        """Codex schreibt die Zeile auch ohne Bewegung - das ist keine Anfrage."""
        self._sitzung(
            tmp_path,
            "c",
            [
                {"type": "session_meta", "timestamp": _iso(3), "payload": {"id": "c3"}},
                {
                    "type": "event_msg",
                    "timestamp": _iso(2),
                    "payload": {"type": "token_count", "info": None},
                },
                {
                    "type": "event_msg",
                    "timestamp": _iso(1),
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 0,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                            }
                        },
                    },
                },
            ],
        )
        quelle = CodexQuelle(tmp_path)

        assert [a for t in quelle.dateien() for a in quelle.anfragen(t)] == []

    def test_texte_kennen_beide_nachrichtenformen(self, tmp_path: Path) -> None:
        self._sitzung(
            tmp_path,
            "d",
            [
                {"type": "session_meta", "timestamp": _iso(3), "payload": {"id": "c4"}},
                {
                    "type": "response_item",
                    "timestamp": _iso(2),
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Bau mir das"}],
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": _iso(1),
                    "payload": {"type": "agent_message", "message": "Fertig"},
                },
            ],
        )
        quelle = CodexQuelle(tmp_path)

        stuecke = [s for t in quelle.dateien() for s in quelle.texte(t)]

        assert [(s.rolle, s.text) for s in stuecke] == [
            ("user", "Bau mir das"),
            ("assistant", "Fertig"),
        ]


class TestQuellenwahl:
    def test_nur_vorhandene_quellen(self, tmp_path: Path) -> None:
        """Eine Quelle ohne Verzeichnis wird weggelassen, nicht leer mitgefuehrt."""
        claude = tmp_path / "claude"
        claude.mkdir()

        quellen = alle_quellen(projekte=claude, codex=tmp_path / "gibtsnicht")

        assert [q.agent for q in quellen] == [CLAUDE]

    def test_beide_wenn_beide_da(self, tmp_path: Path) -> None:
        claude = tmp_path / "claude"
        codex = tmp_path / "codex"
        claude.mkdir()
        codex.mkdir()

        quellen = alle_quellen(projekte=claude, codex=codex)

        assert [q.agent for q in quellen] == [CLAUDE, CODEX]
