#!/usr/bin/env python3
"""Synthetic voice restore regression; production helper and snapshot reader.

No game code or data. Does not establish online audio quality or guest-thread
synchronization; the experiment still requires real-match validation.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_decoder_snapshot import function


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='c++')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    state = (root / 'rpcs3/Emu/Rollback/rb_state.cpp').read_text()
    with tempfile.TemporaryDirectory(prefix='voice runtime ') as directory:
        work = Path(directory)
        (work / 'read.inc').write_text(function(state, '\t\tbool read_saved_voice(u32 slot, u32 begin, std::array<u8, voice_runtime::voice_size>& out) const'))
        shutil.copy2(root / 'rpcs3/Emu/Rollback/rb_voice_runtime.h', work)
        shutil.copy2(here / 'voice_runtime_fixture.cpp', work)
        executable = work / 'test'
        subprocess.run([args.cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror',
                        str(work / 'voice_runtime_fixture.cpp'), '-o', str(executable)], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == '__main__':
    main()
