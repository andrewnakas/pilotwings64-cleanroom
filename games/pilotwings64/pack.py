"""Assemble generated assets into a clean ROM image.

Layout (compat mode): the retail segment offsets, so an executable linked
against the retail layout (the stock recomp) can load the image:
  0x000000 header (written from scratch)
  0x001000 code segments (supplied by the build: --code <bin>, never committed)
  0x0DE720 UVRM/TABL file table
  0x0DF5B0 filesystem
  0x618B70 audio_seq, 0x62D460 audio_ctl, 0x6314D0 audio_tbl

Usage:
  python -m games.pilotwings64.pack --out build/pilotwings64.clean.z64 \
      [--code build/code.bin | --code-from-retail <rom>]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time

from cleanroom import iff, rom as romlib
from . import profile as P
from .generate import Spec, generate, DEFAULT_SPEC
from .audio_gen import generate_audio

CODE_START = 0x1000
CODE_END = P.SEG_FILETABLE


class PackError(Exception):
    pass


def build_filesystem(files, audio):
    """files: generate() output. Returns (table bytes, filesystem bytes, layout)."""
    blobs = []
    layout = []
    for m, ftype, chunks in files:
        if ftype == "UVSX":
            built = []
            for c in chunks:
                if isinstance(c, dict):
                    data = audio["sfx_ctl"] if c["tag"] == ".CTL" else audio["sfx_tbl"]
                    built.append(iff.Chunk(c["tag"], data, c["compressed"]))
                else:
                    built.append(c)
            chunks = built
        form = iff.Form(ftype, chunks)
        blob = iff.build_form(form)
        blobs.append((m["tag"], blob))
    table = P.build_table((t, len(b)) for t, b in blobs)
    fs = bytearray()
    for (tag, b), (m, ftype, chunks) in zip(blobs, files):
        layout.append({"index": m["index"], "tag": tag, "offset": len(fs), "size": len(b)})
        fs += b
    return table, bytes(fs), layout


def build_filetable(table: bytes) -> bytes:
    form = iff.Form("UVRM", [iff.Chunk("PAD ", bytes(4)), iff.Chunk("PAD ", bytes(4)),
                             iff.Chunk("TABL", table, True)])
    return iff.build_form(form)


def _place(img, off, data, limit, what):
    if len(data) > limit:
        raise PackError(f"{what} is {len(data):#x} bytes, slot holds {limit:#x}")
    img[off:off + len(data)] = data


def pack(spec_dir=DEFAULT_SPEC, code: bytes = None, log=print):
    t0 = time.time()
    spec = Spec(spec_dir)
    log(f"spec loaded ({len(spec.files)} files) {time.time() - t0:.1f}s")
    files = generate(spec)
    log(f"graphics/text generated {time.time() - t0:.1f}s")
    audio = generate_audio(spec_dir)
    log(f"audio generated {time.time() - t0:.1f}s")
    table, fs, layout = build_filesystem(files, audio)
    ft = build_filetable(table)
    log(f"filesystem {len(fs):#x} bytes, table {len(ft):#x} {time.time() - t0:.1f}s")

    img = bytearray(P.ROM_SIZE)
    img[0:0x40] = romlib.build_header("PW64 CLEANROOM", b"PW", entry=0x80200050)
    if code is not None:
        _place(img, CODE_START, code, CODE_END - CODE_START, "code")
    _place(img, P.SEG_FILETABLE, ft, P.SEG_FILESYS - P.SEG_FILETABLE, "file table")
    _place(img, P.SEG_FILESYS, fs, P.SEG_AUDIO_SEQ - P.SEG_FILESYS, "filesystem")
    _place(img, P.SEG_AUDIO_SEQ, audio["seq"], P.SEG_AUDIO_CTL - P.SEG_AUDIO_SEQ, "audio_seq")
    _place(img, P.SEG_AUDIO_CTL, audio["ctl"], P.SEG_AUDIO_TBL - P.SEG_AUDIO_CTL, "audio_ctl")
    _place(img, P.SEG_AUDIO_TBL, audio["tbl"], P.ROM_SIZE - P.SEG_AUDIO_TBL, "audio_tbl")
    romlib.finalize_crc(img)
    report = {"layout": layout, "filesystem_size": len(fs),
              "segments": {"filetable": P.SEG_FILETABLE, "filesys": P.SEG_FILESYS,
                           "audio_seq": P.SEG_AUDIO_SEQ, "audio_ctl": P.SEG_AUDIO_CTL,
                           "audio_tbl": P.SEG_AUDIO_TBL},
              "has_code": code is not None}
    return bytes(img), report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=DEFAULT_SPEC)
    ap.add_argument("--out", default=os.path.join("build", "pilotwings64.clean.z64"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--code", help="code segment binary from our own ELF build")
    g.add_argument("--code-from-retail",
                   help="DEV ONLY: copy the code region from a retail ROM for asset-swap tests; "
                        "the output then contains retail code and must not be shared")
    a = ap.parse_args(argv)
    code = None
    if a.code:
        with open(a.code, "rb") as f:
            code = f.read()
    elif a.code_from_retail:
        code = romlib.load_retail(a.code_from_retail)[CODE_START:CODE_END]
    img, report = pack(a.spec, code)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(img)
    report["code_source"] = "retail (dev only)" if a.code_from_retail else ("build" if a.code else "none")
    report["sha1"] = hashlib.sha1(img).hexdigest()
    with open(os.path.splitext(a.out)[0] + ".layout.json", "w") as f:
        json.dump(report, f, indent=1)
    print(f"wrote {a.out} sha1={report['sha1']} code={report['code_source']}")


if __name__ == "__main__":
    main()
