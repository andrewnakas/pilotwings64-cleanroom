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

// Truncate the task's list after n commands, run both, compare DMEM with the
// HLE work area. Logs the first command at which they stop agreeing.
static void pw64_audio_bisect(uint8_t* rdram, uint32_t ucode_addr, const std::vector<uint8_t>& snap,
                              const uint8_t* dmem_snap) {{
    constexpr size_t kSpan = 0x01000000;
    const uint32_t list = RSP_MEM_W_LOAD(0x30, 0xFC0) & 0xFFFFFF;
    const uint32_t size = RSP_MEM_W_LOAD(0x34, 0xFC0);
    std::vector<uint8_t> retail_dmem(0x1000);
    const uint32_t bases[] = {{0x000, 0x4C0, 0x5C0, 0x5B0, 0x5D0, 0x600, 0x640, 0x680}};
    for (uint32_t n = 1; n * 8 <= size; n++) {{
        std::memcpy(rdram, snap.data(), kSpan);
        std::memcpy(dmem, dmem_snap, 0x1000);
        RSP_MEM_W_STORE(0x34, 0xFC0, n * 8);
        aspMain_run(rdram, ucode_addr);
        std::memcpy(retail_dmem.data(), dmem, 0x1000);
        std::vector<uint8_t> retail_rd(snap.size());
        std::memcpy(retail_rd.data(), rdram, kSpan);
        std::memcpy(rdram, snap.data(), kSpan);
        std::memcpy(dmem, dmem_snap, 0x1000);
        RSP_MEM_W_STORE(0x34, 0xFC0, n * 8);
        pw64_hle_reset();
        aspMain_hle_run(rdram, ucode_addr);
        const uint8_t* w = pw64_hle_work();
        auto rd = [&](const uint8_t* m, uint32_t a) {{ return m[a ^ 3]; }};
        const uint32_t a = list + (n - 1) * 8;
        const uint32_t w0 = (uint32_t(rd(snap.data(), a)) << 24) | (rd(snap.data(), a + 1) << 16) | (rd(snap.data(), a + 2) << 8) | rd(snap.data(), a + 3);
        const uint32_t w1 = (uint32_t(rd(snap.data(), a + 4)) << 24) | (rd(snap.data(), a + 5) << 16) | (rd(snap.data(), a + 6) << 8) | rd(snap.data(), a + 7);
        // DMEM is stored byte-swapped per word like RDRAM.
        uint32_t best_base = 0, best = 0xFFFFFFFF;
        for (uint32_t b : bases) {{
            uint32_t d = 0;
            for (uint32_t i = 0; i + b < 0xFC0 && i < 0x1000 - 0x40; i++) d += (retail_dmem[(b + i) ^ 3] != w[i]);
            if (d < best) {{ best = d; best_base = b; }}
        }}
        uint32_t rdiff = 0;
        for (size_t i = 0; i < kSpan; i += 4) rdiff += std::memcmp(&retail_rd[i], &rdram[i], 4) != 0;
        std::fprintf(stderr, "[pw64-bisect] cmd %3u op %2u w0 %08X w1 %08X : dmem diff %4u bytes (base %03X), rdram diff words %u\\n",
                     n, (w0 >> 24) & 0xF, w0, w1, best, best_base, rdiff);
    }}
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
        if (op == 6) {{ out_addr = w1 & 0xFFFFFF; out_len = count; }}
    }}

    static const bool bisect = std::getenv("PW64_AUDIO_BISECT") != nullptr;
    if (bisect && tasks == 300) {{
        pw64_audio_bisect(rdram, ucode_addr, before, dmem_before);
        std::memcpy(rdram, before.data(), kSpan);
        std::memcpy(dmem, dmem_before, 0x1000);
    }}
    const RspExitReason r = aspMain_run(rdram, ucode_addr);
    std::memcpy(retail.data(), rdram, kSpan);
    std::memcpy(rdram, before.data(), kSpan);
    std::memcpy(dmem, dmem_before, 0x1000);
    aspMain_hle_run(rdram, ucode_addr);

    if (++tasks % 30 == 1 && out_len) {{
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
