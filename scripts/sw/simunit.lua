-- STEELWARS -- units on the move: orders, paths, steering, harvesting,
-- transport, capture, repair, deployment. Part of the deterministic
-- simulation (see sim.lua for the rules that come with that).
local D = require("sw.defs")
local U = require("sw.util")
local M = require("sw.map")

return function(S)

local floor, sqrt, abs, min, max, sin, cos = math.floor, math.sqrt, math.abs, math.min, math.max, math.sin, math.cos
local DT = D.TICK

-- --- Buckets: who is near whom ---------------------------------------------------
local BS = 32
local buckets, bucketN = {}, {}

function S.buildBuckets()
    local BW = floor(M.size / BS) + 1
    S.BW = BW
    for k = 1, BW * BW do bucketN[k] = 0 end
    for _, o in ipairs(S.objs) do
        if o.alive and (o.cat == "unit" or o.cat == "bld") and not o.inside then
            local bi = U.clamp(floor((o.x - M.x0) / BS), 0, BW - 1)
            local bj = U.clamp(floor((o.z - M.z0) / BS), 0, BW - 1)
            local k = bj * BW + bi + 1
            local n = bucketN[k] + 1
            bucketN[k] = n
            local b = buckets[k]
            if not b then b = {}; buckets[k] = b end
            b[n] = o
        end
    end
end

-- Call fn(o) for every unit/building whose centre is within r (+ its radius)
-- of (x, z). In bucket order, which is deterministic.
function S.query(x, z, r, fn)
    local BW = S.BW
    local reach = r + 16
    local i0 = U.clamp(floor((x - reach - M.x0) / BS), 0, BW - 1)
    local i1 = U.clamp(floor((x + reach - M.x0) / BS), 0, BW - 1)
    local j0 = U.clamp(floor((z - reach - M.z0) / BS), 0, BW - 1)
    local j1 = U.clamp(floor((z + reach - M.z0) / BS), 0, BW - 1)
    for bj = j0, j1 do
        for bi = i0, i1 do
            local k = bj * BW + bi + 1
            local b = buckets[k]
            for n = 1, bucketN[k] do
                local o = b[n]
                if o.alive then
                    local dx, dz = o.x - x, o.z - z
                    local rr = r + o.radius
                    if dx * dx + dz * dz <= rr * rr then
                        if fn(o) then return end
                    end
                end
            end
        end
    end
end

-- --- Orders --------------------------------------------------------------------
function S.setPath(o, x, z)
    o.goalX, o.goalZ = x, z
    if o.air or o.flying then
        o.path, o.pi = { x, z }, 1
        return true
    end
    local p = M.findPath(o.x, o.z, x, z)
    if not p then o.path = nil; return false end
    o.path, o.pi = p, 1
    o.stuck, o.progX, o.progZ, o.progT = 0, o.x, o.z, S.tick
    return true
end

function S.orderMove(o, x, z, queue)
    x, z = M.clampPos(x, z)
    local ord = { k = "move", x = x, z = z }
    if queue then
        o.orders[#o.orders + 1] = ord
    else
        o.orders = { ord }
        o.target = 0
        o.path = nil
    end
end

function S.stop(o)
    o.orders = {}
    o.path = nil
    o.target = 0
    o.moving = false
end

-- --- Steering ------------------------------------------------------------------
local function separate(o)
    local r = o.radius
    local pushX, pushZ = 0, 0
    S.query(o.x, o.z, r + 1, function(u)
        if u ~= o and u.cat == "unit" and not u.air and not u.flying and not u.inside then
            local dx, dz = o.x - u.x, o.z - u.z
            local d2 = dx * dx + dz * dz
            local rr = (r + u.radius) * 0.9
            if d2 < rr * rr then
                local d = sqrt(d2)
                if d < 0.01 then
                    -- exactly on top: separate by id so both agree
                    dx, dz, d = (o.id < u.id) and 1 or -1, 0.3, 1
                end
                local f = (rr - d) / rr
                -- the one that is standing gives way to the one that is driving
                local w = u.moving and not o.moving and 1.0 or 0.5
                pushX = pushX + dx / d * f * w
                pushZ = pushZ + dz / d * f * w
            end
        end
    end)
    if pushX ~= 0 or pushZ ~= 0 then
        local s = min(1.5, sqrt(pushX * pushX + pushZ * pushZ)) * 3.0 * DT
        local l = sqrt(pushX * pushX + pushZ * pushZ)
        local nx, nz = o.x + pushX / l * s, o.z + pushZ / l * s
        if M.walkableAt(nx, nz) then o.x, o.z = nx, nz end
    end
end

-- Move toward the end of the current path. Returns true on arrival.
local function follow(o, arriveDist)
    local p = o.path
    if not p or #p == 0 then return true end
    local d = o.def
    local last = #p // 2
    if o.pi > last then return true end
    local wx, wz = p[2 * o.pi - 1], p[2 * o.pi]
    local dx, dz = wx - o.x, wz - o.z
    local dist = sqrt(dx * dx + dz * dz)
    local final = (o.pi == last)
    local reach = final and (arriveDist or max(0.6, o.radius * 0.5)) or max(1.6, o.radius * 0.8)
    if dist <= reach then
        o.pi = o.pi + 1
        if o.pi > last then o.moving = false; return true end
        return false
    end
    o.moving = true
    local want = U.heading(dx, dz)
    local speed = d.speed
    if o.flying and d.flySpeed then speed = d.flySpeed end
    if o.cat == "unit" and o.owner >= 0 and o.def.vehicle then
        -- climbing costs speed
        local i, j = M.cellOf(o.x, o.z)
        if M.inside(i, j) then speed = speed * (1 - min(0.5, M.slope[M.index(i, j)] * 0.8)) end
    end
    local step
    if d.infantry or o.air or o.flying then
        o.h = U.turnTo(o.h, want, (d.turn or 6) * DT)
        step = min(dist, speed * DT)
        local nx, nz = o.x + dx / dist * step, o.z + dz / dist * step
        if o.air or o.flying or M.walkableAt(nx, nz) then
            o.x, o.z = nx, nz
        elseif M.walkableAt(nx, o.z) then o.x = nx
        elseif M.walkableAt(o.x, nz) then o.z = nz end
    else
        local diff = abs(U.angDiff(o.h, want))
        o.h = U.turnTo(o.h, want, d.turn * DT)
        local f = (diff > 1.2) and 0.08 or max(0.15, cos(diff))
        step = min(dist, speed * f * DT)
        local nx, nz = o.x + sin(o.h) * step, o.z + cos(o.h) * step
        if M.walkableAt(nx, nz) then o.x, o.z = nx, nz
        elseif M.walkableAt(nx, o.z) then o.x = nx
        elseif M.walkableAt(o.x, nz) then o.z = nz end
    end
    -- not getting anywhere? find another way
    if not (o.air or o.flying) and S.tick - (o.progT or 0) >= 30 then
        local moved = U.dist(o.x, o.z, o.progX or o.x, o.progZ or o.z)
        o.progX, o.progZ, o.progT = o.x, o.z, S.tick
        if moved < 1.0 then
            o.stuck = (o.stuck or 0) + 1
            if o.stuck >= 4 then
                o.path = nil
                o.moving = false
                return true     -- give up this leg
            end
            local p2 = M.findPath(o.x, o.z, p[#p - 1], p[#p])
            if p2 and #p2 > 0 then o.path, o.pi = p2, 1 end
        else
            o.stuck = 0
        end
    end
    return false
end
S.follow = follow

local function goTo(o, x, z, arrive)
    if not o.path or o.goalX ~= x or o.goalZ ~= z then
        if not S.setPath(o, x, z) then return true end
    end
    return follow(o, arrive)
end

-- Distance from unit o to the edge of object t.
local function edgeDist(o, t)
    return U.dist(o.x, o.z, t.x, t.z) - t.radius
end
S.edgeDist = edgeDist

-- A point next to object t, on o's side of it (for walking up to a building).
local function besideOf(o, t)
    local dx, dz = o.x - t.x, o.z - t.z
    local d = sqrt(dx * dx + dz * dz)
    if d < 0.01 then dx, dz, d = 0, 1, 1 end
    local r = t.radius + o.radius + 1.5
    local x, z = t.x + dx / d * r, t.z + dz / d * r
    if not M.walkableAt(x, z) then
        local i, j = M.nearestWalkable(x, z, 10)
        if i then x, z = M.center(i, j) end
    end
    return x, z
end

-- --- Harvesting ---------------------------------------------------------------
local function nearestCrystal(o)
    local best, bd = nil, 1e18
    for _, c in ipairs(S.crystals) do
        if c.alive and c.amount > 60 then
            local d = U.dist2(o.x, o.z, c.x, c.z)
            -- crowded crystals look further away
            d = d + (c.claims or 0) * 900
            if d < bd then best, bd = c, d end
        end
    end
    return best
end

local function nearestRefinery(o)
    local best, bd = nil, 1e18
    for _, b in ipairs(S.objs) do
        if b.alive and b.cat == "bld" and b.type == "refinery" and b.owner == o.owner and b.built >= 1 then
            local d = U.dist2(o.x, o.z, b.x, b.z)
            if d < bd then best, bd = b, d end
        end
    end
    return best
end

-- Whatever refinery dock o was holding is free again (o was taken off its
-- harvesting by hand, and would otherwise keep the others waiting).
function S.releaseDock(o)
    for _, b in ipairs(S.objs) do
        if b.alive and b.cat == "bld" and b.dockUser == o.id then b.dockUser = 0 end
    end
end

function S.dockPoint(r)
    return r.x, M.z0 + (r.j + r.hgt) * D.CELL + 3.5
end

local function harvest(o, ord)
    local cap = o.def.harvest.cap
    local st = ord.st or "seek"
    local pl = S.players[o.owner]
    if st == "seek" then
        if o.carry >= cap * 0.98 then ord.st = "return"; return end
        local c = (ord.id ~= 0) and S.get(ord.id) or nil
        if not c or c.amount <= 0 then c = nearestCrystal(o) end
        if not c then
            if o.carry > 0 then ord.st = "return" else ord.idle = true end
            return
        end
        ord.id = c.id
        c.claims = (c.claims or 0) + 1
        ord.claimed = c.id
        ord.st = "go"
        o.path = nil
    elseif st == "go" then
        local c = S.get(ord.id)
        if not c or c.amount <= 0 then
            if ord.claimed then local cc = S.byId[ord.claimed]; if cc then cc.claims = max(0, (cc.claims or 1) - 1) end end
            ord.claimed = nil
            ord.st, ord.id = "seek", 0
            return
        end
        if goTo(o, c.x, c.z, 3.5) or U.dist(o.x, o.z, c.x, c.z) < 4.5 then
            ord.st = "mine"
            o.path = nil
            o.moving = false
        end
    elseif st == "mine" then
        local c = S.get(ord.id)
        if not c or c.amount <= 0 then
            ord.st = (o.carry > cap * 0.6) and "return" or "seek"
            ord.id = 0
            return
        end
        o.h = U.turnTo(o.h, U.heading(c.x - o.x, c.z - o.z), o.def.turn * DT)
        local amt = min(o.def.harvest.rate * DT, c.amount, cap - o.carry)
        o.carry = o.carry + amt
        c.amount = c.amount - amt
        o.mining = S.tick
        if c.amount <= 0 then c.amount = 0 end
        if o.carry >= cap - 0.01 then
            if ord.claimed then local cc = S.byId[ord.claimed]; if cc then cc.claims = max(0, (cc.claims or 1) - 1) end end
            ord.claimed = nil
            ord.st = "return"
        end
    elseif st == "return" then
        local r = (ord.ref and S.get(ord.ref)) or nearestRefinery(o)
        if not r or r.owner ~= o.owner then
            ord.ref = nil
            ord.idle = true
            return
        end
        ord.ref = r.id
        ord.idle = false
        local dx, dz = S.dockPoint(r)
        if goTo(o, dx, dz, 2.0) or U.dist(o.x, o.z, dx, dz) < 3 then
            if r.dockUser and r.dockUser ~= o.id and S.get(r.dockUser) then
                return   -- someone is unloading; wait our turn
            end
            r.dockUser = o.id
            ord.st = "dock"
            ord.t = 0
            o.path = nil
        end
    elseif st == "dock" then
        local r = S.get(ord.ref or 0)
        if not r then ord.st = "return"; return end
        o.h = U.turnTo(o.h, math.pi, o.def.turn * DT)   -- back in, nose out
        ord.t = ord.t + DT
        if ord.t >= D.REFINERY_DOCK_TIME then
            local room = pl.rawCap - pl.raw
            if room <= 0 then
                if not ord.warned then S.msg(o.owner, "Energicum-Lager voll -- Silo bauen", "storage"); ord.warned = true end
                return
            end
            local put = min(room, o.carry)
            pl.raw = pl.raw + put
            pl.stats.harvested = pl.stats.harvested + put
            o.carry = o.carry - put
            if o.carry <= 0.01 then
                o.carry = 0
                r.dockUser = 0
                ord.st = "seek"
                ord.warned = false
                S.emit({ t = "unload", id = o.id, ref = r.id })
            end
        end
    end
end

-- --- Transport ------------------------------------------------------------------
local function cargoUsed(c)
    local n = 0
    for _, id in ipairs(c.cargo) do
        local u = S.byId[id]
        if u then n = n + (u.def.carry or 1) end
    end
    return n
end
S.cargoUsed = cargoUsed

local function board(u, c)
    if not c or not c.alive or c.owner ~= u.owner then return false end
    if cargoUsed(c) + (u.def.carry or 1) > c.def.transport then return false end
    -- only one vehicle hangs below a copter
    if not u.def.infantry then
        for _, id in ipairs(c.cargo) do
            local x = S.byId[id]
            if x and not x.def.infantry then return false end
        end
    end
    c.cargo[#c.cargo + 1] = u.id
    u.inside = c.id
    u.orders, u.path, u.target, u.moving = {}, nil, 0, false
    u.ctl, u.spd = nil, 0
    S.emit({ t = "board", id = u.id, by = c.id })
    return true
end
S.board = board

local function unloadAll(c)
    local n = 0
    for _, id in ipairs(c.cargo) do
        local u = S.byId[id]
        if u and u.alive then
            n = n + 1
            local a = n * 2.4
            local r = u.def.infantry and 4 or 7
            local x, z = c.x + sin(a) * r, c.z + cos(a) * r
            local i, j = M.nearestWalkable(x, z, 12)
            if i then x, z = M.center(i, j) end
            u.x, u.z, u.px, u.pz = x, z, x, z
            u.inside = nil
            u.h = a
            S.emit({ t = "unboard", id = u.id, by = c.id })
        end
    end
    c.cargo = {}
end

-- Air: fly to (x, z); `land` = touch down there. Returns true on arrival.
local function fly(o, x, z, land)
    local d = o.def
    local dx, dz = x - o.x, z - o.z
    local dist = sqrt(dx * dx + dz * dz)
    local speed = (o.flying and d.flySpeed) or d.speed
    local top = d.flyHeight or 22
    o.landed = false
    if dist > 1.0 then
        o.moving = true
        local want = U.heading(dx, dz)
        o.h = U.turnTo(o.h, want, (d.turn or 3) * DT)
        local f = max(0.2, cos(U.angDiff(o.h, want)))
        local step = min(dist, speed * f * DT)
        if dist < 30 then step = min(step, max(2, dist * 0.6) * speed / 30 * DT * 3) end
        o.x, o.z = o.x + dx / dist * step, o.z + dz / dist * step
        o.y = min(top, o.y + 10 * DT)
        return false
    end
    o.moving = false
    if land then
        o.y = max(0.5, o.y - 9 * DT)
        if o.y <= 0.5 then o.landed = true; return true end
        return false
    end
    o.y = min(top, o.y + 10 * DT)
    return true
end
S.fly = fly

-- --- Repair at a depot ---------------------------------------------------------
-- The nearest own finished building that mends units (defs: depot = true).
function S.nearestDepot(o)
    local best, bd = nil, math.huge
    for _, b in ipairs(S.objs) do
        if b.alive and b.cat == "bld" and b.owner == o.owner and b.built >= 1 and b.def.depot then
            local dd = U.dist2(o.x, o.z, b.x, b.z)
            if dd < bd then best, bd = b, dd end
        end
    end
    return best
end

-- What mending o completely would cost now.
function S.repairCost(o)
    if o.hp >= o.maxhp then return 0 end
    return (o.maxhp - o.hp) / o.maxhp * (o.def.cost or 0) * D.DEPOT_PRICE
end

-- --- Ownership change (capture) -------------------------------------------------
function S.transfer(o, newOwner)
    local old = o.owner
    o.owner = newOwner
    o.target = 0
    o.ctl, o.spd = nil, 0       -- whoever drove it does not any more
    if o.cat == "unit" then
        o.orders, o.path = {}, nil
    else
        o.queue, o.queue2, o.research, o.upgrading, o.rally = {}, {}, nil, nil, nil
        if o.type == "base" and S.players[old] then S.players[old].baseCaptured = true end
    end
    S.emit({ t = "captured", id = o.id, from = old, to = newOwner })
    S.msg(newOwner, (o.def.name or o.type) .. " übernommen", "captured")
    S.msg(old, (o.def.name or o.type) .. " wurde übernommen!", "lost")
end

-- --- Per-unit update ---------------------------------------------------------------
local function idle(o)
    local d = o.def
    if d.harvest and o.owner >= 0 then
        o.orders = { { k = "harvest", id = 0, st = (o.carry > 0) and "return" or "seek" } }
        return
    end
    if d.repair then
        -- engineers look after what is near
        local best, bd = nil, 30 * 30
        S.query(o.x, o.z, 30, function(t)
            if t.owner == o.owner and t ~= o and t.hp < t.maxhp and (t.cat == "bld" and t.built >= 1 or (t.cat == "unit" and not t.air and not t.flying and not t.inside)) then
                local dd = U.dist2(o.x, o.z, t.x, t.z)
                if dd < bd then best, bd = t, dd end
            end
        end)
        if best then o.orders = { { k = "repair", id = best.id, auto = true } } end
        return
    end
    if o.air and o.pad then
        local hg = S.get(o.pad)
        if hg and hg.owner == o.owner then
            local px, pz = S.padPos(hg, o.padK)
            if fly(o, px, pz, true) and hg.ext and o.hp < o.maxhp then
                o.hp = min(o.maxhp, o.hp + D.extend.hangar.repair * DT)
            end
            return
        end
        o.pad = nil
    end
    if o.air and not o.pad then
        -- find a free pad, else hover where it is
        local hg, k = S.freePad(o.owner)
        if hg then hg.padUser[k] = o.id; o.pad, o.padK = hg.id, k end
        if not o.landed then o.moving = false end
    end
end

-- --- Driven by hand ----------------------------------------------------------------
-- A unit its player steers by hand (sw/drive.lua): o.ctl = { thr, steer, ax,
-- az, fire }, set by the order "dc" and kept until the next one. Throttle and
-- steering are -1, 0 or 1 (steer 1 = right); the speed follows the throttle
-- with some inertia, backwards at half of it. Aiming and firing are combat's.
local TWO_PI = 2 * math.pi

-- A vehicle on the ground rolls over the trees under its hull: every forest
-- cell its body reaches at (x, z) opens, and each felled cell costs it a
-- little speed.
local function fell(o, x, z)
    local r = o.radius * 0.8
    local i0, j0 = M.cellOf(x - r, z - r)
    local i1, j1 = M.cellOf(x + r, z + r)
    local half = D.CELL * 0.5
    local felled
    for j = j0, j1 do
        for i = i0, i1 do
            -- the cell's nearest point to the hull's centre
            local cx, cz = M.center(i, j)
            local qx = max(cx - half, min(x, cx + half))
            local qz = max(cz - half, min(z, cz + half))
            if (qx - x) ^ 2 + (qz - z) ^ 2 <= r * r then
                local t = M.fellTrees(i, j)
                if t then
                    felled = felled or {}
                    for k = 1, #t do felled[#felled + 1] = t[k] end
                    o.spd = (o.spd or 0) * 0.85
                end
            end
        end
    end
    if felled then S.emit({ t = "fell", x = x, z = z, h = o.h, back = (o.spd or 0) < 0, trees = felled }) end
end

local function drive(o)
    local d, c = o.def, o.ctl
    local air = o.air or o.flying
    local top = d.speed
    if o.flying and d.flySpeed then top = d.flySpeed end
    if not air and d.vehicle then
        -- climbing costs speed, as on a path
        local i, j = M.cellOf(o.x, o.z)
        if M.inside(i, j) then top = top * (1 - min(0.5, M.slope[M.index(i, j)] * 0.8)) end
    end
    local want = c.thr * top
    if c.thr < 0 then want = want * 0.5 end
    local acc = top * 1.5 * DT
    local spd = o.spd or 0
    if spd < want then spd = min(want, spd + acc)
    elseif spd > want then spd = max(want, spd - acc * 1.5) end
    -- as fast as the unit turns, but no faster than a hand can follow
    local rate = min(d.turn or 2, 2.4)
    if c.steer ~= 0 then
        o.h = o.h - c.steer * rate * DT
        o.h = (o.h + math.pi) % TWO_PI - math.pi
    end
    if o.air then
        o.landed = false
        o.y = min(d.flyHeight or 22, o.y + 10 * DT)
    end
    o.path = nil
    if abs(spd) < 0.02 then o.spd = 0; o.moving = false; return end
    o.spd = spd
    o.moving = true
    local step = spd * DT
    local nx, nz = o.x + sin(o.h) * step, o.z + cos(o.h) * step
    if not air and d.vehicle then fell(o, nx, nz) end
    if air or M.walkableAt(nx, nz) then o.x, o.z = nx, nz
    -- against something: slide along it, slower
    elseif M.walkableAt(nx, o.z) then o.x = nx; o.spd = spd * 0.6
    elseif M.walkableAt(o.x, nz) then o.z = nz; o.spd = spd * 0.6
    else o.spd = 0 end
end

function S.updateUnit(o)
    local d = o.def
    -- the Terminator rises and settles
    if d.canFly then
        if o.flyWant and o.y < d.flyHeight then
            o.y = min(d.flyHeight, o.y + 8 * DT)
        elseif not o.flyWant and o.y > 0 then
            o.y = max(0, o.y - 8 * DT)
        end
        o.flying = o.y > 2
    end
    -- in a driver's hands: only building up (MCV) and unloading (copter) are
    -- still done by the crew, everything else is the hand's
    if o.ctl then
        local od = o.orders[1]
        if not (od and (od.k == "deploy" or od.k == "unload")) then
            drive(o)
            if not o.air and not o.flying then separate(o) end
            return
        end
        o.spd = 0
    end
    local ord = o.orders[1]
    if not ord then idle(o); if not o.air and not o.flying then separate(o) end; return end
    local k = ord.k
    local done = false
    if k == "move" then
        if o.air or o.flying then done = fly(o, ord.x, ord.z, false)
        else done = goTo(o, ord.x, ord.z) end
    elseif k == "amove" then
        local t = S.get(o.target)
        if t and S.inRange and S.inRange(o, t) then
            o.moving = false
        else
            if o.air or o.flying then done = fly(o, ord.x, ord.z, false)
            else done = goTo(o, ord.x, ord.z) end
        end
    elseif k == "attack" then
        local t = S.get(ord.id)
        if not t or not S.enemies(o.owner, t.owner) and t.owner >= 0 then
            done = true
        else
            o.target = t.id
            if S.inRange(o, t) then
                o.moving = false
                o.path = nil
            else
                if o.air or o.flying then fly(o, t.x, t.z, false)
                elseif not o.path or U.dist(t.x, t.z, o.goalX or 0, o.goalZ or 0) > 8 or S.tick % 40 == o.id % 40 then
                    local x, z = besideOf(o, t)
                    S.setPath(o, x, z)
                    follow(o)
                else
                    follow(o)
                end
            end
        end
    elseif k == "harvest" then
        harvest(o, ord)
        if ord.idle then o.moving = false end
    elseif k == "repair" then
        local t = S.get(ord.id)
        if not t or t.hp >= t.maxhp or S.enemies(o.owner, t.owner) or t.owner < 0 then
            done = true
        elseif edgeDist(o, t) <= o.radius + 3 then
            o.moving = false
            o.path = nil
            local pl = S.players[o.owner]
            local amt = min(d.repair * DT, t.maxhp - t.hp)
            local price = amt * 0.12
            if pl.cells >= price then
                pl.cells = pl.cells - price
                t.hp = t.hp + amt
                o.repairing = S.tick
                t.healed = S.tick
                ord.at = t.id
            end
        else
            local x, z = ord.bx, ord.bz
            if not x then x, z = besideOf(o, t); ord.bx, ord.bz = x, z end
            if goTo(o, x, z) then ord.bx = nil end
        end
    elseif k == "service" then
        -- to a depot, stand beside it and be mended, paid by the hit point
        local b = S.get(ord.id)
        if not b or not b.alive or b.owner ~= o.owner then
            b = S.nearestDepot(o)       -- that one fell: the next
            if b then ord.id = b.id; ord.bx = nil end
        end
        if not b or o.hp >= o.maxhp then
            done = true
        elseif edgeDist(o, b) <= o.radius + 4 then
            local ready = true
            if o.air then ready = fly(o, o.x, o.z, true)
            else o.moving = false; o.path = nil end
            if ready then
                local pl = S.players[o.owner]
                local amt = min(D.DEPOT_RATE * DT, o.maxhp - o.hp)
                local price = amt / o.maxhp * (d.cost or 0) * D.DEPOT_PRICE
                if pl.cells >= price then
                    pl.cells = pl.cells - price
                    o.hp = o.hp + amt
                    o.healed = S.tick
                end
            end
        elseif o.air or o.flying then
            fly(o, b.x, b.z, false)
        else
            local x, z = ord.bx, ord.bz
            if not x then x, z = besideOf(o, b); ord.bx, ord.bz = x, z end
            if goTo(o, x, z) then
                -- there, or no way there: give up after a few tries
                ord.bx = nil
                ord.tries = (ord.tries or 0) + 1
                if ord.tries > 3 then done = true end
            end
        end
    elseif k == "capture" then
        local t = S.get(ord.id)
        if not t or not S.enemies(o.owner, t.owner) or t.flying then
            done = true
        elseif edgeDist(o, t) <= o.radius + 2.5 then
            o.moving = false
            ord.t = (ord.t or 0) + DT
            o.capturing = S.tick
            if ord.t >= d.capture then
                S.transfer(t, o.owner)
                S.remove(o, "spent")
                return
            end
        else
            local x, z = ord.bx, ord.bz
            if not x or S.tick % 40 == 0 then x, z = besideOf(o, t); ord.bx, ord.bz = x, z; o.path = nil end
            goTo(o, x, z)
        end
    elseif k == "board" then
        local c = S.get(ord.id)
        if not c then done = true
        elseif U.dist(o.x, o.z, c.x, c.z) <= c.radius + o.radius + 6 and c.landed then
            if not board(o, c) then done = true end
            return
        else
            local x, z = c.x, c.z
            if not ord.gx or U.dist(ord.gx, ord.gz, x, z) > 4 then ord.gx, ord.gz = x, z; o.path = nil end
            goTo(o, x, z, c.radius + o.radius)
        end
    elseif k == "pickup" then
        -- a copter lands by a unit and takes it in
        local u = S.get(ord.id)
        if not u or u.inside or u.owner ~= o.owner then done = true
        else
            if U.dist(o.x, o.z, u.x, u.z) > o.radius + u.radius + 4 then
                fly(o, u.x, u.z, false)
            else
                if fly(o, o.x, o.z, true) then
                    board(u, o)
                    done = true
                end
            end
        end
    elseif k == "wait" then
        -- a copter waits on the ground for the ones walking to it
        fly(o, ord.x or o.x, ord.z or o.z, true)
        ord.t = (ord.t or 0) + DT
        if ord.t > 25 then done = true end
    elseif k == "unload" then
        if fly(o, ord.x, ord.z, true) then
            unloadAll(o)
            done = true
        end
    elseif k == "deploy" then
        done = true
        S.deploy(o)
        if not o.alive then return end
    elseif k == "guard" then
        o.moving = false
    else
        done = true
    end
    if done then
        table.remove(o.orders, 1)
        o.path = nil
        o.moving = false
        if k == "attack" then o.target = 0 end
    end
    if not o.air and not o.flying then separate(o) end
end

function S.deploy(o)
    if not o.def.deploys then return false end
    local bd = D.buildings[o.def.deploys]
    local w, h = bd.size[1], bd.size[2]
    local i, j = M.cellOf(o.x - w * D.CELL * 0.5 + D.CELL * 0.5, o.z - h * D.CELL * 0.5 + D.CELL * 0.5)
    -- the vehicle itself is not in the way of itself
    local ok, why = M.canBuild(i, j, w, h)
    if not ok then
        S.msg(o.owner, "Hier kann nicht ausgebaut werden (" .. why .. ")", "error")
        return false
    end
    local owner = o.owner
    S.remove(o, "deployed")
    local b = S.addBuilding(o.def.deploys, owner, i, j, false)
    S.emit({ t = "deployed", id = b.id })
    -- whoever stood there steps aside
    S.query(b.x, b.z, b.radius, function(u)
        if u.cat == "unit" and not u.air then
            local a, c = M.nearestWalkable(u.x, u.z, 12)
            if a then u.x, u.z = M.center(a, c) end
        end
    end)
    return true
end

function S.updateUnits()
    for _, o in ipairs(S.objs) do
        if o.alive and o.cat == "unit" and not o.inside then
            S.updateUnit(o)
            if o.alive then
                o.x, o.z = M.clampPos(o.x, o.z)
                -- carried ones ride along
                if o.cargo and #o.cargo > 0 then
                    for _, id in ipairs(o.cargo) do
                        local u = S.byId[id]
                        if u then u.x, u.z, u.h = o.x, o.z, o.h end
                    end
                end
            end
        end
    end
end

end
