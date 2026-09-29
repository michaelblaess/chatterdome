"""Das Fehlerprotokoll und seine Sitzungsklammer.

Geprueft wird vor allem der Fall, um dessentwillen es das Protokoll gibt: ein
Lauf ohne Endzeile. Genau daran ist zu erkennen, dass der Prozess von aussen
abgeraeumt wurde und kein Python-Fehler vorlag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chatterdome.kern import absturz


@pytest.fixture(autouse=True)
def _eigenes_protokoll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    datei = tmp_path / "fault.log"
    monkeypatch.setattr(absturz, "PROTOKOLL", datei)
    monkeypatch.setattr(absturz, "_offen", False)
    return datei


class TestProtokoll:
    def test_eintrag_landet_in_der_datei(self, _eigenes_protokoll: Path) -> None:
        absturz.notiere("Probe", "Zeile eins")
        inhalt = _eigenes_protokoll.read_text(encoding="utf-8")
        assert "Probe" in inhalt
        assert "Zeile eins" in inhalt

    def test_absturz_schreibt_den_traceback(self, _eigenes_protokoll: Path) -> None:
        try:
            raise ValueError("kaputt")
        except ValueError as fehler:
            absturz.absturz(fehler)
        inhalt = _eigenes_protokoll.read_text(encoding="utf-8")
        assert "ValueError" in inhalt
        assert "kaputt" in inhalt
        assert "Traceback" in inhalt

    def test_klammer_schliesst_sich_beim_regulaeren_ende(
        self, _eigenes_protokoll: Path
    ) -> None:
        absturz.beobachte("9.9.9")
        absturz._ende("regulaer beendet")
        inhalt = _eigenes_protokoll.read_text(encoding="utf-8")
        assert "Start v9.9.9" in inhalt
        assert "regulaer beendet" in inhalt

    def test_ohne_ende_bleibt_die_klammer_offen(self, _eigenes_protokoll: Path) -> None:
        """Der eigentliche Zweck: ein Lauf ohne Endzeile ist der Befund.

        Wird der Prozess hart abgeraeumt, laeuft weder atexit noch ein
        Signalhandler - unter Windows liefert TerminateProcess gar kein
        Signal. Die fehlende Zeile ist dann der einzige Hinweis darauf, dass
        es KEIN Python-Fehler war.
        """
        absturz.beobachte("9.9.9")
        inhalt = _eigenes_protokoll.read_text(encoding="utf-8")
        assert "Start v9.9.9" in inhalt
        assert "beendet" not in inhalt

    def test_zweites_beobachte_klammert_nicht_doppelt(
        self, _eigenes_protokoll: Path
    ) -> None:
        absturz.beobachte("9.9.9")
        absturz.beobachte("9.9.9")
        assert _eigenes_protokoll.read_text(encoding="utf-8").count("Start v9.9.9") == 1

    def test_datei_waechst_nicht_unbegrenzt(
        self, _eigenes_protokoll: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(absturz, "GRENZE", 2000)
        for i in range(200):
            absturz.notiere(f"Probe {i}", "x" * 100)
        assert _eigenes_protokoll.stat().st_size < 20_000

    def test_kuerzen_beginnt_an_einer_kopfzeile(
        self, _eigenes_protokoll: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nach dem Kuerzen darf die Datei nicht mitten im Traceback anfangen."""
        monkeypatch.setattr(absturz, "GRENZE", 1000)
        for i in range(60):
            absturz.notiere(f"Probe {i}", "Zeile\nZeile\nZeile")
        erste = _eigenes_protokoll.read_text(encoding="utf-8").splitlines()[0]
        assert erste.startswith("[")

    def test_protokoll_bleibt_bei_lf(
        self, _eigenes_protokoll: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anhaengen und Kuerzen muessen dasselbe Zeilenende schreiben.

        Ohne newline="\\n" macht der Textmodus unter Windows CRLF daraus -
        ``read_text`` vereinheitlicht das beim Lesen, die Datei traegt es
        aber trotzdem. Darum roh pruefen.
        """
        monkeypatch.setattr(absturz, "GRENZE", 1000)
        for i in range(60):
            absturz.notiere(f"Probe {i}", "Zeile\nZeile")
        assert b"\r" not in _eigenes_protokoll.read_bytes()

    def test_unschreibbares_ziel_wirft_nicht(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ein Protokoll darf nie selbst zum Fehler werden.

        Es laeuft im Absturzpfad - wenn es dort wirft, verdeckt es genau den
        Fehler, den es festhalten sollte.
        """
        monkeypatch.setattr(absturz, "PROTOKOLL", tmp_path / "nicht" / "da" / "x.log")
        monkeypatch.setattr(Path, "mkdir", _wirft)
        absturz.notiere("Probe")  # darf keine Ausnahme ausloesen


def _wirft(*_args: object, **_kwargs: object) -> None:
    raise OSError("kein Zugriff")
