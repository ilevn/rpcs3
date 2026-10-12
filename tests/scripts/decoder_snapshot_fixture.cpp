// Synthetic memory only: no game code, assets, or captured game memory.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
constexpr u32 page = 0x20000;
constexpr u32 object = page + 0x300;
constexpr u32 thread_id = 42;

namespace vm
{
constexpr int page_readable = 1;
bool check_addr(u32 address, int, u32 size = 1)
{
	return address >= page && u64{address} + size <= page + 0x1000;
}
}

namespace rb
{
struct range_t { u32 begin, end; };
std::vector<range_t> g_excluded, g_sync_excluded, g_fixed_ranges;
std::vector<u32> g_fifo_blocks;
std::unordered_map<u32, u32> g_cal_index;
u64 g_layout_gen = 1;
struct logger
{
	template <typename... Args> void success(const char*, Args...) {}
} rb_log;

#include "exclusions.inc"
#include "async.inc"

struct page_unit
{
	u32 page;
	std::vector<std::pair<u16, u16>> pieces;
};
struct page_store
{
	std::vector<page_unit> units;
	u64 pieces_gen = 0;
#include "pieces.inc"
#include "refresh.inc"
};
}

static std::mutex g_rb_thread_ranges_mutex;
static std::map<u32, std::vector<std::pair<u32, u32>>> g_rb_thread_ranges;
struct entry_t { u32 addr, rtoc; };

void register_thread(const std::string& ppu_name, u64 arg,
	entry_t entry = {0x006b4180, 0x0096a8b0}, u32 tid = thread_id)
{
#include "registration.inc"
}

void exit_thread(u32 id)
{
	struct { u32 id; } ppu{id};
#include "exit.inc"
}

using memory = std::array<u8, 0x1000>;
void put(memory& bytes, u32 address, u32 value)
{
	std::memcpy(bytes.data() + address - page, &value, sizeof(value));
}
u32 get(const memory& bytes, u32 address)
{
	u32 value;
	std::memcpy(&value, bytes.data() + address - page, sizeof(value));
	return value;
}
void restore(rb::page_store& store, memory& live, const memory& saved)
{
	// Match state_net_load's boundary drain and page_store::copy's refresh.
	rb::apply_async_exclusions();
	store.refresh();
	for (const auto& [offset, size] : store.units.front().pieces)
	{
		std::memcpy(live.data() + offset, saved.data() + offset, size);
	}
}

int main()
{
	rb::g_fixed_ranges = {{page, page + 0x1000}};
	rb::page_store store{{{page, {}}}};
	memory old_snapshot{};
	put(old_snapshot, object - 4, 11);
	put(old_snapshot, object + 0x40, 22);
	memory live = old_snapshot;
	constexpr std::array<u32, 4> callback_offsets{0x20, 0x24, 0x34, 0x38};
	for (u32 offset : callback_offsets) put(live, object + offset, 0x12340000 + offset);
	restore(store, live, old_snapshot);
	for (u32 offset : callback_offsets) assert(get(live, object + offset) == 0);
	std::cout << "PASS: negative control restores stale null callback data\n";

	register_thread("bnusCoreDecoderServerThread", object);
	assert(g_rb_thread_ranges.at(thread_id) == (std::vector<std::pair<u32, u32>>{{object, object + 0x40}}));
	assert(rb::g_excluded.empty()); // registration queues work until a boundary
	for (u32 offset : callback_offsets) put(live, object + offset, 0x12340000 + offset);
	put(live, object - 4, 99);
	put(live, object + 0x40, 99);
	restore(store, live, old_snapshot); // old snapshots must also obey new exclusions
	for (u32 offset : callback_offsets) assert(get(live, object + offset) == 0x12340000 + offset);
	assert(get(live, object - 4) == 11 && get(live, object + 0x40) == 22);
	std::cout << "PASS: live callback state survives old snapshot; adjacent state rolls back\n";

	// Calibrated-page layout is the online path, and must have the same behavior.
	rb::g_fixed_ranges.clear();
	rb::g_cal_index[page] = 0;
	++rb::g_layout_gen;
	restore(store, live, old_snapshot);
	for (u32 offset : callback_offsets) assert(get(live, object + offset) == 0x12340000 + offset);
	std::cout << "PASS: calibrated pages preserve the decoder record\n";

	// Another exclusion must survive removal of this thread-owned exact range.
	rb::state_exclude(object + 0x30, object + 0x50, "other live owner");
	exit_thread(thread_id);
	assert(g_rb_thread_ranges.empty());
	rb::apply_async_exclusions();
	assert(rb::g_excluded.size() == 1);
	assert(rb::g_excluded.front().begin == object + 0x30);
	// Save fresh data after reuse: formerly excluded bytes of OLD snapshots are
	// not guaranteed meaningful by the current snapshot lifecycle machinery.
	memory reused_snapshot = live;
	put(reused_snapshot, object + 0x20, 77);
	put(live, object + 0x20, 88);
	put(live, object + 0x34, 99);
	restore(store, live, reused_snapshot);
	assert(get(live, object + 0x20) == 77);
	assert(get(live, object + 0x34) == 99);
	std::cout << "PASS: thread exit restores coverage without removing overlapping owner\n";

	const auto reject = [&](const std::string& name, u64 address, entry_t entry)
	{
		register_thread(name, address, entry);
		assert(g_rb_thread_ranges.empty());
		rb::apply_async_exclusions();
		assert(rb::g_excluded.size() == 1);
	};
	reject("different_thread", object, {0x006b4180, 0x0096a8b0});
	reject("bnusCoreDecoderServerThread", object, {0x006b4184, 0x0096a8b0});
	reject("bnusCoreDecoderServerThread", object, {0x006b4180, 0x0096a8b4});
	reject("bnusCoreDecoderServerThread", 0, {0x006b4180, 0x0096a8b0});
	reject("bnusCoreDecoderServerThread", 0xbfffffe0, {0x006b4180, 0x0096a8b0});
	reject("bnusCoreDecoderServerThread", u64{object} + (u64{1} << 32), {0x006b4180, 0x0096a8b0});
	reject("bnusCoreDecoderServerThread", page + 0xff0, {0x006b4180, 0x0096a8b0});
	std::cout << "PASS: unrelated entrypoints, invalid arguments, and partial mappings rejected\n";

	register_thread("bnusCoreDecoderServerThread", object);
	rb::apply_async_exclusions();
	assert(g_rb_thread_ranges.count(thread_id) == 1 && rb::g_excluded.size() == 2);
	exit_thread(thread_id);
	exit_thread(thread_id); // duplicate exit is harmless
	rb::apply_async_exclusions();
	assert(g_rb_thread_ranges.empty() && rb::g_excluded.size() == 1);
	std::cout << "PASS: reused object can be registered and released again\n";
}
