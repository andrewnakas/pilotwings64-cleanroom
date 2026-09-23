"""CLEAN ROOM: build graybox assets for every slot from spec/ alone.

Never imports cleanroom.rom.load_retail or extract_spec (enforced by
tests/test_cleanroom_rules.py). Output is deterministic.

Per slot:
  UVTX  procedural texels in the slot's own format and mip layout; colour
        chosen from how the texture is used (terrain height/slope, model)
  UVCT  kept terrain positions/topology; new UVs (planar) and vertex
        shading (or normals when lit)
  UVMD  one box per render state fitted to the kept bounds, same hierarchy
  UVAN  kept timing/part structure; rest pose from the model's transforms
  UVBT  panels with a gradient and border
  UVFT  glyphs from cleanroom.gfx.strokefont in the kept cell layout
  ADAT  text generated from each string's key
  UVEN  generated sky/fog colours
"""
import colorsys
import hashlib
import json
import math
import os
import struct

import numpy as np

from cleanroom import iff
from cleanroom.gfx import texfmt, gbi, strokefont
from cleanroom.binio import build_vtx
from . import profile as P
from .formats import engine, misc

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SPEC = os.path.join(HERE, "spec")

GFX_STATE_XLU = 1 << 23
GFX_STATE_LIGHTING = 1 << 27
TEX_NONE = 0xFFF


def _h(*parts) -> int:
    return int.from_bytes(hashlib.sha1(repr(parts).encode()).digest()[:8], "big")


def _rng(*parts):
    return np.random.default_rng(_h(*parts))


# --------------------------------------------------------------------- spec IO

class Spec:
    def __init__(self, spec_dir=DEFAULT_SPEC):
        self.dir = spec_dir
        with open(os.path.join(spec_dir, "manifest.json")) as f:
            self.manifest = json.load(f)
        self.files = []
        for m in self.manifest["files"]:
            with open(os.path.join(spec_dir, "files", m["file"])) as f:
                self.files.append((m, json.load(f)))

    def by_tag(self, tag):
        return {m["id"]: d for m, d in self.files if m["tag"] == tag}


def _comm(d):
    for c in d["chunks"]:
        if c["tag"] == "COMM":
            return c
    return None


# ----------------------------------------------------------------- geometry util

def _simulate(cmds):
    """Expand compressed dlist commands into triangles of vtx-table indices."""
    cache = [0] * 32
    tris = []
    for c in cmds:
        if c[0] == "vtx":
            for k in range(c[2]):
                cache[c[3] + k] = c[1] + k
        else:
            tris.append((cache[c[1]], cache[c[2]], cache[c[3]]))
    return tris


def _vertex_normals(pos, tris):
    pos = np.asarray(pos, dtype=np.float64)
    n = np.zeros_like(pos)
    for a, b, c in tris:
        fn = np.cross(pos[b] - pos[a], pos[c] - pos[a])
        n[a] += fn
        n[b] += fn
        n[c] += fn
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1
    n = n / ln
    # Winding may be either way; terrain should face up.
    return n


# ---------------------------------------------------------------- texture usage

class Usage:
    """How each texture ID is used, derived from kept facts only."""

    def __init__(self, spec: Spec):
        self.terrain = {}   # tex id -> list of (height, upness)
        self.model = set()
        self.xlu = set()
        ys_all = []
        for cid, d in spec.by_tag("UVCT").items():
            ir = _comm(d)["ir"]
            pos = [v[:3] for v in ir["vtx"]]
            if not pos:
                continue
            ys_all.extend(p[2] for p in pos)
            for g in ir["groups"]:
                tid = g["state"] & TEX_NONE
                tris = _simulate(g["cmds"])
                if not tris:
                    continue
                nrm = _vertex_normals(pos, tris)
                idx = sorted({i for t in tris for i in t})
                h = float(np.mean([pos[i][2] for i in idx]))
                up = float(np.mean(np.abs(nrm[idx][:, 2])))
                self.terrain.setdefault(tid, []).append((h, up))
        for mid, d in spec.by_tag("UVMD").items():
            for lod in _comm(d)["ir"]["lods"]:
                for part in lod["parts"]:
                    for st in part["states"]:
                        self.model.add(st["state"] & TEX_NONE)
                        if st["state"] & GFX_STATE_XLU:
                            self.xlu.add(st["state"] & TEX_NONE)
        self.y_lo = float(np.percentile(ys_all, 2)) if ys_all else 0.0
        self.y_hi = float(np.percentile(ys_all, 99)) if ys_all else 1.0

    def terrain_color(self, tid):
        hs = self.terrain[tid]
        h = float(np.mean([a for a, _ in hs]))
        up = float(np.mean([b for _, b in hs]))
        rel = (h - self.y_lo) / max(1.0, self.y_hi - self.y_lo)
        if rel < 0.02 and up > 0.97:
            return (40, 110, 190)      # water
        if rel < 0.06:
            return (214, 196, 140)     # sand
        if up < 0.75:
            return (128, 114, 100)     # rock
        if rel > 0.75:
            return (236, 238, 244)     # snow
        g = _rng("grass", tid).uniform(-12, 12)
        return (int(78 + g), int(140 + g), int(62 + g / 2))


# ------------------------------------------------------------------- textures

def _pattern(tid, w, h, base, kind):
    """Procedural RGBA pattern in normalised coordinates (mip-consistent)."""
    rng = _rng("tex", tid)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u = (xx + 0.5) / max(1, w)
    v = (yy + 0.5) / max(1, h)
    phase = rng.uniform(0, 6.28, 4)
    f = rng.integers(1, 4, 2)
    noise = (np.sin(6.2832 * f[0] * u + phase[0]) * np.sin(6.2832 * f[1] * v + phase[1]) * 0.5
             + np.sin(6.2832 * (u * 3 + v * 2) + phase[2]) * 0.25)
    shade = 1.0 + 0.10 * noise
    if kind == "model":
        # A soft panel border so boxes read as surfaces.
        edge = np.minimum(np.minimum(u, 1 - u), np.minimum(v, 1 - v))
        shade *= np.where(edge < 0.06, 0.78, 1.0)
    rgb = np.clip(np.asarray(base, np.float32)[None, None, :] * shade[..., None], 0, 255)
    a = np.full((h, w, 1), 255, np.float32)
    if kind == "sprite":
        d = np.hypot(u - 0.5, v - 0.5) * 2
        a = (np.clip((1.0 - d) * 4, 0, 1) * 255)[..., None]
    return np.concatenate([rgb, a], -1).astype(np.uint8)


def _tex_tiles(ir):
    """Render tiles incl. those sized at runtime (fall back to header dims)."""
    tiles = {}
    for c in ir["dlist"]:
        b = bytes.fromhex(c)
        w0, w1 = struct.unpack(">II", b)
        op = w0 >> 24
        if op == gbi.G_SETTILE:
            t = (w1 >> 24) & 7
            if t == 7:
                continue
            tiles.setdefault(t, {}).update(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3,
                                           line=(w0 >> 9) & 0x1FF, tmem=w0 & 0x1FF)
        elif op == gbi.G_SETTILESIZE:
            t = (w1 >> 24) & 7
            if t in tiles or True:
                uls, ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
                lrs, lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
                tiles.setdefault(t, {}).update(width=((lrs - uls) >> 2) + 1,
                                               height=((lrt - ult) >> 2) + 1)
    out = []
    for t in sorted(tiles):
        d = tiles[t]
        if "fmt" not in d:
            continue
        d.setdefault("width", ir["width"])
        d.setdefault("height", ir["height"])
        out.append(d)
    return out


def gen_uvtx(tid, ir, usage: Usage):
    size = ir["image_size"]
    img = bytearray(size)
    if tid in usage.terrain:
        base, kind = usage.terrain_color(tid), "terrain"
    elif tid in usage.xlu:
        base, kind = (250, 250, 250), "sprite"
    else:
        hue = (_h("hue", tid) % 360) / 360.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.85)
        base, kind = (r * 255, g * 255, b * 255), "model"
    tiles = sorted(_tex_tiles(ir), key=lambda t: t["tmem"])
    for i, t in enumerate(tiles):
        start = t["tmem"] * 8
        if start >= size:
            continue
        end = tiles[i + 1]["tmem"] * 8 if i + 1 < len(tiles) and tiles[i + 1]["tmem"] * 8 > start else size
        bits = texfmt.BITS[t["siz"]]
        stride = t["line"] * 8 or max(8, (t["width"] * bits + 7) // 8)
        texels_w = stride * 8 // bits
        rows = max(1, -(-(end - start) // stride))
        rgba = _pattern(tid, texels_w, rows, base, kind)
        if t["fmt"] in (texfmt.RGBA, texfmt.IA, texfmt.I):
            if t["fmt"] != texfmt.RGBA:
                # Intensity textures are modulated by vertex/prim colour: keep them bright.
                rgba[..., :3] = np.clip(rgba[..., :3].astype(np.int32) + 90, 0, 255)
            data = texfmt.encode(rgba, t["fmt"], t["siz"])
        else:
            data = bytes(rows * stride)
        end = min(end, size)
        n = min(len(data), end - start)
        img[start:start + n] = data[:n]
    out = {k: v for k, v in ir.items() if k not in ("image_size", "tiles", "timg")}
    out["image"] = bytes(img).hex()
    return out


# ------------------------------------------------------------------- terrain

LIGHT = np.array([0.35, 0.40, 0.85])  # world is Z-up
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def gen_uvct(cid, ir, tex_dims, usage: Usage):
    pos = [v[:3] for v in ir["vtx"]]
    flags = [v[3] for v in ir["vtx"]]
    n = len(pos)
    uv = [(0, 0)] * n
    col = [(200, 200, 200, 255)] * n
    if n:
        P3 = np.asarray(pos, np.float64)
        x0, z0 = P3[:, 0].min(), P3[:, 1].min()
        ext = max(1.0, P3[:, 0].max() - x0, P3[:, 1].max() - z0)
        uv = list(uv)
        col = list(col)
        for g in ir["groups"]:
            tid = g["state"] & TEX_NONE
            tw, th = tex_dims.get(tid, (32, 32))
            tris = _simulate(g["cmds"])
            idx = sorted({i for t in tris for i in t} |
                         {i for c in g["cmds"] if c[0] == "vtx" for i in range(c[1], c[1] + c[2])})
            idx = [i for i in idx if i < n]
            nrm = _vertex_normals(pos, tris) if tris else np.zeros((n, 3))
            # Planar mapping, one repeat per `rep` units, kept inside s10.5 range.
            rep = max(128.0, ext * max(tw, th) / 1900.0)
            base = usage.terrain_color(tid) if tid in usage.terrain else (170, 170, 170)
            for i in idx:
                s = int(round((pos[i][0] - x0) / rep * tw * 32))
                t = int(round((pos[i][1] - z0) / rep * th * 32))
                uv[i] = (max(-32768, min(32767, s)), max(-32768, min(32767, t)))
                nv = nrm[i]
                if nv[2] < 0:
                    nv = -nv
                if g["state"] & GFX_STATE_LIGHTING:
                    col[i] = tuple(int(round(c * 127)) & 0xFF for c in nv) + (255,)
                else:
                    lam = 0.55 + 0.45 * max(0.0, float(np.dot(nv, LIGHT)))
                    shade = int(max(0, min(255, 255 * lam)))
                    col[i] = (shade, shade, shade, 255)
    vtx = [[p[0], p[1], p[2], f, uv[i][0], uv[i][1], *col[i]] for i, (p, f) in enumerate(zip(pos, flags))]
    out = dict(ir)
    out["vtx"] = vtx
    return out


# -------------------------------------------------------------------- models

# Box faces as quads over corner indices of (x, y, z) in {lo, hi}.
_FACES = [((0, 1, 3, 2), (-1, 0, 0)), ((4, 6, 7, 5), (1, 0, 0)),
          ((0, 4, 5, 1), (0, -1, 0)), ((2, 3, 7, 6), (0, 1, 0)),
          ((0, 2, 6, 4), (0, 0, -1)), ((1, 5, 7, 3), (0, 0, 1))]


def _box(bbox, tw, th, lit, color):
    lo, hi = bbox[:3], bbox[3:]
    corners = [(hi[0] if i & 4 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 1 else lo[2])
               for i in range(8)]
    vtx = []
    tris = []
    quad_uv = [(0, 0), (tw * 32, 0), (tw * 32, th * 32), (0, th * 32)]
    for fi, (quad, nrm) in enumerate(_FACES):
        base = len(vtx)
        for k, ci in enumerate(quad):
            x, y, z = corners[ci]
            s, t = quad_uv[k]
            if lit:
                c = tuple(int(v * 127) & 0xFF for v in nrm) + (255,)
            else:
                lam = 0.6 + 0.4 * max(0.0, float(np.dot(nrm, LIGHT)))
                c = tuple(int(min(255, ch * lam)) for ch in color) + (255,)
            vtx.append([int(x), int(y), int(z), 0, min(32767, s), min(32767, t), *c])
        tris.append((base, base + 1, base + 2))
        tris.append((base, base + 2, base + 3))
    return vtx, tris


def _emit(vtx_table, local_vtx, local_tris):
    """Append vertices and produce compressed dlist commands (<=16 per load)."""
    cmds = []
    start = len(vtx_table)
    vtx_table.extend(local_vtx)
    # Faces are 4 vertices each: load up to 4 faces (16 verts) at a time.
    per = 16
    for off in range(0, len(local_vtx), per):
        cnt = min(per, len(local_vtx) - off)
        cmds.append(["vtx", start + off, cnt, 0, 0])
        for a, b, c in local_tris:
            if off <= a < off + cnt:
                cmds.append(["tri", a - off, b - off, c - off, 0])
    return cmds


def gen_uvmd(mid, ir, tex_dims):
    hue = (_h("model", mid) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.35, 0.95)
    color = (r * 255, g * 255, b * 255)
    vtx_table = []
    lods = []
    for lod in ir["lods"]:
        parts = []
        for part in lod["parts"]:
            states = []
            for st in part["states"]:
                cmds = []
                ntri = nx = 0
                if st["bbox"]:
                    tid = st["state"] & TEX_NONE
                    tw, th = tex_dims.get(tid, (32, 32))
                    lv, lt = _box(st["bbox"], tw, th, bool(st["state"] & GFX_STATE_LIGHTING), color)
                    cmds = _emit(vtx_table, lv, lt)
                    ntri, nx = len(lt), len(lv)
                states.append({"state": st["state"], "xfm": nx, "tris": ntri, "cmds": cmds})
            parts.append({"unk5": part["unk5"], "unk6": part["unk6"], "states": states})
        lods.append({"billboard": lod["billboard"], "radius": lod["radius"], "parts": parts})
    out = {k: ir[k] for k in ("transparent", "mtx", "joints", "unk1C", "unk20", "unk24", "keys", "tail")}
    out["vtx"] = vtx_table
    out["lods"] = lods
    return out


# ---------------------------------------------------------------- animation

def _mat_to_quat(m):
    """Inverse of uvMat4SetQuaternionRotation (returns x, y, z, w)."""
    R = np.array([[m[0], m[1], m[2]], [m[4], m[5], m[6]], [m[8], m[9], m[10]]], dtype=np.float64)
    # Remove scale.
    for c in range(3):
        n = np.linalg.norm(R[:, c])
        if n > 1e-9:
            R[:, c] /= n
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q) or 1.0
    return [float(v) for v in q]


def gen_uvan_part(ir, model_ir):
    mtx = model_ir["mtx"] if model_ir else []
    p = ir["part"]
    q = _mat_to_quat(mtx[p]) if 0 <= p < len(mtx) else [0.0, 0.0, 0.0, 1.0]
    return {"part": p, "tail": ir["tail"],
            "keys": [{"q": q, "frame": k["frame"], "flags": k["flags"]} for k in ir["keys"]]}


# --------------------------------------------------------------- blits / UI

SIZ_OF_DEPTH = {4: texfmt.B4, 8: texfmt.B8, 16: texfmt.B16, 32: texfmt.B32}


def gen_uvbt(bid, ir):
    w, h, stride = ir["width"], ir["height"], ir["stride"]
    hue = (_h("blit", bid) % 360) / 360.0
    yy, xx = np.mgrid[0:h, 0:stride].astype(np.float32)
    v = yy / max(1, h - 1)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.35, 0.9)
    base = np.array([r, g, b], np.float32) * 255
    rgb = base[None, None, :] * (0.75 + 0.25 * (1 - v))[..., None]
    border = (xx < 1) | (yy < 1) | (xx >= w - 1) | (yy >= h - 1)
    rgb[border] = (40, 40, 48)
    rgba = np.concatenate([rgb, np.full((h, stride, 1), 255, np.float32)], -1)
    rgba[:, w:, 3] = 0
    fmt = ir["fmt"] if ir["fmt"] in (texfmt.RGBA, texfmt.IA, texfmt.I) else texfmt.RGBA
    data = texfmt.encode(rgba.astype(np.uint8), fmt, SIZ_OF_DEPTH[ir["depth"]])
    need = stride * h * ir["depth"] // 8
    out = dict(ir)
    out["pixels"] = data[:need].ljust(need, b"\0").hex()
    return out


def gen_uvft(chunks):
    """Rebuild a font from kept STRG/FRMT/BITM layout and our stroke glyphs."""
    strg = b""
    fmt = siz = 0
    bitm = []
    imag_sizes = []
    for c in chunks:
        if not isinstance(c, dict):
            continue
        if c["tag"] == "STRG":
            strg = bytes.fromhex(c["ascii"])
        elif c["tag"] == "FRMT":
            fmt, siz = struct.unpack(">ii", bytes.fromhex(c["hex"]))
        elif c["tag"] == "BITM":
            bitm = c["bitm"]
        elif c["tag"] == "IMAG":
            imag_sizes.append(c["size"])
    bits = texfmt.BITS[siz]
    widths = {}
    for b in bitm:
        widths.setdefault(b["imag"], b["width_img"])
    images = []
    for i, size in enumerate(imag_sizes):
        wi = widths.get(i, 8)
        rows = size * 8 // (wi * bits)
        images.append(np.zeros((rows, wi), np.float32))
    for gi, b in enumerate(bitm):
        ch = chr(strg[gi]) if gi < len(strg) and strg[gi] else ""
        if not ch or b["imag"] >= len(images):
            continue
        img = images[b["imag"]]
        cw, chh = b["width"], b["height"]
        mask = strokefont.render(ch, cw, chh)
        y0, x0 = b["t"], b["s"]
        y1, x1 = min(img.shape[0], y0 + chh), min(img.shape[1], x0 + cw)
        if y1 > y0 and x1 > x0:
            img[y0:y1, x0:x1] = np.maximum(img[y0:y1, x0:x1], mask[:y1 - y0, :x1 - x0])
    out = []
    for i, m in enumerate(images):
        rgba = np.zeros(m.shape + (4,), np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = (m * 255).astype(np.uint8)
        f = fmt if fmt in (texfmt.RGBA, texfmt.IA, texfmt.I) else texfmt.IA
        data = texfmt.encode(rgba, f, siz)
        out.append(data[:imag_sizes[i]].ljust(imag_sizes[i], b"\0"))
    return out


# ------------------------------------------------------------------- text

TEXT_ENCODE = {**{str(d): d for d in range(10)},
               **{chr(ord("A") + i): 0x0A + i for i in range(26)},
               **{chr(ord("a") + i): 0x24 + i for i in range(26)},
               "-": 0x3E, "#": 0x3F, "<": 0x40, ">": 0x41, " ": 0x42, "\\": 0x43,
               "(": 0x44, ")": 0x45, "*": 0x46, "&": 0x47, ",": 0x48, ".": 0x49,
               "/": 0x4A, "!": 0x4B, "?": 0x4C, "'": 0x4D, ":": 0x4F, "%": 0xD4,
               "\t": 0xFD, "\n": 0xFE}


def encode_text(s: str, size: int) -> bytes:
    out = bytearray()
    for ch in s:
        v = TEXT_ENCODE.get(ch)
        if v is None:
            continue
        if len(out) + 4 > size:
            break
        out += struct.pack(">H", v)
    while len(out) + 2 <= size:
        out += b"\x00\xFF"
    return bytes(out[:size])


def text_from_key(key: str) -> str:
    words = [w for w in key.replace("-", "_").split("_") if w]
    return " ".join(w.capitalize() if w.isalpha() else w for w in words) or "Text"


# --------------------------------------------------------------- environment

def gen_uven(eid, ir):
    rng = _rng("env", eid)
    sky = (int(rng.uniform(90, 140)), int(rng.uniform(150, 190)), int(rng.uniform(215, 245)), 255)
    fog = tuple(min(255, int(c * 1.08)) for c in sky[:3]) + (255,)
    out = dict(ir)
    out["screen"] = list(sky)
    out["fog"] = list(fog)
    out["unused"] = [0, 0, 0, 0]
    return out


# ------------------------------------------------------------------- driver

def _chunk_bytes(c, data):
    return iff.Chunk(c["tag"], data, c["compressed"])


def generate(spec: Spec):
    """Return list of (tag, FORM bytes) in table order."""
    usage = Usage(spec)
    tex_dims = {}
    for tid, d in spec.by_tag("UVTX").items():
        ir = _comm(d)["ir"]
        tex_dims[tid] = (ir["width"], ir["height"])
    models = {mid: _comm(d)["ir"] for mid, d in spec.by_tag("UVMD").items()}

    out = []
    for m, d in spec.files:
        tag, fid = m["tag"], m["id"]
        chunks = []
        anim_model = None
        text_key = None
        for c in d["chunks"]:
            t = c["tag"]
            if t == "PAD ":
                chunks.append(_chunk_bytes(c, bytes(c["zeros"])))
                continue
            ftype = d["type"]
            if ftype in ("UVSY", "UVLV", "UVTP", "UVSQ", "UVTR") and t == "COMM":
                codec = engine.CODECS[ftype][1]
                chunks.append(_chunk_bytes(c, codec(c["ir"])))
            elif ftype == "UVTX":
                chunks.append(_chunk_bytes(c, engine.build_uvtx(gen_uvtx(fid, c["ir"], usage))))
            elif ftype == "UVCT":
                chunks.append(_chunk_bytes(c, engine.build_uvct(gen_uvct(fid, c["ir"], tex_dims, usage))))
            elif ftype == "UVMD":
                chunks.append(_chunk_bytes(c, engine.build_uvmd(gen_uvmd(fid, c["ir"], tex_dims))))
            elif ftype == "UVEN":
                eid = sum(1 for x in chunks if x.tag == "COMM")
                chunks.append(_chunk_bytes(c, engine.build_uven(gen_uven(eid, c["ir"]))))
            elif ftype == "UVBT":
                chunks.append(_chunk_bytes(c, misc.build_uvbt(gen_uvbt(fid, c["ir"]))))
            elif ftype == "UVAN":
                if t == "COMM":
                    anim_model = models.get(c["ir"]["model"])
                    chunks.append(_chunk_bytes(c, misc.build_uvan_comm(c["ir"])))
                else:
                    chunks.append(_chunk_bytes(c, misc.build_uvan_part(gen_uvan_part(c["ir"], anim_model))))
            elif ftype == "UVFT":
                chunks.append(c)  # resolved below
            elif ftype == "ADAT":
                if t == "NAME":
                    raw = bytes.fromhex(c["hex"])
                    text_key = raw.split(b"\0")[0].decode("ascii", "replace")
                    chunks.append(_chunk_bytes(c, raw))
                elif t == "DATA":
                    chunks.append(_chunk_bytes(c, encode_text(text_from_key(text_key or "Text"), c["size"])))
                else:
                    chunks.append(_chunk_bytes(c, bytes.fromhex(c["hex"])))
            elif ftype == "UPWT" and t in ("NAME", "INFO", "JPTX"):
                label = {"NAME": f"Task {fid}", "INFO": "graybox task", "JPTX": f"T_{fid}"}[t]
                chunks.append(_chunk_bytes(c, label.encode("ascii")[:c["size"] - 1].ljust(c["size"], b"\0")))
            elif "hex" in c:
                chunks.append(_chunk_bytes(c, bytes.fromhex(c["hex"])))
            elif ftype == "UVSX":
                chunks.append(c)  # filled by the audio generator
            else:
                raise ValueError(f"no generator for {ftype}/{t}")
        if d["type"] == "UVFT":
            images = iter(gen_uvft(chunks))
            built = []
            for c in chunks:
                if not isinstance(c, dict):
                    built.append(c)
                elif c["tag"] == "STRG":
                    built.append(_chunk_bytes(c, bytes.fromhex(c["ascii"])))
                elif c["tag"] == "FRMT":
                    built.append(_chunk_bytes(c, bytes.fromhex(c["hex"])))
                elif c["tag"] == "BITM":
                    built.append(_chunk_bytes(c, misc.build_bitm(c["bitm"])))
                elif c["tag"] == "IMAG":
                    built.append(_chunk_bytes(c, next(images)))
                else:
                    built.append(c)
            chunks = built
        out.append((m, d["type"], chunks))
    return out
