#!/usr/bin/env python3
"""Exercise the production Tekken input hooks with synthetic guest memory.

No game or firmware is needed. Tests cover both spectator input streams,
missing/reordered batches, ring wrap, lobby role changes, fighter prediction,
and bounded spectator diagnostics (enabled and disabled).
This does not replace a three-person RPCN lobby test.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from test_decoder_snapshot import function, section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--legacy-role-mapping", action="store_true",
                        help="negative control: restore the old remote-player mapping")
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    source = (tests.parents[1] / "rpcs3/Emu/Rollback/rb_online.cpp").read_text()
    prelude = section(source, "\t\tconstexpr u32 mgr_pointer", "\t\t// RB_ONLINE_HASH_OUT")
    if args.legacy_role_mapping:
        prelude = prelude.replace(
            "return local == 1 ? 2 : local == 2 ? 1 : 0;",
            "return local == 1 ? 2 : 1;")
    extracted = {"roles.inc": prelude,
                 "diagnostics.inc": section(source, "\t\t// Spectator diagnostics:", "\t\t// Predicted remote entry"),
                 "rb_spectator_diagnostics.h": (tests.parents[1] / "rpcs3/Emu/Rollback/rb_spectator_diagnostics.h").read_text()}
    for name, signature in {
        "hle_spectator_request": "\tu64 hle_spectator_request(ppu_thread& ppu, u64 transport, u64 peer, u64 message)",
        "hle_spectator_receive": "\tu64 hle_spectator_receive(ppu_thread& ppu, u64 message)",
        "read_entry": "\t\tentry_t read_entry(u32 addr)",
        "slot_addr": "\t\tu32 slot_addr(u32 mgr, u32 i, u32 frame)",
        "flag_addr": "\t\tu32 flag_addr(u32 mgr, u32 i, u32 frame)",
        "hle_input_available": "\t\tu32 hle_input_available(ppu_thread& ppu, u32 mgr, u32 player)",
        "hle_store_input": "\t\tu32 hle_store_input(ppu_thread& ppu, u32 mgr, u32 player, u32 frame, u32 src)",
    }.items():
        extracted[name + ".inc"] = function(source, signature)

    with tempfile.TemporaryDirectory(prefix="rpcs3 spectator input ") as temporary:
        work = Path(temporary)
        for name, content in extracted.items():
            (work / name).write_text(content)
        shutil.copy2(tests / "spectator_input_fixture.cpp", work / "fixture.cpp")
        executable = work / "fixture"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(work / "fixture.cpp"), "-o", str(executable)],
                       check=True, timeout=60)
        env = {k: v for k, v in os.environ.items() if not k.startswith("RB_")}
        env.update(RB_ONLINE_PREDICT="1", RB_ONLINE_MAX_PREDICT="5")
        subprocess.run([str(executable)], env=env, check=True, timeout=30)
        env["RB_SPECTATOR_DIAGNOSTICS"] = "0"
        subprocess.run([str(executable)], env=env, check=True, timeout=30)


if __name__ == "__main__":
    main()
