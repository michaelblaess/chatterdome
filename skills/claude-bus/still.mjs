// Schluckt die ExperimentalWarning von node:sqlite - und nur die.
//
// Node 22 meldet beim Laden von node:sqlite "SQLite is an experimental feature
// and might change at any time" auf stderr, Node 24 nicht mehr. Das ist keine
// Kosmetik: bus.mjs laeuft im Stop-Hook, und dessen Ausgabe landet im Kontext
// jeder Instanz. Eine Warnzeile je Zustellung waere reines Rauschen.
//
// WICHTIG: Dieses Modul muss VOR node:sqlite importiert werden. ESM fuehrt
// Importe in Reihenfolge aus, der Listener steht dadurch rechtzeitig. Ein
// spaeter registrierter Listener kaeme zu spaet, weil die Warnung schon beim
// Laden des Moduls faellt.
//
// Bewusst NICHT NODE_NO_WARNINGS: das wuerde alle Warnungen unterdruecken,
// auch die, die auf echte Fehler hinweisen. Hier faellt genau eine weg, jede
// andere wird weitergereicht.

// Ein eigener Listener ALLEIN reicht nicht: Node haengt seinen eingebauten
// Handler nicht ab, sobald man einen weiteren registriert - die Warnung kam
// dann doppelt gemoppelt trotzdem heraus (auf senza mit Node 22 nachgestellt).
// Erst removeAllListeners entfernt den Standardausgeber.
process.removeAllListeners('warning');
process.on('warning', (w) => {
  if (w.name === 'ExperimentalWarning' && /SQLite/i.test(w.message)) return;
  console.error(`${w.name}: ${w.message}`);
});
