// Ermittelt den Namen der aufrufenden Claude-Instanz und vergibt ihn beim
// ersten Mal aus dem Pool. Wechselt im selben Fenster nur die Session-ID
// (/clear), geht der Name mit - siehe fenster.mjs.
//
// Bewusst Node und nicht PowerShell: der SessionStart-Hook laeuft als bash auf
// allen Rechnern (Windows/msys, Linux, spaeter macOS), und Node ist dort
// ohnehin vorhanden. PowerShell waere unter Linux nicht garantiert.
//
// Ausgabe auf stdout: nur der Name, ohne Zeilenumbruch-Zierrat.
// Bei jedem Problem wird still mit Code 1 beendet - der Hook faellt dann
// einfach aus, statt eine Sitzung mit Fehlermeldungen zu starten.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { vergibNamen } from './vergabe.mjs';
import {
  ladeFenster, merkeFenster, prozessStart, speichereFenster, vorgaengerSitzung,
} from './fenster.mjs';
import { laeuft } from './prozess.mjs';

function rechnername() {
  // COMPUTERNAME bevorzugen, damit der Pfad exakt dem entspricht, was das
  // PowerShell-Skript benutzt. hostname() kann Suffixe wie .local liefern.
  const n = process.env.COMPUTERNAME || hostname().split('.')[0];
  return n.toUpperCase();
}

function datenVerzeichnis() {
  const dir = join(homedir(), '.claude', 'bus', rechnername());
  mkdirSync(dir, { recursive: true });
  return dir;
}

// Die Auswahl selbst steht in vergabe.mjs, damit Hook und Starter nicht
// auseinanderlaufen - genau daran ist am 10.08.2026 ein "Operator-22"
// entstanden, obwohl der Pool halb leer war.

function ladeNamen(pfad) {
  if (!existsSync(pfad)) return {};
  try {
    return JSON.parse(readFileSync(pfad, 'utf8'));
  } catch {
    // Kaputte Datei nicht eskalieren: lieber neu vergeben als die Sitzung
    // mit einem Fehler starten.
    return {};
  }
}

/**
 * Setzt den Lesezeiger einer frisch benannten Sitzung ans Ende des Busprotokolls.
 *
 * WARUM HIER: der Lesezeiger haengt an der Session-ID, die Adresse eines
 * Auftrags aber am Namen. Eine neue Sitzung startet ohne Zeiger, also bei 0 -
 * und bekommt damit die gesamte Historie ihres frisch geerbten Namens als
 * "neu" vorgesetzt. Am 07.08.2026 hat eine neue Marga auf diesem Weg einen
 * vier Tage alten Auftrag an ihre Vorgaengerin abgearbeitet.
 *
 * Der Sitzungsstart ist der einzige richtige Zeitpunkt dafuer. Wer den Zeiger
 * erst beim ersten Buszugriff setzt, ueberspringt alles, was in der Zwischenzeit
 * eingetroffen ist.
 *
 * Fehler werden geschluckt: eine Sitzung ohne Namen ist schlimmer als eine mit
 * ungenauem Lesezeiger, und der Bus kann aus guten Gruenden blockiert sein
 * (Pfad nicht isoliert).
 *
 * Bewusst ein dynamisches import() statt eines Imports am Dateikopf: node:sqlite
 * wird damit nur geladen, wenn wirklich ein Name vergeben oder uebernommen
 * wird. Eine fortgesetzte Sitzung verlaesst dieses Skript weiter oben und
 * zahlt nichts.
 */
async function pachtWechseln(sid, freigegeben, uebernommenVon) {
  try {
    const bus = new URL('../claude-bus/', import.meta.url);
    const { oeffne } = await import(new URL('speicher.mjs', bus).href);
    const { pachtBeginnt, pachtEndet, pachtGehtUeber } = await import(new URL('pacht.mjs', bus).href);
    const db = oeffne(datenVerzeichnis());
    // Erst die alten Postfaecher schliessen, dann den eigenen Zeiger setzen.
    // Andersherum stuenden die Ruecknahme-Ereignisse hinter meinem Zeiger und
    // ich bekaeme sie als "neu" gemeldet.
    for (const [alteSitzung, alterName] of freigegeben) pachtEndet(db, alteSitzung, alterName);
    // Nach /clear ist es dasselbe Fenster unter neuer Session-ID: dann geht das
    // Postfach mit, statt neu zu beginnen.
    if (uebernommenVon) {
      pachtGehtUeber(db, uebernommenVon, sid);
    } else {
      pachtBeginnt(db, sid);
    }
    db.close();
  } catch { /* siehe Kommentarkopf */ }
}

/**
 * Stellt fest, welche Sitzung zuvor in diesem Fenster lief, und traegt die
 * jetzige ein.
 *
 * Geschrieben wird nur bei einer Aenderung: der Hook laeuft bei jedem
 * Sitzungsstart, auch bei compact und resume, wo sich nichts bewegt.
 *
 * Fehler werden geschluckt und ergeben "kein Vorgaenger" - dann wird wie vor
 * dem 02.10.2026 ein neuer Name vergeben, statt die Sitzung ohne Namen zu
 * starten.
 *
 * @returns {string|null} Session-ID des Vorgaengers oder null.
 */
function fensterWechsel(sid) {
  try {
    const pid = process.env.CLAUDE_PID;
    const start = pid ? prozessStart(pid) : '';
    if (!start) return null;
    const verzeichnis = datenVerzeichnis();
    const fenster = ladeFenster(verzeichnis);
    const vorher = JSON.stringify(fenster);
    const vorgaenger = vorgaengerSitzung(fenster, pid, start, sid);
    merkeFenster(fenster, pid, start, sid, laeuft);
    if (JSON.stringify(fenster) !== vorher) speichereFenster(verzeichnis, fenster);
    return vorgaenger;
  } catch {
    return null;
  }
}

const sessionId = process.env.CLAUDE_CODE_SESSION_ID;
if (!sessionId) process.exit(1);

try {
  const datei = join(datenVerzeichnis(), 'namen.json');
  const tabelle = ladeNamen(datei);
  const vorgaenger = fensterWechsel(sessionId);

  if (tabelle[sessionId]) {
    process.stdout.write(tabelle[sessionId]);
    process.exit(0);
  }

  // Wurde die Instanz ueber starte.mjs gestartet, steht der Name schon fest und
  // klebt bereits in der Terminal-Titelleiste. Dann diesen uebernehmen, statt
  // einen zweiten zu vergeben.
  const { name, freigegeben, uebernommenVon } = vergibNamen({
    tabelle,
    eigeneSession: sessionId,
    vorgabe: process.env.CLAUDE_INSTANZ_NAME,
    vorgaenger,
  });

  tabelle[sessionId] = name;
  writeFileSync(datei, JSON.stringify(tabelle, null, 1), 'utf8');
  await pachtWechseln(sessionId, freigegeben, uebernommenVon);
  process.stdout.write(name);
} catch {
  process.exit(1);
}
