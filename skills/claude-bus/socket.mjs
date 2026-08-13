// Sofortzustellung in eine laufende Claude-Sitzung ueber ihren Inbox-Socket.
//
// ANLASS: Bis hierher war die Zustellung eine Bringschuld des Empfaengers - der
// Stop-Hook sah nach, ob etwas anliegt. Eine wartende Instanz erfuhr von einem
// Auftrag also erst, wenn sie das naechste Mal von sich aus zum Halten kam.
//
// Seit Claude Code 2.1.224 bindet jede Sitzung auf macOS und Linux einen
// Unix-Socket, in den von aussen geschrieben werden darf. Damit wird aus der
// Bringschuld ein echter Push: der Auftrag landet sofort in der Sitzung, auch
// wenn sie gerade nur wartet.
//
// AUF WINDOWS GIBT ES DAS NICHT. Anthropic bietet das Feature auf nativem
// Windows nicht an (Stand 09.08.2026), dort bleibt es beim Stop-Hook. Dieses
// Modul meldet das sauber zurueck, statt es zu verschleiern.
//
// PROTOKOLL (am 09.08.2026 auf senza ermittelt): zeilenweises JSON auf den
// Socket, eine Nachricht je Zeile. Die Form steht nicht in der Doku, wohl aber
// in der Info-Zeile, die Claude Code beim Binden selbst ausgibt:
//
//   {"type":"user","message":{"role":"user","content":"hallo"}}
//
// WICHTIG - die Empfaengersitzung muss "crossSessionInbound": "accept" haben.
// Eine Einspeisung von aussen teilt keinen Berechtigungsmodus mit, und eine
// Sitzung im Bypass-Modus haelt so eine Nachricht dann zur Freigabe zurueck.
// Sie kommt also an, aber der Anwender muss sie erst bestaetigen. Siehe
// starte.mjs, das den Wert beim Start mitgibt.

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { connect } from 'node:net';

/** Wie lange ein Zustellversuch hoechstens dauern darf, in Millisekunden. */
const FRIST = 3000;

/**
 * Kann dieser Rechner ueberhaupt ueber Sockets zustellen?
 *
 * Reine Plattformfrage, unabhaengig davon, ob gerade eine Sitzung laeuft.
 *
 * @returns {boolean}
 * true auf macOS und Linux, false auf nativem Windows.
 */
export function sockelFaehig() {
  return process.platform !== 'win32';
}

const pfadTabelle = (datenDir) => join(datenDir, 'sockets.json');

/**
 * Liest die Zuordnung Session-ID zu Socket-Pfad.
 *
 * Bewusst eine eigene Datei neben namen.json und nicht ein weiteres Feld darin:
 * der Socket ist fluechtiger Zustand, der mit der Sitzung stirbt, waehrend
 * namen.json die Pacht fuehrt. Ausserdem lesen Operator, Statuszeile und Hooks
 * namen.json - ein Formatwechsel dort traefe alle drei.
 *
 * @param {string} datenDir
 * Datenverzeichnis des Rechners.
 * @returns {Record<string,string>}
 * Zuordnung Session-ID zu Socket-Pfad. Leer, wenn die Datei fehlt oder kaputt
 * ist - ein unlesbarer Socketstand darf den Bus nie anhalten, er faellt dann
 * auf den Stop-Hook zurueck.
 */
export function ladeSockets(datenDir) {
  const datei = pfadTabelle(datenDir);
  if (!existsSync(datei)) return {};
  try {
    const d = JSON.parse(readFileSync(datei, 'utf8'));
    return d && typeof d === 'object' && !Array.isArray(d) ? d : {};
  } catch {
    return {};
  }
}

/**
 * Haelt den Socket einer Sitzung fest.
 *
 * Wird vom SessionStart-Hook aufgerufen. Claude Code exportiert den Pfad als
 * CLAUDE_CODE_MESSAGING_SOCKET, und zwar bevor irgendein Hook laeuft.
 *
 * @param {string} datenDir
 * Datenverzeichnis des Rechners.
 * @param {string} sessionId
 * Sitzung, zu der der Socket gehoert.
 * @param {string} pfad
 * Socket-Pfad aus der Umgebung.
 * @returns {boolean}
 * true, wenn geschrieben wurde.
 */
export function merkeSocket(datenDir, sessionId, pfad) {
  if (!sessionId || !pfad) return false;
  const tabelle = ladeSockets(datenDir);
  if (tabelle[sessionId] === pfad) return true;
  tabelle[sessionId] = pfad;
  try {
    writeFileSync(pfadTabelle(datenDir), `${JSON.stringify(tabelle, null, 1)}\n`, 'utf8');
    return true;
  } catch {
    return false;
  }
}

/**
 * Entfernt Sitzungen, die es nicht mehr gibt.
 *
 * Ohne das waechst die Tabelle unbegrenzt, und schlimmer: ein Socket-Pfad wird
 * nach der PID benannt, und PIDs werden wiederverwendet. Ein alter Eintrag
 * koennte also irgendwann auf einen fremden Prozess zeigen.
 *
 * @param {string} datenDir
 * Datenverzeichnis des Rechners.
 * @param {Set<string>|string[]} lebende
 * Session-IDs, die noch laufen.
 * @returns {number}
 * Anzahl der entfernten Eintraege.
 */
export function raeumeSockets(datenDir, lebende) {
  const aktiv = lebende instanceof Set ? lebende : new Set(lebende);
  // Eine leere Liste bedeutet NICHT "nichts laeuft" - sie kann auch aus einem
  // Fehler stammen. Wer daraus loescht, nimmt allen Sitzungen ihren Socket.
  // Dieselbe Vorsicht wie beim Namensaufraeumen in whoami.mjs.
  if (aktiv.size === 0) return 0;

  const tabelle = ladeSockets(datenDir);
  const vorher = Object.keys(tabelle).length;
  for (const sid of Object.keys(tabelle)) {
    if (!aktiv.has(sid)) delete tabelle[sid];
  }
  const entfernt = vorher - Object.keys(tabelle).length;
  if (entfernt > 0) {
    try {
      writeFileSync(pfadTabelle(datenDir), `${JSON.stringify(tabelle, null, 1)}\n`, 'utf8');
    } catch {
      return 0;
    }
  }
  return entfernt;
}

/**
 * Baut die Nutzlast fuer den Socket.
 *
 * Ausgelagert, damit der Test die Form pruefen kann, ohne einen Socket zu
 * brauchen. Der abschliessende Zeilenumbruch ist Teil des Protokolls - der
 * Empfaenger trennt an \n.
 *
 * @param {string} text
 * Was die Sitzung lesen soll.
 * @returns {string}
 * Eine Zeile JSON samt Umbruch.
 */
export function nutzlast(text) {
  return `${JSON.stringify({ type: 'user', message: { role: 'user', content: text } })}\n`;
}

/**
 * Schreibt einen Text in den Socket einer laufenden Sitzung.
 *
 * Schlaegt bewusst LEISE fehl und meldet den Grund als Rueckgabewert, statt zu
 * werfen: der Aufrufer hat den Auftrag zu diesem Zeitpunkt schon in der
 * Datenbank, die Sofortzustellung ist nur die Abkuerzung. Misslingt sie, holt
 * der Stop-Hook den Auftrag wie bisher ab - es geht nichts verloren.
 *
 * @param {string} pfad
 * Socket-Pfad der Zielsitzung.
 * @param {string} text
 * Nachrichtentext.
 * @returns {Promise<string>}
 * Leerer String bei Erfolg, sonst der Grund.
 */
export function schreibeInSocket(pfad, text) {
  return new Promise((fertig) => {
    if (!sockelFaehig()) return fertig('auf Windows gibt es keinen Inbox-Socket');
    if (!pfad) return fertig('kein Socket bekannt');

    let erledigt = false;
    const ende = (grund) => {
      if (erledigt) return;
      erledigt = true;
      try { verbindung.destroy(); } catch { /* schon zu */ }
      fertig(grund);
    };

    const verbindung = connect(pfad, () => {
      verbindung.write(nutzlast(text), (fehler) => {
        // Erst nach dem Schreiben schliessen. Ein sofortiges destroy() nach
        // write() kann die Nutzlast abschneiden, bevor sie den Empfaenger
        // erreicht - write() ist gepuffert.
        if (fehler) return ende(`Schreiben fehlgeschlagen: ${fehler.message}`);
        verbindung.end();
        ende('');
      });
    });

    // ENOENT heisst: die Sitzung ist weg und hat ihren Socket abgeraeumt. Das
    // ist kein Fehler, sondern der Normalfall fuer einen veralteten Eintrag.
    verbindung.on('error', (fehler) => ende(
      fehler.code === 'ENOENT' ? 'Sitzung läuft nicht mehr' : fehler.message,
    ));
    verbindung.setTimeout(FRIST, () => ende('Zeitüberschreitung'));
  });
}

/**
 * Stellt einem Empfaenger sofort zu, sofern das hier geht.
 *
 * Die eine Stelle, an der alle Bedingungen zusammenkommen - Plattform,
 * Einstellung, bekannte Sitzung, erreichbarer Socket. Der Aufrufer bekommt ein
 * Ergebnis, das er dem Anwender direkt zeigen kann.
 *
 * @param {object} lage
 * @param {string} lage.datenDir   Datenverzeichnis des Rechners.
 * @param {string} lage.sessionId  Zielsitzung, oder leer wenn unbekannt.
 * @param {string} lage.text       Nachrichtentext.
 * @param {string} lage.modus      'auto', 'socket' oder 'stop-hook'.
 * @returns {Promise<{zugestellt: boolean, grund: string}>}
 * grund ist leer, wenn zugestellt wurde, sonst die Erklaerung.
 */
export async function sofortZustellen({ datenDir, sessionId, text, modus }) {
  if (modus === 'stop-hook') return { zugestellt: false, grund: 'per Einstellung abgeschaltet' };
  if (!sockelFaehig()) return { zugestellt: false, grund: 'Windows kennt den Inbox-Socket nicht' };
  if (!sessionId) return { zugestellt: false, grund: 'Empfänger ist keiner Sitzung zugeordnet' };

  const pfad = ladeSockets(datenDir)[sessionId];
  if (!pfad) return { zugestellt: false, grund: 'für diese Sitzung ist kein Socket hinterlegt' };

  const fehler = await schreibeInSocket(pfad, text);
  return { zugestellt: !fehler, grund: fehler };
}
