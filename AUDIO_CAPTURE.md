# Investigating Tekken rollback audio

This opt-in Linux capture records RPCS3's Cubeb output and rollback timing on one
monotonic clock. It does not change rollback, audio buffering, or game settings.
Use a single instance on a PC that normally sustains full-speed gameplay.

## Player workflow

Build the instrumented source normally, select **Cubeb** as the audio backend,
then start with:

```sh
./scripts/play_audio_capture.sh boot
```

`RPCS3_EXE` can select another instrumented binary, just as for `play_online.sh`.
Play normally. If something sounds wrong, press **Ctrl+Shift+F8 in the game
window**. Several seconds late is fine. A request message appears; wait at least
10 seconds before closing the emulator. Repeated markers during a capture are
noted in the same capture rather than extending it indefinitely.

Captures are saved under `~/.cache/rpcs3/audio-captures/<session>/`:

- `capture-NN.zip`: game-output WAV files, timestamped events, capture metadata.
- `session.json`: executable hash, capture status and collector errors.

Send the ZIPs and `session.json`. No detailed match chronology is required.
A marker during a clean portion is also useful. The first fight automatically
requests a capture about 10 seconds after its first measured frame, and another
about 90 seconds after that first frame. These cover the initial instability and
provide a later comparison; the later sample is not assumed to be clean.
Repeated audio shortfalls and fight frames over 100 ms can request two further,
rate-limited captures. Startup/inactive output is distinguished from a measured
shortfall. Automatic triggers do not prove that the sound was audibly bad.

Only the emulator's mixed output is recorded: no microphone, Discord, or other
applications. Ordinary in-game voice communication, if mixed by the emulator,
would still be part of game output. The collector does not copy RPCN credentials,
PS3 data, firmware, or the complete emulator log.

## Bounds and interpretation

History is limited by time and a 64 MiB accounting budget. A normal marker keeps
up to 20 seconds before and 10 after. High channel counts, unusually frequent
events, startup, or shutdown may shorten that window; metadata records its bounds.
One disk writer and one queued bundle limit memory amplification. At most eight
captures are attempted per launch; no old sessions are silently deleted. ZIPs
are stored without compression to avoid CPU-heavy encoding during gameplay.

The emulator uses nonblocking local datagrams. A slow/dead collector cannot
block the audio callback. Packet sequence gaps are reported within each saved
window. Missing recording packets must not be mistaken for game audio underruns.
Capture timestamps are callback-side times, not speaker presentation times.
WAVs concatenate recorded chunks; `events.jsonl` maps every chunk to its clock
and WAV sample offset. Format changes create separate WAV files. Silent or
repeated samples inserted by Cubeb on shortfall are included in the recording.

This is **before** PipeWire/PulseAudio/ALSA and the physical device. A clean
recording does not rule out a problem later in the host audio path. The first
implementation supports Linux and Cubeb; other backends do not provide PCM or
shortfall data. These limitations are not evidence that a native recompilation
port would fix the symptom.

## Event schema (version 1)

All events include `time_us`, process-local `seq`, and four integer fields
`a`, `b`, `c`, `d`. Time uses Linux CLOCK_MONOTONIC microseconds in both producer
and collector; no wall-clock synchronization is needed.

| Event | Fields |
|---|---|
| audio | a=sample rate, b=channels, c=bytes/sample, d=bytes supplied; UINT64_MAX means inactive/reset/callback unavailable |
| marker | Manual keypress |
| fight_frame | a=live boundary interval in microseconds, b=rollback count, c=re-simulated frame count |
| restore_begin | a=snapshot game frame |
| restore_end | a=snapshot frame, b=duration including draw wait, c=success |
| resim_begin | a=current frame, b=target frame, c=depth |
| resim_end | a=ending frame, b=elapsed microseconds (0 when untracked) |
| sound | a=simulation frame, b=bank, c=cue, d=0 live request/10 re-simulation request/1 reused/2 suppressed/3 success/4 failed |
| sound (stop) | a=0, b=voice address, c=0, d=5 stop request |
| backend_state | a=Cubeb state enum |

Sound and resimulation events cover the instrumented online path, not every
possible decoder operation. The WAV is required to assess audible corruption;
these counters alone are not an automatic sound-quality detector.

Validation:

```sh
python3 tests/scripts/test_audio_capture.py
```

Linux tests compile and exercise the real nonblocking C++ transport and the
actual Cubeb callback extracted from the source. They deliberately empty its
producer buffer and verify shortfall bytes, repeated output samples, inactive
output, and a disconnected receiver. Collector tests
check automatic starvation detection, pre/post windows, memory bounds, format
and timestamp mapping, and transport loss reporting. Live callback/shortcut
smoke tests are recorded separately; an actual online glitch still needs capture.
