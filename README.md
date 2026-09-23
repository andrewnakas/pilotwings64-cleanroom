# n64cleanrecomp

Clean-room asset generation for N64 decompilation and recompilation ports, so a
port can be built and played without the original ROM.

The first target is **Pilotwings 64** ([pilotwings-64-recomp], built on
gcsmith's [Pilotwings64Decomp]).

## How it works

```
retail ROM ──► extract_spec (dirty room) ──► spec/       (committed: structure + kept facts)
                                              │
                                              ▼
                              generate / audio_gen (clean room)
                                              │
                                              ▼
                              pack ──► pilotwings64.clean.z64
                                              │
                         taint_report ◄───────┘  (fails on shared expressive bytes)
```

| Stage | What happens |
|---|---|
| **Dirty room** (`games/<game>/extract_spec.py`, `audio_spec.py`) | The only code that reads the retail ROM. For every asset slot it writes the structure the engine code depends on (IDs, counts, part hierarchies, texture formats and sizes, bounds, loop points). It also writes the **functional facts** we chose to keep: terrain and collision geometry, task and level placements, paths, demo recordings and lookup keys. |
| **Clean room** (`generate.py`, `audio_gen.py`) | Rebuilds every slot from `spec/` alone. `tests/test_cleanroom_rules.py` enforces that it never imports the ROM loader or the extractors. |
| **Pack** (`pack.py`) | Writes the file table, the filesystem and the audio segments at the retail segment offsets. The header is written from scratch. |
| **Taint** (`cleanroom/taint.py`, `streams.py`) | Collects every expressive retail region, including decompressed chunks: texels, meshes, display lists, animation poses, text, glyphs, samples and note data. The build fails if any generated stream shares a run of 32 bytes or more with them. |

## What is regenerated (Pilotwings 64 graybox)

| Retail asset | Clean replacement |
|---|---|
| 463 textures | Procedural texels in each slot's own format and mip layout. Terrain colours come from the kept geometry: water, sand, grass, rock, snow. |
| 101 terrain contours | Kept positions and topology, with new planar UVs and new slope/height shading. |
| 363 models | One box per render state, fitted to the kept bounds, with the same part hierarchy and transforms. |
| 115 animations | Kept timing and part structure, posed at rest from the model's transforms. |
| 102 blits, 9 fonts | Generated panels, and an original stroke font in the kept glyph cells. |
| 439 text strings | Generated from each string's key. |
| Music (31 sequences) + bank | A procedural composer and a new 5-instrument bank, keeping each sequence's tempo, length and looping. |
| 120 SFX + bank | Synthesised effects with the same envelopes, key maps and loop points, encoded with our own VADPCM encoder. |

Kept as facts, because the user chose this scope: terrain geometry, task and level placements, paths, demo recordings and the text lookup keys. These are listed separately in the spec (`"prov": "fact"`) so they can be replaced with original designs later.

## Use

```sh
pip install numpy pytest
python -m cleanroom extract pilotwings64 "<retail rom or zip>"   # once, dirty room (spec/ is committed)
python -m cleanroom build pilotwings64                            # -> build/pilotwings64.clean.z64
python -m cleanroom taint pilotwings64 "<retail rom>" build/pilotwings64.clean.z64
python -m cleanroom preview pilotwings64 build/pilotwings64.clean.z64
python -m pytest tests
```

A build needs no ROM. Tests that need one read `PW64_ROM`, or `~/Downloads/Pilotwings 64 (U) [!].zip` if that is unset, and skip when neither exists.

Running the game: see [docs/STATUS.md](docs/STATUS.md). The code segment still has to come from the decompilation build (milestone M4). `--code-from-retail` exists only for local asset-swap tests, and the image it produces must not be shared.

## Layout

```
cleanroom/                 game-agnostic: MIO0, IFF, ROM/CRC, N64 texel formats, GBI decode,
                           ALBank/ALSeqFile, compressed MIDI, VADPCM, synth, stroke font, taint
games/pilotwings64/        profile, format codecs, dirty-room extractors, clean-room generators,
                           packer, taint streams, previews, spec/
patches/                   idempotent patches for the recomp (clean-image runtime support)
external/                  pilotwings-64-recomp checkout (git-ignored)
```

[pilotwings-64-recomp]: https://github.com/danielgomesvieira2000/pilotwings-64-recomp
[Pilotwings64Decomp]: https://github.com/gcsmith/Pilotwings64Decomp
