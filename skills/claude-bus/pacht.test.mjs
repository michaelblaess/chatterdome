// Prueft die drei Gegenmittel gegen den Vorfall vom 07.08.2026 einzeln.
//
// Jede Pruefung ist so gebaut, dass sie SCHEITERN kann: sie legt den Zustand
// selbst an, in dem der Fehler auftrat, und misst danach. Ein Test, der nur
// nachsieht, ob eine Spalte existiert, haette den Fehler nicht gefunden - die
// Spalte gab es ja nicht, und trotzdem lief alles scheinbar richtig.
//
// Aufruf: node --test "skills/claude-bus/*.test.mjs"
// Das Verzeichnis als Argument scheitert unter Node 24.18.0 auf Windows mit
// "Cannot find module" (geprueft am 10.08.2026 in bash und PowerShell).

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  oeffne, schreibe, auftrag, cursorLesen, cursorSetzen, ereignisseAb, letzteId,
} from './speicher.mjs';
import { pachtBeginnt, pachtEndet, pachtGehtUeber, verfallen, fehlgeleitete } from './pacht.mjs';

const SITZUNG_ALT = '4d0c0ab0-935e-430a-a670-e9aaeae7e6fa';
const SITZUNG_NEU = 'aaaabbbb-1111-2222-3333-444455556666';

/** Legt eine frische Datenbank in einem Wegwerf-Verzeichnis an. */
function frisch(t) {
  const ordner = mkdtempSync(join(tmpdir(), 'bus-test-'));
  const db = oeffne(ordner);
  t.after(() => {
    db.close();
    rmSync(ordner, { recursive: true, force: true });
  });
  return db;
}

/**
 * Legt einen Auftrag ab.
 *
 * @param vor
 * Alter in Stunden. Der Zeitstempel wird zurueckdatiert, weil sich der Verfall
 * sonst nur mit echtem Warten pruefen liesse.
 */
function auftragAblegen(db, { id, an, anSession = null, bindung = null, vor = 0 }) {
  const ts = new Date(Date.now() - vor * 3600_000).toISOString();
  schreibe(db, {
    auftrag_id: id, ts, art: 'auftrag', host: 'TESTRECHNER', von_host: 'TESTRECHNER',
    von: 'Chatterdome', von_session: '', an, an_session: anSession, bindung,
    zustand: 'submitted', topic: 'allgemein', text: 'gib mir das aktuelle Datum',
    quittung_erwartet: 1,
  });
}

describe('Pacht endet mit der Sitzung', () => {
  test('nimmt einen an die Sitzung gebundenen Auftrag zurueck', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'a1', an: 'Marga', anSession: SITZUNG_ALT, bindung: 'session' });

    const zurueck = pachtEndet(db, SITZUNG_ALT, 'Marga');

    assert.deepEqual(zurueck, ['a1']);
    const nachher = auftrag(db, 'a1');
    assert.equal(nachher.zustand, 'cancelled');
  });

  test('laesst einen Rollenauftrag ausdruecklich stehen', (t) => {
    const db = frisch(t);
    // Kein an_session: ausdruecklich an den NAMEN adressiert. So einer soll
    // den Namenswechsel ueberleben, sonst waere --rolle sinnlos.
    auftragAblegen(db, { id: 'a2', an: 'Marga', bindung: 'rolle' });

    const zurueck = pachtEndet(db, SITZUNG_ALT, 'Marga');

    assert.deepEqual(zurueck, []);
    assert.equal(auftrag(db, 'a2').zustand, 'submitted');
  });

  test('schreibt eine Quittung, die der Absender sehen kann', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'a3', an: 'Marga', anSession: SITZUNG_ALT, bindung: 'session' });

    pachtEndet(db, SITZUNG_ALT, 'Marga');

    const q = db.prepare("SELECT * FROM ereignis WHERE art = 'quittung' AND auftrag_id = 'a3'").get();
    assert.equal(q.status, 410);
    assert.equal(q.an, 'Chatterdome', 'die Quittung muss an den Absender gehen');
    assert.match(q.notiz, /Marga/);
  });
});

describe('Verfall', () => {
  test('nimmt weg, was laenger als die Frist offen liegt', (t) => {
    const db = frisch(t);
    // Genau der Vorfall: vier Tage alt, nie angenommen.
    auftragAblegen(db, { id: 'alt', an: 'Marga', vor: 96 });

    const weg = verfallen(db, 24);

    assert.deepEqual(weg, ['alt']);
    assert.equal(auftrag(db, 'alt').zustand, 'expired');
  });

  test('laesst frische Auftraege in Ruhe', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'neu', an: 'Marga', vor: 2 });

    assert.deepEqual(verfallen(db, 24), []);
    assert.equal(auftrag(db, 'neu').zustand, 'submitted');
  });

  test('Frist 0 schaltet den Verfall ab', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'uralt', an: 'Marga', vor: 10_000 });

    assert.deepEqual(verfallen(db, 0), []);
    assert.equal(auftrag(db, 'uralt').zustand, 'submitted');
  });

  test('greift auch bei einem Auftrag, der schon angenommen wurde', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'haengt', an: 'Marga', vor: 96 });
    schreibe(db, {
      auftrag_id: 'haengt', art: 'quittung', host: 'TESTRECHNER',
      von: 'Marga', an: 'Chatterdome', zustand: 'working', status: 202,
    });

    // 'working' zaehlt zu den offenen Zustaenden - eine Instanz, die einen
    // Auftrag annimmt und dann verschwindet, darf ihn nicht ewig blockieren.
    assert.deepEqual(verfallen(db, 24), ['haengt']);
  });
});

describe('Lesezeiger beim Sitzungsstart', () => {
  test('startet am Ende des Protokolls, nicht bei null', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'vorher1', an: 'Marga' });
    auftragAblegen(db, { id: 'vorher2', an: 'Schmid' });

    const stand = pachtBeginnt(db, SITZUNG_NEU);

    assert.equal(stand, letzteId(db));
    assert.equal(cursorLesen(db, SITZUNG_NEU), 2, 'sonst gilt die ganze Historie als neu');
  });

  test('fasst einen vorhandenen Zeiger nicht an', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'x1', an: 'Marga' });
    cursorSetzen(db, SITZUNG_NEU, 1);
    auftragAblegen(db, { id: 'x2', an: 'Marga' });

    // Eine fortgesetzte Sitzung (claude --resume behaelt die Session-ID) wuerde
    // sonst ihre ungelesenen Nachrichten verlieren.
    assert.equal(pachtBeginnt(db, SITZUNG_NEU), null);
    assert.equal(cursorLesen(db, SITZUNG_NEU), 1);
  });
});

describe('Pacht geht ueber (/clear)', () => {
  test('offener Auftrag und Lesezeiger wandern zur neuen Session-ID', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'gelesen', an: 'Patrick' });
    cursorSetzen(db, SITZUNG_ALT, 1);
    auftragAblegen(db, { id: 'c1', an: 'Patrick', anSession: SITZUNG_ALT, bindung: 'session' });

    assert.deepEqual(pachtGehtUeber(db, SITZUNG_ALT, SITZUNG_NEU), ['c1']);

    // Nicht zurueckgenommen, sondern umgehaengt - der Empfaenger arbeitet im
    // selben Fenster unter demselben Namen weiter.
    assert.equal(auftrag(db, 'c1').zustand, 'submitted');
    assert.equal(auftrag(db, 'c1').an_session, SITZUNG_NEU);
    // Der Zeiger steht da, wo die alte Sitzung aufgehoert hat. Am Ende des
    // Protokolls waere c1 als gelesen durchgerutscht.
    assert.equal(cursorLesen(db, SITZUNG_NEU), 1);
    // Die Zustellung liest die Ereignisse, nicht die Auftraege.
    const zugestellt = ereignisseAb(db, 1).filter((e) => e.an_session === SITZUNG_NEU);
    assert.deepEqual(zugestellt.map((e) => e.auftrag_id), ['c1']);
  });

  test('ohne alten Zeiger startet die neue Sitzung am Ende', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'h1', an: 'Patrick' });
    auftragAblegen(db, { id: 'h2', an: 'Patrick' });

    pachtGehtUeber(db, SITZUNG_ALT, SITZUNG_NEU);

    assert.equal(cursorLesen(db, SITZUNG_NEU), letzteId(db), 'sonst gilt die ganze Historie als neu');
  });

  test('abgeschlossene Auftraege bleiben bei der alten Sitzung', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'fertig', an: 'Patrick', anSession: SITZUNG_ALT, bindung: 'session' });
    pachtEndet(db, SITZUNG_ALT, 'Patrick');

    assert.deepEqual(pachtGehtUeber(db, SITZUNG_ALT, SITZUNG_NEU), []);
    assert.equal(auftrag(db, 'fertig').an_session, SITZUNG_ALT);
  });
});

describe('Diagnose', () => {
  test('meldet einen Auftrag, dessen Name inzwischen neu vergeben ist', (t) => {
    const db = frisch(t);
    auftragAblegen(db, { id: 'd1', an: 'Marga', anSession: SITZUNG_ALT, bindung: 'session' });

    const namen = { [SITZUNG_NEU]: 'Marga' };
    assert.deepEqual(fehlgeleitete(db, namen).map((a) => a.auftrag_id), ['d1']);

    // Gegenprobe: traegt noch dieselbe Sitzung den Namen, ist nichts zu melden.
    assert.deepEqual(fehlgeleitete(db, { [SITZUNG_ALT]: 'Marga' }), []);
  });
});
