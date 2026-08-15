// Wer steckt hinter einer PID, und lebt er noch?
//
// Bewusst ein eigenes Modul nach dem Muster von instanzen.mjs und pool.mjs:
// neustart.mjs braucht dieselbe Pruefung wie "operator stop", koennte sie aber
// nicht aus operator.mjs holen, ohne dessen CLI-Teil mitzuladen.

import { execFileSync } from 'node:child_process';
import { platform } from 'node:os';

/**
 * Ermittelt den Namen des Programms hinter einer PID.
 *
 * Bewusst fail-closed gebaut: laesst sich der Name nicht feststellen, kommt
 * eine leere Zeichenkette zurueck und der Aufrufer bricht ab. Ein
 * verweigerter Stop ist aergerlich, ein Signal an den falschen Prozess ist
 * teuer.
 *
 * @param {number|string} pid  Prozesskennung.
 * @returns {string}  Kleingeschriebener Programmname, leer wenn unbekannt.
 */
export function prozessName(pid) {
  const nummer = Number(pid);
  if (!Number.isInteger(nummer) || nummer <= 0) return '';
  try {
    if (platform() === 'win32') {
      const aus = execFileSync('tasklist', ['/FI', `PID eq ${nummer}`, '/FO', 'CSV', '/NH'],
        { encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] });
      // Ohne Treffer meldet tasklist einen Hinweistext statt einer CSV-Zeile.
      const treffer = aus.match(/^"([^"]+)"/m);
      return treffer ? treffer[1].toLowerCase() : '';
    }
    // Die volle Kommandozeile, nicht "comm": Claude Code laeuft auf Linux als
    // Node-Programm, der blosse Prozessname waere dort "node". Im Argument
    // steht dagegen der Pfad zum claude-Skript.
    const aus = execFileSync('ps', ['-p', String(nummer), '-o', 'args='],
      { encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] });
    return aus.trim().toLowerCase();
  } catch {
    return '';
  }
}

/**
 * Gehoert diese PID zu einer Claude-Code-Sitzung?
 *
 * Die Frage vor jedem Signal. Die PID stammt aus einer Momentaufnahme; ist die
 * Instanz dazwischen ausgestiegen, kann das Betriebssystem dieselbe Nummer
 * laengst neu vergeben haben - unter Windows geschieht das schnell.
 */
export function istClaude(pid) {
  return prozessName(pid).includes('claude');
}

/**
 * Lebt der Prozess noch?
 *
 * Signal 0 stellt nichts zu, es prueft nur die Existenz. EPERM bedeutet
 * "lebt, gehoert aber jemand anderem" und zaehlt deshalb als lebend.
 */
export function laeuft(pid) {
  const nummer = Number(pid);
  if (!Number.isInteger(nummer) || nummer <= 0) return false;
  try {
    process.kill(nummer, 0);
    return true;
  } catch (fehler) {
    return fehler.code === 'EPERM';
  }
}
