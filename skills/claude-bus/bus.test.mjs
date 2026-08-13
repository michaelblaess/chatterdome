// Stellt den Vorfall vom 07.08.2026 ueber die echte Kommandozeile nach.
//
// Der Ablauf ist genau der gemeldete: Sanctuary legt einen Auftrag an Marga
// ab, diese Sitzung endet, der Name geht zurueck in den Pool und wird an eine
// voellig andere Sitzung neu vergeben. Danach wird gemessen, was die neue
// Sitzung in ihrer Warteschlange findet.
//
// Bewusst ueber execFile und nicht ueber die exportierten Funktionen: der
// Fehler sass in der Zusammenarbeit von Namenstabelle, Adressierung und
// Warteschlange. Ein Test, der nur fuerMich() aufruft, haette ihn nicht
// gefunden, weil die Namenstabelle dort gar nicht vorkommt.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir, hostname } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const BUS = join(dirname(fileURLToPath(import.meta.url)), 'bus.mjs');
const RECHNER = (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();

const SITZUNG_ALT = '4d0c0ab0-935e-430a-a670-e9aaeae7e6fa';
const SITZUNG_NEU = 'aaaabbbb-1111-2222-3333-444455556666';

/** Ein Wegwerf-Bus mit eigener Namenstabelle. */
function busUmgebung(t) {
  const wurzel = mkdtempSync(join(tmpdir(), 'bus-cli-'));
  const hostDir = join(wurzel, RECHNER);
  mkdirSync(hostDir, { recursive: true });
  t.after(() => rmSync(wurzel, { recursive: true, force: true }));

  return {
    /** Schreibt die Zuordnung Session-ID zu Name neu - das ist die Pacht. */
    namen(tabelle) {
      writeFileSync(join(hostDir, 'namen.json'), JSON.stringify(tabelle, null, 1), 'utf8');
    },
    /**
     * Ruft die Kommandozeile auf.
     *
     * @param sitzung
     * Wert fuer CLAUDE_CODE_SESSION_ID. Leer bedeutet "kein Claude" - genau so
     * sendet die Oberflaeche, und genau daher kam der gemeldete Auftrag.
     */
    lauf(argumente, sitzung = '') {
      const umgebung = {
        ...process.env,
        CLAUDE_BUS_DIR: wurzel,
        CLAUDE_CODE_SESSION_ID: sitzung,
        // Der Verfall haette in diesen Tests nichts zu tun (alles frisch),
        // wird aber abgeschaltet, damit die Pruefungen sich nicht gegenseitig
        // erklaeren muessen.
        CLAUDE_BUS_VERFALL_STUNDEN: '0',
      };
      try {
        return { code: 0, aus: execFileSync(process.execPath, [BUS, ...argumente], { env: umgebung, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }) };
      } catch (fehler) {
        return { code: fehler.status ?? 1, aus: `${fehler.stdout || ''}${fehler.stderr || ''}` };
      }
    },
    /** Die Warteschlange einer Sitzung als Objekt. */
    warteschlange(sitzung) {
      const { aus } = this.lauf(['tasks', '--json'], sitzung);
      return JSON.parse(aus);
    },
  };
}

describe('Ein neu vergebener Name erbt keine Post', () => {
  test('der gemeldete Vorfall - vier Tage alter Auftrag an die Vorgaengerin', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga' });

    const gesendet = bus.lauf(['send', 'Marga', 'gib mir das aktuelle Datum', '--von', 'Sanctuary', '--host', RECHNER]);
    assert.equal(gesendet.code, 0, gesendet.aus);

    // Die Sitzung endet, der Name geht zurueck in den Pool und wird neu vergeben.
    bus.namen({ [SITZUNG_NEU]: 'Marga' });

    const neue = bus.warteschlange(SITZUNG_NEU);
    assert.deepEqual(neue.meine, [], 'die neue Marga darf den Auftrag ihrer Vorgaengerin nicht sehen');
  });

  test('Gegenprobe - die gemeinte Sitzung bekommt ihn sehr wohl', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga' });
    bus.lauf(['send', 'Marga', 'gib mir das aktuelle Datum', '--von', 'Sanctuary', '--host', RECHNER]);

    const gemeint = bus.warteschlange(SITZUNG_ALT);
    assert.equal(gemeint.meine.length, 1, 'sonst kommt ueberhaupt nichts mehr an');
    assert.equal(gemeint.meine[0].text, 'gib mir das aktuelle Datum');
  });

  test('Gegenprobe - mit --rolle ueberlebt der Auftrag den Namenswechsel', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga' });
    bus.lauf(['send', 'Marga', 'wer auch immer das liest', '--rolle', '--von', 'Sanctuary', '--host', RECHNER]);

    bus.namen({ [SITZUNG_NEU]: 'Marga' });

    // Das ist kein Rueckfall, sondern die andere Adressart: hier war die Rolle
    // gemeint, nicht die Person. Verantwortbar nur zusammen mit dem Verfall.
    const neue = bus.warteschlange(SITZUNG_NEU);
    assert.equal(neue.meine.length, 1);
  });
});

describe('Adressierung', () => {
  test('an einen Namen, den niemand traegt, wird nicht gesendet', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga' });

    const { code, aus } = bus.lauf(['send', 'Schmid', 'Text', '--von', 'Sanctuary', '--host', RECHNER]);

    assert.equal(code, 1, 'ein Auftrag ins Leere ist genau der Bestand, der spaeter jemanden trifft');
    assert.match(aus, /trägt gerade niemand/);
  });

  test('mit --rolle geht auch ein unbesetzter Name', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga' });

    const { code } = bus.lauf(['send', 'Schmid', 'Text', '--rolle', '--von', 'Sanctuary', '--host', RECHNER]);
    assert.equal(code, 0);
  });

  test('der Rundruf erreicht weiterhin jeden ausser dem Absender', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga', [SITZUNG_NEU]: 'Schmid' });

    bus.lauf(['send', 'alle', 'Ich fasse gleich claude-config an', '--von', 'Sanctuary']);

    assert.equal(bus.warteschlange(SITZUNG_ALT).meine.length, 1);
    assert.equal(bus.warteschlange(SITZUNG_NEU).meine.length, 1);
  });
});

describe('Einstellungen', () => {
  test('config zeigt die Frist und woher sie kommt', (t) => {
    const bus = busUmgebung(t);
    const { aus } = bus.lauf(['config']);

    assert.match(aus, /verfall_stunden/);
    // Der Aufruf setzt die Umgebungsvariable auf 0 - genau das muss dastehen,
    // sonst sucht man den Grund fuer einen nicht wirkenden Wert vergeblich.
    assert.match(aus, /aus Umgebung/);
  });
});

// Aufgefallen am 14.08.2026 beim Zustelltest ueber Rechnergrenzen: die
// offen-Ansicht schrieb "[Invalid Date]" statt eines Datums. Zwei Ursachen
// hintereinander - alsNachricht() las z.ts, die Tabelle "auftrag" fuehrt den
// Zeitpunkt aber als "erstellt", und das try/catch in zeit() konnte das nicht
// auffangen, weil new Date(undefined) gar nicht wirft.
describe('Zeitangaben', () => {
  test('die offen-Ansicht zeigt ein Datum, kein "Invalid Date"', (t) => {
    const bus = busUmgebung(t);
    bus.namen({ [SITZUNG_ALT]: 'Marga', [SITZUNG_NEU]: 'Lino' });

    const gesendet = bus.lauf(
      ['send', 'Marga', 'Zeitstempelprobe', '--expect-receipt', '--host', RECHNER],
      SITZUNG_NEU,
    );
    assert.equal(gesendet.code, 0, gesendet.aus);

    const { aus } = bus.lauf(['open'], SITZUNG_NEU);

    assert.doesNotMatch(aus, /Invalid Date/, aus);
    // dd.mm.yy - das Kurzformat von toLocaleString('de-DE').
    assert.match(aus, /\d{2}\.\d{2}\.\d{2}/, aus);
  });
});
