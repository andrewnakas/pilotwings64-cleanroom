"""Codecs for UVBT (blits), UVFT (fonts), UVAN (joint animation) chunks.

References in the decomp: _uvParseUVBT (src/kernel/texture.c),
uvParseTopUVFT (src/kernel/font.c), uvJanimLoad (src/kernel/anim.c).
"""
import struct

from cleanroom.binio import Reader, Writer


# ------------------------------------------------------------------------ UVBT
# COMM: u16 fmt, u16 bitdepth, u16 width, u16 stride, u16 height,
# u16 tile_w, u16 tile_h, then stride*height*bitdepth/8 bytes of texels.

def parse_uvbt(data: bytes) -> dict:
    r = Reader(data)
    b = {"fmt": r.u16(), "depth": r.u16(), "width": r.u16(), "stride": r.u16(),
         "height": r.u16(), "tile_w": r.u16(), "tile_h": r.u16()}
    n = b["stride"] * b["height"] * b["depth"] // 8
    b["pixels"] = r.bytes(n).hex()
    b["tail"] = r.bytes(r.remaining()).hex()
    return b


def build_uvbt(b: dict) -> bytes:
    w = Writer()
    for k in ("fmt", "depth", "width", "stride", "height", "tile_w", "tile_h"):
        w.u16(b[k])
    w.bytes(bytes.fromhex(b["pixels"]))
    w.bytes(bytes.fromhex(b["tail"]))
    return w.getvalue()


# ------------------------------------------------------------------------ UVFT
# STRG: the characters the font covers, FRMT: s32 fmt, s32 siz,
# BITM: libultra Bitmap[] (s16 width, width_img, s, t; u32 buf = IMAG index;
# s16 actualHeight, LUToffset), IMAG: texel blocks.

def parse_bitm(data: bytes):
    out = []
    for i in range(0, len(data), 16):
        w, wi, s, t, buf, ah, lut = struct.unpack_from(">hhhhIhh", data, i)
        out.append({"width": w, "width_img": wi, "s": s, "t": t, "imag": buf,
                    "height": ah, "lut": lut})
    return out


def build_bitm(bitm) -> bytes:
    return b"".join(struct.pack(">hhhhIhh", b["width"], b["width_img"], b["s"], b["t"],
                                b["imag"], b["height"], b["lut"]) for b in bitm)


# ------------------------------------------------------------------------ UVAN
# COMM: s32 first_frame, s32 last_frame, s32 unk8, s32 step, s32 model_id, ...
# PART: s32 count, s32 part, then count x (f32 quat[4], s16 frame, u16 flags)
# where flags bits 11..9 must be 1 ("quaternion format").

def parse_uvan_comm(data: bytes) -> dict:
    r = Reader(data)
    c = {"first": r.s32(), "last": r.s32(), "unk8": r.s32(), "step": r.s32(),
         "model": r.s32()}
    c["rest"] = r.bytes(r.remaining()).hex()
    return c


def build_uvan_comm(c: dict) -> bytes:
    w = Writer()
    for k in ("first", "last", "unk8", "step", "model"):
        w.s32(c[k])
    w.bytes(bytes.fromhex(c["rest"]))
    return w.getvalue()


def parse_uvan_part(data: bytes) -> dict:
    r = Reader(data)
    n = r.s32()
    p = {"part": r.s32(), "keys": []}
    for _ in range(n):
        q = r.f32s(4)
        p["keys"].append({"q": q, "frame": r.s16(), "flags": r.u16()})
    p["tail"] = r.bytes(r.remaining()).hex()
    return p


def build_uvan_part(p: dict) -> bytes:
    w = Writer()
    w.s32(len(p["keys"]))
    w.s32(p["part"])
    for k in p["keys"]:
        w.f32s(k["q"]); w.s16(k["frame"]); w.u16(k["flags"])
    w.bytes(bytes.fromhex(p["tail"]))
    return w.getvalue()


# UVBT texels are stored tile by tile (_uvParseUVBT): for each band of
# tile_h rows, each tile_w-wide tile's rows are contiguous.
def blit_tiles(b):
    cols = -(-b["width"] // b["tile_w"])
    rows = -(-b["height"] // b["tile_h"])
    off = 0
    for i in range(rows):
        th = min(b["tile_h"], b["height"] - i * b["tile_h"])
        for j in range(cols):
            yield i * b["tile_h"], j * b["tile_w"], th, off
            off += th * b["tile_w"]


def blit_detile(texels, b):
    """texels: flat array (texel units, stride*height) -> (height, cols*tile_w) image."""
    import numpy as np
    cols = -(-b["width"] // b["tile_w"])
    img = np.zeros((b["height"], cols * b["tile_w"]) + texels.shape[1:], texels.dtype)
    for y, x, th, off in blit_tiles(b):
        img[y:y + th, x:x + b["tile_w"]] = texels[off:off + th * b["tile_w"]].reshape((th, b["tile_w"]) + texels.shape[1:])
    return img


def blit_retile(img, b):
    import numpy as np
    n = b["stride"] * b["height"]
    out = np.zeros((n,) + img.shape[2:], img.dtype)
    for y, x, th, off in blit_tiles(b):
        blk = img[y:y + th, x:x + b["tile_w"]]
        out[off:off + th * b["tile_w"]] = blk.reshape((th * b["tile_w"],) + img.shape[2:])
    return out


def blit_swizzle(data: bytes, b) -> bytes:
    """Odd rows of each tile are stored TMEM-swizzled (32-bit halves of each
    64-bit word swapped), like UVTX. Self-inverse."""
    from ..texlayout import swizzle
    bpp = b["depth"] / 8
    row = int(b["tile_w"] * bpp)
    out = bytearray(data)
    for y, x, th, off in blit_tiles(b):
        o0, o1 = int(off * bpp), int((off + th * b["tile_w"]) * bpp)
        out[o0:o1] = swizzle(bytes(out[o0:o1]), row)
    return bytes(out)
