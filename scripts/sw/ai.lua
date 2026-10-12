-- STEELWARS -- the computer opponent.
--
-- It plays by the same rules as a person: it sees the world through S, and
-- everything it does goes through S.apply as an order line. It runs INSIDE the
-- simulation step (S.aiThink), so in a multiplayer game with computer players
-- every machine computes the same thoughts from the same state -- no AI order
-- ever has to cross the network. Deterministic: S.rng only, arrays only.
--
-- The same brain also serves the language-model commanders (sw/agent.lua):
-- A.thinkWith runs it OUTSIDE the simulation with a context that carries
-- their plan, sends the orders through the session and draws its chances
-- from math.random -- the simulation's own random numbers stay untouched.
local D = require("sw.defs")
local U = require("sw.util")
local M = require("sw.map")

local A = {}
local floor, min, max, sqrt = math.floor, math.min, math.max, math.sqrt

local brains = {}

local LEVEL = {
    [1] = { think = 40, attackAt = 7000, grow = 1.15, infiltrate = false, defenses = 2, maxHarv = 2, research = false },
    [2] = { think = 20, attackAt = 4500, grow = 1.1,  infiltrate = true,  defenses = 4, maxHarv = 4, research = true },
    [3] = { think = 10, attackAt = 3500, grow = 1.08, infiltrate = true,  defenses = 6, maxHarv = 6, research = true },
}

function A.reset() brains = {} end

local function count(S, p, type, built)
    local n = 0
    for _, o in ipairs(S.objs) do
        if o.alive and o.owner == p and o.type == type and (not built or o.cat ~= "bld" or o.built >= 1) then n = n + 1 end
    end
    return n
end

local function first(S, p, type)
    for _, o in ipairs(S.objs) do
        if o.alive and o.owner == p and o.type == type and (o.cat ~= "bld" or o.built >= 1) then return o end
    end
end

local function queued(b, type)
    for _, q in ipairs({ b.queue, b.queue2 }) do
        for _, it in ipairs(q) do if it.type == type then return true end end
    end
    return false
end

local function cost(type) local d = D.units[type] or D.buildings[type]; return d.cost end

-- Where the enemy is (their first building, else their start).
local function enemyHome(S, p, b)
    local best, bd = nil, 1e18
    for _, o in ipairs(S.objs) do
        if o.alive and o.cat == "bld" and S.enemies(p, o.owner) and o.type ~= "wall" then
            local d = U.dist2(b.homeX or 0, b.homeZ or 0, o.x, o.z)
            if d < bd then best, bd = o, d end
        end
    end
    if best then return best.x, best.z, best end
    for q = 0, S.nPlayers - 1 do
        local pq = S.players[q]
        if S.enemies(p, q) and pq.alive and pq.startX then return pq.startX, pq.startZ end
    end
    return 0, 0
end

-- A spot for a building near home, a corridor around it kept free.
local function findSpot(S, p, type, towardX, towardZ, rnd)
    local bd = D.buildings[type]
    local w, h = bd.size[1], bd.size[2]
    local me = S.players[p]
    local base = first(S, p, "base")
    if not base then return nil end
    local ci, cj = M.cellOf(base.x, base.z)
    local dirX, dirZ = 0, 0
    if towardX then
        local dx, dz = towardX - base.x, towardZ - base.z
        local l = sqrt(dx * dx + dz * dz)
        if l > 1 then dirX, dirZ = dx / l, dz / l end
    end
    local best, bscore = nil, 1e18
    local tries = 0
    for r = 4, 22, 1 do
        for k = 0, 15 do
            local a = (k / 16) * math.pi * 2 + rnd() * 0.2
            local i = floor(ci + math.sin(a) * r - w / 2)
            local j = floor(cj + math.cos(a) * r - h / 2)
            tries = tries + 1
            -- a ring of free cells around it, so units can still pass
            if M.canBuild(i - 1, j - 1, w + 2, h + 2) then
                local score = r
                if towardX then
                    local ax, az = math.sin(a), math.cos(a)
                    score = r - (ax * dirX + az * dirZ) * 6
                end
                if score < bscore then best, bscore = { i, j }, score end
            end
        end
        if best and r > 8 then break end
    end
    return best
end

-- What a commander's plan can ask for (sw/agent.lua fills it; every field is
-- optional, a missing one leaves that part to the level's rules):
--   build      { building, ... }  wanted next, in order (nil: decide yourself,
--                                  {}: nothing beyond the essentials)
--   harvesters n                   how many to keep
--   towers     n                   how many defence towers
--   research   key | "keine"      first in the lab
--   mix        name               the army's make-up (MIX below)
--   stance     "sammeln" | "verteidigen" | "angreifen" | "ueberfall" | "alles_rein"
--   minUnits   n                   attack once this many stand ready
--   spend      "wirtschaft" | "ausgewogen" | "heer"
--   steward    true               the player's own base while they drive a unit
--                                  (sw/steward.lua): no construction vehicle, no
--                                  attacks -- only idle units near home defend it
local MIX = {
    ausgewogen = { f = { tank = 5, eliminator = 2.5, terminator = 1, hypercopter = 1 },
                   b = { soldier = 5, rocketeer = 4, infiltrator = 1 }, inf = 8 },
    panzer     = { f = { tank = 8, eliminator = 2 }, b = { soldier = 6, rocketeer = 4 }, inf = 4 },
    schwer     = { f = { eliminator = 5, terminator = 4, tank = 1 }, b = { rocketeer = 1 }, inf = 3 },
    infanterie = { f = { tank = 2, eliminator = 1 }, b = { soldier = 5, rocketeer = 4, infiltrator = 1 }, inf = 18 },
    flugabwehr = { f = { tank = 5, hypercopter = 1 }, b = { rocketeer = 8, soldier = 2 }, inf = 12 },
    luft       = { f = { hypercopter = 4, terminator = 4, tank = 2 }, b = { rocketeer = 1 }, inf = 4 },
}
A.MIX = MIX

-- A weighted pick among what can be built now.
local function pickFrom(S, p, w, r)
    local total, keys = 0, {}
    for _, k in ipairs({ "tank", "eliminator", "terminator", "hypercopter", "soldier", "rocketeer", "infiltrator" }) do
        if w[k] and S.canProduce(p, k) then total = total + w[k]; keys[#keys + 1] = k end
    end
    if total <= 0 then return nil end
    local x = r * total
    for _, k in ipairs(keys) do
        x = x - w[k]
        if x <= 0 then return k end
    end
    return keys[#keys]
end

local function think(S, p, b, ctx)
    local L = ctx.L
    local P = ctx.plan or {}
    local me = S.players[p]
    local order, rnd = ctx.order, ctx.rnd

    -- 1. no base? deploy the construction vehicle
    local base = first(S, p, "base")
    if not base then
        -- where the player's base goes is the player's to say
        if P.steward then return end
        local mcv = first(S, p, "mcv")
        if mcv and #mcv.orders == 0 then
            if b.deployTries and b.deployTries > 0 then
                -- the last spot would not do: drive a little and try again
                local a = rnd() * math.pi * 2
                order(string.format("mv %d %d %d 0", mcv.id, floor((mcv.x + math.sin(a) * 30) * 10), floor((mcv.z + math.cos(a) * 30) * 10)))
                b.deployTries = 0
            else
                order("dp " .. mcv.id)
                b.deployTries = (b.deployTries or 0) + 1
            end
        end
        return
    end
    b.homeX, b.homeZ = base.x, base.z
    local ex, ez, enemyBld = ctx.target(S, p, b)

    -- 2. place what is ready
    local item = base.queue[1]
    if item and item.done then
        local tx, tz = nil, nil
        if D.buildings[item.type].defense then tx, tz = ex, ez end
        if item.type == "refinery" or item.type == "silo" then
            -- next to the Energicum, so the harvesters drive less
            local best, bd = nil, 1e18
            for _, c in ipairs(S.crystals) do
                if c.alive and c.amount > 0 then
                    local d = U.dist2(base.x, base.z, c.x, c.z)
                    if d < bd then best, bd = c, d end
                end
            end
            if best then tx, tz = best.x, best.z end
        end
        local spot = findSpot(S, p, item.type, tx, tz, rnd)
        if spot then order(string.format("pl %s %d %d", item.type, spot[1], spot[2]))
        else order("cn " .. base.id .. " 1 1") end
        return
    end

    local maxHarv = P.harvesters or L.maxHarv
    local maxDef = P.towers or L.defenses

    -- 3. what to build next
    if #base.queue == 0 then
        local want
        local h = me.has
        local plants = count(S, p, "powerplant")
        local power, use = me.power, me.use
        local nRef = count(S, p, "refinery")
        -- the essentials come first, whatever a plan says
        if plants == 0 then want = "powerplant"
        elseif nRef == 0 then want = "refinery"
        elseif use + 50 > power then want = "powerplant"
        elseif P.build then
            for k, t in ipairs(P.build) do
                if S.canProduce(p, t) then want = t; b.fromPlan = k; break end
            end
        elseif count(S, p, "factory") == 0 then want = "factory"
        elseif count(S, p, "radar") == 0 then want = "radar"
        elseif nRef < 2 and me.cells > 1800 then want = "refinery"
        elseif me.raw > me.rawCap * 0.8 and count(S, p, "silo") < 2 then want = "silo"
        elseif count(S, p, "rocket_tower") + count(S, p, "laser_tower") + count(S, p, "watchtower") < maxDef
            and me.cells > 1000 then
            local t = count(S, p, "watchtower") == 0 and "watchtower" or
                      ((h.lab and count(S, p, "laser_tower") < count(S, p, "rocket_tower")) and "laser_tower" or "rocket_tower")
            want = t
        elseif count(S, p, "lab") == 0 and me.cells > 1600 then want = "lab"
        elseif count(S, p, "hangar") == 0 and h.lab and me.cells > 2500 then want = "hangar"
        elseif count(S, p, "factory") < 2 and me.cells > 6000 then want = "factory"
        end
        b.saving = 0
        if want and b.harvFirst and want ~= "powerplant" and want ~= "refinery" then want = nil end
        if want and S.canProduce(p, want) then
            if me.cells >= cost(want) then
                order("pr " .. base.id .. " " .. want)
                -- a planned building is done with once it is ordered
                if b.fromPlan and P.build and P.build[b.fromPlan] == want then table.remove(P.build, b.fromPlan) end
            else b.saving = cost(want) end
        end
        b.fromPlan = nil
    end
    local reserve = (#base.queue == 0) and (b.saving or 0) or 0
    if P.spend == "heer" then reserve = 0 end
    -- the economy first: a factory without its harvesters saves for them
    local wantHarv = math.min(maxHarv, count(S, p, "refinery") * (P.harvesters and 3 or 2))
    if count(S, p, "factory") > 0 and count(S, p, "harvester") < wantHarv and me.power >= me.use then
        reserve = math.max(reserve, cost("harvester"))
        b.harvFirst = true
    else
        b.harvFirst = false
    end
    if P.spend == "wirtschaft" then reserve = reserve + 500 end

    -- 4. units
    local harv = count(S, p, "harvester")
    local nRef = count(S, p, "refinery")
    local mix = P.mix and MIX[P.mix]
    for _, f in ipairs(S.objs) do
        if f.alive and f.owner == p and f.cat == "bld" and f.built >= 1 and #f.queue2 < 2 then
            if f.type == "factory" then
                local pick
                if harv < min(maxHarv, nRef * (P.harvesters and 3 or 2)) and not queued(f, "harvester") then pick = "harvester"
                elseif mix then pick = pickFrom(S, p, mix.f, rnd()) or "tank"
                else
                    local r = rnd()
                    if S.canProduce(p, "terminator") and r < 0.12 then pick = "terminator"
                    elseif S.canProduce(p, "eliminator") and r < 0.35 then pick = "eliminator"
                    elseif S.canProduce(p, "hypercopter") and r < 0.42 and count(S, p, "hypercopter") < 2 then pick = "hypercopter"
                    else pick = "tank" end
                end
                if pick == "hypercopter" and count(S, p, "hypercopter") >= (mix and 6 or 2) then pick = "tank" end
                if pick then
                    local need = cost(pick) + ((pick == "harvester") and 0 or reserve)
                    if S.canProduce(p, pick) and me.cells >= need then
                        order("pr " .. f.id .. " " .. pick)
                    end
                end
            elseif f.type == "base" then
                local pick
                local r = rnd()
                if count(S, p, "engineer") < 1 then pick = "engineer"
                elseif mix then
                    pick = pickFrom(S, p, mix.b, r) or "soldier"
                    if pick == "infiltrator" and count(S, p, "infiltrator") >= 2 then pick = "soldier" end
                elseif L.infiltrate and S.canProduce(p, "infiltrator") and count(S, p, "infiltrator") < 1 and r < 0.3 then pick = "infiltrator"
                elseif S.canProduce(p, "rocketeer") and r < 0.45 then pick = "rocketeer"
                else pick = "soldier" end
                local infantry = count(S, p, "soldier") + count(S, p, "rocketeer")
                local cap = mix and (mix.inf + 2 * (b.waves or 0)) or (6 + 2 * (b.waves or 0))
                if pick and infantry < cap and S.canProduce(p, pick) and me.cells >= cost(pick) + reserve + 200 then
                    order("pr " .. f.id .. " " .. pick)
                end
            end
        end
    end

    -- 5. research and upgrades
    if L.research and P.research ~= "keine" then
        local lab = first(S, p, "lab")
        if lab and not lab.research and me.cells > 2500 then
            local list = { "weapons1", "plating1", "flight", "base_armor", "weapons2", "plating2",
                           "rocket_tower_ext", "laser_tower_armor", "refinery_ext", "powerplant_ext" }
            if P.research then table.insert(list, 1, P.research) end
            for _, key in ipairs(list) do
                local r = D.researchByKey[key]
                if r and not me.techs[key] and (not r.after or me.techs[r.after]) then
                    order("rs " .. lab.id .. " " .. key)
                    break
                end
            end
        end
        if me.cells > 4000 and S.tick % 200 < L.think then
            for _, o in ipairs(S.objs) do
                if o.alive and o.owner == p and o.cat == "bld" and o.built >= 1 and not o.upgrading then
                    if me.techs[o.type .. "_armor"] and not o.armor then order("up " .. o.id .. " armor"); break end
                    if me.techs[o.type .. "_ext"] and not o.ext then order("up " .. o.id .. " ext"); break end
                end
            end
        end
    end

    -- 6. the army
    local idle, value = {}, 0
    for _, o in ipairs(S.objs) do
        -- a unit steered by hand (o.ctl) is not the brain's
        if o.alive and o.owner == p and o.cat == "unit" and not o.inside and S.weaponOf(o) and not o.def.harvest
            and not o.ctl and not (P.steward and U.dist2(o.x, o.z, base.x, base.z) > 160 * 160) then
            value = value + o.def.cost
            local ord = o.orders[1]
            if not ord or ord.k == "guard" or (ord.k == "move" and ord.rally) then idle[#idle + 1] = o end
        end
    end
    b.attackAt = b.attackAt or L.attackAt
    -- defend: an enemy near home pulls the idle ones
    local threat = nil
    S.query(base.x, base.z, 120, function(t)
        if t.cat == "unit" and S.enemies(p, t.owner) and not t.inside then threat = t; return true end
    end)
    if threat and #idle > 0 then
        order(string.format("am %s %d %d 0", S.encodeIds(idle), floor(threat.x * 10), floor(threat.z * 10)))
        return
    end
    -- the player's army is the player's: where it stands, it stays
    if P.steward then return end
    local stance = P.stance
    local attacking = stance == nil or stance == "angreifen" or stance == "alles_rein" or stance == "ueberfall"
    -- ones that stand idle out in the field press on to the next target
    local home2 = {}
    for _, o in ipairs(idle) do
        if U.dist2(o.x, o.z, ex, ez) < U.dist2(o.x, o.z, base.x, base.z) then home2[#home2 + 1] = o end
    end
    if #home2 > 0 and #home2 == #idle then
        if attacking then
            order(string.format("am %s %d %d 0", S.encodeIds(home2), floor(ex * 10), floor(ez * 10)))
        else
            order(string.format("mv %s %d %d 0", S.encodeIds(home2), floor(base.x * 10), floor(base.z * 10)))
        end
        return
    end
    local go
    if stance == nil then go = value >= b.attackAt and #idle >= 4
    elseif stance == "angreifen" then go = #idle >= (P.minUnits or 6)
    elseif stance == "alles_rein" then go = #idle >= 1
    end
    if stance == "ueberfall" and #idle >= 2 and S.tick - (b.raidAt or -1e9) > 600 then
        -- the fastest few go for the target; the rest stays to gather
        table.sort(idle, function(u, v) return (u.def.flySpeed or u.def.speed) > (v.def.flySpeed or v.def.speed) end)
        local raid = {}
        for k = 1, min(6, #idle - 1 + (#idle == 2 and 1 or 0)) do raid[#raid + 1] = idle[k] end
        order(string.format("am %s %d %d 0", S.encodeIds(raid), floor(ex * 10), floor(ez * 10)))
        b.raidAt = S.tick
        b.waves = (b.waves or 0) + 1
    elseif go then
        local tx, tz = ex, ez
        order(string.format("am %s %d %d 0", S.encodeIds(idle), floor(tx * 10), floor(tz * 10)))
        if stance == nil then b.attackAt = floor(b.attackAt * L.grow) end
        b.waves = (b.waves or 0) + 1
    elseif #idle > 0 and S.tick % 200 < L.think then
        -- gather in front of the base, toward the enemy (defenders stay close)
        local dx, dz = ex - base.x, ez - base.z
        local l = max(1, sqrt(dx * dx + dz * dz))
        local reach = (stance == "verteidigen") and 30 or 60
        local gx, gz = base.x + dx / l * reach, base.z + dz / l * reach
        local list = {}
        for _, o in ipairs(idle) do
            if U.dist(o.x, o.z, gx, gz) > 30 then list[#list + 1] = o end
        end
        if #list > 0 then order(string.format("mv %s %d %d 0", S.encodeIds(list), floor(gx * 10), floor(gz * 10))) end
    end
    -- infiltrators go for the enemy's best building
    if enemyBld then
        for _, o in ipairs(S.objs) do
            if o.alive and o.owner == p and o.type == "infiltrator" and #o.orders == 0 then
                order("cp " .. o.id .. " " .. enemyBld.id)
            end
        end
    end
end

-- A brain run from outside the simulation (sw/agent.lua): ctx.order sends the
-- line, ctx.rnd gives 0..1, ctx.target(S, p, b) -> x, z, building, ctx.plan
-- the commander's wishes. ctx.L may name a level (default 3).
function A.thinkWith(S, p, b, ctx)
    ctx.L = LEVEL[ctx.level or 3]
    ctx.target = ctx.target or enemyHome
    think(S, p, b, ctx)
end
A.enemyHome = enemyHome
A.thinkTicks = function(level) return (LEVEL[level or 3] or LEVEL[3]).think end

-- Called by the simulation every step.
function A.install(S)
    S.aiThink = function()
        for p = 0, S.nPlayers - 1 do
            local pl = S.players[p]
            if pl.ai and pl.alive then
                local L = LEVEL[pl.aiLevel] or LEVEL[2]
                if (S.tick + p * 7) % L.think == 0 then
                    local b = brains[p]
                    if not b then
                        b = {}
                        brains[p] = b
                        b.ctx = { L = L, target = enemyHome,
                                  order = function(line) S.apply(p, line) end,
                                  rnd = function() return S.rng:float() end }
                    end
                    b.ctx.L = L
                    think(S, p, b, b.ctx)
                end
            end
        end
    end
end

return A
