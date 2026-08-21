// Wo liegt das Gespraech einer Sitzung?
//
// Eigenes Modul nach dem Muster von instanzen.mjs und prozess.mjs: neustart.mjs
// braucht dieselbe Suche wie operator.mjs, koennte sie aber nicht von dort
// holen, ohne den CLI-Teil mitzuladen.

import { closeSync, existsSync, openSync, readSync, readdirSync, statSync } from 'node:fs';
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

/** Womit der erste Leseversuch beginnt. Deckt die allermeisten Faelle ab. */
export const FENSTER_START = 400_000;

/**
 * Obergrenze fuer das Nachfassen.
 *
 * EINE Zeile kann riesig sein: Claude Code schreibt Dateisnapshots und
 * eingefuegte Inhalte als je eine JSON-Zeile. Gemessen am 22.08.2026 ueber
 * 34.846 Zeilen aus zwoelf Transkripten: die groesste war 1.454 KB, und 291
 * lagen ueber 64 KB. Dieselbe Groessenordnung setzt pradipta/wallfacer fuer
 * seinen Zeilenpuffer an (16 MB), und aus demselben Grund.
 */
export const FENSTER_MAX = 16 * 1024 * 1024;

/** Liest die letzten `fenster` Bytes und zerlegt sie in vollstaendige Zeilen. */
function ausFenster(pfad, groesse, fenster) {
  let fd;
  try {
    fd = openSync(pfad, 'r');
    const puffer = Buffer.alloc(fenster);
    const gelesen = readSync(fd, puffer, 0, fenster, groesse - fenster);
    const zeilen = puffer.toString('utf8', 0, gelesen).trimEnd().split('\n');
    // Die erste Zeile im Fenster ist angeschnitten, sobald nicht die ganze
    // Datei gelesen wurde - sie waere kein gueltiges JSON.
    if (fenster < groesse) zeilen.shift();
    return zeilen.filter((z) => z.trim());
  } catch {
    return [];
  } finally {
    if (undefined !== fd) {
      try { closeSync(fd); } catch { /* egal */ }
    }
  }
}

/**
 * Liest die letzten Zeilen einer Datei, ohne sie komplett zu laden.
 *
 * Wichtig, weil Transkripte zweistellige MB erreichen: eine fortgesetzte
 * Sitzung hatte 8,3 MB, und der Vollread lief je Instanz und je Aufruf erneut.
 *
 * NACHFASSEN, WENN DAS FENSTER NICHTS HERGIBT: liegt am Dateiende eine
 * einzelne Zeile, die groesser ist als das Fenster, bleibt nach dem Abschneiden
 * der angeschnittenen ersten Zeile NICHTS uebrig - und die Sitzung stuende ohne
 * Modell, Kontext und Werkzeug in der Tabelle, ohne dass irgendwo ein Fehler
 * auftaucht. Deshalb wird das Fenster dann vervierfacht, bis etwas kommt.
 *
 * Im Normalfall bleibt es bei genau einem Lesevorgang: geprueft am 22.08.2026
 * ueber alle 42 Transkripte, die groesser als das Startfenster sind - keines
 * brauchte einen zweiten Versuch.
 */
export function letzteZeilen(pfad, anzahl) {
  let groesse;
  try {
    groesse = statSync(pfad).size;
  } catch {
    return [];
  }
  let fenster = Math.min(groesse, FENSTER_START);
  for (;;) {
    const zeilen = ausFenster(pfad, groesse, fenster);
    if (zeilen.length || fenster >= groesse || fenster >= FENSTER_MAX) {
      return zeilen.slice(-anzahl);
    }
    fenster = Math.min(groesse, Math.min(FENSTER_MAX, fenster * 4));
  }
}
