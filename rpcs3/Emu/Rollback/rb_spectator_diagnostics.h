#pragma once

#include <cstdint>

namespace rb::online::spectator_diagnostics
{
// Host-only accounting: never used to decide whether an input is accepted.
// Ranges describe calls to the input store, not network packet boundaries.
struct stream
{
	uint64_t offered = 0, accepted = 0, duplicates = 0, rejected = 0;
	uint64_t backwards = 0, gaps = 0, cleared_next = 0, cleared_pending = 0;
	uint32_t first = 0, last = 0, low = UINT32_MAX, high = 0, caller = 0;
	uint32_t last_clear = 0, clear_caller = 0, last_pending_clear = 0;

	void offer(uint32_t frame, uint32_t lr, bool present, bool stored, bool next_present, bool next_pending = false)
	{
		if (!offered) first = frame;
		else if (frame < last) ++backwards;
		else if (uint64_t(frame) > uint64_t(last) + 1) ++gaps;
		++offered;
		last = frame;
		caller = lr;
		if (frame < low) low = frame;
		if (frame > high) high = frame;
		if (stored) ++accepted;
		else if (present) ++duplicates;
		else ++rejected;
		if (stored && next_present)
		{
			++cleared_next;
			last_clear = frame + 1;
			clear_caller = lr;
			if (next_pending)
			{
				++cleared_pending;
				last_pending_clear = frame + 1;
			}
		}
	}
};

struct requests
{
	uint64_t calls = 0, repeated = 0;
	uint32_t first = 0, count = 0, tag = 0;

	void sent(uint32_t start, uint32_t size, uint32_t epoch)
	{
		if (calls && first == start && count == size && tag == epoch) ++repeated;
		++calls;
		first = start;
		count = size;
		tag = epoch;
	}
};
}
