#!/usr/bin/env python3
"""Bounded, opt-in Linux RPCS3 audio/rollback capture. Python standard library only."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import selectors
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import zipfile

HEADER = struct.Struct('=II6Q')
NAMES = {1: 'audio', 2: 'marker', 3: 'fight_frame', 4: 'restore_begin',
         5: 'restore_end', 6: 'resim_end', 7: 'sound', 8: 'backend_state', 9: 'resim_begin',
         10: 'mixer_audio', 11: 'mixer_state', 12: 'mixer_decision',
         13: 'rollback_rejected', 14: 'ring_write'}
PCM_STREAMS = {1: 'game-output', 10: 'mixer-input'}
INACTIVE = (1 << 64) - 1
MAX_MEMORY = 64 * 1024 * 1024
MAX_CAPTURES = 8

def now_us():
    return time.monotonic_ns() // 1000

def decode(data):
    if len(data) < HEADER.size:
        return None
    version, kind, stamp, seq, a, b, c, d = HEADER.unpack_from(data)
    if version != 1 or kind not in NAMES:
        return None
    payload = data[HEADER.size:]
    if kind in PCM_STREAMS:
        if not (8000 <= a <= 192000 and 1 <= b <= 8 and c in (2, 4)):
            return None
        if not payload or len(payload) % (b * c) or (d != INACTIVE and d > len(payload)):
            return None
    elif payload:
        return None
    return {'kind': kind, 'time_us': stamp, 'seq': seq, 'a': a, 'b': b, 'c': c, 'd': d, 'pcm': payload}

def wave_header(size, rate, channels, sample_size):
    # PCM signed 16 or IEEE float 32, native little endian on supported x86 Linux.
    align = channels * sample_size
    return b'RIFF' + struct.pack('<I', 36 + size) + b'WAVEfmt ' + struct.pack(
        '<IHHIIHH', 16, 1 if sample_size == 2 else 3, channels, rate,
        rate * align, align, sample_size * 8) + b'data' + struct.pack('<I', size)

def write_bundle(path, records, metadata):
    records = sorted(records, key=lambda r: (r['time_us'], r['seq']))
    groups = []
    for stream, prefix in PCM_STREAMS.items():
        stream_groups = []
        for r in records:
            if r['kind'] != stream:
                continue
            fmt = (r['a'], r['b'], r['c'])
            if not stream_groups or stream_groups[-1][0] != fmt:
                stream_groups.append((fmt, []))
            stream_groups[-1][1].append(r)
        groups.extend((f'{prefix}-{index:02}.wav', fmt, blocks)
                      for index, (fmt, blocks) in enumerate(stream_groups))
    fight = [r for r in records if r['kind'] == 3]
    sequences = {r['seq'] for r in records if r['seq'] >= 0}
    metadata = dict(metadata, summary={
        'audio_shortfall_chunks': sum(r['kind'] == 1 and r['d'] != INACTIVE and r['d'] < len(r['pcm']) for r in records),
        'inactive_or_unavailable_chunks': sum(r['kind'] == 1 and r['d'] == INACTIVE for r in records),
        'max_live_frame_us': max((r['a'] for r in records if r['kind'] == 3), default=0),
        'successful_restores': sum(r['kind'] == 5 and bool(r['c']) for r in records),
        'max_restore_us': max((r['b'] for r in records if r['kind'] == 5), default=None),
        'max_resim_us': max((r['b'] for r in records if r['kind'] == 6 and r['b']), default=None),
        'observed_rollback_counter_increase': sum(max(0, y['b'] - x['b']) for x, y in zip(fight, fight[1:])),
        'mixer_explicit_silence_blocks': sum(r['kind'] == 11 and bool(r['c'] & 1) for r in records),
        'ring_rejected_bytes': sum(max(0, r['a'] - r['b']) for r in records if r['kind'] == 14)},
        schema=2, clock='CLOCK_MONOTONIC microseconds',
                    missing_transport_sequences=(max(sequences) - min(sequences) + 1 - len(sequences)) if sequences else 0,
                    audio_files=len(groups), records=len(records),
                    limitation='Audio taps are cellAudio mixer input to time stretching and Cubeb output before the OS/device; clocks mark production, not speaker presentation. Streams can differ in channel count, duration and latency; do not compare by WAV offset alone. Missing timing events mean unmeasured, not zero rollback cost. Missing chunks are not silently reconstructed. WAV samples are concatenated; events map each chunk to its timestamp and WAV offset.')
    offsets = {}
    temporary = path.with_suffix('.partial')
    with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_STORED) as z:
        for name, fmt, blocks in groups:
            size = sum(len(r['pcm']) for r in blocks)
            offset = 0
            with z.open(name, 'w') as f:
                f.write(wave_header(size, *fmt))
                for r in blocks:
                    f.write(r['pcm'])
                    offsets[id(r)] = {'wav': name, 'sample_frame_offset': offset,
                                      'sample_frames': len(r['pcm']) // (fmt[1] * fmt[2])}
                    offset += len(r['pcm']) // (fmt[1] * fmt[2])
        with z.open('events.jsonl', 'w') as f:
            for r in records:
                item = {k: v for k, v in r.items() if k != 'pcm'}
                item['event'] = NAMES[r['kind']]
                item.update(offsets.get(id(r), {}))
                f.write((json.dumps(item) + '\n').encode())
        z.writestr('capture.json', json.dumps(metadata, indent=2) + '\n')
    temporary.replace(path)

class Collector:
    def __init__(self, output, before=20, after=10):
        self.output = output
        self.before = int(before * 1e6)
        self.after = int(after * 1e6)
        self.ring = collections.deque()
        self.memory = 0
        self.evicted = 0
        self.pending = None
        self.count = 0
        self.auto_count = 0
        self.last_auto = -60_000_000
        self.first_fight = None
        self.first_audio = None
        self.shortages = collections.deque(maxlen=3)
        self.jobs = queue.Queue(maxsize=1)
        self.errors = []
        self.context = {}
        self.worker = threading.Thread(target=self._write, daemon=True)
        self.worker.start()

    def _write(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                path, records, metadata = job
                write_bundle(path, records, metadata)
                print(f'Saved {path}', flush=True)
            except Exception as exc:
                self.errors.append(str(exc))
                print(f'Capture write failed: {exc}', flush=True)
            finally:
                self.jobs.task_done()

    def trigger(self, reason, stamp, automatic=False):
        if self.pending:
            markers = self.pending.setdefault('additional_markers', [])
            if len(markers) < 32:
                markers.append({'reason': reason, 'time_us': stamp})
            return
        if self.count >= MAX_CAPTURES:
            return
        if automatic and (self.auto_count >= 2 or stamp - self.last_auto < 60_000_000):
            return
        if automatic:
            self.auto_count += 1
            self.last_auto = stamp
        self.pending = {'reason': reason, 'marker_us': stamp, 'end_us': stamp + self.after,
                        'start_us': stamp - self.before, 'evictions_at_trigger': self.evicted}
        print(f'Capture requested: {reason}; collecting {self.after / 1e6:g}s after marker', flush=True)

    def add(self, record):
        self.ring.append(record)
        self.memory += len(record['pcm']) + 512
        stamp = record['time_us']
        cutoff = stamp - self.before - self.after - 2_000_000
        while self.ring and (self.ring[0]['time_us'] < cutoff or self.memory > MAX_MEMORY):
            old = self.ring.popleft()
            self.memory -= len(old['pcm']) + 512
            self.evicted += 1
        if record['kind'] == 2:
            self.trigger('manual', stamp)
        elif record['kind'] == 3:
            if self.first_fight is None:
                self.first_fight = stamp
            if stamp - self.first_fight >= 10_000_000 and not getattr(self, 'onset_saved', False):
                self.onset_saved = True
                self.trigger('first_fight_onset', stamp)  # preserves ~10s before fight, first ~20s of fight
            if stamp - self.first_fight >= 90_000_000 and not getattr(self, 'later_saved', False):
                self.later_saved = True
                self.trigger('first_fight_plus_90s', stamp)
            if record['a'] >= 100_000:
                self.trigger('fight_frame_over_100ms', stamp, automatic=True)
        elif record['kind'] == 1:
            if self.first_audio is None:
                self.first_audio = stamp
            if record['d'] != INACTIVE and record['d'] < len(record['pcm']):
                self.shortages.append(stamp)
                if (len(self.shortages) == 3 and stamp - self.shortages[0] < 500_000
                        and stamp - self.first_audio > 5_000_000):
                    self.trigger('three_audio_shortfalls', stamp, automatic=True)

    def tick(self, stamp, final=False):
        if self.pending and (final or stamp >= self.pending['end_us']):
            meta = dict(self.pending, session=self.context, incomplete_post_window=stamp < self.pending['end_us'],
                        ring_evictions=self.evicted,
                        capture_bounds='Up to 20s before and 10s after; time/byte bounds can shorten history.')
            records = [r for r in self.ring if meta['start_us'] <= r['time_us'] <= meta['end_us']]
            meta['history_start_us'] = min((r['time_us'] for r in records), default=None)
            meta['available_pre_seconds'] = max(0, (meta['marker_us'] - meta['history_start_us']) / 1e6) if records else 0
            self.count += 1
            path = self.output / f'capture-{self.count:02}.zip'
            try:
                self.jobs.put_nowait((path, records, meta))
            except queue.Full:
                self.errors.append('Writer busy: capture dropped')
                print('Writer busy: capture dropped (game unaffected)', flush=True)
            self.pending = None

    def close(self):
        self.tick(now_us(), final=True)
        self.jobs.put(None)
        self.worker.join()

def run(args):
    if not args.command:
        raise SystemExit('Supply the normal game launcher after --')
    command = args.command[1:] if args.command[0] == '--' else args.command
    if not command:
        raise SystemExit('Empty launch command')
    if os.sys.platform != 'linux' or os.sys.byteorder != 'little':
        raise SystemExit('Capture currently supports little-endian Linux only')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = Path(args.output).expanduser() / stamp
    output.mkdir(parents=True, mode=0o700)
    temp = tempfile.TemporaryDirectory(prefix='t6-audio-', dir=os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
    endpoint = str(Path(temp.name) / 'capture.sock')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    sock.bind(endpoint)
    os.chmod(endpoint, 0o600)
    sock.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(sock, selectors.EVENT_READ)
    env = dict(os.environ, T6_AUDIO_CAPTURE_SOCKET=endpoint)
    collector = Collector(output)
    binary = Path(env.get('RPCS3_EXE', '/nonexistent'))
    provenance = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None,
                  'started_utc': stamp, 'clock_origin_us': now_us(),
                  'capture_scope': 'RPCS3 cellAudio mixer and Cubeb output, before OS/device'}
    collector.context = provenance
    (output / 'session.json').write_text(json.dumps(provenance, indent=2) + '\n')
    child = None
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    received = 0
    try:
        child = subprocess.Popen(command, env=env)
        print(f'Audio capture armed: {output}\nPress Ctrl+Shift+F8 in the game window to mark a glitch.', flush=True)
        print('Only RPCS3 game audio is captured; no microphone or other applications.', flush=True)
        while not stopped:
            for key, mask in selector.select(timeout=0.1):
                # Bound work per iteration even if an event storm occurs.
                for _ in range(256):
                    try:
                        raw = sock.recv(65536)
                    except BlockingIOError:
                        break
                    record = decode(raw)
                    if record:
                        received += 1
                        collector.add(record)
            collector.tick(now_us())
            if child.poll() is not None:
                break
    finally:
        collector.close()
        selector.close()
        sock.close()
        temp.cleanup()
        (output / 'session.json').write_text(json.dumps(dict(provenance, received_packets=received,
            capture_attempts=collector.count, errors=collector.errors,
            child_exit=child.poll() if child else None,
            note='Collector shutdown does not terminate the emulator.'), indent=2) + '\n')
    return child.returncode if child and child.returncode is not None else 0

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', default='~/.cache/rpcs3/audio-captures')
    p.add_argument('command', nargs=argparse.REMAINDER)
    return run(p.parse_args())

if __name__ == '__main__':
    raise SystemExit(main())
