// Ermittelt den Namen der aufrufenden Claude-Instanz und vergibt ihn beim
// ersten Mal aus dem Pool.
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
import { ladePool, alleNamen } from './pool.mjs';
import { ladeInstanzen } from './instanzen.mjs';

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

// ladePool kommt aus pool.mjs, damit Hook, Operator und Starter dasselbe
// aktive Motiv sehen.

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
 * Sucht den naechsten Namen in drei Stufen. Michaels Vorgabe: erst den Pool
 * weiter abarbeiten, erst bei Erschoepfung aufraeumen, und dann wird es
 * interessant.
 *
 * 1. Ein freier Name des aktiven Motivs.
 * 2. Beendete Sitzungen aufraeumen und noch einmal schauen. Kostet den Aufruf
 *    von "claude agents --json" (knapp eine Sekunde), deshalb erst hier und
 *    nicht bei jedem Sitzungsstart.
 * 3. Ein Name aus einem anderen Motiv - immer noch besser als eine Nummer.
 *
 * Bleibt alles erfolglos, laufen tatsaechlich mehr Instanzen als der gesamte
 * Namensbestand hergibt. Dann wird durchnummeriert.
 *
 * @param tabelle
 * Zuordnung Session-ID zu Name. Wird in Stufe 2 direkt bereinigt.
 * @param vergeben
 * Bereits vergebene Namen.
 * @param pool
 * Namen des aktiven Motivs.
 * @param eigeneSession
 * Die eigene Session-ID, die beim Aufraeumen nie entfernt werden darf.
 */
function vergibNaechsten(tabelle, vergeben, pool, eigeneSession) {
  const frei = pool.filter((n) => !vergeben.has(n));
  if (frei.length > 0) return frei[0];

  // Stufe 2: beendete Sitzungen entfernen. Eine leere Instanzliste bedeutet
  // NICHT, dass nichts laeuft - sie kann auch aus einem Fehler stammen. Wer
  // daraus loescht, nimmt allen laufenden Instanzen ihren Namen.
  const laufende = ladeInstanzen({ timeout: 5000 });
  if (laufende.length > 0) {
    const aktiv = new Set(laufende.map((i) => i.sessionId));
    for (const sid of Object.keys(tabelle)) {
      if (sid !== eigeneSession && !aktiv.has(sid)) delete tabelle[sid];
    }
    const nachDemRaeumen = new Set(Object.values(tabelle));
    const wiederFrei = pool.filter((n) => !nachDemRaeumen.has(n));
    if (wiederFrei.length > 0) return wiederFrei[0];
    vergeben = nachDemRaeumen;
  }

  // Stufe 3: anderes Motiv.
  const ausAnderemMotiv = alleNamen().filter((n) => !vergeben.has(n));
  if (ausAnderemMotiv.length > 0) return ausAnderemMotiv[0];

  return `${pool[0]}-${Object.keys(tabelle).length + 1}`;
}

const sessionId = process.env.CLAUDE_CODE_SESSION_ID;
if (!sessionId) process.exit(1);

try {
  const datei = join(datenVerzeichnis(), 'namen.json');
  const tabelle = ladeNamen(datei);

  if (tabelle[sessionId]) {
    process.stdout.write(tabelle[sessionId]);
    process.exit(0);
  }

  const pool = ladePool();
  const vergeben = new Set(Object.values(tabelle));

  // Wurde die Instanz ueber starte.mjs gestartet, steht der Name schon fest und
  // klebt bereits in der Terminal-Titelleiste. Dann diesen uebernehmen, statt
  // einen zweiten zu vergeben.
  const vorgabe = process.env.CLAUDE_INSTANZ_NAME;
  let name;
  if (vorgabe && /^[A-Za-z0-9-]+$/.test(vorgabe) && !vergeben.has(vorgabe)) {
    name = vorgabe;
  } else {
    name = vergibNaechsten(tabelle, vergeben, pool, sessionId);
  }

  tabelle[sessionId] = name;
  writeFileSync(datei, JSON.stringify(tabelle, null, 1), 'utf8');
  process.stdout.write(name);
} catch {
  process.exit(1);
}
