// Der Name ist eine Pacht, kein Gegenueber - und das Postfach gehoert dazu.
//
// ANLASS (07.08.2026, von Michael gemeldet): Chatterdome legte am 03.08. einen
// Auftrag "gib mir das aktuelle Datum" an Marga ab. Diese Marga holte ihn nie
// ab, ihre Sitzung endete, der Aufraeumschritt gab den Namen frei, und vier
// Tage spaeter bekam eine voellig andere Sitzung denselben Namen aus dem Pool -
// und arbeitete den Auftrag ab. Nachgesehen in der Datenbank: der Auftrag stand
// von 2026-08-03T12:10:02Z bis 2026-08-07T09:19:51Z auf 'submitted', und die
// erste Marga hatte nicht einmal einen Eintrag in der cursor-Tabelle.
//
// Drei Schichten haben gleichzeitig versagt, jede haette allein gereicht:
//
//   1. Die Adresse war ein gepachteter Name. Der Auftrag hielt die Sitzung des
//      ABSENDERS exakt fest, den Empfaenger dagegen nur als Spitznamen.
//   2. Auftraege alterten nicht. Kein Verfall, kein Uebergang "Empfaenger ist
//      weg".
//   3. Lesezeiger und Adresse hatten verschiedene Koernung: der Zeiger haengt
//      an der Session-ID, die Adresse am Namen. Eine frische Sitzung startet
//      bei 0 und bekommt damit die GANZE Historie ihres Namens vorgesetzt.
//
// Dieses Modul haelt die drei Gegenmittel an einer Stelle beisammen, statt sie
// ueber Hook, Operator und Bus zu verteilen. Genau diese Verteilung ist der
// Grund, warum der Namenspool schon einmal auseinandergelaufen ist.

import {
  schreibe, letzteId, cursorLesen, cursorSetzen,
  offeneAelterAls, offeneAnSession, auftraege, sitzungUmhaengen,
} from './speicher.mjs';
import { einstellung } from './einstellungen.mjs';

/**
 * Quittungscodes, die der Bus selbst erzeugt.
 *
 * Beides sind echte HTTP-Bedeutungen und keine erfundenen Nummern: 408 ist die
 * abgelaufene Frist, 410 das endgueltig verschwundene Ziel.
 */
export const VERFALLEN = 408;
export const EMPFAENGER_WEG = 410;

/**
 * Schreibt eine Quittung des Bus selbst.
 *
 * Bewusst art='quittung' und nicht eine eigene Ereignisart: so taucht der
 * Vorgang im Verlauf und in "open" beim ABSENDER auf, mitsamt Code und Notiz.
 * Eine stille Zustandsaenderung waere zwar billiger, wuerde aber genau die
 * Frage offenlassen, die der Absender dann stellt - warum ist mein Auftrag weg.
 */
function quittiereSelbst(db, a, { status, zustand, notiz }) {
  schreibe(db, {
    auftrag_id: a.auftrag_id,
    ts: new Date().toISOString(),
    art: 'quittung',
    host: a.host,
    von_host: a.host,
    von: 'bus',
    von_session: '',
    an: a.von,
    zustand,
    status,
    notiz,
  });
}

/**
 * Beginn der Pacht: der Lesezeiger einer frischen Sitzung startet am ENDE des
 * Protokolls, nicht am Anfang.
 *
 * Warum hier und nicht beim ersten Buszugriff: zwischen Sitzungsstart und
 * erstem Buszugriff kann ein Auftrag eintreffen. Wer den Zeiger erst dann
 * setzt, ueberspringt ihn. Der Sitzungsstart ist der einzige Zeitpunkt, an dem
 * "alles Bisherige geht mich nichts an" auch wirklich stimmt.
 *
 * Ein bereits vorhandener Zeiger wird NICHT angefasst - sonst verloere eine
 * fortgesetzte Sitzung (claude --resume behaelt die Session-ID) ihre
 * ungelesenen Nachrichten.
 *
 * @returns {number|null} der gesetzte Stand, oder null wenn schon einer da war.
 */
export function pachtBeginnt(db, sessionId) {
  if (!sessionId) return null;
  if (cursorLesen(db, sessionId) > 0) return null;
  const stand = letzteId(db);
  cursorSetzen(db, sessionId, stand);
  return stand;
}

/**
 * Die Pacht geht ueber: dasselbe Fenster laeuft unter neuer Session-ID weiter.
 *
 * Das ist /clear - der Prozess bleibt, die Session-ID wechselt, der Name geht
 * mit (siehe operator/fenster.mjs). Weder Beginn noch Ende passen dann:
 * pachtBeginnt setzte den Zeiger ans Ende und liesse alles fallen, was seit
 * dem letzten Lesen eintraf, pachtEndet naehme Auftraege zurueck, deren
 * Empfaenger unter demselben Namen im selben Fenster weiterarbeitet.
 *
 * Also wandert beides mit: der Lesezeiger und die offenen, an die alte Sitzung
 * gebundenen Auftraege.
 *
 * Hatte die alte Sitzung keinen Zeiger, startet die neue am Ende - dieselbe
 * Regel wie beim Beginn, sonst gaelte wieder die ganze Historie als neu.
 *
 * @returns {string[]} die IDs der umgehaengten Auftraege.
 */
export function pachtGehtUeber(db, alt, neu) {
  if (!alt || !neu || alt === neu) return [];
  if (0 === cursorLesen(db, neu)) {
    cursorSetzen(db, neu, cursorLesen(db, alt) || letzteId(db));
  }
  return sitzungUmhaengen(db, alt, neu);
}

/**
 * Ende der Pacht: offene Auftraege, die an diese Sitzung gebunden waren, werden
 * zurueckgenommen.
 *
 * Betroffen sind ausschliesslich Auftraege mit an_session - also solche, die an
 * eine PERSON gingen. Rollenauftraege (--rolle) ueberleben den Namenswechsel
 * absichtlich, sie meinen ja "wer auch immer den Namen traegt". Die faengt der
 * Verfall.
 *
 * @returns {string[]} die IDs der zurueckgenommenen Auftraege.
 */
export function pachtEndet(db, sessionId, name = '') {
  const betroffen = offeneAnSession(db, sessionId);
  for (const a of betroffen) {
    quittiereSelbst(db, a, {
      status: EMPFAENGER_WEG,
      zustand: 'cancelled',
      notiz: `Empfänger ${name || a.an || sessionId.slice(0, 8)} ist beendet, der Auftrag wurde nie angenommen`,
    });
  }
  return betroffen.map((a) => a.auftrag_id);
}

/**
 * Der Kehrbesen: alles, was zu lange offen liegt, verfaellt.
 *
 * Faengt das, was die Bindung nicht faengt - Rollenauftraege, Auftraege von
 * fremden Rechnern (dort ist der Name lokal nicht aufloesbar) und den ganzen
 * Altbestand ohne Bindung.
 *
 * @param {number} [stunden]
 * Frist in Stunden. Ohne Angabe aus den Einstellungen. 0 schaltet ab.
 * @returns {string[]} die IDs der verfallenen Auftraege.
 */
export function verfallen(db, stunden = einstellung('verfall_stunden')) {
  if (!stunden || stunden <= 0) return [];
  const grenze = new Date(Date.now() - stunden * 3600_000).toISOString();
  const betroffen = offeneAelterAls(db, grenze);
  for (const a of betroffen) {
    quittiereSelbst(db, a, {
      status: VERFALLEN,
      zustand: 'expired',
      notiz: `verfallen - lag länger als ${stunden} h offen`,
    });
  }
  return betroffen.map((a) => a.auftrag_id);
}

/**
 * Auftraege, deren Empfaengername an eine ANDERE Sitzung vergeben ist als die,
 * fuer die sie gedacht waren. Reine Diagnose fuer "doctor".
 *
 * @param {Record<string,string>} namen
 * Die Zuordnung Session-ID zu Name aus namen.json.
 */
export function fehlgeleitete(db, namen) {
  const jetzt = new Map(Object.entries(namen).map(([sid, n]) => [String(n).toLowerCase(), sid]));
  return auftraege(db, {})
    .filter((a) => a.an_session && a.an)
    .filter((a) => {
      const inhaber = jetzt.get(String(a.an).toLowerCase());
      return inhaber && inhaber !== a.an_session;
    });
}
