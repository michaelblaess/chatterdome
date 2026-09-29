#!/usr/bin/env node
// sanctuary - der alte Name von chatterdome, als Alias.
//
// Bleibt, solange ein Rechner noch auf dem alten Stand sein kann: die
// Fernaufrufe ueber ssh (bus.mjs, operator.mjs, shot.mjs, update.mjs,
// neustart.mjs) rufen bewusst "sanctuary" auf, weil es diesen Namen auf jedem
// Rechner gibt, alt wie neu. Umbenannt am 29.09.2026.
//
// Einfach importieren: chatterdome.mjs liest process.argv selbst und reicht
// den Unterbefehl weiter, ein zweiter Prozess ist nicht noetig.

import './chatterdome.mjs';
