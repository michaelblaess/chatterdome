"""Gliedert eine lange Antwort im Auftragsverlauf fuer die Anzeige.

Eine Quittung kommt als eine einzige Zeile an: mehrzeilige Notizen koennen auf
dem Weg ueber einen .cmd-Wrapper am ersten Umbruch abgeschnitten werden, siehe
``debatte.absaetze``. Ein Morgenbericht mit sechs Themen stand deshalb als ein
Block im Verlauf (Michael, 08.10.2026). Gegliedert wird hier nur die Anzeige,
der gespeicherte Text bleibt, wie er kam.
"""

from __future__ import annotations

import re

from chatterdome.kern.debatte import ABSATZ_AB_WOERTERN, absaetze

_ETIKETT_TEXT = r"[A-ZÄÖÜ][^\s:.!?]*(?:\s[^\s:.!?]+){0,2}:"
"""Ein bis drei Woerter mit Doppelpunkt, etwa "Logs:" oder "Firewall-Teil NICHT geprüft:"."""

_VOR_ETIKETT = re.compile(rf"(?<=[.!?;])\s+(?={_ETIKETT_TEXT}\s)")
"""Die Stelle zwischen einem Satzende und einem Etikett.

Bewusst ohne die Abkuerzungsregeln aus ``debatte._saetze``: nach "kein 403."
haelt die Satzzerlegung die Zahl fuer eine Ordnungszahl und trennt nicht. Das
Etikett dahinter ist das staerkere Zeichen.
"""

ETIKETT = re.compile(rf"^{_ETIKETT_TEXT}(?=\s)", re.MULTILINE)
"""Ein Etikett am Zeilenanfang, fuer die Hervorhebung in der Anzeige."""


def gliedern(text: str) -> list[str]:
    """Teilt eine Antwort in Absaetze.

    Eigene Zeilenumbrueche des Absenders gelten und bleiben unveraendert, ebenso
    kurze Texte. Ein langer Block wird vor jedem Etikett geteilt. Hat er keine
    Etiketten, greift die Teilung in der Mitte aus ``debatte.absaetze``.

    :param text: die Notiz oder der Auftragstext, wie er im Bestand steht.
    :returns: die Absaetze, mindestens einer.
    """
    rein = text.strip()
    if "\n" in rein or len(rein.split()) < ABSATZ_AB_WOERTERN:
        return [rein]
    teile = [teil.strip() for teil in _VOR_ETIKETT.split(rein) if teil.strip()]
    return teile if len(teile) > 1 else absaetze(rein)
