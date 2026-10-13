# Investigating Tekken rollback audio

This opt-in Linux capture records RPCS3's game mixer, Cubeb output and rollback
timing on one monotonic clock. It does not change rollback, audio buffering, or game settings.
Use a single instance on a PC that normally sustains full-speed gameplay.

## Player workflow

Build the current instrumented source and use its matching collector script,
select **Cubeb** as the audio backend, then start with:

```sh
./scripts/play_audio_capture.sh boot
```

`RPCS3_EXE` can select another instrumented binary, just as for `play_online.sh`.
Play normally. If something sounds wrong, press **Ctrl+Shift+F8 in the game
window**. Several seconds late is fine. A request message appears; wait at least
10 seconds before closing the emulator. Repeated markers during a capture are
noted in the same capture rather than extending it indefinitely.

Captures are saved under `~/.cache/rpcs3/audio-captures/<session>/`:

- `capture-NN.zip`: `game-output-*.wav` (Cubeb) and `mixer-input-*.wav`
  (cellAudio's mix before time stretching and final output conversion),
  timestamped events and capture metadata.
- `session.json`: executable hash, capture status and collector errors.

Send the ZIPs and `session.json`. No detailed match chronology is required.
A marker during a clean portion is also useful. The first fight automatically
requests captures on the first measured fight frames at least 10 and 90 seconds
after its first measured frame. Menus and gaps between fights can delay these. These cover the initial instability and
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
Capture timestamps mark audio production/callbacks, not speaker presentation.
Both streams use the same clock, but buffering and time stretching introduce
latency and can change their lengths; channel counts can also differ. Compare
matching sound content and event timestamps, not identical WAV offsets.
The mixer recording includes explicitly enqueued silence. Mixer-state events
flag that silence and record buffer occupancy and stretching ratio. Mixer
period decisions record untouched-port skips/partial mixing; ring-write events
report rejected audio bytes. Retry loops are not individually logged.

WAVs concatenate recorded chunks; `events.jsonl` maps every chunk to its clock
and WAV sample offset. Format changes create separate WAV files. Silent or
repeated samples inserted by Cubeb on shortfall are included in the recording.

This is **before** PipeWire/PulseAudio/ALSA and the physical device. A clean
recording does not rule out a problem later in the host audio path. The first
implementation supports Linux with Cubeb for the final output tap. Other
backends may provide the cellAudio mixer tap, but lack captured final PCM and
callback shortfall data. These limitations are not evidence that a native recompilation
port would fix the symptom.

## Event schema (capture metadata version 2, wire version 1)

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
| mixer_audio | Same PCM fields as audio; before stretching/final conversion |
| mixer_state | a=queued sample frames (UINT64_MAX without buffering), b=tempo ratio × 1,000,000, c=flags, d=block sample frames |
| mixer_decision | a=reason, b=active ports, c=untouched ports, d=emulated microseconds since last period |
| rollback_rejected | a=requested/selected frame, b=current frame, c=1 no slot / 2 depth or tag limit / 3 not a past frame, d=1 |
| ring_write | a=requested bytes, b=accepted bytes, c=bytes per output sample frame, d=ring bytes occupied after write |
| resim_end | a=ending frame, b=elapsed microseconds (0 when untracked) |
| sound | a=simulation frame, b=bank, c=cue, d=0 live request/10 re-simulation request/1 reused/2 suppressed/3 success/4 failed |
| sound (stop) | a=0, b=voice address, c=0, d=5 stop request |
| backend_state | a=Cubeb state enum |

Mixer flags: 1=explicit silence, 2=forced enqueue, 4=buffering enabled,
8=time stretching enabled. Mixer decision reasons: 1=no active ports (silence),
2=all ports untouched after timeout (skip), 3=partial timeout (mix available ports),
4=untouched fast path (silence). Silence flags describe the enqueue decision;
a mixed block can itself contain silence without that flag.

Restore/resimulation events use d=1 for the active snapshot-ring path and d=0
for the original direct net-load path. Ring restore timing includes preservation
callbacks and draw waits. Ring resim timing includes restoration through return
to the live frame; it is not just time executing resimulated guest instructions.
A begin without its end can reflect capture boundaries, packet loss, or an
unfinished operation; do not invent a duration. Summary duration fields are
`null` when unmeasured. The earlier capture implementation missed ring-path
restore/resim events despite increasing rollback counters; its zero duration
summaries must not be interpreted as no rollback cost.

Both online rollback paths and scheduled ring rollbacks are instrumented.
Sound events still do not cover every decoder operation. The WAV is required
to assess audible corruption; counters alone are not a sound-quality detector.

Validation:

```sh
python3 tests/scripts/test_audio_capture.py
```

Linux tests compile and exercise the real nonblocking C++ transport and the
actual Cubeb callback and mixer enqueue function extracted from the source.
They deliberately empty the callback producer and verify shortfall bytes,
repeated output samples, inactive
output, pre-stretch PCM, explicit silence, inactive/forced enqueue, and a
disconnected receiver. Collector tests check automatic starvation detection, pre/post windows, memory bounds, format
and timestamp mapping, separate interleaved PCM streams, unknown timing, and
transport loss reporting. Live callback/shortcut smoke tests are recorded separately; an actual online glitch still needs capture.
