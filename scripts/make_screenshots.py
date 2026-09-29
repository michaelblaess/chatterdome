"""README-Screenshots im Demo-Modus erzeugen.

Startet die Oberflaeche headless mit erfundenen Daten (siehe kern/umgebung.py),
oeffnet jede Ansicht und speichert sie als SVG. Ein installiertes Chrome oder
Edge rendert daraus PNG-Dateien nach docs/screenshots/.

    uv run python scripts/make_screenshots.py [--lang en] [--browser <pfad>]

Nichts davon liest echte Daten: das Demo-Zuhause entsteht bei jedem Lauf neu.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ZIEL = REPO / "docs" / "screenshots"
GROESSE = (180, 50)

BROWSER = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def _browser(eigen: str) -> str:
    for kandidat in (eigen, *BROWSER):
        if kandidat and (Path(kandidat).is_file() or shutil.which(kandidat)):
            return kandidat
    raise SystemExit("Kein Chrome/Edge gefunden - Pfad mit --browser angeben.")


def _png(browser: str, svg: Path) -> Path:
    """Rendert ein SVG in ein PNG derselben Groesse (steht im viewBox)."""
    kopf = svg.read_text(encoding="utf-8")[:2000]
    treffer = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', kopf)
    breite, hoehe = (int(float(w)) for w in treffer.groups()) if treffer else (2214, 1270)
    png = svg.with_suffix(".png")
    # Schraegstriche: mit Backslashes meldete Chrome "written", die Datei fehlte.
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={png.as_posix()}", f"--window-size={breite},{hoehe}",
         svg.resolve().as_uri()],
        check=True, capture_output=True,
    )
    if not png.is_file():
        raise SystemExit(f"{png} wurde nicht geschrieben.")
    return png


async def _warten(pilot: Any, sekunden: float) -> None:
    for _ in range(int(sekunden / 0.05)):
        await pilot.pause(0.05)


async def _aufnehmen(sprache: str, ordner: Path) -> list[Path]:
    from textual.widgets import Input, TabbedContent

    from chatterdome.kern.debatte import CONTRA, PRO, Diskussion, Teilnehmer
    from chatterdome.kern.demo_quelle import DemoQuelle
    from chatterdome.kern.demo_texte import SKRIPT
    from chatterdome.kern.demo_texte import sprache as demo_sprache
    from chatterdome.tui.app import ChatterdomeApp
    from chatterdome.tui.widgets.diskussion_panel import DiskussionsAuftrag

    bilder: list[Path] = []
    app = ChatterdomeApp(quelle=DemoQuelle(sprache))

    def sichern(name: str) -> None:
        datei = ordner / f"{name}.svg"
        datei.write_text(app.export_screenshot(), encoding="utf-8")
        bilder.append(datei)
        print(f"  {name}")

    async with app.run_test(size=GROESSE) as pilot:
        await _warten(pilot, 2)
        reiter = app.query_one("#bereiche", TabbedContent)

        for name, tab in (("agents", "agenten"), ("bus", "bus"), ("statistics", "statistik"),
                          ("memory", "gedaechtnis")):
            reiter.active = f"tab-{tab}"
            await _warten(pilot, 3)
            sichern(name)

        reiter.active = "tab-suche"
        await _warten(pilot, 2)
        app.query_one("#such-eingabe", Input).value = "backup"
        await _warten(pilot, 2)
        sichern("search")

        # Eine laufende Diskussion: mitten im Ablauf, mit Animation beim naechsten Redner.
        reiter.active = "tab-diskussion"
        await _warten(pilot, 1)
        diskussion = Diskussion(SKRIPT[demo_sprache(sprache)].thema,
                                [Teilnehmer("Sirius", seite=PRO), Teilnehmer("Vega", seite=CONTRA)],
                                runden=3, modell="sonnet")
        app._diskussion_starten(DiskussionsAuftrag(diskussion))
        for _ in range(900):
            await pilot.pause(0.05)
            if len([b for b in diskussion.beitraege if b.art == "beitrag"]) >= 3:
                break
        await _warten(pilot, 1.5)
        sichern("discussion")
        if app._diskussion_stopp is not None:
            app._diskussion_stopp.set()
        await _warten(pilot, 1)

        reiter.active = "tab-agenten"
        app.theme = "catppuccin-mocha"
        await _warten(pilot, 2)
        sichern("theme")
    return bilder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", default="en", choices=("de", "en"))
    parser.add_argument("--browser", default=os.environ.get("CHATTERDOME_BROWSER", ""))
    args = parser.parse_args()

    from chatterdome.i18n import load_locale
    from chatterdome.kern import umgebung

    zuhause = umgebung.demo_aktivieren()
    load_locale(args.lang)
    from chatterdome.kern.demo_daten import erzeugen

    erzeugen(zuhause, args.lang)
    browser = _browser(args.browser)
    ZIEL.mkdir(parents=True, exist_ok=True)
    roh = zuhause.parent / "screenshots"
    roh.mkdir()
    print(f"Aufnahme ({args.lang}):")
    for svg in asyncio.run(_aufnehmen(args.lang, roh)):
        png = _png(browser, svg)
        shutil.copyfile(png, ZIEL / png.name)
    print(f"Fertig: {ZIEL}")


if __name__ == "__main__":
    sys.exit(main())
