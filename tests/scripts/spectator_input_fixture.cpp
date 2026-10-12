#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
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
	bool check_addr(u32 a, int) { return a >= 0x10000 && a < memory.size() - 4; }
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
	template <typename... T> void notice(const char*, T...) {}
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
// Payload prediction is outside this test: repeat the last confirmed entry.
entry_t predict_entry(u32 mgr, u32 i, u32 sim) { return read_entry(slot_addr(mgr, i, sim - 1)); }
#include "hle_input_available.inc"
#include "hle_store_input.inc"

constexpr u32 input = 0x10000, payload = 0x90000;
ppu_thread ppu;

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
}

void spectator_streams()
{
	for (u32 local : {0u, 3u, umax})
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

int main()
{
	spectator_streams();
	spectator_missing_inputs();
	fighter_prediction();
	role_rotation();
	std::cout << "PASS: spectator streams, missing inputs, ring wrap, fighter prediction, lobby rotation\n";
}
