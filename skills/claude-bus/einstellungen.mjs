// Einstellungen des Bus.
//
// Bewusst eine winzige Datei neben dem Code und nicht im Datenverzeichnis:
// namenspool.json liegt aus demselben Grund hier, und damit gilt ein Wert auf
// allen Rechnern, sobald er einmal committet ist. Wer auf einem einzelnen
// Rechner abweichen will, setzt die Umgebungsvariable - die schlaegt die Datei.
//
// Reihenfolge: Umgebungsvariable > einstellungen.json > Vorgabe.

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const DATEI = join(dirname(fileURLToPath(import.meta.url)), 'einstellungen.json');

/**
 * Alle bekannten Einstellungen mit Vorgabe, Umgebungsvariable und Erklaerung.
 *
 * Eine Tabelle statt verstreuter Literale: der Leser sieht in einem Blick, was
 * es gibt, und "config" kann sich daraus selbst erzeugen. Ein neuer Wert ist
 * ein weiterer Eintrag, mehr nicht.
 */
export const FELDER = {
  verfall_stunden: {
    vorgabe: 24,
    umgebung: 'CLAUDE_BUS_VERFALL_STUNDEN',
    art: 'zahl',
    text: 'Nach wie vielen Stunden ein unangenommener Auftrag verfällt. 0 schaltet den Verfall ab.',
  },
  zustellung: {
    vorgabe: 'auto',
    umgebung: 'CLAUDE_BUS_ZUSTELLUNG',
    art: 'auswahl',
    werte: ['auto', 'socket', 'stop-hook'],
    text: 'Wie ein Auftrag beim Empfänger ankommt. auto = sofort über den '
      + 'Inbox-Socket, wo es geht (macOS/Linux), sonst Stop-Hook. socket = nur '
      + 'sofort, ohne Rückfall. stop-hook = immer der bisherige Weg.',
  },
};

function lies() {
  if (!existsSync(DATEI)) return {};
  try {
    const d = JSON.parse(readFileSync(DATEI, 'utf8'));
    return d && typeof d === 'object' ? d : {};
  } catch {
    // Eine kaputte Datei darf den Bus nicht anhalten - dann eben Vorgaben.
    return {};
  }
}

/**
 * Liest eine Einstellung.
 *
 * @param {string} schluessel
 * Name aus FELDER.
 * @returns {number|string}
 * Der Wert aus Umgebung, Datei oder Vorgabe, in dieser Reihenfolge.
 */
export function einstellung(schluessel) {
  const feld = FELDER[schluessel];
  if (!feld) throw new Error(`Unbekannte Einstellung: ${schluessel}`);

  const ausUmgebung = process.env[feld.umgebung];
  const roh = ausUmgebung !== undefined && ausUmgebung !== ''
    ? ausUmgebung
    : lies()[schluessel];

  if (roh === undefined || roh === null || roh === '') return feld.vorgabe;

  // Ein unbekannter Wert faellt auf die Vorgabe zurueck statt durchgereicht zu
  // werden. Sonst traegt ein Tippfehler in der Umgebungsvariablen bis in den
  // Zustellweg, wo ihn niemand mehr als Tippfehler erkennt - er sieht dort nur
  // aus wie "keiner der bekannten Faelle trifft zu".
  if (feld.art === 'auswahl') {
    return feld.werte.includes(String(roh)) ? String(roh) : feld.vorgabe;
  }
  if (feld.art !== 'zahl') return roh;

  // Eine unbrauchbare Zahl faellt auf die Vorgabe zurueck statt NaN durch den
  // ganzen Verfallsvergleich zu tragen - dort waere jeder Vergleich falsch und
  // NICHTS wuerde je verfallen, still und ohne Meldung.
  const zahl = Number(roh);
  return Number.isFinite(zahl) && zahl >= 0 ? zahl : feld.vorgabe;
}

/** Alle Einstellungen mit ihrer Herkunft - fuer die Anzeige in "config". */
export function alleEinstellungen() {
  const datei = lies();
  return Object.entries(FELDER).map(([schluessel, feld]) => {
    const ausUmgebung = process.env[feld.umgebung];
    const herkunft = ausUmgebung !== undefined && ausUmgebung !== ''
      ? 'Umgebung'
      : datei[schluessel] !== undefined ? 'Datei' : 'Vorgabe';
    return { schluessel, wert: einstellung(schluessel), herkunft, ...feld };
  });
}

/**
 * Schreibt eine Einstellung in die Datei.
 *
 * @returns {string|null} Fehlertext, oder null bei Erfolg.
 */
export function setzeEinstellung(schluessel, wert) {
  const feld = FELDER[schluessel];
  if (!feld) return `Unbekannte Einstellung '${schluessel}'. Bekannt: ${Object.keys(FELDER).join(', ')}`;
  if (feld.art === 'zahl') {
    const zahl = Number(wert);
    if (!Number.isFinite(zahl) || zahl < 0) return `'${wert}' ist keine gültige Zahl für ${schluessel}.`;
    wert = zahl;
  }
  if (feld.art === 'auswahl' && !feld.werte.includes(String(wert))) {
    return `'${wert}' ist kein gültiger Wert für ${schluessel}. Erlaubt: ${feld.werte.join(', ')}`;
  }
  const d = lies();
  d[schluessel] = wert;
  writeFileSync(DATEI, `${JSON.stringify(d, null, 2)}\n`, 'utf8');
  return null;
}

export const einstellungsDatei = () => DATEI;
