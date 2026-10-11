"""Cut the ComfyUI drafts (ui_raw/) into the game's UI pieces (textures/ui_*.png).

Each draft lies on black. The outside (black connected to the image border)
becomes transparent, the glow around the frame a soft edge; the frame is cut
to its bounding box, made mirror-symmetric from one quadrant (so the
nine-slice corners match), scaled, and saved as RGBA. Variants (hot, on) are
recoloured copies. Usage: python ui_cut.py  (picks in PICK below)
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
RAW = HERE / "ui_raw"
OUT = HERE.parent / "textures"


def key_black(im, thresh=22, inner_alpha=1.0):
    """RGBA: outside black -> transparent, its glow -> soft alpha."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    lum = a.max(axis=2)
    # outside = dark pixels connected to the border (flood fill on a mask)
    m = Image.fromarray(((lum < thresh) * 255).astype(np.uint8)).copy()   # fromarray shares memory: floodfill would no-op
    h, w = lum.shape
    for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if m.getpixel(p) == 255:
            ImageDraw.floodfill(m, p, 128)
    outside = np.asarray(m) == 128
    # grow the outside a little into the halo, softly
    out_f = np.asarray(Image.fromarray((outside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))) / 255.0
    alpha = np.where(outside, 0.0, inner_alpha)
    # halo: everything near the outside keeps alpha by its own brightness
    halo = np.clip(lum / 120.0, 0, 1)
    alpha = alpha * (1 - out_f) + halo * out_f
    alpha = np.clip(alpha, 0, 1)
    # unpremultiply the halo colour (it was mixed over black)
    rgb = a / np.maximum(alpha[..., None], 1e-3)
    rgb = np.where((out_f > 0.01)[..., None], np.clip(rgb, 0, 255), a)
    return np.dstack([rgb, alpha * 255]).astype(np.float32)


def crop(rgba, pad=5, thr=90):
    # the solid frame decides the box (a stray glow speck must not widen it)
    al = rgba[..., 3]
    ys, xs = np.where(al > thr)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    # centre the box so the mirror axis is the frame's middle
    return rgba[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]


def mirror(rgba, quad="tl"):
    """Make it symmetric from one quadrant (tl, tr, bl, br)."""
    h, w = rgba.shape[:2]
    h2, w2 = h // 2, w // 2
    q = {"tl": rgba[:h2, :w2], "tr": rgba[:h2, w - w2:][:, ::-1],
         "bl": rgba[h - h2:, :w2][::-1], "br": rgba[h - h2:, w - w2:][::-1, ::-1]}[quad]
    top = np.concatenate([q, q[:, ::-1]], axis=1)
    return np.concatenate([top, top[::-1]], axis=0)


def mirror_h(rgba, side="l"):
    """Symmetric left/right only (wide buttons, bars)."""
    w = rgba.shape[1]
    w2 = w // 2
    half = rgba[:, :w2] if side == "l" else rgba[:, w - w2:][:, ::-1]
    return np.concatenate([half, half[:, ::-1]], axis=1)


def save(rgba, name, size):
    im = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")
    if size:
        im = im.resize(size, Image.LANCZOS)
    im.save(OUT / f"{name}.png")
    print("wrote", name, im.size)
    return im


def recolor(rgba, hue_from, gain=1.0, to=None, sat_gain=1.0):
    """Brighten (gain) and/or push the glowing colours toward `to` (r, g, b)."""
    out = rgba.copy()
    rgb = out[..., :3]
    if to is not None:
        lum = rgb.max(axis=2, keepdims=True)
        sat = (rgb.max(axis=2) - rgb.min(axis=2))[..., None] / np.maximum(lum, 1)
        w = np.clip((sat - 0.25) * 2.5, 0, 1) * sat_gain
        tgt = np.array(to, np.float32)[None, None] * lum / 255.0
        rgb = rgb * (1 - w) + tgt * w
    out[..., :3] = np.clip(rgb * gain, 0, 255)
    return out


def darken_centre(rgba, border, value=0.6):
    """Let the middle show some of the world through (glass)."""
    out = rgba.copy()
    h, w = out.shape[:2]
    out[border:h - border, border:w - border, 3] *= value
    return out


def load(name):
    return Image.open(RAW / f"{name}.png")


if __name__ == "__main__":
    import json
    PICK = json.loads((HERE / "ui_pick.json").read_text())
    for name, spec in PICK.items():
        src = key_black(load(spec["raw"]), spec.get("thresh", 22))
        src = crop(src)
        if spec.get("mirror") == "h":
            src = mirror_h(src, spec.get("side", "l"))
        elif spec.get("mirror"):
            src = mirror(src, spec["mirror"])
        size = tuple(spec["size"]) if spec.get("size") else None
        if size:
            im = Image.fromarray(np.clip(src, 0, 255).astype(np.uint8), "RGBA").resize(size, Image.LANCZOS)
            src = np.asarray(im).astype(np.float32)
        if spec.get("glass"):
            src = darken_centre(src, spec["glass"][0], spec["glass"][1])
        for vname, v in spec.get("variants", {}).items():
            save(recolor(src, None, v.get("gain", 1.0), v.get("to"), v.get("sat", 1.0)), vname, None)
        if spec.get("gain"):
            src = recolor(src, None, spec["gain"])
        save(src, name, None)
