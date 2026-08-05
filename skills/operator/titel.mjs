// UserPromptSubmit-Hook-Helfer: baut den Sitzungstitel "<Name> · <Aufgabe>".
//
// Zweck: mehrere Claude-Fenster sind schwer auseinanderzuhalten. Claude Code
// setzt den Titel sonst auf eine Aufgaben-Zusammenfassung (aiTitle) - der
// Agenten-Name fehlt darin. Dieser Hook gibt "sessionTitle" aus, was Claude als
// "customTitle" UND "agentName" speichert. In der Titel-Prioritaet
// (agentName || customTitle || aiTitle) schlaegt das die Zusammenfassung, der
// Name klebt also stabil im Tab. Belegt am Binary v2.1.x (Jse -> type:"custom-title").
//
// Kehrseite bis 05.08.2026: weil der eigene Titel gewinnt, verschwand die
// Zusammenfassung auch aus dem Resume-Hinweis ("claude --resume <Titel>") - man
// sah nur noch Name und Ordner und wusste nicht mehr, woran die Sitzung sass.
// Deshalb wird die Zusammenfassung jetzt selbst nachgeschlagen und angehaengt:
// Claude schreibt sie als {"type":"ai-title","aiTitle":"..."} in dieselbe
// Sitzungsdatei, direkt neben den custom-title. Gibt es keine, bleibt es beim
// Ordnernamen wie zuvor.
//
// Der Name steht schon in namen.json (vom SessionStart-Hook whoami.mjs vergeben);
// hier wird er nur NACHGESCHLAGEN - kein Neuvergeben, kein "claude agents --json".
// So bleibt der Hook billig genug, um bei JEDEM Prompt zu laufen (ein
// Datei-Lesezugriff statt Sekunden).
//
// Ausgabe auf stdout: das Hook-JSON mit sessionTitle. Bei jedem Problem still mit
// Code 0 raus - kein Titel ist besser als ein zerbrochener Prompt-Submit.

import {
  closeSync,
  existsSync,
  fstatSync,
  openSync,
  readdirSync,
  readFileSync,
  readSync,
} from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join, basename } from 'node:path';

// Sitzungsdateien werden mehrere zehn MB gross (gemessen: 44 MB). Der Hook laeuft
// bei JEDEM Prompt, ganz einlesen scheidet damit aus. Die Titel-Eintraege schreibt
// Claude bei jedem Prompt neu fort, der juengste steht also am Dateiende - ein
// Schwanz von 64 KB reicht und kostet unabhaengig von der Sitzungslaenge gleich viel.
const SCHWANZ_BYTES = 64 * 1024;

function rechner() {
  // COMPUTERNAME bevorzugen, damit der Pfad exakt dem entspricht, was der
  // SessionStart-Hook benutzt. hostname() kann Suffixe wie .local liefern.
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
}

// Pfad der Sitzungsdatei. Claude legt sie unter ~/.claude/projects/<cwd>/<id>.jsonl
// ab, wobei <cwd> ein verstuemmelter Arbeitspfad ist ("C:\ZusatzSW\x" wird zu
// "C--ZusatzSW-x", auch der Unterstrich in Benutzernamen wird zum Bindestrich).
// Die Regel ist nirgends zugesichert, deshalb nur als schneller Versuch - danach
// werden die Projektordner abgesucht (~16 Eintraege, vernachlaessigbar).
function sessionDatei(cwd, sessionId) {
  const basis = join(homedir(), '.claude', 'projects');
  const geraten = join(basis, cwd.replace(/[^A-Za-z0-9]/g, '-'), `${sessionId}.jsonl`);
  if (existsSync(geraten)) return geraten;
  try {
    for (const ordner of readdirSync(basis)) {
      const kandidat = join(basis, ordner, `${sessionId}.jsonl`);
      if (existsSync(kandidat)) return kandidat;
    }
  } catch {
    // Kein projects-Verzeichnis - dann gibt es auch keine Zusammenfassung.
  }
  return '';
}

// Juengste Aufgaben-Zusammenfassung aus dem Dateiende, leerer String wenn keine da.
function letzteZusammenfassung(pfad) {
  let fd;
  try {
    fd = openSync(pfad, 'r');
    const groesse = fstatSync(fd).size;
    const start = Math.max(0, groesse - SCHWANZ_BYTES);
    const laenge = groesse - start;
    if (laenge <= 0) return '';
    const puffer = Buffer.allocUnsafe(laenge);
    readSync(fd, puffer, 0, laenge, start);
    const zeilen = puffer.toString('utf8').split('\n');
    // Bei einem Teil-Lesevorgang ist die erste Zeile angeschnitten (und kann mitten
    // in einem UTF-8-Zeichen beginnen) - die ist unbrauchbar.
    if (start > 0) zeilen.shift();
    for (let i = zeilen.length - 1; i >= 0; i -= 1) {
      const zeile = zeilen[i];
      if (!zeile.includes('"type":"ai-title"')) continue;
      try {
        const eintrag = JSON.parse(zeile);
        if (typeof eintrag.aiTitle === 'string' && eintrag.aiTitle.trim()) {
          // Steuerzeichen wuerden die Titel-Sequenz des Terminals zerlegen.
          return eintrag.aiTitle.replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
        }
      } catch {
        // Halbe oder fremde Zeile - weiter nach hinten suchen.
      }
    }
    return '';
  } catch {
    return '';
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        // Schliessen darf den Prompt nicht aufhalten.
      }
    }
  }
}

const sessionId = process.env.CLAUDE_CODE_SESSION_ID;
if (!sessionId) process.exit(0);

// Arbeitsverzeichnis: die Hook-Eingabe auf stdin traegt "cwd" mit, das ist die
// verlaesslichste Quelle. Rueckfall auf process.cwd(), falls stdin leer/blockt.
let cwd = process.cwd();
try {
  const roh = readFileSync(0, 'utf8');
  if (roh.trim()) {
    const eingabe = JSON.parse(roh);
    if (typeof eingabe.cwd === 'string' && eingabe.cwd) cwd = eingabe.cwd;
  }
} catch {
  // stdin ist optional - process.cwd() reicht.
}

let name;
try {
  const pfad = join(homedir(), '.claude', 'bus', rechner(), 'namen.json');
  const tabelle = JSON.parse(readFileSync(pfad, 'utf8'));
  name = tabelle[sessionId];
} catch {
  process.exit(0);
}

// Nur Buchstaben, Ziffern und Bindestrich. Der Ordnername kann alles enthalten,
// deshalb baut JSON.stringify die Ausgabe (kein printf, sauberes Escaping).
if (!name || !/^[A-Za-z0-9-]+$/.test(name)) process.exit(0);

// Die Zusammenfassung sagt mehr als der Ordner - der steht ohnehin in der
// Statuszeile. Fehlt sie (Claude erzeugt nicht in jeder Sitzung eine), bleibt es
// beim bisherigen Verhalten.
const datei = sessionDatei(cwd, sessionId);
const aufgabe = datei ? letzteZusammenfassung(datei) : '';
const titel = `${name} · ${aufgabe || basename(cwd) || '?'}`;

process.stdout.write(
  `${JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      sessionTitle: titel,
    },
  })}\n`,
);
