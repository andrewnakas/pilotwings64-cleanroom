# WebAssembly port plan

Goal: play the ROM-free Pilotwings 64 build in a browser, served from GitHub Pages, with no ROM and no Nintendo microcode.

## What we have

The desktop build is split into these pieces:

| Piece | Source | Web status |
|---|---|---|
| Game code | `RecompiledFuncs/*.c` (N64Recomp output, about 21 MB of C) | Plain C. Compiles with emcc. |
| Runtime | `N64ModernRuntime/librecomp` and `ultramodern` (C++20) | Game threads are `std::thread`s scheduled one at a time. This maps to Emscripten pthreads. |
| Graphics | RT64 (D3D12/Vulkan/Metal) behind `ultramodern::renderer::RendererContext` | **Replace it.** Write a WebGL2 HLE renderer for the game's GBI (F3D NoN SDK 2.0E). |
| Audio | `patches/files/audio_hle.cpp` (our ABI1 HLE), SDL audio | The HLE is portable C++. SDL2 audio works in Emscripten through WebAudio. |
| Input | SDL gamepad and keyboard | SDL2 in Emscripten covers both the Gamepad API and the keyboard. |
| Assets | `pilotwings64.clean.z64` (9 MB) | Fetched next to the `.wasm`. |

## Architecture

```
index.html + coi-serviceworker.js   (COOP/COEP on GitHub Pages -> SharedArrayBuffer)
pw64.js / pw64.wasm                  emcc -pthread -sPROXY_TO_PTHREAD -sALLOW_MEMORY_GROWTH
  librecomp + ultramodern            unchanged except platform shims (timers, file paths)
  RecompiledFuncs                    unchanged
  web_renderer.cpp                   RendererContext -> F3D interpreter -> WebGL2 (via SDL/EGL)
  audio_hle.cpp + SDL audio          unchanged
  pilotwings64.clean.z64             preloaded or fetched
```

### The WebGL2 F3D renderer (the main work)

These are the parts of F3D the game uses, and each needs implementing:
- matrix stack, viewport, vertex load and transform, lighting (1–2 lights plus ambient), fog;
- `gSP1Triangle`, `gSPCullDisplayList`, branches and segments;
- TMEM emulation for LoadBlock/LoadTile/LoadTLUT, SetTile and SetTileSize: texel formats RGBA16/32, IA4/8/16, I4/8 and CI4/8, with wrap, mirror and clamp;
- colour combiner: a generated GLSL program per combiner and othermode pair, cached;
- render modes: opaque, XLU blend, alpha compare, Z compare/update and decal;
- fill and texture rectangles for 2D blits and fonts, and scissor.

The desktop port's per-frame logs of the combiners and render modes the game actually uses give a finite list to cover first.

## Progress

**Stage 1 is done (2026-09-23).** In headless Edge, the Emscripten build:
- boots the clean image and runs the recompiled game;
- reaches the TITLE state at 60 fps, receiving one display list per frame;
- plays audio through our HLE into WebAudio.

Build commands:

```sh
python ports/wasm/setup_port.py <desktop port> E:/n64web/port        # copy + web patches
emcmake cmake -S ports/wasm -B E:/n64web/build -G Ninja -DPORT=E:/n64web/port
cmake --build E:/n64web/build
python ports/wasm/serve.py E:/n64web/build     # http://localhost:8064/pw64.html
```

Web-specific pieces:
- `web_stubs.cpp`: no mods (LiveRecomp JIT), RT64 hooks stubbed.
- `web_audio.*`: SDL audio calls redirected to a main-thread WebAudio queue.
- `web_renderer.cpp`: null renderer for now; stage 2 replaces it.

## Stages

1. **Headless boot in Node.**
   - emcc build of the runtime and RecompiledFuncs with a null renderer and null audio.
   - Pass: the game reaches the title state and the menus under an input script, with the same state transcript as the desktop.
2. **WebGL2 renderer, 2D first.** Texture rectangles and fills for menus, then 3D triangles, combiners and fog for flight.
3. **Audio and input.** SDL2 audio at 22.05 kHz, resampled by the browser, and Gamepad API plus keyboard mapping.
4. **Packaging.** GitHub Pages workflow, `coi-serviceworker` for cross-origin isolation, and a loading screen.

## Risks

- **Threads.** The runtime runs game threads as real threads. Emscripten needs `PTHREAD_POOL_SIZE` at least as large as the peak thread count, and the main thread must not block (`PROXY_TO_PTHREAD`).
- **Size.** RecompiledFuncs is large; compile with `-O2` and use wasm-opt. The target is a download under 30 MB.
- **Timing.** VI interrupts and frame pacing move to `requestAnimationFrame` or timer threads.
