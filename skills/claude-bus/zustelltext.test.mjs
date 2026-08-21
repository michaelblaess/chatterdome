// Was in der Zielsitzung ankommt.
//
// Der Befund vom 17.08.2026: zugestellt wurde der blosse Auftragstext, und
// ueber den Inbox-Socket kommt der als {type:'user'} an - also ununterscheidbar
// von einer Eingabe Michaels, ohne Absender und ohne Auftrags-ID.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { GRENZMARKE, absenderName, empfaengerName, zustelltext } from './zustelltext.mjs';

const AUFTRAG = {
  auftrag_id: 'a1b2c3',
  von: 'Sanctuary',
  von_host: 'rainbow',
  an: 'Operator',
  host: 'RAINBOW',
  topic: 'allgemein',
  text: 'Bitte das aktuelle Datum nennen',
  quittung_erwartet: false,
};

describe('Absender', () => {
  test('wird mit dem Rechner qualifiziert', () => {
    // Derselbe Name kann auf zwei Rechnern leben - ohne Rechner ist er keine
    // Antwortadresse.
    assert.equal(absenderName(AUFTRAG), 'Sanctuary@RAINBOW');
  });

  test('ohne bekannten Rechner bleibt der blosse Name', () => {
    assert.equal(absenderName({ ...AUFTRAG, von_host: '' }), 'Sanctuary');
  });

  test('ohne Absender wird nichts erfunden', () => {
    assert.equal(absenderName({}), 'unbekannt');
  });
});

describe('Empfaenger', () => {
  test('wird mit dem Zielrechner qualifiziert', () => {
    assert.equal(empfaengerName(AUFTRAG), 'Operator@RAINBOW');
  });

  test('ohne Zielrechner bleibt der blosse Name', () => {
    assert.equal(empfaengerName({ ...AUFTRAG, host: '' }), 'Operator');
  });

  test('ohne Empfaenger wird nichts erfunden', () => {
    assert.equal(empfaengerName({}), '?');
  });
});

describe('Zustelltext', () => {
  test('nennt Absender und Auftrags-ID', () => {
    const t = zustelltext(AUFTRAG);
    assert.match(t, /Sanctuary@RAINBOW/);
    assert.match(t, /a1b2c3/);
  });

  test('nennt auch den Empfaenger', () => {
    // Patsy hielt sich am 21.08.2026 fuer eine Sitzung auf DELL, obwohl sie auf
    // RAINBOW lief - und schrieb das in ihre Quittung. Wer angeschrieben wird,
    // soll seine eigene Adresse nicht erschliessen muessen.
    assert.match(zustelltext(AUFTRAG), /an Operator@RAINBOW/);
  });

  test('traegt KEINE eigene Grenzmarke mehr', () => {
    // Claude Code haengt bei einer Einspeisung ueber den Peer-Kanal selbst
    // einen Hinweis an, und der ist der bessere. Zwei Belehrungen in einer
    // Nachricht sind eine zu viel - belegt an Patsys Ausgabe vom 21.08.2026,
    // wo beide untereinander standen und sich im Ton widersprachen.
    assert.ok(!zustelltext(AUFTRAG).includes(GRENZMARKE));
  });

  test('die Grenzmarke gibt es weiterhin - fuer den Weg ueber "read"', () => {
    // Dort rahmt Claude Code nichts, die Instanz liest den Text selbst.
    assert.ok(GRENZMARKE.length > 0);
  });

  test('zeigt einen ausfuehrbaren Weg zur Antwort', () => {
    // Genau hier lag das Muster vom 14.08.2026: die Empfaengerin antwortete im
    // eigenen Fenster, die Quittung blieb inhaltsleer.
    assert.match(zustelltext(AUFTRAG), /bus\.mjs ack a1b2c3 200/);
  });

  test('erwartete Quittung wird als solche benannt', () => {
    const t = zustelltext({ ...AUFTRAG, quittung_erwartet: true });
    assert.match(t, /Quittung erwartet/);
  });

  test('das Thema steht nur da, wenn es eines gibt', () => {
    assert.ok(!zustelltext(AUFTRAG).includes('Thema'));
    assert.match(zustelltext({ ...AUFTRAG, topic: 'release' }), /Thema release/);
  });

  test('ein leerer Text laesst den Aufbau heil', () => {
    const t = zustelltext({ ...AUFTRAG, text: '' });
    assert.match(t, /a1b2c3/);
    assert.match(t, /Sanctuary@RAINBOW an Operator@RAINBOW/);
  });

  test('die Grenzmarke bleibt kurz - sie geht in jeden Kontext', () => {
    // Kein Stilurteil, sondern eine Kostenschranke: der Block laeuft bei JEDER
    // Zustellung mit. 400 Zeichen sind rund 100 Tokens.
    assert.ok(GRENZMARKE.length < 400, `${GRENZMARKE.length} Zeichen`);
  });
});
