// Schlaf-Marke im Tab-Titel, gewuenscht am 17.10.2026: alte Tabs sollen auf
// einen Blick auffallen.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { schlafMarke, schwelleStunden, startAusKopf } from './schlaf.mjs';

const STUNDE = 3600 * 1000;

describe('Schlaf-Marke', () => {
  test('juenger als die Schwelle - keine Marke', () => {
    assert.equal(schlafMarke(0, 5 * STUNDE, 6), '');
  });

  test('genau an der Schwelle - Marke', () => {
    assert.equal(schlafMarke(0, 6 * STUNDE, 6), '😴 ');
  });

  test('ohne Startzeit - keine Marke', () => {
    assert.equal(schlafMarke(Number.NaN, 100 * STUNDE, 6), '');
  });

  test('Schwelle 0 schaltet ab', () => {
    assert.equal(schlafMarke(0, 100 * STUNDE, 0), '');
  });
});

describe('Schwelle aus der Umgebung', () => {
  test('fehlt - Standard', () => {
    assert.equal(schwelleStunden(undefined), 6);
  });

  test('deutsches Komma', () => {
    assert.equal(schwelleStunden('1,5'), 1.5);
  });

  test('Unsinn - Standard', () => {
    assert.equal(schwelleStunden('abc'), 6);
  });
});

describe('Start aus dem Dateikopf', () => {
  test('Kopfzeilen ohne Zeitstempel werden uebersprungen', () => {
    const kopf = [
      '{"type":"last-prompt","sessionId":"x"}',
      '{"type":"mode","mode":"normal"}',
      '{"parentUuid":null,"timestamp":"2026-10-17T15:00:00.000Z"}',
      '{"parentUuid":"a","timestamp":"2026-10-17T16:00:00.000Z"}',
    ].join('\n');
    assert.equal(startAusKopf(kopf), Date.parse('2026-10-17T15:00:00.000Z'));
  });

  test('kein Zeitstempel - NaN', () => {
    assert.ok(Number.isNaN(startAusKopf('{"type":"mode"}')));
  });
});
