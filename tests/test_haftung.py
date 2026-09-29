"""Der Haftungshinweis: Wortlaut, eigene Version, Rueckfrage im Kurzbefehl."""

from __future__ import annotations

import io

from textual_widgets import DISCLAIMER_VERSION

from chatterdome import haftung
from chatterdome.debatte_cli import _zustimmung_einholen


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class TestWortlaut:
    def test_nennt_die_kosten(self) -> None:
        # Michael, 29.09.2026: "das Teil verballert Tokens, das muss schon jeder abnicken".
        assert "Tokens" in haftung.text()
        assert "Kosten" in haftung.text()

    def test_zustimmung_zur_alten_fassung_reicht_nicht(self) -> None:
        assert haftung.VERSION != DISCLAIMER_VERSION
        haftung.zustimmung().record(DISCLAIMER_VERSION)
        assert not haftung.zugestimmt()
        haftung.festhalten()
        assert haftung.zugestimmt()


class TestKurzbefehl:
    def test_ohne_terminal_keine_zustimmung(self) -> None:
        assert _zustimmung_einholen(io.StringIO("j\n"), io.StringIO()) is False
        assert not haftung.zugestimmt()

    def test_ja_im_terminal_haelt_fest(self) -> None:
        ausgabe = io.StringIO()
        assert _zustimmung_einholen(_Terminal("j\n"), ausgabe) is True
        assert "Tokens" in ausgabe.getvalue(), "der Hinweis wurde gezeigt"
        assert haftung.zugestimmt()

    def test_nein_im_terminal(self) -> None:
        assert _zustimmung_einholen(_Terminal("\n"), io.StringIO()) is False
        assert not haftung.zugestimmt()

    def test_einmal_zugestimmt_wird_nicht_mehr_gefragt(self) -> None:
        haftung.festhalten()
        ausgabe = io.StringIO()
        assert _zustimmung_einholen(_Terminal(""), ausgabe) is True
        assert ausgabe.getvalue() == ""
