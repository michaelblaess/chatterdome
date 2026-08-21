"""Darstellung des Auftragsverlaufs.

Michael hat am 09.08.2026 an einem Bildschirmfoto gezeigt, dass die Blasen
ohne Abstand aneinanderkleben. Die Basisregel setzte zwar ``margin: 0 0 1 0``,
aber die spezifischeren Regeln fuer ``eigen`` und ``fremd`` nur
``margin-left`` bzw. ``margin-right`` - und Textual fuehrt ``margin`` als EINE
Eigenschaft. Die spezifischere Regel ersetzte damit den ganzen Wert samt dem
unteren Abstand. Gemessen kam ``bottom=0`` heraus.

GEPRUEFT WIRD IN EINER MINIMALEN APP, nicht in der echten. Der erste Anlauf
fuhr ``SanctuaryApp`` hoch und rief ``zeigen()`` von aussen auf - unter Windows
gruen, auf den Linux-Laeufern der CI kamen null Blasen heraus. Ursache ist kein
Timing, sondern ein Rennen: die App verwaltet dasselbe Panel selbst und leert
es beim naechsten Durchlauf wieder. Auch eine Warteschleife half deshalb nicht.
Hier haengt das Panel allein in einer App, die sonst nichts tut - dasselbe
Stylesheet, aber niemand raeumt dazwischen.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult

import claude_sanctuary.tui as tui_paket
from claude_sanctuary.kern.modelle import Auftrag, Ereignis
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel

TCSS = Path(tui_paket.__file__).parent / "app.tcss"


class NurVerlauf(App[None]):
    """Traegt nur das Verlaufspanel - und das echte Stylesheet."""

    CSS_PATH = TCSS

    def compose(self) -> ComposeResult:
        yield VerlaufPanel(id="verlauf")


def _auftrag() -> Auftrag:
    return Auftrag(
        auftrag_id="x",
        zustand="submitted",
        an="Petra",
        text="wie ist der freie RAM auf Senza?",
        verlauf=[
            Ereignis(
                art="auftrag",
                ts="2026-08-09T04:50:00",
                von="Sanctuary",
                host="RAINBOW",
                an="Petra",
                an_host="SENZA",
                text="wie ist der freie RAM auf Senza?",
            ),
            Ereignis(
                art="quittung",
                ts="2026-08-09T04:51:00",
                von="Petra",
                host="SENZA",
                an="Sanctuary",
                an_host="RAINBOW",
                status=200,
                notiz="Senza: 21 GiB frei von 30 GiB",
            ),
        ],
    )


async def _blasen(panel: VerlaufPanel, pilot: Any) -> list[Any]:
    """Wartet, bis die Blasen haengen. Mounten ist asynchron."""
    for _ in range(60):
        await pilot.pause()
        blasen = [k for k in panel.children if "blase" in k.classes]
        if len(blasen) >= 2:
            return blasen
    return [k for k in panel.children if "blase" in k.classes]


@pytest.mark.asyncio
class TestAbstandZwischenBlasen:
    async def test_jede_blase_hat_unten_abstand(self) -> None:
        """Sonst klebt die naechste Nachricht direkt an der vorigen."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert len(blasen) == 2, "Auftrag und Quittung sollen zwei Blasen ergeben"
            for blase in blasen:
                klassen = " ".join(sorted(blase.classes))
                assert blase.styles.margin.bottom >= 1, f"{klassen} klebt an der naechsten"

    async def test_die_seitliche_einrueckung_bleibt_erhalten(self) -> None:
        """Sie unterscheidet eigene von fremden Nachrichten - beim Reparieren
        des unteren Abstands darf sie nicht verlorengehen."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            # Mit Vorgabewert statt blossem next(): ohne ihn wirft next() eine
            # StopIteration, und die wird in einer Koroutine zu einem
            # RuntimeError - der verdeckt, woran es wirklich lag.
            eigen = next((k for k in blasen if "eigen" in k.classes), None)
            fremd = next((k for k in blasen if "fremd" in k.classes), None)
            assert eigen is not None, "die eigene Blase fehlt"
            assert fremd is not None, "die fremde Blase fehlt"
            assert eigen.styles.margin.left > 0
            assert fremd.styles.margin.right > 0


def _zweiter_auftrag() -> Auftrag:
    """Ein spaeter eingegangener Auftrag, mit eigener Kennung."""
    return Auftrag(
        auftrag_id="y",
        zustand="submitted",
        an="Petra",
        text="und wie voll ist die Platte?",
        verlauf=[
            Ereignis(
                art="auftrag",
                ts="2026-08-09T05:10:00",
                von="Sanctuary",
                host="RAINBOW",
                text="und wie voll ist die Platte?",
            ),
        ],
    )


@pytest.mark.asyncio
class TestAnsichtLeeren:
    """Das Leeren betrifft NUR die Anzeige - der Bus bleibt unberuehrt."""

    async def test_leeren_entfernt_die_blasen(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)

            panel.ansicht_leeren()
            await pilot.pause()

            assert [k for k in panel.children if "blase" in k.classes] == []
            assert panel.etwas_ausgeblendet

    async def test_neue_auftraege_erscheinen_wieder(self) -> None:
        """Sonst waere das Fenster nach einmal Leeren dauerhaft tot."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)
            panel.ansicht_leeren()
            await pilot.pause()

            # Der naechste Durchlauf bringt den alten UND einen neuen Auftrag.
            panel.zeigen("Petra@SENZA", [_auftrag(), _zweiter_auftrag()])
            for _ in range(60):
                await pilot.pause()
                if [k for k in panel.children if "blase" in k.classes]:
                    break

            texte = [k.klartext for k in panel.children if "blase" in k.classes]
            assert len(texte) == 1, f"nur der neue Auftrag gehoert hierher: {texte}"
            assert "Platte" in texte[0]

    async def test_alles_zeigen_nimmt_es_zurueck(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)
            panel.ansicht_leeren()
            await pilot.pause()

            panel.alles_zeigen()
            blasen = await _blasen(panel, pilot)

            assert len(blasen) == 2
            assert not panel.etwas_ausgeblendet

    async def test_partnerwechsel_hebt_das_ausblenden_auf(self) -> None:
        """Die Marke gilt dem Verlauf, den der Anwender vor sich hatte."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)
            panel.ansicht_leeren()
            await pilot.pause()

            panel.zeigen("Lino@RAINBOW", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert len(blasen) == 2, "beim anderen Agenten darf nichts verborgen sein"


@pytest.mark.asyncio
class TestKopierenUndSpeichern:
    async def test_sichtbarer_text_ist_klartext(self) -> None:
        """Ohne Rich-Auszeichnung - der Text geht in Zwischenablage und Datei."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)

            text = panel.sichtbarer_text()

            assert "wie ist der freie RAM auf Senza?" in text
            assert "21 GiB frei" in text
            assert "[" not in text, "Rich-Auszeichnung gehoert nicht in die Datei"

    async def test_geleerte_ansicht_liefert_keinen_text(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await _blasen(panel, pilot)
            panel.ansicht_leeren()
            await pilot.pause()

            assert panel.sichtbarer_text() == ""

    async def test_vorschlagsname_taugt_als_dateiname(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            await pilot.pause()

            name = panel.vorschlagsname()

            assert name == "verlauf-Petra@SENZA.txt"
            # Kein Zeichen, an dem ein Dateisystem sich stoert.
            assert not set(name) & set('\\/:*?"<>|')


@pytest.mark.asyncio
class TestKopfzeile:
    """Beide Seiten, nicht nur der Absender.

    Michael am 14.08.2026: bei einer Quittung stand nur, WER geantwortet hat -
    nicht, an welchen von zwei gleichnamigen Agenten sie ging. Im Mesh ist der
    Name eine Pacht pro Rechner, "Operator" allein ist also mehrdeutig.
    """

    async def test_auftrag_nennt_absender_und_empfaenger(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert "Sanctuary@RAINBOW -> Petra@SENZA" in blasen[0].klartext

    async def test_quittung_zeigt_den_rueckweg(self) -> None:
        """Sie laeuft zurueck an den Rechner, von dem der Auftrag kam."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert "Petra@SENZA -> Sanctuary@RAINBOW" in blasen[1].klartext


class MitMenue(NurVerlauf):
    """Faengt die Menue-Meldung ab, wie die echte App es tut."""

    def __init__(self) -> None:
        super().__init__()
        self.meldungen: list[VerlaufPanel.MenueGewuenscht] = []

    def on_verlauf_panel_menue_gewuenscht(
        self, ereignis: VerlaufPanel.MenueGewuenscht
    ) -> None:
        self.meldungen.append(ereignis)


@pytest.mark.asyncio
class TestRechtsklick:
    async def test_rechtsklick_auf_eine_blase_meldet_sie_mit(self) -> None:
        """Ohne die Blase wuesste das Menue nicht, worauf es zeigt."""
        app = MitMenue()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            await pilot.click(blasen[0], button=3)
            await pilot.pause()

            assert len(app.meldungen) == 1, "der Rechtsklick kam nicht an"
            assert app.meldungen[0].blase is not None
            assert app.meldungen[0].blase.auftrag_id == "x"

    async def test_linksklick_oeffnet_kein_menue(self) -> None:
        app = MitMenue()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            await pilot.click(blasen[0])
            await pilot.pause()

            assert app.meldungen == []


def _offener_auftrag(zustand: str = "submitted", vor_sekunden: int = 8) -> Auftrag:
    """Ein Auftrag, dessen Zustandswechsel gerade eben war."""
    from datetime import datetime, timedelta

    stempel = (datetime.now().astimezone() - timedelta(seconds=vor_sekunden)).isoformat()
    return Auftrag(
        auftrag_id="offen",
        zustand=zustand,
        an="Patsy",
        text="Bitte die Tests laufen lassen",
        erstellt=stempel,
        geaendert=stempel,
        verlauf=[
            Ereignis(
                art="auftrag",
                ts=stempel,
                von="Sanctuary",
                host="RAINBOW",
                an="Patsy",
                an_host="RAINBOW",
                text="Bitte die Tests laufen lassen",
            )
        ],
    )


class TestWarteanzeigeInDerBlase:
    """Michaels Wunsch vom 21.08.2026: sehen, dass etwas passiert.

    Geprueft wird der gerenderte Text, nicht die Logik dahinter - die hat
    ihren eigenen Test in ``test_warten.py``.
    """

    async def test_offener_auftrag_zeigt_die_wartezeit(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Patsy@RAINBOW", [_offener_auftrag(vor_sekunden=8)])
            blasen = await _blasen(panel, pilot)

            assert "0:0" in blasen[0].klartext, blasen[0].klartext

    async def test_die_punkte_kommen_im_gerenderten_text_an(self) -> None:
        """Der eigene Takt wird angehalten, sonst zaehlt er bis zur Pruefung
        weiter - und das Mounten ist asynchron, ein Blick ohne Warten traefe
        noch die alte Blase. Ein spaeter zugewiesenes _tick genuegt nicht:
        set_interval haelt die beim Mounten gebundene Methode fest."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel._punkte_timer.stop()
            panel._takt = 2
            panel.zeigen("Patsy@RAINBOW", [_offener_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert ".." in blasen[0].klartext, blasen[0].klartext

    async def test_erledigter_auftrag_bekommt_keine_punkte(self) -> None:
        """Sonst liefe die Animation neben einem Ergebnis, das schon da ist."""
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel._takt = 2
            panel.zeigen("Patsy@RAINBOW", [_offener_auftrag(zustand="completed")])
            blasen = await _blasen(panel, pilot)

            assert ".." not in blasen[0].klartext

    async def test_nach_der_frist_steht_die_stille_da(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Patsy@RAINBOW", [_offener_auftrag(vor_sekunden=300)])
            blasen = await _blasen(panel, pilot)

            text = blasen[0].klartext
            # Nicht auf die Sekunde genau pruefen: zwischen dem Bauen des
            # Auftrags und dem Zeichnen vergeht echte Zeit.
            assert "keine Reaktion seit 5:0" in text, text
            assert "..." not in text, "nach der Frist wird nicht mehr animiert"

    async def test_ohne_zeitstempel_keine_erfundene_zahl(self) -> None:
        app = NurVerlauf()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            auftrag = _offener_auftrag()
            auftrag.erstellt = ""
            auftrag.geaendert = ""
            panel.zeigen("Patsy@RAINBOW", [auftrag])
            blasen = await _blasen(panel, pilot)

            # NICHT auf "0:" pruefen - das trifft nachts die Uhrzeit im Kopf
            # (00:54). Gemeint ist die Wartezeit HINTER dem Zustandswort.
            text = blasen[0].klartext
            assert not re.search(r"abgelegt\s+\.*\s*\d+:\d\d", text), text
            assert "keine Reaktion" not in text, text
