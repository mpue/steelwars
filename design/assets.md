# STEELWARS – Asset-Spezifikation (3D-Modelle)

Sci-Fi-RTS in der Fitzel-Engine. Alle Einheiten sind **Roboter** (kein Blut, nur Öl).
Look: düster, schwer, industriell – Gunmetal, abgenutzte Panzerplatten, Warnstreifen,
leuchtende Energie-Kerne. Silhouetten müssen **von schräg oben (RTS-Kamera 45–60°,
40–150 m Abstand)** lesbar sein: kräftige Formen, Teamfarbe gut sichtbar auf den
**Oberseiten** (Dach, Turm, Schultern).

## Konventionen (wichtig)

- Blender: Z oben, Einheit/Gebäude **schaut nach -Y** (Front-Ansicht). Meter.
- Export glTF binär (`.glb`), +Y up (Standard). Damit gilt in der Engine:
  `engine = (bx, bz, -by)`, Vorne = **+Z**.
- **Ursprung des Gesamtobjekts** = Bodenmitte (Mitte der Grundfläche auf Höhe 0).
- Die Engine zentriert jedes Modell auf seine **AABB-Mitte** (nicht den glTF-Ursprung).
  Deshalb steht im Manifest pro Teil `center` (AABB-Mitte des Teils im Ruhezustand)
  und `pivot` (Drehpunkt), beide in **Engine-Koordinaten relativ zum Objekt-Ursprung**.
- Bewegliche Teile sind **eigene .glb-Dateien** (Turm, Beine, Rotoren, Radarschüssel …).
  Jedes Teil wird in seiner Ruhelage exportiert (Weltlage wie im zusammengebauten Modell
  ist ok, da die Engine sowieso auf die AABB zentriert – entscheidend ist das Manifest).
- Teamfarbe: Teile mit Teamlack werden 4× exportiert: `_t0` Karminrot (0.55,0.04,0.03),
  `_t1` Kobaltblau (0.04,0.16,0.60), `_t2` Giftgrün (0.10,0.45,0.05), `_t3` Bernstein
  (0.70,0.32,0.02). Teile ohne Teamlack nur einmal ohne Suffix.
- Höchstens **4 Materialien pro Teil** (jedes Material = ein Draw-Call): `team_paint`,
  `metal_dark` (Basis ~0.06–0.10, metallic 0.8, roughness 0.45), `metal_trim`
  (heller, 0.25, metallic 0.9, roughness 0.35, auch Warnstreifen über Geometrie),
  `glow` (Emission, Energie-Cyan (0.3,0.9,1.0) Stärke ~4–8; bei Einheiten-„Augen“
  darf es Teamfarbe sein → dann Teil des Team-Variantensatzes), `black` (Ketten, Gummi).
- Polygone: Infanterie 1.5–4k Tris, Fahrzeuge 4–12k, Gebäude 8–30k. Bevels angewendet,
  Weighted Normals / Auto Smooth, keine N-Gons-Artefakte. Keine Kameras/Lichter im Export.
- **Gebäude**: Unterkante bei y=0 bündig, plus ein **Fundament-Sockel**, der 1.5 m unter
  0 reicht (verdeckt Gelände-Unebenheiten am Hang). Grundfläche innerhalb des Footprints
  minus 0.4 m Rand.

## Einheiten (Länge × Breite × Höhe in m)

| key | Beschreibung | Teile (Achse) |
|---|---|---|
| soldier | 2.4 m hoher Kampfroboter, Sturmgewehr, kantiger Kopf mit Visier (glow) | torso (inkl. Kopf/Arme/Waffe), leg_l, leg_r (pitch um Hüfte) |
| rocketeer | wie soldier, aber bulliger, Raketenwerfer auf der Schulter (Röhre nach vorn) | torso, leg_l, leg_r |
| infiltrator | schlank, dunkel, langes Glüh-Visier, Datenstachel-Arm, wenig Teamfarbe | torso, leg_l, leg_r |
| engineer | Werkzeugarm + Rucksack mit Schweißgerät, gelbe Warnakzente | torso, leg_l, leg_r |
| tank | 7×4.2×3, Kettenpanzer-Bot, Kanone | hull, turret (yaw) |
| eliminator | 10×6×4.5, riesig, Doppelkanone, Raketenkästen | hull, turret (yaw) |
| terminator | 9×6×4.5, schwerer Kettenbot mit zwei seitlichen Strahltriebwerken (Düsen-Glow), die von waagrecht (Boden) auf senkrecht (Flug) schwenken | hull, turret (yaw), jet_l, jet_r (pitch) |
| harvester | 8×4.5×4, Ernter mit Bohr-/Fräskopf vorn und Ladebunker (Energicum-Glow sichtbar) | hull, drill (roll um Längsachse Z) |
| hypercopter | 12×10×4, schneller Transportflieger mit zwei Mantelpropellern links/rechts, Lasthaken unten | body, rotor_l, rotor_r (yaw-spin, je zentriert) |
| mcv | 10×5×4.5, Baufahrzeug, Kran auf dem Dach, Container | hull, crane (yaw) |

Wracks: für jedes Fahrzeug `<key>_wreck.glb` = Rumpf (hull/body) mit verkohltem Material
(fast schwarz, roughness 0.9, etwas glühende Glut-Emission orange in Ritzen), ohne Teamfarbe.
Für Infanterie ein gemeinsames `bot_debris.glb` (zerstreute Roboterteile, ~2×2 m).

## Gebäude (Footprint x × z in m)

| key | Footprint | Beschreibung | Bewegliche Teile |
|---|---|---|---|
| base | 28×28 | Basisstation: Kommandoturm, Landeplattform, Antennen, Notstromaggregat (glow) | – |
| powerplant | 16×16 | Kraftwerk: Reaktor mit leuchtendem Kern (cyan), Kühltürme, Kabel | – |
| refinery | 20×16 | Raffinerie: Verarbeitungstürme, Tanks, **Andockbucht vorn (+Z)** für den Harvester | – |
| silo | 12×12 | 3 senkrechte Glas-/Glow-Kapseln mit Energicum | – |
| factory | 24×24 | Bot Factory: große Halle, **großes Tor vorn (+Z)**, Kräne auf dem Dach | – |
| hangar | 28×28 | 4 Landeplätze (2×2, je ~12×12, Markierungen, Lichter) + kleiner Kontrollmast | – |
| radar | 12×12 | Sockel + große Radarschüssel | dish (yaw) |
| rocket_tower | 8×8 | Sockel + Raketenwerfer-Kopf | head (yaw) |
| laser_tower | 8×8 | Sockel + Laser-Emitter mit Kristall-Linse (glow) | head (yaw) |
| wall | 4×4 | Mauerblock 4.5 m hoch, an allen 4 Seiten anschlussfähig (kachelbar in X und Z) | – |
| watchtower | 8×8 | 12 m hoher Wachturm, oben MG-Kanzel | head (yaw) |
| lab | 20×20 | Forschungslabor: Kuppel mit Glüh-Ringen, Antenne | – |

Gebäude mit Teamfarbe ebenfalls als `_t0.._t3`.

## Ressourcen & Effekte

- `crystal_a/b/c.glb`: Energicum-Kristallgruppen (2–4 m), Glow grün-cyan (0.2,1.0,0.6), stark leuchtend.
- `shell.glb` (Granate, 0.6 m, glow orange), `rocket.glb` (1.2 m, mit Düsen-Glow).

## Manifest

`models/manifest.json`:

```json
{
  "units": {
    "tank": {
      "size": [4.2, 3.0, 7.0],
      "parts": [
        {"name": "hull",   "file": "tank_hull",   "team": true,  "center": [0,1.0,0], "pivot": [0,0,0],    "axis": "none"},
        {"name": "turret", "file": "tank_turret", "team": true,  "center": [0,2.4,0.3], "pivot": [0,2.0,0], "axis": "yaw"}
      ],
      "muzzles": [{"part": "turret", "pos": [0, 2.5, 4.1]}],
      "wreck": "tank_wreck"
    }
  },
  "buildings": {
    "refinery": {"footprint": [20,16], "parts": [...], "dock": [0,0,9.5]},
    "hangar":   {"footprint": [28,28], "parts": [...], "pads": [[-7,0.3,-7],[7,0.3,-7],[-7,0.3,7],[7,0.3,7]]},
    "factory":  {"footprint": [24,24], "parts": [...], "exit": [0,0,13]}
  }
}
```

Alle Koordinaten Engine-Raum (x rechts, y oben, z vorn), relativ zum Objekt-Ursprung.
`muzzles.pos` im Objektraum in Ruhelage (Turm nach vorn). Bei Infanterie `pivot` der Beine
= Hüftgelenk.

## Icons

`icons/<key>.png`, 256×256, transparenter Hintergrund, 3/4-Ansicht von schräg oben,
Teamfarbe t1 (blau), dramatisches Licht. Dazu `icons/contact_sheet.png` mit allem.
