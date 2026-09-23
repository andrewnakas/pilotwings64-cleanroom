"""Texel layout of a UVTX image: which byte ranges hold which render tile.

Shared by the extractor (to measure) and the generator (to fill), so both
see exactly the same regions: tiles sorted by TMEM address, each spanning to
the next tile's address (or the image end), rows of `line` 64-bit words.
"""
import struct

from cleanroom.gfx import gbi, texfmt


def tex_tiles(ir):
    """Render tiles incl. those sized at runtime (fall back to header dims)."""
    tiles = {}
    for c in ir["dlist"]:
        w0, w1 = struct.unpack(">II", bytes.fromhex(c))
        op = w0 >> 24
        if op == gbi.G_SETTILE:
            t = (w1 >> 24) & 7
            if t == 7:
                continue
            tiles.setdefault(t, {}).update(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3,
                                           line=(w0 >> 9) & 0x1FF, tmem=w0 & 0x1FF)
        elif op == gbi.G_SETTILESIZE:
            t = (w1 >> 24) & 7
            uls, ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
            lrs, lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
            tiles.setdefault(t, {}).update(width=((lrs - uls) >> 2) + 1, height=((lrt - ult) >> 2) + 1)
    out = []
    for t in sorted(tiles):
        d = tiles[t]
        if "fmt" not in d:
            continue
        d.setdefault("width", ir["width"])
        d.setdefault("height", ir["height"])
        d["tile"] = t
        out.append(d)
    return out


def regions(ir, size):
    """Yield (tile, start, end, stride, texels_w, rows) for each distinct TMEM
    region of an image of `size` bytes."""
    tiles = sorted(tex_tiles(ir), key=lambda t: t["tmem"])
    seen = set()
    for i, t in enumerate(tiles):
        start = t["tmem"] * 8
        if start >= size or start in seen:
            continue
        seen.add(start)
        nxt = [u["tmem"] * 8 for u in tiles if u["tmem"] * 8 > start]
        end = min(min(nxt) if nxt else size, size)
        bits = texfmt.BITS[t["siz"]]
        stride = t["line"] * 8 or max(8, (t["width"] * bits + 7) // 8)
        texels_w = stride * 8 // bits
        rows = max(1, -(-(end - start) // stride))
        yield t, start, end, stride, texels_w, rows


def has_alpha(fmt):
    return fmt in (texfmt.RGBA, texfmt.IA)
