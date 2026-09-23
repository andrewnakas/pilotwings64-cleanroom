"""Split a Pilotwings 64 image into labelled byte streams for the taint scan.

`expressive_streams(image)` returns only the content the clean room must
regenerate (texels, mesh vertices and display lists, animation poses,
text, font glyphs, samples and note data). `all_streams(image)` returns
every decompressed chunk plus the audio segments.

Works on both retail and clean images (same parsers), with the segment
offsets taken from the image's own layout.
"""
import struct

from cleanroom import iff
from cleanroom.audio import albank, cseq
from cleanroom.binio import Writer
from . import profile as P
from .formats import engine, misc


def _files(image, seg):
    for e, raw in P.read_files(image, seg["filetable"], seg["filesys"]):
        yield e, iff.parse_form(raw)


def _vtx_expressive(vtx):
    # s, t and colour/normal bytes of each Vtx (positions are kept facts).
    return b"".join(struct.pack(">hhBBBB", *v[4:10]) for v in vtx)


def _cmd_bytes(states):
    # The compressed display lists exactly as stored.
    w = Writer()
    for st in states:
        engine._build_cmds(w, st["cmds"])
    return w.getvalue()


def expressive_streams(image, seg=None):
    seg = seg or default_segments()
    for e, f in _files(image, seg):
        label = f"{e.index:04d}:{f.type}"
        for i, c in enumerate(f.chunks):
            lab = f"{label}:{c.tag}{i}"
            if f.type == "UVTX" and c.tag == "COMM":
                yield lab + ":image", bytes.fromhex(engine.parse_uvtx(c.data)["image"])
            elif f.type == "UVBT" and c.tag == "COMM":
                yield lab + ":pixels", bytes.fromhex(misc.parse_uvbt(c.data)["pixels"])
            elif f.type == "UVFT" and c.tag == "IMAG":
                yield lab, c.data
            elif f.type == "UVMD" and c.tag == "COMM":
                m = engine.parse_uvmd(c.data)
                yield lab + ":vtx", b"".join(struct.pack(">hhhHhhBBBB", *v) for v in m["vtx"])
                yield lab + ":dl", _cmd_bytes([s for l in m["lods"] for p in l["parts"] for s in p["states"]])
            elif f.type == "UVCT" and c.tag == "COMM":
                yield lab + ":vtxattr", _vtx_expressive(engine.parse_uvct(c.data)["vtx"])
            elif f.type == "UVAN" and c.tag == "PART":
                p = misc.parse_uvan_part(c.data)
                yield lab + ":quats", b"".join(struct.pack(">4f", *k["q"]) for k in p["keys"])
            elif f.type == "ADAT" and c.tag == "DATA":
                yield lab, c.data
            elif f.type == "UPWT" and c.tag in ("NAME", "INFO", "JPTX"):
                yield lab, c.data
            elif f.type == "UVSX" and c.tag == ".TBL":
                yield lab, c.data
    yield "audio_tbl", image[seg["audio_tbl"]:seg["end"]]
    _, seqs = albank.parse_seqfile(image[seg["audio_seq"]:seg["audio_ctl"]])
    for i, s in enumerate(seqs):
        yield f"seq{i}", s[0x44:]


def all_streams(image, seg=None):
    seg = seg or default_segments()
    for e, f in _files(image, seg):
        for i, c in enumerate(f.chunks):
            yield f"{e.index:04d}:{f.type}:{c.tag}{i}", c.data
    yield "audio_seq", image[seg["audio_seq"]:seg["audio_ctl"]]
    yield "audio_ctl", image[seg["audio_ctl"]:seg["audio_tbl"]]
    yield "audio_tbl", image[seg["audio_tbl"]:seg["end"]]


def default_segments():
    return {"filetable": P.SEG_FILETABLE, "filesys": P.SEG_FILESYS,
            "audio_seq": P.SEG_AUDIO_SEQ, "audio_ctl": P.SEG_AUDIO_CTL,
            "audio_tbl": P.SEG_AUDIO_TBL, "end": P.ROM_SIZE}
