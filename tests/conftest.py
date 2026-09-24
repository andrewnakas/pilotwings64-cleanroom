import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_ROM = os.path.expanduser(os.path.join("~", "Downloads", "Pilotwings 64 (U) [!].zip"))


@pytest.fixture(scope="session")
def retail_rom():
    """Dirty-room fixture: tests using it are skipped without a ROM."""
    path = os.environ.get("PW64_ROM", DEFAULT_ROM)
    if not os.path.exists(path):
        pytest.skip("retail ROM not available (set PW64_ROM)")
    from cleanroom.rom import load_retail
    return load_retail(path)


@pytest.fixture(scope="session")
def clean_image():
    path = os.path.join(ROOT, "build", "pilotwings64.clean.z64")
    if not os.path.exists(path):
        pytest.skip("no clean image built (python -m cleanroom build pilotwings64)")
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture(scope="session")
def clean_segments():
    """Asset segment offsets of the clean image (reserved layout), from the
    ELF's linker symbols; the retail offsets if no ELF is available."""
    from games.pilotwings64 import profile as P
    elf = os.path.join(ROOT, "build", "pilotwings64.clean.elf")
    if os.path.exists(elf):
        try:
            from games.pilotwings64.taint_report import segments_from_elf
            return segments_from_elf(elf)
        except Exception:
            pass
    return {"filetable": P.SEG_FILETABLE, "filesys": P.SEG_FILESYS, "audio_seq": P.SEG_AUDIO_SEQ,
            "audio_ctl": P.SEG_AUDIO_CTL, "audio_tbl": P.SEG_AUDIO_TBL, "end": None}
