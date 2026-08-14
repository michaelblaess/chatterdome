// Was sich am Neustart ohne Desktop pruefen laesst.
//
// Das Fenster selbst kann hier niemand oeffnen - dafuer braucht es einen
// angemeldeten Benutzer, und auf einem CI-Laeufer gibt es den nicht. Geprueft
// wird deshalb, was davor passiert: die Befehlszeile, die Ablage der Parameter
// und die Weigerung ohne Sitzungskennung. Der Fenstertest lief von Hand auf
// senza, siehe Kommentar in neustart.mjs.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { homedir } from 'node:os';

import {
  auftragsDatei, ergebnisDatei, neustartHier, resumeBefehl,
} from './neustart.mjs';

describe('Befehlszeile fuer das neue Fenster', () => {
  test('setzt die Sitzung mit --resume fort', () => {
    assert.match(resumeBefehl('abc-123'), /--resume abc-123$/);
  });

  test('exec statt eines zweiten Prozesses', () => {
    // Sonst haengt eine bash zwischen Fenster und Sitzung, die beim Beenden
    // von claude als leeres Fenster stehen bliebe.
    assert.match(resumeBefehl('abc-123'), /^exec /);
  });
});

describe('Weigerungen', () => {
  test('ohne Sitzungskennung wird nichts geoeffnet', () => {
    const grund = neustartHier('');
    assert.match(grund, /Sitzungskennung/);
  });

  test('die Weigerung kommt als Text, nicht als Ausnahme', () => {
    // Der Aufrufer sitzt womoeglich am anderen Ende einer ssh-Leitung. Eine
    // Ausnahme dort ist ein Stacktrace, ein Satz ist eine Antwort.
    assert.equal(typeof neustartHier(''), 'string');
  });
});

describe('Ablage der Parameter', () => {
  test('Auftrag und Ergebnis liegen im Datenverzeichnis des Rechners', () => {
    for (const pfad of [auftragsDatei(), ergebnisDatei()]) {
      assert.ok(pfad.startsWith(homedir()), pfad);
      assert.match(pfad, /[\\/]\.claude[\\/]bus[\\/]/);
    }
  });

  test('Auftrag und Ergebnis sind zwei verschiedene Dateien', () => {
    // Sonst ueberschriebe die Antwort die Frage, und ein zweiter Lauf faende
    // seinen eigenen alten Erfolg vor.
    assert.notEqual(auftragsDatei(), ergebnisDatei());
  });
});
