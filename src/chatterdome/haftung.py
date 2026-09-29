"""Der Haftungshinweis, gemeinsam fuer Terminal- und Weboberflaeche.

Beide zeigen denselben Wortlaut und lesen dieselbe Zustimmung
(``einstellungen.ZUSTIMMUNG``): wer in der TUI zugestimmt hat, muss es im
Browser nicht noch einmal tun. Den festen Teil (Gewaehrleistung, Haftung)
liefert ``textual_widgets``, hier stehen nur die programmeigenen Absaetze.
"""

from __future__ import annotations

from textual_widgets import DISCLAIMER_VERSION, DisclaimerStore
from textual_widgets.disclaimer_screen import disclaimer_text

from chatterdome import __author__
from chatterdome.i18n import current_language, t
from chatterdome.kern import einstellungen


def titel() -> str:
    return t("disclaimer.title")


def einleitung() -> str:
    return t("disclaimer.intro")


def zusicherungen() -> tuple[str, ...]:
    return (
        t("disclaimer.duty_authorisation"),
        t("disclaimer.duty_actions"),
        t("disclaimer.duty_data"),
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
    return bool(zustimmung().accepted_version == DISCLAIMER_VERSION)
