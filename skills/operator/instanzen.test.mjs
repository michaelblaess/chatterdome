// Zwei PID-Dateien, eine Sitzung - was die Liste daraus machen muss.
//
// Es gibt eine Datei je Prozess, aber der Name haengt an der SITZUNG. Liegen
// zwei Prozesse auf einer Kennung, tragen sie zwangslaeufig denselben Namen,
// und der ist als Adresse dann nicht mehr eindeutig. Am 16.08.2026 auf senza
// genau so vorgefunden: PID 1319787 und 3585570 auf Sitzung 2501336f, weil
// der Neustart den alten Prozess nicht beendet hatte.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { jeSitzungEinmal } from './instanzen.mjs';

const ALT = { pid: 1319787, sessionId: '2501336f', startedAt: 1786669206408 };
const NEU = { pid: 3585570, sessionId: '2501336f', startedAt: 1786832345419 };

describe('jeSitzungEinmal', () => {
  test('faltet zwei Prozesse einer Sitzung zusammen', () => {
    assert.equal(jeSitzungEinmal([ALT, NEU]).length, 1);
  });

  test('der juengere gewinnt - er ist der fortgesetzte', () => {
    assert.equal(jeSitzungEinmal([ALT, NEU])[0].pid, NEU.pid);
  });

  test('die Reihenfolge der Dateien entscheidet nicht', () => {
    // readdirSync liefert keine verlaessliche Ordnung.
    assert.equal(jeSitzungEinmal([NEU, ALT])[0].pid, NEU.pid);
  });

  test('verschiedene Sitzungen bleiben nebeneinander stehen', () => {
    const andere = { pid: 99, sessionId: 'andere', startedAt: 5 };
    assert.equal(jeSitzungEinmal([ALT, NEU, andere]).length, 2);
  });

  test('ohne startedAt bleibt trotzdem genau einer uebrig', () => {
    // Eine halb geschriebene Datei darf die Liste nicht verdoppeln.
    const ohne = [{ pid: 1, sessionId: 'x' }, { pid: 2, sessionId: 'x' }];
    assert.equal(jeSitzungEinmal(ohne).length, 1);
  });

  test('eine leere Liste bleibt leer', () => {
    assert.deepEqual(jeSitzungEinmal([]), []);
  });
});
