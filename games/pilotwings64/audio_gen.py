"""CLEAN ROOM (audio): new instruments, effects and music from spec/audio.json.

* Music bank: our own five instruments (lead, bass, pad, pluck, drum kit),
  RAW16 samples, seamless single-period loops.
* Sequences: procedurally composed, one per slot, matching the slot's
  tempo and length; slots that looped keep looping forever.
* SFX bank: same instrument/sound structure, envelopes, key maps and loop
  points as the slot requires; waveforms synthesised per sound.
"""
import hashlib
import json
import math
import os

import numpy as np

from cleanroom.audio import albank, cseq, synth, vadpcm

HERE = os.path.dirname(os.path.abspath(__file__))
RAW16 = albank.RAW16


def _seed(*parts):
    return int.from_bytes(hashlib.sha1(repr(parts).encode()).digest()[:8], "big")


class Table:
    """Accumulates RAW16 sample data for a .tbl."""

    def __init__(self):
        self.buf = bytearray()

    def add(self, pcm: bytes) -> int:
        while len(self.buf) % 16:
            self.buf.append(0)
        off = len(self.buf)
        self.buf += pcm
        return off


def _wave(tbl, samples, loop=None):
    pcm = synth.to_pcm16be(samples)
    w = {"base": tbl.add(pcm), "len": len(pcm), "type": RAW16, "flags": 0,
         "loop": None, "book": None}
    if loop:
        w["loop"] = dict(loop)
    return w


_BOOK = vadpcm.make_book()


def _wave_adpcm(tbl, samples, loop=None):
    x = np.clip(np.asarray(samples) * 0.8, -1, 1) * 32767
    data, book, dec = vadpcm.encode(x.astype(np.int64), _BOOK)
    w = {"base": tbl.add(data), "len": len(data), "type": albank.ADPCM, "flags": 0,
         "loop": None, "book": book}
    if loop:
        start = loop["start"] & ~15
        w["loop"] = {"start": start, "end": loop["end"], "count": loop["count"],
                     "state": vadpcm.loop_state(dec, start)}
    return w


def _env(attack_us, decay_us, release_us, attack_vol=127, decay_vol=110):
    return {"attack": attack_us, "decay": decay_us, "release": release_us,
            "attack_vol": attack_vol, "decay_vol": decay_vol}


def _keymap(kmin=0, kmax=127, base=60, detune=0):
    return {"vel_min": 0, "vel_max": 127, "key_min": kmin, "key_max": kmax,
            "key_base": base, "detune": detune}


def _inst(sounds, volume=110, pan=64, priority=5):
    return {"volume": volume, "pan": pan, "priority": priority, "flags": 0,
            "trem": [0, 0, 0, 0], "vib": [0, 0, 0, 0], "bend": 200, "sounds": sounds}


def _tonal(tbl, rate, harmonics, key=60, period=84, cycles=40, seed=0):
    """A looped tone: `period` samples per cycle; keyBase/detune describe
    the resulting pitch so the synth transposes correctly."""
    freq = rate / period
    midi = 69 + 12 * math.log2(freq / 440.0)
    base = int(round(midi))
    detune = int(round((base - midi) * 100))
    x = synth.periodic(period, harmonics, cycles, seed)
    loop = {"start": period * 4, "end": period * cycles, "count": 0xFFFFFFFF}
    return _wave(tbl, x, loop), base, detune


# ----------------------------------------------------------------- music

MUSIC_PROGRAMS = ("lead", "bass", "pad", "pluck", "drums")


def build_music_bank(rate):
    tbl = Table()
    insts = []
    specs = {
        "lead": ([1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11], 84, _env(8000, 400000, 90000, 127, 100)),
        "bass": ([1, 0.5, 0.33, 0.25, 0.2, 0.16], 168, _env(4000, 300000, 60000, 127, 110)),
        "pad": ([1, 0.2, 0.1, 0.05], 84, _env(250000, 900000, 400000, 110, 100)),
        "pluck": ([1, 0.6, 0.4, 0.3, 0.2, 0.15, 0.1], 84, _env(2000, 250000, 120000, 127, 40)),
    }
    for name in MUSIC_PROGRAMS[:4]:
        harm, period, env = specs[name]
        w, base, det = _tonal(tbl, rate, harm, period=period, seed=_seed(name))
        insts.append(_inst([{"env": env, "keymap": _keymap(0, 127, base, det), "wave": w,
                             "pan": 64, "volume": 110, "flags": 0}]))
    # Drum kit: kick (35-36), snare (37-40), hats (41-127).
    n = int(rate * 0.25)
    kick = synth.sweep(n, rate, 140, 45) * synth.env_ad(n, 20, 18.0 / n)
    sn = int(rate * 0.2)
    snare = (0.6 * synth.noise(sn, 7) + 0.4 * synth.sweep(sn, rate, 220, 180)) * synth.env_ad(sn, 10, 22.0 / sn)
    hn = int(rate * 0.06)
    hat = synth.highpass(synth.noise(hn, 11), 0.6) * synth.env_ad(hn, 5, 40.0 / hn)
    drums = []
    for (lo, hi, key, x) in ((0, 36, 36, kick), (37, 40, 38, snare), (41, 127, 42, hat)):
        drums.append({"env": _env(1000, 1000000, 50000, 127, 127), "keymap": _keymap(lo, hi, key, 0),
                      "wave": _wave(tbl, x), "pan": 64, "volume": 110, "flags": 0})
    insts.append(_inst(drums, volume=100))
    bank = {"flags": 0, "pad": 0, "rate": rate, "percussion": None, "insts": insts}
    return albank.build_bankfile({"revision": albank.AL_BANK_VERSION, "banks": [bank]}), bytes(tbl.buf)


SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10]}
PROGRESSIONS = [[0, 4, 5, 3], [0, 3, 4, 4], [0, 5, 3, 4], [0, 3, 0, 4]]


def compose(slot, idx, division=96):
    """One sequence: tempo/length from the slot, content from a seeded
    composer (common progressions, scale-walk melody, simple drum groove)."""
    rng = np.random.default_rng(_seed("seq", idx))
    tempo = int(slot["tempo"])
    beats = max(4, int(round(slot["ticks"] / max(1, slot["division"]))))
    loops = bool(slot["loop_counts"])
    mode = "major" if rng.random() < 0.7 else "minor"
    scale = SCALES[mode]
    root = 48 + int(rng.integers(0, 12))
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    q = division
    ev = {0: [(0, "tempo", tempo)]}
    ch_prog = {0: 0, 1: 1, 2: 2, 3: 3, 9: 4}
    for ch, p in ch_prog.items():
        ev.setdefault(ch, [])
        ev[ch] += [(0, "midi", 0xC0 | ch, p),
                   (0, "midi", 0xB0 | ch, 7, {0: 96, 1: 100, 2: 70, 3: 80, 9: 90}[ch]),
                   (0, "midi", 0xB0 | ch, 10, {0: 64, 1: 60, 2: 70, 3: 50, 9: 64}[ch])]

    def degree(d, octave=0):
        return root + 12 * (octave + d // 7) + scale[d % 7]

    short = beats <= 16 and not loops
    if short:
        # Jingle: rising arpeggio of the tonic chord, then a held tonic.
        step = max(1, beats // 8)
        t = 0
        for d in (0, 2, 4, 7, 9, 11):
            if t >= (beats - 2) * q:
                break
            ev[0].append((t, "note", 0, degree(d, 1), 100, int(q * step * 0.9)))
            ev[3].append((t, "note", 3, degree(d, 0), 80, int(q * step * 0.9)))
            t += q * step
        hold = max(q, beats * q - t)
        ev[2].append((t, "note", 2, degree(0, 0), 90, hold))
        ev[2].append((t, "note", 2, degree(2, 0), 90, hold))
        ev[2].append((t, "note", 2, degree(4, 0), 90, hold))
        ev[1].append((t, "note", 1, degree(0, -1), 100, hold))
    else:
        if loops:
            for ch in ev:
                ev[ch].append((0, "loopstart"))
        bars = beats // 4
        melody_deg = 7
        for bar in range(bars):
            chord = prog[bar % len(prog)]
            t0 = bar * 4 * q
            for d in (0, 2, 4):
                ev[2].append((t0, "note", 2, degree(chord + d, 0), 70, 4 * q - 4))
            ev[1].append((t0, "note", 1, degree(chord, -1), 105, 2 * q - 8))
            ev[1].append((t0 + 2 * q, "note", 1, degree(chord + (4 if bar % 2 else 0), -1), 95, 2 * q - 8))
            for b in range(4):
                ev[9].append((t0 + b * q, "note", 9, 36 if b % 2 == 0 else 38, 100, q // 2))
                ev[9].append((t0 + b * q + q // 2, "note", 9, 42, 70, q // 4))
            # Melody: eighth/quarter rhythm, steps toward chord tones.
            t = t0
            while t < t0 + 4 * q:
                dur = q if rng.random() < 0.5 else q // 2
                if rng.random() < 0.15:
                    t += dur
                    continue
                target = chord + 7 + int(rng.choice([0, 2, 4]))
                melody_deg += int(np.sign(target - melody_deg)) if rng.random() < 0.6 else int(rng.integers(-1, 2))
                melody_deg = max(3, min(14, melody_deg))
                ev[0].append((t, "note", 0, degree(melody_deg, 0), 95, int(dur * 0.9)))
                ev[3].append((t, "note", 3, degree(chord + 7, 0) if t % (2 * q) == 0 else degree(chord + 9, 0),
                              60, int(dur * 0.8)))
                t += dur
        end = bars * 4 * q
        if loops:
            for ch in ev:
                ev[ch].append((end, "loopend", 0xFF))
    return cseq.encode({ch: e for ch, e in ev.items() if e}, division)


# ------------------------------------------------------------------- SFX

def _sfx_samples(i, s, rate):
    """A graybox effect of the slot's exact length, shaped by its loop and
    key map (looped slots become continuous hums at the mapped pitch)."""
    frames = max(16, s["frames"])
    rng = np.random.default_rng(_seed("sfx", i))
    loop = s["loop"]
    if loop:
        period = max(8, int(rate / (110 * 2 ** ((rng.integers(0, 12)) / 12))))
        harm = [1] + list(rng.uniform(0, 0.6, 7))
        x = synth.periodic(period, harm, frames // period + 1, _seed("sfxp", i))[:frames]
        grit = synth.noise(frames, _seed("grit", i), 0.8) * 0.15
        return x * 0.85 + grit
    kind = rng.integers(0, 3)
    dur = frames
    if kind == 0:
        x = synth.sweep(dur, rate, rng.uniform(300, 900), rng.uniform(150, 1500))
    elif kind == 1:
        x = synth.noise(dur, _seed("sfxn", i), float(rng.uniform(0.3, 0.95)))
    else:
        x = synth.periodic(int(rng.integers(20, 120)), [1, 0.5, 0.3], dur // 20 + 2, _seed("sfxb", i))[:dur]
    return x * synth.env_ad(dur, min(200, dur // 10), 4.0 / dur)


def build_sfx_bank(sfx):
    tbl = Table()
    rate = sfx["rate"]

    def inst(i, spec):
        if spec is None:
            return None
        sounds = []
        for k, s in enumerate(spec["sounds"]):
            x = _sfx_samples((i, k), s, rate)
            loop = None
            if s["loop"]:
                loop = {"start": s["loop"]["start"], "end": min(s["loop"]["end"], len(x)),
                        "count": s["loop"]["count"]}
            sounds.append({"env": dict(s["env"]), "keymap": dict(s["keymap"]),
                           "wave": _wave_adpcm(tbl, x, loop), "pan": s["pan"],
                           "volume": s["volume"], "flags": 0})
        return {"volume": spec["volume"], "pan": spec["pan"], "priority": spec["priority"],
                "flags": 0, "trem": spec["trem"], "vib": spec["vib"], "bend": spec["bend"],
                "sounds": sounds}

    bank = {"flags": 0, "pad": 0, "rate": rate,
            "percussion": inst("perc", sfx["percussion"]),
            "insts": [inst(i, s) for i, s in enumerate(sfx["insts"])]}
    return albank.build_bankfile({"revision": albank.AL_BANK_VERSION, "banks": [bank]}), bytes(tbl.buf)


def _cache_key(spec_dir):
    h = hashlib.sha1()
    with open(os.path.join(spec_dir, "audio.json"), "rb") as f:
        h.update(f.read())
    for mod in (albank, cseq, synth, vadpcm):
        with open(mod.__file__, "rb") as f:
            h.update(f.read())
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:16]


def generate_audio(spec_dir, cache_dir=os.path.join("build", "cache")):
    """Cached on the spec and every audio source file (encoding is slow)."""
    import pickle
    path = os.path.join(cache_dir, f"audio-{_cache_key(spec_dir)}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    out = _generate_audio(spec_dir)
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(out, f)
    return out


def _generate_audio(spec_dir):
    with open(os.path.join(spec_dir, "audio.json")) as f:
        a = json.load(f)
    music_ctl, music_tbl = build_music_bank(a["music"]["rate"])
    seqs = [compose(s, i) for i, s in enumerate(a["seqs"])]
    seqfile = albank.build_seqfile(seqs)
    sfx_ctl, sfx_tbl = build_sfx_bank(a["sfx"])
    return {"seq": seqfile, "ctl": music_ctl, "tbl": music_tbl,
            "sfx_ctl": sfx_ctl, "sfx_tbl": sfx_tbl}
