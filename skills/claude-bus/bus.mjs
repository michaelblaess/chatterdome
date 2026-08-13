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
  auftraege, auftrag, quittungenZu, zahlen, zustandAusCode, importiereJsonl, OFFEN,
} from './speicher.mjs';
import { verfallen, fehlgeleitete, VERFALLEN, EMPFAENGER_WEG } from './pacht.mjs';
import { einstellung, alleEinstellungen, setzeEinstellung, einstellungsDatei } from './einstellungen.mjs';
import { sofortZustellen, sockelFaehig } from './socket.mjs';
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
  400: 'Nachricht unverständlich',
  403: 'darf ich nicht ohne Michaels Freigabe',
  404: 'Ziel nicht gefunden',
  408: 'verfallen - lag zu lange offen',
  409: 'geht gerade nicht, stecke in etwas anderem',
  410: 'Empfänger gibt es nicht mehr',
  500: 'bei der Ausführung schiefgegangen',
  501: 'verstanden, kann ich aber nicht',
  503: 'beschäftigt, später nochmal',
};

/**
 * Codes, die der Bus selbst vergibt. Sie stehen in CODES, damit die Anzeige sie
 * benennen kann - von Hand quittiert werden sollen sie aber nicht.
 */
const SELBSTCODES = new Set([VERFALLEN, EMPFAENGER_WEG]);

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
          probleme.push(`'${probe}' ist ein Symlink. Das Ziel könnte synchronisiert werden.`);
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
      probleme.push(`Der Pfad liegt im Git-Repo '${g}'. Ein Commit würde Sitzungsinhalte veröffentlichen.`);
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
  // Der Kehrbesen laeuft bei JEDEM Oeffnen, damit kein Aufrufer ihn vergessen
  // kann. Er liest zuerst und schreibt nur, wenn wirklich etwas abgelaufen ist -
  // sonst zoege der Stop-Hook nach jeder Antwort die Schreibsperre.
  try {
    verfallen(dbHandle);
  } catch { /* Ein Kehrbesen, der stolpert, darf den Bus nicht anhalten */ }
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
    // Die Funktion bekommt zwei verschiedene Zeilenarten: aus "ereignis"
    // (Spalte ts) und aus "auftrag" (Spalte erstellt, kein ts). Ohne den
    // Rueckfall stand in der offen-Ansicht "[Invalid Date]", weil z.ts dort
    // schlicht fehlt - siehe zeit().
    id: z.auftrag_id, ts: z.ts ?? z.erstellt, host: z.host,
    from: z.von, fromSession: z.von_session, to: z.an,
    toSession: z.an_session, bindung: z.bindung,
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

/**
 * Die Zuordnung Session-ID zu Name, wie der SessionStart-Hook sie fuehrt.
 *
 * Eine Stelle, die diese Datei liest - vorher stand der Lesevorgang zweimal
 * hier und ein drittes Mal im Operator.
 */
export function namenstabelle() {
  try {
    const t = JSON.parse(readFileSync(join(hostDir(), 'namen.json'), 'utf8'));
    return t && typeof t === 'object' ? t : {};
  } catch {
    return {};
  }
}

/** Instanzname aus der Operator-Namenstabelle, sonst Kurzform der Session-ID. */
export function selbstName(sid = selbstId()) {
  const t = namenstabelle();
  if (t[sid]) return t[sid];
  return sid ? sid.slice(0, 8) : 'unbekannt';
}

/** Welche Sitzung traegt diesen Namen GERADE? null, wenn niemand. */
export function nameZuSession(name) {
  for (const [sid, n] of Object.entries(namenstabelle())) {
    if (String(n).toLowerCase() === String(name).toLowerCase()) return sid;
  }
  return null;
}

/**
 * Ist die Nachricht fuer mich?
 *
 * ZWEI ADRESSARTEN, und die Unterscheidung ist der Kern des Umbaus vom
 * 07.08.2026:
 *
 *   Person - der Auftrag traegt an_session. Dann zaehlt AUSSCHLIESSLICH die
 *            Session-ID. Der Name daneben ist Beschriftung, kein Kriterium.
 *            Wer spaeter denselben Namen aus dem Pool bekommt, bekommt den
 *            Auftrag NICHT.
 *   Rolle  - der Auftrag traegt keine an_session (Rundruf, --rolle, fremder
 *            Rechner, Altbestand). Dann entscheidet der Name, wer immer ihn
 *            gerade traegt. Das ist gewollt, aber nur zusammen mit dem Verfall
 *            zu verantworten.
 *
 * Vorher gab es nur den zweiten Fall - deshalb hat eine neue Marga den vier
 * Tage alten Auftrag an eine laengst beendete Marga abgearbeitet.
 */
function fuerMich(m, sid, name) {
  if (m.host !== rechner()) return false;
  if (m.fromSession === sid) return false;
  if (m.toSession) return m.toSession === sid;
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
    .filter((a) => OFFEN.includes(a.zustand))
    .map(alsNachricht)
    .filter((m) => fuerMich(m, sessionId, wer));
}

function cursorMerken(auf) {
  const sid = selbstId();
  if (sid) cursorSetzen(db(), sid, auf);
}

function zeit(iso) {
  if (!iso) return '?';
  // Hier stand ein try/catch, das nie etwas gefangen hat: new Date('quatsch')
  // wirft NICHT, sondern liefert ein Invalid Date, dessen toLocaleString
  // woertlich "Invalid Date" ausgibt. Nur getTime() verraet den Fehlschlag.
  const wert = new Date(iso);
  if (Number.isNaN(wert.getTime())) return String(iso);
  return wert.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
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
  // BEWUSST der alte deutsche Name, obwohl der Befehl inzwischen "receive"
  // heisst: hier ruft ein Rechner den anderen, und dessen Stand kann aelter
  // sein. "uebernehmen" versteht jede Fassung, "receive" nur die neue.
  // Umstellen erst, wenn alle Rechner nachgezogen haben.
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
 * Zerlegt eine Adresse der Form "Name@RECHNER".
 *
 * Der Name ist eine Pacht PRO RECHNER - dieselbe Pacht kann auf zwei Rechnern
 * gleichzeitig laufen, ohne dass etwas kaputt ist (die Sitzungen haben
 * verschiedene IDs, und jedes Ereignis traegt host UND an_session). Eindeutig
 * sein muss deshalb nicht der Name, sondern die ADRESSE. "Petra@SENZA" leistet
 * genau das, wie ein Benutzer auf einem Host.
 *
 * Ein mesh-weit eindeutiger Namenspool waere die falsche Medizin: er kostet
 * eine Mesh-Abfrage je Sitzungsstart (gemessen 910 ms) und leert den Pool umso
 * schneller, je mehr Rechner dazukommen.
 *
 * @param {string} adresse
 * "Name" oder "Name@RECHNER".
 * @returns {{name: string, host: string|null}}
 * host ist null, wenn die Adresse keinen Rechner nennt.
 */
export function zerlegeAdresse(adresse) {
  const roh = String(adresse ?? '');
  const at = roh.lastIndexOf('@');
  if (at <= 0 || at === roh.length - 1) return { name: roh, host: null };
  return { name: roh.slice(0, at), host: roh.slice(at + 1).toUpperCase() };
}

/**
 * Auf welchen Rechnern laeuft dieser Name?
 *
 * Liefert ALLE Treffer, nicht den ersten. Der erste Treffer waere eine stille
 * Entscheidung zwischen zwei gleichnamigen Sitzungen - und genau so kam am
 * 07.08.2026 ein vier Tage alter Auftrag bei der falschen Instanz an.
 *
 * Der lokale Rechner steht vorn, wenn er den Namen traegt. Die Mesh-Abfrage
 * laeuft trotzdem, denn erst sie zeigt, ob der Name auch woanders lebt.
 *
 * @param {string} name
 * Blosser Name, ohne "@RECHNER".
 * @returns {string[]}
 * Rechnernamen in Grossbuchstaben, ohne Dopplung. Leer, wenn unbekannt.
 */
export function findeRechnerAlle(name) {
  const treffer = [];
  if (nameZuSession(name)) treffer.push(rechner());

  try {
    // fileURLToPath statt URL.pathname: unter Windows liefert pathname
    // "/C:/Users/..." mit fuehrendem Schraegstrich, den node nicht oeffnet.
    const operator = join(dirname(fileURLToPath(import.meta.url)), '..', 'operator', 'operator.mjs');
    const roh = execFileSync(
      process.execPath,
      [operator, 'status', '--mesh', '--json'],
      { encoding: 'utf8', timeout: 40000, maxBuffer: 8 * 1024 * 1024 },
    );
    // Der Vergleichswert kommt aus dem Parameter. Hier stand bis zum 09.08.2026
    // "ziel", eine Variable, die es in dieser Funktion nie gab - der
    // ReferenceError lief in das catch unten und die Funktion lieferte damit
    // IMMER null, sobald der Name nicht lokal bekannt war. Ein Auftrag an einen
    // Agenten auf einem anderen Rechner landete dadurch still auf dem eigenen.
    const ziel = String(name).toLowerCase();
    for (const zweig of JSON.parse(roh).rechner || []) {
      for (const i of zweig.instanzen || []) {
        if (String(i.name).toLowerCase() !== ziel) continue;
        const host = String(zweig.rechner || zweig.host).toUpperCase();
        if (!treffer.includes(host)) treffer.push(host);
      }
    }
  } catch { /* Mesh nicht verfuegbar - der Aufrufer entscheidet */ }
  return treffer;
}

/**
 * Namen, die im Mesh auf mehr als einem Rechner leben.
 *
 * Reine Diagnose fuer "doctor". Kein Fehler, sondern ein Hinweis: die Adresse
 * braucht dann den Rechner dazu.
 *
 * @returns {Array<[string, string[]]>}
 * Paare aus Name und den Rechnern, sortiert. Leer, wenn das Mesh nicht
 * erreichbar ist - eine unbeantwortbare Frage wird nicht geraten.
 */
function geteilteNamen() {
  try {
    const operator = join(dirname(fileURLToPath(import.meta.url)), '..', 'operator', 'operator.mjs');
    const roh = execFileSync(
      process.execPath,
      [operator, 'status', '--mesh', '--json'],
      { encoding: 'utf8', timeout: 40000, maxBuffer: 8 * 1024 * 1024 },
    );
    const je = new Map();
    for (const zweig of JSON.parse(roh).rechner || []) {
      const host = String(zweig.rechner || zweig.host).toUpperCase();
      for (const i of zweig.instanzen || []) {
        if (!i.name) continue;
        const schluessel = String(i.name);
        if (!je.has(schluessel)) je.set(schluessel, new Set());
        je.get(schluessel).add(host);
      }
    }
    return [...je.entries()]
      .filter(([, hosts]) => hosts.size > 1)
      .map(([name, hosts]) => [name, [...hosts].sort()])
      .sort((a, b) => a[0].localeCompare(b[0]));
  } catch {
    return [];
  }
}

/**
 * Auf welchem Rechner laeuft dieser Agent?
 *
 * Nur noch fuer den eindeutigen Fall. Traegt der Name mehr als ein Rechner,
 * gibt es null - der Aufrufer muss dann entscheiden, statt zu raten.
 *
 * @returns {string|null} Rechnername in Grossbuchstaben, oder null.
 */
export function findeRechner(name) {
  const alle = findeRechnerAlle(name);
  return alle.length === 1 ? alle[0] : null;
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
async function cmdUebernehmen() {
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

  // Die Bindung an die Sitzung wird HIER nachgeholt. Der ferne Absender konnte
  // den Namen nicht aufloesen - die Namenstabelle des Empfaengerrechners liegt
  // auf diesem Rechner, und das ist genau der hier. Ohne diesen Schritt bliebe
  // jeder Auftrag ueber Rechnergrenzen namensadressiert und damit vererbbar.
  if (ereignis.art === 'auftrag' && !ereignis.an_session && ereignis.bindung === 'offen' && ereignis.an) {
    const sitzung = nameZuSession(ereignis.an);
    if (sitzung) {
      ereignis.an_session = sitzung;
      ereignis.bindung = 'session';
    }
  }

  schreibe(d, ereignis);

  // AUCH in die JSONL schreiben, nicht nur in die Datenbank. Der Stop-Hook
  // filtert billig ueber die Dateizeit von messages.jsonl, bevor er ueberhaupt
  // node startet - ein nur in der Datenbank abgelegter Auftrag loest diesen
  // Vorfilter nicht aus und wird dem Empfaenger nie gemeldet. Faellt weg,
  // sobald die Uebergangsphase endet und der Hook auf die Datenbank schaut.
  if (ereignis.art === 'auftrag') {
    anhaengen(pfadMessages(), {
      id: ereignis.auftrag_id, ts: ereignis.ts, host: ereignis.host,
      vonHost: ereignis.von_host, from: ereignis.von, fromSession: ereignis.von_session,
      cwd: ereignis.cwd, to: ereignis.an, topic: ereignis.topic, text: ereignis.text,
      quittung: Boolean(ereignis.quittung_erwartet),
    });
  }
  // Der letzte Meter. Der Absender konnte den Socket nicht kennen, er liegt auf
  // DIESEM Rechner - deshalb wird die Sofortzustellung hier versucht und nicht
  // dort. Der Weg ueber Rechnergrenzen bleibt unveraendert ssh im Tailnet, nur
  // die Wartezeit auf den naechsten Stop-Hook faellt weg.
  //
  // Ergebnis in die Antwort, nicht auf die Konsole: der Aufrufer ist ein
  // anderer Rechner und liest genau diese eine JSON-Zeile.
  let sofort = null;
  if (ereignis.art === 'auftrag' && einstellung('zustellung') !== 'stop-hook') {
    const { zugestellt } = await sofortZustellen({
      datenDir: hostDir(),
      sessionId: ereignis.an_session,
      text: ereignis.text,
      modus: einstellung('zustellung'),
    });
    sofort = zugestellt;
  }
  console.log(JSON.stringify({
    ok: true, auftrag_id: ereignis.auftrag_id, host: rechner(), ...(sofort !== null && { sofort }),
  }));
}

async function cmdSend(argv) {
  sicherstellen();
  const adresse = argv[0];

  // Flags MIT Wert muessen samt Wert uebersprungen werden, sonst landet der
  // Wert im Nachrichtentext (genau so beim ersten Test passiert).
  const mitWert = new Set(['--topic', '--host', '--from', '--von']);
  const worte = [];
  for (let i = 1; i < argv.length; i++) {
    if (mitWert.has(argv[i])) { i++; continue; }
    if (argv[i].startsWith('--')) continue;
    worte.push(argv[i]);
  }
  const text = worte.join(' ');

  if (!adresse || !text) {
    console.error('Nutzung: bus.mjs send <Name[@RECHNER]|alle> "Text" [--topic thema] [--host RECHNER] [--von Name] [--rolle] [--erwartet-quittung]');
    process.exit(1);
  }
  const wert = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : null;
  };

  // Wer sendet: --von schlaegt die Sitzungserkennung. Noetig fuer Aufrufer
  // ohne eigene Claude-Sitzung - die TUI etwa lief bisher als "unbekannt",
  // weil CLAUDE_CODE_SESSION_ID dort nicht gesetzt ist.
  const vonName = wert('--from') || wert('--von') || selbstName();
  const rundruf = ['alle', 'all'].includes(String(adresse).toLowerCase());

  // "Name@RECHNER" ist gleichwertig zu --host, nur kuerzer und lesbar. Beides
  // zugleich mit verschiedenen Rechnern waere ein Widerspruch, den zu erraten
  // niemandem hilft.
  const { name: to, host: ausAdresse } = rundruf
    ? { name: adresse, host: null }
    : zerlegeAdresse(adresse);
  const ausFlag = wert('--host') ? String(wert('--host')).toUpperCase() : null;
  if (ausAdresse && ausFlag && ausAdresse !== ausFlag) {
    console.error(`${ROT}Widerspruch: '${adresse}' nennt ${ausAdresse}, --host nennt ${ausFlag}.${R}`);
    process.exit(1);
  }

  // Wohin: ein genannter Rechner spart die Suche. Der Rundruf bleibt bewusst
  // lokal - "alle" ueber alle Rechner waere ein anderer Vorgang und braucht
  // eine eigene Entscheidung, keine stille Ausweitung.
  const genannt = ausAdresse || ausFlag;
  const zielHost = rundruf ? rechner() : (genannt || _zielRechnerErmitteln(to));

  // WEN genau: einen Namen aufloesen wir hier auf die Sitzung, die ihn GERADE
  // traegt. Ein Name ist eine Pacht - ohne diese Aufloesung erbt der naechste
  // Inhaber die Post seines Vorgaengers (am 07.08.2026 genau so passiert).
  //
  // Nicht aufgeloest wird beim Rundruf, bei --rolle und bei einem Ziel auf
  // einem anderen Rechner. Der ferne Fall holt es beim Eintreffen nach, siehe
  // cmdUebernehmen - dort ist die Namenstabelle die richtige.
  const alsRolle = argv.includes('--rolle') || argv.includes('--role');
  const lokal = zielHost === rechner();
  let zielSession = null;
  if (!rundruf && !alsRolle && lokal) {
    zielSession = nameZuSession(to);
    if (!zielSession) {
      console.error(`${ROT}'${to}' trägt gerade niemand auf ${rechner()}.${R}`);
      console.error(`${GRAU}Laufende Instanzen: node ~/.claude/skills/operator/operator.mjs status${R}`);
      console.error(`${GRAU}An den Namen adressieren, wer immer ihn traegt: --rolle${R}`);
      process.exit(1);
    }
  }
  // Drei Werte, weil zwei zu wenig sind: 'rolle' heisst "an den Namen, mit
  // Absicht", 'offen' heisst "an eine Person, hier aber nicht aufloesbar".
  // Nur 'offen' darf der Empfaengerrechner beim Eintreffen nachbinden - waeren
  // beide Faelle derselbe Wert, wuerde er auch Rollenauftraege festnageln.
  const bindung = zielSession ? 'session' : (rundruf || alsRolle) ? 'rolle' : 'offen';

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
    toSession: zielSession,
    bindung,
    topic: topicIdx >= 0 ? argv[topicIdx + 1] : 'allgemein',
    text,
    quittung: argv.includes('--expect-receipt') || argv.includes('--erwartet-quittung'),
  };
  const ereignis = {
    auftrag_id: nachricht.id, ts: nachricht.ts, art: 'auftrag',
    host: zielHost, von_host: nachricht.vonHost,
    von: nachricht.from, von_session: nachricht.fromSession, an: to,
    an_session: zielSession, bindung,
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
  // Sofortzustellung nur fuer den lokalen Fall. Sitzt der Empfaenger woanders,
  // hat zustellenAn() den Auftrag schon dorthin gebracht, und der dortige
  // "receive" versucht den Socket seinerseits - dort kennt er ihn auch, hier
  // nicht.
  if (lokal) await meldeSofort(zielSession, text);

  const frist = einstellung('verfall_stunden');
  console.log(zielSession
    ? `${GRAU}Gebunden an die Sitzung ${zielSession.slice(0, 8)} - ein spaeterer Traeger des Namens bekommt ihn nicht.${R}`
    : bindung === 'rolle'
      ? `${GRAU}An den Namen adressiert, nicht an eine Sitzung${frist ? `. Verfällt nach ${frist} h` : ''}.${R}`
      : `${GRAU}Bindung holt ${zielHost} beim Eintreffen nach${frist ? `, sonst Verfall nach ${frist} h` : ''}.${R}`);
  if (nachricht.quittung) console.log(`${GRAU}Quittung erwartet - Stand mit: bus.mjs open${R}`);
}

/**
 * Sucht den Zielrechner und bricht ab, wenn der Name mehrdeutig ist.
 *
 * FAIL-CLOSED. Traegt den Namen mehr als ein Rechner, waere jede Wahl geraten -
 * und eine an die falsche Sitzung zugestellte Nachricht ist der teurere Fehler.
 * Genau diese Sorte Verwechslung hat am 07.08.2026 einen vier Tage alten
 * Auftrag bei der falschen Instanz landen lassen.
 *
 * Kein Treffer ist dagegen KEIN Abbruch: der Name kann lokal in namen.json
 * stehen, ohne dass das Mesh erreichbar ist. Dann bleibt es beim eigenen
 * Rechner, und die Bindung weiter unten meldet sauber, wenn ihn dort niemand
 * traegt.
 *
 * @param {string} name
 * Blosser Name, ohne "@RECHNER".
 * @returns {string} Rechnername in Grossbuchstaben.
 */
function _zielRechnerErmitteln(name) {
  const alle = findeRechnerAlle(name);
  if (alle.length <= 1) return String(alle[0] || rechner()).toUpperCase();

  console.error(`${ROT}'${name}' gibt es auf ${alle.length} Rechnern: ${alle.join(', ')}.${R}`);
  console.error(`${GRAU}Der Name ist eine Pacht pro Rechner - beide sind echt, mit eigener Sitzung.${R}`);
  console.error(`${GRAU}Bitte die Adresse eindeutig machen:${R}`);
  for (const host of alle) console.error(`${GRAU}    send ${name}@${host} "..."${R}`);
  process.exit(1);
}

/**
 * Versucht die Sofortzustellung und sagt dem Anwender, was daraus wurde.
 *
 * Der Auftrag steht zu diesem Zeitpunkt bereits in der Datenbank. Misslingt die
 * Abkuerzung, geht also nichts verloren - der Stop-Hook holt ihn wie bisher ab.
 * Deshalb ist ein Fehlschlag hier eine Notiz und kein Abbruch.
 *
 * Nur im Modus 'socket' wird laut gewarnt: dort hat der Anwender den Rueckfall
 * ausdruecklich abgewaehlt und muss erfahren, dass es trotzdem der langsame Weg
 * wird.
 *
 * @param {string|null} zielSession
 * Sitzung des Empfaengers, oder null wenn nicht aufloesbar.
 * @param {string} text
 * Der Auftragstext.
 */
async function meldeSofort(zielSession, text) {
  const modus = einstellung('zustellung');
  if (modus === 'stop-hook') return;

  const { zugestellt, grund } = await sofortZustellen({
    datenDir: hostDir(), sessionId: zielSession, text, modus,
  });

  if (zugestellt) {
    console.log(`${GRUEN}Sofort zugestellt${R} ${GRAU}- der Empfaenger reagiert ohne auf den Stop-Hook zu warten.${R}`);
    return;
  }
  if (modus === 'socket') {
    console.error(`${GELB}Sofortzustellung nicht moeglich: ${grund}.${R}`);
    console.error(`${GRAU}Der Auftrag liegt bereit und wird ueber den Stop-Hook abgeholt.${R}`);
    return;
  }
  // Im Modus 'auto' ist der Stop-Hook der geplante Weg und keine Panne. Auf
  // Windows ueberhaupt nichts sagen - dort gibt es den Socket nie, und eine
  // Zeile bei JEDEM Senden waere reines Rauschen.
  if (sockelFaehig()) console.log(`${GRAU}Zustellung ueber den Stop-Hook (${grund}).${R}`);
}

function cmdRead(argv) {
  sicherstellen();
  const alles = argv.includes('--all') || argv.includes('--alle');
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
  if (SELBSTCODES.has(code)) {
    console.log(`${GELB}${code} vergibt sonst der Bus selbst (Verfall, verschwundener Empfänger).${R}`);
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
  const alle = argv.includes('--all') || argv.includes('--alle');
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

  const farbeZustand = (z) => (z === 'completed' ? GRUEN : ['failed', 'cancelled', 'expired'].includes(z) ? ROT : GELB);
  const zeigen = (titel, eintraege) => {
    if (!eintraege.length) return;
    console.log(`\n${CYAN}${titel}${R}\n`);
    for (const a of eintraege) {
      const wie = a.bindung === 'session' ? '' : ' [Rolle]';
      console.log(`  ${farbeZustand(a.zustand)}${a.zustand.padEnd(15)}${R}${GRAU}${zeit(a.erstellt)}  ${a.von} -> ${a.an}${wie}  (${a.topic}, id ${a.auftrag_id})${R}`);
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
/**
 * Baut die Auftragsliste mit allen Quittungen auf.
 *
 * @param {string|null} name
 * Auf einen Agenten einschraenken, oder null fuer den gesamten Bestand.
 */
function verlaufListe(d, name = null) {
  return auftraege(d, {})
    .filter((a) => !name || a.an === name || a.von === name)
    .sort((x, y) => String(x.erstellt).localeCompare(String(y.erstellt)))
    .map((a) => ({ ...a, quittungen: quittungenZu(d, a.auftrag_id) }));
}

/**
 * Der gesamte Bestand, nicht auf einen Gespraechspartner eingeschraenkt.
 *
 * Gedacht als Datenquelle fuer die Bus-Ansicht der Oberflaeche: dort steht die
 * Frage "was liegt ueberhaupt im Bus", und die beantwortet keine Sicht, die
 * vorher einen Namen verlangt.
 */
function cmdLog(argv) {
  sicherstellen();
  const d = db();
  const grenzeIdx = argv.indexOf('--limit');
  const grenze = grenzeIdx >= 0 ? parseInt(argv[grenzeIdx + 1], 10) : 0;
  let liste = verlaufListe(d);
  // Von hinten abschneiden: bei einer Obergrenze will man das Neueste sehen,
  // nicht den Anfang der Zeitrechnung.
  if (Number.isFinite(grenze) && grenze > 0 && liste.length > grenze) {
    liste = liste.slice(-grenze);
  }

  if (argv.includes('--json')) {
    console.log(JSON.stringify({
      rechner: rechner(), ich: selbstName(), zeit: new Date().toISOString(),
      verfall_stunden: einstellung('verfall_stunden'),
      auftraege: liste,
    }, null, 1));
    return;
  }
  console.log(`\n${CYAN}${liste.length} Auftrag/Aufträge im Bus auf ${rechner()}${R}\n`);
  for (const a of liste) {
    console.log(`  ${GRAU}${zeit(a.erstellt)}  ${a.von} -> ${a.an}${R}  ${a.zustand}  ${GRAU}(${a.topic}, id ${a.auftrag_id})${R}`);
    console.log(`  ${String(a.text || '').slice(0, 100)}`);
  }
  console.log('');
}

function cmdVerlauf(argv) {
  sicherstellen();
  const alsJson = argv.includes('--json');
  const name = argv.find((a) => !a.startsWith('--'));
  if (!name) {
    console.error('Aufruf: bus.mjs history <Name> [--json]');
    console.error('Der gesamte Bestand ohne Namen: bus.mjs log [--json] [--limit N]');
    process.exitCode = 1;
    return;
  }

  const d = db();
  const liste = verlaufListe(d, name);

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
  const farbeZustand = (z) => (z === 'completed' ? GRUEN : ['failed', 'cancelled', 'expired'].includes(z) ? ROT : GELB);
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
    const d = db();
    const z = zahlen(d);
    const frist = einstellung('verfall_stunden');
    console.log(`  Datenbank    ${join(hostDir(), 'bus.db')}`);
    console.log(`  Ereignisse   ${z.ereignisse}`);
    console.log(`  Auftraege    ${z.auftraege}, davon offen ${z.offen}`);
    console.log(`  Verfall      ${frist ? `${frist} h` : `${GELB}abgeschaltet${R}`}`);

    // Ein Auftrag, dessen Empfaengername inzwischen einer anderen Sitzung
    // gehoert, ist genau der Vorfall vom 07.08.2026 - nur bekommt ihn dank der
    // Bindung niemand mehr faelschlich zugestellt. Hier steht er trotzdem,
    // damit die Verwechslung sichtbar bleibt statt still zu verschwinden.
    const namen = namenstabelle();
    const irre = fehlgeleitete(d, namen);
    console.log(irre.length
      ? `  Namenswechsel ${GELB}${irre.length} Auftrag/Aufträge an einen inzwischen neu vergebenen Namen${R}`
      : `  Namenswechsel ${GRUEN}keine${R}`);
    for (const a of irre.slice(0, 5)) {
      console.log(`               ${GRAU}${a.auftrag_id}  an ${a.an} (${String(a.an_session).slice(0, 8)}), Name gehoert jetzt einer anderen Sitzung${R}`);
    }
    // Namen, die auf mehreren Rechnern leben. KEIN Fehler - der Name ist eine
    // Pacht pro Rechner, beide Sitzungen sind echt. Nur die Adresse "Petra"
    // allein reicht dann nicht mehr, und genau das soll hier stehen, bevor es
    // beim Senden auffaellt.
    for (const [name, hosts] of geteilteNamen()) {
      console.log(`  Geteilt      ${GELB}${name} lebt auf ${hosts.join(' und ')}${R}`);
      console.log(`               ${GRAU}eindeutig adressieren: send ${name}@${hosts[0]} "..."${R}`);
    }

    console.log(`  Altbestand   ${zeilen(pfadMessages()).length} Nachrichten / ${zeilen(pfadReceipts()).length} Quittungen in JSONL`);
  }
  console.log('');
}

/**
 * Zeigt oder setzt die Einstellungen des Bus.
 *
 * Ohne Argumente die Uebersicht mitsamt Herkunft - der haeufigste Grund fuer
 * "der Wert wirkt nicht" ist eine gesetzte Umgebungsvariable, und die sieht man
 * sonst nirgends.
 */
function cmdConfig(argv) {
  const [schluessel, ...rest] = argv;
  if (schluessel) {
    const fehler = setzeEinstellung(schluessel, rest.join(' '));
    if (fehler) {
      console.error(`${ROT}${fehler}${R}`);
      process.exitCode = 1;
      return;
    }
  }
  console.log(`\n${CYAN}Bus-Einstellungen${R}  ${GRAU}${einstellungsDatei()}${R}\n`);
  for (const e of alleEinstellungen()) {
    const farbe = e.herkunft === 'Vorgabe' ? GRAU : GRUEN;
    console.log(`  ${e.schluessel.padEnd(18)} ${farbe}${String(e.wert).padEnd(8)}${R}${GRAU}aus ${e.herkunft}${R}`);
    console.log(`  ${GRAU}${' '.repeat(18)} ${e.text}${R}`);
    console.log(`  ${GRAU}${' '.repeat(18)} Umgebung: ${e.umgebung}${R}\n`);
  }
  console.log(`${GRAU}Setzen: bus.mjs config <schluessel> <wert>${R}\n`);
}

/** Wird vom Stop-Hook benutzt: nur die Anzahl offener Nachrichten, sonst nichts. */
function cmdPending() {
  const wurzel = busWurzel();
  if (pfadProbleme(wurzel).length) process.exit(0);
  const { gesamt, neu: ungelesen } = offeneNachrichten();

  // NUR melden, was auch noch offen ist. Der Lesezeiger allein genuegt nicht:
  // er wird ausschliesslich von "read" fortgeschrieben, nicht von "ack". Wer
  // einen Auftrag ueber "auftraege" sieht und direkt quittiert, bekam ihn
  // deshalb bei JEDEM weiteren Stop erneut gemeldet - am 02.08.2026 an einem
  // bereits auf completed stehenden Auftrag beobachtet. Bei einem Hook, der
  // nach jedem Werkzeugaufruf laeuft, waere das eine Dauerschleife.
  const offeneIds = new Set(offeneAuftraege().map((m) => m.id));
  const neu = ungelesen.filter((m) => offeneIds.has(m.id));
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

    send <Name|all> "Text" [--topic t] [--rolle] [--expect-receipt]
    read [--all]                  neue Nachrichten holen (schiebt den Lesezeiger)
    tasks [--all] [--json]        Warteschlange - was liegt an, unabhaengig vom Lesezeiger
    history <Name> [--json]       Auftraege und Quittungen mit einem Agenten
    log [--json] [--limit N]      der gesamte Bestand, ohne Namensfilter
    ack <msgId> <Code> ["Notiz"]  quittieren, setzt zugleich den Auftragszustand
    open                          Stand der eigenen Nachrichten
    config [schluessel wert]      Einstellungen zeigen oder setzen
    doctor                        Pfad-Isolation und Datenbank pruefen
    pending                       nur fuer den Stop-Hook
    receive                       Nutzlast von einem anderen Rechner uebernehmen

  Die frueheren deutschen Namen (auftraege, verlauf, offen, uebernehmen) und
  Flags (--alle, --erwartet-quittung, --von) funktionieren weiterhin.

  An WEN adressiert wird
    send Marga "..."          an die Sitzung, die den Namen GERADE traegt.
                               Ein spaeterer Traeger bekommt den Auftrag nicht.
                               Traegt den Namen niemand, bricht der Befehl ab.
    send Marga@SENZA "..."    dieselbe Sitzung, aber mit Rechner. Gleichwertig
                               zu --host, nur kuerzer.
    send Marga "..." --rolle  an den Namen, wer immer ihn traegt. Ueberlebt
                               den Namenswechsel - deshalb nur mit Verfall.

  Derselbe Name auf zwei Rechnern
    Der Name ist eine Pacht PRO RECHNER. "Petra" kann gleichzeitig auf RAINBOW
    und SENZA laufen, ohne dass etwas kaputt ist - die Sitzungen haben eigene
    IDs, und jedes Ereignis traegt host und an_session.

    Eindeutig sein muss deshalb nicht der Name, sondern die ADRESSE. Traegt
    ihn mehr als ein Rechner, bricht "send" ab und nennt beide Fassungen,
    statt still eine davon zu waehlen. "doctor" zeigt solche Namen von sich
    aus an.

  Wie ein Auftrag ankommt - Einstellung "zustellung"
    auto        Vorgabe. Sofort ueber den Inbox-Socket der Zielsitzung, wo es
                den gibt (macOS und Linux), sonst ueber den Stop-Hook.
    socket      nur sofort. Klappt es nicht, gibt es eine Warnung - der Auftrag
                liegt trotzdem bereit und wird spaeter abgeholt.
    stop-hook   immer der bisherige Weg. Auf Windows ohnehin der einzige.

    Setzen mit: config zustellung socket

    Voraussetzung fuer die Sofortzustellung: in ~/.claude/settings.json muss
    "crossSessionInbound": "accept" stehen. Fehlt der Wert, zeigt die
    Zielsitzung stattdessen "Held message from another session" und wartet auf
    eine Freigabe - dann kommt der Auftrag zwar an, aber nicht von allein.

  Zwei Fallen beim Inbox-Socket (Stand 09.08.2026, Claude Code 2.1.226)
    Die ERSTE Sitzung nach einem Claude-Code-Update bekommt das Feature nicht.
    Die Feature-Flags sind dann noch nicht abgerufen, die Sitzung bindet keinen
    Socket. Ein Neustart der Sitzung behebt es. Also nach einem Update einmal
    neu starten, bevor man die Sofortzustellung fuer kaputt haelt.

    "/list-agents" taugt NICHT als Test, ob das Feature laeuft. Der Befehl wird
    auch ohne es erkannt und meldet dann nur "No subagents or other Claude
    sessions" - er listet ja auch Subagenten. Belastbar ist die Zeile
    "Peer address" in /status, oder von aussen: ss -xlp | grep cc-socks

  Zustaende: submitted -> working (202) -> completed (2xx) | failed (4xx/5xx)
             409 und 503 setzen zurueck auf submitted, der Auftrag bleibt liegen
             expired (408) und cancelled (410) vergibt der Bus selbst

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
  // Die deutschen Namen bleiben als stille Aliase bestehen. Sie sind nicht
  // nur Bequemlichkeit: "uebernehmen" ruft ein anderer Rechner ueber SSH auf,
  // und solange dort noch ein aelterer Stand liegt, kommt genau dieses Wort.
  switch (argv[0]) {
    case 'send': await cmdSend(argv.slice(1)); break;
    case 'receive': case 'uebernehmen': await cmdUebernehmen(); break;
    case 'read': cmdRead(argv.slice(1)); break;
    case 'ack': cmdAck(argv.slice(1)); break;
    case 'tasks': case 'task':
    case 'auftraege': case 'auftrag': cmdAuftraege(argv.slice(1)); break;
    case 'history': case 'verlauf': cmdVerlauf(argv.slice(1)); break;
    case 'log': case 'bestand': cmdLog(argv.slice(1)); break;
    case 'open': case 'offen': cmdOffen(); break;
    case 'config': case 'einstellungen': cmdConfig(argv.slice(1)); break;
    case 'doctor': cmdDoctor(); break;
    case 'pending': cmdPending(); break;
    default: hilfe();
  }
}
