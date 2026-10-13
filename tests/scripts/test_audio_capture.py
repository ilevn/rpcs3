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
