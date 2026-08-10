// Die Namensvergabe - eine Quelle fuer Hook (whoami.mjs) und Starter (starte.mjs).
//
// Vorgeschichte: die Vergabe lag doppelt vor. whoami.mjs kannte das Aufraeumen
// beendeter Sitzungen und das Ausweichen auf ein anderes Motiv, starte.mjs
// hatte nur "erster freier Name, sonst durchnummerieren". Am 10.08.2026 stand
// deshalb ein Fenster als "Operator-22" da, obwohl von 19 Comicmotiv-Namen nur
// sechs an laufenden Instanzen hingen - die restlichen Eintraege in namen.json
// waren Karteileichen beendeter Sitzungen.
//
// Kern des Problems: "belegt" wurde aus der TABELLE gelesen, nicht aus den
// tatsaechlich laufenden Instanzen. Die Tabelle waechst mit jedem Fenster,
// aufgeraeumt wurde erst, wenn gar nichts mehr ging.
//
// Deshalb hier: aufraeumen zuerst, danach waehlen. Die Reihenfolge der
// Kandidaten haelt trotzdem daran fest, zuerst NIE benutzte Namen zu nehmen -
// siehe waehleNamen().

import { ladePool, alleNamen } from './pool.mjs';
import { ladeInstanzen } from './instanzen.mjs';

/** Erlaubte Form eines Namens. Er landet spaeter in JSON und in einer Kommandozeile. */
const NAME_ERLAUBT = /^[A-Za-z0-9-]+$/;

/**
 * Entfernt Eintraege beendeter Sitzungen aus der Tabelle.
 *
 * Die Tabelle wird dabei DIREKT veraendert. Aufrufer, die sie nicht schreiben
 * wollen (der Starter), arbeiten einfach auf ihrer eigenen Kopie aus der Datei.
 *
 * Eine leere Instanzliste bedeutet NICHT, dass nichts laeuft - sie kann auch
 * aus einem Fehler oder einem Timeout stammen. Wer daraus loescht, nimmt allen
 * laufenden Instanzen ihren Namen. Also lieber gar nicht aufraeumen.
 *
 * @param tabelle
 * Zuordnung Session-ID zu Name.
 * @param eigeneSession
 * Die eigene Session-ID, die nie entfernt werden darf. Beim Starter gibt es
 * noch keine, dort null uebergeben.
 * @param laufende
 * Die laufenden Instanzen. Nur zum Testen von aussen zu setzen - im Betrieb
 * fragt die Funktion selbst nach.
 * @returns
 * Paare aus Session-ID und Name, deren Pacht damit endet. Ihre offenen
 * Auftraege muessen mitgehen, sonst erbt sie der naechste Traeger des Namens.
 */
export function raeumeAuf(tabelle, eigeneSession, laufende = null) {
  const freigegeben = [];
  if (null === laufende) {
    laufende = ladeInstanzen({ timeout: 5000 });
  }
  if (0 === laufende.length) {
    return freigegeben;
  }

  const aktiv = new Set(laufende.map((i) => i.sessionId));
  for (const sid of Object.keys(tabelle)) {
    if (sid !== eigeneSession && !aktiv.has(sid)) {
      freigegeben.push([sid, tabelle[sid]]);
      delete tabelle[sid];
    }
  }
  return freigegeben;
}

/**
 * Sucht den naechsten Namen in vier Stufen.
 *
 * 1. Ein Name des aktiven Motivs, der noch NIE vergeben war.
 * 2. Ein Name des aktiven Motivs, dessen Sitzung beendet ist.
 * 3. Ein nie vergebener Name aus einem anderen Motiv - immer noch besser als
 *    eine Nummer.
 * 4. Ein freigeraeumter Name aus einem anderen Motiv.
 *
 * Warum Stufe 1 vor Stufe 2: zwischen dem Start einer Instanz und ihrem
 * Auftauchen in "claude agents --json" liegt ein kurzer Moment. Ein Fenster,
 * das genau dann startet, sieht das andere als beendet an. Solange noch nie
 * benutzte Namen da sind, wird dieser Zweifelsfall gar nicht erst angefasst.
 *
 * Bleibt alles erfolglos, laufen tatsaechlich mehr Instanzen als der gesamte
 * Namensbestand hergibt. Dann wird durchnummeriert.
 *
 * @param tabelle
 * Die bereits aufgeraeumte Tabelle.
 * @param rohBelegt
 * Alle Namen, die VOR dem Aufraeumen in der Tabelle standen.
 * @returns
 * Der gewaehlte Name.
 */
export function waehleNamen(tabelle, rohBelegt) {
  const pool = ladePool();
  const belegt = new Set(Object.values(tabelle));
  const alle = alleNamen();

  const stufen = [
    pool.filter((n) => !rohBelegt.has(n)),
    pool.filter((n) => !belegt.has(n)),
    alle.filter((n) => !rohBelegt.has(n)),
    alle.filter((n) => !belegt.has(n)),
  ];
  for (const kandidaten of stufen) {
    if (kandidaten.length > 0) {
      return kandidaten[0];
    }
  }

  return `${pool[0]}-${Object.keys(tabelle).length + 1}`;
}

/**
 * Der komplette Vorgang: aufraeumen, Vorgabe pruefen, sonst waehlen.
 *
 * @param tabelle
 * Zuordnung Session-ID zu Name. Wird beim Aufraeumen direkt veraendert.
 * @param eigeneSession
 * Eigene Session-ID oder null (Starter).
 * @param vorgabe
 * Ein bereits feststehender Name, etwa aus CLAUDE_INSTANZ_NAME. Wird nur
 * uebernommen, wenn er gueltig geformt und noch frei ist.
 * @param laufende
 * Die laufenden Instanzen. Nur zum Testen von aussen zu setzen.
 * @returns
 * { name, freigegeben } - der Name und die Sitzungen, deren Pacht endet.
 */
export function vergibNamen({ tabelle, eigeneSession = null, vorgabe = null, laufende = null }) {
  const rohBelegt = new Set(Object.values(tabelle));
  const freigegeben = raeumeAuf(tabelle, eigeneSession, laufende);
  const belegt = new Set(Object.values(tabelle));

  // Die Vorgabe wird gegen die AUFGERAEUMTE Sicht geprueft. Sonst verwirft der
  // Hook genau den Namen, den der Starter gerade recycelt hat - und im
  // Terminal-Titel staende ein anderer Name als in der Tabelle.
  if (vorgabe && NAME_ERLAUBT.test(vorgabe) && !belegt.has(vorgabe)) {
    return { name: vorgabe, freigegeben };
  }

  return { name: waehleNamen(tabelle, rohBelegt), freigegeben };
}
