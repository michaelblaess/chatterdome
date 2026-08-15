// Die Suche nach dem Gespraech einer Sitzung.
//
// Geprueft wird gegen das echte Ablageverzeichnis: ob dort Transkripte liegen,
// haengt vom Rechner ab, die Weigerungen dagegen gelten ueberall.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { findeTranskript, fortsetzbar } from './transkript.mjs';

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
