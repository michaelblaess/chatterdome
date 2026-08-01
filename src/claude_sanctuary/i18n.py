"""Internationalisierung ueber JSON-Sprachpakete."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from importlib import resources
from typing import Any

logger = logging.getLogger(__name__)

_strings: dict[str, str] = {}
_current_lang: str = "de"

SUPPORTED_LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"


def load_locale(lang: str) -> None:
    """Laedt eine Sprachdatei."""
    global _strings, _current_lang

    if lang not in SUPPORTED_LANGUAGES:
        logger.warning("Sprache '%s' nicht unterstuetzt, verwende '%s'", lang, DEFAULT_LANGUAGE)
        lang = DEFAULT_LANGUAGE
    try:
        datei = resources.files("claude_sanctuary") / "locale" / f"{lang}.json"
        _strings = json.loads(datei.read_text(encoding="utf-8"))
        _current_lang = lang
    except Exception:
        logger.exception("Fehler beim Laden der Sprachdatei '%s'", lang)
        _strings = {}
        _current_lang = lang


def current_language() -> str:
    """Aktuell geladene Sprache."""
    return _current_lang


def t(key: str, **kwargs: Any) -> str:
    """Uebersetzt einen Schluessel, Platzhalter ueber ``{name}``."""
    vorlage = _strings.get(key, key)
    if kwargs:
        try:
            return vorlage.format(**kwargs)
        except (KeyError, IndexError):
            return vorlage
    return vorlage


def format_datetime(zeitpunkt: str, lang: str | None = None) -> str:
    """Formatiert einen ISO-Zeitstempel kulturabhaengig."""
    if not zeitpunkt:
        return "?"
    if lang is None:
        lang = _current_lang
    try:
        wert = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return zeitpunkt[:16].replace("T", " ")
    return wert.strftime("%d.%m.%Y %H:%M") if lang == "de" else wert.strftime("%Y-%m-%d %H:%M")


def format_time(zeitpunkt: str) -> str:
    """Nur die Uhrzeit, fuer die Verlaufsansicht."""
    if not zeitpunkt:
        return ""
    try:
        wert = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return zeitpunkt[11:16]
    return wert.strftime("%H:%M")
