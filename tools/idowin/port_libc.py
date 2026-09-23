"""Derive a native-Windows libc_impl.c from ido-static-recomp's upstream file.

    python tools/idowin/port_libc.py <ido-static-recomp dir> <out.c>

The upstream Windows release is a Cygwin build whose memory emulation fails
on any translation unit over ~32 KB of tokens (cfe reports "Unexpected
End-of-file"). This produces a variant for clang/MSVC using posix_win.h:
guest memory is one committed VirtualAlloc block, files are binary.
"""
import re
import sys
from pathlib import Path


def port(src: str) -> str:
    # POSIX headers -> our shim.
    s = src
    for h in ("sys/mman.h", "sys/types.h", "sys/stat.h", "sys/times.h", "sys/file.h",
              "sys/wait.h", "fcntl.h", "utime.h", "unistd.h", "signal.h", "libgen.h"):
        s = s.replace(f"#include <{h}>\n", "")
    s = s.replace('#include "libc_impl.h"', '#include "posix_win.h"\n#include "libc_impl.h"', 1)

    # struct stat on MSVC has no timespec members.
    s = re.sub(r"statbuf->st_(a|m|c)tim\.tv_sec", r"statbuf->st_\1time", s)
    s = re.sub(r"statbuf->st_(a|m|c)tim\.tv_nsec", "0", s)

    # Binary I/O everywhere, including the standard streams.
    s = s.replace("    progname = argv[0];\n",
                  "    progname = argv[0];\n    _set_fmode(_O_BINARY);\n"
                  "    _setmode(0, _O_BINARY);\n    _setmode(1, _O_BINARY);\n    _setmode(2, _O_BINARY);\n", 1)
    s = s.replace("    int fd = open(pathPtr, f, mode);", "    int fd = open(pathPtr, f | _O_BINARY, mode);", 1)
    return s


def main(argv):
    root = Path(argv[1])
    out = Path(argv[2])
    src = (root / "libc_impl.c").read_text(encoding="utf-8")
    ported = port(src)
    assert "_O_BINARY, mode)" in ported, "open() anchor not found"
    assert "_set_fmode" in ported, "main() anchor not found"
    out.write_text(ported, encoding="utf-8", newline="\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv)
