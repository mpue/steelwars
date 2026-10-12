-- STEELWARS -- a science-fiction real-time strategy game for the Fitzel engine.
--
-- Attach this script to one Empty in the battlefield scene. The scene provides
-- the world (terrain, forests, the ruined town, rivers, sky) and a few markers:
--   "SW Map"    the centre of the playable square
--   "SW Start"  start positions (any number, at least two)
--   "SW Field"  Energicum fields
--   "FX ..."    particle emitters for the effects (see sw/fx.lua)
-- Everything else -- the armies, the bases, the game -- comes from here and
-- the modules in scripts/sw/.
--
-- Module layout:
--   sw/defs     the rules as data        sw/sim(+unit,combat,cmd)  the simulation
--   sw/map      grid and pathfinding     sw/ai       the computer opponent
--   sw/view     units on screen          sw/fx       effects    sw/audio  sound
--   sw/camera   the commander's eye      sw/ui       selecting and ordering
--   sw/drive    one unit steered by hand
--   sw/steward  minds the base while you drive
--   sw/hud      the command screen       sw/menu     title, lobby, results
--   sw/session  the lockstep clock (local or over the relay)
--   sw/agent    commanders that think with a language model (Ollama)

mapSize    = 1024     -- metres, the playable square
showFps    = false
musicOn    = true
autoStart  = ""       -- "skirmish" starts a game straight away, "aivsai" lets two computers fight (testing),
                      -- "agentvsai" / "agentvsagent" lets language-model commanders play (watching)
-- Commander agents (a side played by a language model through Ollama, see sw/agent.lua)
agentModel    = "qwen3:8b"   -- the model of the first agent's staff
agentModel2   = ""           -- the second agent's, "" = the same (two models fighting each other)
agentSubModel = ""           -- the sub-commanders' (Wirtschaft, Heer), "" = the same as their chief
ollamaHost    = "127.0.0.1"
ollamaPort    = 11434
followAction = false  -- the camera goes where the shooting is (spectating)
lookField = 0         -- testing: start looking at Energicum field n

local D, U, M, S, AI, V, F, A, C, I, H, Mn, N, G, Dr, St

local state = "boot"      -- boot, loading, menu, game, result
local loader = nil
local loadMsg, loadProg = "", 0
local markers = {}
local result = nil
local menuCam = 0
local addresses = nil
local netMode = nil       -- "lobby" while in rooms
local myId = 0
local seed0 = 1
local mpTest = nil
local uiTest = nil

-- The UI test: a person's session, step by step, through the same calls the
-- mouse and the keys make (ui.lua / hud.lua), with a report at the end.
local function uiTestStep(dt)
    local T = uiTest
    T.t = T.t + dt
    local me = V.me
    local function find(type)
        for _, o in ipairs(S.objs) do if o.alive and o.owner == me and o.type == type then return o end end
    end
    local function note(s) T.log[#T.log + 1] = string.format("%.1f %s", T.t, s) end
    local steps = {
        function() local m = find("mcv"); if m then I.select({ m }); note("mcv selected"); return true end end,
        function()
            for _, c in ipairs(I.commands()) do if c.label == "Ausbauen" then c.act(); note("deploy pressed"); return true end end
        end,
        function() local b = find("base"); if b and b.built >= 1 then note("base built"); C.lookAt(b.x, b.z); return true end end,
        function() I.sendQueue(find("base"), "powerplant"); note("powerplant queued"); return true end,
        function()
            local b = find("base")
            if b.queue[1] and b.queue[1].done then
                -- the spot the mouse would choose: right of the base
                for r = 0, 10 do
                    local i, j = b.i + b.w + 1 + r, b.j
                    if I.placeOk("powerplant", i, j) then
                        I.startPlace("powerplant")
                        I.send(string.format("pl powerplant %d %d", i, j)); I.mode = nil
                        note("powerplant placed at " .. i .. "," .. j); return true
                    end
                end
            end
        end,
        function() if find("powerplant") then I.sendQueue(find("base"), "refinery"); note("refinery queued"); return true end end,
        function()
            local b = find("base")
            if b.queue[1] and b.queue[1].done then
                for r = 6, 16 do
                    for k = 0, 23 do
                        local a = k / 24 * math.pi * 2
                        local i = math.floor(b.i + 3 + math.sin(a) * r - 2)
                        local j = math.floor(b.j + 3 + math.cos(a) * r - 2)
                        if I.placeOk("refinery", i, j) then
                            I.send(string.format("pl refinery %d %d", i, j)); note("refinery placed at " .. i .. "," .. j); return true
                        end
                    end
                end
                if not T.warned then T.warned = true; note("no spot for the refinery") end
            end
        end,
        function() I.sendQueue(find("base"), "soldier"); I.sendQueue(find("base"), "soldier"); note("two soldiers queued"); return true end,
        function()
            local n = 0
            for _, o in ipairs(S.objs) do if o.alive and o.owner == me and o.type == "soldier" then n = n + 1 end end
            if n >= 5 then note("soldiers out: " .. n); return true end
        end,
        function()
            local list = {}
            for _, o in ipairs(S.objs) do if o.alive and o.owner == me and o.cat == "unit" and S.weaponOf(o) then list[#list + 1] = o end end
            I.select(list)
            local b = find("base")
            I.orderAt(b.x + 60, b.z + 60, nil, false)
            note("army of " .. #list .. " ordered to move")
            return true
        end,
        function() if T.t > (T.moveT or 0) + 12 then note("done"); return true end end,
    }
    local f = steps[T.step]
    if f and f() then
        T.step = T.step + 1
        T.moveT = T.t
        game.saveData("uitest", { log = T.log, cells = S.players[me].cells })
    end
end
local lastDump = nil
local treeSoundAt = nil   -- when a falling tree was last heard (H.time)
local lastFollow = nil

local function requireAll()
    D = require("sw.defs")
    U = require("sw.util")
    M = require("sw.map")
    S = require("sw.sim")
    AI = require("sw.ai")
    V = require("sw.view")
    F = require("sw.fx")
    A = require("sw.audio")
    C = require("sw.camera")
    I = require("sw.ui")
    H = require("sw.hud")
    Mn = require("sw.menu")
    N = require("sw.session")
    G = require("sw.agent")
    Dr = require("sw.drive")
    St = require("sw.steward")
    I.drive = Dr.enter
    I.driveBack = Dr.back
end

-- --- The scene's markers -----------------------------------------------------------
local function readMarkers(e)
    local m = { starts = {}, fields = {} }
    local id = game.find("SW Map")
    if id then
        local x, y, z = game.getPos(id)
        m.cx, m.cz = x, z
    else
        m.cx, m.cz = e.x, e.z
    end
    for _, sid in ipairs(game.findAll("SW Start")) do
        local x, y, z = game.getPos(sid)
        m.starts[#m.starts + 1] = { x, z }
    end
    if #m.starts < 2 then
        local r = mapSize * 0.36
        m.starts = { { m.cx - r, m.cz - r }, { m.cx + r, m.cz + r }, { m.cx - r, m.cz + r }, { m.cx + r, m.cz - r } }
    end
    for _, fid in ipairs(game.findAll("SW Field")) do
        local x, y, z = game.getPos(fid)
        local sx = game.getScale(fid) or 1
        m.fields[#m.fields + 1] = { x, z, sx }
    end
    if #m.fields == 0 then
        for _, s in ipairs(m.starts) do
            local dx, dz = m.cx - s[1], m.cz - s[2]
            m.fields[#m.fields + 1] = { s[1] + dx * 0.22 + dz * 0.12, s[2] + dz * 0.22 - dx * 0.12, 1 }
        end
        m.fields[#m.fields + 1] = { m.cx, m.cz, 1.5 }
    end
    -- sort for a stable order on every machine
    table.sort(m.starts, function(a, b) return a[1] < b[1] or (a[1] == b[1] and a[2] < b[2]) end)
    table.sort(m.fields, function(a, b) return a[1] < b[1] or (a[1] == b[1] and a[2] < b[2]) end)
    return m
end

-- --- Loading (a coroutine, so the screen keeps drawing) --------------------------------
local function load(e)
    loadMsg = "Gelände wird vermessen"
    markers = readMarkers(e)
    local n = 0
    M.build(markers.cx, markers.cz, mapSize,
        function(x, z) return game.terrainHeight(x, z) end,
        function(x, z, h)
            -- a house of the town, a ruin, a wall: something stands above the ground
            local top = game.groundHeight(x, h + 60, z, 70)
            if top and top > h + 1.8 then return true end
            -- rivers and lakes
            local surf, depth = game.waterAt(x, z)
            if surf and depth and depth > 0.7 then return true end
            return false
        end,
        -1e9,
        function(p)
            loadProg = p * 0.6
            n = n + 1
            if n % 4 == 0 then coroutine.yield() end
        end)
    loadMsg = "Wälder werden kartiert"
    coroutine.yield()
    local half = mapSize * 0.5
    local trees = game.trees(markers.cx - half, markers.cz - half, markers.cx + half, markers.cz + half)
    M.markTrees(trees)
    -- room for the bases and the harvesters: the forest steps back
    for _, s in ipairs(markers.starts) do
        M.clearDisc(s[1], s[2], 75)
        game.clearTrees(s[1], s[2], 78)
    end
    for _, s in ipairs(markers.starts) do
        -- a lane through the forest to the nearest field
        local best, bd = nil, 1e18
        for _, f in ipairs(markers.fields) do
            local d = (f[1] - s[1]) ^ 2 + (f[2] - s[2]) ^ 2
            if d < bd then best, bd = f, d end
        end
        if best then
            local n = math.floor(math.sqrt(bd) / 10) + 1
            for k = 0, n do
                local x = s[1] + (best[1] - s[1]) * k / n
                local z = s[2] + (best[2] - s[2]) * k / n
                M.clearDisc(x, z, 16)
                game.clearTrees(x, z, 18)
            end
        end
    end
    for _, f in ipairs(markers.fields) do
        local r = 22 + 18 * (f[3] or 1)
        M.clearDisc(f[1], f[2], r)
        game.clearTrees(f[1], f[2], r + 3)
    end
    loadMsg = "Modelle werden geladen"
    V.preload(function(p) loadProg = 0.6 + p * 0.35; coroutine.yield() end)
    loadMsg = "Radar wird kalibriert"
    H.makeMinimap("sw_minimap_" .. math.floor(markers.cx) .. "_" .. math.floor(markers.cz) .. ".tga")
    V.init()
    F.init()
    loadProg = 1
end

-- --- Starting a game -------------------------------------------------------------------
-- players: { {name, color, team, ai, aiLevel}, ... } -- in slot order.
local function beginGame(players, seed, mySlot, mode)
    seed0 = seed
    local rng = U.rng(seed)
    -- start positions: a shuffle everybody agrees on (the seed)
    local starts = {}
    for k, s in ipairs(markers.starts) do starts[k] = s end
    for k = #starts, 2, -1 do
        local j = rng:int(1, k)
        starts[k], starts[j] = starts[j], starts[k]
    end
    for k, p in ipairs(players) do
        local s = starts[(k - 1) % #starts + 1]
        p.startX, p.startZ = s[1], s[2]
    end
    S.new({ seed = seed, players = players })
    AI.reset()
    AI.install(S)
    -- sides a language model commands
    G.reset()
    G.model, G.subModel = agentModel, agentSubModel
    local nAgents = 0
    for k, p in ipairs(players) do
        if p.agent then
            nAgents = nAgents + 1
            G.add(k - 1, { name = p.name, model = (nAgents >= 2 and agentModel2 ~= "") and agentModel2 or agentModel })
        end
    end
    -- the staffs' thoughts: shown when we watch them, hidden when we fight them (F2)
    local mine = players[mySlot + 1]
    G.show = nAgents > 0 and (mine.agent or mine.ai or false)
    G.onSay = function(st, who, text)
        if who == "radio" and G.show then
            local c = D.teams[S.players[st.slot].color] or D.teams[0]
            H.message(S.players[st.slot].name .. ": " .. text, { c.r, c.g, c.b })
        end
    end
    -- Energicum
    for fi, f in ipairs(markers.fields) do
        local count = math.floor(10 * (f[3] or 1) + 4)
        for k = 0, count - 1 do
            local a = k * 2.39996 + fi
            local r = 6 + math.sqrt(k) * 7.5 * (f[3] or 1)
            local x, z = f[1] + math.cos(a) * r, f[2] + math.sin(a) * r
            if M.walkableAt(x, z) then S.addCrystal(x, z, D.CRYSTAL_AMOUNT, k % 3) end
        end
    end
    -- each player: a construction vehicle and an escort
    for k, p in ipairs(players) do
        local pi = k - 1
        local x, z = p.startX, p.startZ
        local h = U.heading(markers.cx - x, markers.cz - z)
        local i, j = M.nearestWalkable(x, z, 20)
        if i then x, z = M.center(i, j) end
        S.addUnit("mcv", pi, x, z, h)
        local fx, fz = math.sin(h), math.cos(h)
        local rx, rz = fz, -fx
        for n = 1, 4 do
            local ox, oz = x + fx * 14 + rx * (n - 2.5) * 3, z + fz * 14 + rz * (n - 2.5) * 3
            local a, b = M.nearestWalkable(ox, oz, 8)
            if a then ox, oz = M.center(a, b) end
            S.addUnit(n == 4 and "engineer" or "soldier", pi, ox, oz, h)
        end
        local tx, tz = x - fx * 14, z - fz * 14
        local a, b = M.nearestWalkable(tx, tz, 8)
        if a then tx, tz = M.center(a, b) end
        S.addUnit("tank", pi, tx, tz, h)
    end
    V.me = mySlot
    N.start(mode, mySlot)
    I.send = N.send
    I.clearSel()
    Dr.reset()
    St.reset()
    local me = players[mySlot + 1]
    C.jump(me.startX, me.startZ)
    C.tyaw = U.heading(markers.cx - me.startX, markers.cz - me.startZ)
    C.yaw = C.tyaw
    C.tdist, C.dist = 90, 140
    state = "game"
    result = nil
    if musicOn then A.startGameMusic() end
    H.message("Baufahrzeug auswählen und mit X ausbauen", { 1, 0.62, 0.12 })
    A.voice("v_building", 0)
end

local function startSkirmish(o, spectate)
    local agentMe = o.side == "agent" and not spectate
    local players = { { name = agentMe and "ATLAS (Agent)" or (Mn.name ~= "" and Mn.name or "Kommandant"), color = o.color, team = 0,
                        cells = o.cells, ai = spectate, aiLevel = spectate and 3 or nil, agent = agentMe } }
    local colors = {}
    for c = 0, 3 do if c ~= o.color then colors[#colors + 1] = c end end
    local names = { "KRONOS", "VULKAN", "HYDRA" }
    for k = 1, o.enemies do
        local agent = o.foes == "agenten" or (o.foes == "gemischt" and k == 1)
        players[#players + 1] = { name = names[k] .. (agent and " (Agent)" or " (KI)"), color = colors[k], team = k,
                                  ai = not agent, aiLevel = o.level, cells = o.cells, agent = agent }
    end
    beginGame(players, os.time() % 100000 + 1, 0, "local")
    N.speed = o.speed or 1
    if agentMe then
        -- our side commands itself: watch it like a computer game
        V.hideFog = false
        H.message("Dein Stab führt -- F2 blendet seine Gedanken ein und aus", { 1, 0.62, 0.12 })
    end
end

-- --- Events from the simulation -> what is seen and heard ------------------------------
local function handleEvents()
    local me = V.me
    for _, ev in ipairs(S.events) do
        G.event(S, ev)
        local t = ev.t
        if t == "fire" then
            local o = S.byId[ev.id]
            if followAction and o and (H.time - (lastFollow or -10)) > 6 then
                lastFollow = H.time
                C.lookAt(o.x, o.z)
            end
            if o and o.alive then
                ev.gy = V.groundY(ev.x, ev.z)
                F.fire(o, ev, V.muzzle)
            end
        elseif t == "impact" then
            F.impact(ev, V.groundY(ev.x, ev.z))
        elseif t == "explode" then
            local gy = V.groundY(ev.x, ev.z)
            F.explode(ev, gy + (ev.y or 0))
        elseif t == "remove" then
            local vo = V.objs[ev.id]
            if ev.how == "killed" and ev.cat == "unit" and vo and vo.x then
                local man = vo.man
                if man and man.wreck and not (ev.y and ev.y > 3) then
                    F.wreck(man.wreck, vo.x, vo.y, vo.z, (vo.h or 0) * U.DEG, 40)
                elseif ev.type and D.units[ev.type] and D.units[ev.type].infantry and V.loaded["bot_debris.glb"] then
                    F.wreck("bot_debris", vo.x, vo.y, vo.z, math.random() * 360, 25)
                end
            end
            if ev.how == "killed" and ev.cat == "bld" and vo then
                F.wreck(nil)
            end
            V.removed(ev)
            if ev.owner == me and ev.how == "killed" and ev.cat == "unit" then A.voice("v_lost", 10) end
        elseif t == "clear" then
            game.clearTrees(ev.x, ev.z, ev.r)
        elseif t == "fell" then
            -- trees a vehicle rolled over tip away from it: the way it drives,
            -- and a little off to the side they stood on
            local fx, fz = math.sin(ev.h), math.cos(ev.h)
            if ev.back then fx, fz = -fx, -fz end
            for k = 1, #ev.trees - 2, 3 do
                local tx, tz = ev.trees[k], ev.trees[k + 1]
                F.treeDown(tx, tz)
                local rx, rz = tx - ev.x, tz - ev.z
                local rl = math.sqrt(rx * rx + rz * rz)
                if rl > 0.01 then rx, rz = rx / rl, rz / rl end
                if not (game.fellTree and game.fellTree(tx, tz, fx + rx * 0.5, fz + rz * 0.5)) then
                    game.clearTrees(tx, tz, 0.6)
                end
            end
            -- creak, crack and crash -- ten seconds long, so a vehicle ploughing
            -- through a wood starts a new one only now and then
            if F.visible(ev.x, ev.z) and H.time - (treeSoundAt or -1e9) > 1.5 then
                treeSoundAt = H.time
                F.sound("tree_fall", ev.x, V.groundY(ev.x, ev.z), ev.z, 1, 0.92 + math.random() * 0.16)
            end
        elseif t == "burn" then
            -- trees a hit set alight (x, z, scale triples)
            for k = 1, #ev.trees - 2, 3 do F.burnTree(ev.trees[k], ev.trees[k + 1], ev.trees[k + 2], ev.secs) end
        elseif t == "msg" then
            if ev.p == me or ev.p == -1 then
                H.message(ev.text, ev.sound == "error" and { 1, 0.35, 0.25 } or nil)
                local map = { lowpower = "v_lowpower", attacked = "v_attacked", unitattacked = "v_unitattack",
                              research = "v_research", nocash = "v_nocash", captured = "v_captured",
                              lost = "v_lost", storage = "v_storage", error = "error" }
                local cue = map[ev.sound or ""]
                if cue == "error" then A.play("error") elseif cue then A.voice(cue, 8) end
            end
        elseif t == "alert" then
            if ev.p == me then
                I.alert(ev.x, ev.z)
                H.alerts = H.alerts or {}
                H.alerts[#H.alerts + 1] = { x = ev.x, z = ev.z, t = H.time }
            end
        elseif t == "ready" then
            if ev.p == me then
                A.voice("v_ready", 1)
                H.message("Bereit zum Platzieren: " .. D.buildings[ev.type].name, { 0.4, 1, 0.5 })
            end
        elseif t == "produced" then
            local o = S.byId[ev.id]
            if ev.p == me then A.voice("v_unitready", 3) end
            if o then F.sound("unit_out", o.x, 2, o.z) end
        elseif t == "queued" then
            if ev.p == me then A.voice(D.units[ev.type] and "v_training" or "v_building", 2) end
        elseif t == "placed" or t == "deployed" then
            local o = S.byId[ev.id]
            if o then
                F.sound(t == "deployed" and "deploy" or "build_rise", o.x, 2, o.z)
                local gy = V.groundY(o.x, o.z)
                F.emitAt("FX Dust", o.x, gy + 0.5, o.z)
            end
        elseif t == "built" then
            local o = S.byId[ev.id]
            if o and o.owner == me then H.message(o.def.name .. " fertig") end
        elseif t == "captured" then
            local o = S.byId[ev.id]
            if o then F.sound("capture", o.x, 2, o.z) end
        elseif t == "unload" then
            local o = S.byId[ev.id]
            if o then F.sound("unload", o.x, 2, o.z, 0.6) end
        elseif t == "upgraded" then
            local o = S.byId[ev.id]
            if o and o.owner == me then A.voice("v_upgraded", 2) end
        elseif t == "defeat" then
            if ev.p == me then A.voice("v_defeat", 0) end
        elseif t == "gameover" then
            local won = S.players[me] and S.players[me].team == ev.team
            if won then A.voice("v_victory", 0) end
            result = { won = won, at = H.time }
        end
    end
    S.events = {}
end

-- Burning buildings: fire and smoke on whatever is badly hurt.
local burning = {}
local function updateBurning()
    for _, o in ipairs(S.objs) do
        if o.alive and o.cat == "bld" and o.built >= 1 then
            local f = o.hp / o.maxhp
            local b = burning[o.id]
            local vo = V.objs[o.id]
            if f < 0.5 and not b and vo and vo.shown then
                b = { smoke = F.loop("FX Smoke", o.x, (vo.y or 0) + (vo.top or 8) * 0.8, o.z) }
                burning[o.id] = b
            end
            if b and f < 0.25 and not b.fire and vo then
                b.fire = F.loop("FX Fire", o.x + 2, (vo.y or 0) + (vo.top or 8) * 0.5, o.z - 1)
            end
            if b and f >= 0.5 then F.release(b.smoke); F.release(b.fire); burning[o.id] = nil end
        end
    end
    for id, b in pairs(burning) do
        local o = S.byId[id]
        if not o or not o.alive then F.release(b.smoke); F.release(b.fire); burning[id] = nil end
    end
end

-- The mining sparkle and the harvester's hum.
local function updateAmbient(t)
    for _, o in ipairs(S.objs) do
        if o.alive and o.mining and S.tick - o.mining < 3 and (o.id + math.floor(t * 8)) % 6 == 0 then
            local vo = V.objs[o.id]
            if vo and vo.x and vo.shown then
                local fx, fz = math.sin(vo.h or 0), math.cos(vo.h or 0)
                F.emitAt("FX Energicum", vo.x + fx * 4.5, vo.y + 0.8, vo.z + fz * 4.5)
            end
        end
    end
end

-- --- Multiplayer: the lobby half (the game half is sw/session) ---------------------------
local function lobbyPoll()
    for _, m in ipairs(net.poll()) do
        local head, body = m:match("^(%S+)[ \n]?(.*)$")
        if head == "WELCOME" then
            myId = tonumber(body) or 0
            Mn.myId = myId
            Mn.screen = "rooms"
            Mn.status = "Verbunden."
            Mn.statusBad = false
            net.send("LIST")
        elseif head == "ROOMS" then
            Mn.rooms = {}
            for line in m:gmatch("\n([^\n]*)") do
                local f = U.split(line, "\t")
                Mn.rooms[#Mn.rooms + 1] = { name = f[1], players = tonumber(f[2]) or 0, max = tonumber(f[3]) or 2,
                                            started = f[4] == "1", config = f[5] }
            end
        elseif head == "ROOM" then
            local lines = U.split(m, "\n")
            local f = U.split(lines[1]:sub(6), "\t")
            local r = { name = f[1], host = tonumber(f[2]), max = tonumber(f[3]), started = f[4] == "1", config = f[5] or "", members = {} }
            for k = 2, #lines do
                local g = U.split(lines[k], "\t")
                r.members[#r.members + 1] = { id = tonumber(g[1]), name = g[2], data = g[3] }
            end
            Mn.room = r
            Mn.screen = "room"
        elseif head == "START" then
            local lines = U.split(m, "\n")
            local f = U.split(lines[1]:sub(7), "\t")
            local seed, mySlot, count = tonumber(f[1]), tonumber(f[3]), tonumber(f[4])
            local cfg = Mn.decodeData(f[5] or "")
            local players = {}
            for k = 2, #lines do
                local g = U.split(lines[k], "\t")
                local d = Mn.decodeData(g[4])
                players[#players + 1] = { name = g[3], color = d.c, team = d.t }
            end
            -- computer players the host asked for
            local used = {}
            for _, p in ipairs(players) do used[p.color] = true end
            for k = 1, cfg.a or 0 do
                local c = 0
                while used[c] and c < 3 do c = c + 1 end
                used[c] = true
                players[#players + 1] = { name = "KI " .. k, color = c, team = 10 + k, ai = true, aiLevel = cfg.l or 2 }
            end
            -- the same colour twice: make them distinct, the same way everywhere
            local seen = {}
            for _, p in ipairs(players) do
                while seen[p.color] do p.color = (p.color + 1) % 4 end
                seen[p.color] = true
            end
            netMode = nil
            if mpTest then
                -- in the test both machines let a computer brain play their side
                for _, p in ipairs(players) do if not p.ai then p.ai = true; p.aiLevel = 3 end end
            end
            beginGame(players, seed, mySlot, "net")
            if mpTest then V.hideFog = false; followAction = true end
        elseif head == "CHAT" then
            local name, text = body:match("^([^\t]*)\t(.*)$")
            Mn.chat[#Mn.chat + 1] = { name = name or "?", text = text or "" }
        elseif head == "ERROR" then
            Mn.status = body
            Mn.statusBad = true
        end
    end
    local st, err = net.status()
    if st == "closed" and netMode then
        Mn.status = "Verbindung getrennt: " .. (err or "")
        Mn.statusBad = true
        Mn.screen = "mp"
        netMode = nil
    end
end

local function menuAction(act)
    if not act then return end
    local k = act.kind
    if k == "quit" then
        if game.quit then game.quit() else game.loadScene("") end   -- the player closes, the editor stops Play
    elseif k == "skirmish" then
        startSkirmish(act.opts)
    elseif k == "connect" or k == "host" then
        local port = tonumber(Mn.port) or 27960
        if k == "host" then
            local ok, err = net.serve(port)
            if not ok then Mn.status = "Hosten fehlgeschlagen: " .. tostring(err); Mn.statusBad = true; return end
            addresses = net.addresses()
        end
        local ok, err = net.connect(k == "host" and "127.0.0.1" or Mn.host, port)
        if not ok then Mn.status = "Verbindung fehlgeschlagen: " .. tostring(err); Mn.statusBad = true; return end
        Mn.status = "Verbinde ..."
        Mn.statusBad = false
        netMode = "connecting"
        net.send("HELLO " .. Mn.name .. "\tsteelwars\t" .. D.VERSION)
    elseif k == "disconnect" then
        net.close()
        net.stopServer()
        netMode = nil
    elseif k == "list" then
        net.send("LIST")
    elseif k == "create" then
        net.send(string.format("CREATE 4\t%s\ta=0;l=2", (Mn.name .. "s Raum"):sub(1, 30)))
        Mn.myData = { c = Mn.opts.color, t = 0, r = 0 }
        net.send("SET " .. Mn.encodeData(Mn.myData))
    elseif k == "join" then
        net.send("JOIN " .. act.room)
        Mn.myData = { c = (Mn.opts.color + 1) % 4, t = 1, r = 0 }
        net.send("SET " .. Mn.encodeData(Mn.myData))
    elseif k == "set" then
        net.send("SET " .. Mn.encodeData(Mn.myData))
    elseif k == "config" then
        net.send(string.format("CONFIG a=%d;l=%d", act.ai, act.lvl))
    elseif k == "start" then
        net.send("START")
    elseif k == "leave" then
        net.send("LEAVE")
        Mn.screen = "rooms"
        net.send("LIST")
    elseif k == "resume" then
        state = "game"
        N.paused = false
    elseif k == "surrender" then
        N.send("gg")
        state = "game"
        N.paused = false
    elseif k == "quitgame" then
        game.restart()
    end
end

-- --- The engine's entry points -------------------------------------------------------------
function start(e)
    requireAll()
    game.showCursor(true)
    game.setCrosshair(false)
    game.setFocus(1, 100000)
    if llm then llm.setHost(ollamaHost, ollamaPort) end
    state = "loading"
    loader = coroutine.create(function() load(e) end)
end

local fpsAvg = 60
local lastError, errorCount = nil, 0
local frame

function update(e, dt, t)
    local ok, err = xpcall(frame, debug.traceback, e, dt, t)
    if not ok then
        errorCount = errorCount + 1
        if errorCount <= 3 then
            game.log("Steelwars error: " .. tostring(err))
            game.saveData("lasterror", { error = tostring(err), time = t })
        end
        lastError = tostring(err)
    end
    if lastError then
        game.hudText(20, 60, "Skriptfehler (" .. errorCount .. "): " .. lastError:sub(1, 160), 16, 1, 0.3, 0.2, 1, 0, false)
    end
end

frame = function(e, dt, t)
    game.setHud("")
    if dt > 0 then fpsAvg = fpsAvg * 0.95 + (1 / dt) * 0.05 end
    if state == "loading" then
        local ok, err = coroutine.resume(loader)
        if not ok then game.log("Steelwars: loading failed: " .. tostring(err)); state = "error"; loadMsg = tostring(err) end
        if coroutine.status(loader) == "dead" and state == "loading" then
            state = "menu"
            if musicOn then A.startMenuMusic() end
            if autoStart == "skirmish" then startSkirmish(Mn.opts) end
            if autoStart == "mphost" or autoStart == "mpjoin" then
                -- two instances on one machine play each other (testing)
                Mn.name = (autoStart == "mphost") and "Host" or "Gast"
                Mn.port = "27961"
                state = "menu"
                mpTest = { role = autoStart, t = 0 }
                menuAction({ kind = (autoStart == "mphost") and "host" or "connect" })
            end
            if autoStart == "uitest" then
                Mn.opts.enemies = 1
                Mn.opts.level = 1
                startSkirmish(Mn.opts)
                uiTest = { t = 0, step = 1, log = {} }
            end
            if autoStart == "agentvsai" or autoStart == "agentvsagent" then
                Mn.opts.enemies = 1
                Mn.opts.side = "agent"
                Mn.opts.foes = (autoStart == "agentvsagent") and "agenten" or "ki"
                startSkirmish(Mn.opts)
                followAction = true
            end
            if autoStart == "aivsai" then
                Mn.opts.enemies = 1
                startSkirmish(Mn.opts, true)
                V.hideFog = false
                followAction = lookField == 0
                N.speed = 3
                if lookField > 0 and markers.fields[lookField] then
                    local f = markers.fields[lookField]
                    C.jump(f[1], f[2]); C.tdist, C.dist = 60, 60
                end
            end
        end
        local W, Hh = game.hudSize()
        game.hudRect(0, 0, W, Hh, 0.01, 0.012, 0.015, 1)
        if game.imageSize("sw_logo.png") then
            game.hudImage("sw_logo.png", W * 0.5 - 420, Hh * 0.26, 840, 240, 1, 1, 1, 1)
        else
            game.hudText(W * 0.5, Hh * 0.42, "STEELWARS", 96, 1, 0.62, 0.12, 1, 0.5, true)
        end
        game.hudText(W * 0.5, Hh * 0.58, loadMsg, 24, 0.6, 0.65, 0.7, 1, 0.5)
        game.hudRect(W * 0.3, Hh * 0.64, W * 0.4, 8, 0.1, 0.12, 0.14, 1, 4)
        game.hudRect(W * 0.3, Hh * 0.64, W * 0.4 * loadProg, 8, 1, 0.62, 0.12, 1, 4)
        return
    end
    if state == "error" then
        local W, Hh = game.hudSize()
        game.hudText(W * 0.5, Hh * 0.45, "Fehler: " .. loadMsg, 22, 1, 0.3, 0.2, 1, 0.5)
        return
    end
    A.update(dt, state == "game")
    if state == "menu" then
        -- the battlefield circles slowly behind the menu
        menuCam = menuCam + dt * 0.04
        C.tx = markers.cx + math.sin(menuCam) * mapSize * 0.25
        C.tz = markers.cz + math.cos(menuCam * 0.7) * mapSize * 0.25
        C.tyaw = menuCam * 1.3
        C.tdist = 210
        C.update(dt, nil, nil, false, true, 0)
        if netMode then lobbyPoll() end
        if mpTest then
            mpTest.t = mpTest.t + dt
            local r = Mn.room
            if Mn.screen == "rooms" and mpTest.role == "mphost" and not mpTest.created then
                mpTest.created = true
                menuAction({ kind = "create" })
            elseif Mn.screen == "rooms" and mpTest.role == "mpjoin" then
                if #Mn.rooms > 0 then menuAction({ kind = "join", room = Mn.rooms[1].name })
                elseif mpTest.t - (mpTest.listed or 0) > 1 then mpTest.listed = mpTest.t; net.send("LIST") end
            elseif Mn.screen == "room" and r then
                if Mn.myData.r ~= 1 then Mn.myData.r = 1; menuAction({ kind = "set" }) end
                local all = #r.members >= 2
                for _, m in ipairs(r.members) do if Mn.decodeData(m.data).r ~= 1 then all = false end end
                if all and mpTest.role == "mphost" and not mpTest.started then mpTest.started = true; menuAction({ kind = "start" }) end
            end
        end
        menuAction(Mn.draw(dt, { addresses = addresses }))
        return
    end
    -- in a game
    local mx, my, over = game.mousePos()
    local inMenu = (Mn.screen == "pause" or Mn.screen == "help") and state == "pause"
    if state == "game" or state == "pause" then
        local a = N.update(dt)
        handleEvents()
        G.update(S, N.sendAs)
        St.update(S, V.me, Dr.active(), N.send)
        F.camX, F.camZ, F.camDist = C.x, C.z, C.dist
        V.update(a, t, dt)
        F.update(dt)
        updateBurning()
        updateAmbient(t)
        if Dr.active() then Dr.camera(dt, F.shake())
        else C.update(dt, mx, my, over and not I.overHud, state ~= "game", F.shake()) end
        if state == "game" then
            if uiTest then uiTestStep(dt) end
            if Dr.active() then Dr.update(dt, mx, my, over) else I.update(dt, mx, my, over) end
            H.draw(dt, Dr.active())
            if Dr.active() then Dr.draw() end
            G.draw(S)
            if game.keyPressed(game.KEY_F2) then G.show = not G.show end
            if I.wantMenu then
                I.wantMenu = false
                state = "pause"
                Mn.screen = "pause"
                if N.mode == "local" then N.paused = true end
            end
            if game.keyPressed(game.KEY_P) and N.mode == "local" then N.paused = not N.paused end
            if N.paused and state == "game" then
                local W = game.hudSize()
                game.hudText(W * 0.5 - 180, 120, "PAUSE (P)", 48, 1, 0.62, 0.12, 1, 0.5, true)
            end
            if N.desync then
                H.message("Spielstände weichen ab (Desync)!", { 1, 0.3, 0.2 })
                N.desync = false
                if mpTest then mpTest.desyncs = (mpTest.desyncs or 0) + 1 end
            end
            if mpTest and N.turn > 0 and N.turn % 200 == 0 and mpTest.lastLog ~= N.turn then
                mpTest.lastLog = N.turn
                mpTest.log = mpTest.log or {}
                mpTest.log[#mpTest.log + 1] = { turn = N.turn, hash = S.hash(), objs = #S.objs, lag = N.lag }
                game.saveData("mptest_" .. mpTest.role, { log = mpTest.log, desyncs = mpTest.desyncs or 0 })
            end
            if N.lost and not N.lostTold then
                N.lostTold = true
                H.message("Verbindung zum Server verloren -- die Partie steht", { 1, 0.3, 0.2 })
            end
            for _, l in ipairs(N.left) do H.message(l.name .. " hat das Spiel verlassen") end
            N.left = {}
            if result and H.time - result.at > 4 then
                Dr.reset()
                state = "result"
                Mn.screen = "result"
            end
        else
            menuAction(Mn.draw(dt, {}))
            if game.keyPressed(game.KEY_ESCAPE) and Mn.screen == "pause" then menuAction({ kind = "resume" }) end
        end
    elseif state == "result" then
        local stats = {}
        for p = 0, S.nPlayers - 1 do
            local pl = S.players[p]
            stats[#stats + 1] = { name = pl.name, color = pl.color, built = pl.stats.built, killed = pl.stats.killed, lost = pl.stats.lost }
        end
        local a = N.update(dt)
        handleEvents()
        V.update(a, t, dt)
        F.update(dt)
        C.update(dt, mx, my, false, true, 0)
        menuAction(Mn.draw(dt, { result = { won = result and result.won, stats = stats,
            line = (result and result.won) and "Der Feind ist vernichtet." or "Deine Armee ist gefallen." } }))
    end
    -- testing: what the simulation is doing, for reading outside the game
    if followAction and S.tick and S.tick > 0 and S.tick % 600 == 0 and S.tick ~= (lastDump or 0) then
        lastDump = S.tick
        local rep = { tick = S.tick, players = {} }
        for p = 0, S.nPlayers - 1 do
            local pl = S.players[p]
            local r = { cells = math.floor(pl.cells), raw = math.floor(pl.raw), harvested = math.floor(pl.stats.harvested),
                        power = pl.power, use = pl.use, units = {}, harv = {} }
            for _, o in ipairs(S.objs) do
                if o.alive and o.owner == p then
                    r.units[o.type] = (r.units[o.type] or 0) + 1
                    if o.type == "harvester" then
                        local od = o.orders[1]
                        r.harv[#r.harv + 1] = string.format("%s/%s at %.0f,%.0f carry %.0f stuck %d",
                            od and od.k or "-", od and tostring(od.st) or "-", o.x, o.z, o.carry, o.stuck or 0)
                    end
                end
            end
            rep.players[#rep.players + 1] = r
        end
        game.saveData("debug_state_" .. S.tick, rep)
    end
    if showFps then
        local W = game.hudSize()
        game.hudText(W - 400, 60, string.format("%.0f fps  ·  %d Objekte  ·  Turn %d", fpsAvg, #S.objs, N.turn or 0), 16, 0.7, 0.7, 0.7, 1, 1)
    end
end
