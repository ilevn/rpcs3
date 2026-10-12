#!/usr/bin/env python3
"""Exercise the actual Linux relaunch function without building or launching RPCS3.

Usage: python3 tests/scripts/test_relaunch.py [--cxx clang++]
Requires Linux and a C++20 compiler with a linker supporting --wrap (GNU ld/lld).

The function is extracted from rb_input.cpp into a temporary translation unit;
relaunch_fixture.cpp supplies minimal logging/filesystem stubs and injects errors
through linker wrappers. Successful launches execute the fixture itself, checking
exact argv and environment inheritance. The executable lives in a path containing
spaces and exceeding 256 bytes to exercise readlink buffer growth.

Scope: process spawning, error handling, and requests to preserve the old log.
This does not test real RPCS3 log contents, Qt startup, Emulator::BootGame/Restart,
firmware, or game execution. All compiled artifacts are temporary.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++", help="C++ compiler executable (default: c++)")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("run this regression test on Linux (for example, the test VM)")

    tests_dir = Path(__file__).resolve().parent
    root = tests_dir.parents[1]
    source = (root / "rpcs3/Emu/Rollback/rb_input.cpp").read_text()
    signature = "\tbool relaunch_for_boot(const std::string& path)\n"
    if source.count(signature) != 1:
        parser.error("cannot uniquely locate relaunch_for_boot; update the extraction markers")
    start = source.index(signature)
    try:
        end = source.index("\n\tvoid install_static_hooks(", start)
    except ValueError:
        parser.error("cannot locate the end of relaunch_for_boot; update the extraction markers")

    with tempfile.TemporaryDirectory(prefix="rpcs3 relaunch test ") as temporary:
        work = Path(temporary)
        (work / "relaunch_under_test.inc").write_text(source[start:end])
        shutil.copy2(tests_dir / "relaunch_fixture.cpp", work / "fixture.cpp")
        executable = work / ("a" * 200) / ("b" * 100) / "relaunch fixture"
        executable.parent.mkdir(parents=True)
        subprocess.run(
            [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
             str(work / "fixture.cpp"), "-Wl,--wrap=posix_spawn",
             "-Wl,--wrap=readlink", "-o", str(executable)],
            check=True, timeout=60,
        )
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == "__main__":
    main()
