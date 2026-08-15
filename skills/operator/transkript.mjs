// Wo liegt das Gespraech einer Sitzung?
//
// Eigenes Modul nach dem Muster von instanzen.mjs und prozess.mjs: neustart.mjs
// braucht dieselbe Suche wie operator.mjs, koennte sie aber nicht von dort
// holen, ohne den CLI-Teil mitzuladen.

import { existsSync, readdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

/**
 * Sucht die Transkriptdatei einer Sitzung.
 *
 * Claude Code legt sie je Arbeitsverzeichnis ab (der Ordnername ist der Pfad
 * mit Bindestrichen), und welches das war, weiss der Aufrufer nicht - deshalb
 * die Suche ueber alle Projekte.
 *
 * @param {string} sessionId Kennung der Sitzung.
 * @returns {string|null} Pfad der .jsonl, oder null wenn es keine gibt.
 */
export function findeTranskript(sessionId) {
  if (!sessionId) return null;
  const wurzel = join(homedir(), '.claude', 'projects');
  if (!existsSync(wurzel)) return null;
  for (const projekt of readdirSync(wurzel)) {
    const dir = join(wurzel, projekt);
    try {
      if (!statSync(dir).isDirectory()) continue;
      const treffer = join(dir, `${sessionId}.jsonl`);
      if (existsSync(treffer)) return treffer;
    } catch { /* unlesbares Verzeichnis ueberspringen */ }
  }
  return null;
}

/**
 * Laesst sich diese Sitzung ueberhaupt fortsetzen?
 *
 * Ohne Transkript gibt es nichts fortzusetzen - "claude --resume" bricht dann
 * mit "No conversation found with session ID" ab, aber erst NACHDEM das
 * Fenster aufgegangen ist. Belegt am 16.08.2026 auf senza.
 */
export function fortsetzbar(sessionId) {
  return null !== findeTranskript(sessionId);
}
