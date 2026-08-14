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
const UPDATE = join(HIER, '..', 'skills', 'operator', 'update.mjs');
const NEUSTART = join(HIER, '..', 'skills', 'operator', 'neustart.mjs');
const BUS = join(HIER, '..', 'skills', 'claude-bus', 'bus.mjs');
const KOSTEN = join(HIER, '..', 'skills', 'claude-bus', 'kosten.mjs');

// Welcher Unterbefehl gehoert wem. Ueberschneidungen gibt es keine.
//
// Fuehrend sind die englischen Namen. Die deutschen stehen weiter darunter und
// werden bewusst NICHT entfernt: "uebernehmen" ruft ein anderer Rechner ueber
// ssh auf, und dessen Stand kann aelter sein als der hiesige.
const ZIELE = {
  status: OPERATOR, watch: OPERATOR, stop: OPERATOR, names: OPERATOR,
  motif: OPERATOR, 'reset-names': OPERATOR, 'become-operator': OPERATOR,
  motiv: OPERATOR, motive: OPERATOR, 'werde-operator': OPERATOR,
  start: STARTE, starte: STARTE,
  shot: SHOT, bild: SHOT,
  update: UPDATE,
  restart: NEUSTART, neustart: NEUSTART,
  send: BUS, read: BUS, ack: BUS, doctor: BUS, pending: BUS,
  open: BUS, tasks: BUS, task: BUS, history: BUS, receive: BUS,
  log: BUS, bestand: BUS, config: BUS, einstellungen: BUS,
  offen: BUS, auftraege: BUS, auftrag: BUS, verlauf: BUS, uebernehmen: BUS,
  cost: KOSTEN, kosten: KOSTEN,
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
    sanctuary motif [schluessel]   Namensmotive anzeigen oder umschalten

  Instanzen
    sanctuary start [Name]         neue Instanz mit Namen im Tab-Titel
    sanctuary stop <Name> [--force]  Instanz beenden (--force ohne Rueckfrage)
    sanctuary restart <Name>       beenden und mit --resume neu oeffnen
    sanctuary restart --session <id> [--host RECHNER]
                                   dasselbe fuer einen anderen Rechner
    sanctuary restart --setup      Windows: Aufgabe fuer den ssh-Zugriff anlegen
    sanctuary become-operator      diese Sitzung uebernimmt den Operator-Namen

  Bildschirm
    sanctuary shot [RECHNER]       Bildschirmfoto, lokal oder ueber das Tailnet
    sanctuary shot --setup         Windows: Aufgabe fuer den ssh-Zugriff anlegen

  Wartung
    sanctuary update [RECHNER] [--method claude|npm|winget|choco|brew]
                                   Claude Code aktualisieren
    sanctuary update --check       nur die installierte Version melden

  Auftraege
    sanctuary send <Name|all> "Text" [--topic t] [--expect-receipt]
                                   [--host RECHNER] [--from Name] [--rolle]
                                   ohne --rolle an die Sitzung, die den Namen
                                   GERADE traegt - siehe Skill claude-bus
    sanctuary tasks [--all]        Warteschlange (mit --json maschinenlesbar)
    sanctuary history <Name>       Auftraege und Quittungen mit einem Agenten
    sanctuary read [--all]         neue Nachrichten holen
    sanctuary ack <id> <Code> ["Notiz"]
    sanctuary open                 Stand der eigenen Auftraege
    sanctuary log [--limit N]      gesamter Bestand ohne Namensfilter
    sanctuary config [name wert]   Einstellungen, z.B. verfall_stunden
    sanctuary doctor               Bus pruefen
    sanctuary cost                 was die Zustellung gekostet hat

  Ohne Unterbefehl: status

  Die frueheren deutschen Namen gelten weiter: auftraege, verlauf, offen,
  kosten, motiv, werde-operator, uebernehmen - ebenso die Flags --alle,
  --erwartet-quittung, --von und --einrichten.
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
  const eigenstaendig = [STARTE, KOSTEN, SHOT, UPDATE, NEUSTART];
  const rest = eigenstaendig.includes(ziel) ? argv.slice(1) : argv;
  process.argv = [process.argv[0], ziel, ...rest];
  await import(pathToFileURL(ziel).href);
} else {
  console.error(`  Unbekannter Befehl: ${befehl}`);
  hilfe();
  process.exitCode = 1;
}
