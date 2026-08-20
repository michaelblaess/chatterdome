// SessionStart-Hook: haelt den Inbox-Socket dieser Sitzung fest.
//
// WARUM EIN EIGENER HOOK UND NICHT whoami.mjs: whoami steigt fuer eine Sitzung,
// die ihren Namen schon hat, ganz oben wieder aus (der haeufige Fall bei
// "claude --resume"). Ein Socket-Eintrag muss aber JEDES Mal geschrieben
// werden, denn der Pfad enthaelt die PID - nach einem Neustart derselben
// Sitzung ist er ein anderer. In whoami waere die Eintragung genau dann
// ausgefallen, wenn sie am noetigsten ist.
//
// Claude Code exportiert CLAUDE_CODE_MESSAGING_SOCKET, bevor irgendein Hook
// laeuft, SessionStart eingeschlossen. Auf nativem Windows gibt es die Variable
// nicht - dort endet dieses Skript still, und der Bus bleibt beim Stop-Hook.
//
// Ausgabe: KEINE. Der Hook ist reine Buchfuehrung und darf den Sitzungsstart
// nicht mit Text zumuellen. Jeder Fehler endet still mit Code 0, damit eine
// Sitzung niemals an dieser Nebensache scheitert.

import { mkdirSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { merkeSocket, raeumeSockets } from './socket.mjs';

function rechnername() {
  const n = process.env.COMPUTERNAME || hostname().split('.')[0];
  return n.toUpperCase();
}

function datenVerzeichnis() {
  const dir = join(homedir(), '.claude', 'bus', rechnername());
  mkdirSync(dir, { recursive: true });
  return dir;
}

/**
 * Entfernt Eintraege beendeter Sitzungen.
 *
 * Bewusst NUR hier und nicht bei jeder Zustellung: die Instanzliste kostet den
 * Aufruf von "claude agents --json" und damit knapp eine Sekunde. Beim
 * Sitzungsstart faellt das nicht auf, in einem Zustellweg schon.
 *
 * Ein dynamisches import(), damit der haeufige Fall ohne Socket dieses Modul
 * gar nicht erst laedt.
 */
async function aufraeumen(datenDir) {
  try {
    const { ladeInstanzen } = await import(new URL('../operator/instanzen.mjs', import.meta.url).href);
    const laufende = ladeInstanzen({ timeout: 5000 });
    raeumeSockets(datenDir, laufende.map((i) => i.sessionId));
  } catch { /* Aufraeumen ist Kuer, Eintragen ist Pflicht */ }
}

const sessionId = process.env.CLAUDE_CODE_SESSION_ID;
const socket = process.env.CLAUDE_CODE_MESSAGING_SOCKET;
// Der Token beglaubigt eine von aussen eingespeiste Nachricht als "eigenes
// Kind". Fehlt er, gilt sie als unbeglaubigt und wird in einer Sitzung mit
// uebersprungenen Rueckfragen zur Freigabe zurueckgehalten - Anthropics Doku,
// Abschnitt "own-child messages". Auf Linux rettet dort die Pruefung ueber
// den Prozessbaum, unter Windows gibt es die nicht.
const token = process.env.CLAUDE_CODE_MESSAGING_TOKEN || '';

// Kein Socket heisst: natives Windows, oder das Feature ist noch nicht scharf.
// Beides ist normal und keine Meldung wert.
if (sessionId && socket) {
  try {
    const datenDir = datenVerzeichnis();
    merkeSocket(datenDir, sessionId, socket, token);
    await aufraeumen(datenDir);
  } catch { /* siehe Kommentarkopf */ }
}
