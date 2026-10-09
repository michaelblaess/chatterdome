"""Das Archiv der Diskussionen in SQLite."""

from __future__ import annotations

from pathlib import Path

from chatterdome.kern import einstellungen
from chatterdome.kern.debatte import Beitrag, Diskussion, Teilnehmer, Verbrauch
from chatterdome.kern.diskussionsarchiv import Diskussionsarchiv, archiv_datei


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


class TestModell:
    def test_modell_der_diskussion_und_der_teilnehmer(self, tmp_path: Path) -> None:
        archiv = Diskussionsarchiv(tmp_path / "d.db")
        d = _diskussion()
        d.modell = "haiku"
        d.teilnehmer[0].modell = "claude-haiku-4-5-20251001"
        archiv.speichern(d)
        geladen = archiv.laden(d.kennung)
        assert geladen is not None
        assert geladen[0].modell == "haiku"
        assert geladen[0].teilnehmer[0].modell == "claude-haiku-4-5-20251001"
        assert archiv.liste()[0].modell == "haiku"

    def test_datei_vom_ersten_stand_bekommt_die_spalten_nachgetragen(
        self, tmp_path: Path
    ) -> None:
        import sqlite3

        datei = tmp_path / "alt.db"
        # Das Schema vom 28.09.2026, Commit 2572784 - noch ohne Modell.
        alt = sqlite3.connect(datei)
        alt.executescript(
            "CREATE TABLE diskussion (id INTEGER PRIMARY KEY AUTOINCREMENT, beginn TEXT NOT NULL,"
            " thema TEXT NOT NULL, format TEXT NOT NULL, runden INTEGER NOT NULL,"
            " recherche INTEGER NOT NULL, dauer_minuten REAL NOT NULL,"
            " position_pro TEXT NOT NULL, position_contra TEXT NOT NULL,"
            " schlussworte INTEGER NOT NULL, ohne_kontext INTEGER NOT NULL, ende TEXT NOT NULL,"
            " zusammenfassung TEXT NOT NULL, protokoll TEXT NOT NULL,"
            " tokens_neu INTEGER NOT NULL, tokens_cache INTEGER NOT NULL,"
            " tokens_aus INTEGER NOT NULL);"
            "CREATE TABLE teilnehmer (diskussion INTEGER NOT NULL, nr INTEGER NOT NULL,"
            " name TEXT NOT NULL, rolle TEXT NOT NULL, seite TEXT NOT NULL,"
            " ohne_recherche TEXT NOT NULL, sitzung TEXT NOT NULL, PRIMARY KEY (diskussion, nr));"
            "INSERT INTO diskussion VALUES (1, '2026-09-28T18:02:25', 'Alt', 'diskussion', 20,"
            " 1, 0, '', '', 0, 1, '', '', '', 1, 2, 3);"
            "INSERT INTO teilnehmer VALUES (1, 0, 'Agatha', '', 'pro', '', 's-1');"
        )
        alt.commit()
        alt.close()
        archiv = Diskussionsarchiv(datei)
        eintrag = archiv.liste()[0]
        assert (eintrag.thema, eintrag.modell) == ("Alt", "")
        geladen = archiv.laden(1)
        assert geladen is not None and geladen[0].teilnehmer[0].name == "Agatha"
        geladen[0].modell = "opus"
        archiv.speichern(geladen[0])
        assert archiv.liste()[0].modell == "opus"


class TestLoeschen:
    def test_loescht_diskussion_teilnehmer_und_beitraege(self, tmp_path: Path) -> None:
        import sqlite3

        archiv = Diskussionsarchiv(tmp_path / "d.db")
        bleibt, weg = _diskussion("bleibt"), _diskussion("weg")
        archiv.speichern(bleibt)
        archiv.speichern(weg)
        assert archiv.loeschen(weg.kennung) is True
        assert archiv.loeschen(weg.kennung) is False
        assert [e.thema for e in archiv.liste()] == ["bleibt"]
        with sqlite3.connect(tmp_path / "d.db") as db:
            for tabelle in ("teilnehmer", "beitrag"):
                rest = db.execute(f"SELECT count(*) FROM {tabelle} WHERE diskussion=?",
                                  (weg.kennung,)).fetchone()[0]
                assert rest == 0, tabelle

    def test_stimmung_und_entscheidung_ueberleben(self, tmp_path: Path) -> None:
        archiv = Diskussionsarchiv(tmp_path / "d.db")
        d = _diskussion()
        d.stimmung, d.entscheidung = "unfair", True
        d.beitraege.append(Beitrag(3, "Agatha", "ENTSCHEIDUNG: Godot.", "17:20:00",
                                   "entscheidung", seite="pro"))
        geladen = archiv.laden(archiv.speichern(d))
        assert geladen is not None
        assert geladen[0] == d
