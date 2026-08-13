"""Wann das Grafik-Backend vor dem Start geweckt wird.

Aufgefallen am 14.08.2026 auf senza: nach dem Beenden stand ein Traceback in
der Konsole (TimeoutError: Timeout waiting for data). Der Fehler war keiner -
textual-image faengt den Timeout ab und meldet ihn nur mit exc_info, also mit
vollem Traceback. Sichtbar wurde er erst beim Beenden, weil Textual bis dahin
den zweiten Bildschirmpuffer haelt.

Die Ursache lag eine Ebene hoeher: geweckt wurde immer, solange der Bildmodus
nicht "halfblock" war - auch auf einem gnome-terminal, das gar kein Sixel
kann. Genau das haelt dieser Test fest.
"""

from __future__ import annotations

from claude_sanctuary.__main__ import soll_grafik_wecken


class TestGrafikWecken:
    def test_ohne_protokoll_wird_nicht_geweckt(self) -> None:
        """Der gemeldete Fall: gnome-terminal, TERM=xterm-256color."""
        assert soll_grafik_wecken("auto", None) is False

    def test_mit_sixel_wird_geweckt(self) -> None:
        assert soll_grafik_wecken("auto", "sixel") is True

    def test_mit_kitty_protokoll_wird_geweckt(self) -> None:
        assert soll_grafik_wecken("auto", "tgp") is True

    def test_halfblock_weckt_nie(self) -> None:
        """Wer Halbbloecke gewaehlt hat, braucht das Backend gar nicht."""
        assert soll_grafik_wecken("halfblock", "sixel") is False

    def test_erzwungene_grafik_ohne_protokoll_weckt_nicht(self) -> None:
        """Ohne Protokoll kaeme auch bei "graphics" keine Widget-Klasse zustande.

        Das Wecken wuerde hier nur denselben Timeout erzeugen wie im
        gemeldeten Fall, ohne dass danach ein Bild moeglich waere.
        """
        assert soll_grafik_wecken("graphics", None) is False
