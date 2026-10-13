#include "rb_voice_runtime.h"
#include <array>
#include <cassert>
#include <iostream>
#include <random>
#include <unordered_map>
#include <vector>
using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
namespace voice_runtime = rb::voice_runtime;
using namespace rb::voice_runtime;
struct page_unit
{
    u32 page;
    u8* data;
    std::vector<std::pair<u16, u16>> pieces;
};
struct store
{
    std::vector<page_unit> units;
    std::unordered_map<u32, u32> index;
    const std::unordered_map<u32, u64>* skip_pages = nullptr;
#include "read.inc"
};
int main()
{
    std::array<u8, voice_size> live{}, saved{};
    live[0x1a0] = 1;
    live[0x1af] = 1;
    live[0x1a7] = 17;
    saved = live;
    live[0] = 99; // playback has advanced since the snapshot
    assert(unchanged_active_voice(live.data(), saved.data()));
    for (u32 i = runtime_size; i < voice_size; ++i)
    {
        saved[i] ^= 1;
        assert(!unchanged_active_voice(live.data(), saved.data()));
        saved[i] ^= 1;
    }
    live[0x1a0] = saved[0x1a0] = 0;
    assert(!unchanged_active_voice(live.data(), saved.data()));
    live[0x1a0] = saved[0x1a0] = 1;
    live[0x1af] = saved[0x1af] = 0;
    assert(!unchanged_active_voice(live.data(), saved.data()));
    live[0x1af] = saved[0x1af] = 1;

    // A real restore piece: the negative control rewinds playback. The
    // experiment leaves playback live but still restores adjacent memory.
    std::array<u8, voice_size + 32> destination{}, source{};
    destination.fill(9);
    source.fill(3);
    const std::array<u8, 1> keep{1};
    auto restore = [&](std::span<const u8> mask)
    {
        restore_spans(0x10000, destination.size(), 0x10010, mask, [&](u32 off, u32 n)
        { std::memcpy(destination.data() + off, source.data() + off, n); });
    };
    restore({});
    assert(destination == source);
    destination.fill(9);
    restore(keep);
    for (u32 i = 0; i < destination.size(); ++i)
        assert(destination[i] == (i >= 16 && i < 16 + runtime_size ? 9 : 3));

    // Byte-level oracle over randomized piece boundaries, including pages
    // crossing voices, voice tails, empty masks and addresses near UINT32_MAX.
    std::mt19937 rng(713);
    for (u32 trial = 0; trial < 10000; ++trial)
    {
        const u32 core = trial % 2 ? 0x20fa0 : 0xffffb000;
        std::array<u8, 8> mask;
        for (auto& v : mask) v = rng() % 2;
        const u32 begin = core - 1024 + rng() % (8 * voice_size + 2048);
        const u32 length = rng() % 4097;
        std::vector<u8> written(length);
        restore_spans(begin, length, core, mask, [&](u32 off, u32 n)
        {
            assert(n && u64{off} + n <= length);
            for (u32 i = off; i < off + n; ++i) assert(++written[i] == 1);
        });
        for (u32 i = 0; i < length; ++i)
        {
            const u64 address = u64{begin} + i;
            bool excluded = false;
            for (u32 v = 0; v < mask.size(); ++v)
                excluded |= mask[v] && address >= u64{core} + v * voice_size &&
                    address < u64{core} + v * voice_size + runtime_size;
            assert(written[i] == !excluded);
        }
    }

    std::array<u8, 0x2000> page1{}, page2{};
    page1.fill(1); page2.fill(2);
    store s{{{0x1000, page1.data(), {{0, 0x1000}}}, {0x2000, page2.data(), {{0, 0x1000}}}},
            {{0x1000, 0}, {0x2000, 1}}, nullptr};
    std::array<u8, voice_size> out{};
    assert(s.read_saved_voice(1, 0x1f80, out));
    for (u32 i = 0; i < out.size(); ++i) assert(out[i] == (i < 0x80 ? 1 : 2));
    s.units[1].pieces = {{0, 16}, {17, 0xfff - 17}};
    assert(!s.read_saved_voice(1, 0x1f80, out)); // one excluded byte
    s.units[1].pieces = {{0, 16}, {16, 0xff0}};
    assert(s.read_saved_voice(1, 0x1f80, out));
    std::unordered_map<u32, u64> held{{0x2000, 1}};
    s.skip_pages = &held;
    assert(!s.read_saved_voice(1, 0x1f80, out));
    s.skip_pages = nullptr;
    s.index.erase(0x2000);
    assert(!s.read_saved_voice(1, 0x1f80, out));
    std::cout << "Voice runtime: negative control, all control bytes, inactive/reused voices, 10000 range cases, partial/held/missing pages passed\n";
}
