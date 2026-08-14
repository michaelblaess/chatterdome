// Eine Sitzung beenden und mit --resume in einem neuen Fenster fortsetzen -
// auch dann, wenn der Auftrag per ssh von einem anderen Rechner kommt.
//
// WOZU: Eine laufende Sitzung haelt ihre Claude-Version fest. Nach einem
// Update holt erst ein Neustart die installierte. Mit --resume bleibt das
// Gespraech erhalten, und weil die Sitzungskennung dieselbe bleibt, auch der
// Name - die Namenstabelle haengt an der Kennung, nicht am Fenster.
//
// DIE HUERDE IST DAS FENSTER, NICHT DAS BEENDEN. Beenden geht per ssh
// problemlos. Ein Fenster dagegen braucht einen Desktop, und den hat eine
// ssh-Sitzung nicht:
//
//   Windows: der Aufruf laeuft im sshd-Dienstkontext (Session 0) und kommt an
//     keinen Desktop. Derselbe Ausweg wie bei shot.mjs - eine geplante
//     Aufgabe mit /IT, die im angemeldeten Benutzerkontext laeuft. Weil
//     schtasks keine wechselnden Argumente kennt, liegen sie in einer Datei,
//     die das Skript beim Lauf liest.
//   Linux/macOS: DISPLAY und XAUTHORITY sind in einer ssh-Sitzung nicht
//     gesetzt und werden aus der Prozessliste ermittelt (xUmgebung aus
//     shot.mjs, eine Quelle fuer beide Nutzer).
//
// Ausdruecklich KEIN tmux: das gibt es unter Windows nicht, und eine Sitzung
// darin waere auf dem Bildschirm auch nicht mehr zu sehen.

import { execFileSync, spawn } from 'node:child_process';
import {
  existsSync, mkdirSync, readFileSync, realpathSync, unlinkSync, writeFileSync,
} from 'node:fs';
import { homedir, hostname, platform } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { ladeInstanzen } from './instanzen.mjs';
import { xUmgebung } from './shot.mjs';

const HIER = dirname(fileURLToPath(import.meta.url));
const AUFGABE = 'ClaudeSanctuaryNeustart';
const R = '\x1b[0m', GRAU = '\x1b[38;5;244m', GRUEN = '\x1b[38;5;77m', ROT = '\x1b[38;5;203m';

/** Wie lange auf das Ergebnis der geplanten Aufgabe gewartet wird. */
const FRIST_MS = 20000;

function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

function datenDir() {
  const dir = join(homedir(), '.claude', 'bus', rechner());
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** Auftrag und Ergebnis der geplanten Aufgabe - der Umweg um schtasks herum. */
export function auftragsDatei() {
  return join(datenDir(), 'neustart-auftrag.json');
}

export function ergebnisDatei() {
  return join(datenDir(), 'neustart-ergebnis.json');
}

/**
 * Terminal-Kandidaten je System, in der Reihenfolge des Vorzugs.
 *
 * Dieselben wie in kern/terminals.py, nur ohne die Auswahl durch den Anwender:
 * hier zaehlt allein, dass ueberhaupt eines aufgeht.
 *
 * @param {string} befehlszeile Was im Fenster laufen soll.
 * @param {string} verzeichnis Arbeitsverzeichnis, darf leer sein.
 */
function terminalKandidaten(befehlszeile, verzeichnis) {
  const wd = verzeichnis || homedir();
  if (platform() === 'darwin') {
    return [['open', ['-a', 'Terminal', wd]]];
  }
  return [
    ['gnome-terminal', [`--working-directory=${wd}`, '--', 'bash', '-lc', befehlszeile]],
    ['konsole', ['--workdir', wd, '-e', 'bash', '-lc', befehlszeile]],
    ['xfce4-terminal', [`--working-directory=${wd}`, '-e', `bash -lc '${befehlszeile}'`]],
    ['wezterm', ['start', '--cwd', wd, '--', 'bash', '-lc', befehlszeile]],
    ['alacritty', ['--working-directory', wd, '-e', 'bash', '-lc', befehlszeile]],
    ['kitty', ['--directory', wd, 'bash', '-lc', befehlszeile]],
    ['xterm', ['-e', `bash -lc '${befehlszeile}'`]],
  ];
}

/**
 * Baut die Befehlszeile, die im neuen Fenster laufen soll.
 *
 * exec ersetzt die Shell durch claude, damit kein zusaetzlicher bash-Prozess
 * zwischen Fenster und Sitzung haengt.
 */
export function resumeBefehl(sessionId) {
  const claude = process.env.CLAUDE_CODE_EXECPATH || 'claude';
  return `exec ${claude} --resume ${sessionId}`;
}

/**
 * Oeffnet auf DIESEM Rechner ein Fenster mit der fortgesetzten Sitzung.
 *
 * @param {string} sessionId Kennung der fortzusetzenden Sitzung.
 * @param {string} verzeichnis Arbeitsverzeichnis, darf leer sein.
 * @returns {string} Leer bei Erfolg, sonst der Grund.
 */
export function neustartHier(sessionId, verzeichnis = '') {
  if (!sessionId) return 'Keine Sitzungskennung - ohne sie gibt es nichts fortzusetzen.';
  if (platform() === 'win32') return ueberAufgabe(sessionId, verzeichnis);
  return mitTerminal(sessionId, verzeichnis);
}

function mitTerminal(sessionId, verzeichnis) {
  // xUmgebung liefert DISPLAY und XAUTHORITY des laufenden Xorg. Ohne sie
  // scheitert jeder Terminalstart aus einer ssh-Sitzung mit "cannot open
  // display".
  const umgebung = { ...process.env, ...xUmgebung() };
  if (!umgebung.DISPLAY) {
    return 'Kein Desktop gefunden (DISPLAY leer) - auf diesem Rechner ist gerade niemand angemeldet.';
  }
  const zeile = resumeBefehl(sessionId);
  let letzter = '';
  for (const [befehl, args] of terminalKandidaten(zeile, verzeichnis)) {
    try {
      // detached und unref: sonst stirbt das Fenster mit der ssh-Sitzung, aus
      // der es gestartet wurde.
      const kind = spawn(befehl, args, {
        env: umgebung,
        detached: true,
        stdio: 'ignore',
      });
      kind.unref();
      return '';
    } catch (fehler) {
      letzter = String(fehler.message || '').split('\n')[0];
    }
  }
  return letzter || 'Kein Terminal gefunden (gnome-terminal, konsole, xterm).';
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
  const skript = join(HIER, 'neustart.ps1');
  const befehl = `powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "${skript}"`;
  execFileSync(
    'schtasks',
    ['/Create', '/TN', AUFGABE, '/TR', befehl, '/SC', 'ONCE', '/ST', '00:00', '/F', '/IT'],
    { encoding: 'utf8', timeout: 15000 },
  );
  return '';
}

function schlafe(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function ueberAufgabe(sessionId, verzeichnis) {
  if (!aufgabeVorhanden()) {
    return 'Keine Aufgabe eingerichtet. Auf dem Zielrechner einmalig ausfuehren: '
      + 'sanctuary restart --setup';
  }
  const ergebnis = ergebnisDatei();
  if (existsSync(ergebnis)) unlinkSync(ergebnis);
  writeFileSync(
    auftragsDatei(),
    `${JSON.stringify({ session: sessionId, cwd: verzeichnis || '' }, null, 1)}\n`,
    'utf8',
  );

  try {
    execFileSync('schtasks', ['/Run', '/TN', AUFGABE], { encoding: 'utf8', timeout: 15000 });
  } catch (fehler) {
    return `Die geplante Aufgabe liess sich nicht ausloesen: ${fehler.message}`;
  }

  const bis = Date.now() + FRIST_MS;
  while (Date.now() < bis) {
    if (existsSync(ergebnis)) {
      try {
        // Die Stueckliste abschneiden: schreibt das Skript sie doch einmal,
        // scheitert JSON.parse sonst mit "Unexpected token".
        const d = JSON.parse(readFileSync(ergebnis, 'utf8').replace(/^﻿/, ''));
        return d && d.ok ? '' : String((d && d.fehler) || 'Der Start meldete einen Fehler.');
      } catch {
        return 'Das Ergebnis der Aufgabe war nicht lesbar.';
      }
    }
    schlafe(200);
  }
  return 'Die geplante Aufgabe hat kein Fenster geoeffnet (niemand angemeldet?).';
}

/**
 * Stoesst den Neustart auf einem anderen Rechner an.
 *
 * Wie bei shot.mjs zwei Versuche: ein nacktes ssh findet "sanctuary" nur,
 * wenn ~/.local/bin schon im PATH ist - in einer nicht-interaktiven Sitzung
 * ist es das oft nicht, deshalb der zweite Weg ueber die Login-Shell.
 *
 * @returns {string} Leer bei Erfolg, sonst der Grund.
 */
export function neustartVonFerne(host, sessionId, verzeichnis = '') {
  const ziel = String(host).toLowerCase();
  const args = ['restart', '--session', sessionId];
  if (verzeichnis) args.push('--cwd', verzeichnis);
  const zeile = ['sanctuary', ...args].join(' ');
  const versuche = [zeile, `bash -lc "${zeile}"`];

  let letzter = '';
  for (const befehl of versuche) {
    try {
      execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', ziel, befehl], {
        encoding: 'utf8',
        timeout: FRIST_MS + 15000,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      return '';
    } catch (fehler) {
      letzter = String(fehler.stderr || fehler.message || '').trim().split('\n').pop() || '';
    }
  }
  return letzter || `Neustart auf ${ziel} fehlgeschlagen.`;
}

// ---------------------------------------------------------------------------
// Kommandozeile
// ---------------------------------------------------------------------------

function main(argv) {
  if (argv.includes('--setup') || argv.includes('--einrichten')) {
    const fehler = richteAufgabeEin();
    if (fehler) {
      console.log(`${GRAU}${fehler}${R}`);
      return 0;
    }
    console.log(`${GRUEN}Aufgabe eingerichtet.${R} ${GRAU}Neustart per ssh ist jetzt moeglich.${R}`);
    return 0;
  }

  const wert = (flagge) => {
    const i = argv.indexOf(flagge);
    return i !== -1 && argv[i + 1] ? argv[i + 1] : '';
  };
  const session = wert('--session');
  const verzeichnis = wert('--cwd');
  const host = wert('--host');
  const name = argv.find((a) => !a.startsWith('--') && argv[argv.indexOf(a) - 1] !== '--session'
    && argv[argv.indexOf(a) - 1] !== '--cwd' && argv[argv.indexOf(a) - 1] !== '--host') || '';

  if (host && session) {
    const fehler = neustartVonFerne(host, session, verzeichnis);
    if (fehler) {
      console.error(`${ROT}${fehler}${R}`);
      return 1;
    }
    console.log(`${GRUEN}Neustart auf ${host.toUpperCase()} angestossen.${R}`);
    return 0;
  }

  let kennung = session;
  let ordner = verzeichnis;
  if (!kennung && name) {
    // Komfort fuer die Hand: ueber den Namen die Sitzung dieses Rechners
    // suchen. Die Oberflaeche kennt die Kennung schon und uebergibt sie direkt.
    const treffer = ladeInstanzen().find(
      (i) => String(i.name || '').toLowerCase() === name.toLowerCase(),
    );
    if (!treffer) {
      console.error(`${ROT}Kein Agent namens ${name} auf ${rechner()}.${R}`);
      return 1;
    }
    kennung = treffer.sessionId || treffer.session_id || '';
    ordner = ordner || treffer.cwd || '';
  }
  if (!kennung) {
    console.error(`${ROT}Ohne Sitzungskennung gibt es nichts fortzusetzen.${R}`
      + `\n${GRAU}sanctuary restart <Name>  |  --session <id> [--host RECHNER]${R}`);
    return 1;
  }

  const fehler = neustartHier(kennung, ordner);
  if (fehler) {
    console.error(`${ROT}${fehler}${R}`);
    return 1;
  }
  console.log(`${GRUEN}Fenster geoeffnet.${R} ${GRAU}Die Sitzung laeuft unter derselben Kennung weiter.${R}`);
  return 0;
}

/**
 * Wurde diese Datei direkt aufgerufen, oder nur importiert?
 *
 * realpathSync: ~/.claude/skills ist ein Symlink ins Repo. Ohne das Aufloesen
 * ist der Vergleich bei jedem Aufruf ueber den Symlink falsch, und die
 * Kommandozeile liefe gar nicht - still, mit Exit 0.
 *
 * Der Guard drumherum ist kein Zierrat: bei "node -e" ist process.argv[1]
 * undefined, und realpathSync wirft dann. Ein Import wuerde den Aufrufer
 * mitreissen, statt nur keine CLI zu starten.
 */
function direktAufgerufen() {
  try {
    if (!process.argv[1]) return false;
    return import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
  } catch {
    return false;
  }
}

if (direktAufgerufen()) {
  process.exit(main(process.argv.slice(2)));
}
