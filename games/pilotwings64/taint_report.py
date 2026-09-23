"""Clean-room contamination report.

    python -m games.pilotwings64.taint_report <retail rom> <clean image>

Fails (exit 1) if any *generated* stream of the clean image shares a run of
>= taint.FAIL_RUN bytes with retail expressive data. Kept facts are scanned
too and listed for information only.
"""
import sys

from cleanroom import taint
from cleanroom.rom import load_retail
from . import streams


def report(retail, clean, out=print):
    index = taint.build_index(s for _, s in streams.expressive_streams(retail))
    gen = taint.scan(index, streams.expressive_streams(clean))
    bad = [h for h in gen if h[3] >= taint.FAIL_RUN]
    out(f"generated streams: {len(gen)} with coincidental short matches, {len(bad)} failing (run >= {taint.FAIL_RUN} B)")
    for h in sorted(gen, key=lambda h: -h[3])[:10]:
        out(f"  {h[0]}: {h[2]} windows, longest run {h[3]} B")
    return bad


def main(argv):
    bad = report(load_retail(argv[1]), open(argv[2], "rb").read())
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv)
