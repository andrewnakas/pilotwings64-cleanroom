"""Codecs for UltraVision engine chunks (the COMM payloads of UV* files).

Each parse_X(bytes) -> dict mirrors the reader in the decomp
(src/kernel/texture.c: _uvParseUVMD, _uvParseUVCT, _uvExpandTexture, ...),
and build_X(dict) -> bytes is its exact inverse. Byte-for-byte round-trip is
tested against every file in tests/test_pw64_formats.py.

Note: uvConsumeBytes reads 1/2/4-byte fields as big-endian scalars and
larger fields as raw struct copies; raw copies are kept as hex strings or
decoded where their layout is known (Mtx4F, Vtx).
"""
from cleanroom.binio import Reader, Writer, parse_vtx, build_vtx, VTX_SIZE


def _gfx_cmd_list(r, n):
    return [r.bytes(8).hex() for _ in range(n)]


# ---------------------------------------------------------------- display lists
# UVMD/UVCT store compressed display lists: u16 elem; if elem & 0x4000 it is a
# triangle (three 4-bit vertex-cache indices), else a vertex load of
# ((b >> 4) + 1) vertices from vtxTable[elem & 0x3FFF] into cache slot b & 0xF.
# Bits 0x8000/0x3000 of triangles are preserved as "hi" for exact round-trip.

def _parse_cmds(r, count):
    cmds = []
    for _ in range(count):
        e = r.u16()
        if e & 0x4000:
            cmds.append(["tri", (e >> 8) & 0xF, (e >> 4) & 0xF, e & 0xF, e & 0xB000])
        else:
            b = r.u8()
            cmds.append(["vtx", e & 0x3FFF, (b >> 4) + 1, b & 0xF, e & 0xC000])
    return cmds


def _build_cmds(w, cmds):
    for c in cmds:
        if c[0] == "tri":
            w.u16(0x4000 | c[4] | (c[1] << 8) | (c[2] << 4) | c[3])
        else:
            w.u16(c[1] | c[4])
            w.u8(((c[2] - 1) << 4) | c[3])


def _parse_state(r):
    st = {"state": r.u32(), "xfm": r.s16(), "tris": r.s16()}
    n = r.u16()
    st["cmds"] = _parse_cmds(r, n)
    return st


def _build_state(w, st):
    w.u32(st["state"])
    w.s16(st["xfm"])
    w.s16(st["tris"])
    w.u16(len(st["cmds"]))
    _build_cmds(w, st["cmds"])


# ------------------------------------------------------------------------ UVMD

def parse_uvmd(data: bytes) -> dict:
    r = Reader(data)
    vtx_count = r.u16()
    lod_count = r.u8()
    mtx_count = r.u8()
    n24 = r.u8()
    transparent = r.u8()
    n6 = r.u16()
    m = {"transparent": transparent}
    m["vtx"] = parse_vtx(r.bytes(vtx_count * VTX_SIZE))
    lods = []
    for _ in range(lod_count):
        part_count = r.u8()
        lod = {"billboard": r.u8(), "parts": []}
        for _ in range(part_count):
            state_count = r.u8()
            part = {"unk5": r.u8(), "unk6": r.u8(), "states": []}
            for _ in range(state_count):
                part["states"].append(_parse_state(r))
            lod["parts"].append(part)
        lod["radius"] = r.f32()
        lods.append(lod)
    m["lods"] = lods
    m["mtx"] = [r.f32s(16) for _ in range(mtx_count)]
    # UnkUVMD_24: u8 part, u8, u8, pad, f32[6], u16 count, pad, ptr (raw copy)
    m["joints"] = []
    for _ in range(n24):
        j = {"part": r.u8(), "b1": r.u8(), "b2": r.u8(), "pad3": r.u8(),
             "f": r.f32s(6), "count": r.u16(), "pad1e": r.u16(), "ptr": r.u32()}
        m["joints"].append(j)
    m["unk1C"] = r.f32()
    m["unk20"] = r.f32()
    m["unk24"] = r.f32()
    m["keys"] = [[r.u16(), r.u16(), r.u16()] for _ in range(n6)]
    m["tail"] = r.bytes(r.remaining()).hex()
    return m


def build_uvmd(m: dict) -> bytes:
    w = Writer()
    w.u16(len(m["vtx"]))
    w.u8(len(m["lods"]))
    w.u8(len(m["mtx"]))
    w.u8(len(m["joints"]))
    w.u8(m["transparent"])
    w.u16(len(m["keys"]))
    w.bytes(build_vtx(m["vtx"]))
    for lod in m["lods"]:
        w.u8(len(lod["parts"]))
        w.u8(lod["billboard"])
        for part in lod["parts"]:
            w.u8(len(part["states"]))
            w.u8(part["unk5"])
            w.u8(part["unk6"])
            for st in part["states"]:
                _build_state(w, st)
        w.f32(lod["radius"])
    for mt in m["mtx"]:
        w.f32s(mt)
    for j in m["joints"]:
        w.u8(j["part"]); w.u8(j["b1"]); w.u8(j["b2"]); w.u8(j["pad3"])
        w.f32s(j["f"]); w.u16(j["count"]); w.u16(j["pad1e"]); w.u32(j["ptr"])
    w.f32(m["unk1C"]); w.f32(m["unk20"]); w.f32(m["unk24"])
    for k in m["keys"]:
        w.u16(k[0]); w.u16(k[1]); w.u16(k[2])
    w.bytes(bytes.fromhex(m["tail"]))
    return w.getvalue()


# ------------------------------------------------------------------------ UVCT

def parse_uvct(data: bytes) -> dict:
    r = Reader(data)
    vtx_count = r.u16()
    n_boxes = r.u16()
    n_objs = r.u16()
    n_groups = r.u16()
    c = {"vtx": parse_vtx(r.bytes(vtx_count * VTX_SIZE))}
    c["boxes"] = [[r.u16(), r.u16(), r.u16(), r.u16()] for _ in range(n_boxes)]
    c["objs"] = []
    for _ in range(n_objs):
        nm = r.u8()
        o = {"mtx": [r.bytes(0x40).hex() for _ in range(nm)],
             "model": r.u16(), "f": r.f32s(3), "u14": r.u16(), "u16": r.u16()}
        c["objs"].append(o)
    c["groups"] = []
    for _ in range(n_groups):
        g = _parse_state(r)
        g["box"] = r.u16()
        g["u10"] = r.u16()
        g["u12"] = r.u16()
        g["u14"] = r.u16()
        g["f"] = r.f32s(4)
        c["groups"].append(g)
    c["f"] = r.f32s(5)
    c["tail"] = r.bytes(r.remaining()).hex()
    return c


def build_uvct(c: dict) -> bytes:
    w = Writer()
    w.u16(len(c["vtx"])); w.u16(len(c["boxes"])); w.u16(len(c["objs"])); w.u16(len(c["groups"]))
    w.bytes(build_vtx(c["vtx"]))
    for b in c["boxes"]:
        for v in b:
            w.u16(v)
    for o in c["objs"]:
        w.u8(len(o["mtx"]))
        for mt in o["mtx"]:
            w.bytes(bytes.fromhex(mt))
        w.u16(o["model"]); w.f32s(o["f"]); w.u16(o["u14"]); w.u16(o["u16"])
    for g in c["groups"]:
        _build_state(w, g)
        w.u16(g["box"]); w.u16(g["u10"]); w.u16(g["u12"]); w.u16(g["u14"])
        w.f32s(g["f"])
    w.f32s(c["f"])
    w.bytes(bytes.fromhex(c["tail"]))
    return w.getvalue()


# ------------------------------------------------------------------------ UVTX

def parse_uvtx(data: bytes) -> dict:
    r = Reader(data)
    size = r.u16()
    gfx_count = r.u16()
    t = {"scroll0": r.f32s(2), "scroll1": r.f32s(2)}
    t["image"] = r.bytes(size).hex()
    t["dlist"] = _gfx_cmd_list(r, gfx_count)
    t["width"] = r.u16()
    t["height"] = r.u16()
    t["unkE"] = r.u8()
    t["unkF"] = r.u8()
    t["unk10"] = r.u8()
    t["state"] = r.u16()
    t["unk14"] = r.u16()
    t["unk20"] = r.u16()
    t["unk22"] = [r.u8() for _ in range(5)]
    t["unk28"] = r.f32()
    t["tail"] = r.bytes(r.remaining()).hex()
    return t


def build_uvtx(t: dict) -> bytes:
    w = Writer()
    img = bytes.fromhex(t["image"])
    w.u16(len(img)); w.u16(len(t["dlist"]))
    w.f32s(t["scroll0"]); w.f32s(t["scroll1"])
    w.bytes(img)
    for g in t["dlist"]:
        w.bytes(bytes.fromhex(g))
    w.u16(t["width"]); w.u16(t["height"])
    w.u8(t["unkE"]); w.u8(t["unkF"]); w.u8(t["unk10"])
    w.u16(t["state"]); w.u16(t["unk14"]); w.u16(t["unk20"])
    for b in t["unk22"]:
        w.u8(b)
    w.f32(t["unk28"])
    w.bytes(bytes.fromhex(t["tail"]))
    return w.getvalue()


# ------------------------------------------------------------------------ UVTR

def parse_uvtr(data: bytes) -> dict:
    r = Reader(data)
    t = {"bounds": r.f32s(6)}
    t["rows"] = r.u8()
    t["cols"] = r.u8()
    t["f"] = r.f32s(3)
    tiles = []
    for _ in range(t["rows"] * t["cols"]):
        kind = r.u8()
        if kind == 0:
            tiles.append(None)
        else:
            tiles.append({"kind": kind, "mtx": r.f32s(16), "u44": r.u8(), "contour": r.u16()})
    t["tiles"] = tiles
    t["tail"] = r.bytes(r.remaining()).hex()
    return t


def build_uvtr(t: dict) -> bytes:
    w = Writer()
    w.f32s(t["bounds"])
    w.u8(t["rows"]); w.u8(t["cols"])
    w.f32s(t["f"])
    for tile in t["tiles"]:
        if tile is None:
            w.u8(0)
        else:
            w.u8(tile["kind"]); w.f32s(tile["mtx"]); w.u8(tile["u44"]); w.u16(tile["contour"])
    w.bytes(bytes.fromhex(t["tail"]))
    return w.getvalue()


# ------------------------------------------------------------ small tables

LV_KEYS = ("terra", "light", "env", "model", "contour", "texture",
           "sequence", "animation", "font", "blit")


def parse_uvlv(data: bytes) -> dict:
    r = Reader(data)
    lv = {}
    for k in LV_KEYS:
        n = r.u16()
        lv[k] = [r.u16() for _ in range(n)]
    lv["tail"] = r.bytes(r.remaining()).hex()
    return lv


def build_uvlv(lv: dict) -> bytes:
    w = Writer()
    for k in LV_KEYS:
        w.u16(len(lv[k]))
        for v in lv[k]:
            w.u16(v)
    w.bytes(bytes.fromhex(lv["tail"]))
    return w.getvalue()


def parse_uven(data: bytes) -> dict:
    r = Reader(data)
    n = r.u8()
    e = {"models": [[r.u16(), r.u8()] for _ in range(n)]}
    e["screen"] = [r.u8() for _ in range(4)]
    e["fog"] = [r.u8() for _ in range(4)]
    e["unused"] = [r.u8() for _ in range(4)]
    e["padC"] = r.bytes(8).hex()
    e["fog_min"] = r.f32()
    e["fog_max"] = r.f32()
    e["fog_enabled"] = r.u8()
    e["pad1d"] = r.bytes(0x11).hex()
    e["clear_enabled"] = r.u8()
    e["rest"] = r.bytes(0x3C - 0x2F).hex() if r.remaining() >= 0x3C - 0x2F else ""
    e["tail"] = r.bytes(r.remaining()).hex()
    return e


def build_uven(e: dict) -> bytes:
    w = Writer()
    w.u8(len(e["models"]))
    for mid, flag in e["models"]:
        w.u16(mid); w.u8(flag)
    for k in ("screen", "fog", "unused"):
        for v in e[k]:
            w.u8(v)
    w.bytes(bytes.fromhex(e["padC"]))
    w.f32(e["fog_min"]); w.f32(e["fog_max"]); w.u8(e["fog_enabled"])
    w.bytes(bytes.fromhex(e["pad1d"])); w.u8(e["clear_enabled"])
    w.bytes(bytes.fromhex(e["rest"])); w.bytes(bytes.fromhex(e["tail"]))
    return w.getvalue()


def parse_uvsq(data: bytes) -> dict:
    r = Reader(data)
    n = r.u8()
    s = {"frames": [[r.u16(), r.f32()] for _ in range(n)]}
    s["mode"] = r.u8()
    s["reverse"] = r.u8()
    s["framerate"] = r.f32()
    s["tail"] = r.bytes(r.remaining()).hex()
    return s


def build_uvsq(s: dict) -> bytes:
    w = Writer()
    w.u8(len(s["frames"]))
    for tid, ft in s["frames"]:
        w.u16(tid); w.f32(ft)
    w.u8(s["mode"]); w.u8(s["reverse"]); w.f32(s["framerate"])
    w.bytes(bytes.fromhex(s["tail"]))
    return w.getvalue()


def parse_uvtp(data: bytes) -> dict:
    r = Reader(data)
    n = r.u16()
    p = {"map": [[r.u16(), r.u16()] for _ in range(n)]}
    p["tail"] = r.bytes(r.remaining()).hex()
    return p


def build_uvtp(p: dict) -> bytes:
    w = Writer()
    w.u16(len(p["map"]))
    for a, b in p["map"]:
        w.u16(a); w.u16(b)
    w.bytes(bytes.fromhex(p["tail"]))
    return w.getvalue()


SY_KEYS = ("version", "UVMD", "UVCT", "UVTX", "UVEN", "UVLT", "UVTR", "UVSQ",
           "UVLV", "UVAN", "UVFT", "UVBT", "USER", "UVSX", "UVTP", "unk22")


def parse_uvsy(data: bytes) -> dict:
    r = Reader(data)
    s = {"f0": r.f32()}
    for k in SY_KEYS:
        s[k] = r.u16()
    s["tail"] = r.bytes(r.remaining()).hex()
    return s


def build_uvsy(s: dict) -> bytes:
    w = Writer()
    w.f32(s["f0"])
    for k in SY_KEYS:
        w.u16(s[k])
    w.bytes(bytes.fromhex(s["tail"]))
    return w.getvalue()


CODECS = {
    "UVMD": (parse_uvmd, build_uvmd),
    "UVCT": (parse_uvct, build_uvct),
    "UVTX": (parse_uvtx, build_uvtx),
    "UVTR": (parse_uvtr, build_uvtr),
    "UVLV": (parse_uvlv, build_uvlv),
    "UVEN": (parse_uven, build_uven),
    "UVSQ": (parse_uvsq, build_uvsq),
    "UVTP": (parse_uvtp, build_uvtp),
    "UVSY": (parse_uvsy, build_uvsy),
}
