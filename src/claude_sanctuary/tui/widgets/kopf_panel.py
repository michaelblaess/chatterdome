"""Kopf-Panel mit den Eckdaten, vier thematische Spalten zu je vier Zeilen."""

from __future__ import annotations

import platform
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from textual_widgets import InfoHeader, InfoItem

from claude_sanctuary.i18n import format_datetime, t
from claude_sanctuary.kern.modelle import Bestand


def _tokens(wert: int) -> str:
    """Grosse Zahlen kurz: 412417 wird zu 412k."""
    if wert <= 0:
        return "-"
    if wert < 10_000:
        return str(wert)
    return f"{round(wert / 1000)}k"


def _dauer(ms: int) -> str:
    """Millisekunden als Stunden und Minuten."""
    minuten = ms // 60_000
    if minuten < 60:
        return f"{minuten}m"
    return f"{minuten // 60}h {minuten % 60:02d}m"


def _groesse(pfad: Path) -> str:
    try:
        bytes_ = pfad.stat().st_size
    except OSError:
        return "-"
    if bytes_ < 1024 * 1024:
        return f"{round(bytes_ / 1024)} KB"
    return f"{bytes_ / 1024 / 1024:.1f} MB"


class KopfPanel(InfoHeader):  # type: ignore[misc]
    """Vier Spalten: Betrieb, Technik, Netz, Namen."""

    def __init__(self, bus_datei: Path, **kwargs: Any) -> None:
        self._bus_datei = bus_datei
        items = [
            # Spalte 1 - Betrieb
            InfoItem("uptime", t("head.uptime"), "-"),
            InfoItem("agents", t("head.agents"), "-"),
            InfoItem("busy", t("head.busy"), "-"),
            InfoItem("open", t("head.open"), "-"),
            # Spalte 2 - Technik
            InfoItem("claude", t("head.claude"), "-"),
            InfoItem("system", t("head.system"), "-"),
            InfoItem("node", t("head.node"), "-"),
            InfoItem("sqlite", t("head.sqlite"), sqlite3.sqlite_version),
            # Spalte 3 - Netz
            InfoItem("host", t("head.host"), platform.node()),
            InfoItem("mesh", t("head.mesh"), "-"),
            InfoItem("reachable", t("head.reachable"), "-"),
            InfoItem("updated", t("head.updated"), "-"),
            # Spalte 4 - Konto und Namen
            InfoItem("login", t("head.login"), "-"),
            InfoItem("pool", t("head.pool"), "-"),
            InfoItem("free", t("head.free"), "-"),
            InfoItem("db", t("head.db"), str(bus_datei)),
        ]
        super().__init__(items, columns=4, fill="column", label_width=16, **kwargs)

    def on_mount(self) -> None:
        self.set_value("node", f"{sys.version_info.major}.{sys.version_info.minor} / node")

    def uebernehmen(self, bestand: Bestand, *, nur_lokal: bool, laufzeit_ms: int) -> None:
        """Traegt die Werte einer Abfrage ein."""
        self.set_value("uptime", _dauer(laufzeit_ms))
        self.set_value("agents", str(len(bestand.agenten)))
        self.set_value(
            "busy",
            str(bestand.beschaeftigt),
            value_style="bold yellow" if bestand.beschaeftigt else "",
        )
        self.set_value(
            "open",
            str(bestand.offene_auftraege),
            value_style="bold" if bestand.offene_auftraege else "",
        )
        self.set_value("mesh", t("mesh.off") if nur_lokal else t("mesh.on"))
        rechner = {a.rechner for a in bestand.agenten}
        fehlend = len(bestand.fehler)
        self.set_value(
            "reachable",
            f"{len(rechner)}" + (f" ({t('head.gone', n=fehlend)})" if fehlend else ""),
            value_style="bold red" if fehlend else "",
        )
        self.set_value("updated", format_datetime(bestand.zeit))
        self.set_value("system", bestand.system or "-")
        self.set_value("claude", _claude_version(bestand))
        self._anmeldung_setzen(bestand.anmeldung)

    def _anmeldung_setzen(self, iso: str) -> None:
        """Traegt ein, wann eine neue Anmeldung faellig wird.

        Gemeint ist der Refresh-Token. Der Zugriffstoken laeuft nach Stunden
        ab und wird still erneuert - ihn anzuzeigen waere ein Fehlalarm.
        """
        if not iso:
            self.set_value("login", "-")
            return
        try:
            frist = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        except (ValueError, TypeError):
            self.set_value("login", "-")
            return
        tage = (frist - datetime.now(frist.tzinfo)).days
        stil = "bold red" if tage <= 2 else ("yellow" if tage <= 7 else "")
        self.set_value(
            "login",
            f"{frist.strftime('%d.%m.%Y')}  ({t('head.login_days', tage=max(tage, 0))})",
            value_style=stil,
        )

    def namen_setzen(self, pool: str, frei: int) -> None:
        """Traegt den Namenspool ein - kommt aus einer eigenen Abfrage."""
        self.set_value("pool", pool or "-")
        self.set_value("free", str(frei))


def _claude_version(bestand: Bestand) -> str:
    """Haeufigste Claude-Version im Bestand, mit Hinweis auf Abweichungen.

    Frisch gestartete Sitzungen haben noch keinen Transkript-Eintrag und
    damit keine Version - die zaehlen hier nicht mit, statt eine Luecke zu
    erfinden.
    """
    versionen = Counter(a.version for a in bestand.agenten if a.version)
    if not versionen:
        # Keine Sitzung hat bisher geantwortet - dann gilt die installierte
        # Fassung des Rechners, die der Operator dafuer nachschlaegt.
        return bestand.claude_version or "-"
    (haeufigste, _), *rest = versionen.most_common()
    return f"{haeufigste} (+{len(rest)})" if rest else str(haeufigste)
