"""Teach Pilotwings 64: Recompiled to run from a clean image. Idempotent.

    python patches/pw64_clean_runtime.py [path/to/pilotwings-64-recomp]

Changes (each guarded by a marker so a second run is a no-op):
  * src/main.cpp
      - `--clean <image>` (or a pilotwings64.clean.z64 beside the executable)
        selects clean mode: the image's own XXH3-64 becomes the registered
        rom hash, the retail header verification is skipped, the image is
        selected and the game starts without the ROM picker.
  * CMakeLists.txt
      - adds N64ModernRuntime's bundled xxHash to the include path.
Nothing here changes behaviour when no clean image is given.
"""
import sys
from pathlib import Path

MARK = "// [n64cleanrecomp]"

MAIN_INCLUDE = f"""
{MARK} clean-image support
#include <fstream>
#include <iterator>
#define XXH_INLINE_ALL
#include "xxhash.h"

// patches/rt64_ucode_override.py: GBI for microcode RT64 cannot hash-identify.
extern "C" void RT64_SetUCodeOverride(uint32_t textAddress, const char* instanceName);

namespace pw64_clean {{
// The clean image (if any) and its hash; set before the game is registered.
std::string g_image;
uint64_t g_hash = 0;

static std::string exe_dir(const char* argv0) {{
    std::error_code ec;
    auto p = std::filesystem::absolute(std::filesystem::path{{argv0}}, ec).parent_path();
    return p.string();
}}

// Returns true when running in clean mode.
bool detect(int argc, char** argv) {{
    for (int i = 1; i + 1 < argc; i++) {{
        if (std::string{{argv[i]}} == "--clean") {{
            g_image = argv[i + 1];
        }}
    }}
    if (g_image.empty() && argc > 0) {{
        auto beside = std::filesystem::path{{exe_dir(argv[0])}} / "pilotwings64.clean.z64";
        std::error_code ec;
        if (std::filesystem::exists(beside, ec)) {{
            g_image = beside.string();
        }}
    }}
    if (g_image.empty()) {{
        return false;
    }}
    std::ifstream f(g_image, std::ios::binary);
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (data.empty()) {{
        std::fprintf(stderr, "error: cannot read clean image %s\\n", g_image.c_str());
        g_image.clear();
        return false;
    }}
    data.resize((data.size() + 3) & ~size_t{{3}});
    g_hash = XXH3_64bits(data.data(), data.size());
    std::fprintf(stderr, "[pw64] clean image %s (xxh3 %016llx)\\n", g_image.c_str(),
                 static_cast<unsigned long long>(g_hash));
    return true;
}}
}}  // namespace pw64_clean
"""

RUN_SIG = "int run(int argc, char** argv, const char* rom_arg) {"
RUN_CLEAN = f"""int run(int argc, char** argv, const char* rom_arg) {{
    {MARK} a clean image replaces the retail dump entirely.
    const bool clean_mode = pw64_clean::detect(argc, argv);
    if (clean_mode) {{
        rom_arg = pw64_clean::g_image.c_str();
        // A clean image carries no Nintendo microcode, so tell RT64 which GBI
        // the game's two graphics tasks use (identified once from retail by
        // hash; addresses are the textbin symbols' physical addresses).
        RT64_SetUCodeOverride(0x245600, "2.0D, 04-01-96 (F3D.NoN SDK 2.0E)");       // gspF3DEX_fifoTextStart
        RT64_SetUCodeOverride(0x246A30, "2.0D, 04-01-96 (F3D.NoN.fifo SDK 2.0E)");  // gspFast3DTextStart
    }}"""

VERIFY_OLD = "    if (rom_path != nullptr) {\n        pw64::RomHeader header;"
VERIFY_NEW = f"    if (rom_path != nullptr && !clean_mode) {{ {MARK}\n        pw64::RomHeader header;"

HASH_OLD = "    game.rom_hash = pw64::kRomHash;\n    game.internal_name = \"Pilot Wings64\";"
HASH_NEW = (f"    game.rom_hash = clean_mode ? pw64_clean::g_hash : pw64::kRomHash; {MARK}\n"
            "    game.internal_name = clean_mode ? \"PW64 CLEANROOM\" : \"Pilot Wings64\";")

DISPATCH_OLD = "    if (!command.empty() && command[0] == '-') {\n        print_usage(argv[0]);"
DISPATCH_NEW = f"""#if PW64_WITH_RUNTIME && PW64_WITH_RECOMPILED
    if (command == "--clean") {{ {MARK}
        if (argc < 3) {{
            std::fprintf(stderr, "error: --clean needs a path to a clean image\\n");
            return 1;
        }}
        return run(argc, argv, argv[2]);
    }}
#endif

    if (!command.empty() && command[0] == '-') {{
        print_usage(argv[0]);"""

CMAKE_ANCHOR = "target_include_directories(Pilotwings64Recomp"
RSP_OLD = 'set(PW64_RSP_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/RecompiledFuncs/aspMain_rsp.cpp")'
RSP_NEW = """option(PW64_CLEAN_AUDIO "Clean-room audio HLE instead of the RSPRecomp'd microcode" OFF)  # [n64cleanrecomp]
    if(PW64_CLEAN_AUDIO)
        set(PW64_RSP_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/src/audio_hle.cpp")
    else()
        set(PW64_RSP_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/RecompiledFuncs/aspMain_rsp.cpp")
    endif()"""
CMAKE_MARK = "# [n64cleanrecomp]"
CMAKE_ADD = f"""{CMAKE_MARK} xxHash for clean-image hashing
target_include_directories(Pilotwings64Recomp PRIVATE ${{CMAKE_SOURCE_DIR}}/lib/N64ModernRuntime/thirdparty/xxHash)
"""


def patch_main(path: Path):
    s = path.read_bytes().decode("utf-8")
    if MARK in s:
        print(f"{path}: already patched")
        return
    # Include block after the last #include at file top.
    lines = s.split("\n")
    last_inc = max(i for i, l in enumerate(lines[:200]) if l.startswith("#include"))
    lines.insert(last_inc + 1, MAIN_INCLUDE)
    s = "\n".join(lines)
    for old, new in ((RUN_SIG, RUN_CLEAN), (VERIFY_OLD, VERIFY_NEW), (HASH_OLD, HASH_NEW),
                     (DISPATCH_OLD, DISPATCH_NEW)):
        if s.count(old) != 1:
            raise SystemExit(f"{path}: anchor not found exactly once:\n{old}")
        s = s.replace(old, new)
    path.write_bytes(s.encode("utf-8"))
    print(f"{path}: patched")


def patch_cmake(path: Path):
    s = path.read_bytes().decode("utf-8")
    if "# [n64cleanrecomp]" in s:
        print(f"{path}: already patched")
        return
    if s.count(RSP_OLD) != 1:
        raise SystemExit(f"{path}: aspMain source anchor not found")
    s = s.replace(RSP_OLD, RSP_NEW)
    s = s.rstrip("\n") + "\n\n" + CMAKE_ADD
    path.write_bytes(s.encode("utf-8"))
    print(f"{path}: patched")


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "external" / "pilotwings-64-recomp"
    patch_main(root / "src" / "main.cpp")
    patch_cmake(root / "CMakeLists.txt")
    # The clean audio HLE source (selected with -DPW64_CLEAN_AUDIO=ON).
    import shutil
    shutil.copy(Path(__file__).resolve().parent / "files" / "audio_hle.cpp", root / "src" / "audio_hle.cpp")


if __name__ == "__main__":
    main(sys.argv)
