-- STEELWARS -- small shared helpers: maths, the deterministic random generator,
-- Euler angles in the engine's convention, string splitting.
--
-- Everything the SIMULATION uses from here must be deterministic: the same
-- inputs give the same outputs on every machine of a multiplayer game. That is
-- why the generator is our own (math.random is seeded per VM) and why nothing
-- here iterates a table with pairs().
local U = {}

local sqrt, atan, asin, floor, abs = math.sqrt, math.atan, math.asin, math.floor, math.abs
local sin, cos, pi = math.sin, math.cos, math.pi

U.DEG = 180 / pi
U.RAD = pi / 180

function U.clamp(v, a, b) if v < a then return a elseif v > b then return b end return v end
function U.lerp(a, b, t) return a + (b - a) * t end
function U.sign(v) if v < 0 then return -1 elseif v > 0 then return 1 end return 0 end
function U.round(v) return floor(v + 0.5) end

function U.dist(ax, az, bx, bz)
    local dx, dz = bx - ax, bz - az
    return sqrt(dx * dx + dz * dz)
end
function U.dist2(ax, az, bx, bz)
    local dx, dz = bx - ax, bz - az
    return dx * dx + dz * dz
end

-- Shortest signed difference b - a between two angles (radians), in [-pi, pi].
function U.angDiff(a, b)
    local d = (b - a) % (2 * pi)
    if d > pi then d = d - 2 * pi end
    return d
end
-- Turn angle `a` toward `b` by at most `step`.
function U.turnTo(a, b, step)
    local d = U.angDiff(a, b)
    if abs(d) <= step then return b end
    return a + step * U.sign(d)
end
-- Heading of a direction: 0 = +Z, pi/2 = +X (the engine's yaw).
function U.heading(dx, dz) return atan(dx, dz) end

-- --- Deterministic random numbers (xorshift32) -------------------------------
local Rng = {}
Rng.__index = Rng
function U.rng(seed)
    local s = (floor(seed) % 2147483647) + 1
    return setmetatable({ s = s }, Rng)
end
function Rng:next()
    local x = self.s
    x = x ~ ((x << 13) & 0xffffffff)
    x = x ~ (x >> 17)
    x = x ~ ((x << 5) & 0xffffffff)
    x = x & 0xffffffff
    if x == 0 then x = 1 end
    self.s = x
    return x
end
-- [0, 1)
function Rng:float() return (self:next() % 16777216) / 16777216 end
-- integer in [a, b]
function Rng:int(a, b) return a + (self:next() % (b - a + 1)) end
function Rng:range(a, b) return a + (b - a) * self:float() end

-- --- Rotations in the engine's convention ------------------------------------
-- An entity's rotation (rx, ry, rz) in degrees composes as Rz * Ry * Rx.
-- Yaw ry turns +Z toward +X.

-- Euler (degrees) for a frame given by its forward f and up u (unit vectors).
function U.eulerFromFrame(fx, fy, fz, ux, uy, uz)
    -- right = up x forward
    local rx, ry, rz = uy * fz - uz * fy, uz * fx - ux * fz, ux * fy - uy * fx
    local rl = sqrt(rx * rx + ry * ry + rz * rz)
    if rl < 1e-6 then return 0, U.heading(fx, fz) * U.DEG, 0 end
    rx, ry, rz = rx / rl, ry / rl, rz / rl
    -- re-orthogonalise forward = right x up
    fx, fy, fz = ry * uz - rz * uy, rz * ux - rx * uz, rx * uy - ry * ux
    local b = asin(U.clamp(-rz, -1, 1))
    local a = atan(uz, fz)
    local c = atan(ry, rx)
    return a * U.DEG, b * U.DEG, c * U.DEG
end

-- Euler (degrees) for heading h (radians) on ground with normal (nx, ny, nz).
function U.eulerOnGround(h, nx, ny, nz)
    local fx, fz = sin(h), cos(h)
    -- project the heading onto the ground plane
    local d = fx * nx + fz * nz
    local px, py, pz = fx - d * nx, -d * ny, fz - d * nz
    local l = sqrt(px * px + py * py + pz * pz)
    if l < 1e-6 then return 0, h * U.DEG, 0 end
    return U.eulerFromFrame(px / l, py / l, pz / l, nx, ny, nz)
end

-- Rotate vector v by Euler (degrees) in the engine's Rz*Ry*Rx order.
function U.rotate(rx, ry, rz, x, y, z)
    local a, b, c = rx * U.RAD, ry * U.RAD, rz * U.RAD
    local ca, sa, cb, sb, cc, sc = cos(a), sin(a), cos(b), sin(b), cos(c), sin(c)
    -- Rx
    local y1, z1 = ca * y - sa * z, sa * y + ca * z
    local x1 = x
    -- Ry
    local x2, z2 = cb * x1 + sb * z1, -sb * x1 + cb * z1
    local y2 = y1
    -- Rz
    return cc * x2 - sc * y2, sc * x2 + cc * y2, z2
end

-- --- Strings ----------------------------------------------------------------
function U.split(s, sep)
    local out = {}
    sep = sep or " "
    local at = 1
    while true do
        local i = string.find(s, sep, at, true)
        if not i then out[#out + 1] = string.sub(s, at); break end
        out[#out + 1] = string.sub(s, at, i - 1)
        at = i + #sep
    end
    return out
end

function U.fmtInt(n)
    local s = tostring(floor(n))
    local out = s:reverse():gsub("(%d%d%d)", "%1."):reverse()
    if out:sub(1, 1) == "." then out = out:sub(2) end
    return out
end

function U.fmtTime(t)
    t = floor(t)
    return string.format("%d:%02d", t // 60, t % 60)
end

-- A copy of an array.
function U.copy(t)
    local o = {}
    for i = 1, #t do o[i] = t[i] end
    return o
end

return U
