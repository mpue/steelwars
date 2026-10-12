-- STEELWARS -- the screens around a game: title, skirmish setup, the
-- multiplayer lobby (host or join a relay, rooms, players), the pause menu,
-- the result. Drawn on the HUD canvas over the slowly circling battlefield.
local D = require("sw.defs")
local U = require("sw.util")
local A = require("sw.audio")
local K = require("sw.skin")

local Mn = {}
local floor, min, max, sin = math.floor, math.min, math.max, math.sin

Mn.screen = "title"
Mn.time = 0
Mn.opts = { enemies = 1, level = 2, color = 1, cells = 6000, speed = 1, side = "mensch", foes = "ki" }
Mn.name = "Kommandant"
Mn.host = "127.0.0.1"
Mn.port = "27960"
Mn.focus = nil          -- which text field takes the keys
Mn.status = ""
Mn.rooms = {}
Mn.room = nil
Mn.myData = { c = 1, t = 0, r = 0 }
Mn.chat = {}

local AMBER = { 1.0, 0.62, 0.12 }
local WHITE = { 0.92, 0.94, 0.96 }
local DIM = { 0.55, 0.6, 0.65 }
local RED = { 1.0, 0.3, 0.2 }
local GREEN = { 0.35, 1.0, 0.45 }

local function text(x, y, s, size, c, a, align, bold) game.hudText(x, y, s, size, c[1], c[2], c[3], a or 1, align or 0, bold or false) end
local function inside(mx, my, x, y, w, h) return mx and mx >= x and mx <= x + w and my >= y and my <= y + h end

local click
local function button(x, y, w, h, label, mx, my, opts)
    opts = opts or {}
    local hot = inside(mx, my, x, y, w, h) and not opts.disabled
    if not K.button(x, y, w, h, opts.on and "on" or (hot and "hot" or nil), opts.disabled) then
        local r, g, b = 0.06, 0.07, 0.09
        if opts.on then r, g, b = 0.28, 0.18, 0.04 elseif hot then r, g, b = 0.13, 0.15, 0.18 end
        game.hudRect(x, y, w, h, r, g, b, 0.94, 6)
        local fc = opts.on and AMBER or (hot and { 0.85, 0.88, 0.9 } or { 0.3, 0.34, 0.38 })
        game.hudFrame(x, y, w, h, fc[1], fc[2], fc[3], 1, hot and 2.5 or 1.5, 6)
    end
    local tc = opts.disabled and DIM or (opts.on and { 0.8, 0.96, 1.0 } or (hot and { 1, 0.85, 0.6 } or WHITE))
    text(x + w * 0.5, y + h * 0.5 - (opts.size or 26) * 0.6, label, opts.size or 26, tc, 1, 0.5, true)
    if hot and click then A.play("click"); return true end
    return false
end

local function field(x, y, w, label, value, key, mx, my)
    text(x, y - 26, label, 18, DIM)
    local focused = Mn.focus == key
    if not K.nine("ui_panel", x, y, w, 50, 16, 1, 1, 1, 1) then
        game.hudRect(x, y, w, 50, 0.03, 0.035, 0.045, 0.95, 5)
    end
    local fc = focused and AMBER or { 0.3, 0.34, 0.38 }
    if focused then K.brackets(x - 3, y - 3, w + 6, 56, 12, fc[1], fc[2], fc[3], 1, 2) end
    local caret = (focused and floor(Mn.time * 2) % 2 == 0) and "_" or ""
    text(x + 14, y + 11, value .. caret, 24, WHITE)
    if click and inside(mx, my, x, y, w, 50) then Mn.focus = key end
end

-- Typing into the focused field (letters, digits, dot, minus, backspace).
local function typing(value, maxLen)
    local shift = game.keyDown(game.KEY_LSHIFT) or game.keyDown(game.KEY_RSHIFT)
    for c = 65, 90 do
        if game.keyPressed(c) and #value < maxLen then value = value .. string.char(shift and c or c + 32) end
    end
    for c = 48, 57 do
        if game.keyPressed(c) and #value < maxLen then value = value .. string.char(c) end
    end
    if game.keyPressed(46) and #value < maxLen then value = value .. "." end
    if game.keyPressed(45) and #value < maxLen then value = value .. "-" end
    if game.keyPressed(game.KEY_SPACE) and #value < maxLen then value = value .. " " end
    if game.keyPressed(game.KEY_BACKSPACE) and #value > 0 then value = value:sub(1, -2) end
    return value
end

local function cycle(v, lo, hi, d) v = v + (d or 1); if v > hi then v = lo elseif v < lo then v = hi end; return v end

local function backdrop(W, H)
    -- darken the battlefield behind, strongest at the edges
    game.hudGradient(0, 0, W, H * 0.5, 0, 0.01, 0.02, 0.8, 0, 0, 0, 0.35)
    game.hudGradient(0, H * 0.5, W, H * 0.5, 0, 0, 0, 0.35, 0, 0.01, 0.02, 0.88)
    -- thin amber rails at top and bottom, a slow scan line
    game.hudRect(0, 0, W, 3, 1.0, 0.62, 0.12, 0.6)
    game.hudRect(0, H - 3, W, 3, 1.0, 0.62, 0.12, 0.6)
    K.scan(0, 0, W, H, Mn.time * 0.5, 1.0, 0.62, 0.12)
end

local function title(W, y)
    local pulse = 0.85 + 0.15 * sin(Mn.time * 1.3)
    if game.imageSize("sw_logo.png") then
        local iw, ih = game.imageSize("sw_logo.png")
        local h = 250
        local w = h * iw / ih
        game.hudImage("sw_logo.png", W * 0.5 - w * 0.5, y, w, h, 1, 1, 1, 1)
    else
        text(W * 0.5, y + 30, "STEELWARS", 120, { AMBER[1] * pulse, AMBER[2] * pulse, AMBER[3] * pulse }, 1, 0.5, true)
        text(W * 0.5, y + 170, "Roboterarmeen kämpfen um Ruhm und Ehre", 26, DIM, 1, 0.5)
    end
end

local function teamName(c) return D.teams[c].name end
local function levelName(l) return ({ "Leicht", "Mittel", "Schwer" })[l] end

function Mn.encodeData(d) return string.format("c=%d;t=%d;r=%d", d.c, d.t, d.r) end
function Mn.decodeData(s)
    local d = { c = 0, t = 0, r = 0 }
    for k, v in (s or ""):gmatch("(%a)=(%-?%d+)") do d[k] = tonumber(v) end
    return d
end

-- --- Screens ------------------------------------------------------------------------
-- Returns an action table when the player chose something that leaves the menu.
function Mn.draw(dt, ctx)
    Mn.time = Mn.time + dt
    A.clock = A.clock + 0
    local W, H = game.hudSize()
    local mx, my, over = game.mousePos()
    click = over and game.mousePressed(game.MOUSE_LEFT)
    backdrop(W, H)
    local cx = W * 0.5
    local act = nil
    local s = Mn.screen

    if s == "title" then
        title(W, 120)
        local bw, bh = 460, 74
        local y = 440
        K.window(cx - bw / 2 - 50, y - 44, bw + 100, 4 * 92 + 70, 0.92)
        if button(cx - bw / 2, y, bw, bh, "Gefecht", mx, my) then Mn.screen = "skirmish" end
        if button(cx - bw / 2, y + 92, bw, bh, "Mehrspieler", mx, my) then Mn.screen = "mp" end
        if button(cx - bw / 2, y + 184, bw, bh, "Steuerung", mx, my) then Mn.screen = "help" end
        if button(cx - bw / 2, y + 276, bw, bh, "Beenden", mx, my) then act = { kind = "quit" } end
        text(W - 20, H - 36, "Fitzel Engine  ·  v" .. D.VERSION, 16, DIM, 1, 1)

    elseif s == "skirmish" then
        text(cx, 110, "GEFECHT", 54, AMBER, 1, 0.5, true)
        local o = Mn.opts
        local x0, y = cx - 300, 200
        K.window(x0 - 50, y - 40, 720, 7 * 80 + 70, 0.92)
        local function pickFrom(list, v, d)
            local k = 1
            for i, x in ipairs(list) do if x == v then k = i end end
            return list[cycle(k, 1, #list, d)]
        end
        local rows = {
            -- a side can be played by a language-model staff (sw/agent.lua)
            { "Deine Seite", o.side == "agent" and "Agent" or "Mensch", function(d) o.side = pickFrom({ "mensch", "agent" }, o.side, d) end },
            { "Gegner sind", ({ ki = "KI", agenten = "Agenten", gemischt = "Gemischt" })[o.foes] or "KI",
              function(d) o.foes = pickFrom({ "ki", "agenten", "gemischt" }, o.foes, d) end },
            { "Gegner", tostring(o.enemies), function(d) o.enemies = cycle(o.enemies, 1, 3, d) end },
            { "Schwierigkeit", levelName(o.level), function(d) o.level = cycle(o.level, 1, 3, d) end },
            { "Deine Farbe", teamName(o.color), function(d) o.color = cycle(o.color, 0, 3, d) end },
            { "Startkapital", U.fmtInt(o.cells), function(d)
                local list = { 3000, 6000, 10000, 20000 }
                local k = 1
                for i, v in ipairs(list) do if v == o.cells then k = i end end
                o.cells = list[cycle(k, 1, #list, d)]
            end },
            { "Spieltempo", ({ [1] = "Normal", [1.5] = "Schnell", [2] = "Sehr schnell" })[o.speed] or "Normal", function(d)
                local list = { 1, 1.5, 2 }
                local k = 1
                for i, v in ipairs(list) do if v == o.speed then k = i end end
                o.speed = list[cycle(k, 1, #list, d)]
            end },
        }
        for _, r in ipairs(rows) do
            text(x0, y + 16, r[1], 28, DIM)
            if button(x0 + 300, y, 70, 60, "<", mx, my) then r[3](-1) end
            if not K.nine("ui_panel", x0 + 380, y, 160, 60, 16, 1, 1, 1, 1) then
                game.hudRect(x0 + 380, y, 160, 60, 0.04, 0.045, 0.055, 0.95, 5)
            end
            text(x0 + 460, y + 14, r[2], 28, WHITE, 1, 0.5, true)
            if button(x0 + 550, y, 70, 60, ">", mx, my) then r[3](1) end
            y = y + 80
        end
        if o.side == "agent" or o.foes ~= "ki" then
            text(cx, y + 2, "Agenten denken mit einem Sprachmodell (Ollama) -- F2 im Spiel zeigt ihren Stab.", 18, DIM, 1, 0.5)
        end
        if button(cx - 240, y + 40, 480, 80, "Schlacht beginnen", mx, my, { on = true, size = 30 }) then
            act = { kind = "skirmish", opts = o }
        end
        if button(cx - 120, y + 140, 240, 56, "Zurück", mx, my, { size = 22 }) then Mn.screen = "title" end

    elseif s == "mp" then
        text(cx, 110, "MEHRSPIELER", 54, AMBER, 1, 0.5, true)
        local x0 = cx - 300
        field(x0, 250, 600, "Dein Name", Mn.name, "name", mx, my)
        field(x0, 360, 420, "Server (IP-Adresse oder Name)", Mn.host, "host", mx, my)
        field(x0 + 440, 360, 160, "Port", Mn.port, "port", mx, my)
        if Mn.focus == "name" then Mn.name = typing(Mn.name, 18)
        elseif Mn.focus == "host" then Mn.host = typing(Mn.host, 40)
        elseif Mn.focus == "port" then Mn.port = typing(Mn.port, 5) end
        if button(x0, 460, 290, 70, "Verbinden", mx, my) then act = { kind = "connect" } end
        if button(x0 + 310, 460, 290, 70, "Selbst hosten", mx, my) then act = { kind = "host" } end
        text(cx, 560, Mn.status, 22, Mn.statusBad and RED or DIM, 1, 0.5)
        if ctx and ctx.addresses and #ctx.addresses > 0 then
            text(cx, 600, "Deine Adresse im Netz: " .. table.concat(ctx.addresses, ", "), 18, DIM, 1, 0.5)
        end
        text(cx, 650, "Eigener Server: fitzelserver.exe --port 27960 (läuft ohne Spiel weiter)", 17, DIM, 1, 0.5)
        if button(cx - 120, 720, 240, 56, "Zurück", mx, my, { size = 22 }) then act = { kind = "disconnect" }; Mn.screen = "title" end

    elseif s == "rooms" then
        text(cx, 110, "SPIELRÄUME", 54, AMBER, 1, 0.5, true)
        local x0, y = cx - 400, 220
        if #Mn.rooms == 0 then text(cx, y + 20, "Noch keine Räume -- eröffne einen.", 24, DIM, 1, 0.5) end
        for k, r in ipairs(Mn.rooms) do
            local label = string.format("%s   (%d / %d)%s", r.name, r.players, r.max, r.started and "  läuft" or "")
            if button(x0, y, 800, 56, label, mx, my, { size = 22, disabled = r.started or r.players >= r.max }) then
                act = { kind = "join", room = r.name }
            end
            y = y + 66
            if k >= 8 then break end
        end
        y = max(y, 560)
        if button(x0, y + 20, 390, 66, "Raum eröffnen", mx, my) then act = { kind = "create" } end
        if button(x0 + 410, y + 20, 390, 66, "Aktualisieren", mx, my) then act = { kind = "list" } end
        text(cx, y + 110, Mn.status, 20, Mn.statusBad and RED or DIM, 1, 0.5)
        if button(cx - 120, y + 150, 240, 56, "Zurück", mx, my, { size = 22 }) then act = { kind = "disconnect" }; Mn.screen = "mp" end

    elseif s == "room" then
        local r = Mn.room
        text(cx, 90, r and r.name or "Raum", 48, AMBER, 1, 0.5, true)
        local x0, y = cx - 480, 180
        text(x0, y, "Spieler", 20, DIM); text(x0 + 420, y, "Farbe", 20, DIM); text(x0 + 620, y, "Team", 20, DIM); text(x0 + 800, y, "Bereit", 20, DIM)
        y = y + 34
        local isHost = r and r.host == Mn.myId
        local allReady = true
        for _, p in ipairs(r and r.members or {}) do
            local d = Mn.decodeData(p.data)
            local mine = p.id == Mn.myId
            if not K.nine("ui_panel", x0 - 10, y - 6, 960, 58, 16, 1, 1, 1, 1) then
                game.hudRect(x0 - 10, y - 6, 960, 58, 0.04, 0.05, 0.06, 0.9, 5)
            end
            local tc = D.teams[d.c] or D.teams[0]
            game.hudRect(x0, y + 8, 14, 30, tc.r, tc.g, tc.b, 1, 3)
            text(x0 + 26, y + 8, p.name .. ((p.id == (r and r.host)) and "  (Host)" or ""), 24, WHITE, 1, 0, true)
            if mine then
                if button(x0 + 420, y, 170, 46, teamName(d.c), mx, my, { size = 20 }) then
                    Mn.myData.c = cycle(Mn.myData.c, 0, 3); act = { kind = "set" } end
                if button(x0 + 620, y, 150, 46, "Team " .. (d.t + 1), mx, my, { size = 20 }) then
                    Mn.myData.t = cycle(Mn.myData.t, 0, 3); act = { kind = "set" } end
                if button(x0 + 800, y, 140, 46, d.r == 1 and "Ja" or "Nein", mx, my, { size = 20, on = d.r == 1 }) then
                    Mn.myData.r = 1 - Mn.myData.r; act = { kind = "set" } end
            else
                text(x0 + 505, y + 10, teamName(d.c), 22, WHITE, 1, 0.5)
                text(x0 + 695, y + 10, "Team " .. (d.t + 1), 22, WHITE, 1, 0.5)
                text(x0 + 870, y + 10, d.r == 1 and "Ja" or "Nein", 22, d.r == 1 and GREEN or DIM, 1, 0.5, true)
            end
            if d.r ~= 1 then allReady = false end
            y = y + 66
        end
        -- computer players, set by the host (part of the room's config)
        local cfg = Mn.decodeData(r and r.config or "")
        local ai = cfg.a or 0
        text(x0, y + 14, "Computergegner: " .. ai .. "  (" .. levelName(max(1, min(3, cfg.l or 2))) .. ")", 22, DIM)
        if isHost then
            if button(x0 + 420, y + 4, 60, 46, "-", mx, my) then act = { kind = "config", ai = max(0, ai - 1), lvl = cfg.l or 2 } end
            if button(x0 + 490, y + 4, 60, 46, "+", mx, my) then act = { kind = "config", ai = min(3, ai + 1), lvl = cfg.l or 2 } end
            if button(x0 + 570, y + 4, 200, 46, levelName(max(1, min(3, cfg.l or 2))), mx, my, { size = 20 }) then
                act = { kind = "config", ai = ai, lvl = cycle(cfg.l or 2, 1, 3) } end
        end
        y = y + 90
        -- chat
        for k = max(1, #Mn.chat - 4), #Mn.chat do
            local c = Mn.chat[k]
            if c then text(x0, y, c.name .. ": " .. c.text, 19, DIM); y = y + 24 end
        end
        y = max(y, 720)
        if isHost then
            local n = #(r and r.members or {}) + ai
            if button(cx - 220, y + 10, 440, 74, "Spiel starten", mx, my, { on = allReady and n >= 2, disabled = not allReady or n < 2, size = 30 }) then
                act = { kind = "start" }
            end
            if not allReady then text(cx, y + 92, "Alle Spieler müssen bereit sein.", 18, DIM, 1, 0.5) end
        else
            text(cx, y + 30, "Warte auf den Host ...", 24, DIM, 1, 0.5)
        end
        if button(cx - 120, y + 120, 240, 56, "Verlassen", mx, my, { size = 22 }) then act = { kind = "leave" } end
        text(cx, y + 190, Mn.status, 20, Mn.statusBad and RED or DIM, 1, 0.5)

    elseif s == "help" then
        text(cx, 80, "STEUERUNG", 54, AMBER, 1, 0.5, true)
        local lines = {
            { "Linksklick", "Auswählen (Doppelklick: alle dieses Typs)  ·  Ziehen: Rahmen" },
            { "Rechtsklick", "Bewegen, Angreifen, Ernten, Reparieren, Einsteigen, Übernehmen" },
            { "W A S D / Pfeile", "Kamera schieben (auch am Bildschirmrand)" },
            { "Q / E", "Kamera drehen" },
            { "Mausrad / R F", "Zoomen" },
            { "Strg + 1..9", "Gruppe speichern  ·  1..9 abrufen, zweimal: hinfahren" },
            { "Strg + A", "Alle Kampfeinheiten" },
            { "T / G / Z / B", "Stopp / Halten / Angriff-Zug (dann Klick) / zur Werkstatt" },
            { "X", "Ausbauen (Baufahrzeug) · Fliegen (Terminator) · Entladen" },
            { "C", "Selbst steuern: W S A D, Maus zielt, Klick feuert" },
            { "Tab", "Zwischen Fahrersitz und Kommando wechseln" },
            { "V", "Beim Fahren: Verwalter führt die Basis an/aus" },
            { "H / Leertaste", "Zur Basis / zur letzten Meldung" },
            { "V / N / M / Entf", "Sammelpunkt / Verstärken / Erweitern / Verkaufen" },
            { "P", "Pause (Gefecht gegen KI)" },
            { "F2", "Stab der Agenten ein-/ausblenden" },
            { "Esc", "Abbrechen / Menü" },
        }
        local y = 170
        K.window(cx - 560, 140, 1120, #lines * 46 + 52, 0.92)
        for _, l in ipairs(lines) do
            text(cx - 60, y, l[1], 24, AMBER, 1, 1, true)
            text(cx - 30, y, l[2], 24, WHITE)
            y = y + 46
        end
        if button(cx - 120, y + 30, 240, 56, "Zurück", mx, my, { size = 22 }) then Mn.screen = Mn.backTo or "title"; Mn.backTo = nil end

    elseif s == "pause" then
        game.hudRect(0, 0, W, H, 0, 0, 0, 0.5)
        text(cx, 220, "PAUSE", 64, AMBER, 1, 0.5, true)
        local bw = 420
        K.window(cx - bw / 2 - 50, 300, bw + 100, 430, 0.94)
        if button(cx - bw / 2, 340, bw, 70, "Weiterspielen", mx, my) then act = { kind = "resume" } end
        if button(cx - bw / 2, 430, bw, 70, "Steuerung", mx, my) then Mn.screen = "help"; Mn.backTo = "pause" end
        if button(cx - bw / 2, 520, bw, 70, "Aufgeben", mx, my) then act = { kind = "surrender" } end
        if button(cx - bw / 2, 610, bw, 70, "Hauptmenü", mx, my) then act = { kind = "quitgame" } end

    elseif s == "result" then
        local res = ctx and ctx.result or {}
        text(cx, 160, res.won and "SIEG" or "NIEDERLAGE", 110, res.won and GREEN or RED, 1, 0.5, true)
        text(cx, 300, res.line or "", 26, DIM, 1, 0.5)
        local y = 380
        for _, row in ipairs(res.stats or {}) do
            local c = D.teams[row.color] or D.teams[0]
            game.hudRect(cx - 420, y, 12, 30, c.r, c.g, c.b, 1, 3)
            text(cx - 400, y, row.name, 24, WHITE, 1, 0, true)
            text(cx - 60, y, "gebaut " .. row.built, 22, DIM)
            text(cx + 100, y, "zerstört " .. row.killed, 22, DIM)
            text(cx + 260, y, "verloren " .. row.lost, 22, DIM)
            y = y + 44
        end
        if button(cx - 200, y + 60, 400, 70, "Hauptmenü", mx, my) then act = { kind = "quitgame" } end
    end

    if click and not act and Mn.focus and not over then Mn.focus = nil end
    return act
end

return Mn
