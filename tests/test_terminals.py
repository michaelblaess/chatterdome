"""Terminalwahl und die erzeugte Startdatei.

Der Kern der Sache ist die Datei: die Vorbereitungsbefehle duerfen NICHT
durch eine Befehlszeile wandern. Michaels Proxy-Einrichtung enthaelt
Anfuehrungszeichen und Gleichheitszeichen, und die muessten sonst zwei Shells
heil ueberstehen.
"""

from __future__ import annotations

import sys

from claude_sanctuary.kern.terminals import (
    AUTOMATISCH,
    TERMINALS,
    finde,
    startdatei,
    verfuegbare,
    vorbereitung,
)


class TestAuswahl:
    def test_automatisch_nimmt_das_erste_vorhandene(self) -> None:
        erwartet = verfuegbare()[0] if verfuegbare() else None
        assert finde(AUTOMATISCH) is erwartet

    def test_unbekannter_schluessel_ergibt_nichts(self) -> None:
        assert finde("emacs-shell") is None

    def test_nur_terminals_dieses_systems(self) -> None:
        """Ein Terminal eines fremden Systems darf nie als vorhanden gelten.

        Die Einstellungen wandern ueber claude-config auf alle Rechner - ohne
        die Pruefung stuende auf senza "Windows Terminal" zur Wahl.
        """
        assert all(t.system == sys.platform for t in verfuegbare())

    def test_jeder_schluessel_kommt_nur_einmal_vor(self) -> None:
        schluessel = [t.schluessel for t in TERMINALS]
        assert len(schluessel) == len(set(schluessel))


class TestVorbereitung:
    def test_leere_zeilen_fallen_weg(self) -> None:
        werte = {"terminal_vorbereitung": "set A=1\n\n   \nset B=2"}
        assert vorbereitung(werte) == ["set A=1", "set B=2"]

    def test_skript_laeuft_vor_den_zeilen(self) -> None:
        werte = {"terminal_skript": "/pfad/proxy.sh", "terminal_vorbereitung": "echo da"}
        schritte = vorbereitung(werte)
        assert len(schritte) == 2
        assert "proxy.sh" in schritte[0]
        assert schritte[1] == "echo da"

    def test_ohne_angaben_nichts(self) -> None:
        assert vorbereitung({}) == []


class TestStartdatei:
    def test_befehle_stehen_vor_dem_start(self, tmp_path: object) -> None:
        pfad = startdatei(["set HTTPS_PROXY=http://p:8080"], str(tmp_path), ["sanctuary", "start"])
        inhalt = pfad.read_text(encoding="utf-8")
        assert inhalt.index("HTTPS_PROXY") < inhalt.index("sanctuary")

    def test_sonderzeichen_bleiben_unangetastet(self, tmp_path: object) -> None:
        """Genau dafuer gibt es die Datei.

        Eine Zeile mit Anfuehrungszeichen und Klammern waere in einer
        Befehlszeile durch zwei Shells gegangen und dabei zerlegt worden.
        """
        zeile = 'set NO_PROXY="localhost,127.0.0.1" & echo (fertig)'
        pfad = startdatei([zeile], str(tmp_path), ["sanctuary", "start"])
        assert zeile in pfad.read_text(encoding="utf-8")

    def test_wechselt_zuerst_ins_verzeichnis(self, tmp_path: object) -> None:
        pfad = startdatei([], str(tmp_path), ["sanctuary", "start"])
        zeilen = [z for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]
        # Zeile 0 ist die Kopfzeile (@echo off bzw. die Shebang-Zeile).
        assert str(tmp_path) in zeilen[1]

    def test_argument_mit_leerzeichen_wird_gequotet(self, tmp_path: object) -> None:
        pfad = startdatei([], str(tmp_path), ["C:/Program Files/claude.exe", "--resume", "id-1"])
        inhalt = pfad.read_text(encoding="utf-8")
        assert '"C:/Program Files/claude.exe"' in inhalt or \
               "'C:/Program Files/claude.exe'" in inhalt
