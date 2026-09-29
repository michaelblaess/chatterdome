"""Zuordnung Agent zu tmux-Sitzung und der Weg der Tasten hinein."""

from __future__ import annotations

import pytest

from chatterdome.kern import fenster

# Die echte Kette von senza, 16.09.2026: Snorre (743316) haengt unter der Pane
# 743298, das ist die Sitzung agent-112803.
KETTE = {743316: 743315, 743315: 743308, 743308: 743307, 743307: 743298}
TABELLE = {743298: "agent-112803"}


class TestSitzungFuer:
    def test_findet_ueber_elternkette(self) -> None:
        gefunden = fenster.sitzung_fuer(743316, tabelle=TABELLE, eltern=KETTE.get)
        assert gefunden == "agent-112803"

    def test_pane_pid_selbst_trifft_sofort(self) -> None:
        assert fenster.sitzung_fuer(743298, tabelle=TABELLE, eltern=KETTE.get) == "agent-112803"

    def test_ohne_treffer_bleibt_leer(self) -> None:
        # Ein Agent, der nicht in tmux laeuft - etwa in einem eigenen Fenster.
        assert fenster.sitzung_fuer(4242, tabelle=TABELLE, eltern=lambda _p: None) == ""

    def test_schleife_beendet_sich(self) -> None:
        # Zeigt /proc einmal im Kreis, darf die Oberflaeche nicht haengen.
        assert fenster.sitzung_fuer(5, tabelle=TABELLE, eltern=lambda _p: 5) == ""

    def test_ohne_pid(self) -> None:
        assert fenster.sitzung_fuer(None, tabelle=TABELLE) == ""

    def test_leere_tabelle(self) -> None:
        assert fenster.sitzung_fuer(743316, tabelle={}) == ""


class TestFensterName:
    @pytest.mark.parametrize("name", ["-x", "agent 1; rm -rf /", "", "a" * 65])
    def test_lehnt_unzulaessige_namen_ab(self, name: str) -> None:
        with pytest.raises(ValueError):
            fenster.TmuxFenster(name)

    def test_nimmt_den_erzeugten_namen(self) -> None:
        assert fenster.TmuxFenster("agent-112803").sitzung == "agent-112803"


class TestTasten:
    def test_schreiben_ist_buchstaeblich(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ohne ``-l`` deutet tmux Woerter wie "Enter" als Tastennamen.

        Ein Auftragstext, in dem "Enter" vorkommt, wuerde dann mitten im Satz
        eine Zeile abschicken.
        """
        aufrufe: list[list[str]] = []
        monkeypatch.setattr(fenster, "_tmux", lambda args: (aufrufe.append(args), "")[1])

        fenster.TmuxFenster("agent-1").schreiben("bitte Enter druecken")

        assert aufrufe[0][:2] == ["send-keys", "-t"]
        assert "-l" in aufrufe[0]
        assert aufrufe[0][-1] == "bitte Enter druecken"

    def test_taste_ohne_literal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aufrufe: list[list[str]] = []
        monkeypatch.setattr(fenster, "_tmux", lambda args: (aufrufe.append(args), "")[1])

        fenster.TmuxFenster("agent-1").taste("Enter")

        assert "-l" not in aufrufe[0]
        assert aufrufe[0][-1] == "Enter"

    def test_leere_eingabe_ruft_nicht_auf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aufrufe: list[list[str]] = []
        monkeypatch.setattr(fenster, "_tmux", lambda args: (aufrufe.append(args), "")[1])

        fenster.TmuxFenster("agent-1").schreiben("")
        fenster.TmuxFenster("agent-1").taste("")

        assert aufrufe == []
