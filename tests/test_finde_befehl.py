"""Der Aufruf von sanctuary darf mehrzeilige Argumente nicht abschneiden (28.09.2026)."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from claude_sanctuary.kern.lokale_quelle import finde_befehl


def _which(gefunden: str):  # type: ignore[no-untyped-def]
    def which(name: str) -> str | None:
        return gefunden if name == "sanctuary" else "node"

    return which


def test_batch_wrapper_wird_umgangen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", _which(r"C:\x\sanctuary.CMD"))
    befehl = finde_befehl()
    assert befehl[0] == "node"
    assert befehl[1].endswith("sanctuary.mjs")


def test_echter_kurzbefehl_bleibt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", _which("/home/x/.local/bin/sanctuary"))
    assert finde_befehl() == ["/home/x/.local/bin/sanctuary"]


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe gibt es nur unter Windows")
def test_der_grund_cmd_schneidet_am_zeilenumbruch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Belegt die Ursache selbst: dasselbe Argument, einmal ueber eine .cmd."""
    ziel = tmp_path / "argumente.txt"
    echo = tmp_path / "echo.py"
    echo.write_text(
        f"import sys\nopen(r'{ziel}', 'w', encoding='utf-8').write(sys.argv[1])\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{echo}" %*\r\n', encoding="utf-8", newline="")
    subprocess.run([str(wrapper), "erste\nzweite"], check=False, stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=60)
    assert ziel.read_text(encoding="utf-8") == "erste"
    subprocess.run([sys.executable, str(echo), "erste\nzweite"], check=True,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert ziel.read_text(encoding="utf-8") == "erste\nzweite"
