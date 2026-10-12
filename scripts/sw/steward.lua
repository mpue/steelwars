-- STEELWARS -- the steward: while you sit in a vehicle, someone minds the base.
--
-- The computer opponent's brain (sw/ai, A.thinkWith) runs for your side with
-- the plan { steward = true }: it places what is ready, keeps power and
-- harvesters up, builds towers, researches and keeps the factories busy --
-- but it never moves the construction vehicle, never attacks, and of your army
-- only the idle units near home turn on an enemy at the base. The unit you
-- drive is never its business.
--
-- It runs outside the simulation, on your machine only, and its orders go out
-- like your clicks (I.send), so a network game stays in step. V in the driver's
-- seat switches it off and on; the choice holds until you change it.
local D = require("sw.defs")
local AI = require("sw.ai")
local H = require("sw.hud")

local W = {}
local floor = math.floor

W.on = true           -- the player's choice
W.active = false      -- minding the base right now
local brain, ctx, due = nil, nil, nil
local alarmAt = -1e9  -- the last "base under attack" said (simulation seconds)

local AMBER = { 1.0, 0.62, 0.12 }
local DIM = { 0.7, 0.75, 0.8 }

-- A new game: nobody minds anything yet.
function W.reset()
    W.active = false
    brain, ctx, due = nil, nil, nil
    alarmAt = -1e9
end

-- What it does, said in the messages: buildings and research, not every soldier.
local function tell(line, now)
    local k, a, b = line:match("^(%a+) (%S+) ?(%S*)")
    if k == "pr" then
        local d = D.buildings[b]
        if d then H.message("Verwalter: " .. (d.name or b) .. " in Auftrag", DIM) end
    elseif k == "pl" then
        local d = D.buildings[a]
        if d then H.message("Verwalter: " .. (d.name or a) .. " gesetzt", DIM) end
    elseif k == "rs" then
        local r = D.researchByKey[b]
        if r then H.message("Verwalter: Forschung " .. r.name, DIM) end
    elseif k == "am" and now - alarmAt > 15 then
        alarmAt = now
        H.message("Verwalter: Angriff auf die Basis -- Verteidiger rücken aus", AMBER)
    end
end

-- Every frame. `driving`: a unit is steered by hand; `send` puts a line out.
function W.update(S, me, driving, send)
    local pl = S.players[me]
    local want = (driving and W.on and pl ~= nil and pl.alive and not S.over) and true or false
    if want ~= W.active then
        W.active = want
        if want then H.message("Verwalter übernimmt die Basis (V)", AMBER)
        elseif not S.over then H.message("Basis wieder in deiner Hand", AMBER) end
    end
    if not want then return end
    if not brain then
        brain = {}
        ctx = {
            plan = { steward = true },
            rnd = math.random,
            order = function(line) send(line); tell(line, S.tick * D.TICK) end,
        }
    end
    -- as often as the hardest computer opponent thinks
    local now = floor(S.tick / AI.thinkTicks(3))
    if now == due then return end
    due = now
    AI.thinkWith(S, me, brain, ctx)
end

return W
