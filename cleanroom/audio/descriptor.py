"""Coarse audio descriptors and resynthesis.

`describe(samples, rate)` reduces a sound to a coarse outline: per time frame
a fundamental frequency, a harmonicity (0 = noise, 1 = tone) and a 16-band
log-spaced spectral envelope in whole dB. `synthesize(desc, n, rate, seed)`
builds a new waveform with that outline (harmonic partials + band-shaped
noise). No sample data survives the round trip; only the outline.
"""
import numpy as np

NBANDS = 16
FMIN, FMAX = 40.0, 11000.0
EDGES = np.geomspace(FMIN, FMAX, NBANDS + 1)
CENTERS = np.sqrt(EDGES[:-1] * EDGES[1:])
FLOOR_DB = -90


def _frames(n, max_frames=24, min_len=256):
    k = int(np.clip(n // 1024, 1, max_frames))
    k = max(1, min(k, max(1, n // min_len)))
    return np.linspace(0, n, k + 1).astype(int)


def _f0(frame, rate):
    x = frame - frame.mean()
    if np.abs(x).max() < 1e-6 or len(x) < 64:
        return 0.0, 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac /= ac[0] + 1e-12
    lo = int(rate / 1500)  # up to 1.5 kHz fundamentals
    hi = min(len(ac) - 1, int(rate / 40))
    if hi <= lo + 2:
        return 0.0, 0.0
    k = lo + int(np.argmax(ac[lo:hi]))
    return float(rate / k), float(max(0.0, ac[k]))


def describe(samples, rate):
    x = np.asarray(samples, np.float64) / 32768.0
    b = _frames(len(x))
    frames = []
    for a, e in zip(b[:-1], b[1:]):
        seg = x[a:e]
        if len(seg) < 16:
            continue
        win = np.hanning(len(seg))
        spec = np.abs(np.fft.rfft(seg * win)) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1.0 / rate)
        bands = []
        for lo, hi in zip(EDGES[:-1], EDGES[1:]):
            m = (freqs >= lo) & (freqs < hi)
            p = spec[m].mean() if m.any() else 0.0
            bands.append(int(max(FLOOR_DB, round(10 * np.log10(p + 1e-12)))))
        f0, harm = _f0(seg[: min(len(seg), 2048)], rate)
        frames.append({"f0": round(f0, 1), "h": round(harm, 2), "db": bands,
                       "rms": int(max(FLOOR_DB, round(20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9))))})
    return {"frames": frames}


def _shape_noise(n, band_amp, rate, rng):
    """White noise shaped to a 16-band amplitude envelope (FFT domain)."""
    noise = rng.standard_normal(n)
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    gain = np.interp(np.log(np.maximum(freqs, 1.0)), np.log(CENTERS), band_amp, left=band_amp[0], right=0.0)
    return np.fft.irfft(spec * gain, n)


def synthesize(desc, n, rate, seed=0):
    """Waveform of n samples following `desc`, normalised to the frames' RMS."""
    rng = np.random.default_rng(seed)
    frames = desc["frames"]
    if not frames or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    k = len(frames)
    bounds = np.linspace(0, n, k + 1).astype(int)
    out = np.zeros(n)
    phase = 0.0
    t_all = np.arange(n)
    for i, f in enumerate(frames):
        a, e = bounds[i], bounds[i + 1]
        # Overlap by half a segment on each side for smooth transitions.
        pad = max(1, (e - a) // 2)
        a2, e2 = max(0, a - pad), min(n, e + pad)
        m = e2 - a2
        amp = 10 ** (np.asarray(f["db"], float) / 20.0)
        amp = amp / (amp.max() + 1e-12)
        seg = np.zeros(m)
        h = float(f["h"])
        f0 = float(f["f0"])
        if f0 > 20 and h > 0.3:
            t = np.arange(m) / rate
            for p in range(1, 64):
                fp = f0 * p
                if fp >= rate / 2 - 200:
                    break
                ap = np.interp(np.log(fp), np.log(CENTERS), amp, left=amp[0], right=0.0)
                if ap < 1e-3:
                    continue
                seg += ap * np.sin(2 * np.pi * fp * t + phase * p)
            seg = seg / (np.abs(seg).max() + 1e-12) * h
        noise = _shape_noise(m, amp, rate, rng)
        noise = noise / (np.abs(noise).max() + 1e-12) * (1.0 - min(h, 0.95) if f0 > 20 else 1.0)
        seg = seg + noise
        rms_target = 10 ** (f["rms"] / 20.0)
        seg = seg / (np.sqrt((seg ** 2).mean()) + 1e-12) * rms_target
        w = np.ones(m)
        if a2 < a:
            w[: a - a2] = np.linspace(0, 1, a - a2)
        if e2 > e:
            w[m - (e2 - e):] = np.linspace(1, 0, e2 - e)
        out[a2:e2] += seg * w
        if f0 > 20:
            phase += 2 * np.pi * f0 * (e - a) / rate
    peak = np.abs(out).max()
    if peak > 0.99:
        out *= 0.99 / peak
    return out.astype(np.float32)


def make_loop_seamless(x, start, end, xfade=None):
    """Crossfade the end of the loop into the audio just before its start, so
    jumping from `end` back to `start` is continuous."""
    x = np.array(x, dtype=np.float64)
    L = min(xfade or 256, start, end - start)
    if L <= 8:
        return x.astype(np.float32)
    ramp = np.linspace(0, 1, L)
    x[end - L:end] = x[end - L:end] * (1 - ramp) + x[start - L:start] * ramp
    return x.astype(np.float32)
