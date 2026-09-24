// Web renderer context. Stage 1: a null renderer that accepts the game's
// display lists and frames so the runtime can boot headless (no RT64 on the
// web). Stage 2 replaces send_dl with an F3D interpreter drawing via WebGL2.
#include <cstdio>
#include <memory>

#include "pw64/renderer.h"

namespace {

class WebContext final : public ultramodern::renderer::RendererContext {
public:
    explicit WebContext(uint8_t* rdram) : rdram_(rdram) {
        setup_result = ultramodern::renderer::SetupResult::Success;
        chosen_api = ultramodern::renderer::GraphicsApi::Auto;
    }
    bool valid() override { return true; }
    bool update_config(const ultramodern::renderer::GraphicsConfig&,
                       const ultramodern::renderer::GraphicsConfig&) override { return true; }
    void enable_instant_present() override {}
    void send_dl(const OSTask* task) override {
        ++dls_;
    }
    void send_dummy_workload(uint32_t) override {}
    void update_screen() override {
        if (++frames_ % 120 == 0) {
            std::fprintf(stderr, "[web] frame %u, display lists %u\n", frames_, dls_);
        }
    }
    void shutdown() override {}
    uint32_t get_display_framerate() const override { return 60; }
    float get_resolution_scale() const override { return 1.0f; }

private:
    uint8_t* rdram_;
    unsigned frames_ = 0;
    unsigned dls_ = 0;
};

}  // namespace

namespace pw64 {
std::unique_ptr<ultramodern::renderer::RendererContext> create_render_context(
        uint8_t* rdram, ultramodern::renderer::WindowHandle, bool) {
    return std::make_unique<WebContext>(rdram);
}
}  // namespace pw64
