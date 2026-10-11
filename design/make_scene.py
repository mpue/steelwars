"""Build the Steelwars battlefield scene "grenzland.fitzel".

The world comes from the engine's generators -- this only writes what they read:
terrain and ecology settings (taken from the scaper landscape, which is tuned),
a village from the town generator (towncheck --scene) in the middle of the map,
a dusk-and-smoke look, the markers the game reads (SW Map / SW Start / SW
Field), the particle emitters for the effects (FX ...), and the Empty that runs
steelwars.lua.

    python design/make_scene.py [--town <fragment.json>]
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = r"D:\fitzel_projects\scaper\scaper.fitzel"
OUT = os.path.join(ROOT, "grenzland.fitzel")

MAP_C = (0.0, 0.0)
MAP = 1024.0


def entity(eid, name, typ, center=(0, 0, 0), half=(0.5, 0.5, 0.5), comps=None, parent=-1, active=True, rot=(0, 0, 0)):
    return {"active": active, "center": list(center), "components": comps or [], "half": list(half),
            "id": eid, "name": name, "parent": parent, "rotation": list(rot), "type": typ}


def particles(**kw):
    p = {"alphaEnd": 0.0, "alphaStart": 1.0, "blend": 1, "boxSize": [1.0, 1.0, 1.0], "brightness": 1.0,
         "burst": 20.0, "colorEnd": [1.0, 0.25, 0.05], "colorStart": [1.0, 0.85, 0.5], "coneAngle": 25.0,
         "drag": 0.4, "duration": 0.1, "gravity": [0.0, -3.0, 0.0], "inherit": 0.0, "lifeVar": 0.3,
         "lifetime": 1.0, "loop": False, "maxCount": 400.0, "playing": True, "radius": 0.5, "rate": 0.0,
         "rotation": 180.0, "shape": 1, "sizeEnd": 1.2, "sizeStart": 0.4, "sizeVar": 0.25, "speed": 4.0,
         "speedGlowMax": 1.0, "speedGlowMin": 1.0, "speedVar": 1.0, "spin": 20.0, "sprite": "",
         "stretch": 0.0, "type": "particles", "wind": [0.0, 0.0, 0.0], "worldSpace": True}
    p.update(kw)
    return p


# The effects. Bursts are fired by the script with game.emit; FX Fire / FX Smoke
# are looping emitters the script moves onto whatever burns.
FX = {
    "FX Explosion": particles(burst=70, lifetime=0.9, lifeVar=0.4, speed=9, speedVar=5, sizeStart=1.6, sizeEnd=5.5,
                              colorStart=[1.0, 0.75, 0.35], colorEnd=[0.9, 0.2, 0.03], gravity=[0, 2.0, 0], drag=2.5,
                              brightness=4.0, sprite="shmup_fire.png", radius=1.2, maxCount=900),
    "FX Fireball": particles(burst=24, lifetime=1.3, speed=3, speedVar=2, sizeStart=2.5, sizeEnd=7.0,
                             colorStart=[1.0, 0.55, 0.2], colorEnd=[0.4, 0.08, 0.02], gravity=[0, 3.0, 0], drag=1.5,
                             brightness=3.0, sprite="shmup_fire.png", radius=1.0, maxCount=500),
    "FX Smoke Puff": particles(blend=0, burst=22, lifetime=4.0, lifeVar=0.4, speed=2.2, speedVar=1.2, sizeStart=1.8,
                               sizeEnd=7.5, colorStart=[0.035, 0.032, 0.03], colorEnd=[0.09, 0.088, 0.085], alphaStart=0.8,
                               gravity=[0, 1.6, 0], drag=0.9, sprite="shmup_smoke.png", wind=[1.5, 0, 0.6], maxCount=800),
    "FX Sparks": particles(burst=45, lifetime=0.7, lifeVar=0.5, speed=16, speedVar=8, sizeStart=0.12, sizeEnd=0.04,
                           colorStart=[1.0, 0.85, 0.5], colorEnd=[1.0, 0.4, 0.1], gravity=[0, -14, 0], drag=0.6,
                           brightness=5.0, stretch=0.06, radius=0.3, maxCount=1500),
    "FX Debris": particles(blend=0, burst=30, lifetime=1.8, speed=12, speedVar=6, sizeStart=0.45, sizeEnd=0.35,
                           colorStart=[0.06, 0.06, 0.06], colorEnd=[0.05, 0.05, 0.05], alphaStart=1.0, alphaEnd=0.8,
                           gravity=[0, -18, 0], drag=0.3, spin=360, shape=2, coneAngle=60, maxCount=600),
    "FX Oil": particles(blend=0, burst=40, lifetime=1.2, speed=7, speedVar=4, sizeStart=0.25, sizeEnd=0.12,
                        colorStart=[0.02, 0.02, 0.025], colorEnd=[0.01, 0.01, 0.012], alphaStart=1.0, alphaEnd=0.6,
                        gravity=[0, -16, 0], drag=0.2, shape=2, coneAngle=55, maxCount=600),
    "FX Muzzle": particles(burst=8, lifetime=0.09, lifeVar=0.2, speed=2, sizeStart=0.9, sizeEnd=0.2,
                           colorStart=[1.0, 0.8, 0.45], colorEnd=[1.0, 0.45, 0.1], gravity=[0, 0, 0], brightness=6.0,
                           sprite="shmup_fire.png", radius=0.1, maxCount=500),
    "FX Dust": particles(blend=0, burst=30, lifetime=2.6, speed=4, speedVar=2, sizeStart=1.5, sizeEnd=6.0,
                         colorStart=[0.12, 0.1, 0.08], colorEnd=[0.16, 0.14, 0.12], alphaStart=0.45,
                         gravity=[0, 0.4, 0], drag=1.6, sprite="shmup_puff.png", radius=2.0, maxCount=800),
    "FX Energicum": particles(burst=6, lifetime=0.8, speed=5, speedVar=3, sizeStart=0.18, sizeEnd=0.05,
                              colorStart=[0.4, 1.0, 0.7], colorEnd=[0.1, 1.0, 0.5], gravity=[0, -6, 0],
                              brightness=6.0, stretch=0.04, radius=0.6, maxCount=400),
    "FX Laser Hit": particles(burst=20, lifetime=0.35, speed=8, speedVar=4, sizeStart=0.5, sizeEnd=0.1,
                              colorStart=[0.6, 0.95, 1.0], colorEnd=[0.2, 0.6, 1.0], gravity=[0, -4, 0],
                              brightness=7.0, stretch=0.03, maxCount=500),
    "FX Plasma Hit": particles(burst=30, lifetime=0.6, speed=6, speedVar=3, sizeStart=1.8, sizeEnd=4.0,
                               colorStart=[0.5, 0.85, 1.0], colorEnd=[0.15, 0.3, 1.0], gravity=[0, 1, 0],
                               brightness=5.0, sprite="shmup_fire.png", maxCount=500),
    "FX Weld": particles(burst=10, lifetime=0.5, speed=6, speedVar=3, sizeStart=0.1, sizeEnd=0.03,
                         colorStart=[0.7, 0.9, 1.0], colorEnd=[1.0, 0.7, 0.3], gravity=[0, -12, 0],
                         brightness=6.0, stretch=0.04, maxCount=400),
}
LOOPS = {
    "FX Fire": particles(loop=True, rate=45, burst=0, duration=3.0, lifetime=1.1, speed=2.5, speedVar=1,
                         sizeStart=1.6, sizeEnd=0.4, colorStart=[1.0, 0.6, 0.2], colorEnd=[0.8, 0.15, 0.02],
                         gravity=[0, 5, 0], brightness=3.0, sprite="shmup_fire.png", radius=1.2, maxCount=200),
    "FX Smoke": particles(loop=True, blend=0, rate=14, burst=0, duration=3.0, lifetime=7.0, speed=2.5, speedVar=1,
                          sizeStart=2.0, sizeEnd=10.0, colorStart=[0.03, 0.028, 0.026], colorEnd=[0.08, 0.08, 0.08],
                          alphaStart=0.7, gravity=[0, 2.2, 0], drag=0.5, sprite="shmup_smoke.png",
                          wind=[2.0, 0, 0.8], radius=1.0, maxCount=200),
}


def main():
    town_path = None
    if "--town" in sys.argv:
        town_path = sys.argv[sys.argv.index("--town") + 1]
    base = json.load(open(BASE, encoding="utf-8"))
    s = copy.deepcopy(base["settings"])
    # heavy hand-made layers of scaper's own scene: not ours
    for k in ("paintedGrass", "paintedFlowers", "paintedTrees2", "terrainEdits", "terrainPaint", "camPath",
              "splines", "modelMaterialOverrides", "modelMaterialAssign", "anim", "animGraphs", "roads", "towns"):
        s.pop(k, None)
    s["paintedGrass"] = ""
    s["paintedFlowers"] = ""
    s["paintedTrees2"] = ""
    s["terrainEdits"] = ""
    s["terrainPaint"] = ""
    s["roads"] = []
    s["anim"] = {"clips": []}
    s["animGraphs"] = [{"entry": 0, "name": "Graph 1", "params": [], "states": [], "transitions": []}]
    s["modelMaterialOverrides"] = {}
    # the forest: the engine's own trees (scaper's live in its project)
    s["trees"] = [
        {"bbAspect": 0.99, "bbEnabled": True, "bbSize": 1.05, "bbStart": 60.0, "billboard": "billboard_tree_bled.png",
         "density": d, "enabled": True, "lods": [{"dist": 45.0, "model": m}], "materials": [], "name": n, "size": sz}
        for n, m, d, sz in (("Fichte", "tree1.glb", 1.4, 11.0), ("Kiefer", "tree2.glb", 1.0, 12.0),
                            ("Laub", "tree3.glb", 0.7, 9.0), ("Busch", "tree4.glb", 0.5, 3.0))]
    s["ecoForest"] = True
    s["ecoCover"] = 0.55          # open ground for bases, forests as walls between them
    s["ecoStandSize"] = 260.0
    s["ecoSolitary"] = 0.03
    s["forestRadius"] = 1600.0
    s["treeBrightness"] = 0.62
    s["treeContrast"] = 0.8
    s["treeHue"] = -4.0
    # life that does not belong on a battlefield of machines
    s["wildlife"] = False
    s["birdsEnabled"] = False
    s["fireflyEnabled"] = False
    s["herdCount"] = 0
    s["motes"] = True
    s["flowerEnabled"] = False
    # --- the look: late dusk under a heavy sky, smoke in the air ------------------
    s["timeOfDay"] = 17.7
    s["timeFlows"] = False
    s["weatherPreset"] = ""
    s["weather"] = 0.12
    s["coverage"] = 0.5
    s["cloudDensity"] = 1.0
    s["fogDensity"] = 0.0009
    s["fogFalloff"] = 0.018
    s["autoExposure"] = False
    s["exposure"] = 1.35
    s["contrast"] = 0.52
    s["saturation"] = 0.78
    s["warmth"] = 0.12
    s["vignette"] = 0.45
    s["bloom"] = 0.28
    s["filmGrain"] = 0.05
    s["grassTintR"], s["grassTintG"], s["grassTintB"] = 0.55, 0.62, 0.25
    s["grassDensity"] = 1.1
    s["grassRadius"] = 120.0
    s["meadowTint"] = 0.6
    s["motionBlur"] = 0.0
    s["dofBlur"] = 0.0
    s["showCrosshair"] = False
    s["soundscape"] = False
    s["startMode"] = 0
    s["editorCamera"] = {"pitch": -48.0, "x": MAP_C[0] - 260.0, "y": 220.0, "yaw": 45.0, "z": MAP_C[1] - 260.0}
    if town_path:
        frag = json.load(open(town_path, encoding="utf-8"))
        t = frag["towns"]["towns"][0]
        t["name"] = "Ruinen von Weissenfeld"
        t["weathering"] = 1.0
        t["windowLit"] = 0.06
        t["traffic"] = 0.0
        t["people"] = 0.0
        t["personPrefabs"] = []
        t["vehiclePrefabs"] = []
        t["lampPrefabs"] = []
        t["facadeColor"] = [0.42, 0.40, 0.38]
        t["roofColor"] = [0.22, 0.12, 0.10]
        t["colourVariety"] = 0.35
        t["collider"] = True
        frag["towns"]["range"] = 1600.0
        s["towns"] = frag["towns"]
        s["roads"] = frag["roads"]

    ents = []
    eid = 0

    def add(*a, **kw):
        nonlocal eid
        e = entity(eid, *a, **kw)
        ents.append(e)
        eid += 1
        return e

    sun = next(e for e in base["entities"] if e["name"] == "Sun")
    terrain = next(e for e in base["entities"] if e["name"] == "Terrain")
    sun = copy.deepcopy(sun)
    sun["id"] = eid
    sun["components"][0]["color"] = [1.0, 0.72, 0.48]
    sun["components"][0]["intensity"] = 0.85
    ents.append(sun)
    eid += 1
    terrain = copy.deepcopy(terrain)
    terrain["id"] = eid
    ents.append(terrain)
    eid += 1
    s["terrainEntity"] = True

    game = add("Steelwars", 7, (MAP_C[0], 0, MAP_C[1]),
               comps=[{"file": "steelwars.lua", "params": [], "type": "script"}])
    add("SW Map", 7, (MAP_C[0], 0, MAP_C[1]), half=(2, 2, 2))
    r = MAP * 0.37
    for dx, dz in ((-1, -1), (1, 1), (-1, 1), (1, -1)):
        add("SW Start", 7, (MAP_C[0] + dx * r, 0, MAP_C[1] + dz * r), half=(3, 3, 3))
    # Energicum: one field near each start, a rich one either side of the town
    import math
    for dx, dz in ((-1, -1), (1, 1), (-1, 1), (1, -1)):
        sx, sz = dx * r, dz * r
        # toward the centre, turned a little, 80 m out: close enough for one harvester
        a = math.atan2(-sx, -sz) + 0.6
        add("SW Field", 7, (MAP_C[0] + sx + math.sin(a) * 80, 0, MAP_C[1] + sz + math.cos(a) * 80), half=(1, 1, 1))
    add("SW Field", 7, (MAP_C[0] - 210, 0, MAP_C[1] + 10), half=(1.5, 1.5, 1.5))
    add("SW Field", 7, (MAP_C[0] + 210, 0, MAP_C[1] - 10), half=(1.5, 1.5, 1.5))
    for name, comp in FX.items():
        add(name, 7, (MAP_C[0], -200, MAP_C[1]), half=(0.1, 0.1, 0.1), comps=[comp])
    for name, comp in LOOPS.items():
        for k in range(12):
            add(name, 7, (MAP_C[0], -200, MAP_C[1]), half=(0.1, 0.1, 0.1), comps=[copy.deepcopy(comp)], active=False)

    scene = {"entities": ents, "settings": s, "version": base.get("version", 3)}
    if "app" in base:
        scene["app"] = base["app"]
    json.dump(scene, open(OUT, "w", encoding="utf-8"), indent=1)
    print("wrote", OUT, len(ents), "entities")


if __name__ == "__main__":
    main()
