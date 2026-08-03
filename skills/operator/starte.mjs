// Startet eine neue Claude-Instanz mit einem Namen aus dem Pool.
//
// Der Name landet ueber "claude -n <Name>" in der Prompt-Box, im /resume-Picker
// UND in der Terminal-Titelleiste. Damit sieht man am Tab, welche Instanz das
// ist - was der SessionStart-Hook allein nicht leisten kann, weil er den Titel
// nicht setzen darf.
//
// Der Ablauf:
//   1. freien Namen aus namenspool.json suchen
//   2. ihn ueber CLAUDE_INSTANZ_NAME an den Kindprozess weiterreichen
//   3. claude -n <Name> starten
//   4. der SessionStart-Hook liest die Variable und traegt den Namen mit der
//      echten Session-ID in namen.json ein
//
// Schritt 2 bis 4 ist noetig, weil die Session-ID erst nach dem Start existiert.
//
// Aufruf:
//   node starte.mjs                   naechster freier Name
//   node starte.mjs Patrick           bestimmter Name
//   node starte.mjs -- --resume       alles nach -- geht an claude durch

import { spawn } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { ladePool } from './pool.mjs';

function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

function namenDatei() {
  const d = join(homedir(), '.claude', 'bus', rechner());
  mkdirSync(d, { recursive: true });
  return join(d, 'namen.json');
}

function ladeNamen() {
  const p = namenDatei();
  if (!existsSync(p)) return {};
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return {}; }
}

// ladePool kommt aus pool.mjs - eine Quelle fuer alle drei Nutzer.

// --- Argumente: alles nach -- geht unveraendert an claude ---------------------

const argv = process.argv.slice(2);
const trenner = argv.indexOf('--');
const eigene = trenner === -1 ? argv : argv.slice(0, trenner);
const durchreichen = trenner === -1 ? [] : argv.slice(trenner + 1);

const pool = ladePool();
const vergeben = new Set(Object.values(ladeNamen()));

let name = eigene[0];
if (name) {
  if (vergeben.has(name)) {
    console.error(`Der Name ${name} ist bereits vergeben. Frei: ${pool.filter((n) => !vergeben.has(n)).slice(0, 8).join(', ')}`);
    process.exit(1);
  }
} else {
  const frei = pool.filter((n) => !vergeben.has(n));
  // Pool erschoepft: durchnummerieren statt doppelt vergeben.
  name = frei.length ? frei[0] : `${pool[0]}-${vergeben.size + 1}`;
}

const claudeCmd = process.env.CLAUDE_CODE_EXECPATH || 'claude';
const argumente = ['-n', name, ...durchreichen];
const umgebung = { ...process.env, CLAUDE_INSTANZ_NAME: name };

// stdio: 'inherit' gibt das Terminal komplett an Claude weiter, sonst waere die
// Oberflaeche nicht bedienbar.
//
// Zwei Wege, je nachdem ob der echte Binaerpfad bekannt ist:
//   - CLAUDE_CODE_EXECPATH gesetzt -> ohne Shell, Argumente als Array (sicher).
//   - sonst ist "claude" unter Windows ein Wrapper, den nur die Shell im PATH
//     findet. Dann die GANZE Zeile als EIN String uebergeben - ein Args-Array
//     zusammen mit shell:true ist seit Node 24 abgekuendigt (DEP0190), weil die
//     Argumente dabei nur konkateniert statt escaped werden.
let kind;
if (process.env.CLAUDE_CODE_EXECPATH) {
  kind = spawn(claudeCmd, argumente, { stdio: 'inherit', shell: false, env: umgebung });
} else {
  const zeile = [claudeCmd, ...argumente].map(_zitatShell).join(' ');
  kind = spawn(zeile, { stdio: 'inherit', shell: true, env: umgebung });
}

kind.on('exit', (code) => process.exit(code ?? 0));
kind.on('error', (e) => {
  console.error(`Konnte claude nicht starten: ${e.message}`);
  process.exit(1);
});

/**
 * Quotet ein Argument fuer die Shell, damit shell:true es nicht zerlegt.
 *
 * Windows nutzt cmd.exe, POSIX /bin/sh - beide werden bedient. Die hier
 * uebergebenen Werte (validierter Name, Flags) sind harmlos, aber korrektes
 * Quoting ist billig und faengt Argumente mit Leerzeichen ab.
 *
 * @param {string} teil
 * @returns {string}
 */
function _zitatShell(teil) {
  if (process.platform === 'win32') {
    return /[\s"&|<>^()]/.test(teil) ? `"${teil.replace(/"/g, '""')}"` : teil;
  }
  return /[^A-Za-z0-9_@%+=:,./-]/.test(teil) ? `'${teil.replace(/'/g, "'\\''")}'` : teil;
}
