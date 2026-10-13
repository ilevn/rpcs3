#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <span>

namespace rb::voice_runtime
{
// BLUS30359 v1.03 bnusCore voices. Keep this experiment separate from the
// older KEEP_RUNTIME/KEEP_PARAMS callbacks, which copy live bytes back later.
inline constexpr std::uint32_t voice_size = 0x2f0;
inline constexpr std::uint32_t runtime_size = 0x150;

inline bool unchanged_active_voice(const std::uint8_t* live, const std::uint8_t* saved)
{
	// Allocation byte and big-endian valid word must both be nonzero. Require
	// EVERY non-runtime byte to match, including generation, request, parameters,
	// decoder pointers and the side-buffer pointer. Never combine new controls
	// with old playback state merely because a voice index was reused.
	return live[0x1a0] && (live[0x1ac] || live[0x1ad] || live[0x1ae] || live[0x1af]) &&
		std::memcmp(live + runtime_size, saved + runtime_size, voice_size - runtime_size) == 0;
}

// Emit the parts of an existing restore piece that may still be written.
// Offsets refer to that piece, so exclusions and cross-page source offsets
// remain intact. No live memory is copied out and written back after restore.
template <typename Emit>
void restore_spans(std::uint32_t begin, std::uint32_t size, std::uint32_t core,
	std::span<const std::uint8_t> keep, Emit emit)
{
	if (!size) return;
	const std::uint64_t end = std::uint64_t{begin} + size;
	const std::uint64_t core_end = std::uint64_t{core} + keep.size() * voice_size;
	if (keep.empty() || end <= core || begin >= core_end)
	{
		emit(0, size);
		return;
	}

	std::uint64_t cursor = begin;
	const auto first = begin < core ? 0 : (begin - core) / voice_size;
	for (std::size_t i = first; i < keep.size(); ++i)
	{
		const std::uint64_t lo = std::uint64_t{core} + i * voice_size;
		if (lo >= end) break;
		if (!keep[i]) continue;
		const auto hi = std::min(end, lo + runtime_size);
		if (hi <= cursor) continue;
		if (lo > cursor) emit(static_cast<std::uint32_t>(cursor - begin), static_cast<std::uint32_t>(lo - cursor));
		cursor = hi;
	}
	if (cursor < end) emit(static_cast<std::uint32_t>(cursor - begin), static_cast<std::uint32_t>(end - cursor));
}
}
