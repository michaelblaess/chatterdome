#!/usr/bin/env node
// sanctuary - ein Einstiegspunkt fuer Operator und Bus.
//
// Statt zweier langer Pfade (node ~/.claude/skills/operator/operator.mjs ...)
// genuegt "sanctuary status" oder "sanctuary send Lino ...". Der Aufruf wird
// an das zustaendige Skript weitergereicht.
//
// BEWUSST OHNE SUBPROZESS: process.argv wird exakt so gesetzt, wie es beim
// Direktaufruf aussaehe, dann wird das Zielmodul importiert. Das spart einen
// Prozessstart (unter Windows 36 ms) und ist nicht fragil - bus.mjs prueft
// selbst, ob es direkt aufgerufen wurde, und dieser Vergleich geht mit dem
// umgebogenen argv[1] korrekt auf.

import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const HIER = dirname(fileURLToPath(import.meta.url));
const OPERATOR = join(HIER, '..', 'skills', 'operator', 'operator.mjs');
const STARTE = join(HIER, '..', 'skills', 'operator', 'starte.mjs');
const SHOT = join(HIER, '..', 'skills', 'operator', 'shot.mjs');
const BUS = join(HIER, '..', 'skills', 'claude-bus', 'bus.mjs');
const KOSTEN = join(HIER, '..', 'skills', 'claude-bus', 'kosten.mjs');

// Welcher Unterbefehl gehoert wem. Ueberschneidungen gibt es keine.
const ZIELE = {
  status: OPERATOR, watch: OPERATOR, stop: OPERATOR, names: OPERATOR,
  motiv: OPERATOR, motive: OPERATOR, 'reset-names': OPERATOR, 'werde-operator': OPERATOR,
  start: STARTE, starte: STARTE,
  shot: SHOT, bild: SHOT,
  send: BUS, read: BUS, ack: BUS, offen: BUS, doctor: BUS, pending: BUS,
  auftraege: BUS, auftrag: BUS, verlauf: BUS, uebernehmen: BUS,
  kosten: KOSTEN,
};

function hilfe() {
  console.log(`
  sanctuary - Zentrale fuer laufende Claude-Code-Instanzen

  Uebersicht
    sanctuary status [Name]        Tabelle oder Detailansicht
    sanctuary status --mesh        zusaetzlich die anderen Rechner
    sanctuary status --json        maschinenlesbar
    sanctuary watch [Sek]          laufend neu zeichnen (mit --json als Strom)
    sanctuary names                vergebene Namen
    sanctuary motiv [schluessel]   Namensmotive anzeigen oder umschalten

  Instanzen
    sanctuary start [Name]         neue Instanz mit Namen im Tab-Titel
    sanctuary stop <Name>          Instanz beenden
    sanctuary werde-operator       diese Sitzung uebernimmt den Operator-Namen

  Bildschirm
    sanctuary shot [RECHNER]       Bildschirmfoto, lokal oder ueber das Tailnet
    sanctuary shot --einrichten    Windows: Aufgabe fuer den ssh-Zugriff anlegen

  Auftraege
    sanctuary send <Name|alle> "Text" [--topic t] [--erwartet-quittung]
                                   [--host RECHNER] [--von Name]
    sanctuary auftraege [--alle]   Warteschlange (mit --json maschinenlesbar)
    sanctuary verlauf <Name>       Auftraege und Quittungen mit einem Agenten
    sanctuary read [--alle]        neue Nachrichten holen
    sanctuary ack <id> <Code> ["Notiz"]
    sanctuary offen                Stand der eigenen Auftraege
    sanctuary doctor               Bus pruefen
    sanctuary kosten               was die Zustellung gekostet hat

  Ohne Unterbefehl: status
`);
}

const argv = process.argv.slice(2);
const befehl = argv[0];

if (!befehl) {
  process.argv = [process.argv[0], OPERATOR, 'status'];
  await import(pathToFileURL(OPERATOR).href);
} else if (['hilfe', 'help', '--help', '-h'].includes(befehl)) {
  hilfe();
} else if (ZIELE[befehl]) {
  const ziel = ZIELE[befehl];
  // starte.mjs und kosten.mjs kennen den Unterbefehl nicht, sie sind selbst
  // schon das Kommando - deshalb faellt er dort weg.
  const rest = (ziel === STARTE || ziel === KOSTEN || ziel === SHOT) ? argv.slice(1) : argv;
  process.argv = [process.argv[0], ziel, ...rest];
  await import(pathToFileURL(ziel).href);
} else {
  console.error(`  Unbekannter Befehl: ${befehl}`);
  hilfe();
  process.exitCode = 1;
}
