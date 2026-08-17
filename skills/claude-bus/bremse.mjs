// Was nicht in den Bus darf.
//
// Zwei Sitzungen, die sich beim Empfang gegenseitig antworten, bilden eine
// Schleife - und eine Schleife zwischen zwei Agenten ist teuer, lange bevor
// sie auf dem Bildschirm auffaellt. Gemessen am Halma-Duell kostete EIN
// Leerlauf-Durchlauf im Schnitt 369.126 Tokens, weil jeder Aufweckvorgang den
// ganzen Kontext neu liest (siehe reference_agent_token_oekonomie). Zwei
// Instanzen im Ping-Pong verbrennen das im Minutentakt.
//
// Deshalb wird die Schleife STRUKTURELL gebrochen und nicht dem Urteil der
// beiden Modelle ueberlassen: gleicher Text kurz hintereinander wird
// verworfen, ein schneller Absender gedrosselt, und ein Rueckstau, den niemand
// abarbeitet, waechst nicht weiter. Aufbau und Grenzwerte nach
// shift-labs-ai/pi-peer (MIT), src/peer/policy.ts - uebernommen ist der
// Gedanke samt der dort gewaehlten Zahlen, nicht der Code.
//
// UNTERSCHIED ZUR VORLAGE: pi-peer laeuft als langlebige Erweiterung IN der
// Sitzung und haelt seinen Zaehlerstand im Speicher. bus.mjs ist ein
// kurzlebiges Kommando - ein Zaehler im Speicher waere bei jedem Aufruf leer.
// Gezaehlt wird deshalb in der Datenbank, die den Bestand ohnehin fuehrt. Das
// ist nicht nur ein Ersatz, sondern belastbarer: der Stand ueberlebt jeden
// Prozessneustart.

/** Ein Auftrag ist Text, keine Nutzlast. */
export const MAX_TEXT_BYTES = 32 * 1024;

export const GRENZEN = {
  /** Gleicher Text vom selben Absender innerhalb dieser Zeit ist eine Wiederholung. */
  dedupMs: 10_000,
  taktMs: 30_000,
  /** Auftraege je Absender und Takt, bevor gedrosselt wird. */
  proTakt: 8,
  /** Offene Auftraege beim Empfaenger, bevor nichts mehr angenommen wird. */
  maxOffen: 50,
};

/**
 * Passt der Text ueberhaupt durch?
 *
 * Die Meldung sagt dem Modell, was zu tun ist, statt nur nein: wer bloss "zu
 * gross" liest, kuerzt aufs Geratewohl und schickt es dreimal.
 *
 * @param {string} text
 * @returns {string} Leer, wenn er passt, sonst der Grund.
 */
export function pruefeGroesse(text) {
  const bytes = Buffer.byteLength(String(text ?? ''), 'utf8');
  if (bytes <= MAX_TEXT_BYTES) return '';
  return `Der Text ist ${bytes} Bytes gross, erlaubt sind ${MAX_TEXT_BYTES}. `
    + 'Schicke eine Zusammenfassung, oder lege die Einzelheiten in eine Datei und nenne den Pfad.';
}

/**
 * Darf dieser Auftrag abgelegt werden?
 *
 * Bewusst eine reine Funktion: alle Zahlen kommen von aussen herein, damit die
 * Entscheidung ohne Datenbank und ohne Uhr pruefbar ist.
 *
 * @param {object} lage
 * @param {string} lage.text Der Auftragstext.
 * @param {string} [lage.letzterText] Letzter Text desselben Absenders an dasselbe Ziel.
 * @param {number} [lage.letzteZeitMs] Wann der geschickt wurde, in Millisekunden.
 * @param {number} [lage.imTakt] Auftraege dieses Absenders im laufenden Takt, ohne den neuen.
 * @param {number} [lage.offen] Offene Auftraege beim Empfaenger.
 * @param {number} lage.jetztMs Jetzt, in Millisekunden.
 * @param {object} [lage.grenzen] Abweichende Grenzwerte, sonst GRENZEN.
 * @returns {{ok: boolean, grund: string, art: string}}
 * `art` ist maschinenlesbar: '', 'gross', 'wiederholung', 'takt' oder 'rueckstau'.
 */
export function pruefeEingang(lage) {
  const g = { ...GRENZEN, ...(lage.grenzen || {}) };
  const nein = (art, grund) => ({ ok: false, art, grund });

  const zuGross = pruefeGroesse(lage.text);
  if (zuGross) return nein('gross', zuGross);

  // Die Wiederholung zuerst: sie ist der haeufigste Anfang einer Schleife und
  // die billigste Erkennung.
  if (
    lage.letzterText !== undefined
    && lage.letzterText === lage.text
    && lage.jetztMs - Number(lage.letzteZeitMs || 0) < g.dedupMs
  ) {
    return nein(
      'wiederholung',
      `Wortgleich zum vorigen Auftrag an dasselbe Ziel, keine ${Math.round(g.dedupMs / 1000)} s her.`,
    );
  }

  // Der Takt zaehlt den NEUEN Auftrag mit - sonst waere die Grenze um eins
  // durchlaessiger als sie behauptet.
  if (Number(lage.imTakt || 0) + 1 > g.proTakt) {
    return nein(
      'takt',
      `Mehr als ${g.proTakt} Auftraege in ${Math.round(g.taktMs / 1000)} s an dasselbe Ziel.`,
    );
  }

  if (Number(lage.offen || 0) >= g.maxOffen) {
    return nein(
      'rueckstau',
      `Beim Empfaenger liegen schon ${lage.offen} unerledigte Auftraege.`,
    );
  }

  return { ok: true, grund: '', art: '' };
}

/**
 * Baut die Lage aus einer Liste bereits abgelegter Auftraege.
 *
 * Erwartet werden Zeilen mit `ts` (ISO) und `text`, absteigend oder aufsteigend
 * - sortiert wird hier. Wer sie liefert, entscheidet ueber die Auswahl: in
 * bus.mjs sind es die Auftraege desselben Absenders an dasselbe Ziel.
 *
 * @param {Array<{ts: string, text: string}>} vorher
 * @param {number} jetztMs
 * @param {object} [grenzen]
 */
export function lageAus(vorher, jetztMs, grenzen = GRENZEN) {
  const mitZeit = (vorher || [])
    .map((z) => ({ text: z.text, ms: Date.parse(z.ts) }))
    .filter((z) => Number.isFinite(z.ms))
    .sort((a, b) => a.ms - b.ms);
  const letzter = mitZeit[mitZeit.length - 1];
  const seit = jetztMs - grenzen.taktMs;
  return {
    letzterText: letzter ? letzter.text : undefined,
    letzteZeitMs: letzter ? letzter.ms : 0,
    imTakt: mitZeit.filter((z) => z.ms > seit).length,
  };
}
