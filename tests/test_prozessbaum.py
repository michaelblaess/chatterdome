"""Der Weg vom Claude-Prozess zur Shell unserer Startdatei."""

from __future__ import annotations

from chatterdome.kern.prozessbaum import Prozess, fensterwurzel

TEMP = r"C:\Users\x\AppData\Local\Temp\chatterdome"


def _kette() -> dict[int, Prozess]:
    # So sah die Kette am 28.09.2026 aus: Terminal, Shell mit Startdatei,
    # cmd fuer chatterdome.CMD, node, claude.
    return {
        10: Prozess(10, 1, "WindowsTerminal.exe", "wt"),
        20: Prozess(20, 10, "powershell.exe",
                    rf'powershell.exe -NoExit -File "{TEMP}\start-ab12cd.ps1"'),
        30: Prozess(30, 20, "cmd.exe", 'cmd.exe /c "chatterdome.CMD" start'),
        40: Prozess(40, 30, "node.exe", "node chatterdome.mjs start"),
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


def test_fenster_aus_der_zeit_vor_der_umbenennung() -> None:
    # Fenster, die vor dem 29.09.2026 geoeffnet wurden, haben ihre Startdatei
    # noch im Temp-Ordner "claude-sanctuary".
    kette = _kette()
    alt = TEMP.replace("chatterdome", "claude-sanctuary")
    kette[20] = Prozess(20, 10, "powershell.exe",
                        rf'powershell.exe -NoExit -File "{alt}\start-ab12cd.ps1"')
    assert fensterwurzel(50, kette) == 20


def test_aehnlicher_ordnername_zaehlt_nicht() -> None:
    kette = _kette()
    fremd = TEMP.replace("chatterdome", "sanctuary-fremd")
    kette[20] = Prozess(20, 10, "powershell.exe",
                        rf'powershell.exe -NoExit -File "{fremd}\start-ab12cd.ps1"')
    assert fensterwurzel(50, kette) is None
