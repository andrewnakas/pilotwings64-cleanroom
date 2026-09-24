"""Preview renders of a (clean) image: texture contact sheet and top-down
terrain maps per UVTR terrain.

    python -m games.pilotwings64.preview <image> <out_dir>
"""
import os
import struct
import sys
import zlib

import numpy as np

from cleanroom import iff
from cleanroom.gfx import texfmt
from . import profile as P, texlayout
from .formats import engine
from .generate import _tex_tiles, _simulate


def write_png(path, rgba):
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def load(image, seg=None):
    out = {}
    args = (seg["filetable"], seg["filesys"]) if seg else ()
    for e, raw in P.read_files(image, *args):
        out.setdefault(e.tag, {})[e.kind_index] = iff.parse_form(raw)
    return out


def texture_sheet(files, cell=64, cols=24):
    texs = files["UVTX"]
    rows = -(-len(texs) // cols)
    sheet = np.zeros((rows * cell, cols * cell, 4), np.uint8)
    sheet[..., 3] = 255
    avg = {}
    for tid, f in sorted(texs.items()):
        ir = engine.parse_uvtx(f.first("COMM").data)
        tiles = _tex_tiles(ir)
        if not tiles:
            continue
        t = min(tiles, key=lambda t: t["tmem"])
        img = bytes.fromhex(ir["image"])
        bits = texfmt.BITS[t["siz"]]
        stride = t["line"] * 8 or max(8, t["width"] * bits // 8)
        w = stride * 8 // bits
        h = min(t["height"], len(img) // max(1, stride))
        if t["fmt"] == texfmt.CI or h <= 0:
            continue
        data = texlayout.swizzle(img[t["tmem"] * 8:t["tmem"] * 8 + stride * h], stride)
        px = texfmt.decode(data, w, h, t["fmt"], t["siz"])[:, :t["width"]]
        avg[tid] = px[..., :3].reshape(-1, 3).mean(0)
        ys = (np.arange(cell) * px.shape[0] // cell)
        xs = (np.arange(cell) * px.shape[1] // cell)
        r, c = divmod(tid, cols)
        sheet[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = px[ys][:, xs]
    return sheet, avg


def terrain_map(files, tex_avg, terra_id, size=1024):
    tr = engine.parse_uvtr([c for c in files["UVTR"][0].chunks if c.tag == "COMM"][terra_id].data)
    tris2d = []
    for tile in tr["tiles"]:
        if not tile:
            continue
        m = np.array(tile["mtx"]).reshape(4, 4)
        ct = files["UVCT"].get(tile["contour"])
        if ct is None:
            continue
        c = engine.parse_uvct(ct.first("COMM").data)
        pos = np.array([v[:3] for v in c["vtx"]], float)
        if not len(pos):
            continue
        world = np.c_[pos, np.ones(len(pos))] @ m
        cols = np.array([v[6:9] for v in c["vtx"]], float) / 255.0
        for g in c["groups"]:
            base = tex_avg.get(g["state"] & 0xFFF, np.array([180, 180, 180]))
            for a, b, d in _simulate(g["cmds"]):
                tris2d.append((world[[a, b, d]], (base * cols[[a, b, d]].mean(0))))
    if not tris2d:
        return None
    allp = np.concatenate([t[0] for t in tris2d])
    lo, hi = allp.min(0), allp.max(0)
    scale = (size - 1) / max(hi[0] - lo[0], hi[1] - lo[1], 1e-6)
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 3] = 255
    zbuf = np.full((size, size), -1e30)
    for p, col in tris2d:
        xy = (p[:, :2] - lo[:2]) * scale
        x0, y0 = np.floor(xy.min(0)).astype(int)
        x1, y1 = np.ceil(xy.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
        (ax, ay), (bx, by), (cx, cy) = xy
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        l1 = ((by - cy) * (xx - cx) + (cx - bx) * (yy - cy)) / den
        l2 = ((cy - ay) * (xx - cx) + (ax - cx) * (yy - cy)) / den
        l3 = 1 - l1 - l2
        inside = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        z = l1 * p[0, 2] + l2 * p[1, 2] + l3 * p[2, 2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (z > sub)
        sub[upd] = z[upd]
        img[y0:y1 + 1, x0:x1 + 1, :3][upd] = np.clip(col, 0, 255).astype(np.uint8)
    return img[::-1]


def main(argv):
    image = open(argv[1], "rb").read()
    out = argv[2]
    os.makedirs(out, exist_ok=True)
    seg = None
    elf = os.path.splitext(argv[1])[0] + ".elf"
    if os.path.exists(elf):          # clean images use the reserved layout
        from .taint_report import segments_from_elf
        seg = segments_from_elf(elf)
    files = load(image, seg)
    sheet, avg = texture_sheet(files)
    write_png(os.path.join(out, "textures.png"), sheet)
    n = sum(1 for c in files["UVTR"][0].chunks if c.tag == "COMM")
    for t in range(n):
        img = terrain_map(files, avg, t)
        if img is not None:
            write_png(os.path.join(out, f"terrain{t}.png"), img)
    print(f"wrote previews to {out}")


if __name__ == "__main__":
    main(sys.argv)
