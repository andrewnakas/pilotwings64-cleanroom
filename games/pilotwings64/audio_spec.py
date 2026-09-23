"""DIRTY ROOM (audio): keep sound-bank structure and sequence timing only.

Kept per SFX sound: envelope, key map, pan/volume, frame count and loop
points (they decide how the game's code plays each effect). Kept per music
sequence: division, length, tempo, loop counts and which tracks exist.
Dropped: every sample, every note, the music instrument set.
"""
from cleanroom import iff
from cleanroom.audio import albank, cseq
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


def _inst(i):
    if i is None:
        return None
    return {"volume": i["volume"], "pan": i["pan"], "priority": i["priority"],
            "trem": i["trem"], "vib": i["vib"], "bend": i["bend"],
            "sounds": [{"env": {k: v for k, v in s["env"].items() if k != "_id"},
                        "keymap": {k: v for k, v in s["keymap"].items() if k != "_id"},
                        "pan": s["pan"], "volume": s["volume"],
                        "frames": _frames(s["wave"]), "loop": _loop(s["wave"])}
                       for s in i["sounds"]]}


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
                            "loop_counts": loops, "tracks": sorted(tracks)})
    music = albank.parse_bankfile(rom[P.SEG_AUDIO_CTL:P.SEG_AUDIO_TBL])["banks"][0]
    out["music"] = {"rate": music["rate"], "slots": len(music["insts"])}
    for e, raw in P.read_files(rom):
        if e.tag == "UVSX":
            f = iff.parse_form(raw)
            d = {c.tag: c.data for c in f.chunks}
            sb = albank.parse_bankfile(d[".CTL"])["banks"][0]
            out["sfx"] = {"rate": sb["rate"],
                          "percussion": _inst(sb["percussion"]),
                          "insts": [_inst(i) for i in sb["insts"]]}
    return out
