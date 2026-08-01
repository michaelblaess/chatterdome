// Bildschirmfoto eines Rechners - lokal oder ueber das Tailnet.
//
// WOZU: In der Uebersicht steht, dass ein Agent auf einem anderen Rechner
// beschaeftigt ist. Was er dort tut, sieht man nicht. Ein Blick auf den
// Bildschirm beantwortet das schneller als jede Statusabfrage.
//
// WINDOWS UND DIE SESSION-0-HUERDE: Ueber ssh laeuft der Aufruf im
// sshd-Dienstkontext, und der hat keinen Desktop. Gemessen am 02.08.2026 auf
// RAINBOW meldet VirtualScreen dort 1024x768 statt der echten 7680x1446, und
// CopyFromScreen scheitert mit "Das Handle ist ungueltig". Der Ausweg ist eine
// geplante Aufgabe, die im angemeldeten Benutzerkontext laeuft und per
// "schtasks /Run" ausgeloest wird - damit entstand das Bild (2,1 MB, geprueft).
// Einzurichten mit: sanctuary shot --einrichten
//
// LINUX: import(1) aus ImageMagick, mit DISPLAY und XAUTHORITY des laufenden
// Xorg. Beides ist in einer ssh-Sitzung nicht gesetzt und wird deshalb aus der
// Prozessliste ermittelt.

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { homedir, platform, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

const R = '\x1b[0m', GRAU = '\x1b[38;5;244m', GRUEN = '\x1b[38;5;77m', ROT = '\x1b[38;5;203m';
const HIER = dirname(fileURLToPath(import.meta.url));
const AUFGABE = 'ClaudeSanctuaryShot';

/** Ablage der Bilder. Bewusst fluechtig - ein Bildschirmfoto ist kein Bestand. */
export function shotOrdner() {
  const p = join(tmpdir(), 'claude-sanctuary-shots');
  if (!existsSync(p)) mkdirSync(p, { recursive: true });
  return p;
}

function zielPfad() {
  // Ohne Zeitstempel im Namen: sonst sammeln sich die Dateien unbemerkt an.
  // Wer mehrere behalten will, kopiert sie selbst weg.
  return join(shotOrdner(), `shot-${process.env.COMPUTERNAME || 'lokal'}.png`);
}

// ---------------------------------------------------------------------------
// Lokale Aufnahme
// ---------------------------------------------------------------------------

/**
 * Nimmt den Bildschirm dieses Rechners auf.
 *
 * @param {string} ziel Pfad der PNG-Datei.
 * @returns {{pfad: string, groesse: string}}
 * @throws wenn kein Desktop erreichbar ist.
 */
export function nimmLokalAuf(ziel = zielPfad()) {
  const p = platform();
  if (p === 'win32') return { pfad: ziel, groesse: windowsAufnahme(ziel) };
  if (p === 'darwin') {
    execFileSync('screencapture', ['-x', ziel], { timeout: 20000 });
    return { pfad: ziel, groesse: '' };
  }
  return { pfad: ziel, groesse: linuxAufnahme(ziel) };
}

function windowsAufnahme(ziel) {
  const skript = join(HIER, 'shot.ps1');
  try {
    return execFileSync(
      'powershell',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', skript, '-Ziel', ziel],
      { encoding: 'utf8', timeout: 30000 },
    ).trim();
  } catch (fehler) {
    // Kein Desktop in dieser Sitzung: ueber die geplante Aufgabe versuchen,
    // die im Benutzerkontext laeuft. Das ist der ssh-Fall.
    const meldung = String(fehler.stderr || fehler.message || '');
    if (!/Handle|Dienst-Sitzung|ungueltig|ungültig|invalid/i.test(meldung)) throw fehler;
    return ueberAufgabe(ziel);
  }
}

/**
 * Loest die geplante Aufgabe aus und wartet auf die Datei.
 *
 * schtasks kehrt sofort zurueck, die Aufgabe laeuft asynchron - deshalb wird
 * auf das Entstehen der Datei gewartet und nicht auf den Rueckgabewert.
 */
function ueberAufgabe(ziel) {
  if (!aufgabeVorhanden()) {
    throw new Error(
      'Kein Desktop in dieser Sitzung und keine Aufgabe eingerichtet. '
      + 'Auf dem Zielrechner einmalig ausfuehren: sanctuary shot --einrichten',
    );
  }
  if (existsSync(ziel)) unlinkSync(ziel);
  execFileSync('schtasks', ['/Run', '/TN', AUFGABE], { encoding: 'utf8', timeout: 15000 });

  const bis = Date.now() + 15000;
  while (Date.now() < bis) {
    if (existsSync(ziel)) {
      // Die Datei existiert, sobald sie angelegt ist - vollstaendig
      // geschrieben ist sie erst, wenn die Groesse sich nicht mehr aendert.
      const groesse = () => { try { return readFileSync(ziel).length; } catch { return 0; } };
      let a = groesse();
      for (let i = 0; i < 40; i++) {
        schlafe(250);
        const b = groesse();
        if (b > 0 && b === a) return '';
        a = b;
      }
      return '';
    }
    schlafe(200);
  }
  throw new Error('Die geplante Aufgabe hat kein Bild erzeugt (niemand angemeldet?).');
}

/**
 * Blockierendes Warten ohne Prozessstart.
 *
 * setTimeout scheidet aus, weil der ganze Ablauf synchron ist. Ein Node-
 * Unterprozess je Runde waere die teuerste denkbare Uhr - unter Windows kostet
 * allein sein Start rund 70 ms.
 */
function schlafe(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function aufgabeVorhanden() {
  try {
    execFileSync('schtasks', ['/Query', '/TN', AUFGABE], { stdio: 'ignore', timeout: 10000 });
    return true;
  } catch { return false; }
}

/**
 * Legt die geplante Aufgabe an, die im Benutzerkontext laeuft.
 *
 * /IT sorgt dafuer, dass sie nur bei angemeldetem Benutzer und in dessen
 * interaktiver Sitzung laeuft - genau das, was der Dienstkontext nicht kann.
 */
export function richteAufgabeEin() {
  if (platform() !== 'win32') return 'Nur unter Windows noetig.';
  const skript = join(HIER, 'shot.ps1');
  const befehl = `powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "${skript}" -Ziel "${zielPfad()}"`;
  execFileSync(
    'schtasks',
    ['/Create', '/TN', AUFGABE, '/TR', befehl, '/SC', 'ONCE', '/ST', '00:00', '/F', '/IT'],
    { encoding: 'utf8', timeout: 15000 },
  );
  return '';
}

function linuxAufnahme(ziel) {
  const umgebung = { ...process.env, ...xUmgebung() };
  const versuche = [
    ['import', ['-window', 'root', ziel]],
    ['gnome-screenshot', ['-f', ziel]],
    ['scrot', ['-o', ziel]],
    ['grim', [ziel]],
  ];
  let letzter = '';
  for (const [befehl, args] of versuche) {
    try {
      execFileSync(befehl, args, { env: umgebung, timeout: 25000, stdio: 'pipe' });
      if (existsSync(ziel)) return '';
    } catch (fehler) {
      letzter = String(fehler.stderr || fehler.message || '').split('\n')[0];
    }
  }
  throw new Error(letzter || 'Kein Aufnahmewerkzeug gefunden (import, grim, scrot).');
}

/**
 * Ermittelt DISPLAY und XAUTHORITY des laufenden X-Servers.
 *
 * In einer ssh-Sitzung ist beides leer. Der Xorg-Prozess traegt die Angaben
 * aber in seiner Kommandozeile: "Xorg vt2 -displayfd 3 -auth /run/user/1000/
 * gdm/Xauthority". Der Socket in /tmp/.X11-unix nennt die Anzeigenummer.
 */
function xUmgebung() {
  const werte = {};
  try {
    const ps = execFileSync('ps', ['-eo', 'args'], { encoding: 'utf8', timeout: 8000 });
    const auth = ps.match(/-auth\s+(\S+)/);
    if (auth) werte.XAUTHORITY = auth[1];
  } catch { /* ohne ps bleibt es beim Vorhandenen */ }
  if (!process.env.DISPLAY) {
    try {
      const socket = execFileSync('ls', ['/tmp/.X11-unix'], { encoding: 'utf8', timeout: 5000 })
        .split('\n').map((z) => z.trim()).find((z) => /^X\d+$/.test(z));
      if (socket) werte.DISPLAY = `:${socket.slice(1)}`;
    } catch { /* dann eben ohne */ }
  }
  return werte;
}

// ---------------------------------------------------------------------------
// Aufnahme von einem anderen Rechner
// ---------------------------------------------------------------------------

/**
 * Holt ein Bildschirmfoto von einem anderen Rechner.
 *
 * Das Bild kommt base64-kodiert ueber stdout zurueck statt per scp: ein
 * Rueckkanal weniger, und es funktioniert auch dort, wo scp nicht eingerichtet
 * ist. Der Aufschlag von einem Drittel faellt bei einem Bild dieser Groesse
 * nicht ins Gewicht.
 */
export function holeVonFerne(host, ziel = join(shotOrdner(), `shot-${String(host).toUpperCase()}.png`)) {
  const versuche = ['sanctuary shot --stdout', 'bash -lc "sanctuary shot --stdout"'];
  let letzter = '';
  for (const befehl of versuche) {
    try {
      const roh = execFileSync(
        'ssh',
        ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', String(host).toLowerCase(), befehl],
        { encoding: 'utf8', timeout: 60000, maxBuffer: 64 * 1024 * 1024 },
      );
      const daten = Buffer.from(roh.trim(), 'base64');
      if (daten.length < 100) throw new Error('leere Antwort');
      writeFileSync(ziel, daten);
      return { pfad: ziel, groesse: '' };
    } catch (fehler) {
      letzter = String(fehler.stderr || fehler.message || '').split('\n').filter(Boolean).pop() || '';
      if (/connect|timed out|refused|resolve/i.test(letzter)) break;
    }
  }
  throw new Error(letzter || 'nicht erreichbar');
}

// ---------------------------------------------------------------------------
// Kommandozeile
// ---------------------------------------------------------------------------

function main(argv) {
  if (argv.includes('--einrichten')) {
    try {
      const hinweis = richteAufgabeEin();
      console.log(hinweis || `${GRUEN}Aufgabe ${AUFGABE} eingerichtet.${R}`);
    } catch (fehler) {
      console.error(`${ROT}${fehler.message}${R}`);
      process.exitCode = 1;
    }
    return;
  }

  const alsJson = argv.includes('--json');
  const alsStrom = argv.includes('--stdout');
  const ziel = argv.find((a) => !a.startsWith('--'));
  const hier = (process.env.COMPUTERNAME || '').toUpperCase();

  try {
    const start = Date.now();
    const ergebnis = ziel && ziel.toUpperCase() !== hier
      ? holeVonFerne(ziel)
      : nimmLokalAuf();
    const ms = Date.now() - start;

    if (alsStrom) {
      process.stdout.write(readFileSync(ergebnis.pfad).toString('base64'));
      return;
    }
    if (alsJson) {
      console.log(JSON.stringify({
        pfad: ergebnis.pfad,
        rechner: (ziel || hier).toUpperCase(),
        groesse: ergebnis.groesse || null,
        bytes: readFileSync(ergebnis.pfad).length,
        ms,
      }));
      return;
    }
    console.log(`${GRUEN}${ergebnis.pfad}${R}  ${GRAU}${ergebnis.groesse} ${ms} ms${R}`);
  } catch (fehler) {
    if (alsJson) {
      console.log(JSON.stringify({ fehler: fehler.message }));
      return;
    }
    console.error(`${ROT}${fehler.message}${R}`);
    process.exitCode = 1;
  }
}

// Direkt aufgerufen? Der Vergleich geht auch dann auf, wenn sanctuary.mjs
// argv[1] umgebogen hat - genau so macht es bus.mjs.
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  main(process.argv.slice(2));
}
