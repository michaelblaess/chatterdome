// Die Datenbank unter Nebenlaeufigkeit.
//
// Anlass ist ein echter Vorfall vom 21.08.2026: ein "bus.mjs verlauf" brach
// mit "database is locked" ab, waehrend eine andere Instanz gerade ihre
// Quittung schrieb. Der Fehler trug errcode 261 - SQLITE_BUSY_RECOVERY, also
// die Wiederherstellung des WAL-Index, bei der der busy_timeout nicht traegt.
// Ein zweiter Versuch von Hand ging sofort durch.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { oeffne, istBusy } from './speicher.mjs';

const HIER = dirname(fileURLToPath(import.meta.url));

// Jeder Test schliesst seine Verbindung, bevor er aufraeumt: unter Windows
// laesst sich eine offene SQLite-Datei nicht loeschen, rmSync scheitert dann
// mit EPERM - und zwar im finally, wo es wie ein Fehler des Tests aussieht.
function tempDir() {
  return mkdtempSync(join(tmpdir(), 'bus-speicher-'));
}

/**
 * Raeumt ein Testverzeichnis weg, ohne den Test daran scheitern zu lassen.
 *
 * Unter Windows haelt SQLite die Datei samt -wal und -shm noch einen Moment,
 * nachdem der letzte Prozess sie losgelassen hat. rmSync scheitert dann mit
 * EPERM - und weil das im finally passiert, faellt ein voellig gesunder Test
 * um. Das Temp-Verzeichnis raeumt notfalls das Betriebssystem auf, der Befund
 * des Tests ist wichtiger als ein sauberer Papierkorb.
 */
function wegwerfen(pfad) {
  try {
    rmSync(pfad, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 });
  } catch { /* siehe oben */ }
}

describe('istBusy', () => {
  // Die Unterart steht in den oberen Bits, der Grundcode in den unteren acht.
  test('erkennt den blanken BUSY-Code', () => {
    assert.equal(istBusy({ errcode: 5 }), true);
  });

  test('erkennt SQLITE_BUSY_RECOVERY - genau der Fall vom 21.08.', () => {
    assert.equal(istBusy({ errcode: 261 }), true);
  });

  test('erkennt SNAPSHOT und TIMEOUT', () => {
    assert.equal(istBusy({ errcode: 517 }), true);
    assert.equal(istBusy({ errcode: 773 }), true);
  });

  test('ein anderer Fehler ist kein BUSY', () => {
    // 14 ist "unable to open database file" - da hilft kein Wiederholen, und
    // fuenf Versuche wuerden den Abbruch nur verlangsamen.
    assert.equal(istBusy({ errcode: 14 }), false);
    assert.equal(istBusy({ errcode: 1 }), false);
  });

  test('kein Fehlerobjekt ist kein BUSY', () => {
    assert.equal(istBusy(null), false);
    assert.equal(istBusy(undefined), false);
    assert.equal(istBusy({}), false);
  });
});

describe('Oeffnen unter fremder Sperre', () => {
  /**
   * Startet einen ZWEITEN Prozess, der eine Schreibsperre haelt und sie nach
   * der angegebenen Zeit freigibt.
   *
   * Zwei Prozesse sind Pflicht, nicht Zierrat: die Pause in oeffne() blockiert
   * synchron, im selben Prozess kaeme ein Timer also nie zum Zug. Genau daran
   * ist die erste Fassung dieses Tests gescheitert.
   */
  function halterStarten(datei, haltenMs) {
    const skript = join(HIER, 'halter-fuer-test.mjs');
    writeFileSync(skript, [
      "import { DatabaseSync } from 'node:sqlite';",
      'const db = new DatabaseSync(process.argv[2]);',
      "db.exec('PRAGMA busy_timeout = 5000; CREATE TABLE IF NOT EXISTS t(x);');",
      "db.exec('BEGIN IMMEDIATE; INSERT INTO t VALUES (1);');",
      "process.stdout.write('bereit\\n');",
      "setTimeout(() => db.exec('COMMIT'), Number(process.argv[3]));",
      '',
    ].join('\n'), 'utf8');

    const kind = spawn(process.execPath, [skript, datei, String(haltenMs)], { stdio: ['ignore', 'pipe', 'ignore'] });
    return {
      kind,
      skript,
      bereit: new Promise((fertig) => kind.stdout.once('data', fertig)),
    };
  }

  test('eine kurz gehaltene Sperre wird ausgesessen', async () => {
    const dir = tempDir();
    const halter = halterStarten(join(dir, 'bus.db'), 700);
    try {
      await halter.bereit;
      // Die Datei steht absichtlich noch nicht auf WAL: nur der WECHSEL
      // braucht den exklusiven Zugriff, und genau dann beisst die fremde
      // Sperre. Auf einer bereits umgestellten Datei ist das Pragma ein
      // No-Op und liefe auch ohne Wiederholung durch.
      const db = oeffne(dir);
      assert.equal(db.prepare('PRAGMA journal_mode').get().journal_mode, 'wal');
      assert.equal(db.prepare('PRAGMA busy_timeout').get().timeout, 5000);
      db.close();
    } finally {
      // Auf das Ende des Halters WARTEN, nicht nur toeten: Windows gibt die
      // Datei erst frei, wenn der Prozess wirklich weg ist, und ein rmSync
      // eine Millisekunde spaeter scheitert mit EPERM - im finally, wo es wie
      // ein Fehler des Tests aussieht. maxRetries deckt den Rest ab.
      const beendet = new Promise((fertig) => halter.kind.once('exit', fertig));
      halter.kind.kill();
      await beendet;
      try { rmSync(halter.skript, { force: true }); } catch { /* siehe wegwerfen */ }
      wegwerfen(dir);
    }
  });

  test('ohne Sperre kostet das Oeffnen nichts', () => {
    // Gegenstueck zum Test darueber: die Wiederholung darf den Normalfall
    // nicht ausbremsen.
    // Erst anlegen, dann messen: das erste Oeffnen legt Datei und Schema an und
    // brauchte auf dem Windows-Runner mal 530, mal 1.585 ms (29.09.2026). Das ist
    // Kaltstart, keine Wartepause - gemessen werden soll nur die Wiederholung.
    const dir = tempDir();
    try {
      oeffne(dir).close();
      const start = Date.now();
      oeffne(dir).close();
      assert.ok(Date.now() - start < 500, `${Date.now() - start} ms`);
    } finally {
      wegwerfen(dir);
    }
  });

  test('ein anderer Fehler kommt sofort heraus', () => {
    // Ein Verzeichnis, das es nicht gibt: SQLITE_CANTOPEN. Wuerde die
    // Wiederholung auch das schlucken, waere jeder Tippfehler im Pfad ein
    // Zweisekunden-Abbruch.
    const start = Date.now();
    assert.throws(() => oeffne(join(tmpdir(), 'gibt-es-nicht-4711', 'tiefer')));
    assert.ok(Date.now() - start < 500, `${Date.now() - start} ms`);
  });
});

describe('Schema', () => {
  test('WAL und busy_timeout stehen nach dem Oeffnen', () => {
    const dir = tempDir();
    try {
      const db = oeffne(dir);
      assert.equal(db.prepare('PRAGMA journal_mode').get().journal_mode, 'wal');
      assert.equal(db.prepare('PRAGMA busy_timeout').get().timeout, 5000);
      db.close();
    } finally {
      wegwerfen(dir);
    }
  });

  test('zweimal oeffnen ist unschaedlich', () => {
    const dir = tempDir();
    try {
      oeffne(dir).close();
      const db = oeffne(dir);
      assert.equal(db.prepare('SELECT count(*) c FROM ereignis').get().c, 0);
      db.close();
    } finally {
      wegwerfen(dir);
    }
  });
});
