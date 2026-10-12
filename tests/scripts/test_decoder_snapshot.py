#!/usr/bin/env python3
"""Test decoder-server snapshot protection using production C++ source.

Run with Python 3 and a C++20 compiler, on Linux or macOS. The fixture extracts
the thread registration/exit blocks, async exclusion queue, exclusion insertion,
and page-store piece selection/cache refresh. Only guest memory, thread identity,
logging, and the final memcpy are simulated. It does not execute game code or
prove that all asynchronous sound lifetime bugs are resolved.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def section(source, start, end):
    if source.count(start) != 1:
        raise ValueError(f"expected one extraction marker: {start!r}")
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


def function(source, signature):
    if source.count(signature) != 1:
        raise ValueError(f"expected one function: {signature!r}")
    begin = source.index(signature)
    opening = source.index("{", begin)
    depth = 1
    position = opening + 1
    while depth:
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    return source[begin:position]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    root = tests.parents[1]
    threads = (root / "rpcs3/Emu/Cell/lv2/sys_ppu_thread.cpp").read_text()
    state = (root / "rpcs3/Emu/Rollback/rb_state.cpp").read_text()
    sources = {
        "registration.inc": section(
            threads, '\tif (ppu_name == "bnusCoreDecoderServerThread"',
            "\n\tppu.check_state();"),
        "exit.inc": section(
            threads, "\t{\n\t\t// tekken-rollback: the thread's object returns",
            "\n\tppu.state += cpu_flag::wait;"),
        "exclusions.inc": function(
            state, "\tvoid state_exclude(u32 begin, u32 end, const char* what)"),
        "async.inc": section(
            state, "\t// Main thread: drops every snapshot when the memory map changed",
            "\tvoid state_foreign_window("),
        "pieces.inc": function(
            state, "\t\tstatic std::vector<std::pair<u16, u16>> pieces_of(u32 page)"),
        "refresh.inc": function(state, "\t\tvoid refresh()"),
    }
    with tempfile.TemporaryDirectory(prefix="rpcs3 decoder snapshot ") as temporary:
        work = Path(temporary)
        for name, content in sources.items():
            (work / name).write_text(content)
        shutil.copy2(tests / "decoder_snapshot_fixture.cpp", work / "fixture.cpp")
        executable = work / "fixture"
        subprocess.run(
            [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
             str(work / "fixture.cpp"), "-o", str(executable)],
            check=True, timeout=60,
        )
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == "__main__":
    main()
