"""Der Demo-Modus: erfundene Daten auf jedem Bildschirm, nichts Echtes.

Der Kern ist ``TestNichtsEchtes``: die App laeuft im Demo-Modus, jeder Reiter
und jeder Dialog wird geoeffnet, und der gerenderte Text darf kein Kennzeichen
des echten Rechners enthalten - Benutzername, Rechnername, Heimatpfad, die
Namen der echten Notizen und der echten Projektordner. Die Kennzeichen werden
zur Laufzeit erhoben, gelten also fuer jeden, der den Test startet.
"""

from __future__ import annotations

import functools
import getpass
import html
import json
import os
import platform
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest
from textual.widgets import TabbedContent

from chatterdome import __author__, debatte_ablauf, demo_ablauf, i18n
from chatterdome.kern import umgebung
from chatterdome.kern.debatte import CONTRA, PRO, Diskussion, Teilnehmer
from chatterdome.kern.demo_daten import erzeugen
from chatterdome.kern.demo_quelle import DemoQuelle
from chatterdome.kern.demo_texte import AGENTEN, NOTIZEN, SKRIPT
from chatterdome.kern.diskussionsarchiv import Diskussionsarchiv
from chatterdome.kern.protokolle import Quelle
from chatterdome.tui.app import ChatterdomeApp
from chatterdome.tui.widgets.diskussion_panel import DiskussionsAuftrag, DiskussionsPanel

QUELLTEXT = Path(__file__).resolve().parents[1] / "src" / "chatterdome"

REITER = ("agenten", "bus", "diskussion", "statistik", "suche", "gedaechtnis")


# -- Kennzeichen des echten Rechners -------------------------------------------


def _wortschatz() -> set[str]:
    """Woerter, die die Oberflaeche oder die Demo selbst mitbringt.

    Ein echter Ordner namens ``memory`` ist von der Beschriftung "Memory" nicht
    zu unterscheiden - solche Kennzeichen taugen nicht als Beweis und fallen raus.
    """
    texte: list[str] = []
    for sprache in ("de", "en"):
        werte = json.loads((QUELLTEXT / "locale" / f"{sprache}.json").read_text(encoding="utf-8"))
        texte.extend(str(w) for w in werte.values())
    for modul in ("kern/demo_texte.py", "kern/demo_quelle.py", "kern/demo_daten.py"):
        texte.append((QUELLTEXT / modul).read_text(encoding="utf-8"))
    return {w.casefold() for text in texte for w in re.findall(r"[\w.\-]+", text)}


def _cwd(transkript: Path) -> str:
    try:
        with transkript.open(encoding="utf-8", errors="replace") as strom:
            for nummer, zeile in enumerate(strom):
                if nummer > 30:
                    break
                with_cwd = re.search(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', zeile)
                if with_cwd:
                    return str(json.loads(f'"{with_cwd.group(1)}"'))
    except OSError:
        return ""
    return ""


def echte_kennzeichen() -> set[str]:
    """Was auf keinem Demo-Bildschirm stehen darf. MUSS vor dem Umbiegen laufen."""
    heim = Path.home()
    kennzeichen = {getpass.getuser(), platform.node(), str(heim)}
    claude = heim / ".claude"
    demo_notizen = {n.name for n in NOTIZEN}
    kennzeichen |= {d.stem for d in (claude / "memory").glob("*.md")} - demo_notizen
    for ordner in sorted((claude / "projects").glob("*"))[:300]:
        for transkript in sorted(ordner.glob("*.jsonl"))[:1]:
            roh = _cwd(transkript)
            if roh:
                pfad = PureWindowsPath(roh) if "\\" in roh else PurePosixPath(roh)
                kennzeichen.add(pfad.name)
    bekannt = _wortschatz()
    return {k for k in kennzeichen if len(k) >= 3 and k.casefold() not in bekannt}


def bildschirmtext(app: ChatterdomeApp) -> str:
    """Der sichtbare Text des aktuellen Bildschirms."""
    svg = app.export_screenshot()
    return html.unescape(re.sub(r"<[^>]+>", " ", svg)).replace("\xa0", " ")


APP_ANGABEN = (__author__, "michaelblaess.de", "github.com/michaelblaess/chatterdome")
"""Autor und Adressen der App im Info-Dialog - Angaben zur App, keine Nutzerdaten.

Sie fallen NUR dort heraus: derselbe Name als Projektordner in der Statistik
waere ein Leck.
"""


def _ohne_app_angaben(text: str) -> str:
    for angabe in APP_ANGABEN:
        text = text.replace(angabe, "")
    return text


def funde(text: str, kennzeichen: set[str]) -> set[str]:
    return {k for k in kennzeichen
            if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", text)}


# -- Demo-Modus im Test --------------------------------------------------------


def _neutrale_wurzel() -> Path:
    """Ein Ort ohne Benutzernamen im Pfad - so wie die echte Vorgabe."""
    basis = Path("/tmp") if os.name != "nt" else Path(Path.home().anchor)
    return basis / f"chatterdome-demo-test-{uuid.uuid4().hex[:8]}"


def _ruecksetzbar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Merkt sich alles, was ``demo_aktivieren`` aendert, fuer das Zuruecksetzen.

    Die Konstanten in ``einstellungen`` und ``absturz`` hat conftest schon verlegt.
    """
    for name in ("USERPROFILE", "HOME", "TEMP", "TMP", "TMPDIR", "COMPUTERNAME"):
        # setenv merkt sich den alten Zustand, auch "gab es nicht".
        monkeypatch.setenv(name, os.environ.get(name, "platzhalter"))
    monkeypatch.setattr(umgebung, "_demo", False)
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)


@pytest.fixture
def demo_zuhause(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Schaltet den Demo-Modus ein und nach dem Test sauber wieder aus."""
    _ruecksetzbar(monkeypatch)
    wurzel = _neutrale_wurzel()
    zuhause = umgebung.demo_aktivieren(wurzel)
    try:
        yield zuhause
    finally:
        shutil.rmtree(wurzel, ignore_errors=True)


async def _warten(pilot: Any, runden: int = 40) -> None:
    for _ in range(runden):
        await pilot.pause(0.05)


async def _alle_bildschirme(app: ChatterdomeApp, pilot: Any) -> dict[str, str]:
    """Oeffnet jeden Reiter und jeden Dialog und sammelt den Text ein."""
    texte: dict[str, str] = {}
    await _warten(pilot)
    for reiter in REITER:
        app.query_one("#bereiche", TabbedContent).active = f"tab-{reiter}"
        await _warten(pilot, 60)
        texte[reiter] = bildschirmtext(app)

    app.query_one("#bereiche", TabbedContent).active = "tab-agenten"
    await _warten(pilot, 10)
    for aktion in ("show_details", "show_settings", "show_about", "show_help", "show_usage"):
        await app.run_action(aktion)
        await _warten(pilot, 20)
        texte[aktion] = bildschirmtext(app)
        if aktion == "show_about":
            texte[aktion] = _ohne_app_angaben(texte[aktion])
        # Dialoge mit Seiten: jede Seite einmal zeigen.
        for tabs in app.screen.query(TabbedContent):
            for pane in tabs.query("TabPane"):
                if pane.id:
                    tabs.active = pane.id
                    await _warten(pilot, 5)
                    texte[f"{aktion}:{pane.id}"] = bildschirmtext(app)
        if len(app.screen_stack) > 1:
            app.pop_screen()
            await _warten(pilot, 5)
    return texte


# -- Tests ------------------------------------------------------------------------


class TestNichtsEchtes:
    @pytest.mark.parametrize("sprache", ["de", "en"])
    async def test_kein_bildschirm_verraet_den_rechner(self, sprache: str,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        # Vor dem Umbiegen erheben, danach zeigt Path.home() ins Demo-Zuhause.
        kennzeichen = echte_kennzeichen()
        _ruecksetzbar(monkeypatch)
        wurzel = _neutrale_wurzel()
        try:
            zuhause = umgebung.demo_aktivieren(wurzel)
            i18n.load_locale(sprache)
            erzeugen(zuhause, sprache)
            app = ChatterdomeApp(quelle=DemoQuelle(sprache))
            async with app.run_test(size=(180, 50)) as pilot:
                texte = await _alle_bildschirme(app, pilot)
        finally:
            shutil.rmtree(wurzel, ignore_errors=True)

        # Ohne gefuellte Bildschirme waere "nichts gefunden" kein Beweis.
        assert "Sirius" in texte["agenten"]
        assert "home-lab" in texte["statistik"]
        assert "feedback_tests_first" in texte["gedaechtnis"]
        assert "WORKSTATION" in texte["agenten"]
        assert len(texte) > len(REITER) + 5

        lecks = {wo: sorted(funde(text, kennzeichen)) for wo, text in texte.items()}
        assert {wo: f for wo, f in lecks.items() if f} == {}

    async def test_eingeschleustes_kennzeichen_wird_gefunden(self, demo_zuhause: Path) -> None:
        """Gegenprobe: ohne sie waere ein leerer Befund auch bei kaputter Suche gruen."""
        erzeugen(demo_zuhause, "en")
        quelle = DemoQuelle("en")
        quelle._agenten[0].aufgabe = "ZZLECKZZ im Auftrag"
        app = ChatterdomeApp(quelle=quelle)
        async with app.run_test(size=(180, 50)) as pilot:
            await _warten(pilot)
            text = bildschirmtext(app)

        assert funde(text, {"ZZLECKZZ", "ZZNIEZZ"}) == {"ZZLECKZZ"}


class TestUmgebung:
    def test_rechnername_im_demo_modus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(umgebung, "_demo", True)
        assert umgebung.rechnername() == "WORKSTATION"
        monkeypatch.setattr(umgebung, "_demo", False)
        assert umgebung.rechnername() == platform.node()

    def test_fremder_ordner_wird_nie_geleert(self, tmp_path: Path) -> None:
        fremd = tmp_path / "wichtig"
        fremd.mkdir()
        (fremd / "daten.txt").write_text("bleibt", encoding="utf-8")

        with pytest.raises(RuntimeError, match="kein Demo-Verzeichnis"):
            umgebung._leeren(fremd)
        assert (fremd / "daten.txt").read_text(encoding="utf-8") == "bleibt"

    def test_alte_demo_wird_geleert(self, tmp_path: Path) -> None:
        alt = tmp_path / "demo"
        alt.mkdir()
        (alt / umgebung.MARKE).write_text("", encoding="utf-8")
        (alt / "rest.txt").write_text("", encoding="utf-8")

        umgebung._leeren(alt)
        assert not alt.exists()

    def test_aktivieren_biegt_zuhause_und_einstellungen_um(self, demo_zuhause: Path) -> None:
        from chatterdome.kern import absturz, einstellungen

        assert Path.home() == demo_zuhause
        assert demo_zuhause / ".chatterdome" / "settings.json" == einstellungen.DATEI
        assert absturz.PROTOKOLL.is_relative_to(demo_zuhause)
        # Nicht die Vorgabe-Wurzel: dorthin schrieb die Pool-Kopie am 29.09.2026
        # auch dann, wenn die Demo woanders lief.
        assert umgebung.demo_pool_datei().is_relative_to(demo_zuhause)
        assert Path(tempfile.gettempdir()).parent == demo_zuhause.parent


class TestDemoQuelle:
    def test_erfuellt_das_protokoll(self) -> None:
        quelle: Quelle = DemoQuelle("de")
        assert len(quelle.bestand(mesh=True).agenten) == len(AGENTEN)
        assert {a.rechner for a in quelle.bestand().agenten} == {"WORKSTATION"}

    def test_senden_landet_im_verlauf(self) -> None:
        quelle = DemoQuelle("de")
        assert quelle.senden("Vega", "Bitte die Tests laufen lassen") == ""
        assert any(a.text == "Bitte die Tests laufen lassen" for a in quelle.verlauf("Vega"))

    def test_stoppen_nimmt_den_agenten_heraus(self) -> None:
        quelle = DemoQuelle("de")
        assert quelle.stoppen("Vega") == ""
        assert "Vega" not in {a.name for a in quelle.bestand(mesh=True).agenten}
        assert "Vega" in quelle.namen().frei

    def test_bildschirmfoto_und_update_gibt_es_nicht(self) -> None:
        quelle = DemoQuelle("de")
        assert quelle.bildschirmfoto()[0] == ""
        assert quelle.aktualisiere_claude()[1]


def _schnell(**kwargs: Any) -> Any:
    return functools.partial(demo_ablauf.ausfuehren, antwortzeit=0.01, recherchezeit=0.01,
                             takt=0.01, **kwargs)


class TestSimulierteDiskussion:
    def test_spielt_die_diskussion_mit_der_echten_moderation_ab(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(demo_ablauf, "ablage", lambda: tmp_path)
        quelle = DemoQuelle("de")
        diskussion = Diskussion("Tabs oder Leerzeichen?", [Teilnehmer("Sirius", seite=PRO)],
                                runden=2, schlussworte=True)

        ergebnis = _schnell()(diskussion, [Teilnehmer("", seite=CONTRA)], quelle=quelle,
                              archiv=Diskussionsarchiv(tmp_path / "archiv.db"))

        assert ergebnis.fehler == ""
        neu = diskussion.teilnehmer[1].name
        assert neu in {a.name for a in AGENTEN} | {"Mira", "Mizar"} and neu != "Sirius"
        arten = [(b.name, b.art) for b in diskussion.beitraege]
        assert arten.count(("Sirius", "beitrag")) == 2
        assert arten.count((neu, "schlusswort")) == 1
        assert diskussion.zusammenfassung == SKRIPT["de"].zusammenfassung
        assert ergebnis.protokoll is not None and ergebnis.protokoll.is_file()
        # Der frische Teilnehmer verschwindet danach wieder aus dem Bestand.
        assert neu not in {a.name for a in quelle.bestand(mesh=True).agenten}

    async def test_die_app_nimmt_im_demo_modus_nie_den_echten_ablauf(
        self, demo_zuhause: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def echter_ablauf(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("Im Demo-Modus darf keine echte Sitzung starten")

        monkeypatch.setattr(debatte_ablauf, "ausfuehren", echter_ablauf)
        monkeypatch.setattr(demo_ablauf, "ausfuehren", _schnell())
        erzeugen(demo_zuhause, "de")
        app = ChatterdomeApp(quelle=DemoQuelle("de"))
        async with app.run_test(size=(180, 50)) as pilot:
            await _warten(pilot, 10)
            panel = app.query_one("#diskussion", DiskussionsPanel)
            assert "Tabs" in panel.query_one("#disk-thema").text
            diskussion = Diskussion("Tabs oder Leerzeichen?",
                                    [Teilnehmer("Sirius", seite=PRO),
                                     Teilnehmer("Vega", seite=CONTRA)], runden=1)
            app._diskussion_starten(DiskussionsAuftrag(diskussion))
            for _ in range(200):
                await pilot.pause(0.05)
                if app._diskussion_stopp is None:
                    break

        assert app._diskussion_stopp is None
        assert [b.name for b in diskussion.beitraege if b.art == "beitrag"] == ["Sirius", "Vega"]
