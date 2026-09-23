"""Work around a crash in the Windows build of ido-static-recomp's cfe.

cfe (IDO 5.3, decompals Windows release v1.2) dies with signal 11 on `//`
comments that contain quote characters, e.g.
    // asm-process isn't supported outside of IDO
    MODEL_X = 0x158, // 3D "6" in intro PW64 logo
The Linux build does not. Comments do not affect code generation, so this
removes the text of every `//` comment (outside string/char literals and
block comments) in the decomp's src/ and include/. Line numbers are kept.
Idempotent.

    python patches/decomp_ido_windows.py [path/to/Pilotwings64Decomp]
"""
import sys
from pathlib import Path


def strip_line_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            # Keep a backslash continuation if the comment ended with one.
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(text[i:j])
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parents[1] / "external" / "pilotwings-64-recomp" / "lib" / "Pilotwings64Decomp")
    changed = 0
    for sub in ("src", "include"):
        for p in (root / sub).rglob("*"):
            if p.suffix not in (".c", ".h", ".inc"):
                continue
            raw = p.read_bytes().decode("utf-8", "surrogateescape")
            new = strip_line_comments(raw)
            if new != raw:
                assert new.count("\n") == raw.count("\n"), p
                p.write_bytes(new.encode("utf-8", "surrogateescape"))
                changed += 1
    print(f"{root}: {changed} files adjusted")


if __name__ == "__main__":
    main(sys.argv)
