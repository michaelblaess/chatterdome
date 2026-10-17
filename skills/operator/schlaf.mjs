// Schlaf-Marke fuer den Tab-Titel: alte Sitzungen bekommen ein 😴 vorangestellt.
//
// Zweck: bei fuenf, sechs offenen Tabs sieht man nicht, welche schon Stunden oder
// Tage alt sind. Ausgrauen geht nicht - Windows Terminal kennt keine Sequenz, mit
// der ein Prozess die Farbe seines eigenen Tabs aendert (OSC 9;4 am 17.10.2026
// probiert, im Tab kam nichts an), und Kitty & Co. haetten wieder eigene Wege.
// Ein Zeichen im Titel geht dagegen in jedem Terminal.
//
// Das Alter zaehlt ab dem ersten Eintrag der Sitzungsdatei, also ab dem Start.
// Ein --resume setzt es deshalb nicht zurueck.

import { closeSync, fstatSync, openSync, readSync } from 'node:fs';

export const SCHLAF_ZEICHEN = '😴';
export const STANDARD_STUNDEN = 6;

// Der erste Zeitstempel steht in den ersten Zeilen. Die Kopfzeilen (last-prompt,
// mode, permission-mode) tragen keinen, 64 KB reichen dafuer reichlich.
const KOPF_BYTES = 64 * 1024;

/**
 * Liest den ersten Zeitstempel einer Sitzungsdatei.
 * @param {string} inhalt Anfang der Sitzungsdatei.
 * @returns {number} Zeitpunkt in Millisekunden oder NaN, wenn keiner zu finden ist.
 */
export function startAusKopf(inhalt) {
  const treffer = /"timestamp":"([^"]+)"/.exec(inhalt);
  return treffer ? Date.parse(treffer[1]) : Number.NaN;
}

/**
 * Ermittelt den Startzeitpunkt einer Sitzung aus dem Anfang ihrer Datei.
 * @param {string} pfad Pfad der Sitzungsdatei.
 * @returns {number} Zeitpunkt in Millisekunden oder NaN.
 */
export function sitzungsStart(pfad) {
  let fd;
  try {
    fd = openSync(pfad, 'r');
    const laenge = Math.min(KOPF_BYTES, fstatSync(fd).size);
    if (laenge <= 0) return Number.NaN;
    const puffer = Buffer.allocUnsafe(laenge);
    readSync(fd, puffer, 0, laenge, 0);
    return startAusKopf(puffer.toString('utf8'));
  } catch {
    return Number.NaN;
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        // Schliessen darf den Prompt nicht aufhalten.
      }
    }
  }
}

/**
 * Schwelle in Stunden aus der Umgebung, sonst der Standard. 0 schaltet die Marke ab.
 * @param {string | undefined} wert Inhalt von CHATTERDOME_SCHLAF_STUNDEN.
 * @returns {number} Schwelle in Stunden.
 */
export function schwelleStunden(wert) {
  const zahl = Number.parseFloat(String(wert ?? '').replace(',', '.'));
  return Number.isFinite(zahl) && zahl >= 0 ? zahl : STANDARD_STUNDEN;
}

/**
 * Liefert die Marke, wenn die Sitzung älter als die Schwelle ist.
 * @param {number} startMs Startzeitpunkt der Sitzung in Millisekunden.
 * @param {number} jetztMs Aktueller Zeitpunkt in Millisekunden.
 * @param {number} stunden Schwelle in Stunden, 0 schaltet ab.
 * @returns {string} "😴 " oder ein leerer String.
 */
export function schlafMarke(startMs, jetztMs, stunden) {
  if (!Number.isFinite(startMs) || stunden <= 0) return '';
  return jetztMs - startMs >= stunden * 3600 * 1000 ? `${SCHLAF_ZEICHEN} ` : '';
}
