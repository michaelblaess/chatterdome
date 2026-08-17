// Die Schleifenbremse.
//
// Geprueft wird die reine Entscheidung: alle Zahlen kommen als Argument herein,
// keine Datenbank, keine Uhr. Genau dafuer ist pruefeEingang eine reine
// Funktion.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  GRENZEN, MAX_TEXT_BYTES, lageAus, pruefeEingang, pruefeGroesse,
} from './bremse.mjs';

const JETZT = 1_755_000_000_000;

function urteil(zusatz = {}) {
  return pruefeEingang({ text: 'mach mal', jetztMs: JETZT, ...zusatz });
}

describe('Groesse', () => {
  test('ein normaler Auftrag passt', () => {
    assert.equal(pruefeGroesse('Bitte die Tests laufen lassen'), '');
  });

  test('ueber der Grenze kommt eine Absage', () => {
    assert.notEqual(pruefeGroesse('x'.repeat(MAX_TEXT_BYTES + 1)), '');
  });

  test('genau auf der Grenze ist noch erlaubt', () => {
    assert.equal(pruefeGroesse('x'.repeat(MAX_TEXT_BYTES)), '');
  });

  test('gezaehlt werden Bytes, nicht Zeichen', () => {
    // Ein Umlaut sind zwei Bytes. Nach Zeichen gezaehlt kaeme diese Nachricht
    // durch, nach Bytes nicht - und in den Kontext gehen die Bytes.
    const halbe = 'ä'.repeat(MAX_TEXT_BYTES / 2 + 1);
    assert.notEqual(pruefeGroesse(halbe), '');
  });

  test('die Absage sagt, was zu tun ist', () => {
    // Wer bloss "zu gross" liest, kuerzt aufs Geratewohl und schickt es dreimal.
    const grund = pruefeGroesse('x'.repeat(MAX_TEXT_BYTES + 1));
    assert.match(grund, /Zusammenfassung|Datei/);
  });

  test('kein Text ist kein Fehler dieser Pruefung', () => {
    assert.equal(pruefeGroesse(undefined), '');
  });
});

describe('Wiederholung', () => {
  test('wortgleich und frisch wird verworfen', () => {
    const u = urteil({ letzterText: 'mach mal', letzteZeitMs: JETZT - 3_000 });
    assert.equal(u.ok, false);
    assert.equal(u.art, 'wiederholung');
  });

  test('wortgleich, aber lange her, ist erlaubt', () => {
    // Zweimal dieselbe Frage nach einer Stunde ist keine Schleife.
    const u = urteil({ letzterText: 'mach mal', letzteZeitMs: JETZT - GRENZEN.dedupMs - 1 });
    assert.equal(u.ok, true);
  });

  test('anderer Text im selben Moment ist erlaubt', () => {
    assert.equal(urteil({ letzterText: 'etwas anderes', letzteZeitMs: JETZT }).ok, true);
  });
});

describe('Takt', () => {
  test('bis zur Grenze darf gesendet werden', () => {
    assert.equal(urteil({ imTakt: GRENZEN.proTakt - 1 }).ok, true);
  });

  test('der neue Auftrag zaehlt mit', () => {
    // Sonst waere die Grenze um eins durchlaessiger als sie behauptet.
    const u = urteil({ imTakt: GRENZEN.proTakt });
    assert.equal(u.ok, false);
    assert.equal(u.art, 'takt');
  });
});

describe('Rueckstau', () => {
  test('unter der Grenze wird angenommen', () => {
    assert.equal(urteil({ offen: GRENZEN.maxOffen - 1 }).ok, true);
  });

  test('auf der Grenze ist Schluss', () => {
    const u = urteil({ offen: GRENZEN.maxOffen });
    assert.equal(u.ok, false);
    assert.equal(u.art, 'rueckstau');
  });

  test('die Absage nennt die Zahl', () => {
    assert.match(urteil({ offen: 50 }).grund, /50/);
  });
});

describe('Reihenfolge der Gruende', () => {
  test('die Groesse schlaegt alles andere', () => {
    // Ein zu grosser Text bleibt zu gross, auch wenn er der erste seiner Art
    // ist - und die Meldung soll die behebbare Ursache nennen.
    const u = urteil({ text: 'x'.repeat(MAX_TEXT_BYTES + 1), offen: 99 });
    assert.equal(u.art, 'gross');
  });
});

describe('Lage aus dem Bestand', () => {
  const zeile = (msVorher, text) => ({ ts: new Date(JETZT - msVorher).toISOString(), text });

  test('der juengste Auftrag ist der Vergleichstext', () => {
    const lage = lageAus([zeile(20_000, 'alt'), zeile(1_000, 'neu')], JETZT);
    assert.equal(lage.letzterText, 'neu');
  });

  test('die Reihenfolge der Zeilen entscheidet nicht', () => {
    const lage = lageAus([zeile(1_000, 'neu'), zeile(20_000, 'alt')], JETZT);
    assert.equal(lage.letzterText, 'neu');
  });

  test('gezaehlt wird nur, was im Takt liegt', () => {
    const lage = lageAus([zeile(GRENZEN.taktMs + 5_000, 'alt'), zeile(1_000, 'neu')], JETZT);
    assert.equal(lage.imTakt, 1);
  });

  test('kaputte Zeitstempel werden uebergangen, nicht geraten', () => {
    const lage = lageAus([{ ts: 'quatsch', text: 'x' }, zeile(500, 'echt')], JETZT);
    assert.equal(lage.imTakt, 1);
    assert.equal(lage.letzterText, 'echt');
  });

  test('ohne Vorgeschichte ist die Lage leer, nicht ungueltig', () => {
    const lage = lageAus([], JETZT);
    assert.equal(lage.letzterText, undefined);
    assert.equal(lage.imTakt, 0);
    assert.equal(pruefeEingang({ ...lage, text: 'erster', jetztMs: JETZT }).ok, true);
  });
});
