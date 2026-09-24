"""CLEAN ROOM: UI pictures rendered from kept model geometry.

The original menus show pre-rendered pictures of the game's own vehicles and
pilots. We keep those models as facts, so we render our own pictures of them
(own camera, own lighting, colours from our generated textures) instead of
upsampling a coarse colour grid. Which model goes where is authoring data in
ui_renders.json.
"""
import json
import os

import numpy as np

from cleanroom.gfx import raster

HERE = os.path.dirname(os.path.abspath(__file__))
ZUP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float32)     # model z-up -> view y-up

_CFG = None


def config():
    global _CFG
    if _CFG is None:
        with open(os.path.join(HERE, "ui_renders.json")) as f:
            _CFG = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    return _CFG


class Models:
    """Triangles of kept models in their rest pose, coloured by vertex
    colour and our generated textures (sampled at each vertex's UV)."""

    def __init__(self, spec):
        from . import generate as G
        self.G = G
        self.md = spec.by_tag("UVMD")
        self.tx = spec.by_tag("UVTX")
        self._tex = {}
        self._tris = {}

    def _texture(self, tid):
        if tid not in self._tex:
            G = self.G
            img = None
            if tid in self.tx:
                ir = G._comm(self.tx[tid])["ir"]
                d = (ir.get("digest") or [None])[0]
                if d:
                    n = int(round(len(d["grid"]) ** 0.5))
                    img = G._upsample_grid(d["grid"], n, d["vw"], d["vh"])
            self._tex[tid] = img
        return self._tex[tid]

    def tris(self, mid, parts=None):
        key = (mid, tuple(parts) if parts else None)
        if key in self._tris:
            return self._tris[key]
        G = self.G
        ir = G._comm(self.md[mid])["ir"]
        V = np.asarray(ir["vtx"], np.float32)
        mt = [np.asarray(m, np.float32).reshape(4, 4) for m in ir["mtx"]]
        out, stack = [], {}
        for pi, part in enumerate(ir["lods"][0]["parts"]):
            # Parts are a depth-first tree: unk6 is the depth, each part's
            # matrix is relative to the nearest earlier part one level up.
            local = mt[pi] if pi < len(mt) else np.eye(4, dtype=np.float32)
            depth = part["unk6"]
            M = local @ stack[depth - 1] if depth > 0 and (depth - 1) in stack else local
            stack[depth] = M
            if parts and pi not in parts:
                continue
            for st in part["states"]:
                tid = st["state"] & G.TEX_NONE
                lit = bool(st["state"] & G.GFX_STATE_LIGHTING)
                tex = self._texture(tid) if tid != G.TEX_NONE else None
                for a, b, c in G._simulate(st["cmds"]):
                    idx = [a, b, c]
                    p = (np.c_[V[idx, :3], np.ones(3)] @ M)[:, :3]
                    col = np.full((3, 4), 255, np.float32)
                    if not lit:
                        col[:, :3] = V[idx, 6:9]
                        col[:, 3] = V[idx, 9]
                    if tex is not None:
                        th, tw = tex.shape[:2]
                        s = (V[idx, 4] / 32).astype(int) % tw
                        t = (V[idx, 5] / 32).astype(int) % th
                        col[:, :3] = col[:, :3] * tex[t, s, :3] / 255
                    elif lit:
                        col[:, :3] = 200
                    out.append((p, col, lit))
        self._tris[key] = out
        return out


def picture(models, spec_item, w, h):
    """Render one configured picture: {"model", "yaw", "pitch", "fit",
    "crop"} where crop=[top, bottom] keeps a vertical slice (0 = top of the
    model, 1 = bottom) -- e.g. [0, 0.45] for head and shoulders."""
    mid = int(spec_item["model"], 0)
    tris = models.tris(mid)
    crop = spec_item.get("crop")
    if crop:
        zs = np.array([t[0][:, 2] for t in tris])
        top, bot = zs.max(), zs.min()
        z_hi = top - crop[0] * (top - bot)
        z_lo = top - crop[1] * (top - bot)
        tris = [t for t in tris if t[0][:, 2].max() >= z_lo and t[0][:, 2].min() <= z_hi]
    rot = raster.look_at(spec_item.get("yaw", 0.6), spec_item.get("pitch", -0.3)) @ ZUP
    return raster.render(tris, w, h, rot, fit=spec_item.get("fit", 0.9),
                         px_per_unit=spec_item.get("px_per_unit"))


def height(models, mid):
    zs = np.concatenate([t[0][:, 2] for t in models.tris(int(mid, 0))])
    return float(zs.max() - zs.min())


def composite(dst, src, x, y):
    """Alpha-blend src (h, w, 4) into dst at (x, y)."""
    h, w = src.shape[:2]
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return dst
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4] / 255.0
    reg = dst[y0:y1, x0:x1]
    reg[..., :3] = reg[..., :3] * (1 - a) + s[..., :3] * a
    reg[..., 3] = np.maximum(reg[..., 3], s[..., 3])
    return dst


def backdrop(w, h, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = np.asarray(top, np.float32) * (1 - t) + np.asarray(bottom, np.float32) * t
    img[..., 3] = 255
    return img
