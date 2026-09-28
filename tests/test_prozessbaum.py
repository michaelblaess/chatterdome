"""Der Weg vom Claude-Prozess zur Shell unserer Startdatei."""

from __future__ import annotations

from claude_sanctuary.kern.prozessbaum import Prozess, fensterwurzel

TEMP = r"C:\Users\x\AppData\Local\Temp\claude-sanctuary"


def _kette() -> dict[int, Prozess]:
    # So sah die Kette am 28.09.2026 aus: Terminal, Shell mit Startdatei,
    # cmd fuer sanctuary.CMD, node, claude.
    return {
        10: Prozess(10, 1, "WindowsTerminal.exe", "wt"),
        20: Prozess(20, 10, "powershell.exe",
                    rf'powershell.exe -NoExit -File "{TEMP}\start-ab12cd.ps1"'),
        30: Prozess(30, 20, "cmd.exe", 'cmd.exe /c "sanctuary.CMD" start'),
        40: Prozess(40, 30, "node.exe", "node sanctuary.mjs start"),
        50: Prozess(50, 40, "claude.exe", "claude.exe -n Lourdes"),
    }


def test_findet_die_shell_mit_der_startdatei() -> None:
    assert fensterwurzel(50, _kette()) == 20


def test_fremdes_fenster_ohne_startdatei_wird_nicht_angefasst() -> None:
    kette = _kette()
    kette[20] = Prozess(20, 10, "powershell.exe", "powershell.exe -NoExit")
    assert fensterwurzel(50, kette) is None


def test_alte_feste_startdatei_zaehlt_nicht() -> None:
    # Bis 28.09.2026 hiess die Datei immer start.ps1 - so ein Fenster ist nicht
    # sicher zuzuordnen, weil jeder Start dieselbe Datei nannte.
    kette = _kette()
    kette[20] = Prozess(20, 10, "powershell.exe", rf'powershell -File "{TEMP}\start.ps1"')
    assert fensterwurzel(50, kette) is None


def test_unbekannte_pid() -> None:
    assert fensterwurzel(999, _kette()) is None


def test_kreis_in_den_daten_haengt_nicht() -> None:
    kreis = {5: Prozess(5, 6, "a", "a"), 6: Prozess(6, 5, "b", "b")}
    assert fensterwurzel(5, kreis) is None
