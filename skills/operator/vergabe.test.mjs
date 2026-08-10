// Prueft die Namensvergabe an dem Zustand, in dem sie versagt hat.
//
// Am 10.08.2026 hiess ein Fenster "Operator-22", obwohl von 19 Comicmotiv-Namen
// nur sechs an laufenden Instanzen hingen. Der Test baut genau das nach: eine
// namen.json voller Karteileichen, daneben eine kurze Liste laufender
// Instanzen. Er kann scheitern - vor dem Fix liefert er die Nummer zurueck.
//
// Aufruf: node --test skills/operator/

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { raeumeAuf, waehleNamen, vergibNamen } from './vergabe.mjs';
import { ladePool } from './pool.mjs';

/** Eine Session-ID je Name - der Inhalt ist egal, nur die Eindeutigkeit zaehlt. */
function tabelleAus(namen) {
  const t = {};
  namen.forEach((n, i) => { t[`sid-${i}`] = n; });
  return t;
}

/** Die Instanzliste, wie ladeInstanzen sie liefert. */
function laufendeAus(tabelle, namen) {
  const gesucht = new Set(namen);
  return Object.entries(tabelle)
    .filter(([, name]) => gesucht.has(name))
    .map(([sessionId]) => ({ sessionId }));
}

describe('Namensvergabe', () => {
  test('voller Pool aus Karteileichen gibt trotzdem einen echten Namen', () => {
    const pool = ladePool();
    // Alle Namen des aktiven Motivs sind vergeben, plus eine Leiche obendrauf -
    // das ist der Stand, aus dem "Operator-22" entstand.
    const tabelle = tabelleAus([...pool, 'Therese']);
    const lebendig = pool.slice(1, 5);

    const { name } = vergibNamen({
      tabelle,
      laufende: laufendeAus(tabelle, lebendig),
    });

    assert.doesNotMatch(name, /-\d+$/, `durchnummeriert statt recycelt: ${name}`);
    assert.ok(pool.includes(name), `Name kommt nicht aus dem aktiven Motiv: ${name}`);
    assert.ok(!lebendig.includes(name), `Name einer laufenden Instanz vergeben: ${name}`);
  });

  test('nie benutzte Namen kommen vor recycelten', () => {
    const pool = ladePool();
    // Nur die erste Haelfte war je vergeben, keine davon laeuft noch. Trotzdem
    // muss ein unbenutzter Name aus der zweiten Haelfte gewaehlt werden: eine
    // gerade startende Instanz taucht in der Instanzliste noch nicht auf.
    const alt = pool.slice(0, 5);
    const tabelle = tabelleAus(alt);

    const { name } = vergibNamen({ tabelle, laufende: [{ sessionId: 'fremd' }] });

    assert.ok(!alt.includes(name), `recycelt, obwohl frische Namen da waren: ${name}`);
  });

  test('leere Instanzliste raeumt nicht auf', () => {
    // Eine leere Liste kann auch aus einem Timeout stammen. Wer daraus loescht,
    // nimmt allen laufenden Instanzen ihren Namen.
    const tabelle = tabelleAus(['Snorre', 'Lino']);

    const freigegeben = raeumeAuf(tabelle, null, []);

    assert.equal(freigegeben.length, 0);
    assert.equal(Object.keys(tabelle).length, 2);
  });

  test('die eigene Sitzung wird nie freigeraeumt', () => {
    const tabelle = { meine: 'Snorre', fremde: 'Lino' };

    raeumeAuf(tabelle, 'meine', [{ sessionId: 'irgendwer' }]);

    assert.equal(tabelle.meine, 'Snorre');
    assert.equal(tabelle.fremde, undefined);
  });

  test('Vorgabe wird gegen die aufgeraeumte Sicht geprueft', () => {
    // Der Starter hat "Snorre" recycelt und weitergereicht. Der Hook darf ihn
    // nicht verwerfen, nur weil die Leiche noch in der Tabelle steht.
    const tabelle = tabelleAus(['Snorre']);

    const { name } = vergibNamen({
      tabelle,
      vorgabe: 'Snorre',
      laufende: [{ sessionId: 'fremd' }],
    });

    assert.equal(name, 'Snorre');
  });

  test('Vorgabe einer laufenden Instanz wird abgelehnt', () => {
    const tabelle = { lebt: 'Snorre' };

    const { name } = vergibNamen({
      tabelle,
      vorgabe: 'Snorre',
      laufende: [{ sessionId: 'lebt' }],
    });

    assert.notEqual(name, 'Snorre');
  });

  test('erst wenn wirklich alles belegt ist, wird durchnummeriert', () => {
    // Gegenprobe zum ersten Test: hier ist der GESAMTE Namensbestand vergeben
    // und jede Sitzung laeuft. Dann ist eine Nummer richtig.
    const pool = ladePool();
    const tabelle = tabelleAus(alleBekanntenNamen());
    const laufende = Object.keys(tabelle).map((sessionId) => ({ sessionId }));

    const name = vergibNamen({ tabelle, laufende }).name;

    assert.match(name, new RegExp(`^${pool[0]}-\\d+$`));
  });
});

/** Alle Namen aller Motive - ueber waehleNamen ermittelt, ohne pool.mjs-Interna. */
function alleBekanntenNamen() {
  const gesammelt = [];
  const tabelle = {};
  // Solange waehleNamen noch einen echten Namen liefert, ist der Bestand nicht
  // erschoepft. Die Schleife haelt an, sobald durchnummeriert wird.
  for (let i = 0; i < 500; i++) {
    const belegt = new Set(gesammelt);
    const name = waehleNamen(tabelle, belegt);
    if (/-\d+$/.test(name) || gesammelt.includes(name)) break;
    gesammelt.push(name);
    tabelle[`sid-${i}`] = name;
  }
  return gesammelt;
}
