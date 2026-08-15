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
  auftragsDatei, beendeSitzung, ergebnisDatei, neustartHier, resumeBefehl,
} from './neustart.mjs';

/**
 * Eine Attrappe der Prozesswelt: eine Liste von PIDs, die "leben", bis sie
 * ein SIGTERM bekommen. Damit laesst sich das Beenden pruefen, ohne dass ein
 * echter Prozess ins Spiel kommt.
 */
function welt({ prozesse, stirbt = true, claude = true }) {
  const tot = new Set();
  const getoetet = [];
  return {
    getoetet,
    werkzeuge: {
      instanzen: () => prozesse,
      lebt: (pid) => !tot.has(Number(pid)),
      claude: () => claude,
      toete: (pid) => {
        getoetet.push(Number(pid));
        if (stirbt) tot.add(Number(pid));
      },
      warte: () => {},
      frist: 0,
      selbst: 'ich-selbst',
    },
  };
}

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

describe('Beenden vor dem Fortsetzen', () => {
  // Der Vorfall vom 16.08.2026: der ferne Neustart oeffnete ein zweites
  // Fenster mit --resume, ohne das erste zu beenden. Auf senza liefen danach
  // PID 1319787 und 3585570 auf DERSELBEN Sitzung, beide im selben
  // Transkript - und weil der Name an der Sitzung haengt, unter demselben
  // Namen. Die Oberflaeche starb an der doppelten Zeilenkennung.

  const zweiAufEiner = [
    { pid: 1319787, sessionId: 'sid-1', startedAt: 1 },
    { pid: 3585570, sessionId: 'sid-1', startedAt: 2 },
  ];

  test('beendet ALLE Prozesse der Sitzung, nicht nur den ersten', () => {
    const w = welt({ prozesse: zweiAufEiner });
    assert.equal(beendeSitzung('sid-1', w.werkzeuge), '');
    assert.deepEqual(w.getoetet, [1319787, 3585570]);
  });

  test('fremde Sitzungen bleiben unangetastet', () => {
    const w = welt({ prozesse: [...zweiAufEiner, { pid: 42, sessionId: 'sid-2' }] });
    beendeSitzung('sid-1', w.werkzeuge);
    assert.ok(!w.getoetet.includes(42));
  });

  test('stirbt der Prozess nicht, gibt es kein zweites Fenster', () => {
    // Der Rueckgabewert bremst neustartHier aus - genau das ist der Zweck.
    const w = welt({ prozesse: zweiAufEiner, stirbt: false });
    assert.match(beendeSitzung('sid-1', w.werkzeuge), /Beendet nicht: PID 1319787, 3585570/);
  });

  test('eine fremde PID bekommt kein Signal', () => {
    // Nach einem Ausstieg vergibt das System die Nummer neu. Fail-closed:
    // lieber gar nicht beenden als den falschen Prozess.
    const w = welt({ prozesse: zweiAufEiner, claude: false });
    assert.match(beendeSitzung('sid-1', w.werkzeuge), /gehoert nicht mehr zu Claude/);
    assert.deepEqual(w.getoetet, []);
  });

  test('die eigene Sitzung beendet sich nicht selbst', () => {
    const w = welt({ prozesse: [{ pid: 7, sessionId: 'ich-selbst' }] });
    assert.match(beendeSitzung('ich-selbst', w.werkzeuge), /nicht selbst/);
    assert.deepEqual(w.getoetet, []);
  });

  test('laeuft nichts mehr, ist nichts zu tun', () => {
    const w = welt({ prozesse: [] });
    assert.equal(beendeSitzung('sid-1', w.werkzeuge), '');
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
