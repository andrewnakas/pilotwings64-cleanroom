"""DIRTY ROOM: find text-bearing textures and blits for the label tables.

    python -m games.pilotwings64.find_text <retail rom> [out_dir] [--top N]

Writes (to work/find_text by default, never into the repo's clean outputs):
  sheet.png      the top-N candidates, decoded (unswizzled, detiled), in rank order
  ranking.json   [{"kind", "id", "score", "rect"}] in the same order
A person reads the sheet and fills tex_labels.json / hud_labels.json.
"""
import json
import os
import sys

import numpy as np

from cleanroom import iff
from cleanroom.find_text import text_score, contact_sheet
from cleanroom.gfx import png, texfmt
from cleanroom.rom import load_retail
from . import profile as P, texlayout
from .formats import engine, misc


def decoded_images(rom):
    """Yield (kind, id, rgba) for every UVTX first region and every blit."""
    counters = {}
    for e, raw in P.read_files(rom):
        tag = e.tag.strip()
        if tag not in ("UVTX", "UVBT"):
            continue
        form = iff.parse_form(raw)
        comm = [c for c in form.chunks if c.tag == "COMM"]
        if not comm:
            continue
        if tag == "UVTX":
            ir = engine.parse_uvtx(comm[0].data)
            img = bytes.fromhex(ir["image"])
            for t, s, en, stride, tw, rows in texlayout.regions(ir, len(img)):
                if t["fmt"] not in (texfmt.RGBA, texfmt.IA, texfmt.I):
                    break
                data = texlayout.swizzle(img[s:en].ljust(stride * rows, b"\0"), stride)
                rgba = texfmt.decode(data, tw, rows, t["fmt"], t["siz"])
                yield "UVTX", e.kind_index, rgba[:min(rows, ir["height"]), :min(tw, ir["width"])]
                break
        else:
            b = misc.parse_uvbt(comm[0].data)
            fmt = b["fmt"] if b["fmt"] in (texfmt.RGBA, texfmt.IA, texfmt.I) else None
            if fmt is None:
                continue
            siz = {4: texfmt.B4, 8: texfmt.B8, 16: texfmt.B16, 32: texfmt.B32}[b["depth"]]
            px = misc.blit_swizzle(bytes.fromhex(b["pixels"]), b)
            flat = texfmt.decode(px, b["stride"] * b["height"], 1, fmt, siz)[0]
            img = misc.blit_detile(flat, b)[:, :b["width"]]
            yield "UVBT", e.kind_index, img


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    top = 80
    if "--top" in argv:
        top = int(argv[argv.index("--top") + 1])
        args = [a for a in args if a != str(top)]
    rom = load_retail(args[0])
    out = args[1] if len(args) > 1 else os.path.join("work", "find_text")
    os.makedirs(out, exist_ok=True)
    scored = []
    for kind, i, rgba in decoded_images(rom):
        scored.append((text_score(rgba), kind, i, rgba))
    scored.sort(key=lambda s: -s[0])
    best = scored[:top]
    sheet, place = contact_sheet([((k, i), im) for _, k, i, im in best])
    png.write(os.path.join(out, "sheet.png"), sheet)
    with open(os.path.join(out, "ranking.json"), "w") as f:
        json.dump([{"kind": k, "id": i, "score": round(s, 3), "rect": place[(k, i)]}
                   for s, k, i, _ in best], f, indent=1)
    print(f"{len(scored)} images scored; top {len(best)} in {out}")
    return scored


if __name__ == "__main__":
    main(sys.argv)
