"""Clean-room contamination report.

    python -m games.pilotwings64.taint_report <retail rom> <clean image> [clean elf]

Fails (exit 1) if any *generated* stream of the clean image shares a run of
>= taint.FAIL_RUN bytes with retail expressive data. Kept facts are scanned
too and listed for information only.
"""
import sys

from cleanroom import taint
from cleanroom.rom import load_retail
from . import streams


def segments_from_elf(elf_path):
    """Asset segment ROM offsets of a clean image, from its linker symbols."""
    import subprocess
    nm = subprocess.run(["mips64-elf-nm", elf_path], capture_output=True, text=True, check=True).stdout
    sym = {}
    for line in nm.splitlines():
        parts = line.split()
        if len(parts) == 3:
            sym[parts[2]] = int(parts[0], 16)
    return {"filetable": sym["filetable_ROM_START"], "filesys": sym["filesys_ROM_START"],
            "audio_seq": sym["audio_seq_ROM_START"], "audio_ctl": sym["audio_ctl_ROM_START"],
            "audio_tbl": sym["audio_tbl_ROM_START"], "end": sym["audio_tbl_ROM_END"]}


def report(retail, clean, out=print, clean_segments=None):
    index = taint.build_index(s for _, s in streams.expressive_streams(retail))
    gen = taint.scan(index, streams.expressive_streams(clean, clean_segments))
    bad = [h for h in gen if h[3] >= taint.FAIL_RUN]
    out(f"generated streams: {len(gen)} with coincidental short matches, {len(bad)} failing (run >= {taint.FAIL_RUN} B)")
    for h in sorted(gen, key=lambda h: -h[3])[:10]:
        out(f"  {h[0]}: {h[2]} windows, longest run {h[3]} B")
    return bad


def main(argv):
    seg = segments_from_elf(argv[3]) if len(argv) > 3 else None
    bad = report(load_retail(argv[1]), open(argv[2], "rb").read(), clean_segments=seg)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv)
