// Exercise the actual enqueue function with a controlled mixer and resampler.
#include "Emu/Rollback/rb_audio_capture.h"
#include <array>
#include <cassert>
#include <cstdint>
using u32 = std::uint32_t;
using u64 = std::uint64_t;
constexpr u32 AUDIO_MAX_CHANNELS_COUNT = 8, AUDIO_BUFFER_SAMPLES = 256;
#define AUDIT(x) assert(x)
struct active_flag { bool value = true; bool observe() const { return value; } };
struct fake_resampler
{
    unsigned calls = 0;
    void put_samples(float* data, u32 n) { ++calls; assert(n == 256 && data[0] == 0); }
};
struct audio_ringbuffer
{
    struct configuration
    {
        u32 num_allocated_buffers = 1, audio_channels = 2, audio_sampling_rate = 48000;
        bool buffering_enabled = true, time_stretching_enabled = false;
    } cfg;
    struct block
    {
        std::array<float, 512> samples{};
        float* get() { return samples.data(); }
    } buffer[1];
    u32 cur_pos = 0, commits = 0;
    float frequency_ratio = 1;
    active_flag backend_active;
    fake_resampler resampler;
    u64 get_enqueued_samples() const { assert(cfg.buffering_enabled); return 960; }
    void commit_data(float* data, u32 n) { ++commits; assert(data[0] == .25f && n == 256); }
    void enqueue(bool enqueue_silence, bool force);
};
// ENQUEUE_INSERT
int main()
{
    audio_ringbuffer r;
    r.buffer[0].samples.fill(.25f);
    r.enqueue(false, false);
    assert(r.commits == 1 && r.resampler.calls == 0);
    r.cfg.time_stretching_enabled = true;
    r.frequency_ratio = .75f;
    r.enqueue(true, false);
    assert(r.resampler.calls == 1);
    r.backend_active.value = false;
    r.enqueue(false, false); // Unaccepted data must not be recorded as accepted.
    assert(r.resampler.calls == 1);
    r.cfg.buffering_enabled = false;
    r.enqueue(true, true);
    assert(r.resampler.calls == 2);
}
