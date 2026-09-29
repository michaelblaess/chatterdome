"""Was von der Umbenennung claude-sanctuary -> Chatterdome am 29.09.2026 bleiben muss."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chatterdome.kern.einstellungen import alten_ordner_uebernehmen

REPO = Path(__file__).resolve().parents[1]


class TestAlterOrdner:
    def test_wird_kopiert_und_bleibt_liegen(self, tmp_path: Path) -> None:
        alt, neu = tmp_path / ".claude-sanctuary", tmp_path / ".chatterdome"
        (alt / "unter").mkdir(parents=True)
        (alt / "settings.json").write_text('{"theme": "boing"}', encoding="utf-8")
        (alt / "unter" / "diskussionen.db").write_bytes(b"SQLite")
        assert alten_ordner_uebernehmen(alt, neu) is True
        assert (neu / "settings.json").read_text(encoding="utf-8") == '{"theme": "boing"}'
        assert (neu / "unter" / "diskussionen.db").read_bytes() == b"SQLite"
        assert (alt / "settings.json").exists(), "kopiert, nicht verschoben"

    def test_vorhandener_neuer_ordner_wird_nie_ueberschrieben(self, tmp_path: Path) -> None:
        alt, neu = tmp_path / "alt", tmp_path / "neu"
        alt.mkdir()
        (alt / "settings.json").write_text("alt", encoding="utf-8")
        neu.mkdir()
        (neu / "settings.json").write_text("neu", encoding="utf-8")
        assert alten_ordner_uebernehmen(alt, neu) is True
        assert (neu / "settings.json").read_text(encoding="utf-8") == "neu"

    def test_ein_schon_angelegter_neuer_ordner_haelt_nicht_auf(self, tmp_path: Path) -> None:
        # So am 29.09.2026: das Absturzprotokoll hatte ~/.chatterdome schon angelegt.
        alt, neu = tmp_path / "alt", tmp_path / "neu"
        alt.mkdir()
        (alt / "diskussionen.db").write_bytes(b"echt")
        neu.mkdir()
        (neu / "fault.log").write_text("Absturz", encoding="utf-8")
        assert alten_ordner_uebernehmen(alt, neu) is True
        assert (neu / "diskussionen.db").read_bytes() == b"echt"
        assert (neu / "fault.log").read_text(encoding="utf-8") == "Absturz"

    def test_laeuft_nur_einmal(self, tmp_path: Path) -> None:
        alt, neu = tmp_path / "alt", tmp_path / "neu"
        alt.mkdir()
        (alt / "a.json").write_text("1", encoding="utf-8")
        assert alten_ordner_uebernehmen(alt, neu) is True
        (neu / "a.json").unlink()
        assert alten_ordner_uebernehmen(alt, neu) is False
        assert not (neu / "a.json").exists(), "Geloeschtes kommt nicht zurueck"

    def test_ohne_alten_ordner_passiert_nichts(self, tmp_path: Path) -> None:
        assert alten_ordner_uebernehmen(tmp_path / "gibtsnicht", tmp_path / "neu") is False
        assert not (tmp_path / "neu").exists()


class TestAliasSanctuary:
    def test_alter_befehl_tut_dasselbe_wie_der_neue(self) -> None:
        # Andere Rechner rufen "sanctuary" ueber ssh auf, auch nach der Umbenennung.
        def hilfe(skript: str) -> str:
            lauf = subprocess.run(["node", str(REPO / "bin" / skript), "help"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=60, check=True)
            return lauf.stdout

        neu = hilfe("chatterdome.mjs")
        assert "chatterdome" in neu
        assert hilfe("sanctuary.mjs") == neu

    def test_fernaufrufe_nennen_den_alten_namen(self) -> None:
        # Den gibt es auf jedem Rechner, alt wie neu - "chatterdome" erst nach dem Umzug.
        for datei, stelle in (
            ("skills/claude-bus/bus.mjs", "'sanctuary uebernehmen'"),
            ("skills/operator/operator.mjs", "'sanctuary status --json'"),
            ("skills/operator/shot.mjs", "'sanctuary shot --stdout'"),
            ("skills/operator/update.mjs", "`sanctuary update --method"),
            ("skills/operator/neustart.mjs", "['sanctuary', ...args]"),
        ):
            assert stelle in (REPO / datei).read_text(encoding="utf-8"), datei
