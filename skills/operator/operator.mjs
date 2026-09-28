// Operator: Uebersicht und Detailansicht aller laufenden Claude-Code-Instanzen.
//
// Node statt PowerShell, damit es auf allen Rechnern laeuft (Windows, Linux,
// macOS). Die frueheren PowerShell-Fallen entfallen damit ebenfalls: kein
// BOM-Zwang, keine Formatstring-Eigenheiten, kein .Count-Problem bei
// einelementigen Ergebnissen.
//
// Datenquelle ist "claude agents --json", also Claude Code selbst. Es gibt
// bewusst keine Anmeldung und keinen Daemon.
//
// Aufrufe:
//   node operator.mjs status              Tabelle
//   node operator.mjs status <name>       Detail einer Instanz
//   node operator.mjs watch [sekunden]    Tabelle periodisch neu zeichnen
//   node operator.mjs names               vergebene Namen
//   node operator.mjs reset-names         beendete Sitzungen aufraeumen
//   node operator.mjs stop <name>         Instanz beenden (fragt nach)

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, statSync, openSync, readSync, closeSync } from 'node:fs';
import { homedir, hostname, platform, release } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { ladePool, aktivesMotiv, alleMotive, setzeMotiv } from './pool.mjs';
import { ladeInstanzen } from './instanzen.mjs';
import { prozessName } from './prozess.mjs';
import { findeTranskript, letzteZeilen } from './transkript.mjs';
import { aufgabeAusInhalt } from './aufgabe.mjs';
// Nur zum Anzeigen wartender Post. bus.mjs fuehrt beim Import nichts aus.
import { offeneNachrichten } from '../claude-bus/bus.mjs';
import { oeffne as oeffneBus } from '../claude-bus/speicher.mjs';
import { pachtEndet } from '../claude-bus/pacht.mjs';

const R = '\x1b[0m', FETT = '\x1b[1m', GRAU = '\x1b[38;5;244m';
const GRUEN = '\x1b[38;5;77m', GELB = '\x1b[38;5;221m', ROT = '\x1b[38;5;203m';
const CYAN = '\x1b[38;5;80m';

const execFileAsync = promisify(execFile);
// Eigenes Verzeichnis, nicht das Arbeitsverzeichnis des Aufrufers - mesh.json
// liegt neben dem Skript und muss auch dann gefunden werden, wenn der Operator
// aus einem beliebigen Projektordner heraus gestartet wird.
const SKILL_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Pfade und Namen
// ---------------------------------------------------------------------------

function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

function datenDir() {
  const d = join(homedir(), '.claude', 'bus', rechner());
  mkdirSync(d, { recursive: true });
  return d;
}

const namenDatei = () => join(datenDir(), 'namen.json');

function ladeNamen() {
  if (!existsSync(namenDatei())) return {};
  try { return JSON.parse(readFileSync(namenDatei(), 'utf8')); } catch { return {}; }
}

function speichereNamen(t) {
  writeFileSync(namenDatei(), JSON.stringify(t, null, 1), 'utf8');
}

// ladePool, aktivesMotiv, alleMotive und setzeMotiv kommen aus pool.mjs -
// eine Quelle fuer Operator, Starter und Hook.

function vergibName(tabelle, sessionId) {
  if (tabelle[sessionId]) return tabelle[sessionId];
  const pool = ladePool();
  const vergeben = new Set(Object.values(tabelle));
  const frei = pool.filter((n) => !vergeben.has(n));
  const name = frei.length ? frei[0] : `${pool[0]}-${Object.keys(tabelle).length + 1}`;
  tabelle[sessionId] = name;
  return name;
}

// ---------------------------------------------------------------------------
// Instanzen und Transkripte
// ---------------------------------------------------------------------------

// ladeInstanzen kommt aus instanzen.mjs - dieselbe Quelle nutzt der
// SessionStart-Hook, wenn ihm die Namen ausgehen.

// findeTranskript kommt aus transkript.mjs - dieselbe Suche braucht der
// Neustart, um vorher zu wissen, ob es ueberhaupt etwas fortzusetzen gibt.

// letzteZeilen kommt aus transkript.mjs - dort ist es testbar und faengt
// den Fall ab, dass eine einzelne Zeile groesser ist als das Lesefenster.

/**
 * Zeitstempel des ersten Transkript-Eintrags, also der Beginn des Gespraechs.
 * Liest nur die ersten Bytes, weil ein Resume die Datei fortschreibt und sie
 * damit beliebig gross sein kann.
 */
function beginnDesGespraechs(pfad) {
  let fd;
  try {
    fd = openSync(pfad, 'r');
    const puffer = Buffer.alloc(65_536);
    const gelesen = readSync(fd, puffer, 0, puffer.length, 0);
    // Die erste Zeile traegt keinen Zeitstempel (last-prompt/leafUuid),
    // deshalb bis zum ersten Eintrag mit timestamp weiterlesen. Die letzte
    // Zeile im Puffer kann abgeschnitten sein und wird uebersprungen.
    const zeilen = puffer.toString('utf8', 0, gelesen).split('\n');
    if (gelesen === puffer.length) zeilen.pop();
    for (const z of zeilen) {
      let e;
      try { e = JSON.parse(z); } catch { continue; }
      if (e.timestamp) return Date.parse(e.timestamp);
    }
    return null;
  } catch {
    return null;
  } finally {
    if (undefined !== fd) {
      try { closeSync(fd); } catch { /* egal */ }
    }
  }
}

/**
 * Sammelt Kennzahlen aus einem Transkript. Standardmaessig nur aus dem
 * Dateiende, weil die Kontextgroesse dort steht und das billig ist.
 */
function leseTranskript(pfad, { voll = false } = {}) {
  const ergebnis = {
    kontext: 0, tokens: 0, modell: null, letztesTool: null,
    letzteZeit: null, aufgabe: null, aufrufe: 0, nachCompact: false,
    cwd: null, cacheGelesen: 0, version: null,
  };
  if (!pfad || !existsSync(pfad)) return ergebnis;

  let zeilen;
  try {
    zeilen = voll
      ? readFileSync(pfad, 'utf8').trimEnd().split('\n')
      : letzteZeilen(pfad, 400);
  } catch {
    return ergebnis;
  }

  let kontextGesetzt = false;
  for (let i = zeilen.length - 1; i >= 0; i--) {
    let e;
    try { e = JSON.parse(zeilen[i]); } catch { continue; }
    if (e.timestamp && !ergebnis.letzteZeit) ergebnis.letzteZeit = e.timestamp;

    // Jeder Transkript-Eintrag traegt das cwd, das zu diesem Zeitpunkt galt.
    // Rueckwaerts gelesen ist der erste Treffer der aktuelle Stand.
    if (e.cwd && !ergebnis.cwd) ergebnis.cwd = e.cwd;

    // Die Claude-Code-Version steht je Eintrag im Transkript. Damit ist sie
    // auch ueber das Mesh je Instanz bekannt - ein Aufruf von "claude
    // --version" auf dem fernen Rechner ist dafuer nicht noetig.
    if (e.version && !ergebnis.version) ergebnis.version = e.version;

    // Ein Compact erzeugt keinen Modellaufruf. Ohne diesen Zweig bliebe der
    // Wert von vor dem Compact stehen, bis die Sitzung wieder antwortet.
    // Weil rueckwaerts gelesen wird, gewinnt der juengere der beiden Marker.
    if (e.type === 'system' && e.subtype === 'compact_boundary' && !kontextGesetzt) {
      const m = e.compactMetadata;
      if (m && typeof m.postTokens === 'number') {
        ergebnis.kontext = m.postTokens;
        ergebnis.nachCompact = true;
        kontextGesetzt = true;
      }
    }

    if (e.type === 'assistant' && e.message) {
      const u = e.message.usage;
      if (u && !kontextGesetzt) {
        ergebnis.kontext = (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
        kontextGesetzt = true;
      }
      if (e.message.model && !ergebnis.modell) ergebnis.modell = e.message.model;
      if (!ergebnis.letztesTool && Array.isArray(e.message.content)) {
        const tu = e.message.content.filter((c) => c.type === 'tool_use');
        if (tu.length) ergebnis.letztesTool = tu[tu.length - 1].name;
      }
    }

    if (e.type === 'user' && !ergebnis.aufgabe && e.message) {
      const text = aufgabeAusInhalt(e.message.content);
      // Werkzeugergebnisse und Systemtexte sind keine Aufgabe.
      if (text && !text.startsWith('Base directory') && !text.startsWith('<')) {
        ergebnis.aufgabe = text;
      }
    }
  }

  if (voll) {
    // Dieselbe Antwort steht mehrfach im Transkript, weil Streaming-Zwischen-
    // staende eigene Zeilen bekommen. Gemessen am 01.08.2026 ueber den ganzen
    // Bestand: 22.667 Zeilen mit usage zu nur 10.687 eindeutigen message.id,
    // die naive Summe zaehlte also um den Faktor 2,085 zu hoch. Deduplizieren
    // nach message.id, der spaetere Eintrag gewinnt - first-wins lag messbar
    // daneben, weil der letzte Zwischenstand der vollstaendige ist.
    const proAntwort = new Map();
    for (const z of zeilen) {
      if (!z.includes('"usage"')) continue;
      let e;
      try { e = JSON.parse(z); } catch { continue; }
      const u = e.message && e.message.usage;
      if (!u) continue;
      // <synthetic> markiert Abbruch- und Fehlerzeilen, deren Werte alle 0
      // sind - sie wuerden die Zahl der Aufrufe aufblaehen.
      if (e.message.model === '<synthetic>') continue;
      proAntwort.set(e.message.id || e.requestId || `${proAntwort.size}`, u);
    }

    for (const u of proAntwort.values()) {
      ergebnis.aufrufe += 1;
      // Echter Neuverbrauch. cache_read gehoert NICHT dazu: er wiederholt bei
      // jedem Turn denselben Kontext und uebersteigt den Neuinhalt gemessen um
      // das Hundertfache (eine Sitzung: 1,16 Mrd gelesen gegen 9,9 Mio neu
      // erzeugt) - als "Verbrauch" waere das grob irrefuehrend. input_tokens
      // sind ueberwiegend Platzhalter mit Werten von 1 bis 4, kosten in der
      // Summe aber nichts und bleiben deshalb drin.
      ergebnis.tokens += (u.output_tokens || 0) + (u.input_tokens || 0)
        + (u.cache_creation_input_tokens || 0);
      ergebnis.cacheGelesen += (u.cache_read_input_tokens || 0);
    }
  }
  return ergebnis;
}

// ---------------------------------------------------------------------------
// Formatierung
// ---------------------------------------------------------------------------

function dauer(msSeit) {
  const min = Math.floor(msSeit / 60000);
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, '0')}m`;
}

function tok(n) {
  if (!n) return '-';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} Mio`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(n);
}

function kuerze(s, n) {
  if (!s) return '';
  return s.length > n ? '…' + s.slice(s.length - n + 1) : s;
}

function ordnerKurz(cwd) {
  return (cwd || '').replace(homedir(), '~');
}

/**
 * Modell-ID auf das Nennenswerte kuerzen: aus "claude-opus-5" wird "Opus 5",
 * aus "claude-haiku-4-5-20251001" wird "Haiku 4.5". Der Datumsanhang und das
 * Praefix kosten nur Platz, unterschieden werden muessen Familie und Version.
 */
function modellKurz(id) {
  if (!id) return '-';
  // Das 1M-Fenster erklaert, warum eine Sitzung ueberhaupt 600k Kontext
  // erreichen kann - deshalb bleibt es sichtbar, nur kuerzer geschrieben.
  const langerKontext = id.includes('[1m]');
  const ohne = id.replace(/\[1m\]/, '').replace(/^claude-/, '').replace(/-\d{8}$/, '');
  const teile = ohne.split('-');
  const familie = teile.shift() || '';
  const version = teile.join('.');
  const name = familie.charAt(0).toUpperCase() + familie.slice(1);
  const voll = version ? `${name} ${version}` : name;
  return langerKontext ? `${voll} 1M` : voll;
}

/** Kontext einfaerben: ab 600k wird es eng, ab 800k kritisch. */
function kontextFarbe(k) {
  if (k >= 800_000) return ROT;
  if (k >= 600_000) return GELB;
  return GRAU;
}

// ---------------------------------------------------------------------------
// Aktionen
// ---------------------------------------------------------------------------

function sammle({ voll = false } = {}) {
  const instanzen = ladeInstanzen();
  const namen = ladeNamen();
  const selbst = process.env.CLAUDE_CODE_SESSION_ID;
  const jetzt = Date.now();

  const zeilen = instanzen.map((i) => {
    const name = vergibName(namen, i.sessionId);
    const pfad = findeTranskript(i.sessionId);
    const t = leseTranskript(pfad, { voll });

    // Wartende Post. Wichtig, weil eine idle Instanz ihre Nachrichten NICHT
    // von allein bekommt: der Stop-Hook feuert nur, wenn sie eine Antwort
    // beendet. Wer wartet, beendet nichts.
    let post = 0;
    try { post = offeneNachrichten(i.sessionId, name).neu.length; } catch { /* Bus optional */ }

    // Ein Resume startet einen neuen Prozess, setzt aber dieselbe Sitzung
    // fort. startedAt zeigt dann Minuten, obwohl das Gespraech Stunden alt
    // ist - deshalb zusaetzlich das Alter aus dem Transkript.
    const laufzeit = jetzt - Number(i.startedAt);
    const beginn = pfad ? beginnDesGespraechs(pfad) : null;
    const gespraech = null === beginn ? laufzeit : jetzt - beginn;

    return {
      name, status: i.status, pid: i.pid,
      sessionId: i.sessionId, selbst: i.sessionId === selbst,
      laufzeit, gespraech, fortgesetzt: gespraech - laufzeit > 300_000,
      pfad, post, ...t,
      // claude agents --json meldet das Verzeichnis, in dem der Prozess
      // GESTARTET wurde. Wechselt die Sitzung danach in einen Unterordner,
      // bleibt dort das alte stehen - das Transkript kennt den aktuellen
      // Stand und gewinnt deshalb, wo es einen liefert.
      cwd: t.cwd || i.cwd,
    };
  });
  speichereNamen(namen);
  zeilen.sort((a, b) => (a.status === b.status ? a.name.localeCompare(b.name) : a.status === 'busy' ? -1 : 1));
  return zeilen;
}

function zeigeTabelle(zeilen, { voll = false, clear = false } = {}) {
  if (clear) process.stdout.write('\x1b[2J\x1b[H');
  if (!zeilen.length) {
    console.log(`\n  ${GELB}Keine laufenden Instanzen gefunden.${R}\n`);
    return;
  }

  const stand = new Date().toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
  console.log(`\n  ${CYAN}${FETT}Claude-Instanzen auf ${rechner()}${R}   ${GRAU}${stand}${R}\n`);

  let kopf = `  ${'Name'.padEnd(13)}${'Status'.padEnd(7)}${'Ordner'.padEnd(24)}${'Modell'.padEnd(9)}${'Läuft'.padStart(8)}${'Kontext'.padStart(10)}`;
  if (voll) kopf += `${'Tokens'.padStart(11)}`;
  console.log(`${GRAU}${kopf}${R}`);
  console.log(`${GRAU}  ${'-'.repeat(voll ? 82 : 71)}${R}`);

  for (const z of zeilen) {
    const farbe = z.status === 'busy' ? GRUEN : '';
    const marke = z.selbst ? '*' : ' ';
    let text = `${marke} ${z.name.padEnd(12)}${farbe}${z.status.padEnd(7)}${R}`
      + `${kuerze(ordnerKurz(z.cwd), 23).padEnd(24)}`
      + `${GRAU}${modellKurz(z.modell).padEnd(9)}${R}`
      + `${(dauer(z.laufzeit) + (z.fortgesetzt ? '+' : '')).padStart(8)}`
      + `${kontextFarbe(z.kontext)}${tok(z.kontext).padStart(10)}${R}`;
    if (voll) text += `${tok(z.tokens).padStart(11)}`;
    console.log(text);
  }

  const busy = zeilen.filter((z) => z.status === 'busy').length;
  const plus = zeilen.some((z) => z.fortgesetzt) ? '   + = fortgesetzte Sitzung' : '';
  console.log(`\n  ${GRAU}${zeilen.length} Instanzen, davon ${busy} beschäftigt   * = diese Sitzung${plus}${R}`);

  // Post an wartende Instanzen bleibt liegen, bis jemand sie anstösst.
  const mitPost = zeilen.filter((z) => z.post > 0);
  if (mitPost.length) {
    for (const z of mitPost) {
      const wie = z.status === 'busy'
        ? 'bekommt sie, sobald die aktuelle Antwort fertig ist'
        : 'wartet - holt sie erst ab, wenn du dort etwas eingibst';
      console.log(`  ${GELB}${z.name}: ${z.post} Nachricht(en) im Bus${R} ${GRAU}- ${wie}${R}`);
    }
  }
  const eng = zeilen.filter((z) => z.kontext >= 600_000);
  if (eng.length) {
    console.log(`  ${GELB}${eng.length} Sitzung(en) mit großem Kontext: ${eng.map((z) => z.name).join(', ')} - dort lohnt /compact${R}`);
  }
  if (!voll) console.log(`  ${GRAU}Kontext = aktueller Füllstand. Mit --tokens auch den Gesamtverbrauch.${R}`);
  console.log('');
}

function zeigeDetail(suchName) {
  const zeilen = sammle({ voll: true });
  const gesucht = suchName.toLowerCase();

  // Alias: alle Instanzen nacheinander im Detail, mit nur einem Sammellauf
  if (gesucht === 'all' || gesucht === 'alle') {
    for (const z of zeilen) druckeDetail(z);
    return;
  }

  const z = zeilen.find((x) => x.name.toLowerCase() === gesucht);
  if (!z) {
    console.log(`\n  ${GELB}Keine Instanz namens "${suchName}".${R}`);
    console.log(`  ${GRAU}Bekannt: ${zeilen.map((x) => x.name).join(', ')} (oder all)${R}\n`);
    process.exitCode = 1;
    return;
  }

  druckeDetail(z);
}

function druckeDetail(z) {
  const seit = z.letzteZeit
    ? dauer(Date.now() - Date.parse(z.letzteZeit)) + ' still'
    : 'unbekannt';

  console.log(`\n  ${CYAN}${FETT}${z.name}${R}${z.selbst ? `  ${GRAU}(diese Sitzung)${R}` : ''}\n`);
  const p = (k, v) => console.log(`    ${GRAU}${k.padEnd(18)}${R}${v}`);
  p('Status', z.status === 'busy' ? `${GRUEN}busy${R}` : 'idle');
  p('Ordner', ordnerKurz(z.cwd));
  p('Läuft seit', z.fortgesetzt
    ? `${dauer(z.laufzeit)} ${GRAU}(Prozess, fortgesetzte Sitzung)${R}`
    : dauer(z.laufzeit));
  if (z.fortgesetzt) p('Gespräch seit', dauer(z.gespraech));
  p('Letzte Aktion', z.status === 'busy' ? 'jetzt' : seit);
  p('Modell', z.modell || '-');
  p('Letztes Werkzeug', z.letztesTool || '-');
  const woher = z.nachCompact ? ` ${GRAU}(Stand nach Compact)${R}` : '';
  p('Kontext', `${kontextFarbe(z.kontext)}${tok(z.kontext)}${R}${woher}`);
  p('Verbraucht', `${tok(z.tokens)} neu in ${z.aufrufe} Aufrufen`);
  p('Aus Cache', `${tok(z.cacheGelesen)} gelesen (wiederholter Kontext, kein Neuverbrauch)`);
  p('PID', z.pid);
  p('Session', z.sessionId);
  if (z.aufgabe) {
    console.log(`\n    ${GRAU}Woran sie sitzt${R}`);
    console.log(`    ${z.aufgabe.slice(0, 300)}${z.aufgabe.length > 300 ? '…' : ''}`);
  }
  console.log('');
}

/**
 * Stellt eine Rueckfrage auf dem Terminal.
 *
 * Sitzt niemand davor, wird NICHT gefragt, sondern sofort abgelehnt. Ohne
 * diese Sperre haengt der Zeileneditor sich in eine fremde Standardeingabe -
 * ruft eine Oberflaeche den Befehl auf, ist das deren eigenes Terminal, und
 * die Rueckfrage erscheint mitten in deren Bild. Wer keine Rueckfrage
 * beantworten kann, soll den Befehl mit --force erteilen.
 *
 * @param {string} text  Die Frage samt Eingabeaufforderung.
 * @returns {Promise<string>}  Antwort in Kleinschreibung, leer wenn kein TTY.
 */
async function frage(text) {
  if (!process.stdin.isTTY) return '';
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const antwort = await new Promise((res) => rl.question(text, res));
  rl.close();
  return antwort.trim().toLowerCase();
}

async function stoppe(suchName, { ohneRueckfrage = false } = {}) {
  const zeilen = sammle();
  const z = zeilen.find((x) => x.name.toLowerCase() === suchName.toLowerCase());
  if (!z) {
    console.log(`\n  ${GELB}Keine Instanz namens "${suchName}".${R}\n`);
    process.exitCode = 1;
    return;
  }
  if (z.selbst) {
    console.log(`\n  ${ROT}Das ist diese Sitzung. Selbstmord wird nicht angeboten.${R}\n`);
    process.exitCode = 1;
    return;
  }

  console.log(`\n  ${z.name}  ${z.status}  ${ordnerKurz(z.cwd)}  PID ${z.pid}`);
  if (z.status === 'busy') {
    console.log(`  ${ROT}Achtung: die Instanz arbeitet gerade. Beenden kann eine laufende Änderung abschneiden.${R}`);
  }

  if (!ohneRueckfrage) {
    if (!process.stdin.isTTY) {
      console.log(`  ${ROT}Keine Rückfrage möglich - hier hängt kein Terminal.${R}`);
      console.log(`  ${GRAU}Wer nicht antworten kann, erteilt den Befehl mit --force.${R}\n`);
      process.exitCode = 1;
      return;
    }
    const a = await frage(`  ${z.name} wirklich beenden? [j/N] `);
    if (a !== 'j' && a !== 'ja') {
      console.log(`  ${GRAU}Abgebrochen.${R}\n`);
      return;
    }
  }

  // Vor dem Signal pruefen, WEN wir da treffen. Die PID stammt aus einer
  // Momentaufnahme; ist die Instanz dazwischen ausgestiegen, kann das
  // Betriebssystem dieselbe Nummer laengst neu vergeben haben - unter Windows
  // geschieht das schnell. Ein SIGTERM ginge dann an einen unbeteiligten
  // Prozess, und weil Windows dafuer TerminateProcess benutzt, stirbt der
  // ohne jede Chance aufzuraeumen.
  const traeger = prozessName(z.pid);
  if (!traeger.includes('claude')) {
    const was = traeger ? `"${traeger}"` : 'nicht ermittelbar';
    console.log(`\n  ${ROT}PID ${z.pid} gehört nicht mehr zu Claude (${was}).${R}`);
    console.log(`  ${GRAU}Nichts beendet. Liste mit "sanctuary status" neu holen.${R}\n`);
    process.exitCode = 1;
    return;
  }

  try {
    process.kill(Number(z.pid), 'SIGTERM');
    console.log(`  ${GRUEN}${z.name} (PID ${z.pid}) beendet.${R}\n`);
  } catch (e) {
    console.log(`  ${ROT}Konnte nicht beenden: ${e.message}${R}\n`);
    process.exitCode = 1;
  }
}

function zeigeNamen(argv = []) {
  const namen = ladeNamen();
  const { motiv, namen: pool, reserviert } = aktivesMotiv();

  if (argv.includes('--json')) {
    const vergeben = Object.values(namen);
    console.log(JSON.stringify({
      rechner: rechner(),
      motiv,
      reserviert,
      // Reservierte Namen zaehlen nicht zum Motiv - sonst haette "Comicmotiv"
      // ploetzlich 20 statt 19 Namen.
      namen: pool.filter((n) => !reserviert.includes(n)),
      frei: pool.filter((n) => !vergeben.includes(n)),
      vergeben: namen,
    }, null, 1));
    return;
  }

  console.log('');
  const eintraege = Object.entries(namen);
  if (!eintraege.length) {
    console.log(`  ${GRAU}Noch keine Namen vergeben.${R}`);
  } else {
    console.log(`  ${CYAN}Vergebene Namen (${eintraege.length})${R}`);
    for (const [sid, name] of eintraege.sort((a, b) => a[1].localeCompare(b[1]))) {
      // Namen aus einem anderen Motiv kennzeichnen - nach einem Wechsel laufen
      // beide eine Weile nebeneinander.
      const fremd = pool.includes(name) ? '' : ` ${GRAU}(anderes Motiv)${R}`;
      console.log(`    ${name.padEnd(14)}${GRAU}${sid}${R}${fremd}`);
    }
  }
  const frei = pool.filter((n) => !Object.values(namen).includes(n)).length;
  // Reservierte Namen gehoeren keinem Motiv an und werden deshalb getrennt
  // ausgewiesen, sonst haette "Comicmotiv" ploetzlich 20 statt 19 Namen.
  const zusatz = reserviert.length ? `, reserviert: ${reserviert.join(', ')}` : '';
  console.log(`\n  ${GRAU}Motiv "${motiv}": ${pool.length - reserviert.length} Namen, ${frei} frei${zusatz}${R}\n`);
}

function zeigeMotive(wunsch) {
  if (wunsch) {
    const neu = setzeMotiv(wunsch);
    if (!neu) {
      console.log(`\n  ${GELB}Kein Motiv namens "${wunsch}".${R}`);
      console.log(`  ${GRAU}Verfügbar: ${alleMotive().map((m) => m.schluessel).join(', ')}${R}\n`);
      process.exitCode = 1;
      return;
    }
    console.log(`\n  ${GRUEN}Motiv umgestellt auf "${neu.motiv}" (${neu.namen.length} Namen).${R}`);
    console.log(`  ${GRAU}Gilt für neu vergebene Namen. Laufende Instanzen behalten ihren -${R}`);
    console.log(`  ${GRAU}sonst wäre die Übersicht mitten im Betrieb wertlos.${R}`);
    console.log(`  ${GRAU}Beendete Zuordnungen aufräumen mit: reset-names${R}\n`);
    return;
  }

  console.log(`\n  ${CYAN}Verfügbare Motive${R}\n`);
  for (const m of alleMotive()) {
    const marke = m.aktiv ? `${GRUEN}*${R}` : ' ';
    console.log(`  ${marke} ${m.schluessel.padEnd(15)}${m.motiv.padEnd(24)}${GRAU}${m.anzahl} Namen${R}`);
  }
  console.log(`\n  ${GRAU}Umschalten mit: operator.mjs motiv <schluessel>${R}`);
  console.log(`  ${GRAU}Neues Motiv anlegen: Eintrag unter "pools" in namenspool.local.json (bleibt lokal)${R}\n`);
}

/**
 * Benennt die aufrufende Sitzung auf den reservierten Operator-Namen um.
 *
 * Der reservierte Name geht sonst an die zufaellig zuerst gestartete Sitzung,
 * und "zuerst gestartet" ist nicht dasselbe wie "hier wird der Operator
 * bedient". Wer den Skill benutzt, soll auch so heissen - der bisherige Name
 * wird dabei wieder frei.
 */
function werdeOperator() {
  const meine = process.env.CLAUDE_CODE_SESSION_ID;
  const ziel = aktivesMotiv().reserviert[0] || 'Operator';
  if (!meine) {
    console.log(`\n  ${ROT}CLAUDE_CODE_SESSION_ID ist nicht gesetzt - von ausserhalb einer Sitzung aufgerufen?${R}\n`);
    process.exitCode = 1;
    return;
  }

  const namen = ladeNamen();
  const alt = namen[meine];
  if (alt === ziel) {
    console.log(`\n  ${GRAU}Heisst bereits ${ziel}.${R}\n`);
    return;
  }

  // Einer laufenden Sitzung wird der Name NICHT weggenommen - sonst zeigt die
  // Tabelle mitten im Betrieb zwei verschiedene Instanzen unter einem Namen.
  const inhaber = Object.entries(namen).find(([sid, n]) => n === ziel && sid !== meine);
  if (inhaber) {
    const laeuft = ladeInstanzen().some((i) => i.sessionId === inhaber[0]);
    if (laeuft) {
      console.log(`\n  ${GELB}${ziel} ist an eine laufende Sitzung vergeben (${inhaber[0].slice(0, 8)}).${R}`);
      console.log(`  ${GRAU}Dort beenden oder einen anderen Namen wählen.${R}\n`);
      process.exitCode = 1;
      return;
    }
    // Dieselbe Regel wie beim Aufraeumen: mit dem Namen geht das Postfach.
    // Sonst faende ich hier gleich die Auftraege meines Vorgaengers vor.
    postfachSchliessen([[inhaber[0], ziel]]);
    delete namen[inhaber[0]];
  }

  namen[meine] = ziel;
  speichereNamen(namen);
  console.log(`\n  ${GRUEN}${alt ? `${alt} heisst jetzt ${ziel}` : `Name ${ziel} uebernommen`}.${R}`);
  console.log(`  ${GRAU}Die Statuszeile zieht den Namen bei ihrem nächsten Neuzeichnen nach.${R}\n`);
}

/**
 * Fragt einen anderen Rechner im Tailnet nach seiner Instanzliste.
 *
 * Bewusst derselbe Befehl wie lokal, nur ueber ssh - damit gibt es keine
 * zweite Auswertungslogik, die auseinanderlaufen kann. Ein nicht erreichbarer
 * Rechner ist der Normalfall (abgeschaltet, unterwegs) und darf die Sicht auf
 * die uebrigen nicht kippen, deshalb wird der Fehler zurueckgegeben statt
 * geworfen.
 */
async function holeVonFerne(host) {
  // Zwei Anlaeufe, weil es keinen Aufruf gibt, der auf beiden Systemen traegt
  // (alles am 01.08.2026 gemessen):
  //   1. "sanctuary status --json" - greift auf Windows, weil der sshd dort
  //      den Benutzer-PATH samt ~/.local/bin mitbringt. Auf Linux scheitert es
  //      mit "Befehl nicht gefunden", denn eine nicht-interaktive Shell liest
  //      die .bashrc nicht (Ubuntu bricht dort oben per "case $- in *i*" ab).
  //   2. "bash -lc ..." - greift auf Linux. Auf RAINBOW fuehrt es dagegen in
  //      die WSL statt in die Git Bash, und dort gibt es kein node.
  // Ein Pfad mit ~ scheidet ganz aus: unter cmd und PowerShell ist die Tilde
  // ein gewoehnliches Zeichen, "node ~/.claude/..." endete in ERR_MODULE_NOT_FOUND.
  const versuche = ['sanctuary status --json', 'bash -lc "sanctuary status --json"'];
  let stdout;
  let letzterFehler = '';
  for (const befehl of versuche) {
    try {
      // ConnectTimeout knapp halten: die Abfragen laufen zwar parallel, aber
      // ein abgeschalteter Rechner verzoegert die Gesamtanzeige um genau diese
      // Spanne. Gemessen mit dem offline dell - 8 s Timeout ergaben 8,8 s
      // Gesamtlaufzeit, obwohl lokal und senza laengst geantwortet hatten.
      ({ stdout } = await execFileAsync(
        'ssh',
        ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, befehl],
        { timeout: 20000, maxBuffer: 8 * 1024 * 1024 },
      ));
      break;
    } catch (e) {
      // ssh meldet "Connection refused"/"timed out" auf stderr, execFile packt
      // das in e.stderr - die erste Zeile davon ist die brauchbare Auskunft.
      letzterFehler = (e.stderr || e.message || '').split('\n')[0].trim();
      // Ist der Rechner gar nicht da, bringt der zweite Anlauf nichts.
      if (/connect|timed out|refused|resolve/i.test(letzterFehler)) break;
    }
  }
  if (!stdout) {
    return { host, rechner: host.toUpperCase(), instanzen: [], fehler: letzterFehler || 'nicht erreichbar' };
  }

  try {
    const daten = JSON.parse(stdout);
    return {
      host,
      rechner: daten.rechner,
      system: daten.system || null,
      claudeVersion: daten.claudeVersion || null,
      anmeldung: daten.anmeldung || null,
      instanzen: daten.instanzen,
      fehler: null,
    };
  } catch {
    // Faellt eine gefaerbte Tabelle statt JSON zurueck, kennt die Gegenseite
    // --json noch nicht. Der rohe Parserfehler ("Unexpected token") sagt das
    // nicht und schickt einen auf die falsche Faehrte.
    return { host, rechner: host.toUpperCase(), instanzen: [], fehler: 'keine JSON-Antwort - dort git pull noetig?' };
  }
}

/**
 * Trennt die Hosts vorab in erreichbare und offline gemeldete.
 *
 * Ohne das kostet jeder abgeschaltete Rechner den vollen ConnectTimeout und
 * bestimmt damit die Gesamtlaufzeit - gemessen 5,9 s mit dem offline dell,
 * obwohl lokal und senza nach unter einer Sekunde geantwortet hatten.
 * "tailscale status --json" kennt die Antwort in 69 ms.
 *
 * Faellt die Abfrage aus (kein Tailscale installiert, Dienst laeuft nicht),
 * werden ALLE Hosts als erreichbar behandelt - lieber langsam als blind eine
 * laufende Instanz verschweigen.
 */
async function tailscaleOnline() {
  try {
    const { stdout } = await execFileAsync('tailscale', ['status', '--json'], { timeout: 5000 });
    const j = JSON.parse(stdout);
    const stand = new Map();
    for (const p of Object.values(j.Peer || {})) {
      if (p.HostName) stand.set(p.HostName.toLowerCase(), Boolean(p.Online));
    }
    return stand;
  } catch {
    return null;
  }
}

/**
 * Lokale Sicht plus alle Rechner aus mesh.json, parallel abgefragt.
 *
 * Parallel, weil die Wartezeit sonst mit jedem Rechner waechst: ein
 * SSH-Aufruf kostet rund 280 ms Verbindungsaufbau plus die Laufzeit drueben,
 * und die laeuft neben dem lokalen Lauf her.
 */
async function sammleMesh({ voll = false } = {}) {
  let hosts = [];
  try {
    hosts = JSON.parse(readFileSync(join(SKILL_DIR, 'mesh.json'), 'utf8')).hosts || [];
  } catch { /* ohne mesh.json bleibt nur der eigene Rechner */ }

  const selbst = rechner();
  const fremde = hosts.filter((h) => h.toUpperCase() !== selbst);
  const online = await tailscaleOnline();
  const antworten = await Promise.all(fremde.map((h) => {
    if (online && online.get(h.toLowerCase()) === false) {
      return { host: h, rechner: h.toUpperCase(), instanzen: [], fehler: 'offline (Tailscale)' };
    }
    return holeVonFerne(h);
  }));
  const eigeneInstanzen = sammle({ voll });
  const eigen = {
    host: selbst.toLowerCase(),
    rechner: selbst,
    system: systemName(),
    claudeVersion: claudeVersion(eigeneInstanzen),
    anmeldung: anmeldungBis(),
    instanzen: eigeneInstanzen,
    fehler: null,
  };
  return [eigen, ...antworten];
}

function zeigeMesh(bloecke) {
  console.log(`\n  ${CYAN}${FETT}Claude-Instanzen im Mesh${R}   ${GRAU}${new Date().toLocaleString('de-DE')}${R}\n`);
  let gesamt = 0;
  for (const b of bloecke) {
    if (b.fehler) {
      console.log(`  ${GELB}${b.rechner.padEnd(12)}${R}${GRAU}${b.fehler}${R}`);
      continue;
    }
    if (!b.instanzen.length) {
      console.log(`  ${CYAN}${b.rechner.padEnd(12)}${R}${GRAU}keine Instanzen${R}`);
      continue;
    }
    for (const z of b.instanzen) {
      gesamt += 1;
      const marke = z.selbst ? '*' : ' ';
      const farbe = z.status === 'busy' ? GRUEN : GRAU;
      console.log(
        `${marke} ${CYAN}${kuerze(b.rechner, 11).padEnd(12)}${R}`
        + `${z.name.padEnd(13)}`
        + `${farbe}${z.status.padEnd(7)}${R}`
        + `${kuerze(ordnerKurz(z.cwd), 22).padEnd(23)}`
        + `${GRAU}${modellKurz(z.modell).padEnd(10)}${R}`
        + `${kontextFarbe(z.kontext)}${(z.kontext ? `${Math.round(z.kontext / 1000)}k` : '-').padStart(8)}${R}`,
      );
    }
  }
  const nichtDa = bloecke.filter((b) => b.fehler).length;
  console.log(`\n  ${GRAU}${gesamt} Instanz(en) auf ${bloecke.length - nichtDa} Rechner(n)`
    + `${nichtDa ? `, ${nichtDa} nicht erreichbar` : ''}   * = diese Sitzung${R}\n`);
}

/**
 * Maschinenlesbare Ausgabe derselben Daten, die auch die Tabelle zeigt.
 *
 * Fuer Werkzeuge, die den Operator aufrufen (geplante Agenten-TUI). Die
 * Tabelle ist fuer Menschen gebaut - wer sie zurueckparst, faellt bei der
 * naechsten Layoutaenderung auf die Nase, und ANSI-Farben stehen mit drin.
 *
 * einzeilig steuert NDJSON: im Stream MUSS ein Datensatz genau eine Zeile
 * belegen, sonst kann die Gegenseite nicht zeilenweise lesen.
 */
/**
 * Betriebssystem in lesbarer Kurzform.
 *
 * Auf Linux steht der brauchbare Name in /etc/os-release ("Ubuntu 24.04.4
 * LTS"); die Kernel-Version allein sagt niemandem etwas. macOS meldet seine
 * Version ueber release() ausreichend genau. Windows aber meldet sich im
 * Kernel weiterhin als "10.0.x" - auch Windows 11. Unterschieden wird ueber
 * die Build-Nummer (drittes Segment): ab 22000 ist es Windows 11.
 *
 * @returns {string}
 */
function systemName() {
  const p = platform();
  if (p === 'linux') {
    try {
      const treffer = readFileSync('/etc/os-release', 'utf8').match(/^PRETTY_NAME="?([^"\n]+)"?/m);
      if (treffer) return treffer[1];
    } catch { /* ohne os-release bleibt die Kernel-Angabe */ }
    return `Linux ${release()}`;
  }
  if (p === 'win32') return windowsName();
  if (p === 'darwin') return `macOS ${release()}`;
  return `${p} ${release()}`;
}

/**
 * Windows-Produktversion aus der Kernel-Version ableiten.
 *
 * release() liefert etwas wie "10.0.22631". Windows 11 meldet sich weiter
 * als "10.0", die Build-Nummer (drittes Segment) macht den Unterschied: ab
 * Build 22000 ist es Windows 11, darunter Windows 10. Die rohe Build-Nummer
 * bleibt fuer die Diagnose sichtbar.
 *
 * @returns {string}
 */
function windowsName() {
  const roh = release();
  const build = Number.parseInt(roh.split('.')[2], 10);
  if (!Number.isNaN(build)) {
    const produkt = build >= 22000 ? '11' : '10';
    return `Windows ${produkt} (Build ${build})`;
  }
  return `Windows ${roh}`;
}

/**
 * Wann eine neue Anmeldung faellig wird.
 *
 * Entscheidend ist der REFRESH-Token, nicht der Zugriffstoken: letzterer
 * laeuft nach wenigen Stunden ab und wird still erneuert. Erst wenn der
 * Refresh-Token abgelaufen ist, muss sich der Benutzer neu anmelden.
 *
 * Gelesen wird ausschliesslich dieser Zeitstempel - die Token selbst werden
 * nicht angefasst und tauchen nirgends in der Ausgabe auf.
 *
 * @returns {string|null}
 * ISO-Zeitstempel, oder null wenn die Datei fehlt (etwa wenn die Anmeldung
 * im Schluesselbund liegt).
 */
function anmeldungBis() {
  try {
    const datei = join(homedir(), '.claude', '.credentials.json');
    const ms = JSON.parse(readFileSync(datei, 'utf8'))?.claudeAiOauth?.refreshTokenExpiresAt;
    return typeof ms === 'number' ? new Date(ms).toISOString() : null;
  } catch {
    return null;
  }
}

/**
 * Installierte Claude-Code-Version dieses Rechners.
 *
 * Erste Wahl ist das Transkript einer laufenden Instanz - dort steht die
 * Version in jedem Eintrag und kostet nichts. Nur wenn KEINE Instanz eine
 * hat (alle frisch gestartet, noch kein Zug), wird "claude --version"
 * aufgerufen. Der Aufruf kostet rund 100 ms und wuerde die Statusabfrage
 * sonst bei jedem Takt verdoppeln.
 *
 * @param {object[]} zeilen
 * Die bereits gesammelten Instanzen.
 * @returns {string|null}
 */
function claudeVersion(zeilen) {
  const ausTranskript = zeilen.find((z) => z.version)?.version;
  if (ausTranskript) return ausTranskript;
  try {
    const exe = process.env.CLAUDE_CODE_EXECPATH;
    const roh = exe
      ? execFileSync(exe, ['--version'], { encoding: 'utf8', timeout: 8000 })
      : execFileSync('claude --version', { encoding: 'utf8', timeout: 8000, shell: true });
    return (String(roh).match(/\d+\.\d+\.\d+/) || [null])[0];
  } catch {
    return null;
  }
}

function alsJson(zeilen, { einzeilig = false } = {}) {
  const daten = {
    rechner: rechner(),
    system: systemName(),
    claudeVersion: claudeVersion(zeilen),
    anmeldung: anmeldungBis(),
    zeit: new Date().toISOString(),
    anzahl: zeilen.length,
    instanzen: zeilen,
  };
  process.stdout.write(`${JSON.stringify(daten, null, einzeilig ? 0 : 1)}\n`);
}

function raeumeNamen() {
  const namen = ladeNamen();
  const aktiv = new Set(ladeInstanzen().map((i) => i.sessionId));
  const neu = {};
  const beendet = [];
  for (const [sid, name] of Object.entries(namen)) {
    if (aktiv.has(sid)) neu[sid] = name;
    else beendet.push([sid, name]);
  }
  speichereNamen(neu);
  const zurueck = postfachSchliessen(beendet);
  console.log(`\n  ${GRUEN}${beendet.length} Zuordnung(en) beendeter Sitzungen entfernt, ${Object.keys(neu).length} aktiv.${R}`);
  console.log(zurueck.length
    ? `  ${GELB}${zurueck.length} offene(r) Auftrag/Aufträge an diese Sitzungen zurückgenommen.${R}\n`
    : '\n');
}

/**
 * Nimmt die offenen Auftraege beendeter Sitzungen zurueck.
 *
 * Der Name ist eine Pacht, und das Postfach gehoert dazu. Wird der Name
 * freigegeben, ohne dass seine Post mitgeht, erbt sie der naechste Inhaber -
 * am 07.08.2026 hat eine neue Marga so einen vier Tage alten Auftrag an ihre
 * Vorgaengerin abgearbeitet. Betroffen sind nur Auftraege, die an die SITZUNG
 * gebunden waren; ausdrueckliche Rollenauftraege ueberleben und verfallen
 * stattdessen nach Frist.
 *
 * @param {Array<[string,string]>} beendet
 * Paare aus Session-ID und Name.
 * @returns {string[]} IDs der zurueckgenommenen Auftraege.
 */
function postfachSchliessen(beendet) {
  if (!beendet.length) return [];
  try {
    const db = oeffneBus(datenDir());
    const ids = beendet.flatMap(([sid, name]) => pachtEndet(db, sid, name));
    db.close();
    return ids;
  } catch {
    // Ein blockierter Bus (Pfad nicht isoliert) darf das Aufraeumen der
    // Namenstabelle nicht verhindern - die ist davon unabhaengig.
    return [];
  }
}

async function beobachte(sekunden, voll, json = false) {
  const takt = Math.max(2, sekunden || 10) * 1000;
  const zeichne = () => {
    // Ein langlebiger Prozess, der je Takt eine NDJSON-Zeile schreibt, statt
    // dass die Gegenseite im Sekundentakt einen neuen startet: der
    // Prozessstart kostet unter Windows 70-105 ms, die Nutzlast selbst bei
    // 100 Instanzen nur 60 KB. Der Engpass ist die Prozesszahl, nicht die
    // Datenmenge - deshalb Stream statt Polling.
    if (json) {
      alsJson(sammle({ voll }), { einzeilig: true });
      return;
    }
    zeigeTabelle(sammle({ voll }), { voll, clear: true });
    console.log(`  ${GRAU}Aktualisierung alle ${takt / 1000}s, Abbruch mit Strg+C${R}\n`);
  };
  zeichne();
  setInterval(zeichne, takt);
}

// ---------------------------------------------------------------------------

const argv = process.argv.slice(2);
const befehl = argv[0] || 'status';
const voll = argv.includes('--tokens');
const json = argv.includes('--json');
const mesh = argv.includes('--mesh');
const rest = argv.slice(1).filter((a) => !a.startsWith('--'));

switch (befehl) {
  case 'status':
    if (mesh) {
      const bloecke = await sammleMesh({ voll });
      if (json) {
        process.stdout.write(`${JSON.stringify({ zeit: new Date().toISOString(), rechner: bloecke }, null, 1)}\n`);
      } else zeigeMesh(bloecke);
    } else if (json) {
      // "status all --json" ist dasselbe wie "status --json" - all ist nur in
      // der Detailansicht ein Sonderfall.
      const alle = sammle({ voll });
      const gefiltert = rest[0] && rest[0] !== 'all'
        ? alle.filter((z) => z.name.toLowerCase() === rest[0].toLowerCase())
        : alle;
      alsJson(gefiltert);
    } else if (rest[0]) zeigeDetail(rest[0]);
    else zeigeTabelle(sammle({ voll }), { voll });
    break;
  case 'watch':
    await beobachte(Number(rest[0]) || 10, voll, json);
    break;
  case 'stop':
    if (!rest[0]) { console.log('\n  Nutzung: operator.mjs stop <Name>\n'); process.exitCode = 1; }
    else await stoppe(rest[0], { ohneRueckfrage: argv.includes('--force') });
    break;
  case 'names': zeigeNamen(argv); break;
  // Englische Namen sind fuehrend, die deutschen bleiben als stille Aliase.
  case 'motif': case 'motiv': case 'motive': zeigeMotive(rest[0]); break;
  case 'reset-names': raeumeNamen(); break;
  case 'become-operator': case 'werde-operator': werdeOperator(); break;
  default:
    console.log(`
  Operator - Übersicht über laufende Claude-Instanzen

    status              Tabelle aller Instanzen
    status <Name>       Detailansicht einer Instanz
    status all          Detailansicht aller Instanzen
    watch [Sekunden]    Tabelle periodisch neu zeichnen (Standard 10s)
    stop <Name>         Instanz beenden (fragt nach, --force überspringt)
    names               vergebene Namen
    motif [schlüssel]   Namensmotive anzeigen oder umschalten
    reset-names         Zuordnungen beendeter Sitzungen aufräumen
    become-operator     diese Sitzung auf den reservierten Namen umbenennen

    --tokens            zusätzlich den Gesamtverbrauch (langsamer)
    --json              maschinenlesbar statt Tabelle; mit watch als
                        NDJSON-Strom, eine Zeile je Takt
    --mesh              zusätzlich die Rechner aus mesh.json per ssh
                        (nur mit status)
`);
}
