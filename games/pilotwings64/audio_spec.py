"""DIRTY ROOM (audio).

Scope chosen by the user ("SFX envelopes + melodies"):
  * both sound banks keep their structure (instruments, key maps, envelopes,
    pan/volume, loop points) as facts;
  * every sample is reduced to a coarse outline (cleanroom.audio.descriptor:
    per frame f0, harmonicity, 16-band envelope in dB) -- no sample data;
  * music sequences keep their events (notes, controllers, tempo, loops),
    which the clean side re-encodes and plays on resynthesized instruments.
"""
from cleanroom import iff
from cleanroom.audio import albank, cseq, vadpcm, descriptor
import numpy as np
from . import profile as P


def _frames(w):
    if w["type"] == albank.ADPCM:
        return w["len"] // 9 * 16
    return w["len"] // 2


def _loop(w):
    lp = w.get("loop")
    if not lp:
        return None
    return {"start": lp["start"], "end": lp["end"], "count": lp["count"]}


def _decode(w, tbl):
    data = tbl[w["base"]:w["base"] + w["len"]]
    if w["type"] == albank.ADPCM and w.get("book"):
        return vadpcm.decode(data, w["book"], _frames(w))
    return np.frombuffer(data[: len(data) // 2 * 2], ">i2")


def _inst(i, tbl, rate, cache):
    if i is None:
        return None
    sounds = []
    for s in i["sounds"]:
        w = s["wave"]
        key = w["_id"]
        if key not in cache:
            cache[key] = descriptor.describe(_decode(w, tbl), rate)
        sounds.append({"env": {k: v for k, v in s["env"].items() if k != "_id"},
                       "keymap": {k: v for k, v in s["keymap"].items() if k != "_id"},
                       "pan": s["pan"], "volume": s["volume"],
                       "frames": _frames(w), "loop": _loop(w), "wave_id": key, "desc": cache[key]})
    return {"volume": i["volume"], "pan": i["pan"], "priority": i["priority"],
            "trem": i["trem"], "vib": i["vib"], "bend": i["bend"], "sounds": sounds}


def _bank(bank, tbl):
    cache = {}
    rate = bank["rate"]
    return {"rate": rate,
            "percussion": _inst(bank["percussion"], tbl, rate, cache),
            "insts": [_inst(i, tbl, rate, cache) for i in bank["insts"]]}


def extract_audio(rom: bytes) -> dict:
    out = {}
    _, seqs = albank.parse_seqfile(rom[P.SEG_AUDIO_SEQ:P.SEG_AUDIO_CTL])
    out["seqs"] = []
    for s in seqs:
        div, tracks = cseq.decode(s)
        end = max((ev[-1][0] for ev in tracks.values() if ev), default=0)
        tempos = [e[2] for ev in tracks.values() for e in ev if e[1] == "tempo"]
        loops = sorted({e[2] for ev in tracks.values() for e in ev if e[1] == "loopend"})
        out["seqs"].append({"division": div, "ticks": end,
                            "tempo": tempos[0] if tempos else 500000,
                            "loop_counts": loops, "tracks": sorted(tracks),
                            # melodies kept (user scope): events without "end"
                            "events": {str(t): [list(e) for e in ev if e[1] != "end"] for t, ev in tracks.items()}})
    music = albank.parse_bankfile(rom[P.SEG_AUDIO_CTL:P.SEG_AUDIO_TBL])["banks"][0]
    out["music"] = _bank(music, rom[P.SEG_AUDIO_TBL:])
    out["music"]["slots"] = len(music["insts"])
    for e, raw in P.read_files(rom):
        if e.tag == "UVSX":
            f = iff.parse_form(raw)
            d = {c.tag: c.data for c in f.chunks}
            sb = albank.parse_bankfile(d[".CTL"])["banks"][0]
            out["sfx"] = _bank(sb, d[".TBL"])
    return out
