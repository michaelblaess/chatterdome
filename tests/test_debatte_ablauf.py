"""Bausteine des Ablaufs, die ohne echte Fenster pruefbar sind."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatterdome.debatte_ablauf import Verbrauchszaehler, _json_antwort, namen_zuordnen
from chatterdome.kern.debatte import Verbrauch


def _zeile(kennung: str, ein: int, cache: int, aus: int) -> str:
    return json.dumps({
        "type": "assistant", "timestamp": "2026-09-28T17:00:00Z", "sessionId": "s-1",
        "requestId": kennung,
        "message": {"usage": {"input_tokens": ein, "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": cache, "output_tokens": aus}},
    }) + "\n"


class TestNamenZuordnen:
    def test_wunschname_bleibt_rest_der_reihe_nach(self) -> None:
        assert namen_zuordnen(["Maria", "", ""], ["Luzie", "Maria", "Salma"]) == [
            "Maria", "Luzie", "Salma"]

    def test_verweigerter_wunsch_bekommt_einen_anderen_namen(self) -> None:
        assert namen_zuordnen(["Maria", "Agatha"], ["Agatha", "Luzie"]) == ["Luzie", "Agatha"]

    def test_gross_und_kleinschreibung_egal(self) -> None:
        assert namen_zuordnen(["maria"], ["Maria"]) == ["Maria"]


class TestJsonAntwort:
    def test_text_und_verbrauch(self) -> None:
        # Aufbau wie bei einem echten Aufruf am 28.09.2026.
        roh = json.dumps({"type": "result", "result": " OK \n", "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 36004,
            "cache_read_input_tokens": 15428, "output_tokens": 4}})
        assert _json_antwort(roh) == ("OK", Verbrauch(36006, 15428, 4))

    def test_kein_json_ist_reiner_text(self) -> None:
        assert _json_antwort("Einfach Text\n") == ("Einfach Text", Verbrauch())


class TestVerbrauchszaehler:
    def test_zaehlt_nur_was_nach_dem_eintritt_dazukam(self, tmp_path: Path) -> None:
        datei = tmp_path / "projekt" / "s-1.jsonl"
        datei.parent.mkdir()
        datei.write_text(_zeile("r-alt", 999, 999, 999), encoding="utf-8")
        zaehler = Verbrauchszaehler(tmp_path)
        zaehler.merken("s-1")
        with datei.open("a", encoding="utf-8") as strom:
            strom.write(_zeile("r-1", 10, 100, 1))
            # Derselbe Antwortzug steht mehrfach im Transkript, nur der letzte zaehlt.
            strom.write(_zeile("r-2", 20, 200, 1))
            strom.write(_zeile("r-2", 20, 200, 5))
        assert zaehler.stand() == Verbrauch(30, 300, 6)

    def test_frische_sitzung_zaehlt_ab_dem_ersten_byte(self, tmp_path: Path) -> None:
        datei = tmp_path / "projekt" / "s-1.jsonl"
        datei.parent.mkdir()
        datei.write_text(_zeile("r-1", 10, 100, 1), encoding="utf-8")
        zaehler = Verbrauchszaehler(tmp_path)
        zaehler.merken("s-1", frisch=True)
        assert zaehler.stand() == Verbrauch(10, 100, 1)

    def test_transkript_das_erst_spaeter_entsteht(self, tmp_path: Path) -> None:
        zaehler = Verbrauchszaehler(tmp_path)
        zaehler.merken("s-1")
        assert zaehler.stand() == Verbrauch()
        datei = tmp_path / "projekt" / "s-1.jsonl"
        datei.parent.mkdir()
        datei.write_text(_zeile("r-1", 10, 100, 1), encoding="utf-8")
        assert zaehler.stand() == Verbrauch(10, 100, 1)


class TestModellImAufruf:
    def test_zusammenfassung_mit_gewaehltem_modell(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from chatterdome import debatte_ablauf

        befehle: list[list[str]] = []

        def lauf(befehl: list[str], **_werte: object) -> subprocess.CompletedProcess[str]:
            befehle.append(befehl)
            return subprocess.CompletedProcess(befehl, 0, '{"result": "Kurz."}', "")

        monkeypatch.setattr(subprocess, "run", lauf)
        assert debatte_ablauf.claude_einmal("x", tmp_path, "haiku")[0] == "Kurz."
        assert debatte_ablauf.claude_einmal("x", tmp_path)[0] == "Kurz."
        mit, ohne = befehle
        assert mit[mit.index("--model") + 1] == "haiku"
        assert "--model" not in ohne
