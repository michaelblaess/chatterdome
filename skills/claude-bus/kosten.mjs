// Misst, was das Messaging an Tokens gekostet hat.
//
// Grundlage: der Stop-Hook protokolliert jede Zustellung nach
// zustellungen.jsonl (Zeitpunkt, Empfaenger, Zeichenlaenge). Dieses Werkzeug
// korreliert das mit dem Sitzungstranskript.
//
// Der Overhead hat ZWEI Teile, und der zweite ist der groessere:
//
//   Kosten = Laenge  +  Laenge x (Modellaufrufe, die danach noch folgen)
//            ^^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
//            einmalig   Schleppkosten - der Text bleibt im Kontext und wird
//                       bei jedem weiteren Aufruf erneut mitgelesen
//
// Bewusst werden Unter- UND Obergrenze ausgewiesen:
//   Untergrenze = aus der Zeichenlaenge geschaetzt (rund 4 Zeichen je Token)
//   Obergrenze  = cache_creation des naechsten Aufrufs, ENTHAELT aber auch
//                 fremden neuen Kontext und ist deshalb zu hoch
// Der wahre Wert liegt dazwischen. Eine einzelne Zahl waere hier gelogen.

import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';

const R = '\x1b[0m', GRAU = '\x1b[38;5;244m', CYAN = '\x1b[38;5;80m', GELB = '\x1b[38;5;221m';

const ZEICHEN_JE_TOKEN = 4;

function rechner() {
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

function hostDir() {
  return join(process.env.CLAUDE_BUS_DIR || join(homedir(), '.claude', 'bus'), rechner());
}

function zeilen(pfad) {
  if (!existsSync(pfad)) return [];
  return readFileSync(pfad, 'utf8').split('\n').filter((z) => z.trim()).map((z) => {
    try { return JSON.parse(z); } catch { return null; }
  }).filter(Boolean);
}

function findeTranskript(sessionId) {
  const wurzel = join(homedir(), '.claude', 'projects');
  if (!existsSync(wurzel)) return null;
  for (const projekt of readdirSync(wurzel)) {
    const dir = join(wurzel, projekt);
    try {
      if (!statSync(dir).isDirectory()) continue;
      const treffer = join(dir, `${sessionId}.jsonl`);
      if (existsSync(treffer)) return treffer;
    } catch { /* weiter */ }
  }
  return null;
}

/** Alle Modellaufrufe einer Sitzung als (Zeitpunkt, Usage). */
function aufrufe(pfad) {
  const raus = [];
  for (const z of readFileSync(pfad, 'utf8').split('\n')) {
    if (!z.includes('"usage"')) continue;
    let e;
    try { e = JSON.parse(z); } catch { continue; }
    if (e.type !== 'assistant' || !e.message || !e.message.usage) continue;
    const u = e.message.usage;
    raus.push({
      t: e.timestamp ? Date.parse(e.timestamp) : 0,
      neu: u.cache_creation_input_tokens || 0,
      gelesen: u.cache_read_input_tokens || 0,
      aus: u.output_tokens || 0,
    });
  }
  return raus.sort((a, b) => a.t - b.t);
}

function n(x) {
  return Math.round(x).toLocaleString('de-DE');
}

// ---------------------------------------------------------------------------

const zustellungen = zeilen(join(hostDir(), 'zustellungen.jsonl'));
if (!zustellungen.length) {
  console.log(`\n  ${GRAU}Noch keine Zustellungen protokolliert.${R}\n`);
  process.exit(0);
}

// Nach Sitzung gruppieren, damit je Empfaenger gerechnet werden kann.
const jeSession = new Map();
for (const z of zustellungen) {
  if (!jeSession.has(z.session)) jeSession.set(z.session, []);
  jeSession.get(z.session).push(z);
}

console.log(`\n  ${CYAN}Kosten der Nachrichtenzustellung${R}\n`);

let gesamtUnten = 0, gesamtOben = 0, gesamtZahl = 0;

for (const [session, liste] of jeSession) {
  const pfad = findeTranskript(session);
  const name = liste[0].name || session.slice(0, 8);

  if (!pfad) {
    console.log(`  ${name}: Transkript nicht gefunden, ${liste.length} Zustellung(en)`);
    continue;
  }

  const alle = aufrufe(pfad);
  let unten = 0, oben = 0, nochOffen = 0;

  for (const z of liste) {
    const t = Date.parse(z.ts);
    const danach = alle.filter((a) => a.t >= t);
    // Noch kein Modellaufruf seit der Zustellung: die Kosten sind noch nicht
    // entstanden und duerfen nicht als 0 durchgehen.
    if (!danach.length) { nochOffen++; continue; }

    const direktUnten = (z.zeichen || 0) / ZEICHEN_JE_TOKEN;
    const direktOben = danach[0].neu;
    const folgeAufrufe = Math.max(0, danach.length - 1);

    // Schleppkosten: der Text wird bei jedem Folgeaufruf erneut gelesen.
    unten += direktUnten * (1 + folgeAufrufe);
    oben += direktOben + direktUnten * folgeAufrufe;
  }

  gesamtUnten += unten;
  gesamtOben += oben;
  gesamtZahl += liste.length - nochOffen;

  const gemessen = liste.length - nochOffen;
  let zeile = `  ${name.padEnd(14)}${String(gemessen).padStart(3)} gemessen   `;
  zeile += gemessen > 0
    ? `${GRAU}zwischen${R} ${n(unten).padStart(9)} ${GRAU}und${R} ${n(oben).padStart(9)} ${GRAU}Tokens${R}`
    : `${GRAU}noch nichts messbar${R}`;
  if (nochOffen) zeile += `   ${GELB}(${nochOffen} noch ohne Folgeaufruf)${R}`;
  console.log(zeile);
}

console.log(`\n  ${'Gesamt'.padEnd(14)}${String(gesamtZahl).padStart(3)} gemessen   `
  + (gesamtZahl > 0
    ? `${GRAU}zwischen${R} ${n(gesamtUnten).padStart(9)} ${GRAU}und${R} ${n(gesamtOben).padStart(9)} ${GRAU}Tokens${R}`
    : `${GRAU}noch nichts messbar${R}`));

console.log(`\n  ${GRAU}Untergrenze aus der Zeichenlänge geschätzt (${ZEICHEN_JE_TOKEN} Zeichen je Token).${R}`);
console.log(`  ${GRAU}Obergrenze aus cache_creation des nächsten Aufrufs - enthält auch${R}`);
console.log(`  ${GRAU}fremden neuen Kontext und ist deshalb zu hoch. Der wahre Wert liegt dazwischen.${R}`);

// Vergleichsmassstab: was Polling gekostet haette.
const beispiel = 369126;
if (gesamtZahl > 0) {
  console.log(`\n  ${GELB}Zum Vergleich:${R} ein einzelner Leerlauf-Durchlauf per /loop kostete beim`);
  console.log(`  Halma-Duell im Schnitt ${n(beispiel)} Tokens - und zwar auch dann,`);
  console.log(`  wenn gar keine Nachricht vorlag. Der Stop-Hook kostet in dem Fall null.`);
}
console.log('');
