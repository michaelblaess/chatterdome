// Statuszeile: zeigt den Instanznamen dauerhaft am unteren Rand.
//
// Der Name stand bisher nur im Tab-Titel, und auch das nur bei einem Start
// ueber starte.mjs (claude -n <Name>). Wer direkt "claude" tippt, sah den
// Namen nirgends - der SessionStart-Hook kann keinen Titel setzen, und Claude
// Code ueberschreibt den Tab ohnehin laufend mit dem KI-Titel.
//
// Claude Code schickt die Sitzungsdaten als JSON auf stdin und zeigt die
// Ausgabe in einer eigenen Zeile ueber den eingebauten Badges. Aufruf ueber
// "statusLine" in settings.json.
//
// Kein jq, sondern Node: jq ist nicht auf allen Rechnern vorhanden, Node
// dagegen schon - dieselbe Begruendung wie beim Bus-Hook.

import { homedir } from 'node:os';
import { ladeNamen } from './pool.mjs';

const GRAU = '\x1b[38;5;244m';
const CYAN = '\x1b[38;5;80m';
const GELB = '\x1b[38;5;221m';
const ROT = '\x1b[38;5;203m';
const R = '\x1b[0m';

function lieseStdin() {
  return new Promise((fertig) => {
    let roh = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (t) => { roh += t; });
    process.stdin.on('end', () => fertig(roh));
    // Faellt stdin aus, lieber eine karge Zeile als gar keine. unref ist
    // entscheidend: ohne das haelt der Timer den Prozess eine volle Sekunde
    // am Leben, nachdem die Zeile laengst geschrieben ist - gemessen 1154 ms
    // je Aufruf statt 150 ms, und die Zeile laeuft bei jeder Nachricht neu.
    setTimeout(() => fertig(roh), 1000).unref();
  });
}

/** Ordnerpfad kuerzen: Heimatverzeichnis als ~, sonst die letzten zwei Ebenen. */
function ordnerKurz(pfad) {
  if (!pfad) return '';
  const glatt = pfad.replace(/\\/g, '/');
  const heim = homedir().replace(/\\/g, '/');
  // Gleiche Schreibweise wie in der Operator-Tabelle, damit beide Ansichten
  // denselben Ordner gleich benennen.
  if (glatt === heim) return '~';
  if (glatt.startsWith(`${heim}/`)) {
    const rest = glatt.slice(heim.length + 1).split('/').filter(Boolean);
    return `~/${rest.slice(-2).join('/')}`;
  }
  return glatt.split('/').filter(Boolean).slice(-2).join('/');
}

function kontextFarbe(prozent) {
  if (prozent >= 90) return ROT;
  if (prozent >= 70) return GELB;
  return GRAU;
}

const roh = await lieseStdin();
let d = {};
try { d = JSON.parse(roh); } catch { /* karg weiter */ }

/**
 * Beim Sitzungsstart laeuft die Statuszeile unter Umstaenden VOR dem
 * SessionStart-Hook, der den Namen vergibt. Dann steht in namen.json noch
 * nichts, und die Zeile zeigte bis zur ersten Antwort ein Fragezeichen -
 * ausgerechnet bei einem frisch geoeffneten Fenster, wo man am ehesten wissen
 * will, wer da laeuft. Deshalb kurz nachfassen statt sofort aufzugeben.
 *
 * ABER nur, wenn es nichts anderes zu zeigen gibt. Vorher wurde bei jedem
 * Fehltreffer dreimal 100 ms gewartet, und zwar bei JEDEM Neuzeichnen - bei
 * einer Sitzung ohne Poolnamen waren das gemessen 200 von 265 ms Laufzeit,
 * also drei Viertel der Zeile. Die Statuszeile laeuft bei jeder Nachricht neu,
 * ein Rueckfallname fuer ein oder zwei Durchgaenge kostet deshalb nichts, das
 * Warten dagegen dauerhaft.
 *
 * Vergeben wird weiterhin ausschliesslich im Hook. Wuerde die Statuszeile das
 * selbst tun, schrieben zwei Prozesse gleichzeitig dieselbe Datei.
 */
async function nameFuer(sessionId, rueckfall) {
  const sofort = ladeNamen()[sessionId];
  if (sofort) return sofort;
  if (rueckfall) return null; // lieber der KI-Titel als eine Wartezeit
  // Nichts anzuzeigen: einmal kurz nachfassen. Bewusst OHNE unref, sonst
  // beendet Node sofort und gibt gar nichts aus.
  await new Promise((f) => { setTimeout(f, 60); });
  return ladeNamen()[sessionId] || null;
}

// Reihenfolge mit Absicht: der Poolname ist der stabile Bezeichner, unter dem
// Michael die Instanz anspricht. session_name waere der KI-Titel und wechselt.
const name = (await nameFuer(d.session_id, d.session_name)) || d.session_name || '?';

const teile = [`${CYAN}${name}${R}`];

const ordner = ordnerKurz(d.workspace && d.workspace.current_dir);
if (ordner) teile.push(`${GRAU}${ordner}${R}`);

const modell = d.model && d.model.display_name;
if (modell) teile.push(`${GRAU}${modell}${R}`);

const prozent = Math.floor((d.context_window && d.context_window.used_percentage) || 0);
if (prozent > 0) teile.push(`${kontextFarbe(prozent)}${prozent}% Kontext${R}`);

process.stdout.write(teile.join(`${GRAU} · ${R}`));
