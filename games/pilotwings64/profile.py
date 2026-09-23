"""Pilotwings 64 (U) layout and file-table model.

Layout facts come from the decomp's splat config (config/us/pilotwings64.us.yaml)
and docs/pilotwings64_filesystem.md in gcsmith/Pilotwings64Decomp.
"""
import struct
from dataclasses import dataclass
from typing import List

from cleanroom import iff

GAME_ID = "pilotwings64"
RETAIL_SHA1 = "ec771aedf54ee1b214c25404fb4ec51cfd43191a"
ROM_SIZE = 0x800000

# Retail segment starts (ROM offsets). The clean image keeps the same order;
# offsets may move once code is linked from source (M4).
SEG_FILETABLE = 0x0DE720
SEG_FILESYS = 0x0DF5B0
SEG_AUDIO_SEQ = 0x618B70
SEG_AUDIO_CTL = 0x62D460
SEG_AUDIO_TBL = 0x6314D0

# Engine tags have their own ID spaces; everything else is a "user file"
# indexed in table order (uvMemInitBlockHdr in src/kernel/texture.c).
ENGINE_TAGS = ("UVSY", "UVAN", "UVFT", "UVBT", "UVMD", "UVCT", "UVTX", "UVEN",
               "UVLT", "UVLV", "UVSQ", "UVTR", "UVTP", "UVSX")


@dataclass
class FileEntry:
    index: int          # position in TABL
    tag: str            # TABL tag
    size: int           # TABL size (bytes reserved in the filesystem)
    offset: int         # offset relative to the filesystem base
    kind_index: int     # ID within its tag's space (user files share one space)

    @property
    def space(self):
        return self.tag if self.tag in ENGINE_TAGS else "USER"


def parse_table(tabl: bytes) -> List[FileEntry]:
    entries = []
    counters = {}
    off = 0
    for i in range(len(tabl) // 8):
        tag_b, size = struct.unpack_from(">4sI", tabl, i * 8)
        if tag_b == b"\0\0\0\0":
            tag = "\0\0\0\0"
            kind = -1
        else:
            tag = tag_b.decode("latin-1")
            space = tag if tag in ENGINE_TAGS else "USER"
            kind = counters.get(space, 0)
            counters[space] = kind + 1
        entries.append(FileEntry(i, tag, size, off, kind))
        off += size
    return entries


def build_table(entries) -> bytes:
    """entries: iterable of (tag, size)."""
    return b"".join(struct.pack(">4sI", t.encode("latin-1"), s) for t, s in entries)


def read_filetable(image: bytes, filetable_off: int = SEG_FILETABLE) -> List[FileEntry]:
    form = iff.parse_form(image, filetable_off)
    assert form.type == "UVRM", form.type
    return parse_table(form.first("TABL").data)


def read_files(image: bytes, filetable_off: int = SEG_FILETABLE,
               filesys_off: int = SEG_FILESYS):
    """Yield (FileEntry, raw bytes of its reserved region)."""
    for e in read_filetable(image, filetable_off):
        start = filesys_off + e.offset
        yield e, image[start:start + e.size]
