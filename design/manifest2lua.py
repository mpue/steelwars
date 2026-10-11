"""models/manifest.json -> scripts/sw/manifest.lua

The game reads the model manifest as a Lua module (require "sw.manifest"), so it
works the same in the editor and in an exported game whose files sit in an
archive. Run after the Blender build changes the manifest:

    python design/manifest2lua.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lua(v, ind=0):
    pad = "    " * ind
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(round(v, 4)) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        if all(isinstance(x, (int, float)) for x in v):
            return "{ " + ", ".join(lua(x) for x in v) + " }"
        return "{\n" + "".join(pad + "    " + lua(x, ind + 1) + ",\n" for x in v) + pad + "}"
    if isinstance(v, dict):
        out = "{\n"
        for k, x in v.items():
            key = k if k.isidentifier() else '["%s"]' % k
            out += pad + "    " + key + " = " + lua(x, ind + 1) + ",\n"
        return out + pad + "}"
    return "nil"


def main():
    src = os.path.join(ROOT, "models", "manifest.json")
    dst = os.path.join(ROOT, "scripts", "sw", "manifest.lua")
    data = json.load(open(src, encoding="utf-8"))
    text = ("-- GENERATED from models/manifest.json by design/manifest2lua.py -- do not edit.\n"
            "return " + lua(data) + "\n")
    open(dst, "w", encoding="utf-8", newline="\n").write(text)
    n = sum(len(data.get(k, {})) for k in ("units", "buildings", "props", "effects"))
    print("wrote", dst, "with", n, "entries")


if __name__ == "__main__":
    main()
