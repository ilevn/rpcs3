#pragma once

// Opt-in Linux diagnostic transport. No allocation, file I/O, or blocking sends
// on the audio callback. The separate collector owns bounded history/storage.
#include <cstdint>
#ifdef __linux__
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#endif

namespace rb::audio_capture
{
enum kind : std::uint32_t
{
	pcm = 1, marker, frame, restore_begin, restore_end, resim_end, sound,
	backend_state, resim_begin
};

#ifdef __linux__
struct transport
{
	int fd = -1;
	sockaddr_un address{};
	std::atomic<std::uint64_t> sequence{0};
	transport()
	{
		const char* path = std::getenv("T6_AUDIO_CAPTURE_SOCKET");
		if (!path || !*path || std::strlen(path) >= sizeof(address.sun_path)) return;
		address.sun_family = AF_UNIX;
		std::strcpy(address.sun_path, path);
		fd = ::socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
	}
};
inline transport& channel() { static transport value; return value; }
inline bool enabled() { return channel().fd >= 0; }
inline std::uint64_t now_us()
{
	timespec t{};
	clock_gettime(CLOCK_MONOTONIC, &t);
	return std::uint64_t(t.tv_sec) * 1000000 + t.tv_nsec / 1000;
}
inline bool send_event(kind type, std::uint64_t a = 0, std::uint64_t b = 0,
	std::uint64_t c = 0, std::uint64_t d = 0, const void* data = nullptr, std::uint32_t size = 0)
{
	auto& socket = channel();
	if (socket.fd < 0) return false;
	struct packet
	{
		std::uint32_t version, type;
		std::uint64_t timestamp, sequence, a, b, c, d;
	} header{1, type, now_us(), socket.sequence.fetch_add(1, std::memory_order_relaxed), a, b, c, d};
	static_assert(sizeof(packet) == 56);
	iovec parts[2]{{&header, sizeof(header)}, {const_cast<void*>(data), size}};
	msghdr message{};
	message.msg_name = &socket.address;
	message.msg_namelen = sizeof(socket.address);
	message.msg_iov = parts;
	message.msg_iovlen = size ? 2 : 1;
	return sendmsg(socket.fd, &message, MSG_DONTWAIT | MSG_NOSIGNAL) == static_cast<ssize_t>(sizeof(header) + size);
}
inline void audio(const void* data, std::uint32_t bytes, std::uint32_t rate,
	std::uint32_t channels, std::uint32_t sample_size, std::uint64_t written)
{
	if (!enabled() || !channels || !sample_size) return;
	const std::uint32_t stride = channels * sample_size;
	const std::uint32_t limit = 60000 / stride * stride;
	if (!limit) return;
	for (std::uint32_t offset = 0; offset < bytes;)
	{
		const std::uint32_t count = bytes - offset < limit ? bytes - offset : limit;
		const auto available = written == UINT64_MAX ? written :
			written <= offset ? 0 : written - offset < count ? written - offset : count;
		send_event(pcm, rate, channels, sample_size, available, static_cast<const char*>(data) + offset, count);
		offset += count;
	}
}
#else
inline bool enabled() { return false; }
inline std::uint64_t now_us() { return 0; }
inline bool send_event(kind, std::uint64_t = 0, std::uint64_t = 0, std::uint64_t = 0, std::uint64_t = 0) { return false; }
inline void audio(const void*, std::uint32_t, std::uint32_t, std::uint32_t, std::uint32_t, std::uint64_t) {}
#endif
}
