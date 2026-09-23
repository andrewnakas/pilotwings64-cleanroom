"""Structural checks on the clean image using our own parsers."""
import json
import os

from cleanroom import iff
from cleanroom.audio import albank, cseq
from games.pilotwings64 import profile as P
from games.pilotwings64.formats import engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "games/pilotwings64/spec")


def test_slots_match_spec(clean_image):
    with open(os.path.join(SPEC, "manifest.json")) as f:
        manifest = json.load(f)
    ents = [e for e in P.read_filetable(clean_image)]
    assert [(e.tag, e.kind_index) for e in ents] == [(m["tag"], m["id"]) for m in manifest["files"]]
    for e, raw in P.read_files(clean_image):
        f = iff.parse_form(raw)
        assert f.type == e.tag
        if f.type == "UVTX":
            t = engine.parse_uvtx(f.first("COMM").data)
            with open(os.path.join(SPEC, "files", manifest["files"][e.index]["file"])) as fh:
                spec = json.load(fh)
            sir = [c for c in spec["chunks"] if c["tag"] == "COMM"][0]["ir"]
            assert len(t["image"]) // 2 == sir["image_size"]
            assert (t["width"], t["height"], t["dlist"]) == (sir["width"], sir["height"], sir["dlist"])


def test_audio_segments_parse(clean_image):
    _, seqs = albank.parse_seqfile(clean_image[P.SEG_AUDIO_SEQ:P.SEG_AUDIO_CTL])
    assert len(seqs) == 31
    for s in seqs:
        _, tracks = cseq.decode(s)
        assert all(ev[-1][1] == "end" for ev in tracks.values())
    bank = albank.parse_bankfile(clean_image[P.SEG_AUDIO_CTL:P.SEG_AUDIO_TBL])["banks"][0]
    assert bank["rate"] == 22050
