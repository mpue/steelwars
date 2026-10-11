-- STEELWARS -- the look of the command screen: armoured frames, buttons and
-- slots painted in ComfyUI (design/comfy_ui.py) and cut into pieces by
-- design/ui_cut.py. Every piece is drawn as a nine-slice (corners keep their
-- size, edges and middle stretch), so one picture serves any panel size.
-- Without the pictures everything falls back to plain rectangles.
local K = {}

-- name -> border of the nine-slice in source pixels (the rest stretches)
K.pieces = {
    ui_frame      = 64,    -- big window frame: panels, tooltips, menus
    ui_panel      = 64,    -- a quieter, glassy frame for lists and reports
    ui_button     = 48,    -- command button, normal (dim amber)
    ui_button_hot = 48,    -- the same, lit
    ui_button_on  = 48,    -- the same, active (cyan)
    ui_slot       = 64,    -- build-menu card
    ui_slot_hot   = 64,
    ui_bar        = 80,    -- the header bar (caps keep their shape)
}

local known = {}
local function has(name)
    local v = known[name]
    if v == nil then
        local w, h = game.imageSize(name .. ".png")
        v = w and { w, h } or false
        known[name] = v
    end
    return v
end
K.has = has

-- Draw piece `name` over (x, y, w, h). `c` = screen size of the corners
-- (default: the source border at 1:1, shrunk to fit). Tint r, g, b, a.
function K.nine(name, x, y, w, h, c, r, g, b, a)
    local sz = has(name)
    if not sz then return false end
    local iw, ih = sz[1], sz[2]
    local bpx = K.pieces[name] or 32
    c = c or bpx
    c = math.min(c, w * 0.5, h * 0.5)
    r, g, b, a = r or 1, g or 1, b or 1, a or 1
    local f = name .. ".png"
    local bu, bv = bpx / iw, bpx / ih
    local xs = { x, x + c, x + w - c, x + w }
    local ys = { y, y + c, y + h - c, y + h }
    local us = { 0, bu, 1 - bu, 1 }
    local vs = { 0, bv, 1 - bv, 1 }
    for j = 1, 3 do
        local y0, y1 = ys[j], ys[j + 1]
        if y1 - y0 > 0.01 then
            for i = 1, 3 do
                local x0, x1 = xs[i], xs[i + 1]
                if x1 - x0 > 0.01 then
                    game.hudImage(f, x0, y0, x1 - x0, y1 - y0, r, g, b, a, us[i], vs[j], us[i + 1], vs[j + 1])
                end
            end
        end
    end
    return true
end

-- A whole picture, stretched (side panel, top bar, logo).
function K.image(name, x, y, w, h, r, g, b, a)
    if not has(name) then return false end
    game.hudImage(name .. ".png", x, y, w, h, r or 1, g or 1, b or 1, a or 1)
    return true
end

-- A window: the armoured frame, or a dark rectangle with an edge.
function K.window(x, y, w, h, alpha, style)
    alpha = alpha or 1
    if K.nine(style or "ui_frame", x, y, w, h, 48, 1, 1, 1, alpha) then return end
    game.hudRect(x, y, w, h, 0.035, 0.04, 0.05, 0.88 * alpha, 6)
    game.hudFrame(x, y, w, h, 0.32, 0.36, 0.40, 0.9 * alpha, 1.5, 6)
end

-- A button's plate in one of three states. Returns false when the art is missing.
function K.button(x, y, w, h, state, disabled)
    local name = (state == "on" and "ui_button_on") or (state == "hot" and "ui_button_hot") or "ui_button"
    if not has(name) then name = "ui_button" end
    local t = disabled and 0.45 or 1
    local c = math.min(h * 0.42, 30)
    return K.nine(name, x, y, w, h, c, t, t, t, 1)
end

-- A build-menu card.
function K.slot(x, y, w, h, hot, tint)
    local t = tint or 1
    local name = (hot and has("ui_slot_hot")) and "ui_slot_hot" or "ui_slot"
    return K.nine(name, x, y, w, h, math.min(w, h) * 0.22, t, t, t, 1)
end

-- Thin animated scan line across a panel (pure decoration).
function K.scan(x, y, w, h, t, r, g, b)
    local p = (t * 0.25) % 1
    local yy = y + p * h
    game.hudGradient(x, yy - 18, w, 18, r or 0.35, g or 0.88, b or 1, 0, r or 0.35, g or 0.88, b or 1, 0.06)
    game.hudLine(x, yy, x + w, yy, r or 0.35, g or 0.88, b or 1, 0.12, 1)
end

-- Angled corner brackets around a box (selection, hover).
function K.brackets(x, y, w, h, len, r, g, b, a, thick)
    len = len or 12
    thick = thick or 2
    local L = game.hudLine
    L(x, y, x + len, y, r, g, b, a, thick);             L(x, y, x, y + len, r, g, b, a, thick)
    L(x + w, y, x + w - len, y, r, g, b, a, thick);     L(x + w, y, x + w, y + len, r, g, b, a, thick)
    L(x, y + h, x + len, y + h, r, g, b, a, thick);     L(x, y + h, x, y + h - len, r, g, b, a, thick)
    L(x + w, y + h, x + w - len, y + h, r, g, b, a, thick); L(x + w, y + h, x + w, y + h - len, r, g, b, a, thick)
end

return K
