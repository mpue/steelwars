-- STEELWARS -- combat: who shoots whom, turrets, projectiles, damage,
-- destruction. Part of the deterministic simulation.
local D = require("sw.defs")
local U = require("sw.util")
local M = require("sw.map")

return function(S)

local floor, sqrt, abs, min, max, sin, cos = math.floor, math.sqrt, math.abs, math.min, math.max, math.sin, math.cos
local DT = D.TICK
S.projs = {}

local function weaponOf(o)
    local w = o.def.weapon
    return w and D.weapons[w]
end
S.weaponOf = weaponOf

local function rangeOf(o, w)
    local r = w.range
    if o.cat == "bld" and o.ext and D.extend[o.type].rangeMul then r = r * D.extend[o.type].rangeMul end
    return r
end

function S.inRange(o, t)
    local w = weaponOf(o)
    if not w then return false end
    return S.edgeDist(o, t) <= rangeOf(o, w)
end

local function armorOf(t)
    if t.cat == "bld" then return "bld" end
    if t.flying or t.air then return "air" end
    return t.def.armor
end

local function isAir(t) return t.cat == "unit" and (t.air or t.flying) and t.y > 2 end

local function canHit(o, t, w)
    if not t.alive or t.inside or t.cat == "crystal" then return false end
    if not S.enemies(o.owner, t.owner) then return false end
    if isAir(t) then return w.air end
    return w.ground
end

local function online(o)
    -- defences need power (the watchtower's gun is mechanical)
    if o.cat ~= "bld" then return true end
    if o.built < 1 then return false end
    if o.type == "watchtower" then return true end
    return not S.players[o.owner].lowPower
end

-- --- Damage ------------------------------------------------------------------------
function S.damage(t, dmg, class, by)
    if not t.alive then return end
    local mul = 1
    local vs = D.vs[class]
    if vs then mul = vs[armorOf(t)] or 1 end
    local amt = dmg * mul
    if amt <= 0 then return end
    t.hp = t.hp - amt
    t.hitAt = S.tick
    if t.owner >= 0 then
        local pl = S.players[t.owner]
        if (pl.lastAttackMsg or -1000) + 200 < S.tick and by then
            pl.lastAttackMsg = S.tick
            if t.cat == "bld" then S.msg(t.owner, "Basis wird angegriffen", "attacked")
            else S.msg(t.owner, "Einheiten unter Beschuss", "unitattacked") end
            S.emit({ t = "alert", p = t.owner, x = t.x, z = t.z })
        end
        -- remember who did it, so an idle unit can answer
        t.lastHitBy = by
    end
    if t.hp <= 0 then
        t.hp = 0
        local big = (t.cat == "bld") and (t.radius > 8 and 3 or 2) or (t.def.infantry and 0 or (t.radius > 3 and 2 or 1))
        S.emit({ t = "explode", x = t.x, z = t.z, y = t.y, size = big, cat = t.cat, type = t.type, infantry = t.def.infantry })
        S.remove(t, "killed", by)
    end
end

local function splash(x, z, r, dmg, class, owner, by, except)
    S.query(x, z, r, function(t)
        if t ~= except and t.alive and not t.inside and S.enemies(owner, t.owner) and not isAir(t) then
            local d = U.dist(x, z, t.x, t.z) - t.radius
            local f = 1 - U.clamp(d / r, 0, 1)
            if f > 0 then S.damage(t, dmg * 0.5 * f, class, by) end
        end
    end)
end

-- --- Firing -------------------------------------------------------------------------
local function muzzleHeight(o)
    if o.cat == "bld" then return (o.type == "watchtower") and 11 or 6 end
    return o.y + (o.def.infantry and 1.6 or 2.4)
end
local function aimHeight(t)
    if t.cat == "bld" then return 3 end
    return t.y + (t.def.infantry and 1.2 or 1.5)
end

-- --- Trees on fire ---------------------------------------------------------------
-- A hit near a trunk sets the tree alight (bullets do not; shells, rockets,
-- plasma and the laser do). It burns BURN seconds; somewhere in the first
-- half of that it may catch its neighbours: every unburnt tree within
-- SPREAD_R gets one roll at SPREAD_P, and no more than SPREAD_MAX catch. In a
-- dense wood that is a little under one new fire per fire -- about four trees
-- a fire, now and then twenty and more: it runs through a stand and dies out,
-- it does not take the map. Burnt out, the tree stands charred, still a wall;
-- the next hit knocks the snag down.
local BURN = 20
local BURN_T = floor(BURN / DT)
local SPREAD_R, SPREAD_P, SPREAD_MAX = 7, 0.22, 2

local function addTrunks(list, c)
    local t = M.trunks[c]
    if not t then return list end
    list = list or {}
    for k = 1, #t do list[#list + 1] = t[k] end
    return list
end

local function igniteCell(c)
    M.fire[c] = "burning"
    S.fires[#S.fires + 1] = { c = c, t = 0, spread = floor(BURN_T * 0.15) + S.rng:int(0, floor(BURN_T * 0.35)) }
end

-- A hit at (x, z), flying along heading h.
local function hitTrees(x, z, class, h)
    if class == "bullet" then return end
    local r = (class == "heavy" or class == "plasma") and 4 or 2.5
    local lit, down
    for _, c in ipairs(M.treeCells(x, z, r)) do
        local st = M.fire[c]
        if st == nil then
            igniteCell(c)
            lit = addTrunks(lit, c)
        elseif st == "charred" then
            down = addTrunks(down, c)
            M.fellCell(c)
        end
    end
    if lit then S.emit({ t = "burn", trees = lit, secs = BURN }) end
    if down then S.emit({ t = "fell", x = x, z = z, h = h, back = false, trees = down }) end
end

function S.updateFires()
    local list = S.fires
    if #list == 0 then return end
    S.fires = {}
    local lit
    for _, f in ipairs(list) do
        f.t = f.t + 1
        if M.block[f.c] ~= 5 then
            -- rolled over while burning: what is left chars on the ground (the view)
        elseif f.t >= BURN_T then
            M.fire[f.c] = "charred"
        else
            if f.t == f.spread then
                local t = M.trunks[f.c]
                local n = 0
                for _, c in ipairs(M.treeCells(t[1], t[2], SPREAD_R)) do
                    if n < SPREAD_MAX and M.fire[c] == nil and S.rng:float() < SPREAD_P then
                        igniteCell(c)
                        lit = addTrunks(lit, c)
                        n = n + 1
                    end
                end
            end
            S.fires[#S.fires + 1] = f
        end
    end
    if lit then S.emit({ t = "burn", trees = lit, secs = BURN }) end
end

-- At target t -- or, with t nil, at the ground point (gx, gz) (a unit driven
-- by hand, shooting where nobody stands).
local function fire(o, t, w, gx, gz)
    local dmg = w.dmg * S.techMul(o.owner, "dmg")
    if o.cat == "bld" and o.ext and D.extend[o.type].dmgMul then dmg = dmg * D.extend[o.type].dmgMul end
    local salvo = w.salvo or 1
    if o.cat == "bld" and o.ext and D.extend[o.type].salvo then salvo = max(salvo, D.extend[o.type].salvo) end
    local sy, ty = muzzleHeight(o), t and aimHeight(t) or 0
    local tx, tz = t and t.x or gx, t and t.z or gz
    S.emit({ t = "fire", id = o.id, w = o.def.weapon, tid = t and t.id or 0, x = tx, y = ty, z = tz })
    if w.kind == "hit" or w.kind == "beam" then
        if t then S.damage(t, dmg, w.class, o.id)
        elseif w.kind == "beam" then hitTrees(tx, tz, w.class, U.heading(tx - o.x, tz - o.z)) end
        return
    end
    for n = 1, salvo do
        local p = {
            w = o.def.weapon, kind = w.kind, class = w.class, owner = o.owner, src = o.id, tgt = t and t.id or 0,
            x = o.x, y = sy, z = o.z, sx = o.x, sy = sy, sz = o.z,
            tx = tx + (n - 1) * 0.8, ty = ty, tz = tz, dmg = dmg / salvo * (salvo > 1 and 1.15 or 1),
            speed = w.speed or 60, prog = 0, life = 0, alive = true, salvoN = n,
            delay = (n - 1) * 4,
        }
        p.px, p.py, p.pz = p.x, p.y, p.z
        -- rockets set off in the firing direction, then turn toward the target
        local dx, dz = tx - o.x, tz - o.z
        local d = max(0.1, sqrt(dx * dx + dz * dz))
        p.vx, p.vy, p.vz = dx / d * p.speed * 0.6, p.speed * 0.25, dz / d * p.speed * 0.6
        p.dist = d
        S.projs[#S.projs + 1] = p
    end
end

local function acquire(o, w, reach)
    local best, bd = nil, 1e18
    local pl = o.owner
    S.query(o.x, o.z, reach, function(t)
        if canHit(o, t, w) and S.sees(pl, t.x, t.z) then
            local d = U.dist2(o.x, o.z, t.x, t.z)
            -- shoot at what shoots back first, then at buildings
            if t.cat == "bld" then d = d + 2500 end
            if t.cat == "bld" and t.type == "wall" then d = d + 5000 end
            if d < bd then best, bd = t, d end
        end
    end)
    return best
end

-- A unit driven by hand (o.ctl, see simunit.lua) shoots where its driver
-- aims, while the trigger is held. The turret turns to the aim point; a unit
-- without one turns itself while the trigger is held and it is not being
-- steered. The shot goes to the enemy nearest the aim point -- or, with none
-- there, into the ground, no further than the weapon reaches.
local function manual(o, w)
    if o.cd > 0 then o.cd = o.cd - DT end
    local c = o.ctl
    o.target = 0
    local want = U.heading(c.ax - o.x, c.az - o.z)
    local aimed
    if o.def.turretTurn then
        local rel = U.angDiff(o.h, want)
        o.tAng = U.turnTo(o.tAng, rel, o.def.turretTurn * DT)
        aimed = abs(U.angDiff(o.tAng, rel)) < 0.1
    else
        if c.fire and c.steer == 0 then o.h = U.turnTo(o.h, want, min(o.def.turn or 2, 4) * DT) end
        aimed = abs(U.angDiff(o.h, want)) < 0.3
    end
    if not c.fire or not aimed or o.cd > 0 then return end
    local range = rangeOf(o, w)
    local t, bd = nil, 1e18
    S.query(c.ax, c.az, 8, function(u)
        if canHit(o, u, w) and S.edgeDist(o, u) <= range then
            local d = U.dist2(c.ax, c.az, u.x, u.z)
            if d < bd then t, bd = u, d end
        end
    end)
    o.cd = w.cd
    o.firedAt = S.tick
    if t then fire(o, t, w); return end
    local dx, dz = c.ax - o.x, c.az - o.z
    local d = sqrt(dx * dx + dz * dz)
    if d > range then dx, dz = dx / d * range, dz / d * range end
    fire(o, nil, w, o.x + dx, o.z + dz)
end

local function combat(o)
    local w = weaponOf(o)
    if not w or not online(o) then return end
    if o.ctl then manual(o, w); return end
    if o.cd > 0 then o.cd = o.cd - DT end
    local t = S.get(o.target)
    local ord = (o.cat == "unit") and o.orders[1] or nil
    -- a target given by order stands; one found by itself is reviewed
    if t and not canHit(o, t, w) then t = nil; o.target = 0 end
    local range = rangeOf(o, w)
    if t and (not ord or ord.k ~= "attack") and S.edgeDist(o, t) > range + 4 then
        t = nil; o.target = 0
    end
    if not t and (S.tick + o.id) % 6 == 0 then
        local reach = range
        local idle = (o.cat == "unit") and (not ord or ord.k == "guard")
        if idle and not o.def.harvest then reach = range + 12 end
        t = acquire(o, w, reach)
        if t then
            o.target = t.id
            -- an idle unit walks up to what it saw just out of range
            if idle and o.cat == "unit" and not S.inRange(o, t) then
                table.insert(o.orders, 1, { k = "attack", id = t.id, auto = true })
            end
        elseif o.cat == "unit" and idle and o.lastHitBy then
            -- shot at by something we cannot see from here: turn to face it
            local a = S.get(o.lastHitBy)
            o.lastHitBy = nil
            if a and canHit(o, a, w) and U.dist(o.x, o.z, a.x, a.z) < range + 30 then
                table.insert(o.orders, 1, { k = "attack", id = a.id, auto = true })
            end
        end
    end
    if not t then
        -- turret drifts back to the front
        if o.def.turretTurn then o.tAng = U.turnTo(o.tAng, 0, o.def.turretTurn * DT) end
        return
    end
    if S.edgeDist(o, t) > range then return end
    -- aim
    local want = U.heading(t.x - o.x, t.z - o.z)
    local aimed
    if o.cat == "bld" then
        o.tAng = U.turnTo(o.tAng, want, 2.5 * DT)
        aimed = abs(U.angDiff(o.tAng, want)) < 0.12
    elseif o.def.turretTurn then
        local rel = U.angDiff(o.h, want)
        o.tAng = U.turnTo(o.tAng, rel, o.def.turretTurn * DT)
        aimed = abs(U.angDiff(o.tAng, rel)) < 0.1
    else
        if o.def.infantry and o.moving then return end
        o.h = U.turnTo(o.h, want, (o.def.turn or 4) * DT)
        aimed = abs(U.angDiff(o.h, want)) < 0.25
    end
    if aimed and o.cd <= 0 then
        o.cd = w.cd
        o.firedAt = S.tick
        fire(o, t, w)
    end
end

function S.updateCombat()
    for _, o in ipairs(S.objs) do
        if o.alive and not o.inside and (o.cat == "unit" or o.cat == "bld") and o.owner >= 0 then
            combat(o)
        end
    end
end

-- --- Projectiles ----------------------------------------------------------------
function S.updateProjectiles()
    local keep = {}
    for _, p in ipairs(S.projs) do
        p.px, p.py, p.pz = p.x, p.y, p.z
        if p.delay > 0 then
            p.delay = p.delay - 1
            keep[#keep + 1] = p
        else
            p.life = p.life + DT
            local t = S.get(p.tgt)
            local hit = false
            if p.kind == "rocket" then
                local tx, ty, tz = p.tx, p.ty, p.tz
                if t and not t.inside then tx, ty, tz = t.x, aimHeight(t), t.z; p.tx, p.ty, p.tz = tx, ty, tz end
                local dx, dy, dz = tx - p.x, ty - p.y, tz - p.z
                local d = sqrt(dx * dx + dy * dy + dz * dz)
                if d < 2.0 then hit = true
                else
                    local s = p.speed
                    local steer = min(1, 6 * DT)
                    p.vx = p.vx + (dx / d * s - p.vx) * steer
                    p.vy = p.vy + (dy / d * s - p.vy) * steer
                    p.vz = p.vz + (dz / d * s - p.vz) * steer
                    local v = sqrt(p.vx * p.vx + p.vy * p.vy + p.vz * p.vz)
                    local step = min(d, s * DT)
                    p.x, p.y, p.z = p.x + p.vx / v * step, p.y + p.vy / v * step, p.z + p.vz / v * step
                end
                if p.life > 5 then hit = true end
            else
                -- ballistic: straight in plan, a gentle arc in height
                p.prog = p.prog + p.speed * DT / max(1, p.dist)
                local f = min(1, p.prog)
                p.x = p.sx + (p.tx - p.sx) * f
                p.z = p.sz + (p.tz - p.sz) * f
                p.y = p.sy + (p.ty - p.sy) * f + sin(f * math.pi) * p.dist * 0.06
                if f >= 1 then hit = true end
            end
            if hit then
                p.alive = false
                local impactX, impactZ = p.x, p.z
                local direct = t and not t.inside and U.dist(t.x, t.z, impactX, impactZ) <= t.radius + 2.5
                if direct then S.damage(t, p.dmg, p.class, p.src) end
                local r = (p.class == "heavy" or p.class == "plasma") and 4 or 2.5
                splash(impactX, impactZ, r, p.dmg, p.class, p.owner, p.src, direct and t or nil)
                hitTrees(impactX, impactZ, p.class, U.heading(p.tx - p.sx, p.tz - p.sz))
                S.emit({ t = "impact", x = impactX, y = p.y, z = impactZ, w = p.w, class = p.class, direct = direct })
            else
                keep[#keep + 1] = p
            end
        end
    end
    S.projs = keep
end

end
