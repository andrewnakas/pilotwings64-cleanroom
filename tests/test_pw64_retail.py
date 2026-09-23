"""Dirty-room tests: codecs round-trip every retail file byte-exactly, and the
clean image shares no expressive content with retail."""
from cleanroom import iff
from games.pilotwings64 import profile as P
from games.pilotwings64.formats import engine, misc


def test_container_roundtrip(retail_rom):
    for e, raw in P.read_files(retail_rom):
        assert iff.build_form(iff.parse_form(raw, keep_raw=True), reuse_raw=True) == raw


def test_codecs_roundtrip(retail_rom):
    n = 0
    for e, raw in P.read_files(retail_rom):
        f = iff.parse_form(raw)
        for c in f.chunks:
            if f.type in engine.CODECS and c.tag == "COMM":
                parse, build = engine.CODECS[f.type]
                assert build(parse(c.data)) == c.data, (e, c.tag)
                n += 1
            elif f.type == "UVBT" and c.tag == "COMM":
                assert misc.build_uvbt(misc.parse_uvbt(c.data)) == c.data
            elif f.type == "UVAN" and c.tag == "PART":
                assert misc.build_uvan_part(misc.parse_uvan_part(c.data)) == c.data
            elif f.type == "UVFT" and c.tag == "BITM":
                assert misc.build_bitm(misc.parse_bitm(c.data)) == c.data
    assert n > 1000


def test_crc_matches_retail_header(retail_rom):
    import struct
    from cleanroom.rom import cic6102_crc
    assert cic6102_crc(retail_rom) == struct.unpack_from(">II", retail_rom, 0x10)


def test_no_contamination(retail_rom, clean_image):
    from games.pilotwings64.taint_report import report
    assert report(retail_rom, clean_image, out=lambda *_: None) == []
