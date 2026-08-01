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

// stdio: 'inherit' gibt das Terminal komplett an Claude weiter, sonst waere die
// Oberflaeche nicht bedienbar.
const kind = spawn(claudeCmd, ['-n', name, ...durchreichen], {
  stdio: 'inherit',
  shell: !process.env.CLAUDE_CODE_EXECPATH,
  env: { ...process.env, CLAUDE_INSTANZ_NAME: name },
});

kind.on('exit', (code) => process.exit(code ?? 0));
kind.on('error', (e) => {
  console.error(`Konnte claude nicht starten: ${e.message}`);
  process.exit(1);
});
