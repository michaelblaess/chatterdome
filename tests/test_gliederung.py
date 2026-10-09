"""Die Gliederung langer Antworten im Auftragsverlauf."""

from __future__ import annotations

from chatterdome.kern.gliederung import ETIKETT, gliedern

BERICHT = (
    "Tagesbericht 03.05. (Fenster 02.05. 08:00 bis 03.05. 08:00). Logs: ALARM ist ein "
    "abgeschlossener Vorfall vom Vorabend - je 4x rot, 21:10-21:14 Timeout, 21:15-21:19 "
    "HTTP 503, seitdem nichts; /health 0x 503, 12 sonstige 5xx bei 0,48 Mio Requests. "
    "Server: eine Instanz, kein Neustart, 1,2 GB belegt, 6,8 GB frei. Login-Versuche "
    "+120%: Scanner mit wechselnden Kennungen, alles 404, Fund 0. suchfeld 41 = Norden "
    "42: eine Bot-Sitzung. Abgleich 17 Probleme, bekannter Bestand, kein 403. "
    "Firewall-Teil NICHT geprüft: Protokolle ohne Zugriff, Rolle fehlt. Tickets: 9 offen, "
    "0 Rückläufer, 2 verwaist (T-101, 102, 103, 104), In Abnahme 3, 0 blockiert."
)
"""Erfunden, aber im Aufbau die Antwort, an der die Gliederung am 08.10.2026 fehlte."""


class TestGliedern:
    def test_teilt_vor_jedem_etikett(self) -> None:
        absaetze = gliedern(BERICHT)
        assert [a.split(":")[0] for a in absaetze[1:]] == [
            "Logs", "Server", "Login-Versuche +120%", "Firewall-Teil NICHT geprüft", "Tickets"]
        assert absaetze[0] == "Tagesbericht 03.05. (Fenster 02.05. 08:00 bis 03.05. 08:00)."

    def test_es_geht_kein_wort_verloren(self) -> None:
        assert " ".join(gliedern(BERICHT)).split() == BERICHT.split()

    def test_uhrzeiten_und_zahlen_sind_keine_etiketten(self) -> None:
        # "21:10-21:14" und "42: eine" stehen mitten im Satz und teilen nicht.
        logs = next(a for a in gliedern(BERICHT) if a.startswith("Logs"))
        assert "21:10-21:14 Timeout" in logs
        suche = next(a for a in gliedern(BERICHT) if a.startswith("Login"))
        assert "42: eine Bot-Sitzung" in suche

    def test_kurzer_text_bleibt_ein_absatz(self) -> None:
        text = "Erledigt. Hinweis: der Build lief durch."
        assert gliedern(text) == [text]

    def test_eigene_umbrueche_bleiben_unveraendert(self) -> None:
        text = "Erstens: " + "wort " * 30 + "\nZweitens: " + "wort " * 30
        assert gliedern(text) == [text.strip()]

    def test_ohne_etiketten_teilt_die_mitte(self) -> None:
        text = ("Das ist ein langer Satz ohne jedes Etikett und mit vielen Wörtern darin. "
                * 6).strip()
        absaetze = gliedern(text)
        assert len(absaetze) == 2
        assert " ".join(absaetze) == text

    def test_etikett_trifft_nur_den_zeilenanfang(self) -> None:
        treffer = [m.group() for m in ETIKETT.finditer("\n\n".join(gliedern(BERICHT)))]
        assert treffer == ["Logs:", "Server:", "Login-Versuche +120%:",
                           "Firewall-Teil NICHT geprüft:", "Tickets:"]
