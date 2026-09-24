"""The clean room must never see retail bytes: generator modules may not
import the ROM loader or the dirty-room extractors, and the committed spec
must not contain expressive fields."""
import ast
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN = ["games/pilotwings64/generate.py", "games/pilotwings64/audio_gen.py",
         "cleanroom/gfx/strokefont.py", "cleanroom/audio/synth.py"]
FORBIDDEN = {"load_retail", "extract_spec", "audio_spec", "streams", "taint_report"}


def _imports(path):
    with open(os.path.join(ROOT, path)) as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[-1] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[-1])
            names |= {a.name for a in node.names}
    return names


def test_generators_do_not_touch_retail():
    for path in CLEAN:
        bad = _imports(path) & FORBIDDEN
        assert not bad, f"{path} imports {bad}"


def test_spec_contains_no_expressive_fields():
    spec = os.path.join(ROOT, "games/pilotwings64/spec/files")
    for name in os.listdir(spec):
        with open(os.path.join(spec, name)) as f:
            d = json.load(f)
        for c in d["chunks"]:
            ir = c.get("ir") or {}
            assert "image" not in ir and "pixels" not in ir, name
            kept = {"UVMD": "COMM", "UVCT": "COMM", "UVEN": "COMM", "UVAN": "PART"}
            if c["tag"] == kept.get(d["type"]):
                # Geometry + coarse colour scope: kept, and declared as facts.
                assert c["prov"] == "fact", name
            if d["type"] == "UVTX" and c["tag"] == "COMM":
                for dg in ir["digest"]:
                    assert set(dg) <= {"start", "w", "h", "vw", "vh", "grid", "alpha2"}, name
                    assert len(dg["grid"]) <= 16, name
            if (d["type"], c["tag"]) in (("ADAT", "DATA"), ("UVFT", "IMAG")):
                assert set(c) <= {"tag", "compressed", "prov", "size"}, name
            if d["type"] == "UVSX":
                assert set(c) <= {"tag", "compressed", "prov", "size", "zeros"}, name


def test_audio_spec_has_no_samples_or_notes():
    with open(os.path.join(ROOT, "games/pilotwings64/spec/audio.json")) as f:
        a = json.load(f)
    # Scope "SFX envelopes + melodies": note events are kept, sample data is
    # not (no codebooks, no ADPCM state, no raw waves -- only descriptors).
    text = json.dumps(a)
    assert '"book"' not in text and '"state"' not in text and '"samples"' not in text
    for bank in ("music", "sfx"):
        for inst in a[bank]["insts"] + [a[bank]["percussion"]]:
            for snd in (inst or {}).get("sounds", []):
                assert set(snd["desc"]) == {"frames"}
                for fr in snd["desc"]["frames"]:
                    assert set(fr) <= {"f0", "h", "db", "rms"} and len(fr.get("db", [])) <= 16
