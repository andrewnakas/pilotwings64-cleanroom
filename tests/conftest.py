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
