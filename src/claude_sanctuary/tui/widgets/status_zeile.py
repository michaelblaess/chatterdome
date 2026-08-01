"""Einzeilige Zusammenfassung unter den Panels."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.modelle import Bestand


def _tokens(wert: int) -> str:
    if wert <= 0:
        return "0"
    return str(wert) if wert < 10_000 else f"{round(wert / 1000)}k"


class StatusZeile(Static):
    """Eine Zeile, ein Inhalt - deshalb height 1 und kein auto."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)

    def uebernehmen(self, bestand: Bestand) -> None:
        self.update(
            t(
                "status.summary",
                agenten=len(bestand.agenten),
                beschaeftigt=bestand.beschaeftigt,
                offen=bestand.offene_auftraege,
                tokens=_tokens(bestand.tokens),
            )
        )
