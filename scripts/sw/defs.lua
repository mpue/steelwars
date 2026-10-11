-- STEELWARS -- the rules as data: units, buildings, weapons, research.
--
-- Times are seconds, distances metres, speeds metres per second, costs in
-- energy cells (Energiezellen, the currency). Power: + produces, - consumes.
-- Building footprints are in map cells (D.CELL metres).
local D = {}

D.VERSION        = "0.1"
D.TICK           = 0.05     -- one simulation step
D.TICKS_PER_TURN = 2        -- a lockstep turn (100 ms) = two steps
D.CELL           = 4        -- navigation cell size (m)
D.MAP_SIZE       = 1024     -- the playable square (m)
D.START_CELLS    = 6000
D.MAX_PLAYERS    = 4

-- Team colours (index 0..3 = model variant _t0.._t3).
D.teams = {
    [0] = { name = "Rot",   r = 0.85, g = 0.12, b = 0.08, hex = "Karmin" },
    [1] = { name = "Blau",  r = 0.15, g = 0.42, b = 1.00, hex = "Kobalt" },
    [2] = { name = "Grün",  r = 0.30, g = 0.85, b = 0.15, hex = "Gift" },
    [3] = { name = "Gelb",  r = 1.00, g = 0.62, b = 0.10, hex = "Bernstein" },
}

-- Armour classes and how much each kind of weapon hurts them.
D.vs = {
    bullet = { inf = 1.00, light = 0.55, heavy = 0.22, air = 0.55, bld = 0.20 },
    rocket = { inf = 0.35, light = 1.00, heavy = 1.10, air = 1.50, bld = 0.75 },
    shell  = { inf = 0.50, light = 1.00, heavy = 1.00, air = 0.00, bld = 0.90 },
    heavy  = { inf = 0.70, light = 1.15, heavy = 1.25, air = 0.00, bld = 1.20 },
    laser  = { inf = 1.10, light = 1.00, heavy = 0.85, air = 0.70, bld = 0.65 },
    plasma = { inf = 0.90, light = 1.10, heavy = 1.15, air = 0.90, bld = 1.00 },
}

-- Weapons. kind: hit (instant), shell (ballistic, travel), rocket (homing),
-- beam (instant, drawn as a beam). air/ground: what it can shoot at.
D.weapons = {
    rifle    = { class = "bullet", dmg = 9,   cd = 0.55, range = 30, kind = "hit",    ground = true, air = true,  sound = "rifle",   fx = "tracer" },
    mg       = { class = "bullet", dmg = 13,  cd = 0.35, range = 46, kind = "hit",    ground = true, air = true,  sound = "mg",      fx = "tracer" },
    launcher = { class = "rocket", dmg = 48,  cd = 2.4,  range = 42, kind = "rocket", ground = true, air = true,  sound = "rocket",  speed = 45 },
    cannon   = { class = "shell",  dmg = 72,  cd = 1.7,  range = 46, kind = "shell",  ground = true, air = false, sound = "cannon",  speed = 90 },
    twin     = { class = "heavy",  dmg = 85,  cd = 2.2,  range = 56, kind = "shell",  ground = true, air = false, sound = "heavycannon", speed = 95, salvo = 2 },
    plasma   = { class = "plasma", dmg = 150, cd = 2.0,  range = 58, kind = "shell",  ground = true, air = true,  sound = "plasma",  speed = 110 },
    rotorgun = { class = "bullet", dmg = 8,   cd = 0.25, range = 34, kind = "hit",    ground = true, air = true,  sound = "mg",      fx = "tracer" },
    towerrkt = { class = "rocket", dmg = 62,  cd = 2.0,  range = 64, kind = "rocket", ground = true, air = true,  sound = "rocket",  speed = 55, salvo = 2 },
    laser    = { class = "laser",  dmg = 52,  cd = 1.0,  range = 58, kind = "beam",   ground = true, air = true,  sound = "laser" },
}

-- --- Units ------------------------------------------------------------------
-- at: which building trains it. req: buildings that must stand (owned).
-- tech: research needed. carry: transport slots it takes (copter: 6).
D.units = {
    soldier = {
        name = "Soldier", desc = "Einfacher Kampfroboter mit Sturmgewehr.",
        cost = 120, time = 6, hp = 130, armor = "inf", speed = 4.0, turn = 12,
        radius = 0.8, sight = 42, weapon = "rifle", at = "base", req = {}, carry = 1,
        infantry = true, model = "soldier",
    },
    rocketeer = {
        name = "Rocketeer", desc = "Raketenwerfer. Stark gegen Panzer und Flieger.",
        cost = 280, time = 9, hp = 120, armor = "inf", speed = 3.6, turn = 10,
        radius = 0.9, sight = 46, weapon = "launcher", at = "base", req = { "radar" }, carry = 1,
        infantry = true, model = "rocketeer",
    },
    engineer = {
        name = "Ingenieur", desc = "Repariert Gebäude und Fahrzeuge. Unbewaffnet.",
        cost = 400, time = 10, hp = 100, armor = "inf", speed = 3.8, turn = 12,
        radius = 0.8, sight = 36, at = "base", req = {}, carry = 1, repair = 32,
        infantry = true, model = "engineer",
    },
    infiltrator = {
        name = "Infiltrator", desc = "Übernimmt fremde Gebäude und große Landeinheiten.",
        cost = 600, time = 14, hp = 90, armor = "inf", speed = 4.6, turn = 14,
        radius = 0.8, sight = 50, at = "base", req = { "lab" }, carry = 1, capture = 3.0,
        infantry = true, model = "infiltrator",
    },
    tank = {
        name = "Tank", desc = "Kettenpanzer-Bot mit Kanone.",
        cost = 750, time = 13, hp = 720, armor = "heavy", speed = 7.5, turn = 1.6, turretTurn = 2.2,
        radius = 2.4, sight = 50, weapon = "cannon", at = "factory", req = {}, carry = 3,
        vehicle = true, capturable = true, model = "tank",
    },
    eliminator = {
        name = "Eliminator", desc = "Riesiger Panzerbot mit Doppelkanone.",
        cost = 1700, time = 24, hp = 2100, armor = "heavy", speed = 4.8, turn = 0.9, turretTurn = 1.3,
        radius = 3.4, sight = 58, weapon = "twin", at = "factory", req = { "lab" }, carry = 6,
        vehicle = true, capturable = true, model = "eliminator",
    },
    terminator = {
        name = "Terminator", desc = "Schwerer Plasma-Bot. Kann auf Flug umschalten (F).",
        cost = 2600, time = 32, hp = 2400, armor = "heavy", speed = 5.0, flySpeed = 13, turn = 1.0, turretTurn = 1.6,
        radius = 3.2, sight = 64, weapon = "plasma", at = "factory", req = { "lab", "hangar" }, tech = "flight", carry = 6,
        vehicle = true, capturable = true, canFly = true, flyHeight = 22, model = "terminator",
    },
    harvester = {
        name = "Harvester", desc = "Sammelt Energicum und bringt es zur Raffinerie.",
        cost = 1100, time = 16, hp = 1100, armor = "heavy", speed = 8.0, turn = 1.6,
        radius = 2.6, sight = 34, at = "factory", req = { "refinery" }, carry = 3,
        vehicle = true, capturable = true, harvest = { cap = 1000, rate = 80 }, model = "harvester",
    },
    hypercopter = {
        name = "Hypercopter", desc = "Schnell und wendig. Transportiert Truppen, Harvester und Fahrzeuge.",
        cost = 1000, time = 16, hp = 520, armor = "air", speed = 24, turn = 3.0,
        radius = 4.0, sight = 60, weapon = "rotorgun", at = "factory", req = { "hangar" },
        air = true, flyHeight = 26, transport = 6, model = "hypercopter", needsPad = true,
    },
    mcv = {
        name = "Baufahrzeug", desc = "Baut sich am Zielort zur Basisstation aus (D).",
        cost = 3000, time = 30, hp = 1600, armor = "heavy", speed = 4.5, turn = 1.0,
        radius = 3.0, sight = 40, at = "factory", req = { "radar" }, carry = 6,
        vehicle = true, capturable = true, deploys = "base", model = "mcv",
    },
}

-- --- Buildings ----------------------------------------------------------------
-- size = footprint cells {w, h}. power: + produces / - consumes.
D.buildings = {
    base = {
        name = "Basisstation", desc = "Ohne sie geht nichts. Baut Gebäude und Infanterie. Notstromaggregat.",
        cost = 0, time = 0, hp = 4200, power = 30, size = { 7, 7 }, req = {}, sight = 60,
        builds = "structures", trains = true, depot = true, model = "base",
    },
    powerplant = {
        name = "Kraftwerk", desc = "Erzeugt Strom aus Energiezellen.",
        cost = 600, time = 11, hp = 1300, power = 100, fuel = 1 / 3, size = { 4, 4 }, req = { "base" },
        sight = 32, model = "powerplant",
    },
    refinery = {
        name = "Raffinerie", desc = "Wandelt Energicum in Energiezellen um. Mit Harvester.",
        cost = 1700, time = 18, hp = 1900, power = -30, size = { 5, 4 }, req = { "powerplant" },
        sight = 36, store = 1500, convert = 60, freeUnit = "harvester", model = "refinery",
    },
    silo = {
        name = "Silo", desc = "Speichert zusätzlich 2000 Energicum.",
        cost = 400, time = 7, hp = 800, power = -5, size = { 3, 3 }, req = { "refinery" },
        sight = 24, store = 2000, model = "silo",
    },
    factory = {
        name = "Bot Factory", desc = "Baut alles, was fährt oder fliegt.",
        cost = 2000, time = 22, hp = 2600, power = -50, size = { 6, 6 }, req = { "refinery" },
        sight = 36, trains = true, depot = true, model = "factory",
    },
    hangar = {
        name = "Hangar", desc = "Für Flugeinheiten. Vier Landeplätze.",
        cost = 1200, time = 16, hp = 1600, power = -40, size = { 7, 7 }, req = { "factory", "radar" },
        sight = 40, pads = 4, depot = true, model = "hangar",
    },
    radar = {
        name = "Radar", desc = "Ohne Radar keine Karte.",
        cost = 1000, time = 14, hp = 1000, power = -40, size = { 3, 3 }, req = { "refinery" },
        sight = 80, radar = true, model = "radar",
    },
    rocket_tower = {
        name = "Raketenturm", desc = "Verteidigung gegen Panzer und Flieger.",
        cost = 800, time = 12, hp = 950, power = -25, size = { 2, 2 }, req = { "radar" },
        sight = 66, weapon = "towerrkt", model = "rocket_tower", defense = true,
    },
    laser_tower = {
        name = "Laserturm", desc = "Starke Verteidigung. Braucht viel Strom.",
        cost = 1300, time = 16, hp = 1300, power = -60, size = { 2, 2 }, req = { "lab" },
        sight = 60, weapon = "laser", model = "laser_tower", defense = true,
    },
    wall = {
        name = "Mauer", desc = "Hält Bodentruppen auf. In Linien ziehen.",
        cost = 40, time = 1, hp = 900, power = 0, size = { 1, 1 }, req = { "base" },
        sight = 8, model = "wall", wall = true,
    },
    watchtower = {
        name = "Wachturm", desc = "Maschinengewehr gegen Infanterie. Weite Sicht.",
        cost = 500, time = 9, hp = 900, power = -10, size = { 2, 2 }, req = { "base" },
        sight = 72, weapon = "mg", model = "watchtower", defense = true,
    },
    lab = {
        name = "Forschungslabor", desc = "Erforscht Verstärkungen, Erweiterungen und neue Technik.",
        cost = 1500, time = 20, hp = 1500, power = -60, size = { 5, 5 }, req = { "factory", "radar" },
        sight = 36, research = true, model = "lab",
    },
}

-- What each building's "Erweiterung" does (multipliers / extras), once
-- researched and paid for on that building.
D.extend = {
    base         = { label = "+30 Notstrom, Bauzeit -25 %", power = 30, buildSpeed = 1.33 },
    powerplant   = { label = "+60 % Strom", powerMul = 1.6 },
    refinery     = { label = "Umwandlung +60 %, Lager +1000", convertMul = 1.6, store = 1000 },
    silo         = { label = "Lager verdoppelt", storeMul = 2.0 },
    factory      = { label = "Produktion +40 %", buildSpeed = 1.4 },
    hangar       = { label = "Flieger werden repariert", repair = 20 },
    radar        = { label = "Sichtweite +50 %", sightMul = 1.5 },
    rocket_tower = { label = "Reichweite +25 %, Doppelsalve", rangeMul = 1.25, salvo = 2 },
    laser_tower  = { label = "Schaden +50 %", dmgMul = 1.5 },
    wall         = { label = "Energieschild +100 % HP", hpMul = 2.0 },
    watchtower   = { label = "Reichweite und Sicht +30 %", rangeMul = 1.3, sightMul = 1.3 },
    lab          = { label = "Forschung +50 % schneller", researchSpeed = 1.5 },
}
D.ARMOR_MUL   = 1.6     -- "Verstärkt": hit points x 1.6
D.UPGRADE_COST = 0.5    -- an upgrade costs half the building

-- Research at the lab. Building armour/extension techs are generated below.
D.research = {
    { key = "weapons1", name = "Waffen I",     desc = "+20 % Schaden aller Einheiten", cost = 1200, time = 30 },
    { key = "weapons2", name = "Waffen II",    desc = "+20 % Schaden aller Einheiten", cost = 2000, time = 45, after = "weapons1" },
    { key = "plating1", name = "Panzerung I",  desc = "+20 % Struktur aller Einheiten", cost = 1200, time = 30 },
    { key = "plating2", name = "Panzerung II", desc = "+20 % Struktur aller Einheiten", cost = 2000, time = 45, after = "plating1" },
    { key = "flight",   name = "Flugantrieb",  desc = "Schaltet den Terminator frei", cost = 1800, time = 40 },
}
D.researchByKey = {}
D.buildingOrder = { "powerplant", "refinery", "silo", "factory", "radar", "hangar", "lab",
                    "watchtower", "rocket_tower", "laser_tower", "wall" }
local upgradeable = { "base", "powerplant", "refinery", "silo", "factory", "hangar", "radar",
                      "rocket_tower", "laser_tower", "wall", "watchtower", "lab" }
for _, b in ipairs(upgradeable) do
    local bd = D.buildings[b]
    D.research[#D.research + 1] = { key = b .. "_armor", name = bd.name .. ": Verstärkung",
        desc = "Erlaubt, " .. bd.name .. " zu verstärken (+60 % Struktur).",
        cost = 500, time = 18, building = b, upgrade = "armor" }
    D.research[#D.research + 1] = { key = b .. "_ext", name = bd.name .. ": Erweiterung",
        desc = "Erlaubt die Erweiterung: " .. D.extend[b].label .. ".",
        cost = 800, time = 24, building = b, upgrade = "ext" }
end
for _, r in ipairs(D.research) do D.researchByKey[r.key] = r end

D.unitOrder = {
    base    = { "soldier", "rocketeer", "engineer", "infiltrator" },
    factory = { "tank", "harvester", "eliminator", "terminator", "hypercopter", "mcv" },
}

-- Energicum fields: crystals hold this much each.
D.CRYSTAL_AMOUNT = 1200
D.CRYSTAL_REGROW = 5           -- per second, up to the full amount
D.REFINERY_DOCK_TIME = 3.0     -- seconds a harvester spends unloading
D.BUILD_RADIUS = 9             -- cells around own buildings where new ones may go
D.SELL_REFUND = 0.5
-- Repair at a depot (buildings with depot = true): hit points per second, and
-- what a full repair costs as a share of the unit's price.
D.DEPOT_RATE  = 45
D.DEPOT_PRICE = 0.5

return D
