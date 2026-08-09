// Tests fuer die qualifizierte Adresse "Name@RECHNER".
//
// ANLASS (09.08.2026, von Michael gemeldet): "Petra" lief gleichzeitig auf
// RAINBOW und SENZA. Das ist kein Fehler - der Name ist eine Pacht PRO
// Rechner, und beide Sitzungen haben eigene IDs. Mehrdeutig war nur die
// Adresse "send Petra", die bis dahin still den ersten Treffer nahm.
//
// Der Bezug zum Sendeweg wird ueber die echte Kommandozeile geprueft, nicht
// ueber die Funktion allein: die Zerlegung nuetzt nichts, wenn der Rechner
// danach trotzdem aus dem Flag kommt.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { zerlegeAdresse } from './bus.mjs';

const BUS = join(dirname(fileURLToPath(import.meta.url)), 'bus.mjs');

describe('zerlegeAdresse', () => {
  test('ein blosser Name bleibt unveraendert', () => {
    assert.deepEqual(zerlegeAdresse('Petra'), { name: 'Petra', host: null });
  });

  test('Name@RECHNER wird getrennt, der Rechner gross geschrieben', () => {
    assert.deepEqual(zerlegeAdresse('Petra@senza'), { name: 'Petra', host: 'SENZA' });
  });

  test('der Name behaelt seine Schreibweise', () => {
    // Nur der Rechner wird vereinheitlicht. Namen sind Eigennamen aus dem
    // Pool, und die Namenstabelle vergleicht ohnehin case-insensitiv.
    assert.equal(zerlegeAdresse('Piet@RAINBOW').name, 'Piet');
  });

  test('ein @ am Anfang ist kein Rechner, sondern Teil des Namens', () => {
    // Sonst waere "@senza" ein leerer Name auf SENZA - und der Bus wuerde
    // gegen eine Leerzeichenkette adressieren, statt den Unsinn zu melden.
    assert.deepEqual(zerlegeAdresse('@senza'), { name: '@senza', host: null });
  });

  test('ein @ am Ende nennt keinen Rechner', () => {
    assert.deepEqual(zerlegeAdresse('Petra@'), { name: 'Petra@', host: null });
  });

  test('bei mehreren @ zaehlt das letzte', () => {
    assert.deepEqual(zerlegeAdresse('a@b@SENZA'), { name: 'a@b', host: 'SENZA' });
  });

  test('leere Eingabe wirft nicht', () => {
    assert.deepEqual(zerlegeAdresse(''), { name: '', host: null });
    assert.deepEqual(zerlegeAdresse(undefined), { name: '', host: null });
  });
});

describe('Sendeweg', () => {
  /** Ruft den Bus mit isolierter Ablage auf und gibt stdout+stderr zurueck. */
  function bus(args) {
    const dir = mkdtempSync(join(tmpdir(), 'bus-adresse-'));
    try {
      return execFileSync(process.execPath, [BUS, ...args], {
        encoding: 'utf8',
        env: { ...process.env, CLAUDE_BUS_DIR: dir },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (e) {
      return `${e.stdout || ''}${e.stderr || ''}`;
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }

  test('Adresse und --host duerfen sich nicht widersprechen', () => {
    const aus = bus(['send', 'Petra@SENZA', 'text', '--host', 'RAINBOW']);
    assert.match(aus, /Widerspruch/);
    assert.match(aus, /SENZA/);
    assert.match(aus, /RAINBOW/);
  });

  test('derselbe Rechner in beiden ist kein Widerspruch', () => {
    // Der Aufruf scheitert weiter unten (den Namen traegt niemand), aber NICHT
    // am Widerspruch - genau das ist hier die Aussage.
    const aus = bus(['send', 'Petra@SENZA', 'text', '--host', 'senza']);
    assert.doesNotMatch(aus, /Widerspruch/);
  });

  test('die Hilfe nennt die qualifizierte Form', () => {
    const aus = bus(['send']);
    assert.match(aus, /Name\[@RECHNER\]/);
  });
});
