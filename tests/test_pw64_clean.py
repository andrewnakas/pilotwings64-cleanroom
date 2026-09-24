"""Structural checks on the clean image using our own parsers."""
import json
import os

from cleanroom import iff
from cleanroom.audio import albank, cseq
from games.pilotwings64 import profile as P
from games.pilotwings64.formats import engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "games/pilotwings64/spec")


def test_slots_match_spec(clean_image, clean_segments):
    with open(os.path.join(SPEC, "manifest.json")) as f:
        manifest = json.load(f)
    ft, fs = clean_segments["filetable"], clean_segments["filesys"]
    ents = [e for e in P.read_filetable(clean_image, ft)]
    assert [(e.tag, e.kind_index) for e in ents] == [(m["tag"], m["id"]) for m in manifest["files"]]
    for e, raw in P.read_files(clean_image, ft, fs):
        f = iff.parse_form(raw)
        assert f.type == e.tag
        if f.type == "UVTX":
            t = engine.parse_uvtx(f.first("COMM").data)
            with open(os.path.join(SPEC, "files", manifest["files"][e.index]["file"])) as fh:
                spec = json.load(fh)
            sir = [c for c in spec["chunks"] if c["tag"] == "COMM"][0]["ir"]
            assert len(t["image"]) // 2 == sir["image_size"]
            assert (t["width"], t["height"], t["dlist"]) == (sir["width"], sir["height"], sir["dlist"])


def test_audio_segments_parse(clean_image, clean_segments):
    seg = clean_segments
    _, seqs = albank.parse_seqfile(clean_image[seg["audio_seq"]:seg["audio_ctl"]])
    assert len(seqs) == 31
    for s in seqs:
        _, tracks = cseq.decode(s)
        assert all(ev[-1][1] == "end" for ev in tracks.values())
    bank = albank.parse_bankfile(clean_image[seg["audio_ctl"]:seg["audio_tbl"]])["banks"][0]
    assert bank["rate"] == 22050
