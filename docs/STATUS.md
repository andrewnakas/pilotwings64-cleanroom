# Status (2026-09-23)

## Done (M1–M3)

**Format layer**
- Byte-exact round-trip for all 1272 retail files: containers, all engine COMM chunks, blits, animations and font metrics.
- The CIC-6102 CRC implementation reproduces the retail header.

**Spec**
- `games/pilotwings64/spec/` holds 1272 slot specs plus `audio.json` (11 MB).

**Graybox generation (fully deterministic)**
- Textures, terrain, models, animations, blits, fonts, text, environments.
- Music: composer and a new bank. SFX: synthesised, VADPCM-encoded.

**Pack**
- The filesystem is 4.8 MB (the retail slot is 5.4 MB).
- Every segment fits the retail offsets, so the stock executable can load the image.

**Taint**
- 0 failing streams. The longest coincidental shared run is 19 bytes, in smooth gradient texels.

**Tests**
- 14 pass (`python -m pytest tests`).

**Runtime patch**
- `patches/pw64_clean_runtime.py` adds `--clean <image>`, or auto-detects `pilotwings64.clean.z64` beside the exe.
- It applies cleanly and is idempotent. **Not yet compiled.**

## Blocked: WSL

The recomp's toolchain runs under WSL: IDO 5.3 for the decomp, N64Recomp, RSPRecomp and MIPS clang. WSL is not installed on this machine. From an admin shell:

```
wsl --install -d Ubuntu      (reboot)
```

Then follow `external/pilotwings-64-recomp/docs/BUILDING.md`.

## Next

1. **M0 baseline.** Build the stock recomp with the retail ROM.
2. **Asset-swap test.**
   - Apply `patches/pw64_clean_runtime.py` and rebuild.
   - `python -m cleanroom build pilotwings64 --code-from-retail <rom> --out build/pw64.swaptest.z64`
   - Run with `--clean build/pw64.swaptest.z64` (local only; this image contains retail code).
   - Check: boot, menus, each island in free flight, one task per vehicle, audio.
3. **M4 zero-ROM code.**
   - Decomp build mode without `make extract`. The code is 100% C. Replace the hasm (`entrypoint`, `decompress_mio0`, libultra asm) with ultralib sources or clean C.
   - Stub the RSP textbins and confirm RT64's GBI detection.
   - Clean C++ HLE of the libultra audio ABI instead of RSPRecomp'd aspMain.
   - `pack --code build/code.bin`.
4. **M5 authoring.** `overrides/` importers: PNG→UVTX, glTF→UVMD, WAV→bank sound, MIDI→seq, text→ADAT.

## Known graybox limits

- Models are boxes. Billboards and trees become cards or boxes, and transparency is a soft ellipse.
- Text is derived from string keys (for example "Erase sel2"), not written copy.
- Music and SFX are generic. SFX are chosen by loop and length only, with no knowledge of what each sound is.
- None of it has been seen in game yet: the in-game test waits on WSL.
