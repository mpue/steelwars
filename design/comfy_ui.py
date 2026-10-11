"""STEELWARS UI art on the local ComfyUI (Krea2 turbo GGUF).

Stage "gen": one graph, one branch per (asset, seed) -> design/ui_raw/<name>_<k>.png
The picked raw images are cut into the game's UI pieces by ui_cut.py.
"""
import json, sys, time, uuid, shutil, urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8188"
COMFY = Path(r"D:\ComfyUI_windows_portable\ComfyUI")
HERE = Path(__file__).parent
RAW = HERE / "ui_raw"
RAW.mkdir(exist_ok=True)

ISO = (" Isolated on a pure black background, centered, front orthographic view, high detail 3D render, "
       "no text, no letters, no numbers, no logos.")
ART = {
    "frame": ("Game user interface asset: an empty rectangular sci-fi HUD window frame. Dark gunmetal armored "
              "bezel with angled chamfered corners, thin glowing amber orange light strips along the edges, "
              "small bolts and panel seams. The inside of the frame is an empty flat dark charcoal glass surface." + ISO,
              (1024, 1024)),
    "slot": ("Game user interface asset: one square sci-fi inventory slot tile. Thick beveled dark steel frame "
             "with glowing amber orange corner brackets and a thin cyan inner line, the centre is an empty dark "
             "recessed screen." + ISO, (768, 768)),
    "button": ("Game user interface asset: one wide empty sci-fi command button. A long horizontal armored dark "
               "gunmetal plate with chamfered corners, a glowing amber orange edge light, small angled notches on "
               "both ends, the face is empty dark brushed metal." + ISO, (1536, 512)),
    "side": ("Game user interface texture: a tall vertical sci-fi command console side panel filling the entire "
             "frame. Dark brushed gunmetal armor plates with engraved panel lines, hexagonal vent grilles, small "
             "amber warning stripes, tiny cyan indicator lights, rivets. Flat even lighting, front orthographic "
             "view, no screens, no text, no letters.", (576, 1408)),
    "bar": ("Game user interface texture: a long horizontal sci-fi header bar filling the entire frame. Dark "
            "gunmetal armor plate with engraved panel lines and rivets, a thin glowing amber orange light strip "
            "along the bottom edge, small hexagonal vents. Flat even lighting, front orthographic view, no text, "
            "no letters.", (1792, 160)),
    "logo": ("A bold metallic video game title logo reading \"STEELWARS\" in one line. Heavy angular futuristic "
             "military letters in scratched brushed steel with glowing orange molten edges and a dark bevel. "
             "Isolated on a pure black background, centered, front view.", (1792, 512)),
}


def submit(graph):
    body = json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL + "/prompt", body,
                                                                {"Content-Type": "application/json"})))
    pid = r["prompt_id"]
    while True:
        time.sleep(3)
        h = json.load(urllib.request.urlopen(f"{URL}/history/{pid}"))
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise SystemExit(json.dumps(st, indent=1)[:3000])
            return h[pid]["outputs"]


def gen(names, seeds, seed0, extra=""):
    g = {
        "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "krea2_turbo_bf16-Q4_0.gguf"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3-vl-4b-heretic_fp8_e4m3fn.safetensors",
                                                        "type": "krea2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "Qwen_Image-VAE.safetensors"}},
    }
    keys = []
    for n in names:
        text, (w, h) = ART[n]
        g[f"{n}_t"] = {"class_type": "CLIPTextEncode", "inputs": {"text": text + extra, "clip": ["clip", 0]}}
        g[f"{n}_n"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": [f"{n}_t", 0]}}
        g[f"{n}_lat"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        for k in range(seeds):
            key = f"{n}_{k}"
            g[f"{key}_k"] = {"class_type": "KSampler", "inputs": {
                "seed": seed0 + k * 101 + len(n) * 7, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                "scheduler": "simple", "denoise": 1.0, "model": ["unet", 0], "positive": [f"{n}_t", 0],
                "negative": [f"{n}_n", 0], "latent_image": [f"{n}_lat", 0]}}
            g[f"{key}_d"] = {"class_type": "VAEDecode", "inputs": {"samples": [f"{key}_k", 0], "vae": ["vae", 0]}}
            g[f"{key}_s"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"steelwars_ui/{key}",
                                                                  "images": [f"{key}_d", 0]}}
            keys.append(key)
    out = submit(g)
    for key in keys:
        img = out[f"{key}_s"]["images"][0]
        shutil.copy(COMFY / "output" / img.get("subfolder", "") / img["filename"], RAW / f"{key}.png")
        print("raw", key, flush=True)


if __name__ == "__main__":
    names = sys.argv[1].split(",") if len(sys.argv) > 1 else list(ART)
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 4242
    gen(names, seeds, seed0)
