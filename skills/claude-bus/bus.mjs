// Nachrichtenbus zwischen Claude-Instanzen, auch ueber Rechnergrenzen.
//
// Jeder Rechner fuehrt seinen eigenen Bestand. Ein Auftrag an einen Agenten
// auf einem anderen Rechner wird dort per ssh abgelegt (siehe zustellenAn),
// die Quittung nimmt denselben Weg zurueck. Der Absender behaelt eine lokale
// Kopie, damit sein Verlauf vollstaendig bleibt.
//
// Node statt PowerShell, damit derselbe Code auf allen Rechnern laeuft und der
// Stop-Hook (bash) ihn direkt aufrufen kann. Loest bus.ps1 ab.
//
// Ablage, bewusst ausserhalb jedes synchronisierten Bereichs:
//   ~/.claude/bus/<RECHNER>/
//     messages.jsonl      Nachrichten, append-only
//     receipts.jsonl      Quittungen, append-only
//     cursor-<sid>.txt    Lesezeiger je Sitzung
//     zustellungen.jsonl  Protokoll fuer die Kostenmessung
//
// Der Pfad wird vor jedem Zugriff geprueft und der Zugriff verweigert, wenn er
// in Git, einem Cloud-Ordner oder hinter einem Symlink liegt. Fail-closed:
// lieber kein Bus als ein Bus, der Sitzungsinhalte auf andere Rechner traegt.

import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync, statSync, lstatSync, realpathSync } from 'node:fs';
import {
  oeffne, schreibe, ereignisseAb, cursorLesen, cursorSetzen, letzteId,
  auftraege, auftrag, quittungenZu, zahlen, zustandAusCode, importiereJsonl,
} from './speicher.mjs';
import { homedir, hostname } from 'node:os';
import { execFileSync } from 'node:child_process';
import { join, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';

const R = '\x1b[0m', GRAU = '\x1b[38;5;244m', GELB = '\x1b[38;5;221m';
const GRUEN = '\x1b[38;5;77m', ROT = '\x1b[38;5;203m', CYAN = '\x1b[38;5;80m';

// HTTP-Statuscodes als Quittung. Bewusst nur eine Handvoll - der ganze Satz
// waere ein Raetsel statt eines Protokolls.
export const CODES = {
  200: 'erledigt',
  202: 'angenommen, wird bearbeitet',
  204: 'gelesen, nichts zu tun',
  400: 'Nachricht unverstaendlich',
  403: 'darf ich nicht ohne Michaels Freigabe',
  404: 'Ziel nicht gefunden',
  409: 'geht gerade nicht, stecke in etwas anderem',
  500: 'bei der Ausfuehrung schiefgegangen',
  501: 'verstanden, kann ich aber nicht',
  503: 'beschaeftigt, spaeter nochmal',
};

// ---------------------------------------------------------------------------
// Pfade und Schutz
// ---------------------------------------------------------------------------

export function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

export function busWurzel() {
  return process.env.CLAUDE_BUS_DIR || join(homedir(), '.claude', 'bus');
}

export function hostDir() {
  return join(busWurzel(), rechner());
}

/** Sammelt Gruende, warum ein Pfad als Busablage untauglich ist. */
export function pfadProbleme(pfad) {
  const probleme = [];

  if (/[\\/](Dropbox|OneDrive[^\\/]*|Google ?Drive|GoogleDrive|iCloudDrive|Nextcloud|ownCloud|Syncthing|MEGA(sync)?|pCloud)[\\/]/i.test(pfad)) {
    probleme.push('Der Pfad liegt in einem Cloud-Sync-Ordner.');
  }

  // Symlink irgendwo in der Elternkette
  let probe = pfad;
  while (probe) {
    if (existsSync(probe)) {
      try {
        if (lstatSync(probe).isSymbolicLink()) {
          probleme.push(`'${probe}' ist ein Symlink. Das Ziel koennte synchronisiert werden.`);
          break;
        }
      } catch { /* weiter */ }
    }
    const eltern = dirname(probe);
    if (eltern === probe) break;
    probe = eltern;
  }

  // .git in der Elternkette. Kann Verzeichnis oder Datei sein (Worktree).
  let g = pfad;
  while (g) {
    if (existsSync(join(g, '.git'))) {
      probleme.push(`Der Pfad liegt im Git-Repo '${g}'. Ein Commit wuerde Sitzungsinhalte veroeffentlichen.`);
      break;
    }
    const eltern = dirname(g);
    if (eltern === g) break;
    g = eltern;
  }

  return probleme;
}

function sicherstellen() {
  const wurzel = busWurzel();
  const probleme = pfadProbleme(wurzel);
  if (probleme.length) {
    console.error(`\n  ${ROT}BUS BLOCKIERT - der Pfad ist nicht isoliert${R}`);
    console.error(`  ${GRAU}${wurzel}${R}\n`);
    for (const p of probleme) console.error(`  ${GELB}- ${p}${R}`);
    console.error(`\n  ${GRAU}CLAUDE_BUS_DIR auf einen rein lokalen Pfad setzen.${R}\n`);
    process.exit(1);
  }
  const d = hostDir();
  mkdirSync(d, { recursive: true });
  const gi = join(wurzel, '.gitignore');
  if (!existsSync(gi)) writeFileSync(gi, '*\n', 'utf8');
  return d;
}

const pfadMessages = () => join(hostDir(), 'messages.jsonl');
const pfadReceipts = () => join(hostDir(), 'receipts.jsonl');
const pfadZustellungen = () => join(hostDir(), 'zustellungen.jsonl');
const pfadCursor = (sid) => join(hostDir(), `cursor-${String(sid).replace(/[^0-9a-zA-Z-]/g, '_')}.txt`);

// ---------------------------------------------------------------------------
// Datenbank
// ---------------------------------------------------------------------------

let dbHandle = null;

/**
 * Oeffnet die Datenbank beim ersten Zugriff und holt dabei einmalig die alten
 * JSONL-Dateien herein.
 *
 * Der Import ist idempotent (er ueberspringt, was schon drinsteht) und damit
 * bei jedem Start wiederholbar - noetig, solange in der Uebergangsphase noch
 * in beide Speicher geschrieben wird.
 */
function db() {
  if (dbHandle) return dbHandle;
  const d = hostDir();
  mkdirSync(d, { recursive: true });
  dbHandle = oeffne(d);
  try {
    importiereJsonl(dbHandle, d);
  } catch { /* Import ist Komfort, der Betrieb haengt nicht daran */ }
  return dbHandle;
}

/**
 * Bildet eine Auftragszeile auf das alte Nachrichtenformat ab.
 *
 * Damit bleiben Ausgabe, Stop-Hook und der Operator unveraendert, obwohl
 * darunter jetzt eine Zustandsmaschine sitzt. Ein Formatwechsel an dieser
 * Stelle haette drei Aufrufer gleichzeitig gebrochen.
 */
function alsNachricht(z) {
  return {
    id: z.auftrag_id, ts: z.ts, host: z.host,
    from: z.von, fromSession: z.von_session, to: z.an,
    topic: z.topic, text: z.text, quittung: Boolean(z.quittung_erwartet),
    zustand: z.zustand, ereignis: z.id,
  };
}

// ---------------------------------------------------------------------------
// Lesen und Schreiben
// ---------------------------------------------------------------------------

export function zeilen(pfad) {
  if (!existsSync(pfad)) return [];
  return readFileSync(pfad, 'utf8').split('\n').filter((z) => z.trim()).map((z) => {
    try { return JSON.parse(z); } catch { return null; }
  }).filter(Boolean);
}

function anhaengen(pfad, obj) {
  appendFileSync(pfad, JSON.stringify(obj) + '\n', 'utf8');
}

function selbstId() {
  return process.env.CLAUDE_CODE_SESSION_ID || '';
}

/** Instanzname aus der Operator-Namenstabelle, sonst Kurzform der Session-ID. */
export function selbstName(sid = selbstId()) {
  try {
    const t = JSON.parse(readFileSync(join(hostDir(), 'namen.json'), 'utf8'));
    if (t[sid]) return t[sid];
  } catch { /* Notnagel unten */ }
  return sid ? sid.slice(0, 8) : 'unbekannt';
}

function nameZuSession(name) {
  try {
    const t = JSON.parse(readFileSync(join(hostDir(), 'namen.json'), 'utf8'));
    for (const [sid, n] of Object.entries(t)) {
      if (n.toLowerCase() === String(name).toLowerCase()) return sid;
    }
  } catch { /* nichts */ }
  return null;
}

/**
 * Ist die Nachricht fuer mich?
 * 'alle' geht an jeden ausser den Absender, sonst muss Name oder Session-ID passen.
 */
function fuerMich(m, sid, name) {
  if (m.host !== rechner()) return false;
  if (m.fromSession === sid) return false;
  const to = String(m.to || 'alle').toLowerCase();
  return to === 'alle' || to === 'all' || to === String(name).toLowerCase() || to === sid;
}

/**
 * Neue, noch nicht gelesene Nachrichten fuer eine beliebige Sitzung.
 * Ohne Argumente fuer die eigene - mit Argumenten fuer eine fremde, damit der
 * Operator anzeigen kann, wo etwas wartet.
 */
export function offeneNachrichten(sessionId = selbstId(), name = null) {
  const sid = sessionId;
  if (!sid) return { ab: 0, gesamt: 0, neu: [] };
  const d = db();
  const ab = cursorLesen(d, sid);
  const wer = name || selbstName(sid);
  const neu = ereignisseAb(d, ab)
    .filter((z) => z.art === 'auftrag')
    .map(alsNachricht)
    .filter((m) => fuerMich(m, sid, wer));
  return { ab, gesamt: letzteId(d), neu };
}

/**
 * Auftraege, die auf mich warten - unabhaengig vom Lesezeiger.
 *
 * Das ist der eigentliche Gewinn der Umstellung: "gelesen" und "erledigt" sind
 * jetzt zwei verschiedene Dinge. Eine Instanz, die beim Aufwachen hier
 * nachsieht, findet ihre Auftraege auch dann, wenn der Stop-Hook sie nie
 * zugestellt hat - Zustellung ist damit eine Bringschuld des Empfaengers und
 * kein Push mehr, der eine wartende Instanz nie erreicht.
 */
export function offeneAuftraege(sessionId = selbstId(), name = null) {
  const wer = name || selbstName(sessionId);
  return auftraege(db(), {})
    .filter((a) => ['submitted', 'working', 'input_required'].includes(a.zustand))
    .map(alsNachricht)
    .filter((m) => fuerMich(m, sessionId, wer));
}

function cursorMerken(auf) {
  const sid = selbstId();
  if (sid) cursorSetzen(db(), sid, auf);
}

function zeit(iso) {
  try {
    return new Date(iso).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}

// ---------------------------------------------------------------------------
// Zustellung ueber Rechnergrenzen
// ---------------------------------------------------------------------------

const SSH_ZEIT = 20000;

/**
 * Legt ein fertiges Ereignis auf einem anderen Rechner ab.
 *
 * DIE NUTZLAST GEHT UEBER STDIN, nicht als Argument. Ein Auftragstext darf
 * Anfuehrungszeichen, Klammern und Zeilenumbrueche enthalten, und ssh reicht
 * die Argumente als EINEN String an die entfernte Shell weiter - dort zerlegt
 * sie jedes Sonderzeichen neu. Ueber stdin gibt es diese Ebene nicht.
 *
 * Zwei Anlaeufe aus demselben Grund wie in operator.mjs: der blosse Aufruf
 * greift auf Windows, weil der sshd dort den Benutzer-PATH mitbringt. Auf
 * Linux liest eine nicht-interaktive Shell die .bashrc nicht - dort ist
 * "sanctuary" nicht im PATH (am 02.08.2026 auf senza geprueft), erst die
 * Login-Shell findet es.
 *
 * @param {string} host      Zielrechner, wie er in ~/.ssh/config steht.
 * @param {object} ereignis  Fertiges Ereignis fuer schreibe().
 * @returns {string} leer bei Erfolg, sonst die Fehlermeldung.
 */
export function zustellenAn(host, ereignis) {
  const nutzlast = JSON.stringify(ereignis);
  const versuche = ['sanctuary uebernehmen', 'bash -lc "sanctuary uebernehmen"'];
  let letzterFehler = '';
  for (const befehl of versuche) {
    try {
      execFileSync(
        'ssh',
        ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', String(host).toLowerCase(), befehl],
        // stderr abfangen: der erste Anlauf scheitert planmaessig mit
        // "Befehl nicht gefunden", das ist keine Meldung fuer den Anwender.
        { input: nutzlast, encoding: 'utf8', timeout: SSH_ZEIT, stdio: ['pipe', 'pipe', 'pipe'] },
      );
      return '';
    } catch (e) {
      letzterFehler = String(e.stderr || e.message || '').split('\n')[0].trim();
      // Ist der Rechner gar nicht da, bringt der zweite Anlauf nichts.
      if (/connect|timed out|refused|resolve|Host key/i.test(letzterFehler)) break;
    }
  }
  return letzterFehler || 'nicht erreichbar';
}

/**
 * Auf welchem Rechner laeuft dieser Agent?
 *
 * Erst die lokale Namenstabelle - das ist der haeufige Fall und kostet keinen
 * Prozess. Erst wenn der Name hier unbekannt ist, wird das Mesh befragt, und
 * das dauert (ssh an jeden Rechner). Wer den Rechner schon kennt, gibt ihn
 * mit --host mit und spart die Suche ganz.
 *
 * @returns {string|null} Rechnername in Grossbuchstaben, oder null.
 */
export function findeRechner(name) {
  const ziel = String(name).toLowerCase();
  try {
    const t = JSON.parse(readFileSync(join(hostDir(), 'namen.json'), 'utf8'));
    if (Object.values(t).some((n) => String(n).toLowerCase() === ziel)) return rechner();
  } catch { /* keine Namenstabelle, dann eben ueber das Mesh */ }

  try {
    // fileURLToPath statt URL.pathname: unter Windows liefert pathname
    // "/C:/Users/..." mit fuehrendem Schraegstrich, den node nicht oeffnet.
    const operator = join(dirname(fileURLToPath(import.meta.url)), '..', 'operator', 'operator.mjs');
    const roh = execFileSync(
      process.execPath,
      [operator, 'status', '--mesh', '--json'],
      { encoding: 'utf8', timeout: 40000, maxBuffer: 8 * 1024 * 1024 },
    );
    for (const zweig of JSON.parse(roh).rechner || []) {
      for (const i of zweig.instanzen || []) {
        if (String(i.name).toLowerCase() === ziel) {
          return String(zweig.rechner || zweig.host).toUpperCase();
        }
      }
    }
  } catch { /* Mesh nicht verfuegbar - der Aufrufer entscheidet */ }
  return null;
}

// ---------------------------------------------------------------------------
// Befehle
// ---------------------------------------------------------------------------

/**
 * Nimmt ein von einem anderen Rechner zugestelltes Ereignis entgegen.
 *
 * Gegenstueck zu zustellenAn(). Liest genau ein JSON-Ereignis von stdin und
 * legt es unveraendert ab - Absender, Zeitstempel und Auftrags-ID bleiben also
 * die des Ursprungsrechners, sonst liessen sich die beiden Kopien nicht mehr
 * als derselbe Auftrag erkennen.
 */
function cmdUebernehmen() {
  sicherstellen();
  let ereignis;
  try {
    ereignis = JSON.parse(readFileSync(0, 'utf8'));
  } catch (fehler) {
    console.error(`${ROT}Keine lesbare Nutzlast auf stdin: ${fehler.message}${R}`);
    process.exit(1);
  }
  if (!ereignis || !ereignis.auftrag_id || !ereignis.art) {
    console.error(`${ROT}Nutzlast ohne auftrag_id oder art.${R}`);
    process.exit(1);
  }

  // Doppelt zugestellt wird nichts abgelegt. Ohne die Pruefung erzeugte jede
  // Wiederholung ein zweites Ereignis zur selben Auftrags-ID.
  const d = db();
  const schon = ereignis.art === 'auftrag'
    ? Boolean(auftrag(d, ereignis.auftrag_id))
    : quittungenZu(d, ereignis.auftrag_id).some((q) => q.ts === ereignis.ts);
  if (schon) {
    console.log(JSON.stringify({ ok: true, auftrag_id: ereignis.auftrag_id, doppelt: true }));
    return;
  }

  schreibe(d, ereignis);
  console.log(JSON.stringify({ ok: true, auftrag_id: ereignis.auftrag_id, host: rechner() }));
}

function cmdSend(argv) {
  sicherstellen();
  const to = argv[0];

  // Flags MIT Wert muessen samt Wert uebersprungen werden, sonst landet der
  // Wert im Nachrichtentext (genau so beim ersten Test passiert).
  const mitWert = new Set(['--topic', '--host', '--von']);
  const worte = [];
  for (let i = 1; i < argv.length; i++) {
    if (mitWert.has(argv[i])) { i++; continue; }
    if (argv[i].startsWith('--')) continue;
    worte.push(argv[i]);
  }
  const text = worte.join(' ');

  if (!to || !text) {
    console.error('Nutzung: bus.mjs send <Name|alle> "Text" [--topic thema] [--host RECHNER] [--von Name] [--erwartet-quittung]');
    process.exit(1);
  }
  const wert = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : null;
  };

  // Wer sendet: --von schlaegt die Sitzungserkennung. Noetig fuer Aufrufer
  // ohne eigene Claude-Sitzung - die TUI etwa lief bisher als "unbekannt",
  // weil CLAUDE_CODE_SESSION_ID dort nicht gesetzt ist.
  const vonName = wert('--von') || selbstName();
  const rundruf = ['alle', 'all'].includes(String(to).toLowerCase());

  // Wohin: --host spart die Suche. Der Rundruf bleibt bewusst lokal - "alle"
  // ueber alle Rechner waere ein anderer Vorgang und braucht eine eigene
  // Entscheidung, keine stille Ausweitung.
  const zielHost = rundruf
    ? rechner()
    : String(wert('--host') || findeRechner(to) || rechner()).toUpperCase();

  const topicIdx = argv.indexOf('--topic');
  const nachricht = {
    id: randomBytes(5).toString('hex'),
    ts: new Date().toISOString(),
    host: zielHost,
    vonHost: rechner(),
    from: vonName,
    fromSession: selbstId(),
    cwd: process.cwd(),
    to,
    topic: topicIdx >= 0 ? argv[topicIdx + 1] : 'allgemein',
    text,
    quittung: argv.includes('--erwartet-quittung'),
  };
  const ereignis = {
    auftrag_id: nachricht.id, ts: nachricht.ts, art: 'auftrag',
    host: zielHost, von_host: nachricht.vonHost,
    von: nachricht.from, von_session: nachricht.fromSession, an: to,
    zustand: 'submitted', topic: nachricht.topic, text,
    quittung_erwartet: nachricht.quittung, cwd: nachricht.cwd,
  };

  // Immer auch lokal ablegen, selbst wenn der Empfaenger woanders sitzt: nur
  // so sieht der Absender seinen eigenen Verlauf und spaeter die Quittung.
  // Zugestellt wird die Kopie hier NICHT - dafuer sorgt host = Zielrechner.
  schreibe(db(), ereignis);
  // Uebergangsphase: JSONL laeuft parallel weiter, bis die Umstellung auf
  // allen Rechnern steht. Erst danach faellt diese Zeile weg.
  anhaengen(pfadMessages(), nachricht);

  if (zielHost !== rechner()) {
    const fehler = zustellenAn(zielHost, ereignis);
    if (fehler) {
      console.error(`${ROT}Nicht zugestellt an ${zielHost}: ${fehler}${R}`);
      console.error(`${GRAU}Der Auftrag steht lokal (id ${nachricht.id}), ${to} sieht ihn aber nicht.${R}`);
      process.exit(1);
    }
    console.log(`${GRUEN}Gesendet an ${to}${R} ${GRAU}auf ${zielHost} (id ${nachricht.id})${R}`);
  } else {
    console.log(`${GRUEN}Gesendet an ${to}${R}  ${GRAU}(id ${nachricht.id})${R}`);
  }
  if (nachricht.quittung) console.log(`${GRAU}Quittung erwartet - Stand mit: bus.mjs offen${R}`);
}

function cmdRead(argv) {
  sicherstellen();
  const alles = argv.includes('--alle');
  const { gesamt, neu } = offeneNachrichten();
  const zuZeigen = alles
    ? ereignisseAb(db(), 0).filter((z) => z.art === 'auftrag').map(alsNachricht)
      .filter((m) => fuerMich(m, selbstId(), selbstName()))
    : neu;

  cursorMerken(gesamt);

  if (!zuZeigen.length) {
    console.log(`${GRAU}Keine neuen Nachrichten.${R}`);
    return;
  }
  console.log(`\n${CYAN}${zuZeigen.length} Nachricht(en) fuer ${selbstName()}${R}\n`);
  for (const m of zuZeigen) {
    console.log(`  ${GELB}[${zeit(m.ts)}] ${m.from} -> ${m.to}${R}  ${GRAU}(${m.topic}, id ${m.id})${R}`);
    console.log(`  ${m.text}`);
    if (m.quittung) {
      console.log(`  ${GRAU}Quittung erwartet:  node bus.mjs ack ${m.id} 200 "kurze Notiz"${R}`);
    }
    console.log('');
  }
}

function cmdAck(argv) {
  sicherstellen();
  const msgId = argv[0];
  const code = parseInt(argv[1], 10);
  const notiz = argv.slice(2).join(' ');
  if (!msgId || !Number.isFinite(code)) {
    console.error('Nutzung: bus.mjs ack <Nachrichten-ID> <HTTP-Code> ["Notiz"]');
    console.error('Codes: ' + Object.entries(CODES).map(([c, t]) => `${c}=${t}`).join(', '));
    process.exit(1);
  }
  const zeile = auftrag(db(), msgId);
  if (!zeile) {
    console.error(`${ROT}Keine Nachricht mit ID ${msgId}.${R}`);
    process.exit(1);
  }
  const nachricht = alsNachricht(zeile);
  const quittung = {
    id: randomBytes(4).toString('hex'),
    msgId,
    ts: new Date().toISOString(),
    host: rechner(),
    from: selbstName(),
    fromSession: selbstId(),
    an: nachricht.from,
    status: code,
    bedeutung: CODES[code] || 'unbekannter Code',
    notiz,
  };
  const neuerZustand = zustandAusCode(code);
  const ereignis = {
    auftrag_id: msgId, ts: quittung.ts, art: 'quittung', host: quittung.host,
    von_host: rechner(), von: quittung.from, von_session: quittung.fromSession,
    an: nachricht.from, zustand: neuerZustand, status: code, notiz,
    nutzlast: { id: quittung.id, bedeutung: quittung.bedeutung },
  };
  schreibe(db(), ereignis);
  anhaengen(pfadReceipts(), quittung); // Uebergangsphase, siehe cmdSend
  const farbe = code < 300 ? GRUEN : code < 500 ? GELB : ROT;
  console.log(`${farbe}${code} ${quittung.bedeutung}${R}  ${GRAU}an ${nachricht.from} (msg ${msgId})${R}`);
  console.log(`${GRAU}Auftrag ${msgId} steht jetzt auf ${neuerZustand}${R}`);

  // Kam der Auftrag von einem anderen Rechner, muss die Quittung dorthin
  // zurueck - sonst bleibt er beim Absender auf ewig "abgelegt" stehen.
  // Das Ereignis behaelt host = hier, damit drueben erkennbar bleibt, wo
  // quittiert wurde. Es wird dort ueber die Auftrags-ID zugeordnet.
  const zurueck = String(zeile.von_host || '').toUpperCase();
  if (zurueck && zurueck !== rechner()) {
    const fehler = zustellenAn(zurueck, ereignis);
    if (fehler) {
      console.error(`${GELB}Quittung nicht nach ${zurueck} gemeldet: ${fehler}${R}`);
      console.error(`${GRAU}Lokal ist sie vermerkt - ${nachricht.from} sieht sie aber noch nicht.${R}`);
    } else {
      console.log(`${GRAU}Quittung an ${zurueck} gemeldet.${R}`);
    }
  }
}

function cmdOffen() {
  sicherstellen();
  const meine = auftraege(db(), {})
    .filter((a) => a.von_session === selbstId() && a.quittung_erwartet)
    .map(alsNachricht);
  const quittungen = meine.flatMap((m) => quittungenZu(db(), m.id).map((q) => ({
    msgId: q.auftrag_id, status: q.status, from: q.von, notiz: q.notiz,
    bedeutung: CODES[q.status] || 'unbekannter Code',
  })));
  if (!meine.length) {
    console.log(`${GRAU}Keine Nachrichten von dir, die eine Quittung erwarten.${R}`);
    return;
  }
  console.log(`\n${CYAN}Deine Nachrichten mit Quittungserwartung${R}\n`);
  for (const m of meine) {
    const q = quittungen.filter((x) => x.msgId === m.id);
    const kopf = `  ${GRAU}[${zeit(m.ts)}]${R} an ${m.to}: ${m.text.slice(0, 60)}`;
    if (!q.length) {
      console.log(`${kopf}\n    ${GELB}offen - keine Quittung${R}\n`);
      continue;
    }
    console.log(kopf);
    for (const x of q) {
      const farbe = x.status < 300 ? GRUEN : x.status < 500 ? GELB : ROT;
      console.log(`    ${farbe}${x.status}${R} ${x.bedeutung}${x.notiz ? ` - ${x.notiz}` : ''} ${GRAU}(${x.from})${R}`);
    }
    console.log('');
  }
}

/**
 * Zeigt die Warteschlange: was liegt fuer mich an, was habe ich vergeben.
 *
 * Anders als "read" haengt das NICHT am Lesezeiger. Ein Auftrag verschwindet
 * hier erst, wenn er quittiert ist - deshalb findet eine Instanz ihre Arbeit
 * auch dann, wenn sie beim Zustellversuch geschlafen hat.
 */
function cmdAuftraege(argv) {
  sicherstellen();
  const alle = argv.includes('--alle');
  const d = db();
  const liste = alle ? auftraege(d, {}) : auftraege(d, {}).filter((a) => ['submitted', 'working', 'input_required'].includes(a.zustand));

  const meine = liste.filter((a) => fuerMich(alsNachricht(a), selbstId(), selbstName()));
  const vergeben = liste.filter((a) => a.von_session === selbstId());

  if (argv.includes('--json')) {
    console.log(JSON.stringify({
      rechner: rechner(), ich: selbstName(), zeit: new Date().toISOString(),
      meine, vergeben,
    }, null, 1));
    return;
  }

  const farbeZustand = (z) => (z === 'completed' ? GRUEN : z === 'failed' || z === 'cancelled' ? ROT : GELB);
  const zeigen = (titel, eintraege) => {
    if (!eintraege.length) return;
    console.log(`\n${CYAN}${titel}${R}\n`);
    for (const a of eintraege) {
      console.log(`  ${farbeZustand(a.zustand)}${a.zustand.padEnd(15)}${R}${GRAU}${zeit(a.erstellt)}  ${a.von} -> ${a.an}  (${a.topic}, id ${a.auftrag_id})${R}`);
      console.log(`  ${String(a.text || '').slice(0, 100)}`);
    }
  };

  zeigen(`Fuer ${selbstName()}`, meine);
  zeigen('Von dir vergeben', vergeben);
  if (!meine.length && !vergeben.length) {
    console.log(`${GRAU}Nichts offen.${alle ? '' : ' Mit --alle auch erledigte anzeigen.'}${R}`);
    return;
  }
  console.log(`\n${GRAU}Annehmen: bus.mjs ack <id> 202   Erledigt: bus.mjs ack <id> 200 "Notiz"${R}\n`);
}

/**
 * Zeigt den Auftragsverlauf mit einem bestimmten Agenten.
 *
 * Gedacht als Datenquelle fuer die Verlaufsansicht der Oberflaeche: je Auftrag
 * die Anweisung plus alle Quittungen, aufsteigend nach Zeit. Beruecksichtigt
 * beide Richtungen - was ich geschickt habe und was von dort kam.
 *
 * @param {string[]} argv
 * Name des Agenten, dazu optional --json.
 */
function cmdVerlauf(argv) {
  sicherstellen();
  const alsJson = argv.includes('--json');
  const name = argv.find((a) => !a.startsWith('--'));
  if (!name) {
    console.error('Aufruf: bus.mjs verlauf <Name> [--json]');
    process.exitCode = 1;
    return;
  }

  const d = db();
  const liste = auftraege(d, {})
    .filter((a) => a.an === name || a.von === name)
    .sort((x, y) => String(x.erstellt).localeCompare(String(y.erstellt)))
    .map((a) => ({ ...a, quittungen: quittungenZu(d, a.auftrag_id) }));

  if (alsJson) {
    console.log(JSON.stringify({
      rechner: rechner(), ich: selbstName(), partner: name,
      zeit: new Date().toISOString(), auftraege: liste,
    }, null, 1));
    return;
  }

  if (!liste.length) {
    console.log(`${GRAU}Kein Verlauf mit ${name}.${R}`);
    return;
  }
  const farbeZustand = (z) => (z === 'completed' ? GRUEN : z === 'failed' || z === 'cancelled' ? ROT : GELB);
  console.log(`\n${CYAN}Verlauf mit ${name}${R}\n`);
  for (const a of liste) {
    console.log(`  ${GRAU}${zeit(a.erstellt)}  ${a.von} -> ${a.an}${R}  ${farbeZustand(a.zustand)}${a.zustand}${R}`);
    console.log(`  ${String(a.text || '')}`);
    for (const q of a.quittungen) {
      console.log(`    ${GRAU}${zeit(q.ts)}${R}  ${q.status ?? ''} ${q.notiz || ''}`);
    }
    console.log('');
  }
}

function cmdDoctor() {
  const wurzel = busWurzel();
  const probleme = pfadProbleme(wurzel);
  console.log(`\n${CYAN}Bus-Diagnose${R}\n`);
  console.log(`  Rechner      ${rechner()}`);
  console.log(`  Wurzel       ${wurzel}`);
  console.log(`  Host-Zweig   ${hostDir()}`);
  console.log(`  Sitzung      ${selbstId() || '-'} (${selbstName()})`);
  console.log(probleme.length
    ? `  Isolation    ${ROT}BLOCKIERT${R}\n${probleme.map((p) => `               ${GELB}- ${p}${R}`).join('\n')}`
    : `  Isolation    ${GRUEN}OK - der Pfad wird nicht synchronisiert${R}`);
  if (!probleme.length) {
    const z = zahlen(db());
    console.log(`  Datenbank    ${join(hostDir(), 'bus.db')}`);
    console.log(`  Ereignisse   ${z.ereignisse}`);
    console.log(`  Auftraege    ${z.auftraege}, davon offen ${z.offen}`);
    console.log(`  Altbestand   ${zeilen(pfadMessages()).length} Nachrichten / ${zeilen(pfadReceipts()).length} Quittungen in JSONL`);
  }
  console.log('');
}

/** Wird vom Stop-Hook benutzt: nur die Anzahl offener Nachrichten, sonst nichts. */
function cmdPending() {
  const wurzel = busWurzel();
  if (pfadProbleme(wurzel).length) process.exit(0);
  const { gesamt, neu } = offeneNachrichten();
  if (!neu.length) process.exit(0);

  // Zustellung protokollieren, damit die Kosten spaeter messbar sind.
  const hinweis = neu.length === 1
    ? `Eine Nachricht von ${neu[0].from} liegt fuer dich im Bus (Thema: ${neu[0].topic}).`
    : `${neu.length} Nachrichten liegen fuer dich im Bus.`;
  const text = `${hinweis} Abholen mit: node ~/.claude/skills/claude-bus/bus.mjs read`;

  try {
    mkdirSync(hostDir(), { recursive: true });
    anhaengen(pfadZustellungen(), {
      ts: new Date().toISOString(),
      session: selbstId(),
      name: selbstName(),
      anzahl: neu.length,
      msgIds: neu.map((m) => m.id),
      zeichen: text.length,
      cursorVor: gesamt - neu.length,
    });
  } catch { /* Protokoll ist Komfort */ }

  process.stdout.write(text);
  process.exit(0);
}

function hilfe() {
  console.log(`
  Bus - Nachrichten zwischen Claude-Instanzen auf diesem Rechner

    send <Name|alle> "Text" [--topic t] [--erwartet-quittung]
    read [--alle]                 neue Nachrichten holen (schiebt den Lesezeiger)
    auftraege [--alle] [--json]   Warteschlange - was liegt an, unabhaengig vom Lesezeiger
    verlauf <Name> [--json]       Auftraege und Quittungen mit einem Agenten
    ack <msgId> <Code> ["Notiz"]  quittieren, setzt zugleich den Auftragszustand
    offen                         Stand der eigenen Nachrichten
    doctor                        Pfad-Isolation und Datenbank pruefen
    pending                       nur fuer den Stop-Hook

  Zustaende: submitted -> working (202) -> completed (2xx) | failed (4xx/5xx)
             409 und 503 setzen zurueck auf submitted, der Auftrag bleibt liegen

  Quittungscodes
${Object.entries(CODES).map(([c, t]) => `    ${c}  ${t}`).join('\n')}
`);
}

// Nur ausfuehren, wenn direkt aufgerufen. Der Operator importiert dieses Modul,
// um offene Nachrichten fremder Sitzungen zu zaehlen - dabei darf die CLI nicht
// losrennen.
// argv[1] ueber realpathSync aufloesen: ~/.claude/skills ist ein Symlink ins
// Repo claude-config, waehrend import.meta.url immer den aufgeloesten Pfad
// liefert. Ohne das war der Vergleich immer falsch und die CLI blieb stumm.
const direktAufgerufen = process.argv[1]
  && pathToFileURL(aufgeloest(process.argv[1])).href === import.meta.url;

/** Loest Symlinks auf, gibt bei Fehler den Ausgangspfad zurueck. */
function aufgeloest(pfad) {
  try {
    return realpathSync(pfad);
  } catch {
    return pfad;
  }
}

if (direktAufgerufen) {
  const argv = process.argv.slice(2);
  switch (argv[0]) {
    case 'send': cmdSend(argv.slice(1)); break;
    case 'uebernehmen': cmdUebernehmen(); break;
    case 'read': cmdRead(argv.slice(1)); break;
    case 'ack': cmdAck(argv.slice(1)); break;
    case 'auftraege': case 'auftrag': cmdAuftraege(argv.slice(1)); break;
    case 'verlauf': cmdVerlauf(argv.slice(1)); break;
    case 'offen': cmdOffen(); break;
    case 'doctor': cmdDoctor(); break;
    case 'pending': cmdPending(); break;
    default: hilfe();
  }
}
