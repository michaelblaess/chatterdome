// Welcher Text einer Nutzerzeile als "aktuelle Aufgabe" taugt.
//
// ANLASS (14.08.2026): In der Tabelle stand bei drei von fuenf Agenten nur
// "[Image: source: C:\tmp\Gree...". Die Spalte war damit wertlos, obwohl die
// Prompts sehr wohl Text enthielten.
//
// Der Grund: Bild-Platzhalter sind im Transkript SELBST text-Bloecke. Ein
// content-Array sieht so aus:
//
//   [ { type: 'text', text: '[Image: source: C:\\tmp\\...png]' },
//     { type: 'text', text: 'chatterdome sieht gut aus unter Linux' } ]
//
// Wer den ersten text-Block nimmt, bekommt also den Dateipfad statt der
// Aufgabe. Hier wird stattdessen der erste Block genommen, von dem nach dem
// Entfernen der Platzhalter noch etwas uebrig bleibt.

/** Platzhalter, die Claude Code fuer Anhaenge einsetzt: [Image #1], [Image: source: ...]. */
const BILD_PLATZHALTER = /\[Image[^\]]*\]/g;

/**
 * Zieht die Aufgabe aus dem content einer Nutzerzeile.
 *
 * @param {string|Array<{type?: string, text?: string}>|null|undefined} inhalt
 * Das Feld message.content aus dem Transkript. String oder Block-Array.
 * @returns {string}
 * Der erste brauchbare Text, auf eine Zeile normalisiert. "[Bild]", wenn es
 * ausschliesslich Anhaenge gab - das ist kurz und sagt trotzdem, was anlag.
 * Leerer String, wenn gar nichts Verwertbares dabei war.
 */
export function aufgabeAusInhalt(inhalt) {
  let bloecke = [];
  if (typeof inhalt === 'string') {
    bloecke = [inhalt];
  } else if (Array.isArray(inhalt)) {
    bloecke = inhalt
      .filter((x) => x && x.type === 'text' && typeof x.text === 'string')
      .map((x) => x.text);
  }

  let hatteBild = false;
  for (const roh of bloecke) {
    const ohneBild = roh.replace(BILD_PLATZHALTER, ' ');
    if (ohneBild !== roh) hatteBild = true;
    const text = ohneBild.replace(/\s+/g, ' ').trim();
    if (text) return text;
  }
  return hatteBild ? '[Bild]' : '';
}

/**
 * Zieht die Aufgabe aus einem ganzen Transkript-Eintrag.
 *
 * Die Zusammenfassung nach einem /compact steht im Transkript als Nutzerzeile,
 * hat aber niemand geschrieben. Als Aufgabe stand danach bei fast jeder Sitzung
 * "This session is being continued..." (Michael, 01.11.2026). Mit diesem Zweig
 * zieht die Suche weiter zum letzten echten Auftrag. Erkannt am Feld
 * isCompactSummary, nicht am Wortlaut: den kann jede Version aendern.
 *
 * @param {{isCompactSummary?: boolean, message?: {content?: unknown}}} eintrag
 * Eine Zeile des Transkripts.
 * @returns {string} Wie aufgabeAusInhalt, leer bei einer Zusammenfassung.
 */
export function aufgabeAusEintrag(eintrag) {
  if (eintrag.isCompactSummary) return '';
  return aufgabeAusInhalt(eintrag.message?.content);
}
