"""Einstellungen - Sprache liefert die Basisklasse, der Rest steht hier."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Checkbox, Input, Label, Select, Static, TabPane
from textual_widgets import BaseSettingsScreen

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.einstellungen import DATEI, ZUSTIMMUNG


def _namenspool_datei() -> Path:
    """Der Namenspool gehoert dem Operator-Skill."""
    return Path(__file__).resolve().parents[4] / "skills" / "operator" / "namenspool.json"


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
    """

    def __init__(self, werte: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(werte, **kwargs)
        self._pools: dict[str, list[str]] = {}
        self._aktiv = ""
        self._pool_laden()

    # -- Namenspool -----------------------------------------------------

    def _pool_laden(self) -> None:
        try:
            roh = json.loads(_namenspool_datei().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        pools = roh.get("pools", {})
        if isinstance(pools, dict):
            for schluessel, eintrag in pools.items():
                namen = eintrag.get("namen") if isinstance(eintrag, dict) else eintrag
                if isinstance(namen, list):
                    self._pools[str(schluessel)] = [str(n) for n in namen]
        self._aktiv = str(roh.get("aktiv", ""))

    def _pool_speichern(self) -> None:
        """Schreibt die Namenslisten zurueck.

        Anders als der Bus ist diese Datei kein Mehrschreiber-Fall - Node
        fasst sie nur beim Motivwechsel an. Trotzdem wird der vorhandene
        Inhalt gelesen und nur der Zweig ``pools`` ersetzt, damit nichts
        verloren geht, was diese Fassung noch nicht kennt.
        """
        datei = _namenspool_datei()
        try:
            roh = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        pools = roh.get("pools", {})
        if not isinstance(pools, dict):
            return
        for schluessel, namen in self._pools.items():
            if schluessel in pools and isinstance(pools[schluessel], dict):
                pools[schluessel]["namen"] = namen
        roh["pools"] = pools
        if self._aktiv:
            roh["aktiv"] = self._aktiv
        with contextlib.suppress(OSError):
            datei.write_text(
                json.dumps(roh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

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
                with Horizontal(classes="pool-block"):
                    yield Label(t("settings.pool_name"))
                    yield Input(value=schluessel, id=f"pool-name-{i}", disabled=True)
                with Horizontal(classes="pool-block"):
                    yield Label(t("settings.pool_names"))
                    yield Input(value=", ".join(self._pools[schluessel]), id=f"pool-liste-{i}")

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
        settings["proxy_url"] = self.query_one("#set-proxy", Input).value.strip()
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
        ]
