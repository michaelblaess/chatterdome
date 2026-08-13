// Der gemeldete Fall vom 14.08.2026: in der Tabelle stand bei drei von fuenf
// Agenten nur "[Image: source: C:\tmp\Gree...", obwohl die Prompts Text
// enthielten. Bild-Platzhalter sind im Transkript selbst text-Bloecke, und der
// erste Block gewann.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { aufgabeAusInhalt } from './aufgabe.mjs';

describe('Aufgabe aus dem Transkript', () => {
  test('der gemeldete Fall - Platzhalter steht vor dem Text', () => {
    const inhalt = [
      { type: 'text', text: '[Image: source: C:\\tmp\\Greenshot\\2026-08-14 00_36_32.png]' },
      { type: 'text', text: 'claude-sanctuary sieht gut aus unter Linux' },
    ];
    assert.equal(aufgabeAusInhalt(inhalt), 'claude-sanctuary sieht gut aus unter Linux');
  });

  test('Text und Platzhalter im selben Block', () => {
    const inhalt = [{ type: 'text', text: 'sieht gut aus\n[Image #1]' }];
    assert.equal(aufgabeAusInhalt(inhalt), 'sieht gut aus');
  });

  test('nur Anhaenge - dann ein kurzes Kuerzel statt eines Dateipfads', () => {
    const inhalt = [
      { type: 'text', text: '[Image: source: C:\\tmp\\a.png]' },
      { type: 'text', text: '[Image: source: C:\\tmp\\b.png]' },
    ];
    assert.equal(aufgabeAusInhalt(inhalt), '[Bild]');
  });

  test('einfacher String bleibt, wie er ist', () => {
    assert.equal(aufgabeAusInhalt('ja mach den Fix'), 'ja mach den Fix');
  });

  test('Zeilenumbrueche werden zu einer Zeile', () => {
    assert.equal(aufgabeAusInhalt('erste Zeile\n\n  zweite Zeile'), 'erste Zeile zweite Zeile');
  });

  test('Werkzeugergebnisse ohne text-Block ergeben nichts', () => {
    const inhalt = [{ type: 'tool_result', content: 'ausgabe' }];
    assert.equal(aufgabeAusInhalt(inhalt), '');
  });

  test('fehlender Inhalt wirft nicht', () => {
    assert.equal(aufgabeAusInhalt(null), '');
    assert.equal(aufgabeAusInhalt(undefined), '');
  });
});
