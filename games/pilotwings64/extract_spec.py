"""DIRTY ROOM: read a retail ROM and write the clean-room spec.

This is the only module (besides round-trip tests) allowed to see retail
bytes. For every file it keeps
  * slot metadata  - structure the engine code depends on (counts, IDs,
                     part hierarchies, texture formats/dimensions, bounds),
  * facts          - functional gameplay data the user chose to keep
                     (terrain/contour geometry positions, task and level
                     placements, paths, demo recordings, lookup tables),
and drops expressive content: texels, UVs, vertex colours, model meshes,
animation poses, text, fonts glyphs, audio samples and music.

Every chunk in the spec carries "prov": "slot" | "fact" | "gen" so the taint
report can separate kept facts from generated content.

Usage: python -m games.pilotwings64.extract_spec <rom> [spec_dir]
"""
import json
import os
import sys

from cleanroom import iff
from cleanroom.rom import load_retail
from cleanroom.gfx import gbi
from . import profile as P
from .formats import engine, misc
from .audio_spec import extract_audio

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SPEC = os.path.join(HERE, "spec")

FACT_USER_TAGS = ("UPWL", "SPTH", "3VUE", "PDAT")
TASK_TEXT_TAGS = ("NAME", "INFO", "JPTX")


def _pad(c):
    return {"tag": c.tag, "prov": "slot", "zeros": len(c.data), "compressed": c.compressed}


def _vtx_positions(vtx):
    return [[v[0], v[1], v[2], v[3]] for v in vtx]


def _bbox(points):
    if not points:
        return None
    xs, ys, zs = zip(*points)
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def _state_vertices(st, vtx):
    """Positions referenced by one compressed display list, in load order."""
    used = []
    for c in st["cmds"]:
        if c[0] == "vtx":
            used.extend(range(c[1], c[1] + c[2]))
    return [vtx[i][:3] for i in used if i < len(vtx)]


def clean_uvtx(ir):
    dl = [bytes.fromhex(g) for g in ir["dlist"]]
    out = {k: v for k, v in ir.items() if k != "image"}
    out["image_size"] = len(ir["image"]) // 2
    out["tiles"] = gbi.render_tiles(dl)
    out["timg"] = gbi.settimg_list(dl)
    return out


def clean_uvmd(ir):
    """Keep the skeleton, transforms, bounds and render states; drop meshes."""
    vtx = ir["vtx"]
    out = {k: ir[k] for k in ("transparent", "mtx", "joints", "unk1C", "unk20",
                              "unk24", "keys", "tail")}
    out["lods"] = []
    for lod in ir["lods"]:
        l2 = {"billboard": lod["billboard"], "radius": lod["radius"], "parts": []}
        for part in lod["parts"]:
            p2 = {"unk5": part["unk5"], "unk6": part["unk6"], "states": []}
            for st in part["states"]:
                pts = _state_vertices(st, vtx)
                p2["states"].append({"state": st["state"], "bbox": _bbox(pts),
                                     "tris": st["tris"]})
            l2["parts"].append(p2)
        out["lods"].append(l2)
    return out


def clean_uvct(ir):
    """Contours are terrain: positions and topology are kept as facts;
    texture coordinates and vertex colours are regenerated."""
    out = dict(ir)
    out["vtx"] = _vtx_positions(ir["vtx"])
    return out


def clean_uven(ir):
    out = {k: v for k, v in ir.items() if k not in ("screen", "fog", "unused")}
    return out


def clean_uvan_part(ir):
    return {"part": ir["part"], "tail": ir["tail"],
            "keys": [{"frame": k["frame"], "flags": k["flags"] & 0xFF00} for k in ir["keys"]]}


def clean_uvbt(ir):
    return {k: v for k, v in ir.items() if k != "pixels"}


FULL_FACT = {"UVSY": engine.parse_uvsy, "UVLV": engine.parse_uvlv,
             "UVTP": engine.parse_uvtp, "UVSQ": engine.parse_uvsq,
             "UVTR": engine.parse_uvtr}


def clean_chunk(ftype, c, index_in_file):
    tag = c.tag
    base = {"tag": tag, "compressed": c.compressed}
    if tag == "PAD ":
        return _pad(c)
    if ftype in FULL_FACT and tag == "COMM":
        return {**base, "prov": "fact", "ir": FULL_FACT[ftype](c.data)}
    if ftype == "UVTX" and tag == "COMM":
        return {**base, "prov": "slot", "ir": clean_uvtx(engine.parse_uvtx(c.data))}
    if ftype == "UVMD" and tag == "COMM":
        return {**base, "prov": "slot", "ir": clean_uvmd(engine.parse_uvmd(c.data))}
    if ftype == "UVCT" and tag == "COMM":
        return {**base, "prov": "fact", "ir": clean_uvct(engine.parse_uvct(c.data))}
    if ftype == "UVEN" and tag == "COMM":
        return {**base, "prov": "slot", "ir": clean_uven(engine.parse_uven(c.data))}
    if ftype == "UVBT" and tag == "COMM":
        return {**base, "prov": "slot", "ir": clean_uvbt(misc.parse_uvbt(c.data))}
    if ftype == "UVAN" and tag == "COMM":
        return {**base, "prov": "slot", "ir": misc.parse_uvan_comm(c.data)}
    if ftype == "UVAN" and tag == "PART":
        return {**base, "prov": "slot", "ir": clean_uvan_part(misc.parse_uvan_part(c.data))}
    if ftype == "UVFT":
        if tag == "STRG":
            # The character set a font covers is a functional lookup table.
            return {**base, "prov": "fact", "ascii": c.data.hex()}
        if tag == "FRMT":
            return {**base, "prov": "slot", "hex": c.data.hex()}
        if tag == "BITM":
            return {**base, "prov": "slot", "bitm": misc.parse_bitm(c.data)}
        if tag == "IMAG":
            return {**base, "prov": "slot", "size": len(c.data)}
    if ftype == "ADAT":
        if tag == "SIZE":
            return {**base, "prov": "slot", "hex": c.data.hex()}
        if tag == "NAME":
            # String keys looked up by textGetDataByName: functional.
            return {**base, "prov": "fact", "hex": c.data.hex()}
        if tag == "DATA":
            return {**base, "prov": "slot", "size": len(c.data)}
    if ftype == "UPWT":
        if tag in TASK_TEXT_TAGS:
            return {**base, "prov": "slot", "size": len(c.data)}
        return {**base, "prov": "fact", "hex": c.data.hex()}
    if ftype in FACT_USER_TAGS:
        return {**base, "prov": "fact", "hex": c.data.hex()}
    if ftype == "UVSX":
        # Sound bank: handled by the audio extractor (M3 audio step).
        return {**base, "prov": "slot", "size": len(c.data)}
    if ftype == "UVLT":
        return {**base, "prov": "fact", "hex": c.data.hex()}
    raise ValueError(f"no cleaning rule for {ftype}/{tag}")


def extract(rom: bytes, spec_dir: str = DEFAULT_SPEC):
    files_dir = os.path.join(spec_dir, "files")
    os.makedirs(files_dir, exist_ok=True)
    manifest = {"game": P.GAME_ID, "retail_sha1": P.RETAIL_SHA1, "files": []}
    for e, raw in P.read_files(rom):
        form = iff.parse_form(raw)
        chunks = [clean_chunk(form.type, c, i) for i, c in enumerate(form.chunks)]
        name = f"{e.index:04d}_{e.tag.strip()}.json"
        with open(os.path.join(files_dir, name), "w") as f:
            json.dump({"type": form.type, "chunks": chunks}, f, separators=(",", ":"))
        manifest["files"].append({"index": e.index, "tag": e.tag, "id": e.kind_index,
                                  "file": name})
    with open(os.path.join(spec_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(spec_dir, "audio.json"), "w") as f:
        json.dump(extract_audio(rom), f, indent=1)
    return manifest


def main(argv):
    rom = load_retail(argv[1])
    spec_dir = argv[2] if len(argv) > 2 else DEFAULT_SPEC
    m = extract(rom, spec_dir)
    print(f"wrote {len(m['files'])} file specs to {spec_dir}")


if __name__ == "__main__":
    main(sys.argv)
