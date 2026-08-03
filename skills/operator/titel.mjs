// UserPromptSubmit-Hook-Helfer: baut den Terminal-Tab-Titel "<Name> . <Ordner>".
//
// Zweck: mehrere Claude-Fenster sind schwer auseinanderzuhalten. Claude Code
// setzt den Tab-Titel sonst auf eine Aufgaben-Zusammenfassung (aiTitle) - der
// Agenten-Name fehlt darin. Dieser Hook gibt "sessionTitle" aus, was Claude als
// "customTitle" speichert. In der Titel-Prioritaet (agentName || customTitle ||
// aiTitle) schlaegt customTitle die automatische Zusammenfassung, der Name klebt
// also stabil im Tab. Belegt am Binary v2.1.x (Jse -> type:"custom-title").
//
// Der Name steht schon in namen.json (vom SessionStart-Hook whoami.mjs vergeben);
// hier wird er nur NACHGESCHLAGEN - kein Neuvergeben, kein "claude agents --json".
// So bleibt der Hook billig genug, um bei JEDEM Prompt zu laufen (ein
// Datei-Lesezugriff statt Sekunden).
//
// Ausgabe auf stdout: das Hook-JSON mit sessionTitle. Bei jedem Problem still mit
// Code 0 raus - kein Titel ist besser als ein zerbrochener Prompt-Submit.

import { readFileSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { join, basename } from 'node:path';

function rechner() {
  // COMPUTERNAME bevorzugen, damit der Pfad exakt dem entspricht, was der
  // SessionStart-Hook benutzt. hostname() kann Suffixe wie .local liefern.
  return (process.env.COMPUTERNAME || hostname().split('.')[0]).toUpperCase();
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

const titel = `${name} · ${basename(cwd) || '?'}`;

process.stdout.write(
  `${JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      sessionTitle: titel,
    },
  })}\n`,
);
