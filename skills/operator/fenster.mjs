// Welche Sitzung lief zuletzt in diesem Fenster?
//
// ANLASS (02.10.2026, von Michael gemeldet): nach /clear meldete der Hook
// "Diese Instanz heisst Therese", waehrend die Statuszeile desselben Fensters
// weiter "Patrick" zeigte. /clear behaelt den Prozess, vergibt aber eine neue
// Session-ID - und die Namenstabelle haengt an der Session-ID. Der Hook hielt
// das Fenster deshalb fuer ein neues und zog einen frischen Namen. Der alte
// wurde beim naechsten Aufraeumen frei und ging an ein anderes Fenster, sodass
// zeitweise zwei Fenster "Agatha" anzeigten.
//
// Der Name gehoert dem FENSTER, die Session-ID ist nur sein aktueller
// Schluessel. Dieses Modul merkt sich deshalb je Prozess die letzte Sitzung,
// damit whoami.mjs den Namen beim Wechsel mitnehmen kann.
//
// Bewusst eine eigene Datei neben namen.json und kein weiteres Feld darin -
// dieselbe Begruendung wie bei socket.mjs: Operator, Statuszeile und Hooks
// lesen namen.json, ein Formatwechsel dort traefe alle.

import { readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const DATEINAME = 'fenster.json';

/**
 * Startzeitpunkt eines Claude-Prozesses, wie Claude Code ihn selbst festhaelt.
 *
 * Die PID allein reicht als Kennung nicht: Windows vergibt Nummern schnell
 * neu, und ein fremdes Fenster mit derselben PID wuerde sonst Namen und
 * Postfach eines beendeten erben - der Marga-Vorfall vom 07.08.2026 in neuer
 * Verkleidung. Erst PID und Startzeit zusammen bezeichnen einen Prozess.
 *
 * Gelesen aus ~/.claude/sessions/<pid>.json. Die Datei liegt beim
 * SessionStart-Hook bereits vor (geprueft am 02.10.2026 mit v2.1.287).
 *
 * @param {number|string} pid  Prozesskennung aus CLAUDE_PID.
 * @returns {string}  Startzeit, leer wenn sie sich nicht feststellen laesst.
 */
export function prozessStart(pid) {
  try {
    const datei = join(homedir(), '.claude', 'sessions', `${pid}.json`);
    const eintrag = JSON.parse(readFileSync(datei, 'utf8'));
    return eintrag && eintrag.procStart ? String(eintrag.procStart) : '';
  } catch {
    return '';
  }
}

/** Liest die Fensterliste. Fehlt die Datei oder ist sie kaputt, ist sie leer. */
export function ladeFenster(verzeichnis) {
  try {
    const liste = JSON.parse(readFileSync(join(verzeichnis, DATEINAME), 'utf8'));
    return liste && 'object' === typeof liste ? liste : {};
  } catch {
    return {};
  }
}

/**
 * Die Sitzung, die vor der jetzigen in diesem Fenster lief.
 *
 * Fail-closed: ohne PID, ohne Startzeit oder bei abweichender Startzeit gibt
 * es keinen Vorgaenger. Dann vergibt der Hook wie bisher einen neuen Namen -
 * ein Namenswechsel ist aergerlich, ein geerbtes fremdes Postfach ist teuer.
 *
 * @param {object} fenster  Die Fensterliste aus ladeFenster().
 * @param {number|string} pid  Eigene Prozesskennung.
 * @param {string} start  Eigene Startzeit aus prozessStart().
 * @param {string} sessionId  Die jetzige Session-ID.
 * @returns {string|null}  Session-ID des Vorgaengers, null wenn es keinen gibt.
 */
export function vorgaengerSitzung(fenster, pid, start, sessionId) {
  if (!pid || !start) return null;
  const eintrag = fenster[String(pid)];
  if (!eintrag || eintrag.procStart !== start) return null;
  if (!eintrag.sessionId || eintrag.sessionId === sessionId) return null;
  return eintrag.sessionId;
}

/**
 * Haelt fest, welche Sitzung jetzt in diesem Fenster laeuft, und wirft dabei
 * die Eintraege beendeter Prozesse hinaus.
 *
 * @param {object} fenster  Die Fensterliste, wird direkt veraendert.
 * @param {number|string} pid  Eigene Prozesskennung.
 * @param {string} start  Eigene Startzeit.
 * @param {string} sessionId  Die jetzige Session-ID.
 * @param {(pid: number) => boolean} lebt  Prueft, ob ein Prozess noch laeuft.
 * @returns {object}  Dieselbe Liste.
 */
export function merkeFenster(fenster, pid, start, sessionId, lebt) {
  for (const alt of Object.keys(fenster)) {
    if (!lebt(Number(alt))) delete fenster[alt];
  }
  if (pid && start) {
    fenster[String(pid)] = { sessionId, procStart: start };
  }
  return fenster;
}

/** Schreibt die Fensterliste zurueck. */
export function speichereFenster(verzeichnis, fenster) {
  writeFileSync(join(verzeichnis, DATEINAME), JSON.stringify(fenster, null, 1), 'utf8');
}
