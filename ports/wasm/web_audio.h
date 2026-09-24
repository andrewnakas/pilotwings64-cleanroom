// Force-included into the port's callbacks.cpp for the web build: its SDL
// audio calls are redirected to a WebAudio queue on the browser main thread
// (SDL2's Emscripten audio must live on the main thread, but the runtime's
// audio runs on a worker under PROXY_TO_PTHREAD).
#pragma once
#include <SDL.h>

#ifdef __cplusplus
extern "C" {
#endif
SDL_AudioDeviceID pw64web_audio_open(const SDL_AudioSpec* want, SDL_AudioSpec* have);
int pw64web_audio_queue(const void* data, Uint32 bytes);
Uint32 pw64web_audio_queued_bytes(void);
#ifdef __cplusplus
}
#endif

#define SDL_GetDefaultAudioInfo(name, spec, capture) (-1)
#define SDL_InitSubSystem(flags) (((flags) == SDL_INIT_AUDIO) ? 0 : SDL_InitSubSystem(flags))
#define SDL_OpenAudioDevice(dev, cap, want, have, allowed) pw64web_audio_open(want, have)
#define SDL_PauseAudioDevice(dev, pause) ((void)0)
#define SDL_CloseAudioDevice(dev) ((void)0)
#define SDL_QueueAudio(dev, data, bytes) pw64web_audio_queue(data, bytes)
#define SDL_GetQueuedAudioSize(dev) pw64web_audio_queued_bytes()
