# STEELWARS asset generator for Blender 5.x
# ------------------------------------------------------------------
# Run inside Blender (e.g. via the MCP add-on):
#   ns = {}; p = r"D:\fitzel_projects\steelwars\design\blender_build.py"
#   exec(compile(open(p).read(), p, "exec"), ns)
#   ns["process"]("tank")          # build + export + manifest for one asset
#   ns["process_all"]()            # everything
#   ns["render_icon"]("tank")      # icon (needs the asset built in this session)
#
# Everything lives in its own scene "steelwars_build"; the user's scenes are not touched.
# Conventions follow design/assets.md: Blender Z up, front = -Y; engine = (bx, bz, -by).
# ------------------------------------------------------------------
import bpy, bmesh, math, json, os, random
from contextlib import contextmanager
from mathutils import Vector, Matrix, Euler, Quaternion

ROOT = r"D:\fitzel_projects\steelwars"
MODELS = os.path.join(ROOT, "models")
ICONS = os.path.join(ROOT, "icons")
MANIFEST = os.path.join(MODELS, "manifest.json")
SCENE = "steelwars_build"

TEAMS = {"t0": (0.55, 0.04, 0.03), "t1": (0.04, 0.16, 0.60),
         "t2": (0.10, 0.45, 0.05), "t3": (0.70, 0.32, 0.02)}
ICON_TEAM = "t1"
ICON_GLOW = 0.3      # emission is scaled down for icon renders so glows keep their hue

# ------------------------------------------------------------------ materials
# key -> (name, base color, metallic, roughness, emission color, emission strength)
MATS = {
    "dark":   ("metal_dark",  (0.095, 0.10, 0.11), 0.80, 0.45, None, 0),
    "trim":   ("metal_trim",  (0.25, 0.25, 0.26), 0.90, 0.35, None, 0),
    "glow":   ("glow",        (0.30, 0.90, 1.00), 0.0, 0.30, (0.3, 0.9, 1.0), 6.0),
    "black":  ("black",       (0.018, 0.018, 0.02), 0.20, 0.85, None, 0),
    "hazard": ("hazard_yellow", (0.80, 0.55, 0.04), 0.30, 0.45, None, 0),
    "crystal": ("energicum",  (0.20, 1.00, 0.60), 0.0, 0.15, (0.2, 1.0, 0.6), 7.0),
    "orange": ("glow_orange", (1.00, 0.45, 0.10), 0.0, 0.30, (1.0, 0.45, 0.08), 7.0),
    "red":    ("glow_red",    (1.00, 0.10, 0.06), 0.0, 0.30, (1.0, 0.08, 0.04), 5.0),
    "char":   ("charred",     (0.022, 0.020, 0.019), 0.30, 0.90, None, 0),
    "char2":  ("charred_metal", (0.06, 0.05, 0.045), 0.50, 0.80, None, 0),
    "ember":  ("ember",       (0.08, 0.02, 0.0), 0.0, 0.90, (1.0, 0.32, 0.05), 3.5),
    "rock":   ("rock",        (0.11, 0.10, 0.095), 0.0, 0.85, None, 0),
}
for _t, _c in TEAMS.items():
    MATS["team_" + _t] = ("team_paint_" + _t, _c, 0.35, 0.42, None, 0)


def get_mat(key):
    if key == "team":
        key = "team_" + ICON_TEAM
    name, col, met, rough, ecol, estr = MATS[key]
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = (*col, 1)
    bsdf.inputs["Metallic"].default_value = met
    bsdf.inputs["Roughness"].default_value = rough
    if ecol:
        bsdf.inputs["Emission Color"].default_value = (*ecol, 1)
        bsdf.inputs["Emission Strength"].default_value = estr
    else:
        bsdf.inputs["Emission Strength"].default_value = 0.0
    m.diffuse_color = (*col, 1)
    m.use_backface_culling = True
    return m

# ------------------------------------------------------------------ transforms


def M(loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    """loc, rot (degrees XYZ), scale -> 4x4"""
    if not isinstance(scale, (tuple, list, Vector)):
        scale = (scale, scale, scale)
    R = Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
    S = Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    return Matrix.Translation(Vector(loc)) @ R @ S


def M_between(p0, p1, roll=0.0):
    """matrix whose local Z runs from p0 to p1 (origin at midpoint, unit length scale NOT applied)"""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    z = d.normalized()
    ref = Vector((0, 0, 1)) if abs(z.z) < 0.99 else Vector((0, 1, 0))
    x = ref.cross(z).normalized()
    y = z.cross(x)
    R = Matrix((x, y, z)).transposed().to_4x4() @ Matrix.Rotation(math.radians(roll), 4, "Z")
    return Matrix.Translation((p0 + p1) * 0.5) @ R, d.length


def ENG(v):
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4)]

# ------------------------------------------------------------------ primitive geometry (temp bmeshes)


def _bevel(bm, w, seg=1, ang=50.0):
    if w <= 0:
        return bm
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(ang)]
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=w, offset_type="OFFSET", segments=seg,
                        profile=0.5, affect="EDGES", clamp_overlap=True)
    return bm


def g_loft(rings, cap0=True, cap1=True):
    """rings: list of (z, [(x,y),...]) with the same point count, CCW seen from +Z"""
    bm = bmesh.new()
    vr = [[bm.verts.new((p[0], p[1], z)) for p in pts] for z, pts in rings]
    n = len(vr[0])
    if cap0:
        bm.faces.new(list(reversed(vr[0])))
    for a, b in zip(vr, vr[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([a[i], a[j], b[j], b[i]])
    if cap1:
        bm.faces.new(vr[-1])
    return bm


def g_frame(outer, inner, z0, z1):
    """closed ring solid between two CCW polygons with equal point counts (rims, collars)"""
    bm = bmesh.new()
    n = len(outer)
    ob = [bm.verts.new((p[0], p[1], z0)) for p in outer]
    ot = [bm.verts.new((p[0], p[1], z1)) for p in outer]
    ib = [bm.verts.new((p[0], p[1], z0)) for p in inner]
    it = [bm.verts.new((p[0], p[1], z1)) for p in inner]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([ob[i], ob[j], ot[j], ot[i]])
        bm.faces.new([ib[j], ib[i], it[i], it[j]])
        bm.faces.new([ot[i], ot[j], it[j], it[i]])
        bm.faces.new([ob[j], ob[i], ib[i], ib[j]])
    return bm


def rect(w, d, cx=0, cy=0):
    return [(cx - w / 2, cy - d / 2), (cx + w / 2, cy - d / 2), (cx + w / 2, cy + d / 2), (cx - w / 2, cy + d / 2)]


def crect(w, d, c, cx=0, cy=0):
    """chamfered rectangle (octagon)"""
    x, y = w / 2, d / 2
    pts = [(-x + c, -y), (x - c, -y), (x, -y + c), (x, y - c), (x - c, y), (-x + c, y), (-x, y - c), (-x, -y + c)]
    return [(px + cx, py + cy) for px, py in pts]


def ngon(r, n, rot=0.0, cx=0, cy=0, sx=1.0, sy=1.0):
    return [(cx + sx * r * math.cos(math.radians(rot) + 2 * math.pi * i / n),
             cy + sy * r * math.sin(math.radians(rot) + 2 * math.pi * i / n)) for i in range(n)]


def scale_pts(pts, s, sy=None, dx=0, dy=0):
    sy = s if sy is None else sy
    return [(p[0] * s + dx, p[1] * sy + dy) for p in pts]


def g_box(sx, sy, sz, bev=0.0, seg=1):
    bm = g_loft([(-sz / 2, rect(sx, sy)), (sz / 2, rect(sx, sy))])
    return _bevel(bm, min(bev, min(sx, sy, sz) * 0.45), seg)


def g_frustum(bx, by, tx, ty, h, ox=0.0, oy=0.0, bev=0.0, seg=1):
    """bottom (bx,by) at z=0, top (tx,ty) at z=h shifted by (ox,oy)"""
    bm = g_loft([(0, rect(bx, by)), (h, rect(tx, ty, ox, oy))])
    return _bevel(bm, min(bev, min(bx, by, tx, ty, h) * 0.45), seg)


def g_poly(pts, z0, z1, top_scale=1.0, top_pts=None, bev=0.0, seg=1):
    tp = top_pts if top_pts is not None else scale_pts(pts, top_scale)
    bm = g_loft([(z0, pts), (z1, tp)])
    return _bevel(bm, bev, seg)


def g_prism(profile_yz, width, bev=0.0, seg=1):
    """profile in (y,z) CCW seen from +X, extruded along X centred"""
    bm = g_loft([(-width / 2, profile_yz), (width / 2, profile_yz)])
    for v in bm.verts:
        u, w, x = v.co.x, v.co.y, v.co.z
        v.co = Vector((x, u, w))
    return _bevel(bm, bev, seg)


def g_cyl(r, h, seg=16, r2=None, bev=0.0, bseg=1):
    """axis Z, centred"""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r,
                          radius2=r if r2 is None else r2, depth=h)
    return _bevel(bm, min(bev, h * 0.45, r * 0.45), bseg)


def g_lathe(profile, seg=16, closed=False, rot=0.0):
    """profile [(r,z),...] revolved around Z. Walk bottom->outside->top for outward normals."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(math.radians(rot) + 2 * math.pi * i / seg),
                                        r * math.sin(math.radians(rot) + 2 * math.pi * i / seg), z)) for i in range(seg)])
    pairs = list(zip(rings, rings[1:]))
    if closed:
        pairs.append((rings[-1], rings[0]))
    for a, b in pairs:
        if len(a) == 1 and len(b) == 1:
            continue
        for i in range(seg):
            j = (i + 1) % seg
            if len(a) == 1:
                bm.faces.new([a[0], b[j], b[i]])
            elif len(b) == 1:
                bm.faces.new([a[i], a[j], b[0]])
            else:
                bm.faces.new([a[i], a[j], b[j], b[i]])
    return bm


def g_tube(ro, ri, h, seg=16):
    return g_lathe([(ri, -h / 2), (ro, -h / 2), (ro, h / 2), (ri, h / 2)], seg, closed=True)


def g_sphere(r, seg=12, rings=8):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=r)
    return bm


def g_dome(r, seg=16, rings=6, h=None):
    h = r if h is None else h
    prof = [(0, 0)]
    for i in range(rings + 1):
        a = math.pi / 2 * i / rings
        prof.append((r * math.cos(a), h * math.sin(a)))
    prof[-1] = (0, h)
    return g_lathe(prof, seg)


def g_torus(R, r, seg=24, seg2=8):
    prof = [(R + r * math.cos(-math.pi / 2 + 2 * math.pi * i / seg2), r * math.sin(-math.pi / 2 + 2 * math.pi * i / seg2)) for i in range(seg2)]
    return g_lathe(prof, seg, closed=True)


def g_parallelogram(w, h, skew, t):
    """flat stripe on XY (thickness t along +Z): used for hazard stripes"""
    pts = [(-w / 2 - skew / 2, -h / 2), (w / 2 - skew / 2, -h / 2), (w / 2 + skew / 2, h / 2), (-w / 2 + skew / 2, h / 2)]
    return g_loft([(0, pts), (t, pts)])


def g_hull2d(pts):
    pts = sorted(set((round(p[0], 5), round(p[1], 5)) for p in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]   # CCW


def resample_loop(poly, n):
    segs = []
    L = 0
    for i in range(len(poly)):
        a, b = Vector(poly[i]), Vector(poly[(i + 1) % len(poly)])
        segs.append((a, b, (b - a).length))
        L += (b - a).length
    out = []
    for k in range(n):
        s = L * k / n
        for a, b, l in segs:
            if s <= l or (a, b, l) == segs[-1]:
                t = s / l if l > 0 else 0
                out.append(a.lerp(b, min(t, 1)))
                break
            s -= l
    return out

# ------------------------------------------------------------------ part builder


class PB:
    """Accumulates geometry for ONE exported part into a single bmesh (<=4 materials)."""

    def __init__(self, name, mats=()):
        self.name = name
        self.bm = bmesh.new()
        self.mats = list(mats)
        self.stack = [Matrix.Identity(4)]
        self.alias = {}

    def mi(self, key):
        key = self.alias.get(key, key)
        if key not in self.mats:
            self.mats.append(key)
            if len(self.mats) > 4:
                raise RuntimeError("part %s exceeds 4 materials: %s" % (self.name, self.mats))
        return self.mats.index(key)

    @contextmanager
    def at(self, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), m=None):
        mm = m if m is not None else M(loc, rot, scale)
        self.stack.append(self.stack[-1] @ mm)
        try:
            yield self
        finally:
            self.stack.pop()

    def add(self, src, mat, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), m=None):
        T = self.stack[-1] @ (m if m is not None else M(loc, rot, scale))
        idx = self.mi(mat)
        flip = T.to_3x3().determinant() < 0
        src.verts.index_update()
        nv = [self.bm.verts.new(T @ v.co) for v in src.verts]
        for f in src.faces:
            vs = [nv[v.index] for v in f.verts]
            if flip:
                vs.reverse()
            try:
                nf = self.bm.faces.new(vs)
            except ValueError:
                continue
            nf.material_index = idx
            nf.smooth = True
        src.free()
        return self

    # convenience shortcuts -------------------------------------------------
    def box(self, size, loc=(0, 0, 0), mat="dark", bev=0.04, rot=(0, 0, 0), seg=1):
        return self.add(g_box(*size, bev=bev, seg=seg), mat, loc, rot)

    def cyl(self, r, h, loc=(0, 0, 0), mat="dark", rot=(0, 0, 0), seg=16, r2=None, bev=0.02):
        return self.add(g_cyl(r, h, seg, r2, bev), mat, loc, rot)

    def beam(self, p0, p1, w, h=None, mat="dark", bev=0.02, roll=0.0):
        m, L = M_between(p0, p1, roll)
        return self.add(g_box(w, h or w, L, bev=bev), mat, m=m)

    def rod(self, p0, p1, r, mat="trim", seg=8, bev=0.0):
        m, L = M_between(p0, p1)
        return self.add(g_cyl(r, L, seg, bev=bev), mat, m=m)

    def plate(self, size, loc=(0, 0, 0), rot=(0, 0, 0), top="team", base="dark", bev=0.05, t=0.06, inset=0.08):
        """armour plate: base block + painted cap on its top face"""
        sx, sy, sz = size
        with self.at(loc, rot):
            self.add(g_box(sx, sy, sz, bev=bev), base)
            self.add(g_box(max(sx - 2 * inset, 0.05), max(sy - 2 * inset, 0.05), t, bev=min(bev, t * 0.4)), top, (0, 0, sz / 2 + t / 2 - 0.01))
        return self

    def hazard(self, length, height, loc, rot=(0, 0, 0), n=None, mat="trim", t=0.03, w=None):
        """diagonal warning stripes lying in local XY plane, facing +Z"""
        n = n or max(2, int(length / (height * 0.9)))
        pitch = length / n
        w = w or pitch * 0.5
        with self.at(loc, rot):
            for i in range(n):
                x = -length / 2 + pitch * (i + 0.5)
                self.add(g_parallelogram(w, height, height * 0.6, t), mat, (x, 0, 0))
        return self

    def vent(self, w, h, loc, rot=(0, 0, 0), n=5, frame="trim", slat="black", depth=0.08):
        """grille on a surface facing local -Y (front). Frame + slats."""
        with self.at(loc, rot):
            self.add(g_box(w, depth, h, bev=0.015), frame, (0, 0, 0))
            for i in range(n):
                z = -h / 2 + h * (i + 0.5) / n
                self.add(g_box(w * 0.86, depth * 0.6, h / n * 0.45, bev=0.0), slat, (0, -depth * 0.45, z), rot=(25, 0, 0))
        return self

    def bolts(self, p0, p1, n, r=0.04, mat="trim", axis_rot=(0, 0, 0), h=0.03):
        p0, p1 = Vector(p0), Vector(p1)
        for i in range(n):
            p = p0.lerp(p1, (i + 0.5) / n)
            self.add(g_cyl(r, h, 6), mat, p, axis_rot)
        return self

    def light(self, loc, rot=(0, 0, 0), size=0.18, glow="glow", housing="trim"):
        with self.at(loc, rot):
            self.add(g_box(size * 1.3, size * 0.7, size * 1.0, bev=size * 0.12), housing)
            self.add(g_box(size, 0.04, size * 0.7, bev=0.0), glow, (0, -size * 0.36, 0))
        return self

    def pipe(self, pts, r, mat="trim", seg=8, joints=True):
        for a, b in zip(pts, pts[1:]):
            self.rod(a, b, r, mat, seg)
        if joints:
            for p in pts[1:-1]:
                self.add(g_sphere(r * 1.25, seg, 6), mat, p)
        return self

    def greebles(self, area_w, area_d, loc, rot=(0, 0, 0), n=8, seed=1, mats=("dark", "trim"), hmax=0.15, smax=0.4):
        rnd = random.Random(seed)
        with self.at(loc, rot):
            for i in range(n):
                sx = rnd.uniform(0.08, smax)
                sy = rnd.uniform(0.08, smax)
                h = rnd.uniform(0.03, hmax)
                x = rnd.uniform(-area_w / 2 + sx / 2, area_w / 2 - sx / 2)
                y = rnd.uniform(-area_d / 2 + sy / 2, area_d / 2 - sy / 2)
                m = mats[i % len(mats)]
                if rnd.random() < 0.3:
                    self.add(g_cyl(min(sx, sy) / 2, h, 8), m, (x, y, h / 2))
                else:
                    self.add(g_box(sx, sy, h, bev=0.01), m, (x, y, h / 2))
        return self

    def antenna(self, base, h, r=0.03, tip="glow", mat="trim"):
        base = Vector(base)
        self.add(g_cyl(r * 2.5, 0.12, 8), mat, base + Vector((0, 0, 0.06)))
        self.add(g_cyl(r, h, 6, r2=r * 0.5), mat, base + Vector((0, 0, h / 2 + 0.1)))
        self.add(g_sphere(r * 1.8, 8, 4), tip, base + Vector((0, 0, h + 0.1)))
        return self

    def track(self, x, width, wheels, thick=0.12, n=56, grouser=0.05, wheel_mat="trim", belt="black", hub="dark", show_wheels=True):
        """Track assembly centred at X=x. wheels: list of (y, z, r) circles; belt wraps their convex hull."""
        pts = []
        for (y, z, r) in wheels:
            for k in range(36):
                a = 2 * math.pi * k / 36
                pts.append((y + (r + thick) * math.cos(a), z + (r + thick) * math.sin(a)))
        hull = g_hull2d(pts)
        loop = resample_loop(hull, n)
        cen = Vector((sum(p.x for p in loop) / n, sum(p.y for p in loop) / n))
        outer, inner, normals = [], [], []
        for i in range(n):
            p = loop[i]
            t = (loop[(i + 1) % n] - loop[i - 1]).normalized()
            nn = Vector((t.y, -t.x))
            if nn.dot(p - cen) < 0:
                nn = -nn
            normals.append((nn, t))
            outer.append(p)
            inner.append(p - nn * thick)
        bm = bmesh.new()
        x0, x1 = x - width / 2, x + width / 2
        Ro0 = [bm.verts.new((x0, p.x, p.y)) for p in outer]
        Ro1 = [bm.verts.new((x1, p.x, p.y)) for p in outer]
        Ri0 = [bm.verts.new((x0, p.x, p.y)) for p in inner]
        Ri1 = [bm.verts.new((x1, p.x, p.y)) for p in inner]
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([Ro0[i], Ro0[j], Ro1[j], Ro1[i]])
            bm.faces.new([Ri0[j], Ri0[i], Ri1[i], Ri1[j]])
            bm.faces.new([Ro0[j], Ro0[i], Ri0[i], Ri0[j]])
            bm.faces.new([Ro1[i], Ro1[j], Ri1[j], Ri1[i]])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        self.add(bm, belt)
        # grousers (tread cleats)
        for i in range(0, n, 1):
            p = outer[i]
            nn, t = normals[i]
            zax = Vector((0, nn.x, nn.y))
            xax = Vector((1, 0, 0))
            yax = zax.cross(xax)
            R = Matrix((xax, yax, zax)).transposed().to_4x4()
            m = Matrix.Translation(Vector((x, p.x, p.y)) + zax * grouser * 0.5) @ R
            self.add(g_box(width * 1.02, 0.12, grouser, bev=0.0), belt, m=m)
        if show_wheels:
            for (y, z, r) in wheels:
                rr = r - 0.01
                self.add(g_cyl(rr, width * 0.8, 16, bev=0.03), wheel_mat, (x, y, z), (0, 90, 0))
                for sgn in (-1, 1):
                    self.add(g_cyl(rr * 0.55, 0.06, 12, bev=0.01), hub, (x + sgn * width * 0.42, y, z), (0, 90, 0))
                    self.add(g_cyl(rr * 0.18, 0.12, 8), wheel_mat, (x + sgn * width * 0.45, y, z), (0, 90, 0))
        return outer

    def wheel(self, loc, r, w, tyre="black", rim="trim", hub="dark", seg=20, side=1):
        """big rubber wheel, axis along X; side=+1 for right side (hub detail faces +X)"""
        with self.at(loc, (0, 90 * side, 0)):
            prof = [(r * 0.55, -w / 2), (r * 0.92, -w / 2), (r, -w / 2 + w * 0.15), (r, w / 2 - w * 0.15), (r * 0.92, w / 2), (r * 0.55, w / 2)]
            self.add(g_lathe(prof, seg, closed=True), tyre)
            for k in range(seg // 2):
                a = 360 * k / (seg // 2)
                with self.at((0, 0, 0), (0, 0, a)):
                    self.add(g_box(0.08, r * 0.12, w * 0.9, bev=0.0), tyre, (r * 1.0, 0, 0))
            self.add(g_cyl(r * 0.58, w * 0.85, 12, bev=0.02), rim)
            self.add(g_cyl(r * 0.3, w * 0.95, 8, bev=0.02), hub)
            for k in range(6):
                a = math.radians(60 * k)
                self.add(g_cyl(0.035, w * 1.0, 6), rim, (r * 0.42 * math.cos(a), r * 0.42 * math.sin(a), 0))
        return self

    # --------------------------------------------------------------------
    def finish(self, coll, obj_name=None):
        me = bpy.data.meshes.new(obj_name or self.name)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for k in self.mats:
            me.materials.append(get_mat(k))
        me.set_sharp_from_angle(angle=math.radians(46))
        ob = bpy.data.objects.get(obj_name or self.name)
        if ob is not None and ob.type == "MESH":
            old = ob.data
            ob.data = me
            if old.users == 0:
                bpy.data.meshes.remove(old)
            me.name = ob.name
            for md in list(ob.modifiers):
                ob.modifiers.remove(md)
        else:
            ob = bpy.data.objects.new(obj_name or self.name, me)
        if coll.name not in [c.name for c in ob.users_collection]:
            coll.objects.link(ob)
        mod = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        mod.mode = "FACE_AREA"
        mod.weight = 50
        mod.keep_sharp = True
        ob["sw_mats"] = json.dumps(self.mats)
        return ob

# ------------------------------------------------------------------ scene / collections


def scene():
    """Headless (blender --background --command blender_mcp): use the session's own scene.
    With a GUI: a separate scene so the user's scene is untouched."""
    if bpy.app.background:
        sc = bpy.context.scene
        if sc.name != SCENE and bpy.data.scenes.get(SCENE) is None:
            sc.name = SCENE
        return sc
    sc = bpy.data.scenes.get(SCENE)
    if sc is None:
        sc = bpy.data.scenes.new(SCENE)
        sc.unit_settings.system = "METRIC"
    win = bpy.context.window_manager.windows[0]
    if win.scene != sc:
        win.scene = sc
    return sc


def asset_coll(key):
    """collection for one asset. Objects are NOT deleted on rebuild (deleting objects and
    re-evaluating the depsgraph crashed Blender 5.1); PB.finish swaps the mesh instead."""
    sc = scene()
    name = "SW_" + key
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
    if c.name not in sc.collection.children:
        sc.collection.children.link(c)
    return c


def obj_bounds(ob):
    """world AABB + triangle count straight from the mesh data (no depsgraph: the modifiers
    used here never move vertices)."""
    me = ob.data
    mw = ob.matrix_world
    xs = [mw @ v.co for v in me.vertices]
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    mn = Vector((min(v.x for v in xs), min(v.y for v in xs), min(v.z for v in xs)))
    mx = Vector((max(v.x for v in xs), max(v.y for v in xs), max(v.z for v in xs)))
    return mn, mx, tris


def export_obj(ob, filename):
    sc = scene()
    vl = sc.view_layers[0]
    names = set(c.name for c in ob.users_collection)
    for lc in vl.layer_collection.children:
        if lc.name in names:
            lc.exclude = False
    for o in vl.objects:
        o.select_set(False)
    ob.hide_set(False, view_layer=vl)
    ob.select_set(True, view_layer=vl)
    vl.objects.active = ob
    path = os.path.join(MODELS, filename + ".glb")
    win = bpy.context.window_manager.windows[0]
    import io, contextlib
    with bpy.context.temp_override(window=win, scene=sc, view_layer=vl), contextlib.redirect_stdout(io.StringIO()):
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                                  export_yup=True, export_cameras=False, export_lights=False,
                                  export_animations=False, export_materials="EXPORT", export_normals=True,
                                  export_texcoords=False, export_extras=False, export_skins=False, export_morph=False)
    ob.select_set(False, view_layer=vl)
    return path


def export_part(ob, filename, team):
    """team parts: swap the team_paint material and export _t0.._t3."""
    files = []
    if team:
        me = ob.data
        idx = [i for i, m in enumerate(me.materials) if m and m.name.startswith("team_paint_")]
        orig = [me.materials[i] for i in idx]
        for t in TEAMS:
            for i in idx:
                me.materials[i] = get_mat("team_" + t)
            files.append(export_obj(ob, filename + "_" + t))
        for i, m in zip(idx, orig):
            me.materials[i] = m
    else:
        files.append(export_obj(ob, filename))
    return files

# ------------------------------------------------------------------ manifest


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"units": {}, "buildings": {}, "props": {}}


NL = chr(10)


def _dump(o, ind=0):
    flat = json.dumps(o, separators=(", ", ": "))
    if len(flat) + ind <= 150 or not isinstance(o, (dict, list)):
        return flat
    pad = "  " * (ind + 1)
    if isinstance(o, dict):
        items = [pad + json.dumps(k) + ": " + _dump(v, ind + 1) for k, v in o.items()]
        return "{" + NL + ("," + NL).join(items) + NL + "  " * ind + "}"
    items = [pad + _dump(v, ind + 1) for v in o]
    return "[" + NL + ("," + NL).join(items) + NL + "  " * ind + "]"


def save_manifest(man):
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump(man) + NL)
    json.load(open(tmp, encoding="utf-8"))   # validate
    os.replace(tmp, MANIFEST)


def _r(v):
    return [round(float(a), 3) + 0.0 for a in v]

# ------------------------------------------------------------------ registry
ASSETS = {}   # key -> dict(kind, fn, size/footprint)


def asset(key, kind, **kw):
    def deco(fn):
        ASSETS[key] = dict(kind=kind, fn=fn, **kw)
        return fn
    return deco


def build(key):
    info = ASSETS[key]
    coll = asset_coll(key)
    res = info["fn"](coll)
    return coll, res


def process(key, export=True):
    """build asset, export glbs, update manifest; returns report dict"""
    info = ASSETS[key]
    coll, res = build(key)
    report = {"key": key, "parts": {}, "files": []}
    man = load_manifest()
    parts_out = []
    for p in res["parts"]:
        ob = p["obj"]
        mn, mx, tris = obj_bounds(ob)
        c = (mn + mx) * 0.5
        fname = p.get("file", key + "_" + p["name"])
        if export:
            report["files"] += [os.path.basename(f) for f in export_part(ob, fname, p["team"])]
        report["parts"][p["name"]] = tris
        parts_out.append({"name": p["name"], "file": fname, "team": bool(p["team"]),
                          "center": _r(ENG(c)), "pivot": _r(ENG(p.get("pivot", (0, 0, 0)))),
                          "axis": p.get("axis", "none")})
    if info["kind"] == "unit":
        entry = {"size": info["size"], "parts": parts_out,
                 "muzzles": [{"part": m["part"], "pos": _r(ENG(m["pos"]))} for m in res.get("muzzles", [])]}
        if res.get("wreck_from"):
            wob = make_wreck(coll, res["wreck_from"], key + "_wreck")
            if export:
                report["files"] += [os.path.basename(export_obj(wob, key + "_wreck"))]
            report["parts"]["wreck"] = obj_bounds(wob)[2]
            entry["wreck"] = key + "_wreck"
        for k, v in res.get("extra", {}).items():
            entry[k] = v
        man.setdefault("units", {})[key] = entry
    elif info["kind"] == "building":
        entry = {"footprint": info["footprint"], "parts": parts_out}
        if res.get("muzzles"):
            entry["muzzles"] = [{"part": m["part"], "pos": _r(ENG(m["pos"]))} for m in res["muzzles"]]
        for k, v in res.get("points", {}).items():
            entry[k] = _r(ENG(v)) if not isinstance(v[0], (list, tuple)) else [_r(ENG(q)) for q in v]
        man.setdefault("buildings", {})[key] = entry
    else:
        p = parts_out[0]
        entry = {"file": p["file"], "team": p["team"], "center": p["center"]}
        mn, mx, _ = obj_bounds(res["parts"][0]["obj"])
        e = ENG(mx - mn)
        entry["size"] = _r([abs(a) for a in e])
        man.setdefault("props", {})[key] = entry
    if export:
        save_manifest(man)
    report["tris_total"] = sum(report["parts"].values())
    return report


def process_all(keys=None):
    out = []
    for k in (keys or list(ASSETS)):
        out.append(process(k))
    return out

# ------------------------------------------------------------------ wreck


def make_wreck(coll, src_ob, name, seed=7):
    """copy of the hull with charred materials + ember cracks, same bounding box."""
    mats = json.loads(src_ob["sw_mats"])
    remap = {"glow": "ember", "crystal": "ember", "orange": "ember", "red": "ember", "trim": "char2"}
    pb = PB(name, ["char", "char2", "ember"])
    bm = bmesh.new()
    bm.from_mesh(src_ob.data)
    mn, mx, _ = obj_bounds(src_ob)
    rnd = random.Random(seed)
    tops = []
    for f in bm.faces:
        k = mats[f.material_index]
        f.material_index = pb.mi(remap.get(k, "char"))
        if f.normal.z > 0.85 and f.calc_area() > 0.25:
            tops.append((f.calc_center_median(), f.calc_area(), Vector(f.normal)))
    # dents: push a few vertices slightly inward (stay inside the AABB)
    for v in bm.verts:
        if rnd.random() < 0.15:
            d = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 0))) * 0.04
            v.co = Vector((min(max(v.co.x + d.x, mn.x), mx.x), min(max(v.co.y + d.y, mn.y), mx.y), min(max(v.co.z + d.z, mn.z), mx.z)))
    pb.bm.free()
    pb.bm = bm
    rnd.shuffle(tops)
    for c, a, n in tops[:max(6, min(24, len(tops) // 6))]:
        L = min(math.sqrt(a) * 0.8, 1.6)
        ang = rnd.uniform(0, 180)
        segs = 3
        p = Vector(c) + Vector((0, 0, 0.004))
        for s in range(segs):
            ang += rnd.uniform(-35, 35)
            d = Vector((math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0)) * (L / segs)
            q = p + d
            if not (mn.x < q.x < mx.x and mn.y < q.y < mx.y):
                break
            m, l = M_between(p, q)
            pb.add(g_box(0.06, 0.012, l, bev=0.0), "ember", m=m @ M((0, 0, 0), (0, 0, 0)))
            p = q
    ob = pb.finish(coll, name)
    return ob

# ------------------------------------------------------------------ rendering (icons / previews)


def _rig():
    sc = scene()
    c = bpy.data.collections.get("SW_rig")
    if c is None:
        c = bpy.data.collections.new("SW_rig")
        sc.collection.children.link(c)
    def light(name, typ, energy, rot, color=(1, 1, 1), size=None):
        ob = bpy.data.objects.get(name)
        if ob is None:
            ld = bpy.data.lights.new(name, typ)
            ob = bpy.data.objects.new(name, ld)
            c.objects.link(ob)
        ob.data.energy = energy
        ob.data.color = color
        if size is not None and typ == "SUN":
            ob.data.angle = math.radians(size)
        ob.rotation_euler = Euler([math.radians(a) for a in rot], "XYZ")
        return ob
    light("SW_key", "SUN", 6.0, (45, 0, -40), (1.0, 0.94, 0.85), 3)
    light("SW_fill", "SUN", 2.0, (60, 0, 100), (0.6, 0.72, 1.0), 10)
    light("SW_rim", "SUN", 7.0, (-55, 0, 25), (0.8, 0.9, 1.0), 5)
    # holdout ground plane: hides everything below z=0 (foundation plinths) in icons
    hp = bpy.data.objects.get("SW_holdout")
    if hp is None:
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=300)
        me = bpy.data.meshes.new("SW_holdout")
        bm.to_mesh(me)
        bm.free()
        hm = bpy.data.materials.new("SW_holdout")
        hm.use_nodes = True
        nt = hm.node_tree
        nt.nodes.clear()
        ho = nt.nodes.new("ShaderNodeHoldout")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(ho.outputs[0], out.inputs[0])
        me.materials.append(hm)
        hp = bpy.data.objects.new("SW_holdout", me)
        c.objects.link(hp)
    hp.location = (0, 0, -0.01)
    cam = bpy.data.objects.get("SW_cam")
    if cam is None:
        cd = bpy.data.cameras.new("SW_cam")
        cam = bpy.data.objects.new("SW_cam", cd)
        c.objects.link(cam)
    sc.camera = cam
    for ob in sc.objects:
        if not any(c.name.startswith("SW_") for c in ob.users_collection):
            ob.hide_render = True
    # world: bright-top / dark-bottom gradient so metal has something to reflect
    w = bpy.data.worlds.get("SW_world")
    if w is None:
        w = bpy.data.worlds.new("SW_world")
        w.use_nodes = True
        nt = w.node_tree
        nt.nodes.clear()
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        bg = nt.nodes.new("ShaderNodeBackground")
        out = nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        nt.links.new(sep.outputs[2], ramp.inputs[0])
        nt.links.new(ramp.outputs[0], bg.inputs[0])
        nt.links.new(bg.outputs[0], out.inputs[0])
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.02, 0.022, 0.025, 1)
        ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[1].color = (0.55, 0.6, 0.68, 1)
        bg.inputs[1].default_value = 0.8
    w.node_tree.nodes['Background'].inputs[1].default_value = 1.3
    sc.world = w
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Punchy"
    except Exception:
        pass
    return cam


def show_only(keys):
    sc = scene()
    keys = set("SW_" + k for k in keys)
    for lc in sc.view_layers[0].layer_collection.children:
        if lc.name.startswith("SW_") and lc.name != "SW_rig":
            lc.exclude = lc.name not in keys


def coll_bounds(coll):
    mn = Vector((1e9, 1e9, 1e9))
    mx = -mn
    for ob in coll.objects:
        if ob.type != "MESH" or ob.name.endswith("_wreck") or ob.hide_render:
            continue
        a, b, _ = obj_bounds(ob)
        mn = Vector((min(mn[i], a[i]) for i in range(3)))
        mx = Vector((max(mx[i], b[i]) for i in range(3)))
    return mn, mx


def frame_camera(cam, pts, az=35.0, el=35.0, lens=50.0, pad=1.0):
    """aim and choose the distance so all points fit (with margin pad)."""
    c = sum(pts, Vector()) / len(pts)
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.sensor_fit = "AUTO"
    tanh = 18.0 / lens / pad
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    fwd = -d
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd)
    for it in range(5):
        D = 0.0
        for p in pts:
            q = p - c
            z = q.dot(fwd)
            D = max(D, z + abs(q.dot(right)) / tanh, z + abs(q.dot(up)) / tanh)
        eye = c - fwd * D
        xs, ys = [], []
        for p in pts:
            q = p - eye
            z = q.dot(fwd)
            xs.append(q.dot(right) / z)
            ys.append(q.dot(up) / z)
        ox, oy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        c = c + right * ox * D + up * oy * D
    D = 0.0
    for p in pts:
        q = p - c
        z = q.dot(fwd)
        D = max(D, z + abs(q.dot(right)) / tanh, z + abs(q.dot(up)) / tanh)
    cam.location = c - fwd * D
    cam.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start = 0.05
    cam.data.clip_end = D * 6


def coll_points(objs, maxn=6000):
    pts = []
    for ob in objs:
        pts += [ob.matrix_world @ v.co for v in ob.data.vertices]
    pts = [p for p in pts if p.z > -0.05] or pts
    step = max(1, len(pts) // maxn)
    return pts[::step]


def render_view(keys, path, res=256, az=35.0, el=35.0, lens=50.0, pad=1.0, wreck=False, holdout=None):
    sc = scene()
    cam = _rig()
    k0 = keys if isinstance(keys, str) else keys[0]
    if holdout is None:
        holdout = k0 not in ("shell", "rocket")
    bpy.data.objects["SW_holdout"].hide_render = not holdout
    keys = [keys] if isinstance(keys, str) else keys
    show_only(keys)
    for k in keys:
        for ob in bpy.data.collections["SW_" + k].objects:
            iw = ob.name.endswith("_wreck")
            ob.hide_render = (iw != wreck)
    objs = []
    for k in keys:
        for ob in bpy.data.collections["SW_" + k].objects:
            if ob.type == "MESH" and ob.name.endswith("_wreck") == wreck:
                objs.append(ob)
    frame_camera(cam, coll_points(objs), az, el, lens, pad)
    saved = []
    for m in bpy.data.materials:
        if m.node_tree:
            b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if b and b.inputs["Emission Strength"].default_value > 0:
                saved.append((b, b.inputs["Emission Strength"].default_value))
                b.inputs["Emission Strength"].default_value *= ICON_GLOW
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.filepath = path
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, scene=sc):
        bpy.ops.render.render(write_still=True)
    for b, v in saved:
        b.inputs["Emission Strength"].default_value = v
    for k in keys:
        for ob in bpy.data.collections["SW_" + k].objects:
            ob.hide_render = False
    return path


def render_icon(key):
    os.makedirs(ICONS, exist_ok=True)
    return render_view(key, os.path.join(ICONS, key + ".png"), 256, 35, 35, 50, 1.06)

# ==================================================================
#                              UNITS
# ==================================================================


@asset("tank", "unit", size=[4.2, 3.0, 7.0])
def build_tank(coll):
    # ---------------- hull ----------------
    h = PB("tank_hull", ["team", "dark", "trim", "black"])
    wheels = [(-2.95, 0.68, 0.36)] + [(y, 0.48, 0.33) for y in (-2.05, -1.02, 0.0, 1.02, 2.05)] + [(2.95, 0.72, 0.40)]
    for sx in (-1, 1):
        h.track(sx * 1.62, 0.95, wheels, thick=0.1, n=64, grouser=0.05, wheel_mat="dark", hub="trim")
        # drive sprocket teeth
        for k in range(10):
            a = 360 * k / 10
            with h.at((sx * 1.62, 2.95, 0.72), (a, 0, 0)):
                h.box((0.5, 0.1, 0.16), (0, 0, 0.42), "trim", bev=0.01)
    # lower hull (between tracks)
    h.add(g_prism([(-2.9, 0.38), (2.9, 0.38), (3.35, 0.8), (3.35, 1.3), (-2.4, 1.3), (-3.45, 0.86)], 2.3, bev=0.05), "dark")
    # upper deck over the tracks
    h.add(g_prism([(-3.15, 1.12), (3.35, 1.12), (3.48, 1.48), (-2.25, 1.58), (-3.52, 1.22)], 4.2, bev=0.06), "dark")
    # team paint: fender plates + glacis plate
    for sx in (-1, 1):
        h.plate((0.95, 2.5, 0.06), (sx * 1.58, -0.62, 1.57), (-1.0, 0, 0), top="team", base="dark", inset=0.06)
        h.plate((0.95, 2.3, 0.06), (sx * 1.58, 1.85, 1.53), (-1.0, 0, 0), top="team", base="dark", inset=0.06)
        h.box((0.9, 0.12, 0.05), (sx * 1.58, 0.65, 1.58), "trim", bev=0.01)
        # side skirts (3 sections)
        for i, (y0, y1) in enumerate(((-3.0, -1.05), (-0.98, 0.95), (1.02, 2.95))):
            yc, L = (y0 + y1) / 2, (y1 - y0)
            h.box((0.08, L, 0.55), (sx * 2.13, yc, 0.93), "dark", bev=0.03, rot=(0, sx * -8, 0))
            h.bolts((sx * 2.18, y0 + 0.1, 1.1), (sx * 2.18, y1 - 0.1, 1.1), 5, r=0.035, axis_rot=(0, 90, 0))
            h.box((0.04, L - 0.2, 0.06), (sx * 2.175, yc, 0.8), "trim", bev=0.0, rot=(0, sx * -8, 0))
        # tool box on fender + spare links
        h.box((0.5, 1.1, 0.28), (sx * 1.65, 2.35, 1.72), "dark", bev=0.04)
        h.box((0.52, 1.0, 0.04), (sx * 1.65, 2.35, 1.87), "trim", bev=0.01)
    ang = math.degrees(math.atan2(1.58 - 1.22, 3.52 - 2.25))
    h.plate((2.6, 0.9, 0.05), (0, -2.75, 1.47), (ang, 0, 0), top="team", base="dark", inset=0.06)
    # glacis hazard stripes + spare track links + headlights + tow hooks
    h.hazard(3.4, 0.2, (0, -3.36, 1.27), (ang, 0, 0), n=12)
    for sx in (-1, 1):
        h.box((0.32, 0.22, 0.2), (sx * 1.0, -3.45, 1.22), "trim", bev=0.04)
        h.box((0.24, 0.04, 0.12), (sx * 1.0, -3.57, 1.22), "black", bev=0.0)
        for k in range(3):
            h.box((0.55, 0.16, 0.06), (sx * 1.6, -3.05 + k * 0.2, 1.36 + k * 0.057), "black", bev=0.01, rot=(ang, 0, 0))
    # engine deck: vents + exhausts
    h.vent(1.6, 1.3, (0, 2.2, 1.56), (-90, 0, 0), n=6, frame="trim", slat="black", depth=0.06)
    h.greebles(1.6, 1.4, (0, 0.6, 1.58), n=7, seed=3, hmax=0.1, smax=0.35)
    for sx in (-1, 1):
        h.add(g_tube(0.13, 0.09, 0.7, 12), "trim", (sx * 0.85, 3.3, 1.45), (-60, 0, 0))
        h.add(g_cyl(0.1, 0.05, 12), "black", (sx * 0.85, 3.6, 1.62), (-60, 0, 0))
        h.box((0.2, 0.12, 0.16), (sx * 0.45, 3.38, 0.98), "trim", bev=0.03)
    # rear plate with hazard
    h.hazard(1.8, 0.2, (0, 3.36, 1.05), (90, 0, 180), n=7)
    hull = h.finish(coll)

    # ---------------- turret ----------------
    t = PB("tank_turret", ["team", "dark", "trim", "glow"])
    tp = [(-0.72, -1.72), (0.72, -1.72), (1.48, -0.8), (1.55, 1.2), (1.15, 1.85), (-1.15, 1.85), (-1.55, 1.2), (-1.48, -0.8)]
    t.cyl(1.25, 0.18, (0, 0.05, 1.62), "dark", seg=24, bev=0.03)
    t.add(g_loft([(1.68, scale_pts(tp, 0.92, dy=0.05)), (1.8, tp), (2.48, scale_pts(tp, 0.86, dy=0.12))]), "dark")
    cap = scale_pts(tp, 0.74, dy=0.15)
    front = [p for p in cap if p[1] < 0] + [(1.12, 0.05), (-1.12, 0.05)]
    front = [(-0.53, -1.12), (0.53, -1.12), (1.08, -0.45), (1.12, 0.0), (-1.12, 0.0), (-1.08, -0.45)]
    rear = [(-1.13, 0.1), (1.13, 0.1), (1.13, 1.0), (0.84, 1.48), (-0.84, 1.48), (-1.13, 1.0)]
    t.add(_bevel(g_poly(front, 2.44, 2.54), 0.03), "team")
    t.add(_bevel(g_poly(rear, 2.44, 2.54), 0.03), "team")
    t.box((0.5, 0.1, 0.05), (0, 0.05, 2.5), "trim", bev=0.01)
    t.vent(0.9, 0.35, (0, 1.25, 2.56), (-90, 0, 0), n=4, frame="trim", slat="dark", depth=0.04)
    # cheek armour + bolts
    for sx in (-1, 1):
        with t.at((sx * 1.47, 0.15, 2.12), (0, sx * 12, 0)):
            t.box((0.12, 1.8, 0.5), (0, 0, 0), "dark", bev=0.04)
            t.bolts((sx * 0.07, -0.75, 0.15), (sx * 0.07, 0.75, 0.15), 5, r=0.03, axis_rot=(0, 90, 0))
        # smoke launchers
        for k in range(3):
            t.add(g_tube(0.07, 0.045, 0.32, 8), "trim", (sx * (1.25 + 0.1 * k), -1.05 + 0.12 * k, 2.38), (-55, sx * 20, 0))
        # sensor eyes
        t.box((0.32, 0.14, 0.18), (sx * 0.6, -1.62, 2.25), "trim", bev=0.03)
        t.box((0.24, 0.05, 0.09), (sx * 0.6, -1.7, 2.25), "glow", bev=0.0)
    # mantlet + gun
    t.box((1.0, 0.5, 0.62), (0, -1.85, 2.08), "dark", bev=0.08, seg=2)
    t.box((1.04, 0.08, 0.66), (0, -2.0, 2.08), "trim", bev=0.02)
    t.cyl(0.22, 0.8, (0, -2.4, 2.08), "dark", (90, 0, 0), seg=16, bev=0.03)
    t.cyl(0.13, 1.6, (0, -3.3, 2.08), "trim", (90, 0, 0), seg=16, bev=0.0)
    t.cyl(0.19, 0.5, (0, -3.15, 2.08), "dark", (90, 0, 0), seg=16, bev=0.04)
    t.box((0.4, 0.5, 0.32), (0, -4.15, 2.08), "dark", bev=0.05)
    for sx in (-1, 1):
        for k in range(3):
            t.box((0.04, 0.08, 0.2), (sx * 0.2, -4.0 - k * 0.13, 2.08), "glow" if False else "trim", bev=0.0)
    t.cyl(0.09, 0.03, (0, -4.41, 2.08), "glow", (90, 0, 0), seg=12)
    t.cyl(0.05, 0.4, (0.42, -2.0, 1.9), "trim", (90, 0, 0), seg=8)
    # commander cupola, hatch, periscopes
    t.cyl(0.4, 0.22, (0.7, 0.75, 2.6), "dark", seg=16, bev=0.04)
    t.add(g_dome(0.32, 16, 4, 0.12), "team", (0.7, 0.75, 2.7))
    for k in range(6):
        a = math.radians(-120 + 25 * k)
        t.box((0.12, 0.05, 0.06), (0.7 + 0.4 * math.sin(a), 0.75 - 0.4 * math.cos(a), 2.64), "glow", bev=0.0, rot=(0, 0, math.degrees(a)))
    t.cyl(0.3, 0.08, (-0.55, 0.9, 2.55), "trim", seg=12, bev=0.02)
    t.greebles(1.0, 0.8, (-0.4, -0.5, 2.52), n=5, seed=11, hmax=0.08, smax=0.25)
    # bustle rack + vent
    t.box((2.1, 0.5, 0.45), (0, 2.05, 2.05), "dark", bev=0.05)
    t.vent(1.2, 0.3, (0, 2.32, 2.05), (0, 0, 180), n=3, frame="trim", slat="dark", depth=0.05)
    t.antenna((-1.0, 1.55, 2.45), 1.4, r=0.025)
    t.antenna((1.05, 1.6, 2.45), 0.7, r=0.02, tip="trim")
    turret = t.finish(coll)
    return {"parts": [{"name": "hull", "obj": hull, "team": True, "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "turret", "obj": turret, "team": True, "pivot": (0, 0.05, 1.6), "axis": "yaw"}],
            "muzzles": [{"part": "turret", "pos": (0, -4.45, 2.08)}],
            "wreck_from": hull}


# ------------------------------------------------------------------ infantry


def _leg(coll, name, side, hip, s=1.0, bulk=1.0, team_knee=True, foot_len=0.5, slim=False):
    """one robot leg in rest pose. side=+1 left (+X), -1 right. hip=(x,y,z) joint."""
    L = PB(name, ["team", "dark", "trim", "black"] if team_knee else ["dark", "trim", "black"])
    hx, hy, hz = hip
    knee = (hx + side * 0.02 * s, hy - 0.09 * s, hz - 0.5 * s)
    ankle = (hx + side * 0.01 * s, hy + 0.05 * s, 0.17 * s)
    w = 0.24 * s * bulk * (0.8 if slim else 1.0)
    L.cyl(0.13 * s * bulk, 0.26 * s, hip, "trim", (0, 90, 0), seg=12, bev=0.02)
    L.cyl(0.08 * s, 0.32 * s, hip, "dark", (0, 90, 0), seg=8)
    # thigh: main strut + outer armour plate
    L.beam(hip, knee, w, w * 1.15, "dark", bev=0.04)
    with L.at(((hip[0] + knee[0]) / 2 + side * w * 0.45, (hip[1] + knee[1]) / 2 - 0.02, (hip[2] + knee[2]) / 2), (-10, side * 6, 0)):
        L.box((0.06 * s, w * 1.3, 0.42 * s), (0, 0, 0), "dark", bev=0.02)
        L.box((0.03 * s, w * 1.0, 0.06 * s), (side * 0.03 * s, 0, 0.12 * s), "trim", bev=0.0)
    L.box((w * 1.05, 0.08 * s, 0.3 * s), ((hip[0] + knee[0]) / 2, (hip[1] + knee[1]) / 2 - w * 0.62, (hip[2] + knee[2]) / 2 + 0.03 * s), "trim", bev=0.02, rot=(-8, 0, 0))
    # knee
    L.cyl(0.11 * s * bulk, w * 1.15, knee, "trim", (0, 90, 0), seg=12, bev=0.02)
    with L.at((knee[0], knee[1] - 0.12 * s, knee[2] + 0.02 * s), (-30, 0, 0)):
        L.add(g_frustum(w * 1.1, 0.2 * s, w * 0.8, 0.12 * s, 0.1 * s, bev=0.02), "dark", (0, 0, -0.05 * s))
        L.add(g_frustum(w * 0.9, 0.14 * s, w * 0.6, 0.08 * s, 0.03 * s, bev=0.01), "team" if team_knee else "trim", (0, 0, 0.05 * s))
    # shin + shin guard + piston
    L.beam(knee, ankle, w * 0.85, w * 1.0, "dark", bev=0.04)
    with L.at(((knee[0] + ankle[0]) / 2, (knee[1] + ankle[1]) / 2 - w * 0.55, (knee[2] + ankle[2]) / 2 + 0.03 * s), (15, 0, 0)):
        L.add(g_frustum(w * 1.05, 0.08 * s, w * 0.8, 0.06 * s, 0.4 * s, bev=0.02), "dark", (0, 0, -0.2 * s))
        L.box((w * 0.6, 0.03 * s, 0.05 * s), (0, -0.04 * s, 0.1 * s), "trim", bev=0.0)
        L.box((w * 0.6, 0.03 * s, 0.05 * s), (0, -0.04 * s, 0.0), "trim", bev=0.0)
    L.rod((knee[0], knee[1] + w * 0.6, knee[2] - 0.05 * s), (ankle[0], ankle[1] + w * 0.55, ankle[2] + 0.12 * s), 0.035 * s, "trim", 8)
    L.rod((knee[0], knee[1] + w * 0.6, knee[2] - 0.05 * s), (ankle[0], ankle[1] + w * 0.55, (knee[2] + ankle[2]) / 2), 0.05 * s, "black", 8)
    # ankle + foot
    L.cyl(0.08 * s, w * 0.95, ankle, "trim", (0, 90, 0), seg=10, bev=0.01)
    fl = foot_len * s
    fx = ankle[0]
    L.add(g_prism([(-fl * 0.55, 0.0), (fl * 0.45, 0.0), (fl * 0.45, 0.1 * s), (fl * 0.1, 0.16 * s), (-fl * 0.35, 0.13 * s), (-fl * 0.55, 0.06 * s)], w * 1.15, bev=0.025), "dark", (fx, ankle[1] - 0.02 * s, 0.0))
    L.add(g_prism([(-fl * 0.56, 0.0), (fl * 0.46, 0.0), (fl * 0.46, 0.035 * s), (-fl * 0.56, 0.035 * s)], w * 1.2, bev=0.0), "black", (fx, ankle[1] - 0.02 * s, 0.0))
    L.box((w * 0.9, 0.12 * s, 0.05 * s), (fx, ankle[1] - fl * 0.42, 0.135 * s), "trim", bev=0.015, rot=(-25, 0, 0))
    return L.finish(coll)


def _infantry(coll, key, opts):
    s = opts.get("scale", 1.0)
    bulk = opts.get("bulk", 1.0)
    hipz = 1.12 * s
    hx = 0.22 * s * bulk
    legs = []
    for nm, side in (("leg_l", 1), ("leg_r", -1)):
        hip = (side * hx, 0.0, hipz)
        ob = _leg(coll, key + "_" + nm, side, hip, s, bulk, opts.get("team_knee", True), slim=opts.get("slim", False))
        legs.append({"name": nm, "obj": ob, "team": opts.get("team_knee", True), "pivot": hip, "axis": "pitch"})
    return legs, hipz


def _torso_core(T, s, bulk, opts):
    """pelvis, waist, chest, collar, head, shoulders. Returns dict of anchor points."""
    hipz = 1.12 * s
    cw = 0.6 * s * bulk
    T.add(g_frustum(0.46 * s * bulk, 0.3 * s, 0.52 * s * bulk, 0.34 * s, 0.24 * s, bev=0.04), "dark", (0, 0.0, hipz - 0.1 * s))
    T.add(g_frustum(0.2 * s, 0.06 * s, 0.26 * s, 0.06 * s, 0.22 * s, bev=0.02), "trim", (0, -0.18 * s, hipz - 0.14 * s), (-8, 0, 0))
    T.cyl(0.15 * s * bulk, 0.22 * s, (0, 0.02 * s, hipz + 0.22 * s), "trim", seg=12, bev=0.02)
    T.cyl(0.18 * s * bulk, 0.06 * s, (0, 0.02 * s, hipz + 0.16 * s), "dark", seg=12, bev=0.01)
    z0, z1, z2 = hipz + 0.28 * s, hipz + 0.55 * s, hipz + 0.76 * s
    T.add(_bevel(g_loft([(z0, crect(cw * 0.75, 0.34 * s, 0.07 * s, 0, 0.0)),
                         (z1, crect(cw * 1.08, 0.46 * s, 0.1 * s, 0, -0.03 * s)),
                         (z2, crect(cw * 0.95, 0.4 * s, 0.1 * s, 0, 0.0))]), 0.02), "dark")
    chest_mat = opts.get("chest_mat", "team")
    with T.at((0, -0.235 * s, z1 + 0.02 * s), (-12, 0, 0)):
        T.add(g_frustum(cw * 0.9, 0.06 * s, cw * 0.7, 0.05 * s, 0.22 * s, bev=0.02), "dark", (0, 0, -0.12 * s))
        T.box((cw * 0.6, 0.03 * s, 0.05 * s), (0, -0.035 * s, 0.05 * s), chest_mat, bev=0.0)
        T.box((cw * 0.18, 0.03 * s, 0.09 * s), (0, -0.035 * s, -0.06 * s), "glow", bev=0.0)
    T.add(_bevel(g_poly(crect(cw * 0.75, 0.3 * s, 0.06 * s), z2 - 0.01, z2 + 0.03 * s), 0.01), chest_mat)
    T.cyl(0.11 * s, 0.1 * s, (0, 0.0, z2 + 0.06 * s), "trim", seg=10)
    hz0 = z2 + 0.08 * s
    hw = opts.get("head_w", 0.3) * s
    hd = 0.34 * s
    hh = opts.get("head_h", 0.3) * s
    T.add(_bevel(g_loft([(hz0, crect(hw * 0.85, hd * 0.85, 0.04 * s, 0, 0.01 * s)),
                         (hz0 + hh * 0.55, crect(hw, hd, 0.06 * s, 0, 0.0)),
                         (hz0 + hh, crect(hw * 0.85, hd * 0.85, 0.06 * s, 0, 0.02 * s))]), 0.015), "dark")
    vw = opts.get("visor_w", 0.7)
    T.box((hw * vw, 0.06 * s, hh * opts.get("visor_h", 0.18)), (0, -hd / 2 + 0.005, hz0 + hh * 0.55), "glow", bev=0.0)
    T.box((hw * min(vw + 0.15, 1.05), 0.05 * s, hh * 0.08), (0, -hd / 2, hz0 + hh * 0.72), "trim", bev=0.0)
    T.add(_bevel(g_frustum(hw * 0.7, hd * 0.75, hw * 0.45, hd * 0.6, 0.05 * s), 0.01), opts.get("helmet_mat", "team"), (0, 0.02 * s, hz0 + hh - 0.01))
    for sx in (-1, 1):
        T.box((0.04 * s, hd * 0.6, hh * 0.5), (sx * hw * 0.52, 0.02 * s, hz0 + hh * 0.4), "trim", bev=0.01)
    shz = z2 - 0.06 * s
    shx = cw * 0.62
    pm = opts.get("pauldron_mat", "team")
    psz = opts.get("pauldron", 1.0)
    for sx in (-1, 1):
        with T.at((sx * shx, 0.0, shz), (0, sx * 18, 0)):
            T.add(g_frustum(0.3 * s * bulk * psz, 0.4 * s * psz, 0.22 * s * bulk * psz, 0.32 * s * psz, 0.16 * s * psz, bev=0.04), "dark", (0, 0, -0.06 * s))
            T.add(g_frustum(0.24 * s * bulk * psz, 0.33 * s * psz, 0.17 * s * bulk * psz, 0.26 * s * psz, 0.04 * s, bev=0.012), pm, (0, 0, -0.06 * s + 0.16 * s * psz - 0.005))
            T.box((0.32 * s * bulk * psz, 0.42 * s * psz, 0.03 * s), (0, 0, -0.07 * s), "trim", bev=0.0)
    return {"z2": z2, "shz": shz, "shx": shx, "cw": cw, "hz0": hz0, "hh": hh, "hd": hd, "hw": hw}


def _arm(T, sh, elbow, hand, s, w=0.13, mat="dark", hand_mat="trim"):
    T.add(g_sphere(0.1 * s, 10, 6), "trim", sh)
    T.beam(sh, elbow, w * s, w * 1.1 * s, mat, bev=0.03)
    T.add(g_sphere(0.075 * s, 8, 6), "trim", elbow)
    T.beam(elbow, hand, w * 1.05 * s, w * 1.15 * s, mat, bev=0.03)
    e, h = Vector(elbow), Vector(hand)
    m, l = M_between(e.lerp(h, 0.2), e.lerp(h, 0.75))
    T.add(g_box(w * 1.4 * s, w * 1.4 * s, l, bev=0.025), "dark", m=m)
    if hand_mat:
        T.add(g_box(0.11 * s, 0.11 * s, 0.11 * s, bev=0.02), hand_mat, hand)


def _rifle(T, grip, s, length=0.95):
    """assault rifle along -Y; grip = top of the pistol grip; returns muzzle position"""
    gx, gy, gz = grip
    T.box((0.09 * s, length * 0.55 * s, 0.17 * s), (gx, gy - 0.12 * s, gz + 0.03 * s), "dark", bev=0.02)
    T.box((0.1 * s, 0.3 * s, 0.12 * s), (gx, gy + 0.25 * s, gz + 0.02 * s), "dark", bev=0.02)
    T.box((0.075 * s, length * 0.32 * s, 0.11 * s), (gx, gy - length * 0.5 * s, gz + 0.04 * s), "trim", bev=0.015)
    T.box((0.07 * s, 0.1 * s, 0.2 * s), (gx, gy - 0.12 * s, gz - 0.12 * s), "trim", bev=0.01, rot=(-15, 0, 0))
    T.box((0.07 * s, 0.07 * s, 0.13 * s), (gx, gy + 0.05 * s, gz - 0.08 * s), "dark", bev=0.01, rot=(15, 0, 0))
    T.box((0.06 * s, 0.22 * s, 0.07 * s), (gx, gy - 0.05 * s, gz + 0.16 * s), "dark", bev=0.01)
    T.box((0.04 * s, 0.02 * s, 0.04 * s), (gx, gy - 0.165 * s, gz + 0.16 * s), "glow", bev=0.0)
    tip = gy - length * 0.68 * s - 0.2 * s
    T.cyl(0.028 * s, 0.32 * s, (gx, gy - length * 0.68 * s - 0.04 * s, gz + 0.05 * s), "trim", (90, 0, 0), seg=8)
    T.cyl(0.045 * s, 0.1 * s, (gx, tip + 0.06 * s, gz + 0.05 * s), "dark", (90, 0, 0), seg=8)
    return (gx, tip, gz + 0.05 * s)


def _backpack(T, z2, s=1.0, w=0.42, h=0.42, glow=True):
    T.box((w * s, 0.22 * s, h * s), (0, 0.27 * s, z2 - 0.2 * s), "dark", bev=0.04)
    if glow:
        T.box((w * 0.7 * s, 0.04 * s, 0.08 * s), (0, 0.39 * s, z2 - 0.14 * s), "glow", bev=0.0)
    T.box(((w + 0.02) * s, 0.24 * s, 0.04 * s), (0, 0.27 * s, z2 + 0.02 * s), "trim", bev=0.01)
    for sx in (-1, 1):
        T.cyl(0.05 * s, 0.3 * s, (sx * 0.14 * s, 0.38 * s, z2 - 0.28 * s), "trim", seg=8)


@asset("soldier", "unit", size=[1.2, 2.4, 1.2])
def build_soldier(coll):
    s = 1.0
    legs, hipz = _infantry(coll, "soldier", {})
    T = PB("soldier_torso", ["team", "dark", "trim", "glow"])
    a = _torso_core(T, s, 1.0, {})
    shx, shz, z2 = a["shx"], a["shz"], a["z2"]
    grip = (-0.13, -0.42, 1.42)
    muzzle = _rifle(T, grip, s)
    _arm(T, (-shx, 0.0, shz - 0.04), (-shx - 0.02, 0.0, shz - 0.33), (grip[0] - 0.02, grip[1] + 0.05, grip[2] - 0.03), s)
    _arm(T, (shx, 0.0, shz - 0.04), (shx - 0.02, -0.2, shz - 0.33), (grip[0] + 0.07, grip[1] - 0.38, grip[2]), s)
    _backpack(T, z2, s)
    T.antenna((0.15, 0.3, z2 + 0.04), 0.45, r=0.012)
    torso = T.finish(coll)
    return {"parts": [{"name": "torso", "obj": torso, "team": True, "pivot": (0, 0, 0), "axis": "none"}] + legs,
            "muzzles": [{"part": "torso", "pos": muzzle}]}


# ------------------------------------------------------------------ preview sheets


def _load_rgba(path):
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return a


def _save_rgba(arr, path):
    import numpy as np
    h, w, _ = arr.shape
    img = bpy.data.images.new("sw_sheet_tmp", w, h, alpha=True)
    img.pixels[:] = arr.astype(np.float32).ravel()
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def sheet(paths, out, cols, bg=(0.32, 0.33, 0.35)):
    """tile PNGs (same size) into one image, composited over a grey background (bg=None keeps alpha)."""
    import numpy as np
    ims = [_load_rgba(p) for p in paths]
    h, w, _ = ims[0].shape
    rows = (len(ims) + cols - 1) // cols
    big = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    if bg is not None:
        big[..., :3] = bg
        big[..., 3] = 1
    for i, im in enumerate(ims):
        r, c = i // cols, i % cols
        y0 = (rows - 1 - r) * h      # blender images are bottom-up
        if bg is not None:
            a = im[..., 3:4]
            big[y0:y0 + h, c * w:(c + 1) * w, :3] = im[..., :3] * a + np.array(bg) * (1 - a)
        else:
            big[y0:y0 + h, c * w:(c + 1) * w] = im
    _save_rgba(big, out)
    return out


def preview(key, out, views=((35, 35), (215, 30), (120, 62)), res=400, wreck=False):
    tmp = []
    for i, (az, el) in enumerate(views):
        p = out[:-4] + "_v%d.png" % i
        render_view(key, p, res, az, el, 50, 1.04, wreck=wreck)
        tmp.append(p)
    sheet(tmp, out, len(tmp))
    for p in tmp:
        try:
            os.remove(p)
        except OSError:
            pass
    return out


def _crystal_shard(pb, base, h, r, tilt=(0, 0), rot=0.0, mat="crystal", sides=6):
    """hexagonal prism with a pointed tip, standing on base"""
    prof = [(0, -0.05 * h), (r, -0.05 * h), (r, h * 0.72), (r * 0.25, h * 0.97), (0, h)]
    pb.add(g_lathe(prof, sides, rot=rot), mat, base, (tilt[0], tilt[1], rot))


@asset("harvester", "unit", size=[4.5, 4.0, 8.0])
def build_harvester(coll):
    h = PB("harvester_hull", ["team", "dark", "trim", "crystal"])
    wheels = [(-2.85, 0.68, 0.42)] + [(y, 0.53, 0.38) for y in (-1.75, -0.6, 0.6, 1.75)] + [(2.95, 0.75, 0.45)]
    for sx in (-1, 1):
        h.track(sx * 1.72, 1.05, wheels, thick=0.1, n=64, grouser=0.05, wheel_mat="trim", belt="dark", hub="dark")
        # track fenders with team tops
        h.plate((1.15, 6.4, 0.12), (sx * 1.72, 0.05, 1.42), top="team", base="dark", inset=0.08)
        h.box((0.08, 6.0, 0.45), (sx * 2.27, 0.05, 1.15), "dark", bev=0.03)
        h.bolts((sx * 2.32, -2.8, 1.25), (sx * 2.32, 2.9, 1.25), 9, r=0.035, axis_rot=(0, 90, 0))
        h.hazard(1.0, 0.25, (sx * 1.72, -3.15, 1.49), (0, 0, 0), n=4)
    # chassis
    h.add(g_prism([(-3.1, 0.45), (3.2, 0.45), (3.55, 0.85), (3.55, 1.45), (-3.0, 1.45), (-3.45, 0.9)], 2.5, bev=0.05), "dark")
    # front drill mount: two arms + cross head
    for sx in (-1, 1):
        h.beam((sx * 0.85, -2.9, 1.0), (sx * 0.75, -3.8, 1.2), 0.3, 0.45, "dark", bev=0.04)
        h.rod((sx * 0.55, -2.9, 1.55), (sx * 0.5, -3.7, 1.3), 0.07, "trim", 8)
    h.box((1.9, 0.35, 0.6), (0, -3.75, 1.2), "dark", bev=0.06)
    h.cyl(0.55, 0.12, (0, -3.92, 1.2), "trim", (90, 0, 0), seg=20, bev=0.02)
    # cab (front left)
    cx = -1.15
    h.add(g_loft([(1.45, rect(1.7, 1.9, cx, -2.25)), (2.3, rect(1.7, 1.9, cx, -2.25)), (2.95, rect(1.5, 1.35, cx, -2.0))]), "dark")
    h.add(_bevel(g_poly(rect(1.3, 1.1, cx, -1.98), 2.94, 3.02), 0.02), "team")
    with h.at((cx, -2.95, 2.5), (-36, 0, 0)):
        h.box((1.35, 0.06, 0.38), (0, 0, 0), "crystal", bev=0.0)
        h.box((1.5, 0.08, 0.06), (0, 0.0, 0.24), "trim", bev=0.0)
    for sx in (-1, 1):
        h.box((0.06, 0.9, 0.28), (cx + sx * 0.86, -2.2, 2.45), "crystal", bev=0.0)
    h.light((cx - 0.5, -3.22, 2.0), size=0.2, glow="crystal")
    h.light((cx + 0.5, -3.22, 2.0), size=0.2, glow="crystal")
    h.antenna((cx + 0.5, -1.6, 3.0), 0.9, r=0.02, tip="crystal")
    # engine block (front right) with exhaust stacks
    h.box((1.5, 1.6, 0.8), (1.0, -2.3, 1.85), "dark", bev=0.06)
    h.vent(1.2, 0.5, (1.0, -3.1, 1.85), n=4, frame="trim", slat="dark")
    for k in range(2):
        h.add(g_tube(0.13, 0.09, 1.6, 12), "trim", (1.45 - k * 0.35, -1.75, 2.9))
        h.cyl(0.16, 0.12, (1.45 - k * 0.35, -1.75, 2.4), "dark", seg=12)
    h.greebles(1.3, 1.0, (1.0, -2.5, 2.25), n=5, seed=21, hmax=0.12)
    # ore bunker: open hopper full of energicum
    hp_out = crect(4.2, 4.3, 0.35, 0, 1.55)
    h.add(g_loft([(1.45, scale_pts(hp_out, 0.9, dy=0.15)), (3.45, hp_out), (3.65, scale_pts(hp_out, 1.0))], cap1=False), "dark")
    hp_in = scale_pts(hp_out, 0.92, dy=0.12)
    # rim (team) as a ring: outer loft top + inner wall
    h.add(g_frame(scale_pts(hp_out, 1.03, dy=-0.05), hp_in, 3.6, 3.78), "team")
    h.add(g_loft([(3.0, list(reversed(hp_in))), (3.6, list(reversed(hp_in)))], cap0=False, cap1=False), "dark")
    # cargo surface + crystals
    h.add(g_poly(hp_in, 3.05, 3.2), "dark")
    h.add(g_dome(1.5, 12, 3, 0.35), "dark", (0, 1.6, 3.15), scale=(1.15, 1.25, 1))
    rnd = random.Random(5)
    for i in range(30):
        px = rnd.uniform(-1.6, 1.6)
        py = rnd.uniform(-0.1, 3.3)
        rr = (px / 1.75) ** 2 + ((py - 1.6) / 1.9) ** 2
        zz = 3.15 + max(0.0, 0.35 * (1 - rr))
        _crystal_shard(h, (px, py, zz), rnd.uniform(0.3, 0.75), rnd.uniform(0.09, 0.19), (rnd.uniform(-30, 30), rnd.uniform(-30, 30)), rnd.uniform(0, 60))
    # hopper ribs + hazard band + ladder
    for sx in (-1, 1):
        for k in range(5):
            y = -0.35 + k * 0.95
            h.box((0.12, 0.14, 1.9), (sx * 2.02, y, 2.55), "trim", bev=0.02, rot=(0, sx * -3, 0))
    for k in range(4):
        h.box((0.06, 0.06, 1.8), (-0.6 + k * 0.4, 3.85, 2.5), "trim", bev=0.0)
    h.hazard(3.6, 0.3, (0, 3.83, 3.3), (90, 0, 180), n=10)
    for k in range(5):
        h.box((0.5, 0.05, 0.05), (1.4, 3.86, 1.6 + k * 0.38), "trim", bev=0.0)
    for sx in (-1, 1):
        h.box((0.05, 0.08, 2.0), (1.4 + sx * 0.25, 3.86, 2.4), "trim", bev=0.0)
    # side feed pipe from drill to hopper
    h.pipe([(-1.0, -3.6, 1.6), (-1.0, -3.2, 2.2), (-0.4, -1.0, 3.1), (-0.4, -0.45, 3.4)], 0.16, "trim", seg=10)
    hull = h.finish(coll)

    # ---------------- drill head (rolls about the long axis) ----------------
    d = PB("harvester_drill", ["dark", "trim", "crystal"])
    ay, az = -4.0, 1.2
    with d.at((0, ay, az), (90, 0, 0)):      # local +Z -> world -Y
        d.cyl(0.95, 0.3, (0, 0, 0.15), "dark", seg=24, bev=0.04)
        d.add(g_torus(0.82, 0.05, 24, 6), "crystal", (0, 0, 0.32))
        cone = [(0, 0.3), (0.9, 0.3), (0.82, 0.55), (0.12, 1.55), (0, 1.7)]
        d.add(g_lathe(cone, 16), "trim")
        # helical flutes with teeth
        for f in range(3):
            for k in range(9):
                t = k / 9
                z = 0.4 + t * 1.1
                r = 0.84 - 0.72 * t
                a = math.radians(f * 120 + t * 300)
                with d.at((r * math.cos(a), r * math.sin(a), z), (0, 0, math.degrees(a))):
                    d.add(g_box(0.16, 0.12, 0.2, bev=0.02), "dark", (0.03, 0, 0), (0, -38, 0))
                    d.add(g_cyl(0.05, 0.16, 6, r2=0.0), "trim", (0.12, 0, 0.02), (0, 90, 0))
        for k in range(8):
            a = math.radians(k * 45)
            d.add(g_box(0.2, 0.1, 0.18, bev=0.02), "dark", (0.88 * math.cos(a), 0.88 * math.sin(a), 0.4), (0, 0, k * 45))
    drill = d.finish(coll)
    return {"parts": [{"name": "hull", "obj": hull, "team": True, "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "drill", "obj": drill, "team": False, "pivot": (0, ay, az), "axis": "roll"}],
            "muzzles": [],
            "wreck_from": hull}


@asset("mcv", "unit", size=[5.0, 4.5, 10.0])
def build_mcv(coll):
    h = PB("mcv_hull", ["team", "dark", "trim", "black"])
    # chassis frame
    h.add(g_prism([(-4.6, 0.55), (4.7, 0.55), (4.95, 0.9), (4.95, 1.45), (-4.7, 1.45), (-4.98, 0.95)], 3.0, bev=0.05), "dark")
    for sx in (-1, 1):
        for y in (-3.4, -2.0, 2.0, 3.4):
            h.wheel((sx * 2.0, y, 0.72), 0.72, 0.62, side=sx)
            h.cyl(0.12, 0.6, (sx * 1.6, y, 0.72), "trim", (0, 90, 0), seg=8)
        # fenders (team tops)
        for yc in (-2.7, 2.7):
            h.add(g_prism([(-1.35, 0.0), (1.35, 0.0), (1.1, 0.35), (-1.1, 0.35)], 0.8, bev=0.04), "dark", (sx * 2.05, yc, 1.48))
            h.add(_bevel(g_prism([(-1.0, 0.0), (1.0, 0.0), (0.95, 0.06), (-0.95, 0.06)], 0.66), 0.015), "team", (sx * 2.05, yc, 1.82))
        # side box between axles (fuel tanks / stabiliser housings)
        h.box((0.6, 2.6, 0.75), (sx * 2.05, 0.0, 1.05), "dark", bev=0.06)
        h.hazard(2.4, 0.22, (sx * 2.36, 0.0, 1.2), (90, 0, sx * 90), n=8)
        # folded stabiliser legs at the corners
        for yy in (-4.2, 4.3):
            h.box((0.35, 0.4, 1.1), (sx * 2.25, yy, 1.35), "trim", bev=0.04)
            h.box((0.5, 0.55, 0.12), (sx * 2.25, yy, 0.8), "black", bev=0.03)
            h.rod((sx * 2.25, yy, 1.95), (sx * 2.25, yy, 2.5), 0.08, "trim", 8)
    # cab
    cab_y0, cab_y1 = -5.0, -3.1
    h.add(g_prism([(cab_y0 + 0.05, 1.4), (cab_y1, 1.4), (cab_y1, 3.25), (cab_y0 + 0.75, 3.25), (cab_y0, 2.3)], 4.5, bev=0.08), "dark")
    with h.at((0, cab_y0 + 0.38, 2.78), (-(90 - math.degrees(math.atan2(0.95, 0.75))), 0, 0)):
        h.box((4.0, 0.05, 0.75), (0, -0.01, 0), "trim", bev=0.0)
        h.box((0.1, 0.07, 0.8), (0, -0.02, 0), "black", bev=0.0)
    h.plate((4.1, 1.5, 0.08), (0, -3.95, 3.28), top="team", base="dark", inset=0.1)
    for sx in (-1, 1):
        h.box((0.06, 1.0, 0.55), (sx * 2.26, -4.0, 2.7), "trim", bev=0.0)
        h.light((sx * 1.7, -5.02, 1.95), size=0.25, glow="trim", housing="dark")
        h.box((0.08, 0.5, 0.35), (sx * 2.3, -4.6, 2.9), "trim", bev=0.02)    # mirrors
    h.box((3.6, 0.15, 0.4), (0, -5.0, 1.2), "trim", bev=0.04)              # bumper
    h.hazard(3.4, 0.3, (0, -5.08, 1.2), (90, 0, 0), n=10, mat="black")
    # container module
    cy0, cy1 = -2.95, 4.9
    L = cy1 - cy0
    yc = (cy0 + cy1) / 2
    h.box((4.4, L, 1.9), (0, yc, 2.4), "dark", bev=0.08, seg=2)
    for k in range(9):
        y = cy0 + 0.35 + k * (L - 0.7) / 8
        for sx in (-1, 1):
            h.box((0.12, 0.12, 1.7), (sx * 2.22, y, 2.4), "trim", bev=0.02)
    for sx in (-1, 1):
        h.box((0.05, L - 0.8, 0.1), (sx * 2.23, yc, 2.95), "black", bev=0.0)
        h.box((0.05, L - 0.8, 0.1), (sx * 2.23, yc, 1.85), "black", bev=0.0)
    # roof: two team panels + walkway + hazard edges
    for sx in (-1, 1):
        h.plate((1.6, L - 0.5, 0.08), (sx * 1.15, yc, 3.39), top="team", base="dark", inset=0.08)
    h.box((0.7, L - 0.3, 0.06), (0, yc, 3.38), "trim", bev=0.01)
    for k in range(12):
        h.box((0.66, 0.06, 0.04), (0, cy0 + 0.4 + k * (L - 0.8) / 11, 3.42), "dark", bev=0.0)
    h.hazard(4.0, 0.3, (0, cy1 + 0.02, 3.1), (90, 0, 180), n=11)
    h.vent(1.6, 0.9, (0, cy1 + 0.03, 2.3), (0, 0, 180), n=5, frame="trim", slat="black")
    for sx in (-1, 1):
        h.light((sx * 1.85, cy1 + 0.05, 1.7), (0, 0, 180), size=0.22, glow="trim", housing="black")
    # exhaust stacks behind the cab, roof light bar, grille, folded deploy panels, front roof module
    for sx in (-1, 1):
        h.add(g_tube(0.17, 0.12, 1.6, 12), "trim", (sx * 1.95, -2.85, 3.6))
        h.cyl(0.2, 0.3, (sx * 1.95, -2.85, 3.0), "dark", seg=12, bev=0.03)
        h.add(g_cyl(0.13, 0.03, 12), "black", (sx * 1.95, -2.85, 4.39))
    h.box((3.0, 0.3, 0.18), (0, -3.6, 3.45), "trim", bev=0.04)
    for k in range(5):
        h.box((0.35, 0.08, 0.12), (-1.2 + k * 0.6, -3.76, 3.45), "black", bev=0.0)
    for k in range(7):
        h.box((0.1, 0.08, 0.45), (-0.9 + k * 0.3, -5.0, 1.75), "trim", bev=0.0)
    for sx in (-1, 1):
        for k in range(3):
            y0 = -2.2 + k * 2.4
            with h.at((sx * 2.27, y0 + 0.9, 2.45), (0, 0, 0)):
                h.add(g_prism([(-0.95, -0.75), (0.95, -0.75), (0.75, 0.75), (-0.75, 0.75)], 0.08, bev=0.02), "dark", (sx * 0.02, 0, 0))
                h.add(g_prism([(-0.6, -0.5), (0.6, -0.5), (0.45, 0.5), (-0.45, 0.5)], 0.05, bev=0.01), "team", (sx * 0.07, 0, 0))
                h.rod((sx * 0.08, -0.95, -0.78), (sx * 0.08, 0.95, -0.78), 0.05, "trim", 6)
    h.box((3.6, 2.2, 0.5), (0, -1.75, 3.62), "dark", bev=0.06)
    h.plate((3.2, 1.8, 0.05), (0, -1.75, 3.88), top="team", inset=0.08)
    h.hazard(3.2, 0.25, (0, -2.87, 3.62), (90, 0, 0), n=9)
    hull = h.finish(coll)

    # ---------------- crane (yaw) ----------------
    c = PB("mcv_crane", ["team", "dark", "trim", "glow"])
    px, py, pz = 0.0, 2.6, 3.35
    c.cyl(0.85, 0.22, (px, py, pz + 0.11), "trim", seg=24, bev=0.03)
    c.add(g_frustum(1.3, 1.5, 1.1, 1.2, 0.75, bev=0.06), "dark", (px + 0.35, py + 0.1, pz + 0.22))
    c.add(_bevel(g_frustum(1.0, 1.1, 0.9, 0.95, 0.05), 0.015), "team", (px + 0.35, py + 0.1, pz + 0.96))
    c.box((0.06, 0.6, 0.3), (px + 1.01, py - 0.05, pz + 0.65), "glow", bev=0.0)
    c.add(g_cyl(0.09, 0.15, 8), "trim", (px + 0.55, py + 0.4, pz + 1.08))
    c.add(g_sphere(0.1, 8, 4), "glow", (px + 0.55, py + 0.4, pz + 1.2))
    # boom: lattice of two chords + cross members, resting forward over the cab
    root = Vector((px - 0.35, py - 0.3, pz + 0.75))
    tip = Vector((px - 0.35, -4.2, 4.4))
    for sz in (-1, 1):
        for sx in (-1, 1):
            off = Vector((sx * 0.22, 0, sz * 0.2))
            c.beam(root + off, tip + off * 0.6, 0.09, 0.09, "team" if sz > 0 else "dark", bev=0.015)
    n = 9
    for k in range(n + 1):
        p = root.lerp(tip, k / n)
        f = 1 - 0.4 * k / n
        c.box((0.5 * f, 0.06, 0.06), p + Vector((0, 0, 0.2 * f)), "trim", bev=0.0)
        c.box((0.5 * f, 0.06, 0.06), p + Vector((0, 0, -0.2 * f)), "trim", bev=0.0)
        if k < n:
            q = root.lerp(tip, (k + 1) / n)
            for sx in (-1, 1):
                c.beam(p + Vector((sx * 0.22 * f, 0, -0.2 * f)), q + Vector((sx * 0.22 * f, 0, 0.2 * f)), 0.04, 0.04, "trim", bev=0.0)
    c.beam(root + Vector((0, 0.1, -0.4)), root.lerp(tip, 0.3) + Vector((0, 0, -0.2)), 0.16, 0.16, "dark", bev=0.03)   # ram
    c.cyl(0.18, 0.5, tip + Vector((0, -0.1, 0)), "dark", (0, 90, 0), seg=12)
    c.rod(tip + Vector((0, -0.15, -0.1)), tip + Vector((0, -0.15, -0.5)), 0.02, "trim", 6)
    c.box((0.3, 0.3, 0.3), tip + Vector((0, -0.15, -0.62)), "dark", bev=0.04)
    c.add(g_box(0.32, 0.32, 0.05), "team", tip + Vector((0, -0.15, -0.5)))
    c.add(g_torus(0.1, 0.03, 12, 6), "trim", tip + Vector((0, -0.15, -0.86)), (90, 0, 0))
    crane = c.finish(coll)
    return {"parts": [{"name": "hull", "obj": hull, "team": True, "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "crane", "obj": crane, "team": True, "pivot": (px, py, pz), "axis": "yaw"}],
            "muzzles": [],
            "wreck_from": hull}


# ==================================================================
#                              BUILDINGS
# ==================================================================
MARGIN = 0.4


def _foundation(B, fx, fz, top=0.3, mat="dark", edge="trim", lights=True, stripes=True):
    """plinth reaching 1.5 m below ground; usable area = footprint minus MARGIN on each side."""
    w, d = fx - 2 * MARGIN, fz - 2 * MARGIN
    B.add(g_loft([(-1.5, rect(w, d)), (top - 0.12, rect(w, d)), (top, rect(w - 0.24, d - 0.24))]), mat)
    # steel edge band
    B.add(g_frame(rect(w + 0.02, d + 0.02), rect(w - 0.3, d - 0.3), top - 0.3, top - 0.12), edge)
    if stripes:
        for sy in (-1, 1):
            B.hazard(w * 0.3, 0.16, (0, sy * (d / 2 + 0.012), top - 0.21), (90, 0, 0 if sy < 0 else 180), n=max(4, int(w * 0.3 / 0.5)), t=0.02)
    if lights:
        for sx in (-1, 1):
            for sy in (-1, 1):
                B.box((0.3, 0.3, 0.12), (sx * (w / 2 - 0.35), sy * (d / 2 - 0.35), top + 0.06), "trim", bev=0.03)
                B.box((0.18, 0.18, 0.05), (sx * (w / 2 - 0.35), sy * (d / 2 - 0.35), top + 0.14), "glow", bev=0.0)
    return w, d


def _mast(B, base, h, w=0.6, mat="trim", tip="glow", n=None):
    """square lattice mast"""
    bx, by, bz = base
    n = n or max(3, int(h / 1.6))
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for cx, cy in corners:
        B.rod((bx + cx * w / 2, by + cy * w / 2, bz), (bx + cx * w * 0.25, by + cy * w * 0.25, bz + h), 0.05, mat, 6)
    for k in range(n):
        t0, t1 = k / n, (k + 1) / n
        z0, z1 = bz + h * t0, bz + h * t1
        s0, s1 = w / 2 * (1 - 0.5 * t0), w / 2 * (1 - 0.5 * t1)
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            B.rod((bx + a[0] * s0, by + a[1] * s0, z0), (bx + b[0] * s1, by + b[1] * s1, z1), 0.025, mat, 4)
            B.rod((bx + a[0] * s1, by + a[1] * s1, z1), (bx + b[0] * s1, by + b[1] * s1, z1), 0.025, mat, 4)
    B.add(g_sphere(0.15, 8, 5), tip, (bx, by, bz + h + 0.1))
    B.add(g_cyl(0.04, 1.2, 6), mat, (bx, by, bz + h + 0.6))


def _dish(B, center, r, rot=(0, 0, 0), mat="trim", back="dark", feed="glow", depth=None):
    """parabolic dish opening towards local +Z"""
    depth = depth or r * 0.35
    n = 8
    back_prof = [(0, -0.12)] + [(r * i / n, depth * (i / n) ** 2 - 0.12) for i in range(1, n + 1)] + [(r, depth)]
    inner = [(r * i / n, depth * (i / n) ** 2 + 0.002) for i in range(n, -1, -1)]
    with B.at(center, rot):
        B.add(g_lathe(back_prof, 24), back)
        B.add(g_lathe(inner, 24), mat)
        for k in range(3):
            a = math.radians(120 * k)
            B.rod((r * 0.8 * math.cos(a), r * 0.8 * math.sin(a), depth * 0.64), (0, 0, r * 0.75), 0.03, "trim", 4)
        B.add(g_cyl(0.12, 0.3, 8), "dark", (0, 0, r * 0.8))
        B.add(g_sphere(0.1, 8, 4), feed, (0, 0, r * 0.97))
        B.add(g_cyl(r * 0.18, 0.5, 12), back, (0, 0, -0.35))


def tank_at(B, c, r, h, mat="dark", band="trim", cap="team", glow=None, glow_dir=0.0):
    x, y, z = c
    with B.at((x, y, 0), (0, 0, glow_dir)):
        B.add(g_lathe([(0, z), (r, z), (r, z + h), (r * 0.7, z + h + r * 0.3), (0, z + h + r * 0.4)], 20), mat)
        B.add(g_lathe([(0, z + h + r * 0.36), (r * 0.48, z + h + r * 0.36), (r * 0.48, z + h + r * 0.5), (0, z + h + r * 0.5)], 16), cap)
        for k in range(3):
            B.add(g_cyl(r * 1.03, 0.15, 20), band, (0, 0, z + 0.3 + k * (h - 0.6) / 2))
        if glow:
            B.box((0.1, r * 0.4, h * 0.55), (r * 0.97, 0, z + h * 0.5), glow, bev=0.0)
            B.box((0.14, r * 0.5, 0.1), (r * 0.98, 0, z + h * 0.79), band, bev=0.0)
            B.box((0.14, r * 0.5, 0.1), (r * 0.98, 0, z + h * 0.21), band, bev=0.0)


def _stairs(B, base, w, h, run, rot=0.0, mat="trim", n=None):
    n = n or max(3, int(h / 0.25))
    with B.at(base, (0, 0, rot)):
        for k in range(n):
            B.box((w, run / n * 1.05, h / n), (0, -run / 2 + run * (k + 0.5) / n, h * (k + 0.5) / n), mat, bev=0.0)
        for sx in (-1, 1):
            B.rod((sx * w / 2, -run / 2, 0.9), (sx * w / 2, run / 2, h + 0.9), 0.03, "trim", 4)


def _window_band(B, x0, x1, y, z, h=0.35, n=6, mat="glow", frame="trim", face=-1):
    """row of windows on a wall facing -Y (face=-1) or +Y (face=+1)"""
    L = x1 - x0
    for k in range(n):
        x = x0 + L * (k + 0.5) / n
        B.box((L / n * 0.8, 0.06, h), (x, y + face * 0.02, z), mat, bev=0.0)
    B.box((L + 0.2, 0.1, 0.08), ((x0 + x1) / 2, y + face * 0.04, z + h / 2 + 0.06), frame, bev=0.0)
    B.box((L + 0.2, 0.1, 0.08), ((x0 + x1) / 2, y + face * 0.04, z - h / 2 - 0.06), frame, bev=0.0)


@asset("base", "building", footprint=[28, 28])
def build_base(coll):
    B = PB("base", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 28, 28)
    top = 0.3
    # --- main command block (octagonal, two tiers) ---
    oct1 = crect(15.5, 12.5, 3.0, 0, 1.5)
    B.add(_bevel(g_loft([(top, oct1), (5.6, scale_pts(oct1, 0.95, dy=0.1)), (6.0, scale_pts(oct1, 0.93, dy=0.14))]), 0.08), "dark")
    B.add(g_frame(scale_pts(oct1, 0.97, dy=0.1), scale_pts(oct1, 0.83, dy=0.34), 5.95, 6.25), "team")
    # buttresses
    for i, (px, py) in enumerate(oct1):
        B.add(g_frustum(1.0, 1.0, 0.6, 0.6, 4.8, bev=0.06), "dark", (px * 1.02, py * 1.0 + (0.02 if py > 0 else 0), top))
        B.box((0.7, 0.7, 0.14), (px * 1.02, py, top + 4.85), "trim", bev=0.03)
    # front facade: entrance + window rows
    fy = 1.5 - 6.25
    B.box((5.2, 0.5, 4.2), (0, fy - 0.15, top + 2.1), "trim", bev=0.06)       # door frame
    B.box((4.4, 0.4, 3.6), (0, fy - 0.3, top + 1.8), "dark", bev=0.02)       # door
    for k in range(6):
        B.box((4.3, 0.06, 0.08), (0, fy - 0.52, top + 0.4 + k * 0.6), "trim", bev=0.0)
    B.hazard(5.0, 0.3, (0, fy - 0.42, top + 4.05), (90, 0, 0), n=10, mat="team")
    B.light((-2.4, fy - 0.45, top + 4.4), size=0.35)
    B.light((2.4, fy - 0.45, top + 4.4), size=0.35)
    # entrance ramp + bollards
    B.add(g_prism([(-3.0, 0.0), (0.0, 0.0), (0.0, top + 0.02), (-2.9, top)], 5.0, bev=0.0), "trim", (0, fy - 0.2, 0.0))
    B.add(g_prism([(-5.0, top), (0.0, top), (0.0, top + 0.03), (-5.0, top + 0.03)], 5.4), "dark", (0, fy - 0.5, 0.0))
    for sx in (-1, 1):
        _window_band(B, sx * 3.2 - 1.3, sx * 3.2 + 1.3, fy + 0.12, top + 3.4, h=0.5, n=4)
        B.box((0.4, 0.4, 1.0), (sx * 3.0, fy - 2.6, top + 0.5), "trim", bev=0.06)
        B.box((0.3, 0.3, 0.1), (sx * 3.0, fy - 2.6, top + 1.05), "glow", bev=0.0)
    # --- second tier + command bridge ---
    oct2 = crect(10.5, 8.0, 1.8, 0, 2.5)
    B.add(_bevel(g_loft([(6.0, oct2), (9.0, scale_pts(oct2, 0.92, dy=0.25))]), 0.06), "dark")
    bridge = crect(13.0, 4.6, 1.3, 0, 0.3)
    B.add(_bevel(g_loft([(8.6, scale_pts(bridge, 0.9, dy=0.1)), (9.3, bridge), (10.9, scale_pts(bridge, 0.92, dy=0.15))]), 0.06), "dark")
    B.add(_bevel(g_poly(scale_pts(bridge, 0.84, dy=0.2), 10.85, 11.05), 0.03), "team")
    with B.at((0, 0.3 - 2.3, 10.1), (-14, 0, 0)):
        B.box((11.0, 0.08, 0.55), (0, -0.02, 0), "glow", bev=0.0)
        for k in range(11):
            B.box((0.1, 0.12, 0.6), (-5.0 + k * 1.0, -0.05, 0), "trim", bev=0.0)
    for sx in (-1, 1):
        with B.at((sx * 6.35, 0.3, 10.1), (0, 0, sx * -90)):
            B.box((2.4, 0.08, 0.45), (0, 0, 0), "glow", bev=0.0)
    # roof: dish + antennas + vents
    _dish(B, (2.3, 3.6, 9.2), 1.6, (35, 0, 160))
    B.antenna((-2.5, 3.5, 9.0), 3.0, r=0.05)
    B.antenna((-1.6, 4.0, 9.0), 2.0, r=0.04, tip="trim")
    B.vent(2.4, 1.6, (-1.5, 4.6, 9.05), (-90, 0, 0), n=6, frame="trim", slat="dark")
    B.greebles(3.0, 1.6, (0.3, 1.6, 10.9), n=6, seed=9, hmax=0.25, smax=0.6)
    # roof top of tier 1: team deck + walkways
    B.greebles(10.0, 2.0, (0, -2.2, 6.0), n=10, seed=4, hmax=0.3, smax=0.7)
    # --- landing platform (right) ---
    px, py, pz = 8.7, -6.7, 4.2
    for a in range(4):
        ang = math.radians(45 + 90 * a)
        B.beam((px + 2.2 * math.cos(ang), py + 2.2 * math.sin(ang), top), (px + 1.6 * math.cos(ang), py + 1.6 * math.sin(ang), pz - 0.3), 0.45, 0.45, "dark", bev=0.05)
    B.cyl(1.2, pz - top, (px, py, (pz + top) / 2), "dark", seg=12, bev=0.05)
    pad = ngon(3.6, 8, 22.5, px, py)
    B.add(_bevel(g_loft([(pz - 0.5, scale_pts(pad, 0.8, dx=px * 0.2, dy=py * 0.2)), (pz - 0.1, pad), (pz + 0.15, pad)]), 0.05), "dark")
    B.add(g_frame(ngon(3.62, 8, 22.5, px, py), ngon(3.2, 8, 22.5, px, py), pz + 0.12, pz + 0.24), "team")
    B.add(g_poly(ngon(3.2, 8, 22.5, px, py), pz + 0.15, pz + 0.17), "trim")
    # "H" marking
    for sx in (-1, 1):
        B.box((0.35, 2.4, 0.03), (px + sx * 0.8, py, pz + 0.18), "team", bev=0.0)
    B.box((1.6, 0.35, 0.03), (px, py, pz + 0.18), "team", bev=0.0)
    for k in range(8):
        a = math.radians(22.5 + 45 * k)
        B.box((0.22, 0.22, 0.12), (px + 3.35 * math.cos(a), py + 3.35 * math.sin(a), pz + 0.3), "glow", bev=0.02)
    _stairs(B, (px - 1.0, py + 4.4, top), 1.0, pz - top, 4.5, 180)
    # --- emergency generator (left front) ---
    gx, gy = -8.6, -6.4
    B.box((5.0, 4.0, 2.6), (gx, gy, top + 1.3), "dark", bev=0.1, seg=2)
    B.plate((4.6, 3.6, 0.1), (gx, gy, top + 2.65), top="team", inset=0.12)
    for k in range(5):
        B.box((0.25, 0.08, 1.6), (gx - 1.6 + k * 0.8, gy - 2.03, top + 1.3), "glow", bev=0.0)
        B.box((0.4, 0.14, 1.9), (gx - 1.6 + k * 0.8 + 0.4, gy - 2.03, top + 1.3), "trim", bev=0.02)
    B.cyl(1.0, 0.6, (gx + 1.0, gy + 0.5, top + 3.0), "trim", seg=16, bev=0.05)
    B.add(g_torus(0.85, 0.08, 20, 6), "glow", (gx + 1.0, gy + 0.5, top + 3.32))
    for k in range(2):
        B.add(g_tube(0.25, 0.18, 2.2, 12), "trim", (gx - 1.4 + k * 0.7, gy + 1.2, top + 3.5))
    B.pipe([(gx + 2.5, gy + 1.0, top + 1.0), (gx + 3.6, gy + 1.0, top + 1.0), (gx + 3.6, gy + 2.6, top + 1.0), (-6.0, gy + 2.6, top + 1.0)], 0.22, "trim")
    # --- antenna mast (left rear) + comms dish (right rear) ---
    _mast(B, (-9.0, 8.5, top), 16.0, w=1.4)
    B.box((2.0, 2.0, 0.8), (-9.0, 8.5, top + 0.4), "dark", bev=0.08)
    B.box((3.4, 2.6, 2.2), (8.4, 7.6, top + 1.1), "dark", bev=0.08)
    B.plate((3.0, 2.2, 0.08), (8.4, 7.6, top + 2.25), top="team", inset=0.1)
    _dish(B, (8.4, 7.6, top + 3.2), 2.2, (40, 0, 200))
    # --- side wings: storage + vents ---
    for sx in (-1, 1):
        B.box((3.0, 6.0, 3.2), (sx * 9.3, 2.0, top + 1.6), "dark", bev=0.08)
        B.plate((2.7, 5.6, 0.08), (sx * 9.3, 2.0, top + 3.25), top="team", inset=0.1)
        B.vent(2.0, 1.2, (sx * 10.82, 2.0, top + 1.7), (0, 0, sx * 90), n=5, frame="trim", slat="dark")
        B.pipe([(sx * 7.8, 0.0, top + 2.4), (sx * 7.3, 0.0, top + 2.4)], 0.25, "trim", joints=False)
    # slab markings: team corner chevrons, walkway to the door, rear tanks + garage
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * (w / 2 - 1.0), sy * (d / 2 - 1.0)
            B.box((3.2, 0.45, 0.04), (cx - sx * 1.375, cy, top + 0.02), "team", bev=0.0)
            B.box((0.45, 3.2, 0.04), (cx, cy - sy * 1.375, top + 0.02), "team", bev=0.0)
        B.box((0.25, 8.0, 0.03), (sx * 2.8, -9.6, top + 0.015), "trim", bev=0.0)
    B.hazard(5.4, 0.5, (0, -12.6, top + 0.002), (0, 0, 0), n=9, mat="team", t=0.03)
    tank_at(B, (4.6, 10.6, top), 1.3, 3.2, glow="glow", glow_dir=-90)
    tank_at(B, (7.6, 10.9, top), 1.3, 3.2, glow="glow", glow_dir=-90)
    B.pipe([(4.6, 9.2, top + 1.2), (4.6, 8.0, top + 1.2), (2.0, 8.0, top + 1.2), (2.0, 7.4, top + 1.2)], 0.2, "trim")
    B.box((5.5, 4.0, 3.4), (-3.0, 10.4, top + 1.7), "dark", bev=0.08)
    B.plate((5.1, 3.6, 0.08), (-3.0, 10.4, top + 3.45), top="team", inset=0.1)
    B.box((3.4, 0.2, 2.6), (-3.0, 12.42, top + 1.3), "trim", bev=0.03)
    for k in range(5):
        B.box((3.3, 0.06, 0.06), (-3.0, 12.54, top + 0.4 + k * 0.5), "dark", bev=0.0)
    # ground clutter: crates
    rnd = random.Random(3)
    for i in range(6):
        cx, cy = [(-5.0, -10.8), (4.4, -11.4), (-12.0, -3.0), (12.0, -1.5), (-8.0, 11.5), (11.8, 7.0)][i]
        s = rnd.uniform(0.8, 1.2)
        B.box((s, s, s), (cx + rnd.uniform(-0.5, 0.5), cy + rnd.uniform(-0.5, 0.5), top + s / 2), rnd.choice(["dark", "trim"]), bev=0.06)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "base", "pivot": (0, 0, 0), "axis": "none"}],
            "points": {"exit": (0.0, -15.0, 0.0)}}


def _tower(B, c, r, h, mat="dark", ring="trim", cap="team", glow=None, rings=4):
    """processing column with rings, catwalk and a team-painted cap"""
    x, y, z = c
    B.add(g_lathe([(0, z), (r * 1.15, z), (r * 1.15, z + 0.6), (r, z + 0.8), (r, z + h), (r * 0.8, z + h + 0.5), (0, z + h + 0.6)], 20), mat, (x, y, 0))
    for k in range(rings):
        zz = z + 1.5 + k * (h - 2.5) / max(1, rings - 1)
        B.add(g_cyl(r * 1.06, 0.22, 20), ring, (x, y, zz))
    B.add(g_frame(ngon(r * 1.45, 20, 0, x, y), ngon(r * 1.0, 20, 0, x, y), z + h * 0.62, z + h * 0.62 + 0.12), "trim")
    for k in range(10):
        a = 2 * math.pi * k / 10
        B.rod((x + r * 1.42 * math.cos(a), y + r * 1.42 * math.sin(a), z + h * 0.62), (x + r * 1.42 * math.cos(a), y + r * 1.42 * math.sin(a), z + h * 0.62 + 0.9), 0.025, "trim", 4)
    B.add(g_torus(r * 1.42, 0.03, 20, 4), "trim", (x, y, z + h * 0.62 + 0.9))
    B.add(g_cyl(r * 0.55, 0.2, 16), cap, (x, y, z + h + 0.65))
    if glow:
        for k in range(4):
            a = math.radians(45 + 90 * k)
            with B.at((x + r * math.cos(a), y + r * math.sin(a), z + h * 0.35), (0, 0, math.degrees(a))):
                B.box((0.12, 0.3, h * 0.35), (0, 0, 0), glow, bev=0.0)


@asset("refinery", "building", footprint=[20, 16])
def build_refinery(coll):
    B = PB("refinery", ["team", "dark", "trim", "crystal"])
    w, d = _foundation(B, 20, 16, lights=False)
    top = 0.3
    # main processing hall (rear), with team roof panels
    B.box((11.0, 6.0, 5.0), (0, 3.9, top + 2.5), "dark", bev=0.1, seg=2)
    for k in range(3):
        B.plate((3.3, 5.4, 0.1), (-3.6 + k * 3.6, 3.9, top + 5.05), top="team", inset=0.12)
    for k in range(4):
        B.box((0.4, 0.4, 5.0), (-5.4 + k * 3.6, 0.88, top + 2.5), "trim", bev=0.05)
    _window_band(B, -5.0, 5.0, 0.9, top + 4.2, h=0.4, n=8, mat="crystal")
    # processing towers (rear corners)
    _tower(B, (-7.0, 4.6, top), 1.5, 10.0, glow="crystal")
    _tower(B, (7.0, 4.6, top), 1.3, 8.0, glow="crystal")
    B.pipe([(-5.5, 4.6, top + 7.5), (-4.0, 4.6, top + 7.5), (-4.0, 4.6, top + 5.1)], 0.3, "trim")
    B.pipe([(5.7, 4.6, top + 6.5), (4.0, 4.6, top + 6.5), (4.0, 4.6, top + 5.1)], 0.3, "trim")
    # storage tanks with energicum windows (front sides)
    tank_at(B, (-7.2, -3.6, top), 1.6, 3.6, glow="crystal", glow_dir=-90)
    tank_at(B, (7.2, -3.6, top), 1.6, 3.6, glow="crystal", glow_dir=-90)
    tank_at(B, (-7.4, 0.4, top), 1.2, 2.6, glow="crystal", glow_dir=180)
    for sx in (-1, 1):
        B.pipe([(sx * 7.2, -3.6, top + 5.8), (sx * 7.2, -1.2, top + 5.8), (sx * 5.0, -1.2, top + 4.0), (sx * 5.0, 0.6, top + 4.0)], 0.22, "trim")
    # ---- docking bay (front centre, harvester unloads here) ----
    by0 = -d / 2
    B.add(g_poly(rect(7.4, 5.0, 0, by0 + 2.5), top - 0.02, top + 0.02), "trim")
    B.hazard(7.0, 0.5, (0, by0 + 0.35, top + 0.02), (0, 0, 0), n=12, mat="team", t=0.03)
    for sx in (-1, 1):
        # bay side walls with lights
        B.add(g_prism([(by0 + 0.2, 0), (by0 + 5.4, 0), (by0 + 5.4, 3.2), (by0 + 1.6, 3.2), (by0 + 0.2, 1.4)], 0.8, bev=0.06), "dark", (sx * 4.1, 0, top))
        B.add(_bevel(g_prism([(by0 + 1.6, 3.18), (by0 + 5.4, 3.18), (by0 + 5.4, 3.3), (by0 + 1.6, 3.3)], 0.7), 0.02), "team", (sx * 4.1, 0, top))
        for k in range(3):
            B.box((0.06, 0.4, 0.2), (sx * 3.68, by0 + 1.6 + k * 1.3, top + 1.2), "crystal", bev=0.0)
        B.hazard(1.4, 0.25, (sx * 3.69, by0 + 0.9, top + 0.5), (90, 0, sx * 90), n=3)
    # unloading gantry + chute arm reaching over the dock point
    for sx in (-1, 1):
        B.box((0.5, 0.5, 6.4), (sx * 3.4, by0 + 5.0, top + 3.2), "trim", bev=0.05)
    B.box((7.6, 1.2, 1.0), (0, by0 + 5.0, top + 6.6), "dark", bev=0.08)
    B.plate((7.2, 1.0, 0.06), (0, by0 + 5.0, top + 7.13), top="team", inset=0.05)
    arm0 = Vector((0, by0 + 4.6, top + 6.2))
    arm1 = Vector((0, by0 - 1.3, top + 5.0))
    B.beam(arm0, arm1, 1.0, 0.8, "dark", bev=0.06)
    B.beam(arm0 + Vector((0, 0, 0.45)), arm1 + Vector((0, 0, 0.45)), 0.5, 0.15, "team", bev=0.02)
    B.add(g_frustum(1.6, 1.6, 0.9, 0.9, 1.4, bev=0.05), "dark", (0, by0 - 1.3, top + 3.6))
    B.add(g_tube(0.7, 0.55, 0.2, 16), "crystal", (0, by0 - 1.3, top + 3.55))
    B.rod(arm0 + Vector((0, 0.3, -1.5)), arm1 + Vector((0, 0.6, -0.6)), 0.12, "trim", 8)
    # intake hopper at the back of the bay (glowing grate)
    B.add(g_frustum(5.0, 2.0, 6.4, 2.6, 2.4, bev=0.06), "dark", (0, by0 + 6.4, top))
    for k in range(7):
        B.box((0.12, 1.6, 0.08), (-1.8 + k * 0.6, by0 + 6.2, top + 2.43), "trim", bev=0.0)
    B.box((4.6, 1.8, 0.04), (0, by0 + 6.2, top + 2.38), "crystal", bev=0.0)
    # conveyor from hopper to hall
    B.beam((0, by0 + 7.0, top + 2.0), (0, 0.5, top + 4.0), 1.3, 0.5, "dark", bev=0.04)
    # pumps, vents, greebles
    B.vent(2.6, 1.2, (-3.6, 6.92, top + 2.0), (0, 0, 180), n=5, frame="trim", slat="dark")
    B.vent(2.6, 1.2, (3.6, 6.92, top + 2.0), (0, 0, 180), n=5, frame="trim", slat="dark")
    B.greebles(4.0, 2.4, (-5.6, -6.2, top), n=8, seed=13, hmax=0.7, smax=0.9)
    B.greebles(4.0, 2.4, (5.6, -6.6, top), n=8, seed=14, hmax=0.7, smax=0.9)
    B.antenna((2.8, 5.8, top + 5.1), 3.0, r=0.05, tip="crystal")
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "refinery", "pivot": (0, 0, 0), "axis": "none"}],
            "points": {"dock": (0.0, -9.5, 0.0)}}


@asset("powerplant", "building", footprint=[16, 16])
def build_powerplant(coll):
    B = PB("powerplant", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 16, 16)
    top = 0.3
    # cooling towers (rear) - hyperboloid shells, open top
    for sx in (-1, 1):
        cx, cy = sx * 3.8, 3.6
        prof = [(0, top), (3.0, top), (3.0, top + 0.6), (2.75, top + 1.2), (2.2, top + 4.5), (2.05, top + 6.2), (2.2, top + 7.6), (2.35, top + 8.4),
                (2.1, top + 8.4), (1.95, top + 7.6), (1.8, top + 6.2), (1.95, top + 4.5), (0, top + 4.5)]
        B.add(g_lathe(prof, 24), "dark", (cx, cy, 0))
        B.add(g_lathe([(2.2, top + 7.3), (2.28, top + 7.3), (2.4, top + 8.1), (2.32, top + 8.1)], 24, closed=True), "team", (cx, cy, 0))
        B.add(g_cyl(1.85, 0.05, 20), "glow", (cx, cy, top + 5.5))
        for k in range(12):
            a = 2 * math.pi * k / 12
            B.beam((cx + 3.0 * math.cos(a), cy + 3.0 * math.sin(a), top), (cx + 2.65 * math.cos(a), cy + 2.65 * math.sin(a), top + 1.6), 0.18, 0.18, "trim", bev=0.0)
    # turbine hall between the towers' feet and the reactor
    B.box((10.0, 4.0, 3.4), (0, -0.4, top + 1.7), "dark", bev=0.1, seg=2)
    B.plate((9.6, 3.6, 0.08), (0, -0.4, top + 3.45), top="team", inset=0.12)
    B.vent(3.0, 1.4, (-3.0, -2.42, top + 1.6), n=6, frame="trim", slat="dark")
    B.vent(3.0, 1.4, (3.0, -2.42, top + 1.6), n=6, frame="trim", slat="dark")
    for sx in (-1, 1):
        B.add(g_tube(0.3, 0.22, 2.5, 12), "trim", (sx * 4.3, -1.6, top + 4.5))
    # reactor (front centre): base drum, glowing core inside a cage, team cap
    rx, ry = 0.0, -4.4
    B.add(g_lathe([(0, top), (2.8, top), (2.8, top + 1.0), (2.4, top + 1.4), (0, top + 1.4)], 24), "dark", (rx, ry, 0))
    B.add(g_frame(ngon(2.86, 24, 0, rx, ry), ngon(2.5, 24, 0, rx, ry), top + 0.95, top + 1.15), "team")
    B.cyl(1.25, 5.0, (rx, ry, top + 3.9), "glow", seg=16)
    for k in range(8):
        a = 2 * math.pi * k / 8 + math.pi / 8
        B.box((0.35, 0.35, 5.2), (rx + 1.65 * math.cos(a), ry + 1.65 * math.sin(a), top + 3.9), "trim", bev=0.05, rot=(0, 0, math.degrees(a)))
    for k in range(3):
        B.add(g_torus(1.7, 0.16, 24, 6), "trim", (rx, ry, top + 2.2 + k * 1.7))
    B.add(g_lathe([(0, top + 6.3), (2.2, top + 6.3), (2.2, top + 6.7), (1.6, top + 7.3), (0, top + 7.45)], 24), "dark", (rx, ry, 0))
    B.add(g_lathe([(0, top + 7.4), (1.3, top + 7.4), (1.3, top + 7.55), (0, top + 7.6)], 20), "team", (rx, ry, 0))
    B.add(g_torus(2.0, 0.07, 24, 4), "glow", (rx, ry, top + 6.75))
    B.antenna((rx, ry, top + 7.55), 1.5, r=0.06)
    # coils / capacitors around the reactor
    for k in range(4):
        a = math.radians(-160 + k * 46.7)
        cx, cy = rx + 3.8 * math.cos(a), ry + 2.6 * math.sin(a) * 0.9
        if cy < -7.0:
            cy = -7.0
        B.cyl(0.45, 1.6, (cx, cy, top + 0.8), "dark", seg=12, bev=0.04)
        for j in range(4):
            B.add(g_torus(0.48, 0.06, 12, 4), "trim", (cx, cy, top + 0.35 + j * 0.3))
        B.add(g_sphere(0.22, 8, 5), "glow", (cx, cy, top + 1.75))
    # power cables (thick ducts) from reactor to the hall and out to the grid
    for sx in (-1, 1):
        B.pipe([(sx * 1.3, ry + 1.6, top + 0.5), (sx * 1.3, -2.4, top + 0.5)], 0.28, "dark")
        B.pipe([(sx * 5.2, -0.4, top + 2.6), (sx * 6.6, -0.4, top + 2.6), (sx * 6.6, -0.4, top + 0.5), (sx * 6.6, -6.6, top + 0.5)], 0.22, "dark")
        # pylon with glowing insulators
        px, py = sx * 6.4, -6.4
        B.beam((px, py, top), (px, py, top + 4.0), 0.3, 0.3, "trim", bev=0.03)
        B.box((1.8, 0.2, 0.2), (px, py, top + 3.8), "trim", bev=0.02)
        for j in (-1, 1):
            B.cyl(0.08, 0.35, (px + j * 0.75, py, top + 3.55), "glow", seg=6)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "powerplant", "pivot": (0, 0, 0), "axis": "none"}]}


def _gantry_crane(B, x, y0, y1, z, span, h=2.2):
    """portal crane straddling a roof: two rails along Y, portal at mid"""
    for sx in (-1, 1):
        B.box((0.25, y1 - y0, 0.2), (x + sx * span / 2, (y0 + y1) / 2, z + 0.1), "trim", bev=0.02)
    yc = y0 + (y1 - y0) * 0.35
    for sx in (-1, 1):
        B.box((0.5, 1.4, 0.35), (x + sx * span / 2, yc, z + 0.38), "dark", bev=0.05)
        B.beam((x + sx * span / 2, yc - 0.5, z + 0.5), (x + sx * span / 2, yc, z + h), 0.25, 0.25, "team", bev=0.03)
        B.beam((x + sx * span / 2, yc + 0.5, z + 0.5), (x + sx * span / 2, yc, z + h), 0.25, 0.25, "team", bev=0.03)
    B.box((span + 0.6, 0.6, 0.5), (x, yc, z + h + 0.15), "team", bev=0.05)
    B.box((1.0, 0.9, 0.6), (x - span * 0.2, yc, z + h - 0.3), "dark", bev=0.05)
    B.rod((x - span * 0.2, yc, z + h - 0.6), (x - span * 0.2, yc, z + 0.9), 0.03, "trim", 4)
    B.box((0.4, 0.4, 0.3), (x - span * 0.2, yc, z + 0.8), "dark", bev=0.04)


@asset("factory", "building", footprint=[24, 24])
def build_factory(coll):
    B = PB("factory", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 24, 24)
    top = 0.3
    # main hall
    hw, hd, hh = 16.0, 17.0, 8.5
    hy = 1.6
    B.box((hw, hd, hh), (0, hy, top + hh / 2), "dark", bev=0.15, seg=2)
    # wall pilasters + window band on the sides
    for sx in (-1, 1):
        for k in range(6):
            B.box((0.5, 0.6, hh + 0.3), (sx * (hw / 2 + 0.1), hy - hd / 2 + 1.2 + k * (hd - 2.4) / 5, top + (hh + 0.3) / 2), "trim", bev=0.06)
        with B.at((sx * (hw / 2 + 0.02), hy, top + 6.6), (0, 0, sx * 90)):
            B.box((hd - 2.0, 0.08, 0.5), (0, 0, 0), "glow", bev=0.0)
    # wall cladding: ribs, ledge, team band under the parapet, corner buttresses
    for sy in (-1, 1):
        yy = hy + sy * (hd / 2 + 0.06)
        for k in range(11):
            x = -hw / 2 + 0.8 + k * (hw - 1.6) / 10
            if sy < 0 and abs(x) < 6.2:
                continue
            B.box((0.22, 0.14, hh - 1.2), (x, yy, top + (hh - 1.2) / 2), "trim", bev=0.03)
    for sx in (-1, 1):
        for sy in (-1, 1):
            B.add(g_frustum(1.4, 1.4, 0.9, 0.9, hh + 0.4, bev=0.08), "dark", (sx * hw / 2, hy + sy * hd / 2, top))
    B.add(g_frame(rect(hw + 0.16, hd + 0.16, 0, hy), rect(hw - 0.1, hd - 0.1, 0, hy), top + hh - 1.1, top + hh - 0.55), "team")
    B.add(g_frame(rect(hw + 0.3, hd + 0.3, 0, hy), rect(hw - 0.1, hd - 0.1, 0, hy), top + 4.6, top + 4.85), "dark")
    by = hy + hd / 2 + 0.08
    for k in range(3):
        B.vent(2.2, 1.4, (-5.0 + k * 5.0, by, top + 6.0), (0, 0, 180), n=6, frame="trim", slat="dark")
    B.pipe([(-6.5, by + 0.4, top + 0.3), (-6.5, by + 0.4, top + 9.4), (-6.5, by - 1.0, top + 9.4)], 0.25, "trim")
    B.pipe([(6.8, by + 0.4, top + 0.3), (6.8, by + 0.4, top + 9.4), (6.8, by - 1.0, top + 9.4)], 0.25, "trim")
    for k in range(14):
        B.box((0.6, 0.06, 0.06), (-5.6, by + 0.25, top + 0.6 + k * 0.6), "trim", bev=0.0)
    for sx in (-1, 1):
        B.box((0.06, 0.08, 8.4), (-5.6 + sx * 0.3, by + 0.25, top + 4.5), "trim", bev=0.0)
    # roof: perimeter parapet, team panels, glowing skylights, crane rails + cranes
    rz = top + hh
    B.add(g_frame(rect(hw + 0.2, hd + 0.2, 0, hy), rect(hw - 0.5, hd - 0.5, 0, hy), rz - 0.05, rz + 0.5), "trim")
    for k in range(4):
        y = hy - hd / 2 + 2.3 + k * 4.1
        B.plate((hw - 1.6, 3.4, 0.1), (0, y, rz + 0.05), top="team", inset=0.15)
        B.box((hw - 4.0, 0.5, 0.18), (0, y + 1.95, rz + 0.1), "glow", bev=0.0)
    _gantry_crane(B, -3.2, hy - hd / 2 + 1.0, hy + hd / 2 - 1.0, rz + 0.2, 5.0)
    _gantry_crane(B, 3.6, hy - hd / 2 + 1.0, hy + hd / 2 - 1.0, rz + 0.2, 4.4, h=1.8)
    # front: big gate
    fy = hy - hd / 2
    gw, gh = 10.0, 7.0
    B.box((gw + 2.0, 1.2, gh + 1.2), (0, fy - 0.4, top + (gh + 1.2) / 2), "trim", bev=0.1)
    B.box((gw, 1.0, gh), (0, fy - 0.55, top + gh / 2), "dark", bev=0.03)       # door leaf (recessed)
    for k in range(8):
        B.box((gw - 0.4, 0.1, 0.1), (0, fy - 1.07, top + 0.6 + k * 0.85), "trim", bev=0.0)
    B.box((0.12, 0.12, gh - 0.2), (0, fy - 1.1, top + gh / 2), "black" if False else "trim", bev=0.0)
    B.hazard(gw + 1.6, 0.6, (0, fy - 1.02, top + gh + 0.6), (90, 0, 0), n=14, mat="team")
    for sx in (-1, 1):
        B.hazard(gh, 0.5, (sx * (gw / 2 + 0.5), fy - 1.02, top + gh / 2), (90, 90, 0), n=10, mat="team")
        B.light((sx * (gw / 2 - 0.6), fy - 1.1, top + gh + 1.5), size=0.45)
        B.rod((sx * (gw / 2 + 1.4), fy - 1.3, top + 0.3), (sx * (gw / 2 + 1.4), fy - 1.3, top + 6.0), 0.15, "trim", 10)
        B.box((0.6, 0.6, 0.8), (sx * (gw / 2 + 1.4), fy - 1.3, top + 6.2), "dark", bev=0.05)
    # gate apron with guide lines
    B.add(g_prism([(-3.4, 0.0), (0.0, 0.0), (0.0, top + 0.02), (-3.2, top)], gw + 1.0), "trim", (0, fy - 1.0, 0.0))
    for sx in (-1, 1):
        B.box((0.3, 3.0, 0.03), (sx * 3.0, fy - 2.6, top + 0.02), "glow", bev=0.0)
    # side annexes: left = furnace with chimneys, right = assembly control
    ax = hw / 2 + 2.0
    B.box((3.8, 10.0, 5.0), (-ax, 2.0, top + 2.5), "dark", bev=0.1)
    B.plate((3.4, 9.6, 0.08), (-ax, 2.0, top + 5.05), top="team", inset=0.12)
    for k in range(3):
        cy = -1.5 + k * 3.2
        B.add(g_lathe([(0, top + 4.9), (0.75, top + 4.9), (0.6, top + 9.5 + k * 0.6), (0.7, top + 9.8 + k * 0.6), (0.5, top + 9.8 + k * 0.6), (0, top + 9.0)], 14), "trim", (-ax, cy, 0))
        B.add(g_cyl(0.66, 0.25, 14), "dark", (-ax, cy, top + 8.4 + k * 0.6))
        B.add(g_cyl(0.48, 0.05, 12), "glow", (-ax, cy, top + 9.6 + k * 0.6))
    B.vent(2.8, 1.6, (-ax - 1.92, 2.0, top + 2.4), (0, 0, -90), n=6, frame="trim", slat="dark")
    B.box((3.8, 7.0, 3.6), (ax, 4.0, top + 1.8), "dark", bev=0.1)
    B.plate((3.4, 6.6, 0.08), (ax, 4.0, top + 3.65), top="team", inset=0.12)
    _window_band(B, ax - 1.4, ax + 1.4, 4.0 - 3.52, top + 2.6, h=0.6, n=3)
    _dish(B, (ax, 6.0, top + 4.2), 1.3, (35, 0, 150))
    tank_at(B, (ax, -2.6, top), 1.4, 3.0, glow="glow", glow_dir=-90)
    B.pipe([(ax, -2.6, top + 4.6), (ax - 1.8, -2.6, top + 4.6), (ax - 1.8, -1.0, top + 4.6), (hw / 2, -1.0, top + 4.6)], 0.22, "trim")
    # rear loading dock
    B.box((8.0, 1.6, 0.9), (0, hy + hd / 2 + 0.8, top + 0.45), "trim", bev=0.05)
    B.box((5.0, 0.3, 4.0), (0, hy + hd / 2 + 0.1, top + 2.0), "dark", bev=0.04)
    B.greebles(6.0, 1.4, (0, hy + hd / 2 + 0.8, top + 0.9), n=6, seed=17, hmax=0.6, smax=0.8)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "factory", "pivot": (0, 0, 0), "axis": "none"}],
            "points": {"exit": (0.0, -13.0, 0.0)}}


# ==================================================================
#                         RESOURCES / EFFECTS
# ==================================================================


def _rock(pb, c, r, seed, flat=0.55):
    rnd = random.Random(seed)
    bm = g_sphere(r, 9, 6)
    for v in bm.verts:
        k = 1 + rnd.uniform(-0.18, 0.18)
        v.co = Vector((v.co.x * k, v.co.y * k, v.co.z * k * flat))
    pb.add(bm, "rock", c)


def _crystal_group(key, coll, seed, n, size):
    pb = PB(key, ["rock", "crystal"])
    rnd = random.Random(seed)
    for i in range(5):
        a = rnd.uniform(0, 2 * math.pi)
        rr = rnd.uniform(0.0, size * 0.32)
        _rock(pb, (rr * math.cos(a), rr * math.sin(a), 0.0), rnd.uniform(0.4, 0.75) * size * 0.45, seed * 10 + i)
    for i in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        rr = rnd.uniform(0.0, size * 0.33) * (0.3 if i == 0 else 1.0)
        hgt = size * (1.0 if i == 0 else rnd.uniform(0.3, 0.75))
        rad = hgt * rnd.uniform(0.12, 0.18)
        tilt = 0 if i == 0 else min(55, rr / (size * 0.33) * 45 + rnd.uniform(0, 12))
        with pb.at((rr * math.cos(a), rr * math.sin(a), -0.15), (0, 0, math.degrees(a))):
            pb.add(g_lathe([(0, 0), (rad, 0), (rad, hgt * 0.72), (rad * 0.25, hgt * 0.97), (0, hgt)], 6, rot=15), "crystal", (0, 0, 0), (0, tilt, 0))
    return pb.finish(coll)


@asset("crystal_a", "prop")
def build_crystal_a(coll):
    return {"parts": [{"name": "main", "obj": _crystal_group("crystal_a", coll, 11, 9, 2.8), "team": False, "file": "crystal_a"}]}


@asset("crystal_b", "prop")
def build_crystal_b(coll):
    return {"parts": [{"name": "main", "obj": _crystal_group("crystal_b", coll, 23, 13, 3.8), "team": False, "file": "crystal_b"}]}


@asset("crystal_c", "prop")
def build_crystal_c(coll):
    return {"parts": [{"name": "main", "obj": _crystal_group("crystal_c", coll, 37, 6, 2.1), "team": False, "file": "crystal_c"}]}


@asset("rocketeer", "unit", size=[1.4, 2.5, 1.4])
def build_rocketeer(coll):
    s, bulk = 1.0, 1.18
    legs, hipz = _infantry(coll, "rocketeer", {"bulk": bulk})
    T = PB("rocketeer_torso", ["team", "dark", "trim", "glow"])
    a = _torso_core(T, s, bulk, {"pauldron": 1.15, "head_w": 0.32})
    shx, shz, z2 = a["shx"], a["shz"], a["z2"]
    # shoulder launcher on the right shoulder (-X), 2x2 tubes towards -Y
    lx, ly, lz = -shx - 0.16, 0.05, shz + 0.25
    T.box((0.44, 0.92, 0.38), (lx, ly, lz), "dark", bev=0.05)
    T.plate((0.38, 0.8, 0.04), (lx, ly + 0.02, lz + 0.19), top="team", inset=0.04)
    muzzles = []
    for ix in (-1, 1):
        for iz in (-1, 1):
            cx, cz = lx + ix * 0.105, lz + iz * 0.09
            T.add(g_tube(0.08, 0.06, 0.14, 12), "trim", (cx, ly - 0.49, cz), (90, 0, 0))
            T.cyl(0.061, 0.02, (cx, ly - 0.44, cz), "glow", (90, 0, 0), seg=10)
            muzzles.append((cx, ly - 0.57, cz))
    T.box((0.38, 0.06, 0.32), (lx, ly + 0.48, lz), "trim", bev=0.02)
    T.box((0.1, 0.26, 0.14), (lx - 0.3, ly - 0.3, lz + 0.12), "dark", bev=0.02)       # sight
    T.box((0.04, 0.03, 0.07), (lx - 0.3, ly - 0.44, lz + 0.12), "glow", bev=0.0)
    T.beam((lx + 0.1, ly + 0.1, lz - 0.28), (-shx * 0.7, 0.05, shz + 0.05), 0.12, 0.12, "trim")   # mount arm
    # right arm up to the launcher grip, left arm with ammo canister
    _arm(T, (-shx, 0.0, shz - 0.04), (-shx - 0.12, -0.15, shz - 0.36), (lx + 0.05, ly - 0.3, lz - 0.3), s, w=0.15)
    _arm(T, (shx, 0.0, shz - 0.04), (shx + 0.08, -0.05, shz - 0.4), (shx + 0.05, -0.3, shz - 0.55), s, w=0.15)
    T.cyl(0.07, 0.5, (shx + 0.05, -0.32, shz - 0.6), "trim", (90, 0, 0), seg=8)
    T.add(g_cyl(0.07, 0.14, 8, r2=0.0), "team", (shx + 0.05, -0.64, shz - 0.6), (90, 0, 0))
    # backpack with reload racks
    T.box((0.55, 0.28, 0.55), (0, 0.3, z2 - 0.22), "dark", bev=0.05)
    for k in range(3):
        T.cyl(0.07, 0.5, (-0.15 + k * 0.15, 0.48, z2 - 0.22), "trim", seg=8)
        T.add(g_cyl(0.07, 0.12, 8, r2=0.0), "team", (-0.15 + k * 0.15, 0.48, z2 + 0.09))
    T.box((0.3, 0.04, 0.08), (0, 0.45, z2 - 0.45), "glow", bev=0.0)
    torso = T.finish(coll)
    return {"parts": [{"name": "torso", "obj": torso, "team": True, "pivot": (0, 0, 0), "axis": "none"}] + legs,
            "muzzles": [{"part": "torso", "pos": m} for m in muzzles]}


@asset("engineer", "unit", size=[1.2, 2.4, 1.2])
def build_engineer(coll):
    s = 1.0
    legs, hipz = _infantry(coll, "engineer", {})
    T = PB("engineer_torso", ["team", "dark", "hazard", "glow"])
    T.alias = {"trim": "hazard"}
    a = _torso_core(T, s, 1.0, {"pauldron": 0.8, "chest_mat": "hazard"})
    shx, shz, z2 = a["shx"], a["shz"], a["z2"]
    # welder backpack: two gas bottles + generator box + hose
    T.box((0.46, 0.24, 0.5), (0, 0.27, z2 - 0.22), "dark", bev=0.04)
    for sx in (-1, 1):
        T.add(g_lathe([(0, z2 - 0.6), (0.11, z2 - 0.6), (0.11, z2 + 0.05), (0.07, z2 + 0.12), (0, z2 + 0.14)], 12), "team", (sx * 0.14, 0.48, 0))
        T.cyl(0.04, 0.08, (sx * 0.14, 0.48, z2 + 0.17), "dark", seg=8)
        T.add(g_cyl(0.115, 0.05, 12), "hazard", (sx * 0.14, 0.48, z2 - 0.3))
    T.box((0.3, 0.05, 0.08), (0, 0.4, z2 - 0.1), "glow", bev=0.0)
    T.hazard(0.42, 0.12, (0, 0.395, z2 - 0.38), (90, 0, 180), n=3, mat="hazard", t=0.015)
    # tool arm (right): forearm ends in a welding torch with a claw
    sh_r = (-shx, 0.0, shz - 0.04)
    el_r = (-shx - 0.06, -0.12, shz - 0.34)
    wr = (-0.3, -0.62, shz - 0.32)
    _arm(T, sh_r, el_r, wr, s, w=0.14, hand_mat=None)
    with T.at(wr, (90, 0, 0)):
        T.cyl(0.09, 0.2, (0, 0, 0.05), "dark", seg=10, bev=0.02)
        T.cyl(0.05, 0.28, (0, 0, 0.28), "hazard", seg=8)
        T.cyl(0.03, 0.08, (0, 0, 0.45), "dark", seg=8, r2=0.015)
        T.add(g_sphere(0.04, 8, 4), "glow", (0, 0, 0.5))
        for k in range(3):
            ang = 120 * k
            with T.at((0, 0, 0.12), (0, 0, ang)):
                T.beam((0.08, 0, 0), (0.13, 0, 0.22), 0.04, 0.04, "hazard", bev=0.0)
    torch_tip = (wr[0], wr[1] - 0.5, wr[2])
    T.pipe([(0.14, 0.45, z2 - 0.55), (-0.3, 0.3, z2 - 0.65), (-shx - 0.1, 0.0, shz - 0.45), (wr[0], wr[1] + 0.12, wr[2] - 0.08)], 0.025, "dark", seg=6, joints=False)
    # left arm holds a scanner
    hand_l = (shx - 0.05, -0.38, shz - 0.4)
    _arm(T, (shx, 0.0, shz - 0.04), (shx + 0.05, -0.08, shz - 0.36), hand_l, s, w=0.13)
    T.box((0.1, 0.24, 0.16), (hand_l[0], hand_l[1] - 0.1, hand_l[2] + 0.05), "dark", bev=0.02)
    T.box((0.08, 0.02, 0.1), (hand_l[0], hand_l[1] - 0.225, hand_l[2] + 0.05), "glow", bev=0.0)
    T.antenna((-0.15, 0.3, z2 + 0.04), 0.35, r=0.012, mat="hazard")
    torso = T.finish(coll)
    return {"parts": [{"name": "torso", "obj": torso, "team": True, "pivot": (0, 0, 0), "axis": "none"}] + legs,
            "muzzles": [{"part": "torso", "pos": torch_tip}]}


@asset("infiltrator", "unit", size=[1.0, 2.4, 1.0])
def build_infiltrator(coll):
    s, bulk = 1.0, 0.82
    legs, hipz = _infantry(coll, "infiltrator", {"bulk": bulk, "slim": True, "team_knee": False})
    T = PB("infiltrator_torso", ["team", "dark", "trim", "glow"])
    a = _torso_core(T, s, bulk, {"pauldron": 0.75, "pauldron_mat": "dark", "chest_mat": "dark", "visor_w": 1.02, "visor_h": 0.24, "head_w": 0.27, "head_h": 0.33, "helmet_mat": "dark"})
    shx, shz, z2 = a["shx"], a["shz"], a["z2"]
    # minimal team marking: thin stripe across the helmet + one shoulder chevron
    T.box((0.05, 0.3, 0.03), (0, 0.02, a["hz0"] + a["hh"] + 0.04), "team", bev=0.0)
    T.box((0.2, 0.06, 0.03), (shx + 0.02, -0.05, shz + 0.12), "team", bev=0.0, rot=(0, 18, 0))
    # sensor spine on the back
    for k in range(4):
        T.box((0.06, 0.12, 0.1), (0, 0.24 + k * 0.01, z2 - 0.05 - k * 0.14), "dark", bev=0.01, rot=(20, 0, 0))
        T.box((0.02, 0.02, 0.05), (0, 0.31 + k * 0.01, z2 - 0.05 - k * 0.14), "glow", bev=0.0)
    T.box((0.32, 0.16, 0.36), (0, 0.24, z2 - 0.25), "dark", bev=0.03)
    T.antenna((0.1, 0.25, z2 - 0.05), 0.55, r=0.01)
    # data-spike arm (right): forearm becomes a long blade/spike with glowing data lines
    sh_r = (-shx, 0.0, shz - 0.04)
    el_r = (-shx - 0.03, -0.08, shz - 0.33)
    wr = (-0.26, -0.48, shz - 0.36)
    _arm(T, sh_r, el_r, wr, s, w=0.11, hand_mat=None)
    tip = Vector(wr) + Vector((0.02, -0.75, -0.12))
    m, l = M_between(wr, tip)
    T.add(g_cyl(0.06, l, 4, r2=0.005), "trim", m=m)
    T.add(g_cyl(0.025, l * 0.8, 4, r2=0.004), "glow", m=m @ M((0.035, 0, -l * 0.05)))
    T.add(g_cyl(0.025, l * 0.8, 4, r2=0.004), "glow", m=m @ M((-0.035, 0, -l * 0.05)))
    T.cyl(0.08, 0.1, wr, "dark", (90, 0, 0), seg=8)
    # left arm: clawed hand held low
    hand_l = (shx + 0.02, -0.25, shz - 0.6)
    _arm(T, (shx, 0.0, shz - 0.04), (shx + 0.04, -0.02, shz - 0.33), hand_l, s, w=0.11)
    for k in range(3):
        T.beam(hand_l, (hand_l[0] - 0.04 + k * 0.04, hand_l[1] - 0.14, hand_l[2] - 0.08), 0.025, 0.025, "trim", bev=0.0)
    torso = T.finish(coll)
    return {"parts": [{"name": "torso", "obj": torso, "team": True, "pivot": (0, 0, 0), "axis": "none"}] + legs,
            "muzzles": [{"part": "torso", "pos": tuple(tip)}]}


def _skirts(h, x, sections, z0, z1, tilt=-8, bolts=True):
    """armoured side skirts on side x (sign of x picks the side)"""
    sx = 1 if x > 0 else -1
    for (y0, y1) in sections:
        yc, L = (y0 + y1) / 2, (y1 - y0)
        h.box((0.1, L, z1 - z0), (x, yc, (z0 + z1) / 2), "dark", bev=0.03, rot=(0, sx * tilt, 0))
        if bolts:
            h.bolts((x + sx * 0.06, y0 + 0.12, z1 - 0.1), (x + sx * 0.06, y1 - 0.12, z1 - 0.1), max(3, int(L / 0.45)), r=0.035, axis_rot=(0, 90, 0))
        h.box((0.05, L - 0.25, 0.07), (x + sx * 0.05, yc, z0 + 0.15), "trim", bev=0.0, rot=(0, sx * tilt, 0))


@asset("eliminator", "unit", size=[6.0, 4.5, 10.0])
def build_eliminator(coll):
    h = PB("eliminator_hull", ["team", "dark", "trim", "black"])
    wheels = [(-4.25, 0.92, 0.5)] + [(-3.15 + k * 1.05, 0.6, 0.42) for k in range(7)] + [(4.3, 0.98, 0.56)]
    for sx in (-1, 1):
        h.track(sx * 2.35, 1.3, wheels, thick=0.12, n=64, grouser=0.06, wheel_mat="dark", hub="trim")
        for k in range(12):
            with h.at((sx * 2.35, 4.3, 0.98), (k * 30, 0, 0)):
                h.box((0.7, 0.12, 0.2), (0, 0, 0.6), "trim", bev=0.01)
        _skirts(h, sx * 3.05, [(-4.3, -2.25), (-2.15, -0.05), (0.05, 2.15), (2.25, 4.2)], 0.75, 1.55)
        # fender plates (team)
        for (yc, L) in ((-2.7, 2.6), (0.0, 2.6), (2.7, 2.6)):
            h.plate((1.3, L - 0.1, 0.08), (sx * 2.3, yc, 2.02 - 0.012 * yc), (-0.8, 0, 0), top="team", inset=0.08)
        # stowage + spare links
        h.box((0.7, 1.4, 0.35), (sx * 2.3, 3.7, 2.2), "dark", bev=0.05)
        h.box((0.72, 1.3, 0.05), (sx * 2.3, 3.7, 2.39), "trim", bev=0.01)
    h.add(g_prism([(-4.2, 0.5), (4.2, 0.5), (4.75, 1.0), (4.75, 1.75), (-3.4, 1.75), (-4.9, 1.1)], 3.4, bev=0.06), "dark")
    h.add(g_prism([(-4.5, 1.45), (4.75, 1.45), (4.95, 1.95), (-3.2, 2.05), (-5.05, 1.62)], 6.0, bev=0.08), "dark")
    ang = math.degrees(math.atan2(2.05 - 1.62, 5.05 - 3.2))
    h.plate((3.6, 1.4, 0.08), (0, -4.0, 1.88), (ang, 0, 0), top="team", inset=0.1)
    h.hazard(5.6, 0.26, (0, -4.88, 1.69), (ang, 0, 0), n=16)
    # front ram plate
    h.add(g_prism([(-5.3, 0.55), (-4.6, 0.55), (-4.6, 1.35), (-5.05, 1.4)], 4.6, bev=0.05), "dark")
    for k in range(5):
        h.box((0.12, 0.3, 0.7), (-1.8 + k * 0.9, -5.22, 0.95), "trim", bev=0.02, rot=(-15, 0, 0))
    for sx in (-1, 1):
        h.light((sx * 1.9, -5.02, 1.62), (-20, 0, 0), size=0.28, glow="trim", housing="dark")
    # engine deck: vents, exhausts, greebles
    h.vent(2.4, 1.6, (0, 3.2, 2.0), (-90, 0, 0), n=7, frame="trim", slat="black", depth=0.06)
    h.greebles(2.6, 2.0, (0, 0.2, 2.04), n=9, seed=31, hmax=0.12, smax=0.4)
    for sx in (-1, 1):
        h.add(g_tube(0.2, 0.14, 1.1, 14), "trim", (sx * 1.3, 4.55, 1.9), (-60, 0, 0))
        h.cyl(0.15, 0.05, (sx * 1.3, 5.02, 2.17), "black", (-60, 0, 0), seg=14)
    h.hazard(2.6, 0.24, (0, 4.76, 1.4), (90, 0, 180), n=8)
    hull = h.finish(coll)

    t = PB("eliminator_turret", ["team", "dark", "trim", "glow"])
    tp = [(-1.05, -2.3), (1.05, -2.3), (2.0, -1.1), (2.05, 1.6), (1.5, 2.45), (-1.5, 2.45), (-2.05, 1.6), (-2.0, -1.1)]
    pz = 2.05
    t.cyl(1.7, 0.2, (0, 0.3, pz + 0.05), "dark", seg=28, bev=0.03)
    t.add(_bevel(g_loft([(pz + 0.1, scale_pts(tp, 0.92, dy=0.3)), (pz + 0.25, scale_pts(tp, 1.0, dy=0.3)), (pz + 1.25, scale_pts(tp, 0.86, dy=0.42))]), 0.07), "dark")
    front = [(-0.75, -1.45), (0.75, -1.45), (1.48, -0.6), (1.5, 0.15), (-1.5, 0.15), (-1.48, -0.6)]
    rear = [(-1.5, 0.3), (1.5, 0.3), (1.5, 1.4), (1.1, 2.0), (-1.1, 2.0), (-1.5, 1.4)]
    t.add(_bevel(g_poly(front, pz + 1.22, pz + 1.32), 0.03), "team")
    t.add(_bevel(g_poly(rear, pz + 1.22, pz + 1.32), 0.03), "team")
    # twin guns
    gz = pz + 0.72
    t.box((2.2, 0.6, 0.85), (0, -1.95, gz), "dark", bev=0.1, seg=2)
    t.box((2.26, 0.08, 0.9), (0, -2.2, gz), "trim", bev=0.02)
    muzzles = []
    for sx in (-1, 1):
        bx = sx * 0.55
        t.cyl(0.26, 0.9, (bx, -2.6, gz), "dark", (90, 0, 0), seg=16, bev=0.03)
        t.cyl(0.16, 2.3, (bx, -4.1, gz), "trim", (90, 0, 0), seg=16)
        t.cyl(0.23, 0.55, (bx, -3.7, gz), "dark", (90, 0, 0), seg=16, bev=0.04)
        t.box((0.45, 0.6, 0.38), (bx, -5.4, gz), "dark", bev=0.05)
        for k in range(3):
            t.box((0.5, 0.06, 0.24), (bx, -5.22 - k * 0.15, gz), "trim", bev=0.0)
        t.cyl(0.1, 0.03, (bx, -5.71, gz), "glow", (90, 0, 0), seg=12)
        muzzles.append((bx, -5.75, gz))
        # rocket boxes on the turret flanks
        rx = sx * 2.35
        t.box((0.85, 1.7, 0.85), (rx, 0.3, pz + 0.85), "dark", bev=0.07)
        t.plate((0.75, 1.5, 0.05), (rx, 0.3, pz + 1.28), top="team", inset=0.06)
        for i in range(3):
            for j in range(2):
                t.add(g_tube(0.11, 0.08, 0.1, 10), "trim", (rx - 0.24 + i * 0.24, -0.58, pz + 0.68 + j * 0.3), (90, 0, 0))
                t.cyl(0.08, 0.02, (rx - 0.24 + i * 0.24, -0.56, pz + 0.68 + j * 0.3), "glow", (90, 0, 0), seg=10)
        t.beam((sx * 1.7, 0.3, pz + 0.7), (sx * 1.95, 0.3, pz + 0.75), 0.4, 0.4, "trim", bev=0.03)
        # sensor eyes
        t.box((0.32, 0.14, 0.18), (sx * 1.0, -1.83, pz + 1.08), "trim", bev=0.03)
        t.box((0.24, 0.05, 0.09), (sx * 1.0, -1.91, pz + 1.08), "glow", bev=0.0)
    # cupola, hatch, bustle, antennas
    t.cyl(0.45, 0.28, (0.8, 1.1, pz + 1.45), "dark", seg=16, bev=0.04)
    t.add(g_dome(0.36, 16, 4, 0.14), "team", (0.8, 1.1, pz + 1.58))
    for k in range(6):
        a = math.radians(-120 + 25 * k)
        t.box((0.13, 0.05, 0.06), (0.8 + 0.45 * math.sin(a), 1.1 - 0.45 * math.cos(a), pz + 1.5), "glow", bev=0.0, rot=(0, 0, math.degrees(a)))
    t.cyl(0.35, 0.08, (-0.7, 1.2, pz + 1.34), "trim", seg=12, bev=0.02)
    t.box((3.0, 0.6, 0.7), (0, 2.85, pz + 0.65), "dark", bev=0.06)
    t.vent(1.8, 0.4, (0, 3.16, pz + 0.65), (0, 0, 180), n=3, frame="trim", slat="dark", depth=0.05)
    t.vent(1.2, 0.5, (0, 1.6, pz + 1.36), (-90, 0, 0), n=4, frame="trim", slat="dark", depth=0.04)
    t.antenna((-1.3, 2.2, pz + 1.25), 1.6, r=0.03)
    t.antenna((1.35, 2.3, pz + 1.25), 0.9, r=0.025, tip="trim")
    turret = t.finish(coll)
    return {"parts": [{"name": "hull", "obj": hull, "team": True, "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "turret", "obj": turret, "team": True, "pivot": (0, 0.3, pz), "axis": "yaw"}],
            "muzzles": [{"part": "turret", "pos": m} for m in muzzles],
            "wreck_from": hull}


@asset("terminator", "unit", size=[6.0, 4.5, 9.0])
def build_terminator(coll):
    h = PB("terminator_hull", ["team", "dark", "trim", "black"])
    wheels = [(-3.85, 0.82, 0.45)] + [(-2.6 + k * 1.04, 0.55, 0.38) for k in range(6)] + [(3.85, 0.88, 0.5)]
    for sx in (-1, 1):
        h.track(sx * 1.6, 1.0, wheels, thick=0.11, n=72, grouser=0.05, wheel_mat="dark", hub="trim")
        _skirts(h, sx * 2.12, [(-3.8, -1.3), (-1.2, 1.3), (1.4, 3.8)], 0.7, 1.35, tilt=-10)
        h.plate((1.0, 2.4, 0.07), (sx * 1.55, -2.3, 1.73), top="team", inset=0.07)
        h.plate((1.0, 2.4, 0.07), (sx * 1.55, 2.35, 1.72), top="team", inset=0.07)
        # jet pylons + axle housings (the nacelles themselves are separate parts)
        h.add(g_prism([(-0.9, 0.0), (1.1, 0.0), (0.7, 0.5), (-0.6, 0.5)], 0.5, bev=0.04), "dark", (sx * 1.95, 0.6, 1.95), (0, sx * -15, 0))
        h.cyl(0.32, 0.3, (sx * 2.1, 0.6, 2.75), "trim", (0, 90, 0), seg=14, bev=0.03)
        h.beam((sx * 1.4, 0.6, 2.2), (sx * 2.05, 0.6, 2.75), 0.45, 0.6, "dark", bev=0.05)
    h.add(g_prism([(-3.7, 0.45), (3.7, 0.45), (4.25, 0.9), (4.25, 1.6), (-3.0, 1.6), (-4.35, 1.0)], 2.4, bev=0.05), "dark")
    h.add(g_prism([(-3.9, 1.3), (4.2, 1.3), (4.4, 1.7), (-2.9, 1.8), (-4.5, 1.45)], 4.2, bev=0.07), "dark")
    ang = math.degrees(math.atan2(1.8 - 1.45, 4.5 - 2.9))
    h.plate((2.6, 1.1, 0.07), (0, -3.6, 1.66), (ang, 0, 0), top="team", inset=0.08)
    h.hazard(3.8, 0.22, (0, -4.33, 1.5), (ang, 0, 0), n=12)
    for sx in (-1, 1):
        h.light((sx * 1.4, -4.42, 1.33), (-15, 0, 0), size=0.24, glow="trim", housing="dark")
    # rear power pack with heat sinks
    h.box((2.6, 1.6, 0.6), (0, 3.3, 2.05), "dark", bev=0.06)
    for k in range(7):
        h.box((2.4, 0.08, 0.35), (0, 2.7 + k * 0.2, 2.45), "trim", bev=0.0)
    h.greebles(2.0, 1.6, (0, 0.6, 1.8), n=6, seed=41, hmax=0.12, smax=0.35)
    for sx in (-1, 1):
        h.add(g_tube(0.16, 0.11, 0.6, 12), "trim", (sx * 1.0, 4.2, 1.8), (-70, 0, 0))
    hull = h.finish(coll)

    # turret: compact head with a heavy beam cannon
    t = PB("terminator_turret", ["team", "dark", "trim", "glow"])
    pz = 1.8
    tp = [(-0.8, -1.6), (0.8, -1.6), (1.35, -0.6), (1.35, 1.0), (0.9, 1.6), (-0.9, 1.6), (-1.35, 1.0), (-1.35, -0.6)]
    t.cyl(1.15, 0.2, (0, 0.2, pz + 0.05), "dark", seg=24, bev=0.03)
    t.add(_bevel(g_loft([(pz + 0.1, scale_pts(tp, 0.9, dy=0.2)), (pz + 0.25, scale_pts(tp, 1.0, dy=0.2)), (pz + 1.05, scale_pts(tp, 0.8, dy=0.35))]), 0.06), "dark")
    t.add(_bevel(g_poly(scale_pts(tp, 0.66, dy=0.4), pz + 1.02, pz + 1.12), 0.03), "team")
    gz = pz + 0.62
    t.box((1.1, 0.8, 0.8), (0, -1.6, gz), "dark", bev=0.08, seg=2)
    t.cyl(0.3, 0.7, (0, -2.2, gz), "trim", (90, 0, 0), seg=16, bev=0.03)
    t.cyl(0.16, 2.2, (0, -3.4, gz), "dark", (90, 0, 0), seg=16)
    for k in range(5):
        t.add(g_torus(0.22, 0.06, 16, 6), "glow", (0, -2.7 - k * 0.38, gz), (90, 0, 0))
        t.cyl(0.25, 0.08, (0, -2.53 - k * 0.38, gz), "trim", (90, 0, 0), seg=16)
    t.add(g_lathe([(0, 0), (0.24, 0), (0.3, 0.35), (0.14, 0.42), (0, 0.42)], 16), "trim", (0, -4.5, gz), (90, 0, 0))
    t.cyl(0.11, 0.02, (0, -4.93, gz), "glow", (90, 0, 0), seg=12)
    muzzle = (0, -4.98, gz)
    # robot "head" sensor with eye slit
    t.box((0.7, 0.6, 0.4), (-0.75, -0.5, pz + 1.25), "dark", bev=0.06)
    t.box((0.5, 0.05, 0.08), (-0.75, -0.81, pz + 1.27), "glow", bev=0.0)
    t.add(_bevel(g_frustum(0.55, 0.45, 0.4, 0.35, 0.06), 0.01), "team", (-0.75, -0.48, pz + 1.44))
    for sx in (-1, 1):
        t.box((0.15, 1.6, 0.5), (sx * 1.2, 0.3, pz + 0.65), "dark", bev=0.04, rot=(0, sx * 15, 0))
    t.vent(1.0, 0.35, (0.3, 1.0, pz + 1.13), (-90, 0, 0), n=3, frame="trim", slat="dark", depth=0.04)
    t.antenna((0.85, 1.25, pz + 1.05), 1.2, r=0.025)
    turret = t.finish(coll)

    jets = []
    for nm, sx in (("jet_l", 1), ("jet_r", -1)):
        j = PB("terminator_" + nm, ["team", "dark", "trim", "glow"])
        cx, cy, cz = sx * 2.62, 0.6, 2.75
        L = 2.5
        with j.at((cx, cy, cz), (-90, 0, 0)):     # local +Z -> world +Y (nozzle at the rear)
            prof = [(0.0, -L / 2), (0.42, -L / 2), (0.5, -L / 2 + 0.25), (0.52, L / 2 - 0.7), (0.42, L / 2 - 0.15), (0.36, L / 2), (0.0, L / 2)]
            j.add(g_lathe(prof, 18), "dark")
            j.add(g_torus(0.44, 0.06, 18, 6), "trim", (0, 0, -L / 2 + 0.02))
            j.add(g_cyl(0.38, 0.04, 18), "black" if False else "trim", (0, 0, -L / 2 + 0.06))
            for k in range(8):
                with j.at((0, 0, -L / 2 + 0.08), (0, 0, k * 45 + 10)):
                    j.add(g_box(0.32, 0.08, 0.02, bev=0.0), "dark", (0.18, 0, 0), (0, 25, 0))
            j.add(g_cyl(0.1, 0.12, 10), "dark", (0, 0, -L / 2 + 0.1))
            # nozzle with glow core and petals
            j.add(g_tube(0.38, 0.3, 0.3, 18), "trim", (0, 0, L / 2 + 0.1))
            j.add(g_cyl(0.3, 0.04, 18), "glow", (0, 0, L / 2 - 0.02))
            j.add(g_cyl(0.18, 0.3, 12, r2=0.05), "glow", (0, 0, L / 2 + 0.05))
            for k in range(3):
                j.add(g_cyl(0.535, 0.08, 18), "trim", (0, 0, -0.4 + k * 0.45))
        # team spine on top + side fins
        j.box((0.24, L * 0.75, 0.08), (cx, cy - 0.1, cz + 0.52), "team", bev=0.02)
        j.box((0.06, 0.9, 0.45), (cx + sx * 0.5, cy + 0.6, cz + 0.05), "dark", bev=0.02)
        j.cyl(0.2, 0.32, (cx - sx * 0.55, cy, cz), "trim", (0, 90, 0), seg=12)
        jets.append({"name": nm, "obj": j.finish(coll), "team": True, "pivot": (cx - sx * 0.55, cy, cz), "axis": "pitch"})
    return {"parts": [{"name": "hull", "obj": hull, "team": True, "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "turret", "obj": turret, "team": True, "pivot": (0, 0.2, pz), "axis": "yaw"}] + jets,
            "muzzles": [{"part": "turret", "pos": muzzle}],
            "wreck_from": hull}


@asset("hypercopter", "unit", size=[10.0, 4.0, 12.0])
def build_hypercopter(coll):
    b = PB("hypercopter_body", ["team", "dark", "trim", "glow"])
    zc = 2.05
    # fuselage stations along Y: (y, width, height, chamfer, z centre)
    st = [(5.6, 0.5, 0.55, 0.12, 2.75), (3.0, 0.75, 0.8, 0.2, 2.6), (2.0, 1.9, 1.7, 0.45, 2.2), (-1.0, 2.6, 2.2, 0.6, 2.05),
          (-3.2, 2.4, 2.0, 0.6, 2.0), (-4.8, 1.7, 1.4, 0.45, 1.85), (-5.9, 0.7, 0.6, 0.2, 1.75)]
    rings = []
    for (y, w, hh, c, z) in reversed(st):
        rings.append((-y, crect(w, hh, c, 0, z)))
    rings.sort(key=lambda r: r[0])
    with b.at((0, 0, 0), (90, 0, 0)):
        b.add(_bevel(g_loft(rings), 0.03), "dark")
    # cockpit canopy (glow glass) + frame
    with b.at((0, -4.15, 2.62), (-24, 0, 0)):
        b.add(_bevel(g_frustum(1.5, 1.7, 1.0, 1.1, 0.32), 0.04), "glow")
        b.box((0.08, 1.75, 0.4), (0, 0, 0.18), "trim", bev=0.0)
    # dorsal spine (team) + engines
    b.add(_bevel(g_loft([(2.9, crect(1.2, 4.4, 0.3, 0, -0.6)), (3.25, crect(0.9, 3.8, 0.3, 0, -0.4))]), 0.04), "team")
    for sx in (-1, 1):
        b.add(g_lathe([(0, 0), (0.38, 0), (0.42, 0.4), (0.42, 2.2), (0.3, 2.6), (0, 2.6)], 14), "dark", (sx * 0.85, -1.2, 2.95), (-90, 0, 0))
        b.add(g_torus(0.36, 0.06, 14, 6), "trim", (sx * 0.85, -1.2, 2.95), (90, 0, 0))
        b.cyl(0.24, 0.05, (sx * 0.85, 1.42, 2.95), "glow", (90, 0, 0), seg=12)
    # stub wings carrying the ducts
    dx, dy, dz = 3.2, -0.6, 2.25
    for sx in (-1, 1):
        b.add(g_prism([(-0.9, -0.12), (0.9, -0.12), (1.0, 0.0), (0.6, 0.14), (-0.8, 0.12)], 1.1, bev=0.03), "dark", (sx * 1.3, dy, dz))
        b.add(_bevel(g_prism([(-0.7, 0.1), (0.6, 0.1), (0.5, 0.17), (-0.6, 0.16)], 0.8), 0.01), "team", (sx * 1.3, dy, dz))
        b.beam((sx * 1.2, dy - 0.3, dz - 0.05), (sx * (dx - 1.55), dy - 0.3, dz - 0.05), 0.25, 0.22, "dark", bev=0.03)
        b.beam((sx * 1.2, dy + 0.4, dz - 0.05), (sx * (dx - 1.55), dy + 0.4, dz - 0.05), 0.25, 0.22, "dark", bev=0.03)
        # duct ring (shroud)
        duct = [(1.55, -0.5), (1.72, -0.55), (1.8, -0.3), (1.8, 0.3), (1.7, 0.5), (1.55, 0.45)]
        b.add(g_lathe(duct, 32, closed=True), "dark", (sx * dx, dy, dz))
        b.add(g_frame(ngon(1.8, 32, 0, sx * dx, dy), ngon(1.58, 32, 0, sx * dx, dy), dz + 0.42, dz + 0.5), "team")
        # stator struts + motor pod
        for k in range(3):
            a = math.radians(90 + 120 * k)
            b.beam((sx * dx + 0.3 * math.cos(a), dy + 0.3 * math.sin(a), dz - 0.25), (sx * dx + 1.6 * math.cos(a), dy + 1.6 * math.sin(a), dz - 0.25), 0.1, 0.14, "trim", bev=0.0)
        b.add(g_lathe([(0, -0.6), (0.2, -0.55), (0.3, -0.3), (0.3, -0.05), (0, -0.05)], 12), "dark", (sx * dx, dy, dz))
        b.add(g_sphere(0.09, 8, 4), "glow", (sx * (dx + 1.8), dy, dz))
    # tail: fins + stabiliser
    b.add(g_prism([(-0.2, 0), (1.1, 0), (1.3, 1.25), (0.9, 1.3)], 0.12, bev=0.02), "dark", (0, 4.4, 2.9))
    b.add(_bevel(g_prism([(0.88, 1.15), (1.28, 1.15), (1.3, 1.3), (0.9, 1.3)], 0.14), 0.01), "team", (0, 4.4, 2.9))
    b.add(g_prism([(-0.3, -0.05), (0.7, -0.05), (0.8, 0.05), (-0.2, 0.06)], 3.0, bev=0.02), "dark", (0, 5.0, 2.8))
    for sx in (-1, 1):
        b.add(g_prism([(-0.25, 0), (0.6, 0), (0.75, 0.6), (0.35, 0.6)], 0.08, bev=0.01), "dark", (sx * 1.5, 5.0, 2.8))
    b.add(g_sphere(0.08, 8, 4), "glow", (0, 5.7, 4.25))
    # landing skids
    for sx in (-1, 1):
        b.add(g_lathe([(0, -2.2), (0.08, -2.1), (0.08, 2.1), (0, 2.2)], 8), "trim", (sx * 1.1, -0.5, 0.1), (90, 0, 0))
        for yy in (-1.8, 0.9):
            b.beam((sx * 1.1, yy - 0.5, 0.1), (sx * 0.8, yy - 0.5, 1.05), 0.1, 0.1, "trim", bev=0.0)
    # cargo winch + hook
    b.box((0.7, 0.9, 0.35), (0, -0.4, 0.95), "dark", bev=0.05)
    b.rod((0, -0.4, 0.8), (0, -0.4, 0.5), 0.02, "trim", 4)
    b.box((0.25, 0.2, 0.18), (0, -0.4, 0.45), "team", bev=0.03)
    b.add(g_torus(0.1, 0.03, 12, 6), "trim", (0, -0.4, 0.3), (90, 0, 0))
    # nose sensor + lights + weapons pods
    b.add(g_sphere(0.2, 10, 6), "glow", (0, -5.85, 1.6))
    b.light((0, -5.3, 1.25), (-30, 0, 0), size=0.16)
    b.antenna((0.3, 1.5, 3.0), 0.9, r=0.02)
    b.vent(0.9, 0.4, (0, 0.5, 3.12), (-90, 0, 0), n=3, frame="trim", slat="dark", depth=0.04)
    body = b.finish(coll)

    rotors = []
    for nm, sx in (("rotor_l", 1), ("rotor_r", -1)):
        r = PB("hypercopter_" + nm, ["team", "dark", "trim"])
        cx, cy, cz = sx * dx, dy, dz + 0.05
        r.add(g_dome(0.26, 12, 3, 0.18), "trim", (cx, cy, cz + 0.06))
        r.cyl(0.26, 0.12, (cx, cy, cz), "dark", seg=12)
        for k in range(6):
            a = 60 * k
            with r.at((cx, cy, cz), (0, 0, a)):
                r.add(g_box(1.2, 0.3, 0.04, bev=0.0), "dark", (0.85, 0, 0), (18, 0, 0))
                r.add(g_box(0.26, 0.31, 0.045, bev=0.0), "team", (1.36, 0, 0), (18, 0, 0))
        rotors.append({"name": nm, "obj": r.finish(coll), "team": True, "pivot": (cx, cy, cz), "axis": "yaw"})
    return {"parts": [{"name": "body", "obj": body, "team": True, "pivot": (0, 0, 0), "axis": "none"}] + rotors,
            "muzzles": [],
            "wreck_from": body}


@asset("silo", "building", footprint=[12, 12])
def build_silo(coll):
    B = PB("silo", ["team", "dark", "trim", "crystal"])
    w, d = _foundation(B, 12, 12, lights=False)
    top = 0.3
    B.add(_bevel(g_poly(ngon(4.6, 6, 30), top, top + 0.6, 0.94), 0.05), "dark")
    caps = [(0.0, -2.3), (-2.0, 1.2), (2.0, 1.2)]
    H = 6.5
    for i, (cx, cy) in enumerate(caps):
        z0 = top + 0.6
        B.add(g_lathe([(0, z0), (1.55, z0), (1.55, z0 + 0.7), (1.35, z0 + 0.9), (0, z0 + 0.9)], 20), "dark", (cx, cy, 0))
        # glowing energicum column inside a glass-like cage
        B.add(g_lathe([(0, z0 + 0.85), (1.05, z0 + 0.85), (1.05, z0 + H - 0.5), (0.7, z0 + H - 0.1), (0, z0 + H)], 16), "crystal", (cx, cy, 0))
        for k in range(8):
            a = 2 * math.pi * k / 8
            B.box((0.16, 0.16, H - 0.2), (cx + 1.17 * math.cos(a), cy + 1.17 * math.sin(a), z0 + 0.9 + (H - 0.2) / 2), "trim", bev=0.03, rot=(0, 0, math.degrees(a)))
        for k in range(3):
            B.add(g_torus(1.2, 0.09, 20, 6), "trim", (cx, cy, z0 + 1.8 + k * 1.8))
        B.add(g_lathe([(0, z0 + H + 0.5), (1.4, z0 + H + 0.5), (1.4, z0 + H + 0.7), (1.0, z0 + H + 1.1), (0, z0 + H + 1.2)], 20), "dark", (cx, cy, 0))
        B.add(g_lathe([(0, z0 + H + 1.15), (0.8, z0 + H + 1.15), (0.75, z0 + H + 1.25), (0, z0 + H + 1.3)], 16), "team", (cx, cy, 0))
        B.add(g_frame(ngon(1.45, 20, 0, cx, cy), ngon(1.0, 20, 0, cx, cy), z0 + H + 0.45, z0 + H + 0.58), "team")
        B.add(g_cyl(0.2, 0.6, 8), "trim", (cx, cy, z0 + H + 1.5))
    # central pump + connecting pipes
    B.cyl(0.9, 2.4, (0, -0.2, top + 1.8), "dark", seg=16, bev=0.06)
    B.add(g_torus(0.92, 0.07, 16, 4), "crystal", (0, -0.2, top + 2.6))
    B.add(g_dome(0.9, 16, 4, 0.5), "team", (0, -0.2, top + 3.0))
    for (cx, cy) in caps:
        v = Vector((cx, cy + 0.2, 0)).normalized()
        B.pipe([(v.x * 0.8, -0.2 + v.y * 0.8, top + 2.2), (cx - v.x * 1.5, cy - v.y * 1.5, top + 2.2)], 0.2, "trim", joints=False)
    # walkway ring + stairs
    B.hazard(4.0, 0.4, (0, -5.0, top + 0.002), n=7, mat="team", t=0.03)
    B.greebles(2.5, 1.5, (4.0, 3.6, top), n=6, seed=51, hmax=0.6, smax=0.7)
    B.greebles(2.0, 1.5, (-4.0, -3.8, top), n=5, seed=52, hmax=0.6, smax=0.7)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "silo", "pivot": (0, 0, 0), "axis": "none"}]}


@asset("hangar", "building", footprint=[28, 28])
def build_hangar(coll):
    B = PB("hangar", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 28, 28, lights=False, stripes=False)
    top = 0.3
    pads = []
    for px in (-7, 7):
        for py in (-7, 7):
            pads.append((px, py))
            # pad surface (slightly raised), edge band, team ring, crosshair, lights
            B.add(_bevel(g_poly(crect(11.6, 11.6, 1.0, px, py), top, top + 0.12), 0.04), "dark")
            B.add(g_frame(crect(11.7, 11.7, 1.05, px, py), crect(11.1, 11.1, 0.8, px, py), top, top + 0.16), "trim")
            B.add(g_frame(ngon(4.4, 32, 0, px, py), ngon(3.8, 32, 0, px, py), top + 0.12, top + 0.15), "team")
            for k in range(4):
                a = 90 * k
                with B.at((px, py, top + 0.12), (0, 0, a)):
                    B.box((0.35, 2.2, 0.03), (0, 2.6, 0.015), "team", bev=0.0)
                    B.box((1.4, 0.3, 0.03), (0, 5.0, 0.015), "trim", bev=0.0)
            B.box((1.2, 1.2, 0.03), (px, py, top + 0.135), "trim", bev=0.0)
            for cx in (-1, 1):
                for cy in (-1, 1):
                    B.box((0.3, 0.3, 0.14), (px + cx * 5.3, py + cy * 5.3, top + 0.19), "trim", bev=0.03)
                    B.box((0.2, 0.2, 0.05), (px + cx * 5.3, py + cy * 5.3, top + 0.28), "glow", bev=0.0)
            for k in range(5):
                B.box((0.18, 0.18, 0.06), (px - 2.4 + k * 1.2, py - 5.6 * (1 if py < 0 else -1), top + 0.17), "glow", bev=0.0)
    # centre service strip with taxi lights
    for k in range(9):
        B.box((0.16, 0.16, 0.06), (0, -12.0 + k * 3.0, top + 0.03), "glow", bev=0.0)
        B.box((0.16, 0.16, 0.06), (-12.0 + k * 3.0, 0, top + 0.03), "glow", bev=0.0)
    # control mast (centre)
    B.add(g_frustum(1.4, 1.4, 1.0, 1.0, 7.0, bev=0.08), "dark", (0, 0, top))
    for k in range(4):
        B.box((0.1, 0.1, 6.6), (0.55 * (1 if k % 2 else -1), 0.55 * (1 if k < 2 else -1), top + 3.4), "trim", bev=0.0)
    cab = ngon(1.6, 8, 22.5)
    B.add(_bevel(g_loft([(top + 7.0, scale_pts(cab, 0.6)), (top + 7.4, cab), (top + 8.6, scale_pts(cab, 1.08)), (top + 8.8, scale_pts(cab, 0.95))]), 0.04), "dark")
    for k in range(8):
        a = math.radians(22.5 + 45 * k + 22.5)
        with B.at((1.62 * math.cos(a), 1.62 * math.sin(a), top + 8.0), (0, 0, math.degrees(a) + 90)):
            B.box((1.0, 0.05, 0.6), (0, 0, 0), "glow", bev=0.0)
    B.add(_bevel(g_poly(scale_pts(cab, 1.0), top + 8.78, top + 8.95), 0.03), "team")
    B.antenna((0.4, 0.2, top + 8.95), 2.5, r=0.04)
    _dish(B, (-0.5, -0.4, top + 9.3), 0.6, (40, 0, 30))
    B.add(g_sphere(0.15, 8, 4), "glow", (0, 0, top + 7.2))
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "hangar", "pivot": (0, 0, 0), "axis": "none"}],
            "points": {"pads": [(px, py, top) for (px, py) in [(-7, 7), (7, 7), (-7, -7), (7, -7)]]}}


def _pedestal(B, size, h, top=0.3, mat="dark"):
    """tapered bunker pedestal for towers / radar"""
    pts = crect(size, size, size * 0.18)
    B.add(_bevel(g_loft([(top, pts), (top + h * 0.75, scale_pts(pts, 0.82)), (top + h, scale_pts(pts, 0.8))]), 0.08), mat)
    B.add(g_frame(scale_pts(pts, 0.82), scale_pts(pts, 0.6), top + h - 0.02, top + h + 0.15), "team")
    for k in range(4):
        a = 90 * k
        with B.at((0, 0, top), (0, 0, a)):
            B.box((size * 0.4, 0.12, h * 0.22), (0, -size * 0.43, h * 0.25), "trim", bev=0.02, rot=(-8, 0, 0))
            B.light((0, -size * 0.44, h * 0.55), (-12, 0, 0), size=0.22)


@asset("radar", "building", footprint=[12, 12])
def build_radar(coll):
    B = PB("radar", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 12, 12)
    top = 0.3
    # operations block (rear) + pedestal tower (front)
    B.box((8.0, 4.0, 3.0), (0, 2.6, top + 1.5), "dark", bev=0.1)
    B.plate((7.6, 3.6, 0.08), (0, 2.6, top + 3.04), top="team", inset=0.12)
    _window_band(B, -3.4, 3.4, 0.58, top + 2.1, h=0.45, n=6)
    B.vent(2.0, 1.0, (2.5, 4.62, top + 1.4), (0, 0, 180), n=4, frame="trim", slat="dark")
    B.greebles(4.0, 1.4, (-1.5, 3.0, top + 3.12), n=6, seed=61, hmax=0.4, smax=0.6)
    B.add(_bevel(g_loft([(top, crect(4.0, 4.0, 0.8, 0, -1.2)), (top + 4.5, crect(2.6, 2.6, 0.5, 0, -1.2)), (top + 5.0, crect(2.6, 2.6, 0.5, 0, -1.2))]), 0.06), "dark")
    B.add(g_frame(crect(2.7, 2.7, 0.5, 0, -1.2), crect(2.0, 2.0, 0.3, 0, -1.2), top + 4.95, top + 5.1), "team")
    B.cyl(0.9, 0.5, (0, -1.2, top + 5.3), "trim", seg=20, bev=0.04)
    for sx in (-1, 1):
        B.box((0.15, 2.0, 0.15), (sx * 1.6, -1.2, top + 2.0), "trim", bev=0.0)
        B.hazard(1.6, 0.25, (sx * 1.9, -1.2, top + 0.6), (90, 0, sx * 90), n=4)
    _mast(B, (4.4, -4.0, top), 6.0, w=0.6)
    B.pipe([(0, 0.6, top + 2.5), (0, -0.2, top + 2.5)], 0.18, "trim", joints=False)
    ob = B.finish(coll)
    # dish (yaw) on top of the pedestal
    D = PB("radar_dish", ["team", "dark", "trim", "glow"])
    px, py, pz = 0.0, -1.2, top + 5.55
    D.cyl(0.75, 0.3, (px, py, pz + 0.15), "dark", seg=20, bev=0.04)
    for sx in (-1, 1):
        D.add(g_prism([(-0.5, 0), (0.5, 0), (0.3, 1.4), (-0.3, 1.4)], 0.25, bev=0.03), "dark", (px + sx * 1.0, py, pz + 0.25))
        D.cyl(0.25, 0.35, (px + sx * 1.0, py, pz + 1.55), "trim", (0, 90, 0), seg=12)
    D.box((2.3, 0.5, 0.3), (px, py, pz + 0.35), "trim", bev=0.04)
    _dish(D, (px, py - 0.2, pz + 1.9), 3.0, (-60, 0, 0), mat="trim", back="dark")
    with D.at((px, py - 0.2, pz + 1.9), (-60, 0, 0)):
        D.add(g_frame(ngon(3.06, 24), ngon(2.8, 24), 1.04, 1.16), "team")
    D.box((0.6, 0.4, 0.5), (px, py + 0.9, pz + 1.0), "dark", bev=0.05)
    D.box((0.4, 0.04, 0.1), (px, py + 1.11, pz + 1.0), "glow", bev=0.0)
    dish = D.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "radar", "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "dish", "obj": dish, "team": True, "file": "radar_dish", "pivot": (px, py, pz), "axis": "yaw"}]}


@asset("rocket_tower", "building", footprint=[8, 8])
def build_rocket_tower(coll):
    B = PB("rocket_tower", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 8, 8, stripes=False)
    top = 0.3
    _pedestal(B, 6.2, 3.2, top)
    B.cyl(1.6, 0.3, (0, 0, top + 3.3), "trim", seg=20, bev=0.04)
    ob = B.finish(coll)
    H = PB("rocket_tower_head", ["team", "dark", "trim", "glow"])
    pz = top + 3.45
    H.cyl(1.3, 0.4, (0, 0, pz + 0.2), "dark", seg=20, bev=0.05)
    H.add(_bevel(g_frustum(1.8, 2.0, 1.4, 1.6, 0.9), 0.06), "dark", (0, 0.2, pz + 0.4))
    H.add(_bevel(g_frustum(1.2, 1.4, 1.0, 1.2, 0.08), 0.02), "team", (0, 0.2, pz + 1.28))
    H.box((0.9, 0.12, 0.25), (0, -0.62, pz + 0.95), "trim", bev=0.02)
    H.box((0.6, 0.05, 0.12), (0, -0.69, pz + 0.95), "glow", bev=0.0)
    muzzles = []
    for sx in (-1, 1):
        cx = sx * 1.45
        H.beam((sx * 0.8, 0.2, pz + 0.85), (cx, 0.2, pz + 0.95), 0.4, 0.4, "trim", bev=0.03)
        with H.at((cx, 0.1, pz + 1.0), (8, 0, 0)):
            H.box((1.0, 2.0, 0.95), (0, 0, 0), "dark", bev=0.07)
            H.plate((0.9, 1.8, 0.05), (0, 0.05, 0.48), top="team", inset=0.06)
            for i in range(2):
                for j in range(3):
                    lx, lz = -0.25 + i * 0.5, -0.3 + j * 0.3
                    H.add(g_tube(0.12, 0.09, 0.12, 10), "trim", (lx, -1.0, lz), (90, 0, 0))
                    H.cyl(0.09, 0.02, (lx, -0.97, lz), "glow", (90, 0, 0), seg=10)
            H.hazard(1.6, 0.18, (sx * 0.51, 0.1, -0.2), (90, 0, sx * 90), n=5)
        for i in range(2):
            for j in range(3):
                lx, lz = -0.25 + i * 0.5, -0.3 + j * 0.3
                m = M((cx, 0.1, pz + 1.0), (8, 0, 0)) @ Vector((lx, -1.1, lz))
                muzzles.append(tuple(m))
    H.antenna((0.5, 0.9, pz + 1.3), 1.0, r=0.03)
    head = H.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "rocket_tower", "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "head", "obj": head, "team": True, "file": "rocket_tower_head", "pivot": (0, 0, pz), "axis": "yaw"}],
            "muzzles": [{"part": "head", "pos": m} for m in muzzles]}


@asset("laser_tower", "building", footprint=[8, 8])
def build_laser_tower(coll):
    B = PB("laser_tower", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 8, 8, stripes=False)
    top = 0.3
    _pedestal(B, 6.0, 3.6, top)
    B.cyl(1.4, 0.3, (0, 0, top + 3.7), "trim", seg=20, bev=0.04)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        B.add(g_lathe([(0, 0), (0.35, 0), (0.3, 1.4), (0, 1.6)], 6), "trim", (2.0 * math.cos(a), 2.0 * math.sin(a), top + 2.7))
        B.add(g_sphere(0.14, 8, 4), "glow", (2.0 * math.cos(a), 2.0 * math.sin(a), top + 4.35))
    ob = B.finish(coll)
    H = PB("laser_tower_head", ["team", "dark", "trim", "crystal"])
    H.alias = {"glow": "crystal"}
    pz = top + 3.85
    H.cyl(1.1, 0.4, (0, 0, pz + 0.2), "dark", seg=20, bev=0.05)
    # yoke + emitter barrel with crystal lens
    for sx in (-1, 1):
        H.add(g_prism([(-0.6, 0), (0.6, 0), (0.35, 1.4), (-0.35, 1.4)], 0.3, bev=0.04), "dark", (sx * 0.95, 0, pz + 0.4))
        H.add(_bevel(g_prism([(-0.3, 1.38), (0.3, 1.38), (0.28, 1.45), (-0.28, 1.45)], 0.3), 0.01), "team", (sx * 0.95, 0, pz + 0.4))
    ez = pz + 1.4
    with H.at((0, 0, ez), (90, 0, 0)):        # local +Z -> world -Y (front)
        H.add(g_lathe([(0, -1.2), (0.5, -1.2), (0.62, -0.8), (0.62, 0.4), (0.45, 0.9), (0.45, 1.6), (0.55, 1.75), (0.55, 1.95), (0, 1.95)], 16), "dark")
        for k in range(4):
            H.add(g_torus(0.5, 0.07, 16, 6), "glow", (0, 0, 0.95 + k * 0.17))
        H.add(g_cyl(0.66, 0.15, 16), "trim", (0, 0, -0.4))
        H.add(g_cyl(0.66, 0.15, 16), "team", (0, 0, 0.1))
        # crystal lens: faceted gem in a claw mount
        H.add(g_lathe([(0, 1.95), (0.32, 2.05), (0.38, 2.25), (0.2, 2.5), (0, 2.6)], 6), "glow")
        for k in range(3):
            with H.at((0, 0, 2.0), (0, 0, 120 * k)):
                H.beam((0.5, 0, -0.05), (0.32, 0, 0.45), 0.1, 0.1, "trim", bev=0.0)
    H.cyl(0.2, 2.2, (0, 0, ez), "trim", (0, 90, 0), seg=12)
    H.box((0.8, 0.8, 0.5), (0, 0.9, ez + 0.1), "dark", bev=0.05)
    H.vent(0.6, 0.3, (0, 1.31, ez + 0.1), (0, 0, 180), n=3, frame="trim", slat="dark", depth=0.04)
    head = H.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "laser_tower", "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "head", "obj": head, "team": True, "file": "laser_tower_head", "pivot": (0, 0, pz), "axis": "yaw"}],
            "muzzles": [{"part": "head", "pos": (0, -2.65, ez)}]}


@asset("wall", "building", footprint=[4, 4])
def build_wall(coll):
    """4x4 block, 4.5 m high, flush on all four sides so it tiles in X and Z."""
    B = PB("wall", ["team", "dark", "trim", "glow"])
    s = 2.0
    B.add(g_loft([(-1.5, rect(4.0, 4.0)), (4.1, rect(4.0, 4.0))]), "dark")
    # parapet: walkway recessed, raised rims along the edges, team cap
    B.add(g_frame(rect(4.0, 4.0), rect(3.2, 3.2), 4.1, 4.5), "dark")
    B.add(g_frame(rect(3.9, 3.9), rect(3.3, 3.3), 4.49, 4.56), "team")
    B.add(g_poly(rect(3.2, 3.2), 4.05, 4.15), "trim")
    for k in range(4):
        B.box((3.1, 0.08, 0.05), (0, -1.2 + k * 0.8, 4.17), "dark", bev=0.0)
    # corner posts on the parapet (doubled up when tiled - reads like merlons)
    for cx in (-1, 1):
        for cy in (-1, 1):
            B.add(_bevel(g_frustum(0.55, 0.55, 0.42, 0.42, 0.45), 0.04), "dark", (cx * 1.72, cy * 1.72, 4.5))
            B.add(_bevel(g_frustum(0.4, 0.4, 0.32, 0.32, 0.05), 0.01), "team", (cx * 1.72, cy * 1.72, 4.94))
    # side faces: inset armour panels (inside the edge) + bolts + slit light
    for k in range(4):
        with B.at((0, 0, 0), (0, 0, 90 * k)):
            B.box((3.2, 0.12, 2.8), (0, -s - 0.04, 1.75), "dark", bev=0.05)
            B.box((3.0, 0.06, 0.18), (0, -s - 0.1, 3.35), "trim", bev=0.01)
            B.box((3.0, 0.06, 0.18), (0, -s - 0.1, 0.2), "trim", bev=0.01)
            B.bolts((-1.4, -s - 0.11, 2.95), (1.4, -s - 0.11, 2.95), 6, r=0.05, axis_rot=(90, 0, 0))
            B.box((0.8, 0.05, 0.1), (0, -s - 0.11, 3.75), "glow", bev=0.0)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "wall", "pivot": (0, 0, 0), "axis": "none"}]}


@asset("watchtower", "building", footprint=[8, 8])
def build_watchtower(coll):
    B = PB("watchtower", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 8, 8, stripes=False)
    top = 0.3
    ph = 9.6
    # four splayed legs with bracing
    for cx in (-1, 1):
        for cy in (-1, 1):
            B.beam((cx * 2.7, cy * 2.7, top), (cx * 1.25, cy * 1.25, top + ph), 0.42, 0.42, "dark", bev=0.05)
            B.box((1.0, 1.0, 0.5), (cx * 2.7, cy * 2.7, top + 0.25), "trim", bev=0.05)
    for lvl in range(3):
        z0 = top + 0.8 + lvl * 3.0
        z1 = z0 + 3.0
        f0 = 2.7 - (2.7 - 1.25) * (z0 - top) / ph
        f1 = 2.7 - (2.7 - 1.25) * (z1 - top) / ph
        for k in range(4):
            a = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            p, q = a[k], a[(k + 1) % 4]
            B.rod((p[0] * f0, p[1] * f0, z0), (q[0] * f1, q[1] * f1, z1), 0.06, "trim", 6)
            B.rod((q[0] * f0, q[1] * f0, z0), (p[0] * f1, p[1] * f1, z1), 0.06, "trim", 6)
            B.rod((p[0] * f1, p[1] * f1, z1), (q[0] * f1, q[1] * f1, z1), 0.07, "dark", 6)
    # central lift shaft + ladder
    B.box((1.0, 1.0, ph), (0, 0, top + ph / 2), "dark", bev=0.05)
    for k in range(int(ph / 0.5)):
        B.box((0.5, 0.05, 0.05), (0, -0.55, top + 0.3 + k * 0.5), "trim", bev=0.0)
    # platform with railings + team deck
    pz = top + ph
    plat = crect(4.0, 4.0, 0.6)
    B.add(_bevel(g_loft([(pz - 0.6, scale_pts(plat, 0.75)), (pz - 0.1, plat), (pz + 0.15, plat)]), 0.04), "dark")
    B.add(g_frame(scale_pts(plat, 1.01), scale_pts(plat, 0.86), pz + 0.13, pz + 0.2), "team")
    for i, (px, py) in enumerate(plat):
        B.rod((px * 0.97, py * 0.97, pz + 0.15), (px * 0.97, py * 0.97, pz + 1.0), 0.04, "trim", 4)
    for i in range(len(plat)):
        p, q = plat[i], plat[(i + 1) % len(plat)]
        B.rod((p[0] * 0.97, p[1] * 0.97, pz + 1.0), (q[0] * 0.97, q[1] * 0.97, pz + 1.0), 0.035, "trim", 4)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        B.light((1.9 * math.cos(a), 1.9 * math.sin(a), pz - 0.3), (0, 0, 90 * k), size=0.25)
    ob = B.finish(coll)
    # MG cupola (yaw)
    H = PB("watchtower_head", ["team", "dark", "trim", "glow"])
    hz = pz + 0.2
    H.cyl(1.0, 0.25, (0, 0, hz + 0.12), "trim", seg=20, bev=0.03)
    cup = crect(1.8, 1.8, 0.45)
    H.add(_bevel(g_loft([(hz + 0.25, cup), (hz + 1.2, scale_pts(cup, 1.05)), (hz + 1.7, scale_pts(cup, 0.8, dy=0.1))]), 0.05), "dark")
    H.add(_bevel(g_poly(scale_pts(cup, 0.62, dy=0.12), hz + 1.68, hz + 1.78), 0.02), "team")
    with H.at((0, -0.9, hz + 1.1), (-10, 0, 0)):
        H.box((1.3, 0.06, 0.18), (0, 0, 0), "glow", bev=0.0)
    # twin MG
    gz = hz + 0.8
    H.box((0.7, 0.6, 0.5), (0, -1.0, gz), "dark", bev=0.06)
    for sx in (-1, 1):
        H.cyl(0.07, 1.1, (sx * 0.18, -1.75, gz), "trim", (90, 0, 0), seg=8)
        H.cyl(0.1, 0.25, (sx * 0.18, -1.45, gz), "dark", (90, 0, 0), seg=8)
        H.cyl(0.09, 0.12, (sx * 0.18, -2.3, gz), "dark", (90, 0, 0), seg=8)
    H.box((0.25, 0.35, 0.3), (0.5, -0.95, gz - 0.1), "trim", bev=0.03)
    H.add(g_cyl(0.25, 0.2, 12), "dark", (0.0, 0.5, hz + 1.85))
    H.light((0, 0.5, hz + 2.1), (0, 0, 0), size=0.25)
    H.antenna((-0.6, 0.6, hz + 1.7), 1.2, r=0.025)
    head = H.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "watchtower", "pivot": (0, 0, 0), "axis": "none"},
                      {"name": "head", "obj": head, "team": True, "file": "watchtower_head", "pivot": (0, 0, hz), "axis": "yaw"}],
            "muzzles": [{"part": "head", "pos": (sx * 0.18, -2.38, gz)} for sx in (-1, 1)]}


@asset("lab", "building", footprint=[20, 20])
def build_lab(coll):
    B = PB("lab", ["team", "dark", "trim", "glow"])
    w, d = _foundation(B, 20, 20)
    top = 0.3
    # octagonal drum + big dome with glowing rings
    drum = ngon(7.0, 16, 11.25, 0, 0.6)
    B.add(_bevel(g_loft([(top, scale_pts(drum, 1.05, dy=-0.03)), (top + 2.8, drum), (top + 3.2, scale_pts(drum, 0.97, dy=0.02))]), 0.06), "dark")
    B.add(g_frame(scale_pts(drum, 1.0), scale_pts(drum, 0.9, dy=0.06), top + 3.15, top + 3.4), "team")
    for k in range(16):
        a = math.radians(11.25 + 22.5 * k)
        B.box((0.5, 0.5, 3.0), (7.05 * math.cos(a), 0.6 + 7.05 * math.sin(a), top + 1.5), "trim", bev=0.05, rot=(0, 0, math.degrees(a)))
        if k % 2 == 0:
            with B.at((6.9 * math.cos(a + math.pi / 16), 0.6 + 6.9 * math.sin(a + math.pi / 16), top + 2.2), (0, 0, math.degrees(a + math.pi / 16) + 90)):
                B.box((1.2, 0.08, 0.5), (0, 0, 0), "glow", bev=0.0)
    dome_r = 6.1
    B.add(g_dome(dome_r, 32, 10, 5.0), "dark", (0, 0.6, top + 3.3))
    for k, el in enumerate((18, 38, 58)):
        e = math.radians(el)
        rr = dome_r * math.cos(e)
        zz = top + 3.3 + 5.0 * math.sin(e)
        B.add(g_torus(rr + 0.05, 0.13, 32, 6), "glow", (0, 0.6, zz))
        B.add(g_torus(rr + 0.02, 0.2, 32, 6), "trim", (0, 0.6, zz - 0.3))
    # dome ribs + team crown
    for k in range(8):
        a = 2 * math.pi * k / 8
        prev = None
        for i in range(9):
            e = math.radians(5 + 80 * i / 8)
            p = Vector((dome_r * math.cos(e) * math.cos(a) * 1.01, 0.6 + dome_r * math.cos(e) * math.sin(a) * 1.01, top + 3.3 + 5.0 * math.sin(e) * 1.01))
            if prev is not None:
                B.beam(prev, p, 0.18, 0.12, "trim", bev=0.0)
            prev = p
    B.add(g_lathe([(0, top + 8.0), (1.8, top + 8.0), (1.8, top + 8.35), (1.2, top + 8.6), (0, top + 8.65)], 20), "team", (0, 0.6, 0))
    # antenna spire
    B.add(g_lathe([(0, top + 8.6), (0.5, top + 8.6), (0.15, top + 12.0), (0.05, top + 13.5), (0, top + 13.6)], 8), "trim", (0, 0.6, 0))
    for k in range(3):
        B.add(g_torus(0.5 - k * 0.12, 0.05, 12, 4), "glow", (0, 0.6, top + 9.5 + k * 1.0))
    B.add(g_sphere(0.18, 8, 5), "glow", (0, 0.6, top + 13.7))
    # entrance (front) + wings
    B.box((3.6, 2.0, 3.0), (0, -6.9, top + 1.5), "dark", bev=0.08)
    B.plate((3.2, 1.8, 0.08), (0, -6.9, top + 3.04), top="team", inset=0.1)
    B.box((2.4, 0.12, 2.2), (0, -7.92, top + 1.1), "trim", bev=0.02)
    B.box((2.0, 0.08, 1.8), (0, -7.98, top + 1.0), "glow", bev=0.0)
    for sx in (-1, 1):
        B.box((3.0, 5.0, 2.4), (sx * 7.4, 4.8, top + 1.2), "dark", bev=0.08)
        B.plate((2.6, 4.6, 0.08), (sx * 7.4, 4.8, top + 2.44), top="team", inset=0.1)
        _dish(B, (sx * 7.4, 5.6, top + 3.2), 1.0, (40, 0, sx * 30 + 180))
        tank_at(B, (sx * 7.6, -6.6, top), 0.9, 1.8, glow="glow", glow_dir=-90)
    ob = B.finish(coll)
    return {"parts": [{"name": "main", "obj": ob, "team": True, "file": "lab", "pivot": (0, 0, 0), "axis": "none"}]}


# ------------------------------------------------------------------ debris / projectiles


@asset("bot_debris", "prop")
def build_bot_debris(coll):
    P = PB("bot_debris", ["dark", "trim", "black", "ember"])
    rnd = random.Random(77)
    # oil puddle
    P.add(g_poly(ngon(0.75, 14, 0, 0.1, 0.1, 1.2, 0.9), 0.0, 0.012), "black")
    # broken torso shell lying on its back
    with P.at((-0.15, 0.1, 0.22), (0, 70, 25)):
        P.add(_bevel(g_loft([(-0.2, crect(0.45, 0.34, 0.07)), (0.15, crect(0.62, 0.44, 0.1)), (0.32, crect(0.55, 0.4, 0.1))]), 0.02), "dark")
        P.box((0.3, 0.05, 0.08), (0, -0.23, 0.12), "ember", bev=0.0)
        P.box((0.04, 0.4, 0.3), (0.2, 0, 0.1), "ember", bev=0.0, rot=(0, 0, 20))
    # head with a dead visor
    with P.at((0.55, -0.45, 0.13), (15, -20, 60)):
        P.add(_bevel(g_loft([(-0.13, crect(0.25, 0.28, 0.04)), (0.0, crect(0.3, 0.34, 0.06)), (0.15, crect(0.25, 0.28, 0.06))]), 0.015), "dark")
        P.box((0.2, 0.05, 0.05), (0, -0.17, 0.02), "black", bev=0.0)
        P.box((0.06, 0.05, 0.03), (0.05, -0.18, 0.02), "ember", bev=0.0)
    # arm segment + hand
    P.beam((-0.8, -0.5, 0.08), (-0.35, -0.75, 0.1), 0.13, 0.15, "dark", bev=0.03)
    P.add(g_sphere(0.08, 8, 6), "trim", (-0.8, -0.5, 0.08))
    P.box((0.12, 0.12, 0.11), (-0.3, -0.78, 0.07), "trim", bev=0.02)
    # leg piece with knee joint
    P.beam((0.3, 0.55, 0.12), (0.85, 0.3, 0.1), 0.2, 0.22, "dark", bev=0.04)
    P.cyl(0.1, 0.24, (0.3, 0.55, 0.12), "trim", (0, 90, 25), seg=10)
    P.rod((0.35, 0.65, 0.12), (0.8, 0.45, 0.06), 0.03, "trim", 6)
    # foot
    P.add(g_prism([(-0.25, 0.0), (0.22, 0.0), (0.22, 0.08), (0.05, 0.13), (-0.25, 0.1)], 0.22, bev=0.02), "dark", (-0.75, 0.55, 0.0), (0, 0, 40))
    # armour plates and scrap
    for i in range(10):
        sx, sy = rnd.uniform(0.08, 0.3), rnd.uniform(0.06, 0.25)
        x, y = rnd.uniform(-0.95, 0.95), rnd.uniform(-0.95, 0.95)
        P.box((sx, sy, 0.03), (x, y, 0.03), rnd.choice(["dark", "trim", "dark"]), bev=0.005, rot=(rnd.uniform(-20, 20), rnd.uniform(-20, 20), rnd.uniform(0, 180)))
    for i in range(4):
        x, y = rnd.uniform(-0.8, 0.8), rnd.uniform(-0.8, 0.8)
        P.add(g_cyl(0.025, 0.25, 6), "trim", (x, y, 0.03), (90, 0, rnd.uniform(0, 180)))
    # smouldering embers
    for i in range(5):
        P.add(g_sphere(0.03, 6, 4), "ember", (rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), 0.02))
    return {"parts": [{"name": "main", "obj": P.finish(coll), "team": False, "file": "bot_debris"}]}


@asset("shell", "prop")
def build_shell(coll):
    P = PB("shell", ["trim", "dark", "orange"])
    L = 0.6
    with P.at((0, 0, 0), (90, 0, 0)):      # local +Z -> world -Y (flight direction, engine +Z)
        P.add(g_lathe([(0, -L / 2), (0.075, -L / 2), (0.085, -L / 2 + 0.03), (0.085, 0.02), (0.07, 0.12), (0.035, 0.24), (0, L / 2)], 12), "orange")
        P.add(g_cyl(0.09, 0.05, 12), "trim", (0, 0, -0.04))
        P.add(g_cyl(0.088, 0.03, 12), "dark", (0, 0, -0.2))
    return {"parts": [{"name": "main", "obj": P.finish(coll), "team": False, "file": "shell"}]}


@asset("rocket", "prop")
def build_rocket(coll):
    P = PB("rocket", ["dark", "trim", "orange"])
    L = 1.2
    r = 0.08
    with P.at((0, 0, 0), (90, 0, 0)):      # nose towards world -Y (engine +Z)
        P.add(g_lathe([(0, -L / 2 + 0.06), (r * 0.8, -L / 2 + 0.06), (r, -L / 2 + 0.12), (r, L / 2 - 0.3), (r * 0.6, L / 2 - 0.1), (0, L / 2)], 12), "dark")
        P.add(g_cyl(r * 1.04, 0.05, 12), "trim", (0, 0, L / 2 - 0.32))
        P.add(g_cyl(r * 1.04, 0.04, 12), "trim", (0, 0, 0.0))
        P.add(g_lathe([(0, -L / 2 - 0.02), (r * 0.75, -L / 2 - 0.02), (r * 0.8, -L / 2 + 0.07), (0, -L / 2 + 0.07)], 12), "trim")
        P.add(g_cyl(r * 0.55, 0.03, 12), "orange", (0, 0, -L / 2 - 0.025))
        P.add(g_cyl(r * 0.45, 0.18, 10, r2=0.0), "orange", (0, 0, -L / 2 - 0.12), (180, 0, 0))
        for k in range(4):
            with P.at((0, 0, -L / 2 + 0.2), (0, 0, 45 + 90 * k)):
                P.add(g_box(0.11, 0.014, 0.22, bev=0.0), "trim", (r + 0.05, 0, 0))
    return {"parts": [{"name": "main", "obj": P.finish(coll), "team": False, "file": "rocket"}]}


def render_icons(keys=None):
    """icons/<key>.png for every unit and building + icons/contact_sheet.png"""
    keys = keys or [k for k, v in ASSETS.items() if v["kind"] in ("unit", "building")]
    paths = []
    for k in keys:
        if bpy.data.collections.get("SW_" + k) is None or not bpy.data.collections["SW_" + k].objects:
            build(k)
        paths.append(render_icon(k))
    sheet(paths, os.path.join(ICONS, "contact_sheet.png"), 6, bg=(0.11, 0.12, 0.13))
    return paths
