// Tests fuer die Sofortzustellung.
//
// Der wichtigste Test baut einen ECHTEN Unix-Socket und liest, was ankommt.
// Eine Attrappe wuerde genau das nicht pruefen, worauf es hier ankommt: dass
// die Nutzlast als eine Zeile JSON auf der Leitung landet und der Empfaenger
// sie an \n trennen kann.
//
// Auf Windows gibt es keine Unix-SOCKETS - die betroffenen Tests werden dort
// uebersprungen statt zu scheitern. Der Kanal selbst ist dort inzwischen
// erreichbar, nur eben als Named Pipe, und die laesst sich in einem Test nicht
// so billig aufsetzen wie ein Socket im Temp-Verzeichnis.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'node:net';

import {
  sockelFaehig, ladeSockets, merkeSocket, raeumeSockets, eintrag,
  nutzlast, schreibeInSocket, sofortZustellen,
} from './socket.mjs';

const WINDOWS = process.platform === 'win32';

function tempDir() {
  return mkdtempSync(join(tmpdir(), 'bus-socket-'));
}

describe('Nutzlast', () => {
  test('ist eine Zeile JSON in der Form, die Claude Code erwartet', () => {
    const zeile = nutzlast('hallo');
    assert.ok(zeile.endsWith('\n'), 'der Zeilenumbruch ist Teil des Protokolls');
    assert.deepEqual(JSON.parse(zeile), {
      type: 'user',
      message: { role: 'user', content: 'hallo' },
    });
  });

  test('haelt Zeilenumbrueche im Text aus, ohne das Protokoll zu zerreissen', () => {
    // Ein Auftragstext darf mehrzeilig sein. Wuerde er roh eingesetzt, laese
    // der Empfaenger zwei halbe Nachrichten - JSON.stringify escapt das.
    const zeile = nutzlast('erste\nzweite');
    assert.equal(zeile.split('\n').length, 2, 'genau eine Nutzzeile plus Abschluss');
    assert.equal(JSON.parse(zeile).message.content, 'erste\nzweite');
  });
});

describe('Socket-Tabelle', () => {
  test('merkt sich einen Pfad und liest ihn wieder', () => {
    const dir = tempDir();
    try {
      assert.deepEqual(ladeSockets(dir), {}, 'ohne Datei ist die Tabelle leer');
      assert.equal(merkeSocket(dir, 'sid-1', '/tmp/a.sock'), true);
      assert.deepEqual(ladeSockets(dir), { 'sid-1': { pfad: '/tmp/a.sock' } });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('eine kaputte Datei liefert eine leere Tabelle statt zu werfen', () => {
    const dir = tempDir();
    try {
      writeFileSync(join(dir, 'sockets.json'), '{kein json', 'utf8');
      assert.deepEqual(ladeSockets(dir), {});
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('ohne Session-ID oder Pfad wird nichts geschrieben', () => {
    const dir = tempDir();
    try {
      assert.equal(merkeSocket(dir, '', '/tmp/a.sock'), false);
      assert.equal(merkeSocket(dir, 'sid-1', ''), false);
      assert.deepEqual(ladeSockets(dir), {});
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('raeumt beendete Sitzungen weg, behaelt die laufenden', () => {
    const dir = tempDir();
    try {
      merkeSocket(dir, 'lebt', '/tmp/a.sock');
      merkeSocket(dir, 'weg', '/tmp/b.sock');
      assert.equal(raeumeSockets(dir, ['lebt']), 1);
      assert.deepEqual(ladeSockets(dir), { lebt: { pfad: '/tmp/a.sock' } });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('eine LEERE Liste laufender Sitzungen loescht nichts', () => {
    // Der wichtige Fall: eine leere Instanzliste kann auch aus einem Fehler
    // stammen. Wer daraus loescht, nimmt allen laufenden Sitzungen ihren
    // Socket - derselbe Fehler, den whoami.mjs beim Namensaufraeumen vermeidet.
    const dir = tempDir();
    try {
      merkeSocket(dir, 'lebt', '/tmp/a.sock');
      assert.equal(raeumeSockets(dir, []), 0);
      assert.deepEqual(ladeSockets(dir), { lebt: { pfad: '/tmp/a.sock' } });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});

describe('Zustellung', () => {
  test('der Weg ist auf jeder Plattform grundsaetzlich offen', () => {
    // Bis zum 20.08.2026 stand hier die Plattformgrenze. Sie gilt nicht mehr:
    // mit CLAUDE_CODE_HARBOR_KITE bindet Claude Code auch unter Windows einen
    // Kanal, dort eine Named Pipe. Ob eine BESTIMMTE Sitzung erreichbar ist,
    // entscheidet ihr Eintrag in sockets.json, nicht das Betriebssystem.
    assert.equal(sockelFaehig(), true);
  });

  test('ein unbekannter Pfad ist ein Grund, kein Absturz', async () => {
    const grund = await schreibeInSocket('', 'text');
    assert.notEqual(grund, '', 'ohne Pfad muss ein Grund zurueckkommen');
  });

  test('modus stop-hook schaltet die Sofortzustellung ab', async () => {
    const dir = tempDir();
    try {
      const e = await sofortZustellen({ datenDir: dir, sessionId: 'sid', text: 't', modus: 'stop-hook' });
      assert.equal(e.zugestellt, false);
      assert.match(e.grund, /Einstellung/);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('ohne hinterlegten Socket wird nicht zugestellt', async (t) => {
    if (WINDOWS) return t.skip('kein Inbox-Socket auf Windows');
    const dir = tempDir();
    try {
      const e = await sofortZustellen({ datenDir: dir, sessionId: 'unbekannt', text: 't', modus: 'auto' });
      assert.equal(e.zugestellt, false);
      assert.match(e.grund, /kein Socket/);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('schreibt echtes JSON in einen echten Socket', async (t) => {
    if (WINDOWS) return t.skip('kein Inbox-Socket auf Windows');
    const dir = tempDir();
    const pfad = join(dir, 'probe.sock');
    let empfangen = '';
    const server = createServer((c) => { c.on('data', (d) => { empfangen += d; }); });
    await new Promise((f) => server.listen(pfad, f));
    try {
      const fehler = await schreibeInSocket(pfad, 'Auftrag mit "Anfuehrung" und (Klammern)');
      assert.equal(fehler, '', 'die Zustellung muss gelingen');
      // Kurz warten: write() ist gepuffert, die Daten koennen noch unterwegs sein.
      await new Promise((f) => setTimeout(f, 120));
      assert.ok(empfangen.endsWith('\n'), 'eine vollstaendige Zeile');
      assert.equal(
        JSON.parse(empfangen).message.content,
        'Auftrag mit "Anfuehrung" und (Klammern)',
      );
    } finally {
      server.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test('ein toter Socket meldet die beendete Sitzung, statt zu haengen', async (t) => {
    if (WINDOWS) return t.skip('kein Inbox-Socket auf Windows');
    const dir = tempDir();
    try {
      // Pfad eingetragen, aber nie gebunden - genau der Fall einer Sitzung,
      // die beendet wurde und ihren Socket abgeraeumt hat.
      merkeSocket(dir, 'sid', join(dir, 'gibtsnicht.sock'));
      const e = await sofortZustellen({ datenDir: dir, sessionId: 'sid', text: 't', modus: 'auto' });
      assert.equal(e.zugestellt, false);
      assert.match(e.grund, /läuft nicht mehr/);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('der Vollzug: eingetragener Socket, echter Empfaenger, zugestellt', async (t) => {
    if (WINDOWS) return t.skip('kein Inbox-Socket auf Windows');
    const dir = tempDir();
    const pfad = join(dir, 'ziel.sock');
    let empfangen = '';
    const server = createServer((c) => { c.on('data', (d) => { empfangen += d; }); });
    await new Promise((f) => server.listen(pfad, f));
    try {
      merkeSocket(dir, 'sid-ziel', pfad);
      const e = await sofortZustellen({ datenDir: dir, sessionId: 'sid-ziel', text: 'los', modus: 'auto' });
      assert.equal(e.grund, '');
      assert.equal(e.zugestellt, true);
      await new Promise((f) => setTimeout(f, 120));
      assert.equal(JSON.parse(empfangen).message.content, 'los');
    } finally {
      server.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('Beglaubigung', () => {
  // Anthropics Doku, Abschnitt "own-child messages": ein Skript, das in den
  // Socket seiner eigenen Sitzung schreibt, weist sich mit
  // {"type":"auth","token":"..."} als ERSTER Zeile aus. Fehlt der Nachweis,
  // gilt die Nachricht als unbeglaubigt - und eine Sitzung, die Rueckfragen
  // ueberspringt, haelt sie dann zur Freigabe zurueck, statt sie zuzustellen.
  test('der Eintrag traegt Pfad und Token', () => {
    const dir = tempDir();
    try {
      merkeSocket(dir, 'sid-1', '/tmp/a.sock', 'geheim');
      assert.deepEqual(ladeSockets(dir), { 'sid-1': { pfad: '/tmp/a.sock', token: 'geheim' } });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('ohne Token bleibt der Eintrag schlank', () => {
    // Auf Linux beglaubigt der Prozessbaum, dort braucht es keinen Token.
    const dir = tempDir();
    try {
      merkeSocket(dir, 'sid-1', '/tmp/a.sock');
      assert.deepEqual(ladeSockets(dir), { 'sid-1': { pfad: '/tmp/a.sock' } });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  test('die alte Form mit blossem Pfad bleibt lesbar', () => {
    // Sonst verloere jede laufende Sitzung ihren Eintrag in dem Moment, in dem
    // der Bus aktualisiert wird.
    assert.deepEqual(eintrag('/tmp/alt.sock'), { pfad: '/tmp/alt.sock', token: '' });
  });

  test('ein fehlender Eintrag ergibt kein halbes Objekt', () => {
    assert.deepEqual(eintrag(undefined), { pfad: '', token: '' });
  });

  test('der Auth-Frame geht als erste Zeile ueber die Leitung', { skip: WINDOWS }, async () => {
    const dir = tempDir();
    const pfad = join(dir, 'auth.sock');
    const zeilen = [];
    const server = createServer((s) => {
      s.on('data', (d) => zeilen.push(...String(d).split('\n').filter(Boolean)));
    });
    await new Promise((f) => server.listen(pfad, f));
    try {
      assert.equal(await schreibeInSocket(pfad, 'hallo', 'geheim'), '');
      await new Promise((f) => setTimeout(f, 120));
      assert.equal(JSON.parse(zeilen[0]).type, 'auth', 'die erste Zeile muss der Nachweis sein');
      assert.equal(JSON.parse(zeilen[1]).message.content, 'hallo');
    } finally {
      server.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test('ohne Token faengt die Leitung direkt mit der Nachricht an', { skip: WINDOWS }, async () => {
    const dir = tempDir();
    const pfad = join(dir, 'ohne.sock');
    const zeilen = [];
    const server = createServer((s) => {
      s.on('data', (d) => zeilen.push(...String(d).split('\n').filter(Boolean)));
    });
    await new Promise((f) => server.listen(pfad, f));
    try {
      await schreibeInSocket(pfad, 'hallo');
      await new Promise((f) => setTimeout(f, 120));
      assert.equal(JSON.parse(zeilen[0]).type, 'user');
    } finally {
      server.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
