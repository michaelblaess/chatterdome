"""Einstellungen - Sprache liefert die Basisklasse, der Rest steht hier."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TabPane, TextArea
from textual_widgets import BaseSettingsScreen
from textual_widgets.keymap import KeymapStyle

from chatterdome.i18n import t
from chatterdome.kern.absturz import PROTOKOLL
from chatterdome.kern.einstellungen import DATEI, ZUSTIMMUNG
from chatterdome.kern.terminals import AUTOMATISCH, auswahl

VERFAHREN = ("claude", "npm", "winget", "choco", "brew")
"""Aktualisierungsverfahren, gleiche Reihenfolge wie in update.mjs.

Bewusst hier gespiegelt und nicht aus Node gelesen: es sind fuenf feste
Woerter, und ein Unterprozess nur zum Fuellen einer Auswahlliste waere
Verschwendung. Aendert sich die Liste drueben, faellt es beim Speichern auf -
update.mjs lehnt einen unbekannten Schluessel ausdruecklich ab.
"""


def _namenspool_datei() -> Path:
    """Der Namenspool gehoert dem Operator-Skill."""
    return Path(__file__).resolve().parents[4] / "skills" / "operator" / "namenspool.json"


def _namenspool_lokal() -> Path:
    """Lokale Ergaenzung zum Namenspool, per .gitignore aus dem Repo gehalten."""
    return _namenspool_datei().with_name("namenspool.local.json")


def _lies_json(datei: Path) -> dict[str, Any] | None:
    try:
        roh = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return roh if isinstance(roh, dict) else None


def _schreibe_json(datei: Path, roh: dict[str, Any]) -> None:
    with contextlib.suppress(OSError):
        # newline="\n": ohne das macht Windows CRLF daraus, und die
        # versionierte Datei taucht nach jedem Speichern als geaendert auf.
        datei.write_text(
            json.dumps(roh, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _bus_datei() -> Path:
    import platform

    return Path.home() / ".claude" / "bus" / (platform.node().upper() or "?") / "bus.db"


class EinstellungenScreen(BaseSettingsScreen):  # type: ignore[misc]
    """Mesh, Netzwerk, Namenspool und Datenbank."""

    DEFAULT_CSS = """
    EinstellungenScreen .pool-block {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        border: solid $surface-lighten-1;
    }
    EinstellungenScreen .pool-block Label {
        width: 12;
        padding: 1 1;
    }
    EinstellungenScreen .pool-block Input {
        width: 1fr;
    }
    EinstellungenScreen .feldname {
        margin-top: 1;
        text-style: bold;
    }
    EinstellungenScreen #set-terminal-vorbereitung {
        height: 8;
        border: round $surface-lighten-2;
    }
    EinstellungenScreen #set-terminal-suchen {
        margin-left: 1;
        min-width: 12;
    }
    """

    def __init__(self, werte: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(werte, **kwargs)
        self._pools: dict[str, list[str]] = {}
        self._aktiv = ""
        self._pool_laden()

    # -- Namenspool -----------------------------------------------------

    def _pool_laden(self) -> None:
        """Liest mitgelieferte und lokale Datei, wie ``pool.mjs`` es tut.

        Lokale Motive ergaenzen die mitgelieferten und ersetzen
        gleichnamige, das lokale ``aktiv`` gewinnt.
        """
        for datei in (_namenspool_datei(), _namenspool_lokal()):
            roh = _lies_json(datei)
            if roh is None:
                continue
            pools = roh.get("pools", {})
            if isinstance(pools, dict):
                for schluessel, eintrag in pools.items():
                    namen = eintrag.get("namen") if isinstance(eintrag, dict) else eintrag
                    if isinstance(namen, list):
                        self._pools[str(schluessel)] = [str(n) for n in namen]
            if roh.get("aktiv"):
                self._aktiv = str(roh["aktiv"])

    def _pool_speichern(self) -> None:
        """Schreibt die Namenslisten zurueck, jede in die Datei, aus der sie kam.

        Anders als der Bus ist das kein Mehrschreiber-Fall - Node fasst die
        Dateien nur beim Motivwechsel an. Trotzdem wird der vorhandene Inhalt
        gelesen und nur der Zweig ``pools`` ersetzt, damit nichts verloren
        geht, was diese Fassung noch nicht kennt. Das aktive Motiv landet
        immer in der lokalen Datei: sonst waere die mitgelieferte nach jedem
        Umschalten geaendert, und ein lokales Motiv stuende als aktiv im Repo.
        """
        lokal_datei = _namenspool_lokal()
        for datei in (_namenspool_datei(), lokal_datei):
            roh = _lies_json(datei)
            if roh is None:
                continue
            pools = roh.get("pools", {})
            if not isinstance(pools, dict):
                continue
            for schluessel, namen in self._pools.items():
                if schluessel in pools and isinstance(pools[schluessel], dict):
                    pools[schluessel]["namen"] = namen
            roh["pools"] = pools
            if datei == lokal_datei and self._aktiv:
                roh["aktiv"] = self._aktiv
            _schreibe_json(datei, roh)
        if self._aktiv and _lies_json(lokal_datei) is None:
            _schreibe_json(lokal_datei, {"aktiv": self._aktiv})

    # -- Werte fuer die Auswahlfelder -----------------------------------

    def _terminal_wert(self) -> str:
        """Gespeichertes Terminal, sofern es hier ueberhaupt existiert.

        Ein Wert, den die Liste nicht enthaelt, wird von Select abgelehnt -
        und gespeichert sein kann leicht etwas, das nur auf einem anderen
        Rechner installiert ist. Die Einstellungen wandern ja mit.
        """
        gespeichert = str(self._settings.get("terminal", AUTOMATISCH))
        vorhanden = {schluessel for _, schluessel in auswahl()}
        return gespeichert if gespeichert in vorhanden else AUTOMATISCH

    def _keymap_stil_wert(self) -> str:
        """Gespeicherter Stil, sofern die Auswahl ihn kennt - sonst nach Betriebssystem."""
        gespeichert = str(self._settings.get("keymap_style", "") or "")
        erlaubt = {"", *(stil.value for stil in KeymapStyle)}
        return gespeichert if gespeichert in erlaubt else ""

    def _update_wert(self) -> str:
        gespeichert = str(self._settings.get("update_verfahren", "claude"))
        return gespeichert if gespeichert in VERFAHREN else "claude"

    @on(Button.Pressed, "#set-terminal-suchen")
    def _skript_suchen(self) -> None:
        from chatterdome.tui.screens.dateiwahl_screen import DateiwahlScreen

        feld = self.query_one("#set-terminal-skript", Input)
        self.app.push_screen(DateiwahlScreen(feld.value), callback=self._skript_gewaehlt)

    def _skript_gewaehlt(self, pfad: str | None) -> None:
        if pfad:
            self.query_one("#set-terminal-skript", Input).value = pfad

    # -- Hooks der Basisklasse ------------------------------------------

    def app_tabs(self) -> ComposeResult:
        with TabPane(t("settings.tab_mesh"), id="tab-mesh"), VerticalScroll():
            yield Checkbox(
                t("settings.local_only"),
                value=bool(self._settings.get("nur_lokal", True)),
                id="set-nur-lokal",
            )
            with Horizontal(classes="settings-row"):
                yield Label(t("settings.interval"))
                yield Input(
                    value=str(self._settings.get("aktualisierung_sekunden", 5)),
                    id="set-takt",
                    type="integer",
                )

        with TabPane(t("settings.tab_network"), id="tab-netzwerk"), VerticalScroll():
            with Horizontal(classes="settings-row"):
                yield Label(t("settings.proxy"))
                yield Input(
                    value=str(self._settings.get("proxy_url", "")),
                    placeholder="http://proxy.example.com:8080",
                    id="set-proxy",
                )
            yield Static(t("settings.proxy_hint"), classes="hint")

        with TabPane(t("settings.tab_pool"), id="tab-pool"), VerticalScroll():
            yield Static(t("settings.pool_hint"), classes="hint")
            if self._pools:
                with Horizontal(classes="settings-row"):
                    yield Label(t("settings.pool_active"))
                    yield Select(
                        [(s, s) for s in sorted(self._pools)],
                        # Select.NULL, nicht Select.BLANK - letzteres loest zu
                        # False auf und wird als Wert abgelehnt.
                        value=self._aktiv if self._aktiv in self._pools else Select.NULL,
                        id="set-pool-aktiv",
                    )
            for i, schluessel in enumerate(sorted(self._pools)):
                # Der Rahmen umschliesst die Gruppe, nicht die einzelne Zeile -
                # sonst steht jedes Feld fuer sich und die Zusammengehoerigkeit
                # ist nicht erkennbar (wie in death-proof).
                with Vertical(classes="pool-block"):
                    with Horizontal(classes="settings-row"):
                        yield Label(t("settings.pool_name"))
                        yield Input(value=schluessel, id=f"pool-name-{i}", disabled=True)
                    with Horizontal(classes="settings-row"):
                        yield Label(t("settings.pool_names"))
                        yield Input(
                            value=", ".join(self._pools[schluessel]), id=f"pool-liste-{i}"
                        )

        with TabPane(t("settings.tab_terminal"), id="tab-terminal"), VerticalScroll():
            with Horizontal(classes="settings-row"):
                yield Label(t("settings.terminal_program"))
                # Nur was hier wirklich installiert ist - eine Auswahl, die
                # nicht vorhandene Programme anbietet, erzeugt nur Fehlschlaege.
                yield Select(
                    [(t("settings.terminal_auto"), AUTOMATISCH), *auswahl()],
                    value=self._terminal_wert(),
                    id="set-terminal",
                )
            yield Static(t("settings.terminal_hint"), classes="hint")

            yield Static(t("settings.terminal_script"), classes="feldname")
            with Horizontal(classes="settings-row"):
                yield Input(
                    value=str(self._settings.get("terminal_skript", "")),
                    placeholder=t("settings.terminal_script_ph"),
                    id="set-terminal-skript",
                )
                yield Button(t("settings.browse"), id="set-terminal-suchen")

            yield Static(t("settings.terminal_prepare"), classes="feldname")
            yield TextArea(
                str(self._settings.get("terminal_vorbereitung", "")),
                id="set-terminal-vorbereitung",
            )
            yield Static(t("settings.terminal_prepare_hint"), classes="hint")

        with TabPane(t("settings.tab_update"), id="tab-update"), VerticalScroll():
            with Horizontal(classes="settings-row"):
                yield Label(t("settings.update_method"))
                yield Select(
                    [(t(f"settings.update_{s}"), s) for s in VERFAHREN],
                    value=self._update_wert(),
                    id="set-update",
                )
            yield Static(t("settings.update_hint"), classes="hint")

        with TabPane(t("settings.tab_keyboard"), id="tab-tastatur"), VerticalScroll():
            yield Static(t("settings.keymap_intro"), classes="hint")
            with Horizontal(classes="settings-row"):
                yield Label(t("settings.keymap_style"))
                yield Select(
                    [
                        (t("settings.keymap_style_auto"), ""),
                        (t("settings.keymap_style_classic"), KeymapStyle.CLASSIC.value),
                        (
                            t("settings.keymap_style_function_keys"),
                            KeymapStyle.FUNCTION_KEYS.value,
                        ),
                    ],
                    value=self._keymap_stil_wert(),
                    id="set-keymap-style",
                )
            vim = Checkbox(
                t("settings.keymap_vim"),
                value=bool(self._settings.get("keymap_vim", False)),
                id="set-keymap-vim",
            )
            vim.tooltip = t("settings.keymap_vim_tip")
            yield vim
            yield Static(t("settings.keymap_custom_hint"), classes="hint")

        with TabPane(t("settings.tab_database"), id="tab-datenbank"), VerticalScroll():
            yield Checkbox(
                t("settings.show_ids"),
                value=bool(self._settings.get("id_spalte", False)),
                id="set-ids",
            )
            yield Static(t("settings.db_hint"), classes="hint")

    def collect_app_settings(self, settings: dict[str, Any]) -> None:
        settings["nur_lokal"] = self.query_one("#set-nur-lokal", Checkbox).value
        settings["id_spalte"] = self.query_one("#set-ids", Checkbox).value
        stil = self.query_one("#set-keymap-style", Select).value
        settings["keymap_style"] = stil if isinstance(stil, str) else ""
        settings["keymap_vim"] = self.query_one("#set-keymap-vim", Checkbox).value
        settings["proxy_url"] = self.query_one("#set-proxy", Input).value.strip()
        settings["terminal_skript"] = self.query_one("#set-terminal-skript", Input).value.strip()
        settings["terminal_vorbereitung"] = self.query_one(
            "#set-terminal-vorbereitung", TextArea
        ).text
        for feld, schluessel, vorgabe in (
            ("#set-terminal", "terminal", AUTOMATISCH),
            ("#set-update", "update_verfahren", "claude"),
        ):
            wert = self.query_one(feld, Select).value
            # Select.NULL ist kein Text - dann bleibt es bei der Vorgabe.
            settings[schluessel] = wert if isinstance(wert, str) else vorgabe
        try:
            settings["aktualisierung_sekunden"] = max(
                2, int(self.query_one("#set-takt", Input).value or 5)
            )
        except ValueError:
            settings["aktualisierung_sekunden"] = 5

        for i, schluessel in enumerate(sorted(self._pools)):
            feld = self.query(f"#pool-liste-{i}")
            if not feld:
                continue
            roh = str(feld.first(Input).value)
            self._pools[schluessel] = [n.strip() for n in roh.split(",") if n.strip()]
        auswahl = self.query("#set-pool-aktiv")
        if auswahl:
            wert = auswahl.first(Select).value
            if isinstance(wert, str):
                self._aktiv = wert
        self._pool_speichern()

    def storage_paths(self) -> list[tuple[str, Path]]:
        return [
            (t("settings.storage.config"), DATEI),
            (t("settings.storage.bus"), _bus_datei()),
            (t("settings.storage.disclaimer"), ZUSTIMMUNG),
            (t("settings.storage.fault"), PROTOKOLL),
        ]
