// Dependency shell around the actual Cubeb callback extracted by the test.
#include "Emu/Rollback/rb_audio_capture.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cstring>
#include <functional>
#include <mutex>
using u32 = std::uint32_t;
using u8 = std::uint8_t;
#define ensure(x) assert(x)
constexpr int CUBEB_ERROR = -1;
struct cubeb_stream {};
struct logger { template <typename... T> void error(T...) {} } Cubeb;
struct value { u32 v; u32 observe() const { return v; } operator u32() const { return v; } };
struct CubebBackend {
    static long data_cb(cubeb_stream*, void*, const void*, void*, long);
    std::timed_mutex m_cb_mutex;
    value m_reset_req{0}, full_sample_size{4};
    bool m_playing = true;
    cubeb_stream* m_stream = nullptr;
    std::function<u32(u32, void*)> m_write_callback;
    std::array<u8, 32> m_last_sample{};
    u32 get_sampling_rate() const { return 48000; }
    u32 get_channels() const { return 2; }
    u32 get_sample_size() const { return 2; }
};
// CALLBACK_INSERT
int main() {
    CubebBackend backend;
    cubeb_stream stream;
    backend.m_stream = &stream;
    std::array<u8, 16> output{};
    backend.m_write_callback = [](u32 n, void* out) { std::memset(out, 0x12, n); return n; };
    assert(CubebBackend::data_cb(&stream, &backend, nullptr, output.data(), 4) == 4);
    backend.m_write_callback = [](u32, void*) { return 0; }; // deliberately empty producer
    assert(CubebBackend::data_cb(&stream, &backend, nullptr, output.data(), 4) == 4);
    assert(std::all_of(output.begin(), output.end(), [](u8 b){ return b == 0x12; }));
    backend.m_playing = false;
    assert(CubebBackend::data_cb(&stream, &backend, nullptr, output.data(), 4) == 4);
    assert(std::all_of(output.begin(), output.end(), [](u8 b){ return b == 0; }));
}
