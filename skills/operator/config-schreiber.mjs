// Meldet, wenn eine andere Claude-Instanz gerade ebenfalls nach claude-config
// schreibt. WARNT nur - blockiert nie.
//
// Hintergrund: Michael startet mehrere update-skill-Laeufe nebeneinander. Die
// ueberholen sich beim Commit und Push, was zu abgelehnten Pushes, Rebases und
// im schlimmsten Fall zu Merge-Commits fuehrt (belegt: 91a8d48).
//
// Bewusst KEINE Sperre. Michaels ausdrueckliche Vorgabe: eine Warnung reicht,
// er entscheidet selbst, ob er weitermacht.
//
// Aufruf aus dem PreToolUse-Hook, JSON des Werkzeugaufrufs auf stdin.
// Ausgabe: entweder nichts oder eine Zeile JSON mit systemMessage.
// Exit immer 0.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// Wie lange gilt ein Marker als frisch. Laenger als ein typischer
// update-skill-Lauf dauert, aber kurz genug, dass vergessene Marker nicht ewig
// warnen.
const FENSTER_MS = 10 * 60 * 1000;

const HIER = dirname(fileURLToPath(import.meta.url));

function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

function markerDatei() {
  const d = join(homedir(), '.claude', 'bus', rechner());
  mkdirSync(d, { recursive: true });
  return join(d, 'config-schreiber.json');
}

function lies(pfad) {
  if (!existsSync(pfad)) return {};
  try { return JSON.parse(readFileSync(pfad, 'utf8')); } catch { return {}; }
}

/** Loest die Session-ID in den vergebenen Instanznamen auf. */
function nameZu(sessionId) {
  try {
    const p = join(homedir(), '.claude', 'bus', rechner(), 'namen.json');
    const t = JSON.parse(readFileSync(p, 'utf8'));
    return t[sessionId] || sessionId.slice(0, 8);
  } catch {
    return sessionId.slice(0, 8);
  }
}

/**
 * Prueft, ob der Befehl schreibend auf claude-config wirkt.
 * Lesende Befehle (status, log, fetch, diff) sind unkritisch und sollen keine
 * Warnung ausloesen.
 */
function istConfigSchreibzugriff(command, cwd) {
  if (!command || !/\bgit\b/.test(command)) return null;

  const schreibend = /\bgit\b[^|;&]*\b(commit|push|rebase|merge|reset|checkout|restore)\b/.test(command);
  if (!schreibend) return null;

  // Trifft claude-config, wenn der Pfad im Befehl steht oder das
  // Arbeitsverzeichnis dort liegt. ~/.claude zaehlt mit, weil die Symlinks von
  // dort ins Repo zeigen.
  const imBefehl = /claude-config/.test(command);
  const imCwd = /claude-config/.test(cwd || '') || /[\\/]\.claude([\\/]|$)/.test(cwd || '');
  if (!imBefehl && !imCwd) return null;

  const art = /\bpush\b/.test(command) ? 'push'
    : /\bcommit\b/.test(command) ? 'commit'
      : 'schreibend';
  return art;
}

// ---------------------------------------------------------------------------

let roh = '';
try {
  roh = readFileSync(0, 'utf8');
} catch {
  process.exit(0);
}

let eingabe;
try { eingabe = JSON.parse(roh); } catch { process.exit(0); }

const command = (eingabe.tool_input && eingabe.tool_input.command) || '';
const cwd = eingabe.cwd || '';
const selbst = eingabe.session_id || process.env.CLAUDE_CODE_SESSION_ID || '';

const art = istConfigSchreibzugriff(command, cwd);
if (!art || !selbst) process.exit(0);

const pfad = markerDatei();
const marker = lies(pfad);
const jetzt = Date.now();

// Fremde, noch frische Marker einsammeln.
const andere = [];
for (const [sid, eintrag] of Object.entries(marker)) {
  if (sid === selbst) continue;
  const alter = jetzt - Date.parse(eintrag.ts || 0);
  if (Number.isFinite(alter) && alter < FENSTER_MS) {
    andere.push({ name: eintrag.name || nameZu(sid), art: eintrag.art, vorMin: Math.round(alter / 60000) });
  }
}

// Eigenen Marker setzen und dabei abgelaufene entfernen, damit die Datei nicht
// unbegrenzt waechst.
const frisch = {};
for (const [sid, eintrag] of Object.entries(marker)) {
  if (jetzt - Date.parse(eintrag.ts || 0) < FENSTER_MS) frisch[sid] = eintrag;
}
frisch[selbst] = { name: nameZu(selbst), art, ts: new Date(jetzt).toISOString() };
try { writeFileSync(pfad, JSON.stringify(frisch, null, 1), 'utf8'); } catch { /* egal */ }

if (andere.length === 0) process.exit(0);

const liste = andere
  .map((a) => `${a.name} (${a.art}, vor ${a.vorMin} Min)`)
  .join(', ');
const meldung = `ACHTUNG: ${liste} schreibt ebenfalls nach claude-config. `
  + `Dein ${art} kann abgelehnt werden oder einen Merge erzeugen. `
  + `Vorher: git pull --rebase. Der Befehl laeuft trotzdem weiter.`;

// Anfuehrungszeichen und Backslashes entschaerfen, damit die per JSON.stringify
// erzeugte Zeile in jedem Fall gueltig bleibt.
process.stdout.write(JSON.stringify({ systemMessage: meldung }) + '\n');
process.exit(0);
