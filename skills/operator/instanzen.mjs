// Die Liste der laufenden Claude-Code-Instanzen. Eine Quelle fuer Operator und
// SessionStart-Hook.
//
// Bewusst als eigenes Modul, nach dem Muster von pool.mjs: whoami.mjs braucht
// die Liste nur im Erschoepfungsfall, koennte sie aber nicht aus operator.mjs
// holen, ohne dessen CLI-Teil mitzuladen.

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const SESSIONS = join(homedir(), '.claude', 'sessions');

/**
 * Liest die Instanzliste direkt aus ~/.claude/sessions/<pid>.json.
 *
 * Claude Code legt dort je laufender Sitzung eine Datei ab, deren Inhalt die
 * Ausgabe von "claude agents --json" vollstaendig enthaelt (pid, sessionId,
 * cwd, startedAt, kind, name, status) und darueber hinaus noch version und
 * procStart. Der CLI-Aufruf kostete gemessen 758 ms, diese Lesung 3 ms - der
 * gesamte "operator status" faellt damit von 842 ms auf 63 ms.
 *
 * Der Preis ist eine Annahme ueber ein Verzeichnis, das nicht dokumentiert
 * ist. Deshalb: bei jedem Zweifel null zurueckgeben, damit der Aufrufer den
 * CLI-Weg nimmt, statt eine falsche Liste zu liefern.
 *
 * @returns {Array|null}
 * Liste der lebenden Instanzen, oder null wenn das Verzeichnis nicht taugt.
 */
function ausSessionsVerzeichnis() {
  let dateien;
  try {
    dateien = readdirSync(SESSIONS).filter((f) => f.endsWith('.json'));
  } catch {
    // Verzeichnis fehlt - andere Claude-Version oder anderer Ablageort.
    return null;
  }

  const liste = [];
  for (const datei of dateien) {
    let e;
    try {
      e = JSON.parse(readFileSync(join(SESSIONS, datei), 'utf8'));
    } catch {
      continue; // halb geschriebene oder kaputte Datei ueberspringen
    }
    if (!e || !e.pid || !e.sessionId) continue;

    // Die Datei wird bei Statuswechseln geschrieben, nicht per Herzschlag -
    // ein Eintrag kann also einen laengst beendeten Prozess beschreiben.
    // Signal 0 stellt nichts zu, es prueft nur die Existenz. EPERM bedeutet
    // "lebt, gehoert aber jemand anderem" und zaehlt deshalb als lebend.
    try {
      process.kill(e.pid, 0);
    } catch (err) {
      if (err.code !== 'EPERM') continue;
    }

    liste.push(e);
  }
  return liste;
}

/**
 * Haelt je Sitzungskennung nur den juengsten Eintrag.
 *
 * Es gibt eine Datei je PID, aber der Name haengt an der SITZUNG - zwei
 * Eintraege mit derselben Kennung erscheinen also zwangslaeufig unter einem
 * Namen, und der ist als Adresse dann nicht mehr eindeutig. Belegt am
 * 16.08.2026 auf senza: nach einem Neustart, der den alten Prozess nicht
 * beendet hatte, lagen PID 1319787 und 3585570 auf Sitzung 2501336f vor.
 *
 * Der juengste gewinnt, weil ein Resume den fortgesetzten Prozess ist - der
 * aeltere Eintrag ist entweder eine Leiche mit neu vergebener PID oder der
 * Vorgaenger, der gerade aussteigt.
 *
 * Das ist ein Netz, kein Fix. Die Ursache gehoert in neustart.mjs behoben,
 * hier wird nur verhindert, dass sie sich in Namensvergabe und Oberflaeche
 * fortpflanzt.
 */
export function jeSitzungEinmal(liste) {
  const beste = new Map();
  for (const e of liste) {
    const da = beste.get(e.sessionId);
    if (!da || Number(e.startedAt || 0) > Number(da.startedAt || 0)) beste.set(e.sessionId, e);
  }
  return [...beste.values()];
}

/** Der bisherige Weg ueber das CLI. Bleibt als Rueckfall. */
function ueberCli({ timeout }) {
  // CLAUDE_CODE_EXECPATH zeigt auf die echte Binaerdatei und ist der
  // zuverlaessigste Weg. Unter Windows findet execFileSync ein blosses
  // "claude" nicht, weil das dort ein Wrapper ist - deshalb der Fallback
  // ueber die Shell.
  const versuche = [];
  if (process.env.CLAUDE_CODE_EXECPATH) {
    versuche.push({ cmd: process.env.CLAUDE_CODE_EXECPATH, shell: false });
  }
  versuche.push({ cmd: 'claude', shell: true });

  for (const v of versuche) {
    try {
      const roh = execFileSync(v.cmd, ['agents', '--json'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
        timeout, shell: v.shell,
      });
      const liste = JSON.parse(roh);
      if (Array.isArray(liste)) return liste;
    } catch { /* naechsten Weg probieren */ }
  }
  return [];
}

/**
 * Liefert die laufenden Instanzen als Array. Bei jedem Problem ein leeres
 * Array - Aufrufer muessen den Unterschied zwischen "keine laufen" und
 * "Abfrage fehlgeschlagen" selbst behandeln, siehe Hinweis unten.
 *
 * WICHTIG: Ein leeres Ergebnis ist KEIN Beweis, dass nichts laeuft. Wer daraus
 * Eintraege loescht, loescht im Fehlerfall alles. Vorher auf Laenge pruefen.
 *
 * @param {number} timeout
 * Wartezeit in Millisekunden fuer den CLI-Rueckfall. Der Hook nimmt einen
 * kleineren Wert als das CLI, weil er den Sitzungsstart nicht aufhalten darf.
 * @param {boolean} jeProzess
 * Jeden Prozess einzeln liefern, auch wenn zwei auf derselben Sitzung liegen.
 * Nur fuer das Aufraeumen gedacht - wer beenden will, muss alle sehen. Fuer
 * jede Anzeige und jede Namensvergabe gilt die Vorgabe, siehe jeSitzungEinmal.
 */
export function ladeInstanzen({ timeout = 20000, jeProzess = false } = {}) {
  const roh = process.env.OPERATOR_INSTANZEN_VIA_CLI
    ? ueberCli({ timeout })
    : (ausSessionsVerzeichnis() ?? ueberCli({ timeout }));
  return jeProzess ? roh : jeSitzungEinmal(roh);
}
