// Prueft den Vorfall vom 02.10.2026: nach /clear hiess ein Fenster ploetzlich
// "Therese", waehrend seine Statuszeile weiter "Patrick" zeigte.
//
// Der letzte Test faehrt whoami.mjs als echten Prozess gegen ein
// Wegwerf-Heimatverzeichnis - genau den Weg, den der SessionStart-Hook nimmt.
// Er kann scheitern: ohne die Fensterliste liefert der zweite Aufruf einen
// anderen Namen als der erste.
//
// Aufruf: node --test "skills/operator/*.test.mjs"

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { merkeFenster, vorgaengerSitzung } from './fenster.mjs';
import { vergibNamen } from './vergabe.mjs';

const HIER = dirname(fileURLToPath(import.meta.url));
const ALT = 'f507f8be-9200-4260-a6bb-b57d2c26b488';
const NEU = '898b85f8-862a-4e65-ad5a-e9aac2dcf2bd';

describe('Vorgaenger im selben Fenster', () => {
  test('gleiche PID und gleiche Startzeit ergeben den Vorgaenger', () => {
    const fenster = { 73588: { sessionId: ALT, procStart: '134' } };
    assert.equal(vorgaengerSitzung(fenster, 73588, '134', NEU), ALT);
  });

  test('neu vergebene PID erbt nichts', () => {
    // Windows vergibt PIDs schnell neu. Ein fremdes Fenster mit derselben
    // Nummer darf weder Namen noch Postfach des beendeten bekommen.
    const fenster = { 73588: { sessionId: ALT, procStart: '134' } };
    assert.equal(vorgaengerSitzung(fenster, 73588, '999', NEU), null);
  });

  test('ohne Startzeit gibt es keinen Vorgaenger', () => {
    const fenster = { 73588: { sessionId: ALT, procStart: '134' } };
    assert.equal(vorgaengerSitzung(fenster, 73588, '', NEU), null);
  });

  test('dieselbe Sitzung ist nicht ihr eigener Vorgaenger', () => {
    const fenster = { 73588: { sessionId: ALT, procStart: '134' } };
    assert.equal(vorgaengerSitzung(fenster, 73588, '134', ALT), null);
  });

  test('merken wirft beendete Prozesse hinaus', () => {
    const fenster = { 1: { sessionId: 'tot', procStart: 'a' }, 2: { sessionId: 'lebt', procStart: 'b' } };
    merkeFenster(fenster, 3, 'c', NEU, (pid) => pid !== 1);
    assert.deepEqual(Object.keys(fenster).sort(), ['2', '3']);
    assert.deepEqual(fenster[3], { sessionId: NEU, procStart: 'c' });
  });
});

describe('Namensvergabe mit Vorgaenger', () => {
  test('der Name geht mit, statt neu vergeben zu werden', () => {
    const tabelle = { [ALT]: 'Patrick', andere: 'Lucia' };

    const ergebnis = vergibNamen({
      tabelle, eigeneSession: NEU, vorgaenger: ALT, laufende: [{ sessionId: 'andere' }],
    });

    assert.equal(ergebnis.name, 'Patrick');
    assert.equal(ergebnis.uebernommenVon, ALT);
    // Der Vorgaenger ist keine Karteileiche: stuende er in "freigegeben",
    // naehme pachtEndet seine offenen Auftraege zurueck.
    assert.deepEqual(ergebnis.freigegeben, []);
    assert.equal(tabelle[ALT], undefined, 'sonst tragen zwei Sitzungen denselben Namen');
  });

  test('unbekannter Vorgaenger faellt auf die normale Vergabe zurueck', () => {
    const tabelle = { andere: 'Lucia' };

    const ergebnis = vergibNamen({
      tabelle, eigeneSession: NEU, vorgaenger: ALT, laufende: [{ sessionId: 'andere' }],
    });

    assert.equal(ergebnis.uebernommenVon, null);
    assert.notEqual(ergebnis.name, 'Lucia');
  });
});

describe('whoami.mjs ueber /clear hinweg', () => {
  test('zweiter Aufruf mit neuer Session-ID liefert denselben Namen', (t) => {
    const heim = mkdtempSync(join(tmpdir(), 'whoami-test-'));
    t.after(() => rmSync(heim, { recursive: true, force: true }));

    // Die eigene PID steht fuer den Claude-Prozess: sie lebt nachweislich, und
    // damit raeumt weder die Fensterliste noch die Namenstabelle sie weg.
    const pid = process.pid;
    const sitzungen = join(heim, '.claude', 'sessions');
    mkdirSync(sitzungen, { recursive: true });
    const sitzungsdatei = (sessionId) => writeFileSync(
      join(sitzungen, `${pid}.json`),
      JSON.stringify({ pid, sessionId, procStart: '134353634051227183' }),
      'utf8',
    );

    const rufe = (sessionId) => execFileSync(process.execPath, [join(HIER, 'whoami.mjs')], {
      encoding: 'utf8',
      env: {
        ...process.env,
        USERPROFILE: heim,
        HOME: heim,
        COMPUTERNAME: 'TESTRECHNER',
        CLAUDE_PID: String(pid),
        CLAUDE_CODE_SESSION_ID: sessionId,
        CLAUDE_INSTANZ_NAME: '',
      },
    });

    sitzungsdatei(ALT);
    const vorher = rufe(ALT);
    sitzungsdatei(NEU);
    const nachher = rufe(NEU);

    assert.ok(vorher, 'erster Aufruf hat keinen Namen geliefert');
    assert.equal(nachher, vorher);
    const tabelle = JSON.parse(readFileSync(join(heim, '.claude', 'bus', 'TESTRECHNER', 'namen.json'), 'utf8'));
    assert.deepEqual(tabelle, { [NEU]: vorher });
  });
});
