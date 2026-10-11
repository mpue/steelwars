-- STEELWARS -- the battlefield as a grid: what can be driven on, what is
-- built on, where the Energicum lies, and the way from here to there (A*).
--
-- Built once at the start from the terrain as the engine draws it. Every
-- machine of a multiplayer game builds the same grid from the same scene, so
-- the grid is part of the deterministic simulation; the visual layer may ask
-- it for heights, the simulation never asks the engine anything after this.
local D = require("sw.defs")
local U = require("sw.util")

local M = {}

local floor, sqrt, abs, min, max = math.floor, math.sqrt, math.abs, math.min, math.max
local CELL = D.CELL

-- Build the grid. `cx, cz` is the centre of the playable square in the world.
-- heightAt(x, z) -> terrain height; standsAt(x, z, h) -> true when something
-- (a house of the ruined town, a wall, a bridge pier) stands above the terrain.
function M.build(cx, cz, size, heightAt, standsAt, waterLevel, progress)
    local W = floor(size / CELL)
    M.W, M.H = W, W
    M.size = size
    M.x0, M.z0 = cx - size * 0.5, cz - size * 0.5
    M.cx, M.cz = cx, cz
    M.waterLevel = waterLevel or -1e9
    local hgt, block, slope = {}, {}, {}
    M.hgt, M.block, M.slope = hgt, block, slope
    M.occ = {}        -- building id per cell (0 = free)
    M.crystal = {}    -- crystal id per cell (0 = none)
    -- Heights on the cell corners, so a cell's slope is measured across it.
    local CW = W + 1
    local corner = {}
    for j = 0, W do
        for i = 0, W do
            corner[j * CW + i + 1] = heightAt(M.x0 + i * CELL, M.z0 + j * CELL)
        end
        if progress then progress(0.5 * j / W) end
    end
    M.corner = corner
    for j = 0, W - 1 do
        for i = 0, W - 1 do
            local a = corner[j * CW + i + 1]
            local b = corner[j * CW + i + 2]
            local c = corner[(j + 1) * CW + i + 1]
            local d = corner[(j + 1) * CW + i + 2]
            local h = (a + b + c + d) * 0.25
            local s = max(abs(a - b), abs(c - d), abs(a - c), abs(b - d)) / CELL
            local k = j * W + i + 1
            hgt[k] = h
            slope[k] = s
            local blocked = 0
            if s > 0.85 then blocked = 1 end            -- cliff
            if h < M.waterLevel - 0.6 then blocked = 2 end   -- deep water
            if blocked == 0 and standsAt then
                local x, z = M.x0 + (i + 0.5) * CELL, M.z0 + (j + 0.5) * CELL
                if standsAt(x, z, h) then blocked = 3 end     -- a house, a ruin
            end
            -- the edge of the map is a wall
            if i == 0 or j == 0 or i == W - 1 or j == W - 1 then blocked = 4 end
            block[k] = blocked
            M.occ[k] = 0
            M.crystal[k] = 0
        end
        if progress then progress(0.5 + 0.5 * j / W) end
    end
    M.stamp, M.g, M.parent, M.searchId = {}, {}, {}, 0
end

-- --- Coordinates ---------------------------------------------------------------
function M.cellOf(x, z)
    return floor((x - M.x0) / CELL), floor((z - M.z0) / CELL)
end
function M.index(i, j) return j * M.W + i + 1 end
function M.inside(i, j) return i >= 0 and j >= 0 and i < M.W and j < M.H end
function M.center(i, j) return M.x0 + (i + 0.5) * CELL, M.z0 + (j + 0.5) * CELL end
function M.clampPos(x, z)
    local lo, hiX, hiZ = CELL * 1.5, M.size - CELL * 1.5, M.size - CELL * 1.5
    return U.clamp(x, M.x0 + lo, M.x0 + hiX), U.clamp(z, M.z0 + lo, M.z0 + hiZ)
end

-- Bilinear height over the corner lattice (the simulation's own idea of the
-- ground; the view uses the engine's exact terrain).
function M.height(x, z)
    local fx, fz = (x - M.x0) / CELL, (z - M.z0) / CELL
    local i, j = floor(fx), floor(fz)
    if i < 0 then i = 0 elseif i > M.W - 1 then i = M.W - 1 end
    if j < 0 then j = 0 elseif j > M.H - 1 then j = M.H - 1 end
    local tx, tz = U.clamp(fx - i, 0, 1), U.clamp(fz - j, 0, 1)
    local CW = M.W + 1
    local c = M.corner
    local a, b = c[j * CW + i + 1], c[j * CW + i + 2]
    local e, f = c[(j + 1) * CW + i + 1], c[(j + 1) * CW + i + 2]
    return (a * (1 - tx) + b * tx) * (1 - tz) + (e * (1 - tx) + f * tx) * tz
end

-- Trees of the forest (x, z, scale triples): a trunk makes its cell a wall
-- for ground units. A building may still go there -- it clears the trees.
-- Where the trunks stand (and how tall) is kept per cell, for a vehicle that
-- rolls them over and a shell that sets them alight.
function M.markTrees(list)
    local n = 0
    M.trunks = {}
    M.fire = {}       -- cell -> "burning" or "charred" (a fire takes a tree once)
    for k = 1, #list - 2, 3 do
        local i, j = M.cellOf(list[k], list[k + 1])
        if M.inside(i, j) then
            local c = j * M.W + i + 1
            if M.block[c] == 0 then M.block[c] = 5; n = n + 1 end
            if M.block[c] == 5 then
                local t = M.trunks[c]
                if not t then t = {}; M.trunks[c] = t end
                t[#t + 1] = list[k]
                t[#t + 1] = list[k + 1]
                t[#t + 1] = list[k + 2]
            end
        end
    end
    return n
end

-- A vehicle rolls over the trees of a cell (or a hit knocks a charred snag
-- down): the cell opens, and the trunks that stood in it (x, z, scale
-- triples) go to the view to be felled. Nil when there were none.
function M.fellTrees(i, j)
    if not M.inside(i, j) then return nil end
    return M.fellCell(j * M.W + i + 1)
end
function M.fellCell(c)
    if M.block[c] ~= 5 or M.occ[c] ~= 0 then return nil end
    M.block[c] = 0
    local t = M.trunks and M.trunks[c]
    if t then M.trunks[c] = nil end
    return t or {}
end

-- The forest cells with a trunk standing within r of (x, z) (still a wall:
-- not rolled over), in grid order.
function M.treeCells(x, z, r)
    local out = {}
    if not M.trunks then return out end
    local i0, j0 = M.cellOf(x - r, z - r)
    local i1, j1 = M.cellOf(x + r, z + r)
    for j = j0, j1 do
        for i = i0, i1 do
            if M.inside(i, j) then
                local c = j * M.W + i + 1
                local t = M.trunks[c]
                if t and M.block[c] == 5 then
                    for k = 1, #t - 2, 3 do
                        if (t[k] - x) ^ 2 + (t[k + 1] - z) ^ 2 <= r * r then
                            out[#out + 1] = c
                            break
                        end
                    end
                end
            end
        end
    end
    return out
end

-- The tree whose trunk stands within r of (x, z), standing still (a wall):
-- its x, z, scale, or nil.
function M.treeNear(x, z, r)
    if not M.trunks then return nil end
    local i0, j0 = M.cellOf(x - r, z - r)
    local i1, j1 = M.cellOf(x + r, z + r)
    local bx, bz, bs, bd = nil, nil, nil, r * r
    for j = j0, j1 do
        for i = i0, i1 do
            if M.inside(i, j) then
                local c = j * M.W + i + 1
                local t = M.trunks[c]
                if t and M.block[c] == 5 then
                    for k = 1, #t - 2, 3 do
                        local d = (t[k] - x) ^ 2 + (t[k + 1] - z) ^ 2
                        if d <= bd then bx, bz, bs, bd = t[k], t[k + 1], t[k + 2], d end
                    end
                end
            end
        end
    end
    return bx, bz, bs
end

-- Clear the forest from a disc (start positions, Energicum fields).
function M.clearDisc(x, z, r)
    local i0, j0 = M.cellOf(x - r, z - r)
    local i1, j1 = M.cellOf(x + r, z + r)
    for j = j0, j1 do
        for i = i0, i1 do
            if M.inside(i, j) then
                local cx, cz = M.center(i, j)
                if (cx - x) ^ 2 + (cz - z) ^ 2 <= r * r and M.block[j * M.W + i + 1] == 5 then
                    M.block[j * M.W + i + 1] = 0
                end
            end
        end
    end
end

-- Clear the forest from a footprint; true when there was any.
function M.clearTrees(i, j, w, h)
    local any = false
    for jj = j, j + h - 1 do
        for ii = i, i + w - 1 do
            if M.inside(ii, jj) and M.block[jj * M.W + ii + 1] == 5 then
                M.block[jj * M.W + ii + 1] = 0
                any = true
            end
        end
    end
    return any
end

-- Can a ground unit be on this cell?
function M.walkable(i, j)
    if i < 0 or j < 0 or i >= M.W or j >= M.H then return false end
    local k = j * M.W + i + 1
    return M.block[k] == 0 and M.occ[k] == 0
end
function M.walkableAt(x, z)
    local i, j = M.cellOf(x, z)
    return M.walkable(i, j)
end

-- Could a building of w x h cells go with its corner cell at (i, j)?
-- Returns ok and the reason when not.
function M.canBuild(i, j, w, h)
    for jj = j, j + h - 1 do
        for ii = i, i + w - 1 do
            if not M.inside(ii, jj) then return false, "Kartenrand" end
            local k = jj * M.W + ii + 1
            if M.block[k] ~= 0 and M.block[k] ~= 5 then return false, "Gelände" end
            if M.occ[k] ~= 0 then return false, "belegt" end
            if M.crystal[k] ~= 0 then return false, "Energicum" end
            if M.slope[k] > 0.35 then return false, "zu steil" end
        end
    end
    return true
end

function M.occupy(i, j, w, h, id)
    for jj = j, j + h - 1 do
        for ii = i, i + w - 1 do
            if M.inside(ii, jj) then M.occ[jj * M.W + ii + 1] = id end
        end
    end
end

-- The nearest walkable cell to (x, z), searching outwards in rings.
function M.nearestWalkable(x, z, maxRing)
    local i, j = M.cellOf(x, z)
    if M.walkable(i, j) then return i, j end
    for r = 1, maxRing or 24 do
        local best, bi, bj = nil, nil, nil
        for dj = -r, r do
            for di = -r, r do
                if abs(di) == r or abs(dj) == r then
                    local ii, jj = i + di, j + dj
                    if M.walkable(ii, jj) then
                        local d = di * di + dj * dj
                        if not best or d < best then best, bi, bj = d, ii, jj end
                    end
                end
            end
        end
        if best then return bi, bj end
    end
    return nil
end

-- A straight line on the grid that a ground unit could drive (no blocked cell).
function M.lineClear(x0, z0, x1, z1)
    local dx, dz = x1 - x0, z1 - z0
    local len = sqrt(dx * dx + dz * dz)
    local steps = floor(len / (CELL * 0.5)) + 1
    for s = 1, steps do
        local t = s / steps
        local i, j = M.cellOf(x0 + dx * t, z0 + dz * t)
        if not M.walkable(i, j) then return false end
    end
    return true
end

-- --- A* -----------------------------------------------------------------------
local heapK, heapF, heapN = {}, {}, 0

local function heapPush(k, f)
    heapN = heapN + 1
    local n = heapN
    heapK[n], heapF[n] = k, f
    while n > 1 do
        local p = n // 2
        if heapF[p] <= heapF[n] then break end
        heapK[p], heapK[n] = heapK[n], heapK[p]
        heapF[p], heapF[n] = heapF[n], heapF[p]
        n = p
    end
end

local function heapPop()
    local k = heapK[1]
    heapK[1], heapF[1] = heapK[heapN], heapF[heapN]
    heapN = heapN - 1
    local n = 1
    while true do
        local l, r, s = 2 * n, 2 * n + 1, n
        if l <= heapN and heapF[l] < heapF[s] then s = l end
        if r <= heapN and heapF[r] < heapF[s] then s = r end
        if s == n then break end
        heapK[s], heapK[n] = heapK[n], heapK[s]
        heapF[s], heapF[n] = heapF[n], heapF[s]
        n = s
    end
    return k
end

local NB = { { 1, 0, 1 }, { -1, 0, 1 }, { 0, 1, 1 }, { 0, -1, 1 },
             { 1, 1, 1.4142 }, { -1, 1, 1.4142 }, { 1, -1, 1.4142 }, { -1, -1, 1.4142 } }

-- Path from world (sx, sz) to (tx, tz) for a ground unit. Returns a list of
-- world waypoints {x1, z1, x2, z2, ...} (the start excluded), smoothed; when
-- the goal cannot be reached, the way to the reachable cell nearest it.
-- `budget` caps the cells expanded.
function M.findPath(sx, sz, tx, tz, budget)
    local W = M.W
    local si, sj = M.cellOf(sx, sz)
    if not M.walkable(si, sj) then
        local a, b = M.nearestWalkable(sx, sz, 6)
        if not a then return nil end
        si, sj = a, b
    end
    local gi, gj = M.cellOf(tx, tz)
    if not M.walkable(gi, gj) then
        local a, b = M.nearestWalkable(tx, tz, 30)
        if not a then return nil end
        gi, gj = a, b
    end
    M.searchId = M.searchId + 1
    local sid = M.searchId
    local stamp, g, parent, block, occ, slope = M.stamp, M.g, M.parent, M.block, M.occ, M.slope
    local start, goal = sj * W + si + 1, gj * W + gi + 1
    heapN = 0
    stamp[start], g[start], parent[start] = sid, 0, 0
    local function h(i, j)
        local di, dj = abs(i - gi), abs(j - gj)
        return (max(di, dj) + 0.4142 * min(di, dj)) * 1.3
    end
    heapPush(start, h(si, sj))
    local best, bestH = start, h(si, sj)
    local closed = {}
    local expanded = 0
    budget = budget or 9000
    while heapN > 0 do
        local k = heapPop()
        if k == goal then best = goal; break end
        if not closed[k] then
            closed[k] = true
            expanded = expanded + 1
            if expanded > budget then break end
            local i, j = (k - 1) % W, (k - 1) // W
            local gk = g[k]
            for n = 1, 8 do
                local d = NB[n]
                local ii, jj = i + d[1], j + d[2]
                if ii >= 0 and jj >= 0 and ii < W and jj < W then
                    local kk = jj * W + ii + 1
                    if block[kk] == 0 and occ[kk] == 0 then
                        -- no squeezing diagonally between two blocked cells
                        local ok = true
                        if d[3] > 1 then
                            local ka, kb = j * W + ii + 1, jj * W + i + 1
                            if block[ka] ~= 0 or occ[ka] ~= 0 or block[kb] ~= 0 or occ[kb] ~= 0 then ok = false end
                        end
                        if ok then
                            local cost = gk + d[3] * (1 + slope[kk] * 2)
                            if stamp[kk] ~= sid or cost < g[kk] then
                                stamp[kk], g[kk], parent[kk] = sid, cost, k
                                local hh = h(ii, jj)
                                if hh < bestH then best, bestH = kk, hh end
                                heapPush(kk, cost + hh)
                            end
                        end
                    end
                end
            end
        end
    end
    -- Walk back.
    local cells = {}
    local k = best
    while k ~= 0 and k ~= start do
        cells[#cells + 1] = k
        k = parent[k]
    end
    if #cells == 0 then
        if best == start then return {} end
        return nil
    end
    -- Reverse into world points.
    local pts = {}
    for n = #cells, 1, -1 do
        local c = cells[n]
        local x, z = M.center((c - 1) % W, (c - 1) // W)
        pts[#pts + 1] = x
        pts[#pts + 1] = z
    end
    -- The goal itself, when its cell was reached and it is walkable.
    if best == goal and M.walkableAt(tx, tz) then
        pts[#pts - 1], pts[#pts] = tx, tz
    end
    -- String pulling: from each anchor, skip to the furthest point in sight.
    local out = {}
    local ax, az = sx, sz
    local n = 1
    local count = #pts // 2
    while n <= count do
        local far = n
        local m = math.min(count, n + 24)
        while m > n do
            if M.lineClear(ax, az, pts[2 * m - 1], pts[2 * m]) then far = m; break end
            m = m - 1
        end
        out[#out + 1] = pts[2 * far - 1]
        out[#out + 1] = pts[2 * far]
        ax, az = pts[2 * far - 1], pts[2 * far]
        n = far + 1
    end
    return out
end

return M
