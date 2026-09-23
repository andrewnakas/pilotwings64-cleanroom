"""Build Pilotwings 64: Recompiled from the clean (ROM-free) ELF.

    python -m games.pilotwings64.build_port [--port DIR] [--zig ZIG] [--elf build/pilotwings64.clean.elf]

1. The clean ELF from build_code.py replaces the port's pilotwings64.us.elf.
2. N64Recomp regenerates RecompiledFuncs (no RSPRecomp: nothing is taken
   from Nintendo's audio microcode; the port's PW64_CLEAN_AUDIO HLE runs the
   audio command lists instead).
3. The port's C patches are rebuilt (tools/pw64_build_patches_win.py, Zig).
4. CMake builds build-clean/Pilotwings64Recomp.exe with PW64_CLEAN_AUDIO=ON,
   and the clean image is placed beside it as pilotwings64.clean.z64.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

DEFAULTS = {
    "port": Path(r"C:/Users/andre/n64work/pilotwings-64-recomp"),
    "zig": Path(os.path.expanduser(r"~/.local/zig-x86_64-windows-0.16.0/zig.exe")),
    "python": Path(r"C:/Users/andre/n64work/venv/Scripts/python.exe"),
    "vcvars": Path(r"C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat"),
    "llvm": Path(os.path.expanduser(r"~/.local/clang+llvm-23.1.2-x86_64-pc-windows-msvc/bin")),
}


def run(cmd, cwd=None, **kw):
    print("  $", " ".join(str(c) for c in cmd)[:160])
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, **kw)
    if r.returncode != 0:
        raise SystemExit(f"failed ({r.returncode}): {cmd[0]}")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=Path, default=DEFAULTS["port"])
    ap.add_argument("--zig", type=Path, default=DEFAULTS["zig"])
    ap.add_argument("--elf", type=Path, default=REPO / "build" / "pilotwings64.clean.elf")
    ap.add_argument("--image", type=Path, default=REPO / "build" / "pilotwings64.clean.z64")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args(argv)
    port, py = a.port, DEFAULTS["python"]
    n64recomp = port / "lib" / "N64ModernRuntime" / "N64Recomp" / "build-win" / "N64Recomp.exe"

    print("patches ...")
    # Start from the pristine port sources (dev tools such as the audio
    # comparison harness patch them too), then apply the clean-build patches.
    run(["git", "-C", port, "checkout", "--", "src/main.cpp", "src/callbacks.cpp", "CMakeLists.txt"])
    run([sys.executable, REPO / "patches" / "pw64_clean_runtime.py", port])
    run([sys.executable, REPO / "patches" / "rt64_ucode_override.py", port])

    # Nothing derived from retail microcode belongs in the clean build.
    (port / "RecompiledFuncs" / "aspMain_rsp.cpp").unlink(missing_ok=True)
    print("recompiling the clean ELF ...")
    shutil.copy(a.elf, port / "pilotwings64.us.elf")
    funcs = port / "RecompiledFuncs"
    shutil.rmtree(funcs, ignore_errors=True)
    funcs.mkdir()
    run([py, port / "tools" / "gen_mdebug_mappings.py"], cwd=port)
    with open(funcs / "recompile.log", "w") as log:
        run([n64recomp, port / "recomp" / "pilotwings64.us.full.toml"], cwd=port, stderr=log)
    if not (funcs / "funcs.h").read_text().rstrip().endswith("#endif"):
        raise SystemExit("funcs.h is truncated")
    (funcs / "context").mkdir()
    run([n64recomp, port / "recomp" / "pilotwings64.us.full.toml", "--dump-context"],
        cwd=funcs / "context", stdout=subprocess.DEVNULL)
    run([py, port / "tools" / "gen_reimplemented_decls.py"], cwd=port)

    print("patches (MIPS, via Zig) ...")
    run([py, REPO / "tools" / "pw64_build_patches_win.py", port, a.zig])

    print("building the executable ...")
    bat = port / "build_clean.bat"
    bat.write_text(
        "@echo off\r\n"
        f'call "{DEFAULTS["vcvars"]}" >nul\r\n'
        f"set PATH={DEFAULTS['llvm']};%PATH%\r\n"
        f"cd /d {port}\r\n"
        'cmake -B build-clean -G Ninja "-DCMAKE_C_COMPILER=clang-cl" "-DCMAKE_CXX_COMPILER=clang-cl" '
        '"-DCMAKE_BUILD_TYPE=RelWithDebInfo" "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" '
        '"-DPW64_WITH_RUNTIME=ON" "-DPW64_WITH_RECOMPILED=ON" "-DPW64_WITH_FRONTEND=ON" '
        '"-DPW64_CLEAN_AUDIO=ON" || exit /b 1\r\n'
        f"cmake --build build-clean --target Pilotwings64Recomp -j {a.jobs} || exit /b 1\r\n")
    run(["cmd", "/c", bat])
    exe_dir = port / "build-clean"
    shutil.copy(a.image, exe_dir / "pilotwings64.clean.z64")
    print(f"ready: {exe_dir / 'Pilotwings64Recomp.exe'} (with pilotwings64.clean.z64 beside it)")


if __name__ == "__main__":
    main()
