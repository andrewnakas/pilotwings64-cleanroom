import numpy as np

from cleanroom.codec import mio0
from cleanroom.audio import vadpcm, cseq, albank, synth
from cleanroom.gfx import texfmt


def test_mio0_roundtrip():
    rng = np.random.default_rng(1)
    for data in (b"", b"a", bytes(1000), rng.integers(0, 4, 5000, dtype=np.uint8).tobytes(),
                 rng.integers(0, 256, 3000, dtype=np.uint8).tobytes()):
        assert mio0.decompress(mio0.compress(data)) == data


def test_vadpcm_self_consistent_and_accurate():
    x = (synth.periodic(84, [1, .5, .3], 30) * 20000).astype(np.int64)
    data, book, dec = vadpcm.encode(x)
    assert len(data) == -(-len(x) // 16) * 9
    out = vadpcm.decode(data, book, len(x))
    assert (out == dec[:len(x)]).all()
    snr = 10 * np.log10(np.sum(x ** 2) / np.sum((x - out.astype(np.int64)) ** 2))
    assert snr > 30


def test_cseq_roundtrip_with_loop_and_escape():
    tracks = {0: [(0, "tempo", 500000), (0, "midi", 0xC0, 3), (0, "loopstart"),
                  (0, "note", 0, 60, 100, 48), (96, "note", 0, 62, 100, 254),
                  (192, "loopend", 0xFF)]}
    div, dec = cseq.decode(cseq.encode(tracks, 96))
    assert div == 96
    assert [e[1] for e in dec[0]] == ["tempo", "midi", "loopstart", "note", "note", "loopend", "end"]
    assert dec[0][4][5] == 254  # duration containing an escaped 0xFE byte


def test_bankfile_roundtrip():
    env = {"attack": 1, "decay": 2, "release": 3, "attack_vol": 127, "decay_vol": 100}
    km = {"vel_min": 0, "vel_max": 127, "key_min": 0, "key_max": 127, "key_base": 60, "detune": -5}
    wave = {"base": 0, "len": 90, "type": 0, "flags": 0,
            "loop": {"start": 16, "end": 160, "count": 0xFFFFFFFF, "state": list(range(16))},
            "book": vadpcm.make_book()}
    inst = {"volume": 100, "pan": 64, "priority": 5, "flags": 0, "trem": [0] * 4, "vib": [0] * 4,
            "bend": 200, "sounds": [{"env": env, "keymap": km, "wave": wave, "pan": 64,
                                     "volume": 100, "flags": 0}]}
    bf = {"revision": albank.AL_BANK_VERSION,
          "banks": [{"flags": 0, "pad": 0, "rate": 22050, "percussion": None, "insts": [inst, None]}]}
    back = albank.parse_bankfile(albank.build_bankfile(bf))
    s = back["banks"][0]["insts"][0]["sounds"][0]
    assert back["banks"][0]["insts"][1] is None
    assert s["keymap"]["detune"] == -5 and s["wave"]["loop"]["state"] == list(range(16))
    assert s["wave"]["book"]["book"] == wave["book"]["book"]


def test_texfmt_roundtrip():
    rng = np.random.default_rng(2)
    px = rng.integers(0, 256, (8, 8, 4), dtype=np.uint8)
    for fmt, siz, tol in ((texfmt.RGBA, texfmt.B32, 0), (texfmt.RGBA, texfmt.B16, 8)):
        back = texfmt.decode(texfmt.encode(px, fmt, siz), 8, 8, fmt, siz)
        assert np.abs(back[..., :3].astype(int) - px[..., :3].astype(int)).max() <= tol
