"""DEV ONLY: audio HLE comparison harness for Pilotwings 64: Recompiled.

Builds both the RSPRecomp'd retail microcode (RecompiledFuncs/aspMain_rsp.cpp,
generated from a retail ROM) and our clean HLE (src/audio_hle.cpp, renamed to
aspMain_hle_run). With PW64_AUDIO_COMPARE=1, every audio task is run twice
from the same RDRAM/DMEM snapshot and the differences are logged; the retail
result is what plays. This is a measurement tool for the dirty room; the
resulting executable must not be distributed.

    python patches/dev_audio_compare.py <port dir>
"""
import sys
from pathlib import Path

MARK = "// [n64cleanrecomp audio compare]"

CALL_OLD = "    const RspExitReason reason = aspMain_run(rdram, ucode_addr);"
CALL_NEW = f"""    {MARK}
    const RspExitReason reason = pw64_audio_compare(rdram, ucode_addr);"""

HELPER_ANCHOR = "RspExitReason asp_main_watched(uint8_t* rdram, uint32_t ucode_addr) {"
HELPER = f"""{MARK}
extern "C" RspExitReason aspMain_hle_run(uint8_t* rdram, uint32_t ucode_addr);

extern "C" uint8_t* pw64_hle_work();
extern "C" void pw64_hle_reset();

extern "C" void pw64_hle_step(uint8_t* rdram, uint32_t w0, uint32_t w1);
extern "C" void pw64_hle_states_save();
extern "C" void pw64_hle_states_restore();
extern "C" void pw64_hle_io(uint32_t*, uint32_t*, uint32_t*);

// Isolated per-command test: give the HLE the microcode's own DMEM from just
// before command n, run only command n, compare with the microcode after n.
static void pw64_audio_bisect(uint8_t* rdram, uint32_t ucode_addr, const std::vector<uint8_t>& snap,
                              const uint8_t* dmem_snap) {{
    constexpr size_t kSpan = 0x01000000;
    constexpr uint32_t kBase = 0x5C0, kLen = 0xA00;
    const uint32_t list = RSP_MEM_W_LOAD(0x30, 0xFC0) & 0xFFFFFF;
    const uint32_t size = RSP_MEM_W_LOAD(0x34, 0xFC0);
    std::vector<uint8_t> A(0x1000), B(0x1000), Ard(kSpan), Brd(kSpan);
    auto retail_run = [&](uint32_t n, std::vector<uint8_t>& dm, std::vector<uint8_t>& rd) {{
        std::memcpy(rdram, snap.data(), kSpan);
        std::memcpy(dmem, dmem_snap, 0x1000);
        RSP_MEM_W_STORE(0x34, 0xFC0, n * 8);
        if (n) aspMain_run(rdram, ucode_addr);
        std::memcpy(dm.data(), dmem, 0x1000);
        std::memcpy(rd.data(), rdram, kSpan);
    }};
    auto word = [&](uint32_t a) {{
        auto r = [&](uint32_t x) {{ return snap[x ^ 3]; }};
        return (uint32_t(r(a)) << 24) | (r(a + 1) << 16) | (r(a + 2) << 8) | r(a + 3);
    }};
    pw64_hle_states_save();
    for (uint32_t n = 1; n * 8 <= size; n++) {{
        pw64_hle_states_restore();
        retail_run(n - 1, A, Ard);
        retail_run(n, B, Brd);
        // HLE state (segments, buffers, volumes) from commands 1..n-1, then
        // the microcode's own DMEM, then command n alone.
        std::memcpy(rdram, snap.data(), kSpan);
        pw64_hle_reset();
        for (uint32_t k = 1; k < n; k++) {{
            const uint32_t kw0 = word(list + (k - 1) * 8);
            const uint32_t op = (kw0 >> 24) & 0xF;
            // Registers only: segments, buffers, volumes, codebook, loop state.
            if (op == 7 || op == 8 || op == 9 || op == 11 || op == 15) pw64_hle_step(rdram, kw0, word(list + (k - 1) * 8 + 4));
        }}
        uint8_t* w = pw64_hle_work();
        for (uint32_t i = 0; i < kLen; i++) w[i] = A[(kBase + i) ^ 3];
        std::memcpy(rdram, Ard.data(), kSpan);
        const uint32_t w0 = word(list + (n - 1) * 8), w1 = word(list + (n - 1) * 8 + 4);
        pw64_hle_step(rdram, w0, w1);
        double e2 = 0, s2 = 0;
        uint32_t changed = 0, wrong = 0;
        for (uint32_t i = 0; i + 1 < kLen; i += 2) {{
            const int a0 = int16_t((A[(kBase + i) ^ 3] << 8) | A[(kBase + i + 1) ^ 3]);
            const int x = int16_t((B[(kBase + i) ^ 3] << 8) | B[(kBase + i + 1) ^ 3]);
            const int y = int16_t((w[i] << 8) | w[i + 1]);
            if (x != a0 || y != a0) {{
                changed++;
                if (x != y) wrong++;
                e2 += double(x - y) * (x - y);
                s2 += double(x) * x;
            }}
        }}
        uint32_t rdiff = 0;
        for (size_t i = 0; i < kSpan; i += 4) rdiff += std::memcmp(&Brd[i], &rdram[i], 4) != 0;
        static int dumps = 0;
        if (((w0 >> 24) & 0xF) == 3 && (w0 & 0x10000) && dumps < 2) {{
            dumps++;
            uint32_t hin, hout, hcnt; pw64_hle_io(&hin, &hout, &hcnt);
            auto S = [&](const std::vector<uint8_t>& m, uint32_t a) {{ return int(int16_t((m[(kBase + a) ^ 3] << 8) | m[(kBase + a + 1) ^ 3])); }};
            auto H = [&](uint32_t a) {{ return int(int16_t((w[a] << 8) | w[a + 1])); }};
            std::fprintf(stderr, "[pw64-env] in %X out %X count %X\\n", hin, hout, hcnt);
            const uint32_t bufs[4] = {{hout, 0x580, 0x6C0, 0x800}};
            for (int b = 0; b < 4; b++) {{
                std::fprintf(stderr, "[pw64-env] buf %X pre/retail/hle:", bufs[b]);
                for (int k = 0; k < 40; k += 4) std::fprintf(stderr, " %d/%d/%d", S(A, bufs[b] + k * 2), S(B, bufs[b] + k * 2), H(bufs[b] + k * 2));
                std::fprintf(stderr, "\\n");
            }}
            std::fprintf(stderr, "[pw64-env] input:");
            for (int k = 0; k < 40; k += 4) std::fprintf(stderr, " %d", S(A, hin + k * 2));
            std::fprintf(stderr, "\\n");
        }}
        std::fprintf(stderr, "[pw64-iso] cmd %3u op %2u w0 %08X w1 %08X : changed %4u samples, wrong %4u, SNR %6.1f dB, rdram words off %u\\n",
                     n, (w0 >> 24) & 0xF, w0, w1, changed, wrong, e2 > 0 ? 10 * std::log10(s2 / e2) : 999.0, rdiff);
    }}
    pw64_hle_states_restore();
    std::fflush(stderr);
}}

static RspExitReason pw64_audio_compare(uint8_t* rdram, uint32_t ucode_addr) {{
    static const bool on = std::getenv("PW64_AUDIO_COMPARE") != nullptr;
    if (!on) {{
        return aspMain_run(rdram, ucode_addr);
    }}
    constexpr size_t kSpan = 0x01000000;  // 16 MB: the game's RDRAM plus the port's scratch
    static std::vector<uint8_t> before(kSpan), retail(kSpan);
    static uint8_t dmem_before[0x1000];
    static uint64_t tasks = 0;
    std::memcpy(before.data(), rdram, kSpan);
    std::memcpy(dmem_before, dmem, 0x1000);

    // The final save of the list is the mixed stereo output (save.c).
    const uint32_t list = RSP_MEM_W_LOAD(0x30, 0xFC0) & 0xFFFFFF;
    const uint32_t size = RSP_MEM_W_LOAD(0x34, 0xFC0);
    uint32_t out_addr = 0, out_len = 0, count = 0;
    for (uint32_t off = 0; off + 8 <= size; off += 8) {{
        auto rd = [&](uint32_t a) {{ return rdram[a ^ 3]; }};
        const uint32_t a = list + off;
        const uint32_t w0 = (uint32_t(rd(a)) << 24) | (rd(a + 1) << 16) | (rd(a + 2) << 8) | rd(a + 3);
        const uint32_t w1 = (uint32_t(rd(a + 4)) << 24) | (rd(a + 5) << 16) | (rd(a + 6) << 8) | rd(a + 7);
        const uint32_t op = (w0 >> 24) & 0xF;
        if (op == 8 && !((w0 >> 16) & 0x08)) count = w1 & 0xFFFF;
        if (op == 6 && count >= out_len) {{ out_addr = w1 & 0xFFFFFF; out_len = count; }}
    }}

    static const long bisect_at = std::getenv("PW64_AUDIO_BISECT") ? std::atol(std::getenv("PW64_AUDIO_BISECT")) : -1;
    if (bisect_at >= 0 && (long)tasks == bisect_at) {{
        pw64_audio_bisect(rdram, ucode_addr, before, dmem_before);
        std::memcpy(rdram, before.data(), kSpan);
        std::memcpy(dmem, dmem_before, 0x1000);
    }}
    const RspExitReason r = aspMain_run(rdram, ucode_addr);
    std::memcpy(retail.data(), rdram, kSpan);
    std::memcpy(rdram, before.data(), kSpan);
    std::memcpy(dmem, dmem_before, 0x1000);
    aspMain_hle_run(rdram, ucode_addr);

    if (++tasks % 10 == 1 && out_len) {{
        double err = 0, sig = 0;
        int maxd = 0;
        for (uint32_t i = 0; i + 1 < out_len; i += 2) {{
            const uint32_t a = out_addr + i;
            const int16_t x = int16_t((retail[a ^ 3] << 8) | retail[(a + 1) ^ 3]);
            const int16_t y = int16_t((rdram[a ^ 3] << 8) | rdram[(a + 1) ^ 3]);
            err += double(x - y) * (x - y);
            sig += double(x) * x;
            maxd = std::max(maxd, std::abs(x - y));
        }}
        // Other regions that differ (state blocks, reverb lines).
        uint32_t regions = 0, first = 0xFFFFFFFF;
        for (size_t i = 0; i < kSpan; i += 64) {{
            if (std::memcmp(&retail[i], &rdram[i], 64) != 0 && !(i + 64 > out_addr && i < out_addr + out_len)) {{
                regions++;
                if (first == 0xFFFFFFFF) first = uint32_t(i);
            }}
        }}
        std::fprintf(stderr, "[pw64-cmp] task %llu: out %u B at %06X, SNR %.1f dB, max diff %d, rms sig %.0f; "
                             "other differing 64B blocks %u (first %06X)\\n",
                     (unsigned long long)tasks, out_len, out_addr,
                     err > 0 ? 10 * std::log10(sig / err) : 999.0, maxd, std::sqrt(sig / std::max(1u, out_len / 2)),
                     regions, first);
        std::fflush(stderr);
    }}
    std::memcpy(rdram, retail.data(), kSpan);  // play the retail result
    return r;
}}

"""

CMAKE_OLD = '    if(PW64_CLEAN_AUDIO)'
CMAKE_NEW = f'''    option(PW64_AUDIO_COMPARE "DEV: build retail aspMain and the HLE side by side" OFF)  # [n64cleanrecomp audio compare]
    if(PW64_AUDIO_COMPARE)
        list(APPEND PW64_RECOMPILED_SOURCES "${{CMAKE_CURRENT_SOURCE_DIR}}/src/audio_hle.cpp")
        set_source_files_properties("${{CMAKE_CURRENT_SOURCE_DIR}}/src/audio_hle.cpp" PROPERTIES COMPILE_DEFINITIONS "PW64_HLE_ENTRY=aspMain_hle_run")
    endif()
    if(PW64_CLEAN_AUDIO)'''


def main(argv):
    root = Path(argv[1])
    cb = root / "src" / "callbacks.cpp"
    s = cb.read_bytes().decode("utf-8")
    if MARK not in s:
        for old, new in ((HELPER_ANCHOR, HELPER + HELPER_ANCHOR), (CALL_OLD, CALL_NEW)):
            assert s.count(old) == 1, old
            s = s.replace(old, new)
        for inc in ("#include <cmath>", "#include <cstdlib>", "#include <cstring>", "#include <vector>", "#include <algorithm>"):
            if inc not in s:
                s = inc + "\n" + s
        cb.write_bytes(s.encode("utf-8"))
    cm = root / "CMakeLists.txt"
    s = cm.read_bytes().decode("utf-8")
    if "PW64_AUDIO_COMPARE" not in s:
        assert s.count(CMAKE_OLD) == 1
        s = s.replace(CMAKE_OLD, CMAKE_NEW)
        cm.write_bytes(s.encode("utf-8"))
    print("audio compare harness in place")


if __name__ == "__main__":
    main(sys.argv)
