-- STEELWARS -- in the driver's seat: one of your units, steered by hand.
--
-- Select a single unit and press C (or "Steuern"): the camera drops in behind
-- it, W/S drive, A/D steer, the mouse aims and the left button fires; Q/E turn
-- the camera around the unit, the wheel brings it nearer or further, X does
-- what X always does (build up, fly, unload here). C or Esc gives the unit
-- back to its crew, who stop where it stands.
--
-- What the hands do reaches the simulation as orders like any click ("dc id
-- throttle steer aimX aimZ fire", see simcmd.lua), so a driven unit is the
-- same on every machine of a network game. A line goes out when the keys or
-- the trigger change, a moved aim at most ten times a second.
local U = require("sw.util")
local M = require("sw.map")
local S = require("sw.sim")
local V = require("sw.view")
local C = require("sw.camera")
local I = require("sw.ui")
local A = require("sw.audio")

local R = {}
local sin, cos, min, max, abs, floor, pi = math.sin, math.cos, math.min, math.max, math.abs, math.floor, math.pi

R.id = nil            -- the unit being driven
R.time = 0
local sent, sentKeys, sentT = nil, nil, -1
local camYaw = 0      -- the camera's turn around the unit (Q/E), on top of its heading
local camZoom = 1     -- the wheel
local yaw = 0         -- where the camera looks from (follows the hull with a lag)
local aimX, aimZ = 0, 0
local hasAim = false

local AMBER = { 1.0, 0.62, 0.12 }
local RED = { 1.0, 0.25, 0.18 }
local GREEN = { 0.35, 1.0, 0.45 }
local WHITE = { 0.92, 0.94, 0.96 }
local DIM = { 0.55, 0.6, 0.65 }
-- How far the driver sees enemies: the camera behind the unit looks far past
-- its sight (35 to 65 m), and what is on the road ahead should be there.
local EYE = 250

function R.active() return R.id ~= nil end

function R.canDrive(o)
    return o ~= nil and o.alive and o.cat == "unit" and o.owner == V.me and not o.inside
end

function R.enter(o)
    if not R.canDrive(o) then return end
    R.id = o.id
    sent, sentKeys = nil, nil
    camYaw, camZoom = 0, 1
    yaw = o.h
    hasAim = false
    I.select({ o })
    I.mode, I.hover, I.dragStart, I.dragging = nil, nil, nil, nil
    A.voice("v_ack", 0)
end

-- Out of the seat. `quiet`: the unit is gone or no longer ours -- nothing to give back.
function R.leave(quiet)
    if not R.id then return end
    local o = S.get(R.id)
    if o and not quiet then I.send("dx " .. R.id) end
    R.id = nil
    V.eye = nil
    -- the commander's view takes over above the unit, facing the same way
    if o then C.jump(o.x, o.z) end
    C.tyaw, C.yaw = yaw, yaw
    C.tdist = 90
end

-- A new game: nobody is driving.
function R.reset() R.id = nil; V.eye = nil end

local function unit()
    local o = R.id and S.get(R.id)
    if o and o.owner == V.me and not o.inside then return o end
    return nil
end

-- --- The camera: behind and above the unit, following its hull ------------------------
function R.camera(dt, shake)
    local o = unit()
    if not o then R.leave(true); return end
    local vo = V.objs[o.id]
    local x, y, z = o.x, 0, o.z
    local h = o.h
    if vo and vo.x then x, y, z, h = vo.x, vo.y, vo.z, vo.h or o.h end
    V.eye = V.eye or {}
    V.eye.x, V.eye.z, V.eye.r = o.x, o.z, EYE
    local turn = 0
    if game.keyDown(game.KEY_Q) then turn = turn + 1 end
    if game.keyDown(game.KEY_E) then turn = turn - 1 end
    camYaw = camYaw + turn * 1.8 * dt
    local wheel = game.mouseWheel and game.mouseWheel() or 0
    if wheel ~= 0 then camZoom = U.clamp(camZoom * (1 - wheel * 0.1), 0.5, 2.5) end
    yaw = yaw + U.angDiff(yaw, h + camYaw) * min(1, dt * 4)
    local size = o.radius * V.scaleOf(o)
    local dist = (o.def.infantry and 8 or max(13, size * 5)) * camZoom
    local up = dist * 0.38 + size
    local ex, ez = x - sin(yaw) * dist, z - cos(yaw) * dist
    local ey = y + up
    local g = game.terrainHeight(ex, ez)
    if ey < g + 2 then ey = g + 2 end
    if shake and shake > 0 then
        local s = shake * 0.3
        ex = ex + (math.random() - 0.5) * s
        ey = ey + (math.random() - 0.5) * s
        ez = ez + (math.random() - 0.5) * s
    end
    -- look past the unit, a little above it: the road ahead and the horizon
    local lx, lz = x + sin(yaw) * dist, z + cos(yaw) * dist
    local ly = y + size * 1.2
    game.setCameraPos(ex, ey, ez)
    game.setCameraDir(lx - ex, ly - ey, lz - ez)
    game.setCameraFov(60)
    -- the commander's camera stays over the unit (the shroud, the effects and
    -- the way back out read it)
    C.x, C.z, C.tx, C.tz = x, z, x, z
    C.dist, C.tdist = 110, 110
    C.eyeX, C.eyeY, C.eyeZ = ex, ey, ez
end

-- A tree in the line of sight from the camera to the ground point (gx, gy, gz):
-- the first one whose crown the ray passes through, by its trunk (x, z), or nil.
-- A tree is a cylinder here, from a little above its foot to its top, as wide
-- as a crown is. Only from the unit on: the trees around the camera behind it
-- are not what its gun points at.
local function treeOnRay(o, gx, gy, gz)
    local ex, ey, ez = C.eyeX, C.eyeY, C.eyeZ
    if not ex then return nil end
    local dx, dy, dz = gx - ex, gy - ey, gz - ez
    local len = math.sqrt(dx * dx + dy * dy + dz * dz)
    if len < 1 then return nil end
    local from = max(1, floor(U.dist(ex, ez, o.x, o.z)))
    for k = from, floor(len) do
        local f = k / len
        local px, py, pz = ex + dx * f, ey + dy * f, ez + dz * f
        local tx, tz, ts = M.treeNear(px, pz, 3.5)
        if tx then
            local r = max(1.0, ts * 0.2)
            local base = V.groundY(tx, tz)
            if (px - tx) ^ 2 + (pz - tz) ^ 2 <= r * r and py >= base + ts * 0.1 and py <= base + ts then
                return tx, tz
            end
        end
    end
    return nil
end

-- --- Hands on the controls ------------------------------------------------------------
function R.update(dt, mx, my, over)
    R.time = R.time + dt
    local o = unit()
    if not o then R.leave(true); return end
    if game.keyPressed(game.KEY_C) or game.keyPressed(game.KEY_ESCAPE) then
        R.leave()
        A.play("click")
        return
    end
    local kd = game.keyDown
    local thr, steer = 0, 0
    if kd(game.KEY_W) or kd(game.KEY_UP) then thr = thr + 1 end
    if kd(game.KEY_S) or kd(game.KEY_DOWN) then thr = thr - 1 end
    if kd(game.KEY_D) or kd(game.KEY_RIGHT) then steer = steer + 1 end
    if kd(game.KEY_A) or kd(game.KEY_LEFT) then steer = steer - 1 end
    if game.keyPressed(game.KEY_X) then
        if o.def.deploys then I.send("dp " .. o.id)
        elseif o.def.canFly then I.send("fl " .. o.id)
        elseif o.def.transport and #o.cargo > 0 then
            I.send(string.format("ul %d %s %s", o.id, S.dmStr(o.x), S.dmStr(o.z)))
        end
        A.play("click")
    end
    -- the aim: where the mouse meets the ground; above the horizon, straight
    -- out from the camera as far as the weapon reaches
    local w = S.weaponOf(o)
    local free = over and not I.overHud
    if free then
        local gx, gy, gz = C.groundHit()
        if gx then
            aimX, aimZ = gx, gz
            -- a tree in the way: that is what is aimed at
            local tx, tz = treeOnRay(o, gx, gy, gz)
            if tx then aimX, aimZ = tx, tz end
        else
            local r = w and w.range or 40
            aimX, aimZ = o.x + sin(yaw) * r, o.z + cos(yaw) * r
        end
        hasAim = true
    elseif not hasAim then
        aimX, aimZ = o.x + sin(o.h) * 20, o.z + cos(o.h) * 20
    end
    local fire = free and w ~= nil and game.mouseDown(game.MOUSE_LEFT)
    local keys = string.format("%d %d %d", thr, steer, fire and 1 or 0)
    local line = string.format("dc %d %d %d %s %s %d", o.id, thr, steer, S.dmStr(aimX), S.dmStr(aimZ), fire and 1 or 0)
    if line ~= sent and (keys ~= sentKeys or R.time - sentT >= 0.1) then
        I.send(line)
        sent, sentKeys, sentT = line, keys, R.time
    end
end

-- --- On screen: the aim in the world, the unit's state at the bottom ----------------------
local function ring(x, y, z, r, col, a, thick)
    local px, py
    for k = 0, 24 do
        local ang = k / 24 * pi * 2
        local hx, hy = game.worldToHud(x + cos(ang) * r, y, z + sin(ang) * r)
        if hx and px then game.hudLine(px, py, hx, hy, col[1], col[2], col[3], a, thick or 2) end
        px, py = hx, hy
    end
end

local function enemyNear(o, w, x, z)
    local best, bd = nil, 64
    for _, u in ipairs(S.objs) do
        if u.alive and not u.inside and (u.cat == "unit" or u.cat == "bld") and S.enemies(o.owner, u.owner)
            and V.visibleTo(u) then
            local d = U.dist2(x, z, u.x, u.z) - u.radius * u.radius
            if d < bd then best, bd = u, d end
        end
    end
    return best
end

function R.draw()
    local o = unit()
    if not o then return end
    local W, Hh = game.hudSize()
    local w = S.weaponOf(o)
    local d = o.def
    -- the aim point; beyond the weapon's reach the shot falls short, at the inner ring
    if w and hasAim then
        local t = enemyNear(o, w, aimX, aimZ)
        local col = t and RED or AMBER
        local range = w.range
        local dx, dz = aimX - o.x, aimZ - o.z
        local dist = math.sqrt(dx * dx + dz * dz)
        local gy = V.groundY(aimX, aimZ) + 0.4
        ring(aimX, gy, aimZ, 1.6, col, 0.95, 2.5)
        local hx, hy = game.worldToHud(aimX, gy, aimZ)
        if hx then
            game.hudLine(hx - 14, hy, hx - 5, hy, col[1], col[2], col[3], 0.95, 2)
            game.hudLine(hx + 5, hy, hx + 14, hy, col[1], col[2], col[3], 0.95, 2)
            game.hudLine(hx, hy - 14, hx, hy - 5, col[1], col[2], col[3], 0.95, 2)
            game.hudLine(hx, hy + 5, hx, hy + 14, col[1], col[2], col[3], 0.95, 2)
        end
        if dist > range then
            local fx, fz = o.x + dx / dist * range, o.z + dz / dist * range
            ring(fx, V.groundY(fx, fz) + 0.4, fz, 1.0, DIM, 0.8, 1.5)
        end
    end
    -- the panel
    local pw, ph = 620, 112
    local px, py = (W - pw) * 0.5, Hh - ph - 18
    game.hudRect(px, py, pw, ph, 0.02, 0.03, 0.04, 0.82, 6)
    game.hudFrame(px, py, pw, ph, AMBER[1], AMBER[2], AMBER[3], 0.6, 1.5, 6)
    game.hudText(px + 18, py + 10, (d.name or o.type), 24, WHITE[1], WHITE[2], WHITE[3], 1, 0, true)
    game.hudText(px + pw - 18, py + 14, "DIREKTSTEUERUNG", 14, AMBER[1], AMBER[2], AMBER[3], 1, 1, true)
    local f = o.hp / o.maxhp
    local hc = (f > 0.6 and GREEN) or (f > 0.3 and AMBER) or RED
    game.hudRect(px + 18, py + 44, 300, 12, 0.1, 0.1, 0.1, 1, 3)
    game.hudRect(px + 18, py + 44, 300 * f, 12, hc[1], hc[2], hc[3], 1, 3)
    if w then
        local ready = 1 - U.clamp(o.cd / w.cd, 0, 1)
        local rc = ready >= 1 and GREEN or DIM
        game.hudRect(px + 340, py + 44, 160, 12, 0.1, 0.1, 0.1, 1, 3)
        game.hudRect(px + 340, py + 44, 160 * ready, 12, rc[1], rc[2], rc[3], 1, 3)
        game.hudText(px + 508, py + 41, ready >= 1 and "BEREIT" or "LÄDT", 14, rc[1], rc[2], rc[3], 1, 0, true)
    end
    local speed = abs(o.spd or 0) * 3.6
    local info = string.format("%d km/h", floor(speed + 0.5))
    if d.harvest then info = info .. string.format("   ·   Ladung %d / %d", floor(o.carry), d.harvest.cap) end
    if d.transport then info = info .. string.format("   ·   Fracht %d / %d", S.cargoUsed(o), d.transport) end
    if o.flying then info = info .. "   ·   im Flug" end
    game.hudText(px + 18, py + 62, info, 15, DIM[1], DIM[2], DIM[3], 1, 0)
    local keys = "W/S fahren  ·  A/D lenken  ·  Maus zielen" .. (w and ", Linksklick feuern" or "")
    if d.deploys then keys = keys .. "  ·  X ausbauen"
    elseif d.canFly then keys = keys .. (o.flyWant and "  ·  X landen" or "  ·  X fliegen")
    elseif d.transport then keys = keys .. "  ·  X entladen" end
    keys = keys .. "  ·  Q/E Blick  ·  C/Esc aussteigen"
    game.hudText(px + 18, py + 84, keys, 14, WHITE[1], WHITE[2], WHITE[3], 0.85, 0)
end

return R
