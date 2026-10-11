-- STEELWARS -- effects: muzzle flashes, tracers, laser beams, explosions,
-- burning wrecks, scorch marks, oil (robots do not bleed), flashes of light,
-- and the sounds that go with them.
--
-- Particle bursts come from emitter objects authored in the scene ("FX
-- Explosion", "FX Sparks", ...): one emitter serves any number of blasts -- put
-- it there, fire it, move on (game.emit). Continuous fires and smoke columns are
-- a pool of looping emitters that are moved onto whatever burns.
local D = require("sw.defs")
local U = require("sw.util")
local A = require("sw.audio")

local F = {}
local floor, sqrt, min, max, abs, sin, cos = math.floor, math.sqrt, math.min, math.max, math.abs, math.sin, math.cos

local burst = {}       -- name -> emitter id
local loops = {}       -- kind -> { {id, busy, x,y,z, until} }
local LOOPS = 32        -- flames and smoke columns at once, each (a wood on fire)
local lights = {}      -- { id, life, max, intensity }
local beams = {}       -- { id, life, max, kind }
local wrecks = {}
local shake = 0
F.camX, F.camZ, F.camDist = 0, 0, 100

local BURSTS = { "FX Explosion", "FX Fireball", "FX Smoke Puff", "FX Sparks", "FX Debris", "FX Oil", "FX Muzzle",
                 "FX Dust", "FX Energicum", "FX Laser Hit", "FX Plasma Hit", "FX Trail", "FX Weld" }

function F.init()
    for _, n in ipairs(BURSTS) do burst[n] = game.find(n) end
    for _, kind in ipairs({ "FX Fire", "FX Smoke" }) do
        loops[kind] = {}
        local ids = game.findAll(kind)
        -- a burning wood wants more than the scene brought: copies of the first
        for _ = #ids + 1, LOOPS do
            local id = ids[1] and game.clone(ids[1], kind)
            if not id or id == 0 then break end
            ids[#ids + 1] = id
        end
        for _, id in ipairs(ids) do
            loops[kind][#loops[kind] + 1] = { id = id, busy = false }
            game.setActive(id, false)
        end
    end
    -- flashes of light
    for k = 1, 8 do
        local id = game.spawn{ type = game.LIGHT, x = 0, y = -100, z = 0, r = 1, g = 0.6, b = 0.3, physics = 0, name = "FX Light" }
        lights[k] = { id = id, life = 0, max = 1, intensity = 0, fresh = 2 }
    end
    -- tracers and beams: thin glowing boxes
    F.matTracer = game.createMaterial{ name = "SW Tracer", color = { 1, 0.8, 0.4 }, emission = { 1, 0.75, 0.35 }, emissionStrength = 9 }
    F.matLaser = {}
    for k = 1, 3 do
        local s = 14 - k * 4
        F.matLaser[k] = game.createMaterial{ name = "SW Laser " .. k, color = { 0.4, 0.9, 1 }, emission = { 0.35, 0.85, 1.0 },
                                             emissionStrength = s, opacity = 1 - (k - 1) * 0.3, alphaMode = game.ALPHA_BLEND }
    end
    for k = 1, 40 do
        local id = game.spawn{ type = game.BOX, x = 0, y = -100, z = 0, size = 0.05, physics = 0, material = F.matTracer, name = "FX Beam" }
        beams[k] = { id = id, life = 0, max = 0.1, fresh = 2 }
    end
    F.scorch = game.findMaterial("SW Scorch") or game.createMaterial{ name = "SW Scorch", texture = "scorch.png",
        alphaMode = game.ALPHA_BLEND, color = { 1, 1, 1 }, roughness = 0.95 }
    F.oil = game.findMaterial("SW Oil") or game.createMaterial{ name = "SW Oil", texture = "oil.png",
        alphaMode = game.ALPHA_BLEND, color = { 1, 1, 1 }, reflectivity = 0.6, roughness = 0.15 }
end

local function emitAt(name, x, y, z)
    local id = burst[name]
    if not id then return end
    game.setPos(id, x, y, z)
    game.emit(id)
end
F.emitAt = emitAt

local function flash(x, y, z, r, g, b, intensity, range, life)
    local best, bl = nil, 1e9
    for _, l in ipairs(lights) do
        if l.life <= 0 then best = l; break end
        if l.life < bl then best, bl = l, l.life end
    end
    if not best or best.fresh > 0 then return end
    best.life, best.max, best.intensity = life, life, intensity
    game.setActive(best.id, true)
    game.setPos(best.id, x, y, z)
    game.setLight(best.id, { color = { r, g, b }, intensity = intensity, range = range })
end

local function beam(x1, y1, z1, x2, y2, z2, kind, life)
    local b
    for _, c in ipairs(beams) do if c.life <= 0 and c.fresh <= 0 then b = c; break end end
    if not b then return end
    local dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
    local l = sqrt(dx * dx + dy * dy + dz * dz)
    if l < 0.5 then return end
    local rx, ry, rz = U.eulerFromFrame(dx / l, dy / l, dz / l, 0, 1, 0)
    local w = (kind == "laser") and 0.22 or 0.045
    local len = l * 0.5
    if kind ~= "laser" then
        -- a tracer is a short streak near the target end
        len = min(len, 3)
        x1, y1, z1 = x2 - dx / l * len * 2, y2 - dy / l * len * 2, z2 - dz / l * len * 2
    end
    game.setActive(b.id, true)
    game.setScale(b.id, w, w, len)
    game.setMaterial(b.id, kind == "laser" and F.matLaser[1] or F.matTracer)
    game.setLocal(b.id, (x1 + x2) * 0.5, (y1 + y2) * 0.5, (z1 + z2) * 0.5, rx, ry, rz)
    b.life, b.max, b.kind = life, life, kind
end

-- How loud something is at the camera: the engine attenuates by distance too,
-- but a battle at the other end of the map should not be in the mix at all.
local function audible(x, z)
    return U.dist(x, z, F.camX, F.camZ) < F.camDist * 3.5 + 150
end

function F.sound(cue, x, y, z, vol, pitch)
    if x and not audible(x, z) then return end
    A.play(cue, x, y, z, vol, pitch)
end

-- --- Events from the simulation ------------------------------------------------------
function F.fire(o, ev, muzzle)
    local w = D.weapons[ev.w]
    if not w then return end
    local mx, my, mz = muzzle(o, 1)
    local vis = F.visible(o)
    if vis then
        emitAt("FX Muzzle", mx, my, mz)
        if w.kind == "hit" then
            beam(mx, my, mz, ev.x, ev.gy + ev.y, ev.z, "tracer", 0.07)
            if F.rng() < 0.5 then emitAt("FX Sparks", ev.x, ev.gy + ev.y, ev.z) end
        elseif w.kind == "beam" then
            beam(mx, my, mz, ev.x, ev.gy + ev.y, ev.z, "laser", 0.3)
            emitAt("FX Laser Hit", ev.x, ev.gy + ev.y, ev.z)
            flash(ev.x, ev.gy + ev.y + 1, ev.z, 0.4, 0.8, 1.0, 40, 18, 0.25)
        elseif w.kind == "shell" then
            flash(mx, my, mz, 1.0, 0.7, 0.35, 30, 14, 0.12)
        end
    end
    F.sound(w.sound, mx, my, mz, 0.8, 0.93 + F.rng() * 0.14)
end

function F.impact(ev, gy)
    local y = gy + 0.3
    local big = (ev.class == "heavy" or ev.class == "plasma")
    if ev.class == "plasma" then emitAt("FX Plasma Hit", ev.x, y + 1, ev.z) end
    emitAt("FX Fireball", ev.x, y + 1, ev.z)
    emitAt("FX Dust", ev.x, y, ev.z)
    if big or ev.direct then emitAt("FX Sparks", ev.x, y + 1, ev.z) end
    flash(ev.x, y + 2, ev.z, 1.0, 0.6, 0.25, big and 70 or 40, big and 22 or 14, 0.18)
    if F.rng() < 0.6 then game.decal(ev.x, gy + 0.05, ev.z, 0, 1, 0, big and 3.5 or 2.2, F.scorch, F.rng() * 360) end
    F.sound(big and "impact_big" or "impact", ev.x, y, ev.z, 0.9)
end

function F.explode(ev, gy)
    local y = gy + 0.5
    if ev.infantry then
        emitAt("FX Sparks", ev.x, y + 1, ev.z)
        emitAt("FX Oil", ev.x, y + 1, ev.z)
        emitAt("FX Smoke Puff", ev.x, y + 0.5, ev.z)
        game.decal(ev.x, gy + 0.05, ev.z, 0, 1, 0, 2.4, F.oil, F.rng() * 360)
        flash(ev.x, y + 1.5, ev.z, 1.0, 0.8, 0.5, 20, 8, 0.15)
        F.sound("die_bot", ev.x, y, ev.z, 1.0, 0.9 + F.rng() * 0.2)
        return
    end
    local size = ev.size or 1
    emitAt("FX Explosion", ev.x, y + 1, ev.z)
    emitAt("FX Fireball", ev.x, y + 2, ev.z)
    emitAt("FX Debris", ev.x, y + 1, ev.z)
    emitAt("FX Smoke Puff", ev.x, y + 2, ev.z)
    emitAt("FX Sparks", ev.x, y + 2, ev.z)
    if size >= 2 then
        for k = 1, size do
            local a = F.rng() * 6.283
            local r = 3 + size * 2
            emitAt("FX Explosion", ev.x + cos(a) * r, y + 2, ev.z + sin(a) * r)
            emitAt("FX Fireball", ev.x + cos(a) * r, y + 4, ev.z + sin(a) * r)
        end
    end
    game.decal(ev.x, gy + 0.05, ev.z, 0, 1, 0, 4 + size * 3, F.scorch, F.rng() * 360)
    flash(ev.x, y + 3, ev.z, 1.0, 0.55, 0.2, 90 + size * 60, 25 + size * 12, 0.45 + size * 0.15)
    F.sound(size >= 3 and "explode_big" or (size >= 2 and "explode_med" or "explode_small"), ev.x, y, ev.z, 1.0, 0.9 + F.rng() * 0.15)
    if U.dist(ev.x, ev.z, F.camX, F.camZ) < F.camDist * 1.2 then shake = min(1.2, shake + 0.25 * size) end
end

-- A burning wreck where a vehicle died; it smoulders, sinks and goes.
function F.wreck(file, x, y, z, ry, life)
    if not file then return end
    local id = game.spawn{ model = file .. ".glb", x = x, y = y, z = z, ry = ry, physics = 0, name = "wreck" }
    if not id or id == 0 then return end
    local w = { id = id, x = x, y = y, z = z, ry = ry, t = 0, life = life or 40 }
    w.fire = F.loop("FX Fire", x, y + 1.5, z, 10)
    w.smoke = F.loop("FX Smoke", x, y + 3, z, 25)
    wrecks[#wrecks + 1] = w
end

-- Borrow a looping emitter for `secs` seconds (nil = until released). Each
-- loan counts up l.gen, so a holder can tell its loan from a later one.
function F.loop(kind, x, y, z, secs)
    local pool = loops[kind]
    if not pool then return nil end
    for _, l in ipairs(pool) do
        if not l.busy then
            l.busy = true
            l.left = secs
            l.gen = (l.gen or 0) + 1
            game.setActive(l.id, true)
            game.setPos(l.id, x, y, z)
            return l
        end
    end
    return nil
end
-- `gen`: only that loan (it may have run out and gone to someone else).
function F.release(l, gen)
    if l and l.busy and (gen == nil or l.gen == gen) then l.busy = false; game.setActive(l.id, false) end
end

-- --- Trees on fire --------------------------------------------------------------------
-- Flames in the crown and smoke above it while the tree chars (game.burnTree);
-- the flames die down before the wood is out. Keyed by the trunk, so a tree
-- rolled over while it burns takes its fire with it.
local treeFires = {}
local function treeKey(x, z) return string.format("%.2f,%.2f", x, z) end

function F.burnTree(x, z, scale, secs)
    if game.burnTree and not game.burnTree(x, z, secs) then return end
    local gy = game.terrainHeight(x, z)
    local f = F.loop("FX Fire", x, gy + scale * 0.55, z, secs * 0.7)
    local s = F.loop("FX Smoke", x, gy + scale * 0.85, z, secs)
    treeFires[treeKey(x, z)] = { f = f, fg = f and f.gen, s = s, sg = s and s.gen }
end

function F.treeDown(x, z)
    local k = treeKey(x, z)
    local t = treeFires[k]
    if not t then return end
    F.release(t.f, t.fg)
    F.release(t.s, t.sg)
    treeFires[k] = nil
end

-- --- Per frame ------------------------------------------------------------------------
function F.update(dt)
    for _, l in ipairs(lights) do
        if l.fresh > 0 then
            l.fresh = l.fresh - 1
            if l.fresh == 0 then game.setActive(l.id, false); game.setLight(l.id, { intensity = 0 }) end
        elseif l.life > 0 then
            l.life = l.life - dt
            if l.life <= 0 then
                game.setActive(l.id, false)
            else
                local f = l.life / l.max
                game.setLight(l.id, { intensity = l.intensity * f * f })
            end
        end
    end
    for _, b in ipairs(beams) do
        if b.fresh > 0 then
            b.fresh = b.fresh - 1
            if b.fresh == 0 then game.setActive(b.id, false) end
        elseif b.life > 0 then
            b.life = b.life - dt
            if b.life <= 0 then
                game.setActive(b.id, false)
            elseif b.kind == "laser" then
                local k = (b.life / b.max > 0.66) and 1 or ((b.life / b.max > 0.33) and 2 or 3)
                game.setMaterial(b.id, F.matLaser[k])
            end
        end
    end
    for kind, pool in pairs(loops) do
        for _, l in ipairs(pool) do
            if l.busy and l.left then
                l.left = l.left - dt
                if l.left <= 0 then F.release(l) end
            end
        end
    end
    local keep = {}
    for _, w in ipairs(wrecks) do
        w.t = w.t + dt
        if w.t > w.life - 6 then
            -- sink away
            local s = (w.t - (w.life - 6)) / 6
            game.setLocal(w.id, w.x, w.y - s * 3, w.z, 0, w.ry, 0)
        end
        if w.t >= w.life then
            game.destroy(w.id)
            F.release(w.fire)
            F.release(w.smoke)
        else
            keep[#keep + 1] = w
        end
    end
    wrecks = keep
    shake = max(0, shake - dt * 2.5)
end

function F.shake() return shake end

-- the view's random numbers (not the simulation's)
local seed = 12345
function F.rng()
    seed = (seed * 1103515245 + 12345) % 2147483648
    return seed / 2147483648
end

F.visible = function() return true end

return F
