// Clean-room high-level emulation of the libultra audio command list (ABI 1).
//
// Replaces the RSPRecomp'd audio microcode, which needs Nintendo's microcode
// text at build time and its data (jump table, filter constants) at run time.
// This interprets the command list the game's synthesizer (libultra
// src/audio/synthesizer.c, env.c, load.c, resample.c, reverb.c) writes, using
// the command encodings from PR/abi.h. The DSP here is our own: the ADPCM
// decode follows the documented VADPCM predictor, the resampler is a 4-point
// cubic interpolator, and the envelope ramps are simple multiplicative steps.
// It is not bit-exact with the microcode; it only has to sound right.
//
// Addresses in the list are segmented (A_SEGMENT). State blocks the synth
// hands over (ADPCM_STATE, RESAMPLE_STATE, ENVMIX_STATE, POLEF_STATE) are
// opaque to the game, so their layout here is ours.

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include <librecomp/rsp.hpp>

namespace {

constexpr int A_SPNOOP = 0, A_ADPCM = 1, A_CLEARBUFF = 2, A_ENVMIXER = 3, A_LOADBUFF = 4,
              A_RESAMPLE = 5, A_SAVEBUFF = 6, A_SEGMENT = 7, A_SETBUFF = 8, A_SETVOL = 9,
              A_DMEMMOVE = 10, A_LOADADPCM = 11, A_MIXER = 12, A_INTERLEAVE = 13, A_POLEF = 14,
              A_SETLOOP = 15;
constexpr uint32_t A_INIT = 0x01, A_LOOP = 0x02, A_LEFT = 0x02, A_VOL = 0x04, A_AUX = 0x08;

// Our "DMEM": the synth addresses a 4 KB work area.
uint8_t work[0x1000 + 64];

struct State {
    uint32_t segments[16] = {};
    uint16_t in = 0, out = 0, count = 0;
    uint16_t dry_right = 0, wet_left = 0, wet_right = 0;
    int16_t vol[2] = {}, target[2] = {};
    int32_t rate[2] = {};
    int16_t dry = 0, wet = 0;
    int16_t book[16 * 16] = {};  // order 2 x 8 taps x up to 16 predictors
    uint32_t loop_addr = 0;
} st;

inline uint32_t resolve(uint32_t addr) {
    return (st.segments[(addr >> 24) & 0xF] + (addr & 0xFFFFFF)) & 0xFFFFFF;
}

// RDRAM is stored with each 32-bit word byte-swapped.
inline uint8_t rd8(const uint8_t* rdram, uint32_t a) { return rdram[a ^ 3]; }
inline void wr8(uint8_t* rdram, uint32_t a, uint8_t v) { rdram[a ^ 3] = v; }

void rdram_to_work(const uint8_t* rdram, uint32_t w, uint32_t a, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) work[(w + i) & 0xFFF] = rd8(rdram, (a + i) & 0xFFFFFF);
}
void work_to_rdram(uint8_t* rdram, uint32_t a, uint32_t w, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) wr8(rdram, (a + i) & 0xFFFFFF, work[(w + i) & 0xFFF]);
}

// Work memory holds big-endian samples, like DMEM.
inline int16_t ws(uint32_t w) { return int16_t((work[w & 0xFFF] << 8) | work[(w + 1) & 0xFFF]); }
inline void wws(uint32_t w, int32_t v) {
    v = std::clamp(v, -32768, 32767);
    work[w & 0xFFF] = uint8_t(v >> 8);
    work[(w + 1) & 0xFFF] = uint8_t(v);
}

inline int16_t rds(const uint8_t* rdram, uint32_t a) {
    return int16_t((rd8(rdram, a) << 8) | rd8(rdram, a + 1));
}
inline void wrs(uint8_t* rdram, uint32_t a, int16_t v) {
    wr8(rdram, a, uint8_t(uint16_t(v) >> 8));
    wr8(rdram, a + 1, uint8_t(v));
}

// ---------------------------------------------------------------- ADPCM
void adpcm(uint8_t* rdram, uint32_t flags, uint32_t state_addr) {
    int16_t hist[16] = {};
    if (flags & A_INIT) {
    } else if (flags & A_LOOP) {
        for (int i = 0; i < 16; i++) hist[i] = rds(rdram, st.loop_addr + i * 2);
    } else {
        for (int i = 0; i < 16; i++) hist[i] = rds(rdram, state_addr + i * 2);
    }
    int32_t y2 = hist[14], y1 = hist[15];
    uint32_t in = st.in, out = st.out;
    int remaining = st.count;
    int16_t last[16] = {};
    while (remaining > 0) {
        uint8_t hdr = work[in & 0xFFF];
        int scale = hdr >> 4, pred = hdr & 0xF;
        const int16_t* b0 = &st.book[pred * 16];
        const int16_t* b1 = b0 + 8;
        int32_t nib[16];
        for (int i = 0; i < 8; i++) {
            uint8_t b = work[(in + 1 + i) & 0xFFF];
            int hi = b >> 4, lo = b & 0xF;
            nib[i * 2] = (hi >= 8 ? hi - 16 : hi) << scale;
            nib[i * 2 + 1] = (lo >= 8 ? lo - 16 : lo) << scale;
        }
        for (int g = 0; g < 2; g++) {
            const int32_t* r = &nib[g * 8];
            int32_t o[8];
            for (int i = 0; i < 8; i++) {
                int64_t acc = (int64_t(r[i]) << 11) + int64_t(b0[i]) * y2 + int64_t(b1[i]) * y1;
                for (int k = 0; k < i; k++) acc += int64_t(b1[i - 1 - k]) * r[k];
                o[i] = std::clamp<int32_t>(int32_t(acc >> 11), -32768, 32767);
            }
            for (int i = 0; i < 8; i++) {
                wws(out + (g * 8 + i) * 2, o[i]);
                last[g * 8 + i] = int16_t(o[i]);
            }
            y2 = o[6];
            y1 = o[7];
        }
        in += 9;
        out += 32;
        remaining -= 32;
    }
    for (int i = 0; i < 16; i++) wrs(rdram, state_addr + i * 2, last[i]);
}

// -------------------------------------------------------------- resample
// State: s16 history[4], u16 frac, pad.
void resample(uint8_t* rdram, uint32_t flags, uint32_t pitch, uint32_t state_addr) {
    int16_t hist[4] = {};
    uint32_t frac = 0;
    if (!(flags & A_INIT)) {
        for (int i = 0; i < 4; i++) hist[i] = rds(rdram, state_addr + i * 2);
        frac = uint16_t(rds(rdram, state_addr + 8));
    }
    // The four history samples sit just before the input.
    uint32_t in = st.in - 8;
    for (int i = 0; i < 4; i++) wws(in + i * 2, hist[i]);
    uint32_t pos = 0;          // in samples from `in`
    uint32_t acc = frac;       // 16-bit fraction
    const uint32_t step = pitch << 1;  // pitch is Q1.15; step is 16.16
    const int n = st.count / 2;
    for (int i = 0; i < n; i++) {
        float t = acc / 65536.0f;
        float p0 = ws(in + (pos + 0) * 2), p1 = ws(in + (pos + 1) * 2);
        float p2 = ws(in + (pos + 2) * 2), p3 = ws(in + (pos + 3) * 2);
        // Catmull-Rom between p1 and p2.
        float v = p1 + 0.5f * t * (p2 - p0 + t * (2.0f * p0 - 5.0f * p1 + 4.0f * p2 - p3 +
                                                    t * (3.0f * (p1 - p2) + p3 - p0)));
        wws(st.out + i * 2, int32_t(v));
        acc += step;
        pos += acc >> 16;
        acc &= 0xFFFF;
    }
    for (int i = 0; i < 4; i++) wrs(rdram, state_addr + i * 2, ws(in + (pos + i) * 2));
    wrs(rdram, state_addr + 8, int16_t(acc));
}

// ------------------------------------------------------------ env mixer
// State: vol[2], target[2], rate[2] (s32 as two s16), dry, wet.
void envmixer(uint8_t* rdram, uint32_t flags, uint32_t state_addr) {
    int32_t vol[2], target[2], rate[2], dry, wet;
    if (flags & A_INIT) {
        vol[0] = st.vol[0]; vol[1] = st.vol[1];
        target[0] = st.target[0]; target[1] = st.target[1];
        rate[0] = st.rate[0]; rate[1] = st.rate[1];
        dry = st.dry; wet = st.wet;
    } else {
        vol[0] = rds(rdram, state_addr + 0); vol[1] = rds(rdram, state_addr + 2);
        target[0] = rds(rdram, state_addr + 4); target[1] = rds(rdram, state_addr + 6);
        rate[0] = (int32_t(uint16_t(rds(rdram, state_addr + 8))) << 16) | uint16_t(rds(rdram, state_addr + 10));
        rate[1] = (int32_t(uint16_t(rds(rdram, state_addr + 12))) << 16) | uint16_t(rds(rdram, state_addr + 14));
        dry = rds(rdram, state_addr + 16); wet = rds(rdram, state_addr + 18);
    }
    const int n = st.count / 2;
    for (int i = 0; i < n; i++) {
        if ((i & 7) == 0) {
            // Rates are 16.16 multipliers applied every 8 samples (libultra env.c
            // computes them that way); stop at the target.
            for (int c = 0; c < 2; c++) {
                if (rate[c] != 0 && vol[c] != target[c]) {
                    int64_t nv = (int64_t(vol[c] == 0 ? (target[c] > 0 ? 1 : -1) : vol[c]) * rate[c]) >> 16;
                    if ((rate[c] > 0x10000 && nv >= target[c]) || (rate[c] < 0x10000 && nv <= target[c]) ||
                        rate[c] == 0x10000) {
                        nv = target[c];
                    }
                    vol[c] = int32_t(std::clamp<int64_t>(nv, -32768, 32767));
                }
            }
        }
        int32_t s = ws(st.in + i * 2);
        int32_t l = (s * vol[0]) >> 15;
        int32_t r = (s * vol[1]) >> 15;
        wws(st.out + i * 2, ws(st.out + i * 2) + ((l * dry) >> 15));
        wws(st.dry_right + i * 2, ws(st.dry_right + i * 2) + ((r * dry) >> 15));
        wws(st.wet_left + i * 2, ws(st.wet_left + i * 2) + ((l * wet) >> 15));
        wws(st.wet_right + i * 2, ws(st.wet_right + i * 2) + ((r * wet) >> 15));
    }
    wrs(rdram, state_addr + 0, int16_t(vol[0])); wrs(rdram, state_addr + 2, int16_t(vol[1]));
    wrs(rdram, state_addr + 4, int16_t(target[0])); wrs(rdram, state_addr + 6, int16_t(target[1]));
    wrs(rdram, state_addr + 8, int16_t(rate[0] >> 16)); wrs(rdram, state_addr + 10, int16_t(rate[0]));
    wrs(rdram, state_addr + 12, int16_t(rate[1] >> 16)); wrs(rdram, state_addr + 14, int16_t(rate[1]));
    wrs(rdram, state_addr + 16, int16_t(dry)); wrs(rdram, state_addr + 18, int16_t(wet));
}

// ------------------------------------------------------------ pole filter
// One-pole low-pass used by the reverb. State: s16 last output.
void polef(uint8_t* rdram, uint32_t flags, uint32_t gain, uint32_t state_addr) {
    int32_t y = (flags & A_INIT) ? 0 : rds(rdram, state_addr);
    const int32_t g = int16_t(gain);
    const int n = st.count / 2;
    for (int i = 0; i < n; i++) {
        int32_t x = ws(st.in + i * 2);
        y = y + (((x - y) * std::clamp(g, 0, 32767)) >> 15);
        wws(st.out + i * 2, y);
    }
    wrs(rdram, state_addr, int16_t(y));
}

}  // namespace

RspExitReason aspMain_run(uint8_t* rdram, uint32_t /*ucode_addr*/) {
    // Diagnostic: PW64_HLE_OFF=1 skips the command list entirely (silence).
    static const bool off = std::getenv("PW64_HLE_OFF") != nullptr;
    if (off) {
        return RspExitReason::Broke;
    }
    // The OSTask is in DMEM at 0xFC0 (librecomp puts it there): data_ptr at
    // +0x30, data_size at +0x34.
    const uint32_t list = RSP_MEM_W_LOAD(0x30, 0xFC0) & 0xFFFFFF;
    const uint32_t size = RSP_MEM_W_LOAD(0x34, 0xFC0);
    for (uint32_t off = 0; off + 8 <= size; off += 8) {
        const uint32_t a = list + off;
        const uint32_t w0 = (uint32_t(rd8(rdram, a)) << 24) | (rd8(rdram, a + 1) << 16) |
                            (rd8(rdram, a + 2) << 8) | rd8(rdram, a + 3);
        const uint32_t w1 = (uint32_t(rd8(rdram, a + 4)) << 24) | (rd8(rdram, a + 5) << 16) |
                            (rd8(rdram, a + 6) << 8) | rd8(rdram, a + 7);
        const uint32_t flags = (w0 >> 16) & 0xFF;
        switch ((w0 >> 24) & 0xF) {
        case A_SPNOOP:
            break;
        case A_SEGMENT:
            st.segments[(w1 >> 24) & 0xF] = w1 & 0xFFFFFF;
            break;
        case A_SETBUFF:
            if (flags & A_AUX) {
                st.dry_right = w0 & 0xFFFF;
                st.wet_left = w1 >> 16;
                st.wet_right = w1 & 0xFFFF;
            } else {
                st.in = w0 & 0xFFFF;
                st.out = w1 >> 16;
                st.count = w1 & 0xFFFF;
            }
            break;
        case A_CLEARBUFF:
            for (uint32_t i = 0; i < (w1 & 0xFFFF); i++) work[((w0 & 0xFFFF) + i) & 0xFFF] = 0;
            break;
        case A_LOADBUFF:
            rdram_to_work(rdram, st.in, resolve(w1), st.count);
            break;
        case A_SAVEBUFF:
            work_to_rdram(rdram, resolve(w1), st.out, st.count);
            break;
        case A_DMEMMOVE: {
            const uint32_t i = w0 & 0xFFFF, o = w1 >> 16, n = w1 & 0xFFFF;
            uint8_t tmp[0x1000];
            for (uint32_t k = 0; k < n && k < sizeof(tmp); k++) tmp[k] = work[(i + k) & 0xFFF];
            for (uint32_t k = 0; k < n && k < sizeof(tmp); k++) work[(o + k) & 0xFFF] = tmp[k];
            break;
        }
        case A_LOADADPCM: {
            const uint32_t src = resolve(w1);
            const uint32_t n = std::min<uint32_t>(w0 & 0xFFFF, sizeof(st.book));
            for (uint32_t k = 0; k < n / 2; k++) st.book[k] = rds(rdram, src + k * 2);
            break;
        }
        case A_SETLOOP:
            st.loop_addr = resolve(w1);
            break;
        case A_ADPCM:
            adpcm(rdram, flags, resolve(w1));
            break;
        case A_RESAMPLE:
            resample(rdram, flags, w0 & 0xFFFF, resolve(w1));
            break;
        case A_SETVOL:
            if (flags & A_AUX) {
                st.dry = int16_t(w0 & 0xFFFF);
                st.wet = int16_t(w1 & 0xFFFF);  // aSetVolume(A_AUX, dry, 0, wet)
            } else if (flags & A_VOL) {
                st.vol[(flags & A_LEFT) ? 0 : 1] = int16_t(w0 & 0xFFFF);
            } else {
                const int c = (flags & A_LEFT) ? 0 : 1;
                st.target[c] = int16_t(w0 & 0xFFFF);
                st.rate[c] = int32_t(w1);
            }
            break;
        case A_ENVMIXER:
            envmixer(rdram, flags, resolve(w1));
            break;
        case A_MIXER: {
            const int32_t gain = int16_t(w0 & 0xFFFF);
            const uint32_t i = w1 >> 16, o = w1 & 0xFFFF;
            for (int k = 0; k < st.count / 2; k++) {
                wws(o + k * 2, ws(o + k * 2) + ((ws(i + k * 2) * gain) >> 15));
            }
            break;
        }
        case A_INTERLEAVE: {
            const uint32_t l = w1 >> 16, r = w1 & 0xFFFF;
            const int n = st.count / 2;
            int16_t tmp[2048];
            for (int k = 0; k < n && k < 1024; k++) {
                tmp[k * 2] = ws(l + k * 2);
                tmp[k * 2 + 1] = ws(r + k * 2);
            }
            for (int k = 0; k < n * 2 && k < 2048; k++) wws(st.out + k * 2, tmp[k]);
            break;
        }
        case A_POLEF:
            polef(rdram, flags, w0 & 0xFFFF, resolve(w1));
            break;
        default:
            break;
        }
    }
    return RspExitReason::Broke;
}
