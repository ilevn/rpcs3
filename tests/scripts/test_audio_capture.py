#!/usr/bin/env python3
"""Collector bounds, starvation detection, real WAV bytes, and Linux sender ABI."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('capture', ROOT / 'scripts/audio_capture.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

def event(kind, stamp, seq=0, a=0, b=0, d=0, pcm=b'', sample_size=2):
    return {'kind': kind, 'time_us': stamp, 'seq': seq, 'a': a, 'b': b,
            'c': sample_size, 'd': d, 'pcm': pcm}

class CaptureTests(unittest.TestCase):
    def test_voice_experiment_events(self):
        rows = [c.decode(c.HEADER.pack(1, 15, 100, 0, 0x36000000, 192, 190, 1)),
                c.decode(c.HEADER.pack(1, 16, 101, 1, 20, 12, 10, 12))]
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'capture.zip'
            c.write_bundle(path, rows, {})
            with zipfile.ZipFile(path) as z:
                events = [json.loads(row) for row in z.read('events.jsonl').splitlines()]
                self.assertEqual([row['event'] for row in events], ['voice_layout', 'voice_restore'])
                summary = json.loads(z.read('capture.json'))['summary']
                self.assertEqual(summary['voice_restore_events'], 1)
                self.assertEqual(summary['voice_runtime_differences'], 10)
                self.assertEqual(summary['voice_runtime_protections'], 12)

    def test_decode_rejects_bad_audio(self):
        self.assertIsNone(c.decode(b'bad'))
        self.assertIsNone(c.decode(c.HEADER.pack(1, 1, 0, 0, 48000, 0, 2, 0) + b'xx'))
        self.assertIsNone(c.decode(c.HEADER.pack(1, 1, 0, 0, 48000, 2, 2, 99) + b'xxxx'))

    def test_wav_offsets_and_loss(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'capture.zip'
            rows = [event(1, 100, 3, 48000, 2, 4, b'\x01\x02\x03\x04'),
                    event(2, 105, 4), event(1, 110, 6, 48000, 2, 0, b'\0'*4)]
            c.write_bundle(p, rows, {'marker_us': 105})
            with zipfile.ZipFile(p) as z:
                wav = z.read('game-output-00.wav')
                self.assertEqual(wav[:4], b'RIFF')
                self.assertEqual(struct.unpack_from('<I', wav, 40)[0], 8)
                self.assertEqual(wav[44:], b'\x01\x02\x03\x04'+b'\0'*4)
                meta = json.loads(z.read('capture.json'))
                self.assertEqual(meta['missing_transport_sequences'], 1)
                events = [json.loads(l) for l in z.read('events.jsonl').splitlines()]
                self.assertEqual(events[2]['sample_frame_offset'], 1)

    def test_interleaved_streams_formats_and_missing_timing(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'capture.zip'
            rows = [event(1, 100, 0, 48000, 2, 4, b'abcd'),
                    event(10, 101, 1, 48000, 2, 8, b'12345678', sample_size=4),
                    event(1, 102, 2, 48000, 2, 4, b'efgh'),
                    event(10, 103, 3, 48000, 2, 8, b'ABCDEFGH', sample_size=4),
                    event(10, 104, 4, 48000, 1, 4, b'ijkl', sample_size=4)]
            # Both stream kinds must validate payloads in the wire decoder.
            for r in rows:
                packet = c.HEADER.pack(1, r['kind'], r['time_us'], r['seq'], r['a'], r['b'], r['c'], r['d']) + r['pcm']
                self.assertEqual(c.decode(packet), r)
            self.assertIsNone(c.decode(c.HEADER.pack(1, 10, 0, 0, 48000, 2, 4, 8) + b'x'))
            c.write_bundle(p, rows, {})
            with zipfile.ZipFile(p) as z:
                self.assertEqual(z.read('game-output-00.wav')[44:], b'abcdefgh')
                self.assertEqual(z.read('mixer-input-00.wav')[44:], b'12345678ABCDEFGH')
                self.assertEqual(z.read('mixer-input-01.wav')[44:], b'ijkl')
                records = [json.loads(l) for l in z.read('events.jsonl').splitlines()]
                self.assertEqual([r['sample_frame_offset'] for r in records], [0, 0, 1, 1, 0])
                meta = json.loads(z.read('capture.json'))
                self.assertEqual(meta['audio_files'], 3)
                self.assertIsNone(meta['summary']['max_restore_us'])
                self.assertIsNone(meta['summary']['max_resim_us'])

    @unittest.skipUnless(os.sys.platform == 'linux', 'Linux actual-mixer capture test')
    def test_actual_mixer_before_stretch_and_silence(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            source = (ROOT/'rpcs3/Emu/Cell/Modules/cellAudio.cpp').read_text()
            body = source[source.index('void audio_ringbuffer::enqueue('):source.index('void audio_ringbuffer::enqueue_silence(')]
            fixture = Path(__file__).with_name('audio_capture_mixer_fixture.cpp').read_text()
            (t/'mixer.cpp').write_text(fixture.replace('// ENQUEUE_INSERT', body))
            subprocess.run(['c++', '-std=c++20', '-I', str(ROOT/'rpcs3'), str(t/'mixer.cpp'), '-o', str(t/'mixer')], check=True)
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.bind(str(t/'socket')); sock.settimeout(2)
                subprocess.run([str(t/'mixer')], env=dict(os.environ, T6_AUDIO_CAPTURE_SOCKET=str(t/'socket')), check=True, timeout=3)
                rows = [c.decode(sock.recv(65536)) for _ in range(6)]
            self.assertEqual([r['kind'] for r in rows], [11, 10, 11, 10, 11, 10])
            self.assertEqual(rows[1]['pcm'], struct.pack('=512f', *([.25]*512)))
            self.assertEqual(rows[3]['pcm'], bytes(2048))
            self.assertEqual(rows[0]['a'], 960)
            self.assertEqual(rows[2]['b'], 750000)
            self.assertEqual(rows[2]['c'], 1 | 4 | 8)
            self.assertEqual(rows[4]['a'], c.INACTIVE)
            self.assertEqual(rows[4]['c'], 1 | 2 | 8)

    def test_pre_post_window_and_inactive_not_underrun(self):
        with tempfile.TemporaryDirectory() as t:
            obj = c.Collector(Path(t), before=.02, after=.01)
            for i in range(10):
                obj.add(event(1, 6_000_000+i*1000, i, 48000, 2, c.INACTIVE, b'\0'*4))
            self.assertIsNone(obj.pending)
            obj.add(event(2, 6_010_000, 10))
            obj.add(event(1, 6_025_000, 11, 48000, 2, 4, b'\0'*4))
            obj.tick(6_021_000)
            obj.close()
            with zipfile.ZipFile(Path(t)/'capture-01.zip') as z:
                rows = [json.loads(l) for l in z.read('events.jsonl').splitlines()]
                self.assertTrue(all(5_990_000 <= r['time_us'] <= 6_020_000 for r in rows))

    def test_starvation_and_memory_bound(self):
        with tempfile.TemporaryDirectory() as t:
            obj = c.Collector(Path(t))
            obj.add(event(1, 0, 0, 48000, 2, 4, b'\0'*4))
            for i in range(3):
                obj.add(event(1, 6_000_000+i*10000, i+1, 48000, 2, 0, b'\0'*4))
            self.assertEqual(obj.pending['reason'], 'three_audio_shortfalls')
            previous = c.MAX_MEMORY
            try:
                c.MAX_MEMORY = 2048
                for i in range(100): obj.add(event(7, 6_050_000, i+4))
                self.assertLessEqual(obj.memory, 2048)
            finally:
                c.MAX_MEMORY = previous
                obj.close()

    def test_first_fight_and_later_capture(self):
        with tempfile.TemporaryDirectory() as t:
            obj = c.Collector(Path(t))
            obj.add(event(3, 1_000_000, 0, 16000))
            obj.add(event(3, 11_000_000, 1, 16000))
            self.assertEqual(obj.pending['reason'], 'first_fight_onset')
            obj.tick(21_000_000)
            obj.jobs.join()
            obj.add(event(3, 91_000_000, 2, 16000))
            self.assertEqual(obj.pending['reason'], 'first_fight_plus_90s')
            obj.close()

    @unittest.skipUnless(os.sys.platform == 'linux', 'Linux actual-callback capture test')
    def test_actual_cubeb_callback_starvation(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            source = (ROOT/'rpcs3/Emu/Audio/Cubeb/CubebBackend.cpp').read_text()
            callback = source[source.index('long CubebBackend::data_cb('):source.index('void CubebBackend::state_cb(')]
            fixture = Path(__file__).with_name('audio_capture_callback_fixture.cpp').read_text()
            (t/'callback.cpp').write_text(fixture.replace('// CALLBACK_INSERT', callback))
            subprocess.run(['c++', '-std=c++20', '-pthread', '-I', str(ROOT/'rpcs3'), str(t/'callback.cpp'), '-o', str(t/'callback')], check=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(str(t/'socket')); sock.settimeout(2)
            subprocess.run([str(t/'callback')], env=dict(os.environ, T6_AUDIO_CAPTURE_SOCKET=str(t/'socket')), check=True, timeout=3)
            records = [c.decode(sock.recv(65536)) for _ in range(3)]
            sock.close()
            self.assertEqual([r['d'] for r in records], [16, 0, c.INACTIVE])
            self.assertEqual(records[1]['pcm'], b'\x12'*16)
            self.assertEqual(records[2]['pcm'], b'\0'*16)

    @unittest.skipUnless(os.sys.platform == 'linux', 'Linux sender uses AF_UNIX')
    def test_cpp_sender_starved_audio_and_disconnected_nonblocking(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            code = t/'sender.cpp'
            code.write_text('''#include "Emu/Rollback/rb_audio_capture.h"
int main() {
  short samples[4]{1,2,3,4};
  rb::audio_capture::audio(samples, sizeof(samples), 48000, 2, 2, 0);
  rb::audio_capture::send_event(rb::audio_capture::marker);
}
''')
            subprocess.run(['c++', '-std=c++20', '-I', str(ROOT/'rpcs3'), str(code), '-o', str(t/'sender')], check=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(str(t/'socket'));sock.settimeout(2)
            env = dict(os.environ, T6_AUDIO_CAPTURE_SOCKET=str(t/'socket'))
            subprocess.run([str(t/'sender')], env=env, check=True, timeout=2)
            first = c.decode(sock.recv(65536));second = c.decode(sock.recv(65536))
            self.assertEqual(first['d'], 0)
            self.assertEqual(first['pcm'], struct.pack('=4h',1,2,3,4))
            self.assertEqual(second['kind'], 2)
            self.assertLess(abs(c.now_us()-first['time_us']), 2_000_000)
            sock.close()
            subprocess.run([str(t/'sender')], env=env, check=True, timeout=2)

if __name__ == '__main__':
    unittest.main()
