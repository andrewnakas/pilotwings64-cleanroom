"""Build Pilotwings 64's code from the decompilation with NO retail ROM.

    python -m games.pilotwings64.build_code [--work DIR] [--out build/pilotwings64.clean.z64]

Every input that the decomp normally extracts from the ROM is replaced:
  * splat is run against a synthetic ROM (our header, zeros elsewhere) only
    to produce the linker script and file layout (config copy without sha1);
  * game-specific hand-written asm -> games/pilotwings64/cleanasm (ours);
  * libultra asm -> ours for bcopy/bzero/sqrtf; splat's zero-filled layout for
    the rest (N64ModernRuntime reimplements it);
  * RSP microcode bins -> zero-filled stubs of the same size (the port uses
    an HLE audio implementation and an RT64 GBI override instead);
  * ipl3 -> zeros; filesystem/audio bins -> our generated clean assets.
The C code is compiled byte-for-byte as the decomp does (native IDO 5.3).

Environment/paths it relies on (defaults for this machine, override with args):
  --decomp   the Pilotwings64Decomp checkout (git repo; a worktree is made)
  --ido-bin  native IDO passes (tools/idowin)
  --python   Python with splat installed
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from cleanroom import rom as romlib
from . import profile as P

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CLEANASM = HERE / "cleanasm"

DEFAULTS = {
    "decomp": Path(r"C:/Users/andre/n64work/pilotwings-64-recomp/lib/Pilotwings64Decomp"),
    "work": Path(r"C:/Users/andre/n64work/decomp_clean"),
    "ido_bin": Path(r"C:/Users/andre/n64work/idowin/bin"),
    "python": Path(r"C:/Users/andre/n64work/venv/Scripts/python.exe"),
    "mips": Path(os.path.expanduser(r"~/.local/mips64/bin")),
}

# Game-specific and runtime-required asm we wrote (games/pilotwings64/cleanasm).
# bcopy/bzero/sqrtf are recompiled from the game's own code (not provided by
# N64ModernRuntime), so they need real bodies; the rest of libultra's asm is
# reimplemented by the runtime and keeps splat's zero-filled layout.
CLEAN_ASM_FILES = ("entrypoint.s", "header.s", "kernel/decompress_mio0.s",
                   "libultra/libc/bcopy.s", "libultra/libc/bzero.s", "libultra/gu/sqrtf.s")

# Fixed slot sizes for the asset segments (audio_tbl is last and may grow).
RESERVE = {"filetable": 0x2000, "filesys": 0x700000, "audio_seq": 0x40000, "audio_ctl": 0x8000}

DATA_4D4F0 = """.include "macro.inc"
.section .data, "wa"
/* Four words of kernel data (0x10, 0x10, 0x20, 0), n64cleanrecomp. */
dlabel D_8024C540
    .word 0x00000010
    .word 0x00000010
    .word 0x00000020
    .word 0x00000000
enddlabel D_8024C540
"""


def run(cmd, cwd=None, env=None, log=None):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
        raise SystemExit(f"failed: {' '.join(str(c) for c in cmd[:4])}")
    return r


def make_worktree(decomp: Path, work: Path):
    if not (work / "Makefile").exists():
        run(["git", "-C", decomp, "worktree", "add", "--force", "--detach", work, "HEAD"])
    # IDO on Windows: see patches/decomp_ido_windows.py.
    run([sys.executable, REPO / "patches" / "decomp_ido_windows.py", work])


def synthetic_rom(path: Path):
    img = bytearray(P.ROM_SIZE)
    img[0:0x40] = romlib.build_header("PW64 CLEANROOM", b"PW", entry=0x80200050)
    path.write_bytes(bytes(img))


def run_splat(work: Path, py: Path):
    src = work / "config" / "us" / "pilotwings64.us.yaml"
    cfg = work / "config" / "us" / "pilotwings64.clean.yaml"
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"^sha1:.*\n", "", text, flags=re.M)
    text = text.replace("target_path: baserom.us.z64", "target_path: clean_synthetic.z64")
    cfg.write_text(text, encoding="utf-8")
    synthetic_rom(work / "clean_synthetic.z64")
    for d in ("asm", "bin", "build"):
        shutil.rmtree(work / d, ignore_errors=True)
    run([py, "-m", "splat", "split", cfg], cwd=work)


def replace_inputs(work: Path, decomp: Path, assets: dict, reserve=True):
    for rel in CLEAN_ASM_FILES:
        shutil.copy(CLEANASM / rel, work / "asm" / rel)
    (work / "asm" / "data" / "4D4F0.data.s").write_text(DATA_4D4F0)
    # Addresses splat would have found by disassembling retail code.
    shutil.copy(HERE / "layout" / "undefined_syms_auto.txt",
                work / "build" / "splat_out" / "us" / "undefined_syms_auto.txt")
    # Microcode: zero stubs of the original sizes. ipl3: zeros.
    for b in (work / "bin" / "rsp").glob("*.bin"):
        b.write_bytes(bytes(b.stat().st_size))
    (work / "bin" / "ipl3.bin").write_bytes(bytes((work / "bin" / "ipl3.bin").stat().st_size))
    # Clean assets, padded to fixed reservations so the segment offsets baked
    # into the code never move when the assets change size.
    for name, data in assets.items():
        slot = RESERVE.get(name) if reserve else None
        if slot is not None:
            reserve_n = slot
            if len(data) > reserve_n:
                raise SystemExit(f"{name} is {len(data):#x} bytes; reservation is {reserve_n:#x}")
            data = data.ljust(reserve_n, bytes(1))
        (work / "bin" / f"{name}.bin").write_bytes(data)


def build_elf(work: Path, ido_bin: Path, py: Path, mips: Path, jobs: int = 6):
    env = dict(os.environ)
    env["IDO_BIN"] = str(ido_bin)
    env["PATH"] = os.pathsep.join([str(Path(py).parent), str(mips), env.get("PATH", "")])
    for d in ("src", "asm", "bin"):
        for root, dirs, _ in os.walk(work / d):
            (work / "build" / Path(root).relative_to(work)).mkdir(parents=True, exist_ok=True)
    ido_cc = REPO / "tools" / "idowin" / "ido_cc.py"
    cmd = ["make", "RECOMP_BUILD=1", "CC_CHECK=true", f"CC={sys.executable} {ido_cc.as_posix()}",
           "CPP=mips64-elf-gcc", "CPPFLAGS=-E -P -x c -Wno-trigraphs -D_LANGUAGE_ASSEMBLY",
           f"-j{jobs}", "build/pilotwings64.us.elf"]
    run(cmd, cwd=work, env=env)
    return work / "build" / "pilotwings64.us.elf"


def generated_assets(spec_dir=None):
    """Filetable, filesystem and audio segments from the clean generators."""
    from .generate import Spec, generate, DEFAULT_SPEC
    from .audio_gen import generate_audio
    from .pack import build_filesystem, build_filetable
    spec_dir = spec_dir or DEFAULT_SPEC
    files = generate(Spec(spec_dir))
    audio = generate_audio(spec_dir)
    table, fs, _ = build_filesystem(files, audio)
    return {"filetable": build_filetable(table), "filesys": fs,
            "audio_seq": audio["seq"], "audio_ctl": audio["ctl"], "audio_tbl": audio["tbl"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--decomp", type=Path, default=DEFAULTS["decomp"])
    ap.add_argument("--work", type=Path, default=DEFAULTS["work"])
    ap.add_argument("--ido-bin", type=Path, default=DEFAULTS["ido_bin"])
    ap.add_argument("--python", type=Path, default=DEFAULTS["python"])
    ap.add_argument("--mips", type=Path, default=DEFAULTS["mips"])
    ap.add_argument("--out", type=Path, default=REPO / "build" / "pilotwings64.clean.z64")
    ap.add_argument("--dev-retail-ucode", action="store_true",
                    help="DEV ONLY: keep the retail RSP microcode bins (for the audio comparison harness)")
    ap.add_argument("--no-reserve", action="store_true", help="pack asset segments back to back")
    ap.add_argument("--dev-retail-assets", type=Path, default=None,
                    help="DEV ONLY: take the asset segments from a retail ROM to isolate code vs asset "
                         "problems; the output contains retail assets and must not be shared")
    ap.add_argument("--elf-out", type=Path, default=REPO / "build" / "pilotwings64.clean.elf")
    a = ap.parse_args(argv)

    print("worktree ...")
    make_worktree(a.decomp, a.work)
    print("splat (synthetic ROM) ...")
    run_splat(a.work, a.python)
    print("clean assets ...")
    if a.dev_retail_assets:
        r = romlib.load_retail(str(a.dev_retail_assets))
        assets = {"filetable": r[P.SEG_FILETABLE:P.SEG_FILESYS], "filesys": r[P.SEG_FILESYS:P.SEG_AUDIO_SEQ],
                  "audio_seq": r[P.SEG_AUDIO_SEQ:P.SEG_AUDIO_CTL], "audio_ctl": r[P.SEG_AUDIO_CTL:P.SEG_AUDIO_TBL],
                  "audio_tbl": r[P.SEG_AUDIO_TBL:]}
    else:
        assets = generated_assets()
    print("replacing ROM-derived inputs ...")
    replace_inputs(a.work, a.decomp, assets, reserve=not a.no_reserve)
    if a.dev_retail_ucode:
        for b in (a.decomp / "bin" / "rsp").glob("*.bin"):
            shutil.copy(b, a.work / "bin" / "rsp" / b.name)
    print("building ELF with native IDO ...")
    elf = build_elf(a.work, a.ido_bin, a.python, a.mips)
    binpath = a.work / "build" / "pilotwings64.clean.bin"
    run([a.mips / "mips64-elf-objcopy", "-O", "binary", elf, binpath])
    img = bytearray(binpath.read_bytes())
    romlib.finalize_crc(img)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(bytes(img))
    shutil.copy(elf, a.elf_out)
    print(f"wrote {a.out} ({len(img):#x} bytes) and {a.elf_out}")


if __name__ == "__main__":
    main()
