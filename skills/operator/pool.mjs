// Namenspool: eine Quelle fuer Operator, Starter und SessionStart-Hook.
//
// Die Datei namenspool.json haelt mehrere Motive und merkt sich, welches aktiv
// ist. Ein neues Motiv ist ein weiterer Eintrag unter "pools", mehr nicht.
//
// Daneben liegt optional namenspool.local.json im selben Format, per
// .gitignore aus dem Repo gehalten. Dort stehen Motive, die nicht
// mitgeliefert werden duerfen (Figuren geschuetzter Werke), und die Wahl des
// aktiven Motivs - ein Motivwechsel veraendert damit keine versionierte Datei.
//
// Bewusst als eigenes Modul: die Ladelogik lag vorher dreifach in operator.mjs,
// starte.mjs und whoami.mjs. Genau so faengt Auseinanderdriften an - der Pool
// war schon einmal doppelt vorhanden (PowerShell und Node), bevor er hierher
// ausgelagert wurde.

import { readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir, hostname } from 'node:os';

const DATEI = join(dirname(fileURLToPath(import.meta.url)), 'namenspool.json');
const LOKAL = join(dirname(fileURLToPath(import.meta.url)), 'namenspool.local.json');

// Greift, wenn die Datei fehlt oder unlesbar ist. Lieber ein paar Namen als
// eine Instanz ohne Namen.
const NOTNAGEL = ['Therese', 'Agatha', 'Jeanne', 'Lucia', 'Franziskus'];

function liesDatei(datei) {
  try {
    return JSON.parse(readFileSync(datei, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Mitgelieferte und lokale Datei zusammengefuehrt. Lokale Motive ergaenzen
 * die mitgelieferten und ersetzen gleichnamige, das lokale "aktiv" gewinnt.
 * Fehlt die lokale Datei, ist das Ergebnis genau die mitgelieferte.
 */
function lies() {
  const d = liesDatei(DATEI);
  const lokal = liesDatei(LOKAL);
  if (!lokal) return d;
  if (!d) return lokal;
  // Altes Format ohne Motive: dann bleibt die lokale Datei aussen vor, ein
  // Mischformat waere schwerer zu durchschauen als der Verzicht.
  if (Array.isArray(d.namen)) return d;
  return {
    ...d,
    aktiv: lokal.aktiv || d.aktiv,
    reserviert: [...new Set([...reservierte(d), ...reservierte(lokal)])],
    pools: { ...(d.pools || {}), ...(lokal.pools || {}) },
  };
}

/**
 * Reservierte Namen stehen vor jedem Motiv und gelten unabhaengig davon, was
 * gerade aktiv ist. "Operator" faellt damit an die erste Instanz, ohne dass er
 * in jeder Motivliste einzeln gepflegt werden muss - genau die Doppelpflege,
 * an der der Pool schon einmal auseinandergelaufen ist.
 */
function reservierte(d) {
  return d && Array.isArray(d.reserviert) ? d.reserviert : [];
}

/**
 * Liefert das aktive Motiv als { schluessel, motiv, namen }.
 * Versteht auch das alte Format (flaches "namen"-Array ohne Motive).
 */
export function aktivesMotiv() {
  const d = lies();
  // Unlesbare Datei: dann gibt es auch keine reservierten Namen. Das Feld
  // trotzdem setzen, damit Aufrufer bedenkenlos .length lesen koennen.
  if (!d) return { schluessel: 'notnagel', motiv: 'Notnagel', namen: NOTNAGEL, reserviert: [] };
  const vorn = reservierte(d);

  // Altes Format: { motiv, namen }
  if (Array.isArray(d.namen)) {
    return { schluessel: 'standard', motiv: d.motiv || 'Standard', namen: [...vorn, ...d.namen], reserviert: vorn };
  }

  const pools = d.pools || {};
  const schluessel = d.aktiv && pools[d.aktiv] ? d.aktiv : Object.keys(pools)[0];
  const p = pools[schluessel];
  if (!p || !Array.isArray(p.namen) || !p.namen.length) {
    return { schluessel: 'notnagel', motiv: 'Notnagel', namen: [...vorn, ...NOTNAGEL], reserviert: vorn };
  }
  return { schluessel, motiv: p.motiv || schluessel, namen: [...vorn, ...p.namen], reserviert: vorn };
}

/** Nur die Namen des aktiven Motivs. */
export function ladePool() {
  return aktivesMotiv().namen;
}

/**
 * Rechnername wie im Buspfad. COMPUTERNAME bevorzugen, weil hostname()
 * Suffixe wie .local liefern kann.
 */
export function rechnername() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

/**
 * Die Zuordnung Session-ID zu Name. Nur lesend - vergeben wird ausschliesslich
 * im SessionStart-Hook, damit nicht mehrere Stellen gleichzeitig schreiben.
 */
export function ladeNamen() {
  try {
    const datei = join(homedir(), '.claude', 'bus', rechnername(), 'namen.json');
    return JSON.parse(readFileSync(datei, 'utf8'));
  } catch {
    return {};
  }
}

/**
 * Alle Namen aller Motive, das aktive zuerst. Letzte Reserve, wenn selbst nach
 * dem Aufraeumen kein Name des aktiven Motivs mehr frei ist - dann ist ein
 * Heiligenname immer noch besser als "Snorre-21".
 */
export function alleNamen() {
  const d = lies();
  const { namen: aktiv } = aktivesMotiv();
  const uebrige = d && d.pools
    ? Object.values(d.pools).flatMap((p) => (Array.isArray(p.namen) ? p.namen : []))
    : [];
  // Set haelt die Reihenfolge der ersten Einfuegung, das aktive Motiv bleibt
  // damit vorn, auch wenn ein Name in mehreren Motiven vorkommt.
  return [...new Set([...aktiv, ...uebrige])];
}

/** Alle verfuegbaren Motive als [{ schluessel, motiv, anzahl, aktiv }]. */
export function alleMotive() {
  const d = lies();
  if (!d || !d.pools) return [aktivesMotiv()].map((m) => ({ ...m, anzahl: m.namen.length, aktiv: true }));
  return Object.entries(d.pools).map(([schluessel, p]) => ({
    schluessel,
    motiv: p.motiv || schluessel,
    anzahl: Array.isArray(p.namen) ? p.namen.length : 0,
    aktiv: schluessel === d.aktiv,
  }));
}

/**
 * Schaltet das aktive Motiv um. Wirkt nur auf Namen, die noch NICHT vergeben
 * sind - laufende Instanzen behalten ihren Namen, sonst waere die Uebersicht
 * mitten im Betrieb wertlos.
 */
export function setzeMotiv(schluessel) {
  const d = lies();
  if (!d || !d.pools || !d.pools[schluessel]) return null;
  // Die Wahl landet in der lokalen Datei, die mitgelieferte bleibt unberuehrt.
  // Vorher schrieb setzeMotiv die ganze zusammengefuehrte Sicht zurueck - mit
  // der lokalen Datei hiesse das, geschuetzte Motive ins Repo zu kopieren.
  const lokal = liesDatei(LOKAL) || {};
  lokal.aktiv = schluessel;
  writeFileSync(LOKAL, JSON.stringify(lokal, null, 2) + '\n', 'utf8');
  return { schluessel, motiv: d.pools[schluessel].motiv || schluessel, namen: d.pools[schluessel].namen };
}
