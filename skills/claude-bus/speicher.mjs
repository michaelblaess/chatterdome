// SQLite-Speicher fuer den Bus.
//
// WARUM NICHT WEITER JSONL: append-only ist bei mehreren Schreibern nur unter
// Linux sicher. Gemessen am 01.08.2026 mit acht parallelen Prozessen auf
// Windows - reines Node 0 Verluste, reines Python 240 von 3.200 Zeilen weg
// (7,5 %) und 49 zerrissene Zeilen. Ursache ist die Microsoft-CRT, die
// O_APPEND als lseek(SEEK_END) plus write() umsetzt (bugs.python.org/issue42606).
// POSIX garantiert ohnehin nur das Offset-Setzen, nicht die Unteilbarkeit der
// Nutzdaten - die verbreitete PIPE_BUF-Annahme gilt nur fuer Pipes.
//
// Der Bus ist heute also nur zufaellig heil, weil ausschliesslich Node
// schreibt. Die geplante Python-TUI wuerde still Daten zerstoeren.
//
// SQLite ist in Node 22+ und Python 3.13 eingebaut - kein Dienst, keine
// Abhaengigkeit, damit auch auf dem Kunden-Rechner zulaessig.

import './still.mjs'; // MUSS vor node:sqlite stehen, siehe dort
import { DatabaseSync } from 'node:sqlite';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Oeffnet die Bus-Datenbank und legt das Schema an, falls noetig.
 *
 * Die drei PRAGMAs sind Pflicht, nicht Geschmack:
 * - WAL, damit Leser und Schreiber sich nicht gegenseitig sperren.
 * - busy_timeout, sonst scheitern parallele Schreibvorgaenge sofort. Gemessen
 *   mit acht Prozessen: ohne den Wert kamen 1.022 von 9.000 Inserts an
 *   (89 % "database is locked"), mit 5000 ms alle 16.000 von 16.000.
 * - synchronous=NORMAL, der uebliche Kompromiss unter WAL.
 *
 * ACHTUNG: WAL funktioniert nicht auf Netzlaufwerken. Liegt ~/.claude per
 * Profil-Umleitung oder Cloud-Sync auf einem solchen, ist das vorher zu
 * pruefen.
 *
 * @param {string} verzeichnis
 * Host-Zweig des Bus, also .../bus/<RECHNER>.
 */
export function oeffne(verzeichnis) {
  const db = new DatabaseSync(join(verzeichnis, 'bus.db'));
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous  = NORMAL;
    PRAGMA busy_timeout = 5000;

    CREATE TABLE IF NOT EXISTS ereignis (
      id          INTEGER PRIMARY KEY,
      auftrag_id  TEXT NOT NULL,
      ts          TEXT NOT NULL,
      art         TEXT NOT NULL,
      host        TEXT NOT NULL,
      von_host    TEXT,
      von         TEXT,
      von_session TEXT,
      an          TEXT,
      zustand     TEXT,
      topic       TEXT,
      text        TEXT,
      status      INTEGER,
      notiz       TEXT,
      cwd         TEXT,
      nutzlast    TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_ereignis_auftrag ON ereignis(auftrag_id, id);
    CREATE INDEX IF NOT EXISTS ix_ereignis_ts      ON ereignis(ts);

    CREATE TABLE IF NOT EXISTS auftrag (
      auftrag_id        TEXT PRIMARY KEY,
      zustand           TEXT NOT NULL,
      host              TEXT NOT NULL,
      von_host          TEXT,
      von               TEXT,
      von_session       TEXT,
      an                TEXT,
      topic             TEXT,
      text              TEXT,
      quittung_erwartet INTEGER NOT NULL DEFAULT 0,
      erstellt          TEXT NOT NULL,
      geaendert         TEXT NOT NULL,
      letztes_ereignis  INTEGER
    );
    CREATE INDEX IF NOT EXISTS ix_auftrag_zustand ON auftrag(zustand, an);

    CREATE TABLE IF NOT EXISTS cursor (
      sitzung     TEXT PRIMARY KEY,
      gelesen_bis INTEGER NOT NULL
    );
  `);
  nachruesten(db);
  return db;
}

/**
 * Ergaenzt Spalten, die spaeter dazugekommen sind.
 *
 * NOETIG, WEIL "CREATE TABLE IF NOT EXISTS" eine bereits vorhandene Tabelle
 * unangetastet laesst - auf jedem Rechner, der den Bus schon benutzt hat,
 * fehlte die neue Spalte sonst still, und erst das INSERT wuerde scheitern.
 *
 * @param {import('node:sqlite').DatabaseSync} db
 */
function nachruesten(db) {
  const spalten = (tabelle) =>
    new Set(db.prepare(`PRAGMA table_info(${tabelle})`).all().map((s) => s.name));
  for (const tabelle of ['ereignis', 'auftrag']) {
    if (!spalten(tabelle).has('von_host')) {
      db.exec(`ALTER TABLE ${tabelle} ADD COLUMN von_host TEXT`);
    }
  }
}

/**
 * Die Zustaende eines Auftrags.
 *
 * Uebernommen aus dem A2A-Vokabular statt selbst erfunden - dieselben Begriffe
 * benutzen CrewAI und verwandte Systeme, das erspart spaeter Uebersetzungen.
 */
export const ZUSTAENDE = ['submitted', 'working', 'input_required', 'completed', 'failed', 'cancelled'];

/** Aus welchem Quittungscode welcher Folgezustand wird. */
export function zustandAusCode(code) {
  if (code >= 200 && code < 300) return code === 202 ? 'working' : 'completed';
  if (code === 409 || code === 503) return 'submitted'; // spaeter nochmal
  return 'failed';
}

/**
 * Schreibt ein Ereignis und zieht die Auftragstabelle nach.
 *
 * ZUR BEDEUTUNG VON host UND von_host: ``host`` ist der Rechner des
 * EMPFAENGERS, nicht der des Erzeugers - nur so findet ein Agent seine
 * Auftraege, wenn sie von einem anderen Rechner kamen. ``von_host`` haelt
 * fest, wohin die Quittung zurueckgeht. Vorher trug ``host`` den Erzeuger,
 * und genau daran ist die rechneruebergreifende Zustellung gescheitert: ein
 * auf RAINBOW abgelegter Auftrag an Franko@SENZA blieb dort liegen.
 *
 * Beides in EINER Transaktion mit BEGIN IMMEDIATE. Ohne das Schluesselwort
 * beginnt SQLite eine Lesetransaktion und muss sie beim ersten Schreibbefehl
 * hochstufen - schlaegt das fehl, kommt SQLITE_BUSY_SNAPSHOT zurueck, und zwar
 * unabhaengig vom busy_timeout.
 *
 * @returns {number} die vergebene Ereignis-ID.
 */
export function schreibe(db, e) {
  const jetzt = new Date().toISOString();
  db.exec('BEGIN IMMEDIATE');
  try {
    const einfuegen = db.prepare(`
      INSERT INTO ereignis (auftrag_id, ts, art, host, von_host, von, von_session, an, zustand, topic, text, status, notiz, cwd, nutzlast)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const r = einfuegen.run(
      e.auftrag_id, e.ts || jetzt, e.art, e.host, e.von_host ?? null,
      e.von ?? null, e.von_session ?? null, e.an ?? null, e.zustand ?? null,
      e.topic ?? null, e.text ?? null, e.status ?? null, e.notiz ?? null,
      e.cwd ?? null, e.nutzlast ? JSON.stringify(e.nutzlast) : null,
    );
    const id = Number(r.lastInsertRowid);

    if (e.art === 'auftrag') {
      db.prepare(`
        INSERT INTO auftrag (auftrag_id, zustand, host, von_host, von, von_session, an, topic, text, quittung_erwartet, erstellt, geaendert, letztes_ereignis)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(auftrag_id) DO UPDATE SET zustand = excluded.zustand, geaendert = excluded.geaendert, letztes_ereignis = excluded.letztes_ereignis
      `).run(
        e.auftrag_id, e.zustand || 'submitted', e.host, e.von_host ?? null,
        e.von ?? null, e.von_session ?? null, e.an ?? null,
        e.topic ?? null, e.text ?? null, e.quittung_erwartet ? 1 : 0,
        e.ts || jetzt, e.ts || jetzt, id,
      );
    } else if (e.zustand) {
      db.prepare(`
        UPDATE auftrag SET zustand = ?, geaendert = ?, letztes_ereignis = ? WHERE auftrag_id = ?
      `).run(e.zustand, e.ts || jetzt, id, e.auftrag_id);
    }

    db.exec('COMMIT');
    return id;
  } catch (fehler) {
    db.exec('ROLLBACK');
    throw fehler;
  }
}

/** Alle Ereignisse ab einer Ereignis-ID, aufsteigend. Das ist der Pull. */
export function ereignisseAb(db, ab = 0) {
  return db.prepare('SELECT * FROM ereignis WHERE id > ? ORDER BY id').all(ab);
}

export function cursorLesen(db, sitzung) {
  const r = db.prepare('SELECT gelesen_bis FROM cursor WHERE sitzung = ?').get(sitzung);
  return r ? Number(r.gelesen_bis) : 0;
}

export function cursorSetzen(db, sitzung, bis) {
  db.prepare(`
    INSERT INTO cursor (sitzung, gelesen_bis) VALUES (?, ?)
    ON CONFLICT(sitzung) DO UPDATE SET gelesen_bis = excluded.gelesen_bis
  `).run(sitzung, bis);
}

/** Hoechste vergebene Ereignis-ID. Fuer "alles als gelesen markieren". */
export function letzteId(db) {
  const r = db.prepare('SELECT COALESCE(MAX(id), 0) AS m FROM ereignis').get();
  return Number(r.m);
}

export function auftraege(db, { zustand = null, an = null } = {}) {
  let sql = 'SELECT * FROM auftrag';
  const wo = [];
  const werte = [];
  if (zustand) { wo.push('zustand = ?'); werte.push(zustand); }
  if (an) { wo.push('lower(an) = lower(?)'); werte.push(an); }
  if (wo.length) sql += ` WHERE ${wo.join(' AND ')}`;
  return db.prepare(`${sql} ORDER BY geaendert DESC`).all(...werte);
}

export function auftrag(db, id) {
  return db.prepare('SELECT * FROM auftrag WHERE auftrag_id = ?').get(id);
}

/** Alle Quittungen zu einem Auftrag, aelteste zuerst. */
export function quittungenZu(db, auftragId) {
  return db.prepare("SELECT * FROM ereignis WHERE art = 'quittung' AND auftrag_id = ? ORDER BY id").all(auftragId);
}

/** Kennzahlen fuer die Diagnose. */
export function zahlen(db) {
  const eine = (sql) => Number(db.prepare(sql).get().n);
  return {
    ereignisse: eine('SELECT COUNT(*) AS n FROM ereignis'),
    auftraege: eine('SELECT COUNT(*) AS n FROM auftrag'),
    offen: eine("SELECT COUNT(*) AS n FROM auftrag WHERE zustand IN ('submitted','working','input_required')"),
  };
}

/**
 * Uebernimmt die vorhandenen JSONL-Dateien in die Datenbank.
 *
 * Idempotent ueber die Ereignis-IDs der Altdaten: eine Nachricht, die schon
 * als Auftrag steht, wird uebersprungen. Deshalb darf der Import mehrfach
 * laufen, ohne zu verdoppeln - das ist wichtig, weil er in der Uebergangsphase
 * bei jedem Start aufgerufen wird.
 *
 * @returns {{auftraege: number, quittungen: number}}
 */
export function importiereJsonl(db, verzeichnis) {
  const lies = (name) => {
    const p = join(verzeichnis, name);
    if (!existsSync(p)) return [];
    return readFileSync(p, 'utf8').split('\n').filter((z) => z.trim())
      .map((z) => { try { return JSON.parse(z); } catch { return null; } })
      .filter(Boolean);
  };

  const vorhanden = new Set(db.prepare('SELECT auftrag_id FROM auftrag').all().map((r) => r.auftrag_id));
  const quittiert = new Set(
    db.prepare("SELECT nutzlast FROM ereignis WHERE art = 'quittung'").all()
      .map((r) => { try { return JSON.parse(r.nutzlast || '{}').id; } catch { return null; } })
      .filter(Boolean),
  );

  let auftraegeNeu = 0;
  for (const m of lies('messages.jsonl')) {
    if (!m.id || vorhanden.has(m.id)) continue;
    schreibe(db, {
      auftrag_id: m.id, ts: m.ts, art: 'auftrag', host: m.host || '',
      von: m.from, von_session: m.fromSession, an: m.to,
      zustand: 'submitted', topic: m.topic, text: m.text,
      quittung_erwartet: m.quittung, cwd: m.cwd,
    });
    auftraegeNeu += 1;
  }

  let quittungenNeu = 0;
  for (const q of lies('receipts.jsonl')) {
    if (!q.id || quittiert.has(q.id)) continue;
    schreibe(db, {
      auftrag_id: q.msgId, ts: q.ts, art: 'quittung', host: q.host || '',
      von: q.from, von_session: q.fromSession, an: q.an,
      zustand: zustandAusCode(q.status), status: q.status, notiz: q.notiz,
      nutzlast: { id: q.id, bedeutung: q.bedeutung },
    });
    quittungenNeu += 1;
  }

  return { auftraege: auftraegeNeu, quittungen: quittungenNeu };
}
