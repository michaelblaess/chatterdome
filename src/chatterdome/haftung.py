"""Der Haftungshinweis fuer TUI und Diskussions-Kurzbefehl.

Beide lesen dieselbe Zustimmung (``einstellungen.ZUSTIMMUNG``). Den festen
Teil (Gewaehrleistung, Haftung) liefert ``textual_widgets``, hier stehen nur
die programmeigenen Absaetze.
"""

from __future__ import annotations

from textual_widgets import DISCLAIMER_VERSION, DisclaimerStore
from textual_widgets.disclaimer_screen import disclaimer_text

from chatterdome import __author__
from chatterdome.i18n import current_language, t
from chatterdome.kern import einstellungen

VERSION = f"{DISCLAIMER_VERSION}+chatterdome-2026-09-29"
"""Fassung des Hinweises, der zugestimmt wird.

Eigene Version statt der von textual-widgets: am 29.09.2026 kam die
Zusicherung zu den Kosten dazu (Michael: "das Teil verballert Tokens, das
muss schon jeder abnicken"). Mit der alten Version galt eine Zustimmung
von vorher einfach weiter. Aendert sich der Wortlaut, steigt diese Version.
"""


def titel() -> str:
    return t("disclaimer.title")


def einleitung() -> str:
    return t("disclaimer.intro")


def zusicherungen() -> tuple[str, ...]:
    return (
        t("disclaimer.duty_authorisation"),
        t("disclaimer.duty_actions"),
        t("disclaimer.duty_data"),
        t("disclaimer.duty_costs"),
    )


def absaetze() -> list[list[str]]:
    """Der ganze Hinweis als Absaetze aus Zeilen, fuer die Weboberflaeche."""
    text = disclaimer_text(lang=current_language(), author=__author__, title=titel(),
                           intro=einleitung(), duties=zusicherungen())
    return [absatz.split("\n") for absatz in text.split("\n\n")]


def zustimmung() -> DisclaimerStore:
    """Die Ablage der Zustimmung. Zur Laufzeit gelesen, damit Tests sie verlegen koennen."""
    return DisclaimerStore(einstellungen.ZUSTIMMUNG)


def zugestimmt() -> bool:
    """Wahr, wenn der aktuellen Fassung des Hinweises zugestimmt wurde."""
    return bool(zustimmung().accepted_version == VERSION)


def festhalten() -> None:
    """Haelt die Zustimmung zur aktuellen Fassung fest."""
    zustimmung().record(VERSION)


def text() -> str:
    """Der ganze Hinweis als Fliesstext, fuer die Kommandozeile."""
    return "\n\n".join("\n".join(zeilen) for zeilen in absaetze())
