"""CLEAN ROOM: authoring briefs for every texture slot.

    python -m cleanroom briefs pilotwings64 [out_dir]      (default work/briefs)

For each UVTX slot this writes, from the spec only:
  <id>/brief.json   hard constraints (size per region, format, alpha, tiling),
                    role, where it is used, label text, suggested prompt
  <id>/guide.png    the coarse colour layout at slot size (img2img / ControlNet
                    conditioning: composition and palette, no original detail)
  <id>/mask.png     the 2-bit alpha outline, when the slot has one
and index.jsonl with one line per slot. Artists or a local image model fill
games/pilotwings64/overrides/textures/<id>.png (any size; see generate.py
_override_region) and the next build picks them up.
"""
import json
import os
import sys

import numpy as np

from cleanroom.gfx import png, texfmt, gbi
from . import generate as G
from .texlayout import regions

WRAP = {0: "wrap", 1: "mirror", 2: "clamp", 3: "mirror+clamp"}
FMT = {texfmt.RGBA: "RGBA", texfmt.IA: "IA", texfmt.I: "I", 2: "CI", 3: "IA", 4: "I"}
NAMES = [((40, 110, 190), "blue water"), ((214, 196, 140), "sand"), ((128, 114, 100), "grey-brown rock"),
         ((236, 238, 244), "white"), ((78, 140, 62), "green grass"), ((30, 30, 30), "black"),
         ((200, 40, 40), "red"), ((240, 200, 40), "yellow"), ((110, 160, 230), "sky blue"),
         ((150, 150, 150), "grey"), ((120, 80, 40), "brown"), ((240, 150, 60), "orange")]


def colour_words(grid):
    g = np.asarray(grid, np.float32).reshape(-1, 4)
    g = g[g[:, 3] > 64][:, :3] if (g[:, 3] > 64).any() else g[:, :3]
    counts = {}
    for c in g:
        name = min(NAMES, key=lambda n: np.sum((np.array(n[0]) - c) ** 2))[1]
        counts[name] = counts.get(name, 0) + 1
    return [n for n, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]


def role_of(tid, ir, usage):
    if tid in G.tex_labels():
        return "hud-text"
    if tid in usage.terrain:
        return "terrain"
    if tid in usage.xlu:
        return "cutout"
    if tid in usage.model:
        return "model"
    return "ui"


PROMPTS = {
    "terrain": "seamless tileable top-down {colours} ground texture, painterly 1990s console style, soft detail",
    "model": "{colours} surface texture for a low-poly 3D model, clean 1990s console style",
    "cutout": "{colours} sprite with transparent background, clean silhouette, 1990s console style",
    "ui": "{colours} user-interface graphic, clean flat shading, 1990s console style",
    "hud-text": "(generated from tex_labels.json; no image needed)",
}


def brief(tid, ir, usage):
    tiles = {t["tile"]: t for t in gbi.render_tiles([bytes.fromhex(c) for c in ir["dlist"]])}
    role = role_of(tid, ir, usage)
    digests = {d["start"]: d for d in ir.get("digest") or []}
    regs = []
    for t, start, end, stride, tw, rows in regions(ir, ir["image_size"]):
        d = digests.get(start)
        full = tiles.get(t["tile"], {})
        regs.append({"tile": t["tile"], "width": d["vw"] if d else t["width"], "height": d["vh"] if d else t["height"],
                     "format": FMT.get(t["fmt"], str(t["fmt"])), "bits": texfmt.BITS[t["siz"]],
                     "alpha": bool(d and "alpha2" in d),
                     "wrap_s": WRAP.get(full.get("cms", 0)), "wrap_t": WRAP.get(full.get("cmt", 0))})
    first = (ir.get("digest") or [None])[0]
    colours = colour_words(first["grid"]) if first else []
    b = {"id": tid, "kind": "texture", "override": f"games/pilotwings64/overrides/textures/{tid:03x}.png",
         "role": role, "regions": regs, "colours": colours,
         "tileable": bool(regs) and regs[0]["wrap_s"] != "clamp" and regs[0]["wrap_t"] != "clamp",
         "prompt": PROMPTS[role].format(colours=", ".join(colours) or "neutral")}
    label = G.tex_labels().get(tid)
    if label:
        b["label"] = label["text"]
    return b, first


def main(argv):
    out = argv[1] if len(argv) > 1 else os.path.join("work", "briefs")
    spec = G.Spec()
    usage = G.Usage(spec)
    os.makedirs(out, exist_ok=True)
    n = 0
    with open(os.path.join(out, "index.jsonl"), "w") as idx:
        for tid, d in sorted(spec.by_tag("UVTX").items()):
            ir = G._comm(d)["ir"]
            b, first = brief(tid, ir, usage)
            sub = os.path.join(out, f"{tid:03x}")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, "brief.json"), "w") as f:
                json.dump(b, f, indent=1)
            if first:
                n_grid = int(round(len(first["grid"]) ** 0.5))
                vis = G._upsample_grid(first["grid"], n_grid, first["vw"], first["vh"])
                png.write(os.path.join(sub, "guide.png"), np.clip(vis, 0, 255).astype(np.uint8))
                if "alpha2" in first:
                    a = G._unpack_alpha2(first["alpha2"], first["w"], first["h"])[:first["vh"], :first["vw"]]
                    png.write(os.path.join(sub, "mask.png"), np.clip(a, 0, 255).astype(np.uint8)[..., None])
            idx.write(json.dumps(b) + "\n")
            n += 1
        for bid, d in sorted(spec.by_tag("UVBT").items()):
            ir = G._comm(d)["ir"]
            if "grid8" not in ir:
                continue
            label = G.hud_labels().get(bid)
            b = {"id": bid, "kind": "blit", "role": "ui-panel" if label and label["style"] == "panel"
                 else ("ui-text" if label else "ui-picture"),
                 "width": ir["width"], "height": ir["height"], "alpha": "alpha2" in ir,
                 "colours": colour_words(ir["grid8"]),
                 "override": f"games/pilotwings64/overrides/blits/{bid}.png",
                 "prompt": "{} 2D menu illustration, clean 1990s console style".format(
                     ", ".join(colour_words(ir["grid8"])))}
            if label:
                b["label"] = label.get("text") or [c.get("text") for c in label.get("cells", [])]
            sub = os.path.join(out, f"blit_{bid}")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, "brief.json"), "w") as f:
                json.dump(b, f, indent=1)
            w, h = ir["width"], ir["height"]
            vis = G._upsample_grid(ir["grid8"], 8, w, h)
            png.write(os.path.join(sub, "guide.png"), np.clip(vis, 0, 255).astype(np.uint8))
            if "alpha2" in ir:
                cw = -(-w // ir["tile_w"]) * ir["tile_w"]
                a = G._unpack_alpha2(ir["alpha2"], cw, h)[:, :w]
                png.write(os.path.join(sub, "mask.png"), np.clip(a, 0, 255).astype(np.uint8)[..., None])
            idx.write(json.dumps(b) + "\n")
            n += 1
    print(f"{n} briefs (textures + blits) in {out}")


if __name__ == "__main__":
    main(sys.argv)
