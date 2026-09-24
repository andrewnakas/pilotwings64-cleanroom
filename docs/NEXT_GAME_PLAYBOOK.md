# Playbook: the next game (first up: Super Mario 64)

**Principle:** tokens go to *decisions, coordination and hard problems*. Everything repeatable is a script that prints a **one-screen summary**, and the model reads summaries, not data.

## 0. Token discipline

| Do | Don't |
|---|---|
| Run long jobs (`build`, `extract`, `pytest`, `emcc`, headless runs) in the background and wait for the notification. | Poll or re-run to "check". |
| Have every tool print a short summary: counts, pass/fail, the worst five. | Cat JSON, specs or logs into the context. |
| Look at **one contact sheet** (`find_text.contact_sheet`, `headless_shot.py`, preview sheets). | Open images one by one. |
| Put fixes into scripts and patch lists (`setup_port.py` PATCHES, label JSON, config JSON). | Hand-edit generated or copied trees. |
| Write edit scripts with the Write tool, then run them. | Run `python - <<EOF` with C strings containing `\n` (it broke several times; the heredoc turns `\n` into a real newline). |
| Use `rg`/`grep -c` for counts, and `sed -n a,bp` for the exact lines needed. | Read whole large files. |
| Use one Agent or Workflow per independent mechanical batch (per-asset classes). | Spawn agents for decisions. |

## 1. Mechanical pipeline (scripts; model reads only the summaries)

| Step | Tool | Summary the model reads |
|---|---|---|
| Unpack ROM, verify CRC | `cleanroom/rom.py`, `codec/*` | size, CRC ok |
| Asset census | new `games/<g>/profile.py` + `extract_spec.py` | counts per asset type |
| Round-trip every format | `tests/test_<g>_retail.py` | n files byte-identical |
| Spec (dirty room) | `python -m cleanroom extract <g> <rom>` | files written, per-type provenance counts |
| Text finder | `find_text.py` | `sheet.png` (one look), then hand-transcribe labels to JSON |
| Generate + pack | `python -m cleanroom build <g>` | image size, segment fits |
| Taint | `taint_report` | failing count, worst run |
| Briefs for image generation | `python -m cleanroom briefs <g>` | n briefs |
| Web port | `ports/wasm/*` (reuse) | build errors (unique, counted), headless states + fps |
| Visual check | `headless_shot.py --query script=...` | one sheet of 6 frames |

## 2. Hard parts (where the model's attention goes)

- **Scope decisions** with the user: what counts as a kept fact versus regenerated.
- **Format traps** (see HARNESS.md §2). On a new game, check these first:
  - TMEM swizzle;
  - tiled or flipped UI;
  - unit glyphs in fonts;
  - coverage-bit effects such as the shadow columns;
  - 32-bit `size_t` in runtime code for the web.
- **Renderer semantics** when a frame looks wrong. Trace the render state with a one-shot filtered print; never dump full display lists.
- **Audio correctness** against the retail microcode (dev comparison harness), before judging content.
- **Integration**: tying the stages together and keeping the clean-room boundary: no retail bytes in outputs, dev images never shared.

## 3. Super Mario 64: what's different, and the plan

The SM64 decomp (`n64decomp/sm64`) is **already a source build**:
- Level geometry, collision, behaviours and object placements are C in the repo.
- `extract_assets.py` pulls only the **binary assets** from the ROM:
  - textures, as PNGs under `textures/`, `actors/` and `levels/`;
  - sound samples and banks (`sound/samples`, `sound/sound_banks`);
  - sequences (`sound/sequences`);
  - the text, skybox and some binary blobs.

So for SM64 the clean room is mostly **"regenerate what `extract_assets.py` writes"**:

1. **Census (mechanical).**
   - Run the decomp's extractor once in the dirty room, and list every extracted file with its type, size and format (from the filename, e.g. `.rgba16.png`, `.ia8.png`).
   - That list *is* the slot spec.
   - Keep per-texture coarse digests (grid plus alpha outline), like PW64.
2. **Textures (mechanical + optional image generation).**
   - Generate each PNG at its slot size and format from the digest (reuse `generate._from_digest` logic and `texfmt`).
   - Briefs and overrides work the same way as PW64, so a local SD/Flux model fills them.
3. **Text / HUD / fonts.**
   - Run `find_text` on the extracted textures.
   - The font glyphs (HUD numbers, dialog font) come from `strokefont`.
   - Dialog text is in the decomp as C (`text/us/*.h`); check the licensing and scope with the user.
4. **Audio.**
   - Samples: descriptors, then resynthesis, then VADPCM (`descriptor.py`, `vadpcm.py`), with bank structure kept.
   - Sequences: keep the note events (user scope) or compose new ones. `cseq`/m64 differ: SM64 uses its own sequence format (m64), which needs a codec plus a round-trip test first.
5. **Build.** The decomp builds natively (reuse the IDO toolchain from PW64: `tools/idowin`). No N64Recomp is needed for a web version: an SM64 **PC or web port** already exists in the community (sm64-port / sm64ex, with an Emscripten target). Point it at the clean assets instead of retail. Alternatively, reuse `ports/wasm` if we go the N64Recomp route. Decide with the user.
6. **Taint scan** over every generated asset against retail. Same `cleanroom/taint.py`.
7. **Web publish** with `make_site.py`-style packaging, `coi-sw.js` only if threads are used, and GitHub Pages.

## 4. Session checklist (copy into the first message of the next session)

1. `profile.py` for SM64. Round-trip or census, with summary only.
2. Scope questions to the user, answered in one question batch.
3. Build the extract → generate → pack/assets → taint scripts, and run them in the background.
4. Build the game with the clean assets, then run it headless (desktop or web) and look at one contact sheet.
5. Fix only what the sheet or summary shows. Commit, and push to a new repo if the user wants.
