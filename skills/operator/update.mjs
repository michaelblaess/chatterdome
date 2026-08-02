// Aktualisiert Claude Code - auf diesem oder einem anderen Rechner.
//
// WOZU: In der Uebersicht steht je Instanz die Claude-Version. Weicht sie
// zwischen den Rechnern ab, will man sie angleichen, ohne sich vorher per ssh
// dorthin zu verbinden.
//
// WELCHES VERFAHREN: Das haengt davon ab, wie Claude Code installiert wurde,
// und das weiss nur der Anwender. Deshalb wird NICHT geraten, sondern das
// Verfahren mitgegeben (--method). Ein falsch geratenes Verfahren waere
// schlimmer als keins: winget auf einer npm-Installation meldet froehlich
// Erfolg und aendert nichts.
//
// Aufruf:
//   node update.mjs                       lokal, Verfahren "claude"
//   node update.mjs SENZA --method npm    ueber ssh auf einem anderen Rechner
//   node update.mjs --check               nur die Version melden, nichts tun

import { execFileSync } from 'node:child_process';
import { platform } from 'node:os';
import { pathToFileURL } from 'node:url';
import { realpathSync } from 'node:fs';

const R = '\x1b[0m', GRAU = '\x1b[38;5;244m', GRUEN = '\x1b[38;5;77m', ROT = '\x1b[38;5;203m';

// Fuenf Minuten. Ein Paketmanager laedt herunter, entpackt und schreibt -
// die uebliche 25-Sekunden-Grenze der Oberflaeche waere hier zu knapp.
const ZEIT = 300000;

/**
 * Die Verfahren und ihre Befehlszeilen.
 *
 * Der Schluessel ist das, was die Oberflaeche in den Einstellungen anbietet.
 * Jeder Eintrag nennt zusaetzlich, wofuer er gedacht ist - das steht so auch
 * im Einstellungsdialog, damit niemand raten muss.
 */
export const VERFAHREN = {
  claude: { befehl: ['claude', 'update'], zweck: 'eingebauter Updater' },
  npm: { befehl: ['npm', 'install', '-g', '@anthropic-ai/claude-code'], zweck: 'npm-Installation' },
  winget: { befehl: ['winget', 'upgrade', '--id', 'Anthropic.ClaudeCode', '--silent'], zweck: 'Windows Paketverwaltung' },
  choco: { befehl: ['choco', 'upgrade', 'claude-code', '-y'], zweck: 'Chocolatey' },
  brew: { befehl: ['brew', 'upgrade', 'claude-code'], zweck: 'Homebrew' },
};

/**
 * Fuehrt die Aktualisierung auf diesem Rechner aus.
 *
 * @param {string} verfahren  Schluessel aus VERFAHREN.
 * @returns {{ok: boolean, ausgabe: string, version: string}}
 */
export function aktualisiere(verfahren = 'claude') {
  const eintrag = VERFAHREN[verfahren];
  if (!eintrag) {
    return { ok: false, ausgabe: `Unbekanntes Verfahren: ${verfahren}`, version: '' };
  }
  const [befehl, ...args] = ueberCmd(eintrag.befehl);
  try {
    const ausgabe = execFileSync(befehl, args, {
      encoding: 'utf8',
      timeout: ZEIT,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { ok: true, ausgabe: String(ausgabe).trim(), version: version() };
  } catch (fehler) {
    const text = String(fehler.stdout || '') + String(fehler.stderr || fehler.message || '');
    return { ok: false, ausgabe: text.trim().split('\n').slice(-5).join('\n'), version: version() };
  }
}

/**
 * Setzt unter Windows "cmd /c" davor.
 *
 * claude, npm und winget sind dort Wrapper-Skripte, die execFileSync ohne
 * Hilfe nicht findet. Die naheliegende Loesung waere shell:true - die ist
 * aber seit Node 22 abgekuendigt (DEP0190), weil dann die Argumente
 * unmaskiert aneinandergehaengt werden. Ueber cmd bleibt die Argumentliste
 * eine Liste.
 */
function ueberCmd(befehl) {
  return platform() === 'win32' ? ['cmd', '/c', ...befehl] : befehl;
}

/** Installierte Version, oder leer wenn nicht ermittelbar. */
export function version() {
  const [befehl, ...args] = ueberCmd(['claude', '--version']);
  try {
    const aus = execFileSync(befehl, args, {
      encoding: 'utf8', timeout: 20000,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    const treffer = String(aus).match(/\d+\.\d+\.\d+/);
    return treffer ? treffer[0] : String(aus).trim();
  } catch {
    return '';
  }
}

/**
 * Fuehrt die Aktualisierung auf einem anderen Rechner aus.
 *
 * Zwei Anlaeufe wie beim Bus: in einer nicht-interaktiven Shell fehlt
 * ~/.local/bin im PATH, erst die Login-Shell findet den Befehl.
 */
export function aktualisiereFern(host, verfahren) {
  const kern = `sanctuary update --method ${verfahren} --json`;
  const versuche = [kern, `bash -lc "${kern}"`];
  let letzter = '';
  for (const befehl of versuche) {
    try {
      const aus = execFileSync(
        'ssh',
        ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', String(host).toLowerCase(), befehl],
        { encoding: 'utf8', timeout: ZEIT, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      try {
        return JSON.parse(aus);
      } catch {
        return { ok: true, ausgabe: String(aus).trim(), version: '' };
      }
    } catch (fehler) {
      letzter = String(fehler.stderr || fehler.message || '').split('\n')[0].trim();
      if (/connect|timed out|refused|resolve|Host key/i.test(letzter)) break;
    }
  }
  return { ok: false, ausgabe: letzter || 'nicht erreichbar', version: '' };
}

// ---------------------------------------------------------------------------

function main(argv) {
  const wert = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : null;
  };
  const alsJson = argv.includes('--json');
  const verfahren = wert('--method') || 'claude';
  // Den Wert hinter --method ueberspringen, sonst haelt ihn die Suche nach
  // dem Rechnernamen fuer eben diesen.
  const methodeIdx = argv.indexOf('--method');
  const ziel = argv.find((a, i) => !a.startsWith('--') && i !== methodeIdx + 1);
  const hier = (process.env.COMPUTERNAME || '').toUpperCase();

  if (argv.includes('--check')) {
    const v = version();
    if (alsJson) console.log(JSON.stringify({ ok: Boolean(v), version: v, ausgabe: '' }));
    else console.log(v ? `  Claude ${v}` : `  ${ROT}Version nicht ermittelbar${R}`);
    return;
  }

  const ergebnis = ziel && ziel.toUpperCase() !== hier
    ? aktualisiereFern(ziel, verfahren)
    : aktualisiere(verfahren);

  if (alsJson) {
    console.log(JSON.stringify(ergebnis));
    if (!ergebnis.ok) process.exitCode = 1;
    return;
  }
  const wo = ziel || hier || 'hier';
  if (ergebnis.ok) {
    console.log(`\n  ${GRUEN}${wo}: aktualisiert${R}${ergebnis.version ? ` ${GRAU}(${ergebnis.version})${R}` : ''}`);
  } else {
    console.log(`\n  ${ROT}${wo}: fehlgeschlagen${R}`);
    process.exitCode = 1;
  }
  if (ergebnis.ausgabe) console.log(`  ${GRAU}${ergebnis.ausgabe.split('\n').join(`\n  `)}${R}`);
  console.log('');
}

const direkt = process.argv[1]
  && pathToFileURL(aufgeloest(process.argv[1])).href === import.meta.url;

function aufgeloest(pfad) {
  try { return realpathSync(pfad); } catch { return pfad; }
}

if (direkt) main(process.argv.slice(2));
