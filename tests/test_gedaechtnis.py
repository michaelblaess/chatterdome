"""Tests der Gedaechtnisanalyse.

Alle Tests bauen ihren Bestand in einem eigenen Verzeichnis auf. Ein Test, der
das echte Gedaechtnis unter ``~/.claude/memory`` liest, waere von Michaels
Arbeitsstand abhaengig und morgen rot, ohne dass sich Code geaendert haette.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_sanctuary.kern.gedaechtnis import (
    Recallbericht,
    lade_gedaechtnis,
    normalisiere,
    schaetze_tokens,
    uebernimm_recalls,
    zaehle_recalls,
)


def _notiz(
    ordner: Path,
    name: str,
    typ: str = "reference",
    beschreibung: str = "Eine Notiz",
    rumpf: str = "Inhalt.",
) -> Path:
    datei = ordner / f"{name}.md"
    datei.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {beschreibung}\n"
        "metadata:\n"
        "  node_type: memory\n"
        f"  type: {typ}\n"
        "---\n\n"
        f"{rumpf}\n",
        encoding="utf-8",
        newline="\n",
    )
    return datei


def _index(ordner: Path, zeilen: list[str]) -> None:
    (ordner / "MEMORY.md").write_text(
        "\n".join(zeilen) + "\n", encoding="utf-8", newline="\n"
    )


class TestLaden:
    def test_leeres_verzeichnis_liefert_leeren_bestand(self, tmp_path: Path) -> None:
        bestand = lade_gedaechtnis(tmp_path)
        assert bestand.anzahl == 0
        assert not bestand.index_vorhanden
        assert bestand.befunde() == []

    def test_fehlendes_verzeichnis_wirft_nicht(self, tmp_path: Path) -> None:
        bestand = lade_gedaechtnis(tmp_path / "gibt-es-nicht")
        assert bestand.anzahl == 0

    def test_frontmatter_wird_gelesen(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "reference_alpha", typ="feedback", beschreibung="Kurz erklaert")
        _index(tmp_path, ["- [Alpha](reference_alpha.md) - Haken"])

        notiz = lade_gedaechtnis(tmp_path).notizen[0]
        assert notiz.name == "reference_alpha"
        assert notiz.typ == "feedback"
        assert notiz.beschreibung == "Kurz erklaert"
        assert notiz.im_index
        assert notiz.index_text == "Alpha"

    def test_index_wird_nicht_als_notiz_gezaehlt(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_eins")
        _index(tmp_path, ["- [Eins](project_eins.md) - Haken"])

        bestand = lade_gedaechtnis(tmp_path)
        assert bestand.anzahl == 1
        assert bestand.index_vorhanden
        assert bestand.index_eintraege == 1

    def test_beschreibung_in_anfuehrungszeichen_wird_entkleidet(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_zitat", beschreibung='"Mit Anfuehrungszeichen"')
        assert lade_gedaechtnis(tmp_path).notizen[0].beschreibung == "Mit Anfuehrungszeichen"

    def test_datei_ohne_frontmatter_faellt_auf_den_dateinamen_zurueck(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "rohnotiz.md").write_text("Nur Text.\n", encoding="utf-8", newline="\n")

        notiz = lade_gedaechtnis(tmp_path).notizen[0]
        assert notiz.name == "rohnotiz"
        assert notiz.typ == ""


class TestVerweise:
    def test_wikilink_erzeugt_beide_richtungen(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a", rumpf="Siehe [[project_b]].")
        _notiz(tmp_path, "project_b")

        bestand = lade_gedaechtnis(tmp_path)
        a = bestand.finde("project_a")
        b = bestand.finde("project_b")
        assert a is not None and b is not None
        assert a.verweist_auf == ["project_b"]
        assert b.eingehend == ["project_a"]
        assert a.isoliert
        assert not b.isoliert

    def test_wikilink_ins_leere_ist_ein_befund(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a", rumpf="Siehe [[gibt_es_nicht]].")
        _index(tmp_path, ["- [A](project_a.md) - Haken"])

        bestand = lade_gedaechtnis(tmp_path)
        notiz = bestand.finde("project_a")
        assert notiz is not None
        assert notiz.tote_verweise == ["gibt_es_nicht"]
        assert [b.art for b in bestand.befunde()] == ["toter_wikilink"]

    def test_selbstbezug_macht_eine_notiz_nicht_verbunden(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a", rumpf="Ich verweise auf [[project_a]].")

        notiz = lade_gedaechtnis(tmp_path).finde("project_a")
        assert notiz is not None
        assert notiz.verweist_auf == []
        assert notiz.isoliert, "Ein Selbstbezug darf keine Verbindung vortaeuschen"

    def test_bindestrich_und_unterstrich_gelten_als_derselbe_name(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "feedback_alt_neu", rumpf="Nichts.")
        _notiz(tmp_path, "project_b", rumpf="Siehe [[feedback-alt-neu]].")

        ziel = lade_gedaechtnis(tmp_path).finde("feedback_alt_neu")
        assert ziel is not None
        assert ziel.eingehend == ["project_b"], "Historische Bindestrichnamen muessen greifen"


class TestBefunde:
    def test_waise_wird_erkannt(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_ohne_index")
        _index(tmp_path, ["# Index ohne Eintraege"])

        bestand = lade_gedaechtnis(tmp_path)
        assert [n.name for n in bestand.waisen] == ["project_ohne_index"]
        assert any(b.art == "waise" for b in bestand.befunde())

    def test_toter_index_verweis_wird_erkannt(self, tmp_path: Path) -> None:
        _index(tmp_path, ["- [Weg](project_geloescht.md) - Haken"])

        bestand = lade_gedaechtnis(tmp_path)
        assert bestand.unbekannte_index_verweise == ["project_geloescht"]
        assert any(b.art == "toter_verweis" for b in bestand.befunde())

    def test_fehlender_typ_wird_gemeldet(self, tmp_path: Path) -> None:
        (tmp_path / "ohne_typ.md").write_text(
            "---\nname: ohne_typ\ndescription: x\n---\n\nText.\n",
            encoding="utf-8",
            newline="\n",
        )
        _index(tmp_path, ["- [Ohne](ohne_typ.md) - Haken"])

        assert any(b.art == "ohne_typ" for b in lade_gedaechtnis(tmp_path).befunde())

    def test_sauberer_bestand_hat_keine_befunde(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a", rumpf="Siehe [[project_b]].")
        _notiz(tmp_path, "project_b", rumpf="Siehe [[project_a]].")
        _index(
            tmp_path,
            ["- [A](project_a.md) - Haken", "- [B](project_b.md) - Haken"],
        )

        assert lade_gedaechtnis(tmp_path).befunde() == []


class TestKennzahlen:
    def test_typverteilung_haelt_die_vorgesehene_reihenfolge(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "a_ref", typ="reference")
        _notiz(tmp_path, "b_user", typ="user")
        _notiz(tmp_path, "c_proj", typ="project")

        # Nach Dateinamen waere die Folge ref, user, proj - erwartet wird die
        # Reihenfolge der Anleitung, damit die Balken nicht springen.
        assert list(lade_gedaechtnis(tmp_path).nach_typ) == ["user", "project", "reference"]

    def test_index_und_bestand_werden_getrennt_gerechnet(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_gross", rumpf="x" * 7000)
        _index(tmp_path, ["- [Gross](project_gross.md) - Haken"])

        bestand = lade_gedaechtnis(tmp_path)
        assert bestand.bestand_tokens > bestand.index_tokens * 10, (
            "Die Trennung der beiden Kosten ist die Kernaussage des Tabs"
        )

    def test_tokens_je_indexzeile(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a")
        _notiz(tmp_path, "project_b")
        _index(
            tmp_path,
            ["- [A](project_a.md) - Haken", "- [B](project_b.md) - Haken"],
        )

        bestand = lade_gedaechtnis(tmp_path)
        assert bestand.tokens_je_indexzeile == round(bestand.index_tokens / 2)

    def test_ohne_index_kein_teilen_durch_null(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a")
        assert lade_gedaechtnis(tmp_path).tokens_je_indexzeile == 0

    def test_groesste_zuerst(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_klein", rumpf="kurz")
        _notiz(tmp_path, "project_gross", rumpf="\n".join(["Zeile"] * 60))

        assert lade_gedaechtnis(tmp_path).groesste(1)[0].name == "project_gross"

    def test_erledigt_verdacht(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_fertig", rumpf="Der Vorgang ist ABGESCHLOSSEN.")
        _notiz(tmp_path, "project_offen", rumpf="Laeuft noch.")

        assert [n.name for n in lade_gedaechtnis(tmp_path).erledigte] == ["project_fertig"]

    def test_schaetzung_ist_monoton(self) -> None:
        assert schaetze_tokens(0) == 0
        assert schaetze_tokens(3500) < schaetze_tokens(7000)

    def test_normalisierung(self) -> None:
        assert normalisiere("Feedback-Git-Repo") == "feedback_git_repo"
        assert normalisiere("  project_a  ") == "project_a"


def _transkript(ordner: Path, name: str, saetze: list[dict[str, object]]) -> Path:
    datei = ordner / f"{name}.jsonl"
    datei.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in saetze) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return datei


def _abruf(name: str, tage: int = 3) -> dict[str, object]:
    text = (
        f"<system-reminder>This memory is {tage} days old. Memories are "
        "point-in-time observations.</system-reminder>\n"
        f"1\t---\n2\tname: {name}\n3\tdescription: egal\n4\tmetadata: \n"
    )
    return {"type": "user", "message": {"content": [{"type": "text", "content": text}]}}


class TestRecalls:
    def test_abruf_wird_gezaehlt(self, tmp_path: Path) -> None:
        _transkript(tmp_path, "sitzung", [_abruf("project_a"), _abruf("project_a")])

        bericht = zaehle_recalls(tmp_path, {"project_a", "project_b"})
        assert bericht.treffer == {"project_a": 2}
        assert bericht.bloecke == 2
        assert bericht.unzugeordnet == 0

    def test_blosse_erwaehnung_zaehlt_nicht(self, tmp_path: Path) -> None:
        # Genau die Falle, die ein naives grep hat: der Name steht in einer
        # ganz normalen Werkzeugausgabe, ohne dass etwas abgerufen wurde.
        _transkript(
            tmp_path,
            "sitzung",
            [
                {
                    "type": "user",
                    "message": {"content": "memory/project_a.md | 24 +-\n memory/project_b.md"},
                }
            ],
        )

        bericht = zaehle_recalls(tmp_path, {"project_a", "project_b"})
        assert bericht.treffer == {}
        assert bericht.bloecke == 0

    def test_eigene_auswertung_zaehlt_sich_nicht_selbst(self, tmp_path: Path) -> None:
        """Der Fall, der beim Bau dieses Moduls wirklich eingetreten ist.

        Wer in einer Sitzung die Transkripte nach Abrufen durchsucht, dessen
        Ausgabe landet im laufenden Transkript. Ohne das oeffnende Element im
        Marker zaehlt die Auswertung ihre eigene Ausgabe als Abruf mit - beim
        echten Bestand waren das 24 von 67 Fundstellen.
        """
        ausgabe = (
            "      6 system-reminder>This memory is 4 days old. Memories are point-in-time\n"
            "      3 system-reminder>This memory is 3 days old. Memories are point-in-time\n"
        )
        _transkript(
            tmp_path,
            "sitzung",
            [{"type": "user", "message": {"content": ausgabe}}, _abruf("project_a")],
        )

        bericht = zaehle_recalls(tmp_path, {"project_a"})
        assert bericht.bloecke == 1, "Nur der echte Abruf zaehlt, nicht die Ausgabe darueber"
        assert bericht.treffer == {"project_a": 1}

    def test_historischer_bindestrichname_wird_zugeordnet(self, tmp_path: Path) -> None:
        _transkript(tmp_path, "sitzung", [_abruf("feedback-alt-neu")])

        bericht = zaehle_recalls(tmp_path, {"feedback_alt_neu"})
        assert bericht.treffer == {"feedback_alt_neu": 1}

    def test_ausschnitt_ohne_frontmatter_wird_ausgewiesen(self, tmp_path: Path) -> None:
        satz = {
            "type": "user",
            "message": {
                "content": (
                    "<system-reminder>This memory is 8 days old.</system-reminder>\n"
                    "174\tirgendein Ausschnitt aus der Mitte der Notiz\n"
                )
            },
        }
        _transkript(tmp_path, "sitzung", [satz])

        bericht = zaehle_recalls(tmp_path, {"project_a"})
        assert bericht.bloecke == 1
        assert bericht.unzugeordnet == 1, "Nicht zuordenbar heisst ausweisen, nicht verschweigen"
        assert bericht.zugeordnet == 0

    def test_unbekannter_name_zaehlt_als_unzugeordnet(self, tmp_path: Path) -> None:
        _transkript(tmp_path, "sitzung", [_abruf("project_laengst_geloescht")])

        bericht = zaehle_recalls(tmp_path, {"project_a"})
        assert bericht.unzugeordnet == 1
        assert bericht.treffer == {}

    def test_juengstes_alter_gewinnt(self, tmp_path: Path) -> None:
        _transkript(tmp_path, "sitzung", [_abruf("project_a", tage=9), _abruf("project_a", tage=2)])

        assert zaehle_recalls(tmp_path, {"project_a"}).letztes_alter == {"project_a": 2}

    def test_unterordner_werden_mitgelesen(self, tmp_path: Path) -> None:
        tief = tmp_path / "sitzung" / "subagents"
        tief.mkdir(parents=True)
        _transkript(tief, "kind", [_abruf("project_a")])

        assert zaehle_recalls(tmp_path, {"project_a"}).treffer == {"project_a": 1}

    def test_kaputte_zeile_bricht_den_durchgang_nicht_ab(self, tmp_path: Path) -> None:
        datei = tmp_path / "sitzung.jsonl"
        gut = json.dumps(_abruf("project_a"), ensure_ascii=False)
        datei.write_text(
            "{kein gueltiges json mit This memory is drin\n" + gut + "\n",
            encoding="utf-8",
            newline="\n",
        )

        assert zaehle_recalls(tmp_path, {"project_a"}).treffer == {"project_a": 1}

    def test_fehlendes_verzeichnis_liefert_leeren_bericht(self, tmp_path: Path) -> None:
        bericht = zaehle_recalls(tmp_path / "weg", {"project_a"})
        assert bericht.bloecke == 0
        assert bericht.dateien == 0

    def test_uebernahme_traegt_die_zahlen_in_die_notizen(self, tmp_path: Path) -> None:
        _notiz(tmp_path, "project_a")
        _notiz(tmp_path, "project_b")
        bestand = lade_gedaechtnis(tmp_path)
        bericht = Recallbericht(treffer={"project_a": 4}, letztes_alter={"project_a": 2})

        uebernimm_recalls(bestand, bericht)

        a = bestand.finde("project_a")
        b = bestand.finde("project_b")
        assert a is not None and b is not None
        assert (a.recalls, a.letzter_recall_tage) == (4, 2)
        assert (b.recalls, b.letzter_recall_tage) == (0, None)
        assert bestand.recall_bericht is bericht
