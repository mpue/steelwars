-- STEELWARS -- the commander's eye: a camera high above the field, looking
-- down at an angle. Pans with WASD / arrow keys / the screen edge, turns with
-- Q/E, zooms with the wheel (or R/F) -- every move also reachable by key, none
-- needs a steady drag.
local U = require("sw.util")
local M = require("sw.map")

local C = {}
local sin, cos, min, max, sqrt = math.sin, math.cos, math.min, math.max, math.sqrt

C.x, C.z = 0, 0          -- the ground point looked at
C.yaw = 0.0              -- radians; 0 = looking toward +Z
C.dist = 120             -- metres from the ground point
C.tx, C.tz, C.tyaw, C.tdist = 0, 0, 0, 120
C.pitch = 0.82           -- radians below the horizon
C.minDist, C.maxDist = 45, 260
C.edge = true
C.fov = 42
C.eyeX, C.eyeY, C.eyeZ = 0, 100, 0

function C.jump(x, z)
    C.tx, C.tz = x, z
    C.x, C.z = x, z
end
function C.lookAt(x, z) C.tx, C.tz = x, z end

local function keyDown(k) return game.keyDown(k) end

function C.update(dt, mx, my, over, blocked, shake)
    local w, h = game.hudSize()
    local speed = C.tdist * 1.25 * dt
    if keyDown(game.KEY_LSHIFT) then speed = speed * 2 end
    local fx, fz = sin(C.yaw), cos(C.yaw)
    local rx, rz = -cos(C.yaw), sin(C.yaw)     -- screen right: forward x up
    local dx, dz = 0, 0
    local ctrl = keyDown(game.KEY_LCTRL) or keyDown(game.KEY_RCTRL)
    if not blocked and not ctrl then
        if keyDown(game.KEY_W) or keyDown(game.KEY_UP) then dx, dz = dx + fx, dz + fz end
        if keyDown(game.KEY_S) or keyDown(game.KEY_DOWN) then dx, dz = dx - fx, dz - fz end
        if keyDown(game.KEY_A) or keyDown(game.KEY_LEFT) then dx, dz = dx - rx, dz - rz end
        if keyDown(game.KEY_D) or keyDown(game.KEY_RIGHT) then dx, dz = dx + rx, dz + rz end
        if C.edge and over and mx then
            local m = 6
            if mx < m then dx, dz = dx - rx, dz - rz end
            if mx > w - m then dx, dz = dx + rx, dz + rz end
            if my < m then dx, dz = dx + fx, dz + fz end
            if my > h - m then dx, dz = dx - fx, dz - fz end
        end
        if keyDown(game.KEY_Q) then C.tyaw = C.tyaw - 1.6 * dt end
        if keyDown(game.KEY_E) then C.tyaw = C.tyaw + 1.6 * dt end
        if keyDown(game.KEY_R) then C.tdist = C.tdist * (1 - 1.2 * dt) end
        if keyDown(game.KEY_F) then C.tdist = C.tdist * (1 + 1.2 * dt) end
        if over then
            local wheel = game.mouseWheel and game.mouseWheel() or 0
            if wheel ~= 0 then C.tdist = C.tdist * (1 - wheel * 0.12) end
        end
    end
    local l = sqrt(dx * dx + dz * dz)
    if l > 0 then C.tx, C.tz = C.tx + dx / l * speed, C.tz + dz / l * speed end
    C.tdist = U.clamp(C.tdist, C.minDist, C.maxDist)
    if M.x0 then
        local pad = 20
        C.tx = U.clamp(C.tx, M.x0 + pad, M.x0 + M.size - pad)
        C.tz = U.clamp(C.tz, M.z0 + pad, M.z0 + M.size - pad)
    end
    local k = min(1, dt * 10)
    C.x = C.x + (C.tx - C.x) * k
    C.z = C.z + (C.tz - C.z) * k
    C.yaw = C.yaw + (C.tyaw - C.yaw) * k
    C.dist = C.dist + (C.tdist - C.dist) * min(1, dt * 7)
    -- a little steeper when far out, flatter when close: more horizon up close
    local pitch = C.pitch + (C.dist - 120) / 600
    local gy = game.terrainHeight(C.x, C.z)
    local hd = cos(pitch) * C.dist
    local ex = C.x - sin(C.yaw) * hd
    local ez = C.z - cos(C.yaw) * hd
    local ey = gy + sin(pitch) * C.dist
    -- never below the ground in front of a hill
    local gEye = game.terrainHeight(ex, ez)
    if ey < gEye + 12 then ey = gEye + 12 end
    if shake and shake > 0 then
        local s = shake * 0.6
        ex = ex + (math.random() - 0.5) * s
        ey = ey + (math.random() - 0.5) * s
        ez = ez + (math.random() - 0.5) * s
    end
    C.eyeX, C.eyeY, C.eyeZ = ex, ey, ez
    game.setCameraPos(ex, ey, ez)
    game.setCameraDir(C.x - ex, gy + 2 - ey, C.z - ez)
    game.setCameraFov(C.fov)
end

-- Where the mouse ray meets the ground (march, then bisect).
function C.groundHit()
    local ox, oy, oz, dx, dy, dz = game.mouseRay()
    if not ox then return nil end
    if dy > -0.02 then return nil end
    local step = 6
    local t = 0
    local px, py, pz = ox, oy, oz
    for _ = 1, 400 do
        local nt = t + step
        local x, y, z = ox + dx * nt, oy + dy * nt, oz + dz * nt
        local g = game.terrainHeight(x, z)
        if y <= g then
            local lo, hi = t, nt
            for _ = 1, 12 do
                local mid = (lo + hi) * 0.5
                local mx, my, mz = ox + dx * mid, oy + dy * mid, oz + dz * mid
                if my <= game.terrainHeight(mx, mz) then hi = mid else lo = mid end
            end
            local x2, z2 = ox + dx * hi, oz + dz * hi
            return x2, oy + dy * hi, z2, ox, oy, oz, dx, dy, dz
        end
        t = nt
    end
    return nil
end

-- The same for an arbitrary HUD point is not available; corners of the view
-- for the minimap frame are found from the camera itself.
function C.viewQuad()
    local hd = cos(C.pitch) * C.dist
    local f = C.dist * 0.75
    local fx, fz = sin(C.yaw), cos(C.yaw)
    local rx, rz = cos(C.yaw), -sin(C.yaw)
    local near, far = -hd * 0.25, hd * 0.9
    local wn, wf = f * 0.55, f * 1.2
    return {
        C.x + fx * near - rx * wn, C.z + fz * near - rz * wn,
        C.x + fx * near + rx * wn, C.z + fz * near + rz * wn,
        C.x + fx * far + rx * wf, C.z + fz * far + rz * wf,
        C.x + fx * far - rx * wf, C.z + fz * far - rz * wf,
    }
end

return C
