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

## Play in the browser

**https://andrewnakas.github.io/pilotwings64-cleanroom/** (WebAssembly; keyboard or gamepad; best in Chrome or Edge)

## Status

**Pilotwings 64 is playable without the ROM on Windows.** The executable is built from the decompilation with a native IDO toolchain, and the image is built from `spec/`. Both are recompiled with N64Recomp and rendered by RT64, with our own audio microcode HLE.

The boot, menus, every vehicle and flight have been tested in game. It also runs in the browser: see [docs/WASM_PORT.md](docs/WASM_PORT.md).

## What is regenerated

Scope chosen for this build: **geometry + coarse colour, SFX envelopes + melodies, UI redrawn with our font.**

| Retail asset | Clean replacement |
|---|---|
| 463 textures | A 4x4 colour grid per TMEM region, a 2-bit alpha or coverage outline, and our own value-noise detail, in each slot's format and layout. Texels are TMEM-swizzled as the loader expects. |
| Text inside textures and blits | Redrawn with our stroke font from label tables (`tex_labels.json`, `hud_labels.json`): the HUD words, menu buttons, class, level and island grids, and the photo prompts. |
| Menu pictures | Rendered from the kept 3D models (`renders.py`, `ui_renders.json`): vehicle icons, pilot portraits and the title-screen pilot group. |
| 9 fonts | Our stroke font in the kept glyph cells: proportional, with real lowercase and unit glyphs. |
| Music and SFX banks | Every sample is resynthesised from a coarse descriptor (per-frame pitch, harmonicity and a 16-band envelope). Bank structure is kept. The melodies (note events) are kept and re-encoded. |
| Text strings | Generated from each string's key. |

These are kept as facts (`"prov": "fact"` in `spec/`):
- terrain, collision and model geometry;
- animations;
- environment colours;
- task and level placements, paths and demos;
- note events.

## Build and play (no ROM)

```sh
pip install numpy pytest
python -m games.pilotwings64.build_code     # clean image + ELF from the decomp (native IDO)
python -m games.pilotwings64.build_port     # N64Recomp + RT64 exe, image copied beside it
python -m pytest tests
```

`python -m cleanroom extract pilotwings64 <rom>` (dirty room) is only needed to regenerate `spec/`, which is committed. The taint check runs with `python -m games.pilotwings64.taint_report <rom> build/pilotwings64.clean.z64 build/pilotwings64.clean.elf`. It fails if any generated stream shares 32 or more bytes with retail expressive data.

## Better assets: briefs and overrides

`python -m cleanroom briefs pilotwings64` writes a folder per texture and blit slot into `work/briefs/`:
- `brief.json`: size, format, alpha, tiling, role and a suggested prompt;
- `guide.png`: the coarse colour layout;
- `mask.png`: the alpha outline.

Feed them to a local image model (img2img or ControlNet), or to an artist. Drop results in `games/pilotwings64/overrides/textures/<hexid>.png` or `overrides/blits/<id>.png`. The build resizes, quantises and swizzles them. [docs/HARNESS.md](docs/HARNESS.md) records what this game taught us about bringing up the next one.

## Legal note

This repository contains no ROM data other than the facts listed above, which are derived from the retail ROM by `extract_spec.py`: geometry, placements and note events. All art, audio samples, fonts and text are generated. Pilotwings 64 is a trademark of Nintendo; this project is not affiliated with Nintendo or Paradigm.

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
