// Die Suche nach dem Gespraech einer Sitzung.
//
// Geprueft wird gegen das echte Ablageverzeichnis: ob dort Transkripte liegen,
// haengt vom Rechner ab, die Weigerungen dagegen gelten ueberall.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { FENSTER_START, findeTranskript, fortsetzbar, letzteZeilen } from './transkript.mjs';

describe('findeTranskript', () => {
  test('eine unbekannte Kennung findet nichts', () => {
    assert.equal(findeTranskript('00000000-0000-0000-0000-000000000000'), null);
  });

  test('ohne Kennung wird gar nicht erst gesucht', () => {
    assert.equal(findeTranskript(''), null);
  });

  test('gefunden wird eine .jsonl, kein Verzeichnis', () => {
    // Nur pruefen, wenn dieser Rechner ueberhaupt Transkripte hat.
    const eigene = process.env.CLAUDE_CODE_SESSION_ID;
    const pfad = eigene ? findeTranskript(eigene) : null;
    if (null === pfad) return;
    assert.match(pfad, /\.jsonl$/);
  });
});

describe('fortsetzbar', () => {
  test('ohne Transkript nicht fortsetzbar', () => {
    // Der Fall vom 16.08.2026: eine frisch geoeffnete Sitzung, die noch kein
    // Wort gewechselt hatte. "claude --resume" bricht dort ab - aber erst,
    // nachdem das Fenster aufgegangen ist.
    assert.equal(fortsetzbar('00000000-0000-0000-0000-000000000000'), false);
  });

  test('eine leere Kennung ist nicht fortsetzbar', () => {
    assert.equal(fortsetzbar(''), false);
  });
});

describe('letzteZeilen', () => {
  // Der Anlass steht in transkript.mjs: eine EINZELNE Zeile kann groesser sein
  // als das Lesefenster. Gemessen am 22.08.2026 ueber 34.846 Zeilen aus zwoelf
  // echten Transkripten - die groesste war 1.454 KB.

  function schreibe(zeilen) {
    const dir = mkdtempSync(join(tmpdir(), 'transkript-'));
    const datei = join(dir, 'x.jsonl');
    writeFileSync(datei, zeilen.map((z) => JSON.stringify(z)).join('\n') + '\n', 'utf8');
    return { dir, datei };
  }

  test('liefert die letzten Zeilen einer kleinen Datei', () => {
    const { dir, datei } = schreibe([{ i: 1 }, { i: 2 }, { i: 3 }]);
    try {
      const zeilen = letzteZeilen(datei, 2);
      assert.equal(zeilen.length, 2);
      assert.equal(JSON.parse(zeilen[1]).i, 3);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('eine Zeile groesser als das Startfenster geht NICHT verloren', () => {
    // Ohne das Nachfassen bliebe nach dem Abschneiden der angeschnittenen
    // ersten Zeile nichts uebrig, und die Sitzung stuende ohne Modell,
    // Kontext und Werkzeug in der Tabelle - ohne dass irgendwo ein Fehler
    // auftaucht.
    const riese = { i: 2, brocken: 'x'.repeat(FENSTER_START + 50_000) };
    const { dir, datei } = schreibe([{ i: 1 }, riese]);
    try {
      const zeilen = letzteZeilen(datei, 5);
      assert.ok(zeilen.length >= 1, 'nichts gelesen');
      assert.equal(JSON.parse(zeilen[zeilen.length - 1]).i, 2);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('auch zwei Riesen hintereinander kommen an', () => {
    const gross = (i) => ({ i, brocken: 'y'.repeat(FENSTER_START) });
    const { dir, datei } = schreibe([{ i: 0 }, gross(1), gross(2)]);
    try {
      const zeilen = letzteZeilen(datei, 2);
      assert.equal(JSON.parse(zeilen[zeilen.length - 1]).i, 2);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('eine fehlende Datei ergibt eine leere Liste, keine Ausnahme', () => {
    assert.deepEqual(letzteZeilen(join(tmpdir(), 'gibt-es-nicht-4711.jsonl'), 10), []);
  });

  test('leere Zeilen fallen weg', () => {
    const dir = mkdtempSync(join(tmpdir(), 'transkript-'));
    const datei = join(dir, 'x.jsonl');
    try {
      writeFileSync(datei, '{"i":1}\n\n\n{"i":2}\n', 'utf8');
      assert.equal(letzteZeilen(datei, 10).length, 2);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});
