"""Das Archiv der Diskussionen in SQLite."""

from __future__ import annotations

from pathlib import Path

from claude_sanctuary.kern import einstellungen
from claude_sanctuary.kern.debatte import Beitrag, Diskussion, Teilnehmer, Verbrauch
from claude_sanctuary.kern.diskussionsarchiv import Diskussionsarchiv, archiv_datei


def _diskussion(thema: str = "Unity oder Godot?",
                beginn: str = "2026-09-28T17:12:00") -> Diskussion:
    return Diskussion(
        thema=thema,
        teilnehmer=[Teilnehmer("Agatha", seite="pro", sitzung="s-1"),
                    Teilnehmer("Maria", "Spieleentwicklerin", "contra", "keine Antwort", "s-2")],
        runden=3, recherche=True, positionen=("Unity", "Godot"), beginn=beginn,
        ohne_kontext=True,
        beitraege=[Beitrag(0, "Maria", "- Notiz", "17:12:10", "vorbereitung", seite="contra"),
                   Beitrag(1, "Agatha", "Unity ist schneller.", "17:13:00", seite="pro"),
                   Beitrag(1, "Maria", "Godot ist frei.", "17:14:00", seite="contra",
                           ungeprueft=True)],
    )


class TestArchiv:
    def test_liegt_im_einstellungsordner(self) -> None:
        # conftest verlegt den Ordner - die echte Datei bleibt unberuehrt.
        assert archiv_datei().parent == einstellungen.VERZEICHNIS

    def test_speichern_und_laden_geben_dasselbe(self, tmp_path: Path) -> None:
        archiv = Diskussionsarchiv(tmp_path / "d.db")
        d = _diskussion()
        d.verbrauch = Verbrauch(1000, 50000, 200)
        kennung = archiv.speichern(d, "C:/protokoll.md")
        assert kennung == d.kennung > 0
        geladen = archiv.laden(kennung)
        assert geladen is not None
        zurueck, protokoll = geladen
        assert protokoll == "C:/protokoll.md"
        assert zurueck == d

    def test_erneutes_speichern_ersetzt_und_behaelt_das_protokoll(self, tmp_path: Path) -> None:
        archiv = Diskussionsarchiv(tmp_path / "d.db")
        d = _diskussion()
        archiv.speichern(d, "C:/protokoll.md")
        d.beitraege.append(Beitrag(2, "Agatha", "Noch was.", "17:15:00", seite="pro"))
        d.ende = "2 Runden gespielt"
        archiv.speichern(d)
        geladen = archiv.laden(d.kennung)
        assert geladen is not None
        assert len(geladen[0].beitraege) == 4
        assert geladen[0].ende == "2 Runden gespielt"
        assert geladen[1] == "C:/protokoll.md"
        assert len(archiv.liste()) == 1

    def test_liste_neueste_zuerst_mit_gespielten_runden(self, tmp_path: Path) -> None:
        archiv = Diskussionsarchiv(tmp_path / "d.db")
        alt = _diskussion("Alt", "2026-09-27T10:00:00")
        neu = _diskussion("Neu", "2026-09-28T10:00:00")
        neu.verbrauch = Verbrauch(100, 9999, 20)
        archiv.speichern(alt)
        archiv.speichern(neu)
        eintraege = archiv.liste()
        assert [e.thema for e in eintraege] == ["Neu", "Alt"]
        assert eintraege[0].teilnehmer == ("Agatha", "Maria")
        assert eintraege[0].runden == 1          # gespielt, nicht geplant (3)
        assert eintraege[0].tokens == 120        # ohne Cache-Lesung

    def test_unbekannte_nummer(self, tmp_path: Path) -> None:
        assert Diskussionsarchiv(tmp_path / "d.db").laden(42) is None
