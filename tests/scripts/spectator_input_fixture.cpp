#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <mutex>
#include "rb_spectator_diagnostics.h"
namespace spectator_diagnostics = rb::online::spectator_diagnostics;
#include <string>
#include <string_view>
#include <thread>
#include <vector>

using u8 = uint8_t;
using u32 = uint32_t;
using u64 = uint64_t;
using s32 = int32_t;
constexpr u32 umax = UINT32_MAX;

static void check(bool condition, const char* message)
{
	if (!condition)
	{
		std::cerr << "FAIL: " << message << '\n';
		std::exit(1);
	}
}

namespace vm
{
	std::vector<u8> memory(0x00C10000);
	constexpr int page_readable = 1;
	bool check_addr(u32 a, int, u32 size = 4) { return a >= 0x10000 && uint64_t(a) + size <= memory.size(); }
	u8 read8(u32 a) { return memory.at(a); }
	void write8(u32 a, u8 v) { memory.at(a) = v; }
	u32 read32(u32 a)
	{
		return (u32(read8(a)) << 24) | (u32(read8(a + 1)) << 16) | (u32(read8(a + 2)) << 8) | read8(a + 3);
	}
	void write32(u32 a, u32 v)
	{
		for (u32 i = 0; i < 4; ++i) write8(a + i, u8(v >> (24 - 8 * i)));
	}
	template <typename T> T* get_super_ptr(u32 a) { return reinterpret_cast<T*>(&memory.at(a)); }
}

struct ppu_thread { u64 lr = 0; u64 gpr[32]{}; };
struct logger
{
	std::vector<std::string> notices;
	template <typename... T> void notice(const char* text, T...) { notices.emplace_back(text); }
	template <typename... T> void warning(const char*, T...) {}
	template <typename... T> void error(const char*, T...) {}
} rb_online_log;
namespace fmt { template <typename... T> void append(std::string&, const char*, T...) {} }
bool state_stress_ready() { return true; }
bool state_net_ready() { return true; }
bool is_resimulating() { return false; }
bool predict_game_mode() { return true; }
bool run_receiver(ppu_thread&) { return false; }
void state_exclude(u32, u32, const char*) {}
void note_caller(const char*, ppu_thread&, u32) {}
void rb_timing(const char*, u32) {}
void get_seq(u32 (&seq)[2]) { seq[0] = 100; seq[1] = 0; }

#include "roles.inc"
#include "read_entry.inc"
#include "slot_addr.inc"
#include "flag_addr.inc"
#include "diagnostics.inc"
// Payload prediction is outside this test: repeat the last confirmed entry.
entry_t predict_entry(u32 mgr, u32 i, u32 sim) { return read_entry(slot_addr(mgr, i, sim - 1)); }
#include "hle_input_available.inc"
#include "hle_store_input.inc"

constexpr u32 input = 0x10000, payload = 0x90000;
ppu_thread ppu;
std::chrono::steady_clock::time_point test_time = std::chrono::steady_clock::now();

namespace side_heap
{
	u32 calls = 0, target = 0;
	std::vector<u64> arguments;
	u64 result = 0;
	template <typename F> void with_frame(ppu_thread&, F&& f) { f(0); }
	u64 call(ppu_thread&, u32 addr, std::initializer_list<u64> args)
	{
		++calls;
		target = addr;
		arguments.assign(args);
		if (addr == 0x45e6f8 && arguments[0])
		{
			vm::write8(static_cast<u32>(arguments[0]) + 0xc, 17);
			vm::write32(static_cast<u32>(arguments[0]) + 0x10, 850);
		}
		return result;
	}
}
#include "hle_spectator_request.inc"
#include "hle_spectator_receive.inc"

void setup(u32 local)
{
	std::fill(vm::memory.begin(), vm::memory.end(), 0);
	clear_prediction_state();
	vm::write32(mgr_pointer, input);
	vm::write32(input + 8, 1);
	vm::write32(input + 0x10, 1);
	vm::write32(input + 0x14, local);
	for (u32 i = 0; i < 2; ++i)
	{
		vm::write32(input + 0x1c + i * 0x10, 0x20000 + i * 0x30000);
		vm::write32(input + 0x20 + i * 0x10, 0x20000 + i * 0x30000 + ring * entry_size);
		vm::write32(input + 0x3c + i * 0x10, 0x80000 + i * 0x1000);
	}
	g_max_received = 0;
	g_fight_frames = 30;
	g_sim_at[99] = 1;
	ppu.lr = 0x00421b94;
	g_spectator = {};
	spectator_tick(input_manager(), test_time);
}

void spectator_streams()
{
	for (u32 local : {0u, 3u, 4u, umax})
	{
		setup(local);
		// A spectator's history stream is not bounded by the previous fighter's
		// single-peer message watermark. This fails with the old role mapping.
		check(hle_store_input(ppu, input, 1, 1, payload) == 1, "spectator P1 history rejected by fighter watermark");
		check(hle_store_input(ppu, input, 2, 1, payload) == 1, "spectator P2 history rejected");
		check(input_manager() == input && manager() == 0 && remote_player(input) == 0, "spectator classified as fighter");
		for (u32 f = 2; f < 6000; ++f)
		{
			for (u32 player : {1u, 2u})
			{
				const u32 i = player - 1;
				vm::write32(input + 0x60 + i * 4, f);
				vm::write32(payload, f * 4 + player);
				check(hle_input_available(ppu, input, player) == 0, "spectator predicted a missing input");
				check(hle_store_input(ppu, input, player, f, payload) == 1, "spectator stream stopped across ring wrap");
				check(hle_input_available(ppu, input, player) == 1, "confirmed spectator input unavailable");
				check(vm::read32(slot_addr(input, i, f)) == f * 4 + player, "spectator payload corrupted");
				check(hle_store_input(ppu, input, player, f, payload) == 0, "duplicate spectator input rewritten");
			}
		}
		check(g_predicted.empty() && g_remote.empty() && g_mismatch_frame == umax, "spectator modified fighter rollback history");
	}
}

void spectator_missing_inputs()
{
	setup(0);
	ppu.lr = 0x004229a0;
	vm::write32(input + 0x74, 0);
	for (u32 player : {1u, 2u})
	{
		const u32 i = player - 1;
		vm::write32(input + 0x60 + i * 4, 2177);
		vm::write32(input + 0x58 + i * 4, 2177);
		check(hle_input_available(ppu, input, player) == 0, "lead-zero shortcut fabricated spectator input");
		// Stale present bits and predictions from a prior fighter cannot certify
		// a wrapped slot. Late real data must still release the wait.
		vm::write8(flag_addr(input, i, 2177), 1);
		g_predicted[2177] = {};
		check(hle_input_available(ppu, input, player) == 0, "stale prediction accepted by spectator");
		check(hle_store_input(ppu, input, player, 2177, payload) == 1, "late spectator input rejected");
		check(hle_input_available(ppu, input, player) == 1, "late spectator input did not release wait");
	}
	check(hle_store_input(ppu, input, 0, 1, payload) == 0, "invalid player zero accepted");
	check(hle_store_input(ppu, input, 3, 1, payload) == 0, "invalid player three accepted");
}

void fighter_prediction()
{
	for (u32 local : {1u, 2u})
	{
		setup(local);
		const u32 remote = 3 - local, ri = remote - 1;
		check(manager() == input && remote_player(input) == remote, "fighter role changed");
		check(hle_store_input(ppu, input, local, 1, payload) == 0, "received input replaced local fighter");
		check(hle_store_input(ppu, input, remote, 1, payload) == 0, "fighter watermark protection lost");
		g_max_received = 1;
		check(hle_store_input(ppu, input, remote, 1, payload) == 1, "confirmed fighter input rejected");
		vm::write32(input + 0x60 + ri * 4, 2);
		check(hle_input_available(ppu, input, remote) == 1 && g_predicted.contains(2), "fighter prediction disabled");
		vm::write32(input + 0x60 + ri * 4, 3);
		vm::write32(payload, 0x1234);
		g_max_received = 2;
		check(hle_store_input(ppu, input, remote, 2, payload) == 1, "late fighter input rejected");
		check(g_mismatch_frame == 2 && !g_predicted.contains(2), "fighter misprediction did not trigger rollback");
	}
}

void role_rotation()
{
	setup(1);
	update_input_role(input);
	for (u32 local : {0u, 2u, 3u, 1u})
	{
		g_predicted[5] = {};
		g_predicted_at[5] = 99;
		g_remote[5] = {};
		g_remote_at[5] = 99;
		g_local[5] = {};
		g_sim_at[99] = 5;
		g_remote_last = 6;
		g_mismatch_frame = 5;
		g_sync_hold = true;
		g_sync_avg = 4;
		g_fight_start_ns = 100;
		vm::write32(input + 0x14, local);
		update_input_role(input);
		check(g_predicted.empty() && g_predicted_at.empty() && g_remote.empty() && g_remote_at.empty()
			&& g_local.empty() && g_sim_at.empty() && g_remote_last == 0 && g_mismatch_frame == umax,
			"lobby rotation retained previous fighter's inputs");
		check(!g_sync_hold && g_sync_avg == 0 && g_fight_start_ns == 0, "lobby rotation retained fight timing state");
	}
	g_predicted[10] = {};
	update_input_role(input);
	check(g_predicted.contains(10), "unchanged role cleared live predictions");
	update_input_role(0);
	check(g_predicted.empty(), "leaving online play retained predictions");
}

// Characterization tests: preserve the current behavior while recording the
// suspected failure. These do not claim the game's transport delivers this order.
void spectator_reordered_batches()
{
	for (u32 base : {85u, ring - 8, ring + 85})
	{
		setup(4);
		for (u32 i = 0; i < 2; ++i)
		{
			vm::write32(input + 0x60 + i * 4, base);
			vm::write32(input + 0x58 + i * 4, base);
		}
		spectator_tick(input, test_time);
		// Drop the first 17-frame batch; the following batch arrives intact.
		for (u32 f = base + 17; f < base + 34; ++f)
			for (u32 p : {1u, 2u}) check(hle_store_input(ppu, input, p, f, payload) == 1, "later batch not stored");
		check(hle_input_available(ppu, input, 1) == 0, "input hole skipped because high-water mark advanced");
		// A duplicate must not change guest state.
		const auto before_duplicate = vm::memory;
		check(hle_store_input(ppu, input, 1, base + 17, payload) == 0, "duplicate accepted");
		check(vm::memory == before_duplicate, "duplicate changed guest state");
		// Deliver the missing batch late. Its final store clears the ready bit
		// of the first entry of the newer batch (including across ring wrap).
		for (u32 f = base; f < base + 17; ++f)
			for (u32 p : {1u, 2u}) check(hle_store_input(ppu, input, p, f, payload) == 1, "late batch rejected");
		check(hle_input_available(ppu, input, 1) == 1, "late batch did not fill original hole");
		vm::write32(input + 0x60, base + 17);
		check(hle_input_available(ppu, input, 1) == 0, "characterization changed: next-slot clearing no longer reproduced");
		check(vm::read32(input + 0x58) == base + 34, "high-water mark changed on reordered input");
		if (spectator_diagnostics_enabled())
		{
			check(g_spectator.streams[0].backwards > 0 && g_spectator.streams[0].duplicates == 1, "ordering diagnostics missed reordered/duplicate input");
			check(g_spectator.streams[0].cleared_next == 1 && g_spectator.streams[0].last_clear == base + 17
				&& g_spectator.streams[0].cleared_pending == 1 && g_spectator.streams[0].last_pending_clear == base + 17, "diagnostics missed cleared confirmed input");
		}
		// Retransmitting that entry releases the wait; no prediction is used.
		check(hle_store_input(ppu, input, 1, base + 17, payload) == 1, "replacement input rejected");
		check(hle_input_available(ppu, input, 1) == 1, "replacement input did not release wait");
	}
	std::cout << "REPRODUCED: late 17-frame batch clears newer ready flag; high-water mark conceals hole\n";
}

void spectator_trace_lifecycle()
{
	setup(4);
	vm::write32(input + 0x60, 85);
	vm::write32(input + 0x64, 85);
	vm::write32(input + 0x58, 850);
	vm::write32(input + 0x5c, 850);
	spectator_tick(input, test_time);
	const auto before = vm::memory;
	const auto notices = rb_online_log.notices.size();
	spectator_tick(input, test_time + std::chrono::seconds(2));
	check(vm::memory == before, "diagnostic sample modified guest state");
	if (!spectator_diagnostics_enabled())
	{
		check(rb_online_log.notices.size() == notices, "disabled diagnostics logged a sample");
		return;
	}
	check(g_spectator.stalled && rb_online_log.notices.size() > notices, "stalled playback not reported");
	const auto after = rb_online_log.notices.size();
	for (u32 j = 0; j < 1000; ++j) spectator_tick(input, test_time + std::chrono::seconds(2));
	check(rb_online_log.notices.size() == after, "stall logging is not bounded");
	vm::write32(input + 0x60, 86);
	spectator_tick(input, test_time + std::chrono::seconds(3));
	check(!g_spectator.stalled, "resumed progress not recognized");
	g_spectator.requests.sent(850, 17, 0);
	const auto epoch = g_spectator.epoch;
	vm::write32(input + 0x60, 0);
	vm::write32(input + 0x64, 0);
	vm::write32(input + 0x58, 0);
	vm::write32(input + 0x5c, 0);
	spectator_tick(input, test_time + std::chrono::seconds(4));
	check(g_spectator.epoch == epoch + 1 && !g_spectator.requests.calls, "round reset retained previous request accounting");
	vm::write32(input + 0x14, 1);
	spectator_tick(input, test_time + std::chrono::seconds(5));
	check(!g_spectator.mgr, "fighter retained spectator trace");
}

void spectator_transport_wrappers()
{
	setup(4);
	vm::write8(payload + 4, 3);
	vm::write32(payload + 8, 850);
	vm::write8(payload + 0xc, 17);
	const auto memory_before = vm::memory;
	side_heap::calls = 0;
	side_heap::result = 0x123456789abcdef0ull;
	check(hle_spectator_request(ppu, 7, 8, payload) == side_heap::result, "send wrapper truncated return");
	check(side_heap::calls == 1 && side_heap::target == 0x40ef2c
		&& side_heap::arguments == std::vector<u64>({7, 8, payload}), "send wrapper changed original call");
	hle_spectator_request(ppu, 7, 8, payload);
	if (spectator_diagnostics_enabled())
		check(g_spectator.requests.calls == 2 && g_spectator.requests.repeated == 1
			&& g_spectator.requests.first == 850 && g_spectator.requests.count == 17 && g_spectator.requests.tag == 3, "request range/retry not recorded");
	check(vm::memory == memory_before, "send diagnostics changed request");
	vm::write8(payload + 4, 17);
	side_heap::calls = 0;
	check(hle_spectator_receive(ppu, payload) == side_heap::result, "receive wrapper truncated return");
	check(side_heap::calls == 1 && side_heap::target == 0x45e6f8
		&& side_heap::arguments == std::vector<u64>({payload}), "receive wrapper changed original call");
	if (spectator_diagnostics_enabled())
		check(g_spectator.batches.offered == 1 && g_spectator.batches.last == 850 && g_spectator.batch_count == 17, "response range not recorded");
	side_heap::result = 0;
	hle_spectator_receive(ppu, payload);
	check(g_spectator.batches.offered == (spectator_diagnostics_enabled() ? 2u : 0u), "decode return value incorrectly interpreted as receive status");
	if (spectator_diagnostics_enabled())
	{
		check(g_spectator.event_count == 4 && g_spectator.events[0].request
			&& !g_spectator.events[2].request && g_spectator.events[2].count == 17, "transport observation order lost");
		for (u32 i = 0; i < 1000; ++i) g_spectator.event(false, i, 17, 0);
		check(g_spectator.events[(g_spectator.event_count - 1) % 32].first == 999, "bounded transport history lost latest event");
	}
	// A failed or unmapped diagnostic read must still forward the original call.
	side_heap::calls = 0;
	hle_spectator_request(ppu, 7, 8, 0);
	hle_spectator_receive(ppu, 0);
	check(side_heap::calls == 2, "invalid diagnostic address suppressed transport call");
}

int main()
{
	spectator_streams();
	spectator_missing_inputs();
	spectator_reordered_batches();
	spectator_trace_lifecycle();
	spectator_transport_wrappers();
	fighter_prediction();
	role_rotation();
	std::cout << "PASS: spectator streams, missing inputs, ring wrap, fighter prediction, lobby rotation, diagnostics, transport forwarding\n";
}
