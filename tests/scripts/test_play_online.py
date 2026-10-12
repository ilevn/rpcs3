#!/usr/bin/env python3
"""Test launcher without RPCS3, firmware, game data, or a graphical session.

Optional: --reference-bat /path/to/original/play_online.bat verifies the frozen
profile fixture against the original Windows distribution as well.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/play_online.sh'
PROFILE = ROOT / 'scripts/config_BLUS30359.yml'
EXPECTED = json.loads((Path(__file__).parent / 'online_profile.json').read_text())
REFERENCE_BAT = None


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rollback test ')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.exe = self.directory / 'binary space' / 'rpcs3'
        self.exe.parent.mkdir()
        self.exe.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CAPTURE_PATH'], 'w') as stream:
    json.dump({'env': dict(os.environ), 'args': sys.argv[1:], 'cwd': os.getcwd()}, stream)
''')
        self.exe.chmod(0o755)
        self.capture = self.directory / 'capture.json'
        self.portable = self.exe.parent / 'portable'
        self.config = self.portable / 'custom_configs/config_BLUS30359.yml'
        self.env = dict(os.environ, RPCS3_EXE=str(self.exe), CAPTURE_PATH=str(self.capture),
                        HOME=str(self.directory / 'home'), XDG_CACHE_HOME=str(self.directory / 'cache'))
        self.env.pop('XDG_CONFIG_HOME', None)

    def launch(self, *args, ok=True):
        result = subprocess.run(['bash', str(SCRIPT), *args], env=self.env,
                                text=True, capture_output=True, timeout=10)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(self.capture.read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.capture.exists())
        return result

    def check_profile(self, data, delay='auto', fast='2'):
        fixed = dict(EXPECTED, RB_ONLINE_LEAD=delay, RB_DRAW_IDLE_RSX=fast)
        actual = {k: v for k, v in data['env'].items() if k.startswith('RB_')}
        log = Path(actual.pop('RB_ONLINE_HASH_OUT'))
        self.assertEqual(actual, fixed)
        self.assertEqual(log.parent, (self.portable / 'rollback_log').resolve())
        self.assertTrue(log.is_file())
        self.assertEqual(self.config.read_bytes(), PROFILE.read_bytes())
        self.assertEqual(data['cwd'], str(self.portable.resolve()))

    def test_default_and_inherited_flags(self):
        self.env.update(RB_NATIVE='/tmp/native.dll', RB_SOUND_SEPARATE='1',
                        RB_DEFER_HANDOFF='1', RB_UNEXPECTED_DEBUG='1', RB_FIXED_TIME='0')
        data = self.launch()
        self.check_profile(data)
        self.assertEqual(data['args'], [])

    def test_numeric_boot_fast(self):
        data = self.launch('2', 'boot', 'fast')
        self.check_profile(data, '2', '1')
        self.assertEqual(data['args'], ['%RPCS3_GAMEID%:BLUS30359'])

    def test_fast_without_boot_and_zero_delay(self):
        data = self.launch('0', 'fast')
        self.check_profile(data, '0', '1')
        self.assertEqual(data['args'], [])

    def test_implicit_auto_and_option_order(self):
        data = self.launch('fast', 'boot')
        self.check_profile(data, 'auto', '1')
        self.assertEqual(data['args'], ['%RPCS3_GAMEID%:BLUS30359'])

    def test_bad_arguments(self):
        for args in [('-1',), ('nonsense',), ('2147483648',), ('99999999999',),
                     ('auto', 'boot', 'boot'), ('auto', 'fast', 'fast'), ('2', 'unknown')]:
            with self.subTest(args=args):
                self.launch(*args, ok=False)
                self.assertFalse(self.portable.exists())

    def test_config_mismatch_is_preserved(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('user data\n')
        result = self.launch(ok=False)
        self.assertIn('Game profile differs', result.stderr)
        self.assertEqual(self.config.read_text(), 'user data\n')

    def test_missing_binary(self):
        self.exe.unlink()
        self.assertIn('RPCS3 executable not found', self.launch(ok=False).stderr)

    def test_real_binary_path_and_previous_log(self):
        alias = self.directory / 'rpcs3 symlink'
        alias.symlink_to(self.exe)
        self.env['RPCS3_EXE'] = str(alias)
        old = Path(self.env['XDG_CACHE_HOME']) / 'rpcs3/RPCS3.log'
        old.parent.mkdir(parents=True)
        old.write_text('previous emulator log\n')
        data = self.launch()
        self.check_profile(data)
        previous = list(old.parent.glob('RPCS3_prev_*.log'))
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0].read_bytes(), old.read_bytes())
        first_log = data['env']['RB_ONLINE_HASH_OUT']
        data = self.launch()
        self.check_profile(data)
        self.assertNotEqual(data['env']['RB_ONLINE_HASH_OUT'], first_log)

    def test_log_location_fallbacks(self):
        self.env.pop('XDG_CACHE_HOME')
        for base in ['config', 'home']:
            if base == 'config':
                self.env['XDG_CONFIG_HOME'] = str(self.directory / 'config')
                log_dir = self.directory / 'config/rpcs3'
            else:
                self.env.pop('XDG_CONFIG_HOME')
                log_dir = Path(self.env['HOME']) / '.cache/rpcs3'
            log_dir.mkdir(parents=True)
            (log_dir / 'RPCS3.log').write_text(base)
            self.launch()
            copies = list(log_dir.glob('RPCS3_prev_*.log'))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_text(), base)

    def test_original_windows_profile(self):
        if not REFERENCE_BAT:
            self.skipTest('optional original Windows profile comparison')
        found = {}
        for line in Path(REFERENCE_BAT).read_text().splitlines():
            match = re.fullmatch(r'set (RB_\w+)=(.*)', line)
            if match and match[1] != 'RB_ONLINE_LEAD':
                found[match[1]] = match[2]
        self.assertEqual(found, EXPECTED)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference-bat')
    args, rest = parser.parse_known_args()
    REFERENCE_BAT = args.reference_bat
    unittest.main(argv=[__file__, *rest])
