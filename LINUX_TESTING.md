# Linux test release: Tekken 6 rollback

Experimental x86-64 Linux port of [Ekspym's Tekken 6 rollback](https://github.com/Ekspym/Tekken6-rollback).
This release uses RPCS3 emulation. It does not require ps3recomp or generated native
code. Both players need their own Tekken 6 USA (BLUS30359), update 1.03, firmware,
and RPCN account. The supplied profile requires an AVX2-capable CPU.

## Get the matching sources

Use Git rather than GitHub's automatic source ZIP: the build needs submodules
and the separate GGPO repository. Run these commands in a new working directory:

```sh
git clone --branch linux-port https://github.com/ilevn/rpcs3.git
git clone https://github.com/ilevn/ggpo.git
cd rpcs3
# Once published, select the prerelease; otherwise use the linux-port branch.
git checkout linux-test-1
git -C ../ggpo checkout "$(cat scripts/ggpo-revision)"
git submodule update --init --recursive
```

The GGPO commit is fixed by the RPCS3 source revision. Do not replace it with
upstream GGPO or an arbitrary branch tip. The helper refuses mismatched or dirty
GGPO checkouts. Its public C API and wire format are unchanged by this release.

## Native build dependencies

Install dependencies with your distribution's package manager. These commands
are for Arch Linux and Fedora 44; other versions may need different package names.
The CMake minimums are Qt 6.7 and system LLVM 18, but minimum versions do not
establish tested compatibility. The original full build used Clang/LLVM 22 and
Qt 6.10.2 on Ubuntu 26.04. Record the actual versions used on each test system.

Arch Linux (perform a complete system upgrade, not a partial upgrade):

```sh
sudo pacman -Syu --needed base-devel git cmake ninja clang lld llvm python pkgconf abseil-cpp \
  qt6-base qt6-multimedia qt6-svg sdl3 ffmpeg opencv curl alsa-lib libpulse \
  openal libevdev systemd libxkbcommon-x11 zlib glew mesa vulkan-headers wayland \
  libxrandr libxinerama libxi libxcursor
```

Fedora 44:

```sh
sudo dnf install git cmake ninja-build clang lld llvm-devel gcc-c++ make python3 \
  pkgconf-pkg-config abseil-cpp-devel qt6-qtbase-devel qt6-qtbase-private-devel \
  qt6-qtmultimedia-devel qt6-qtsvg-devel SDL3-devel ffmpeg-free-devel \
  opencv-devel libcurl-devel alsa-lib-devel pulseaudio-libs-devel \
  openal-soft-devel libevdev-devel systemd-devel libxkbcommon-x11-devel \
  zlib-ng-compat-devel glew-devel mesa-libGL-devel mesa-libEGL-devel vulkan-headers \
  wayland-devel libXrandr-devel libXinerama-devel libXi-devel libXcursor-devel
```

A working Vulkan driver for your GPU is also needed for gameplay. Development
headers alone do not install or validate hardware acceleration.

## Build

```sh
./scripts/build_linux.sh
```

The helper uses the compiler/LLVM found on PATH, Release mode, system media
libraries, no LTO, and no machine-specific compiler optimization. Two build jobs
are the default; adjust to available RAM. It prints the toolchain and records
`build-linux/build-info.txt`, `configure.log`, and `build.log`.

```sh
BUILD_JOBS=4 ./scripts/build_linux.sh
CC=clang-22 CXX=clang++-22 LLVM_CONFIG=llvm-config-22 ./scripts/build_linux.sh
./scripts/build_linux.sh --configure-only
```

`GGPO_SOURCE_DIR`, `BUILD_DIR`, and `LLVM_DIR` can override their default paths.
Use a fresh build directory when changing compiler or LLVM. The helper never
installs packages, downloads sources, or changes your game settings. CMake reports
missing dependencies and the selected LLVM package version in `configure.log`.

## First launch and play

```sh
./scripts/play_online.sh
```

1. Install your firmware through File > Install Firmware.
2. Add your game and install BLUS30359 update 1.03 through RPCS3.
3. Configure your controller and RPCN account in this instance.
4. Boot practice mode first and establish whether the machine can sustain 60 FPS.
5. For an online test, both players use the same source release and supplied game
   profile. Start with Player Match; test Ranked Match after a successful session.

Always use the launcher to enable rollback. It installs the release profile under
`build-linux/bin/portable/custom_configs/` and refuses to overwrite a different
profile. Back up any existing custom profile before intentionally replacing it.
The portable directory holds your configuration and game data separately from
another RPCS3 installation. Do not share that directory as a release or bug report.

The official RPCS3 updater is disabled in this Linux fork because it would replace
the rollback build. Update by checking out the next source release, its pinned
GGPO revision and submodules, and rebuilding; coordinate updates with your peer.

Automatic input delay is the default; `./scripts/play_online.sh 2 boot` selects a
fixed two-frame delay and boots the installed game. `RPCS3_EXE` can select another
build's executable. The optional `fast` argument changes graphics restore waits;
leave it off for initial comparisons. The launcher clears inherited `RB_*` debug
flags and does not enable the separate direct GGPO transport or native module.

Use the unchanged release game profile for paired tests. Local graphics tuning
is an experiment: record all deviations and do not assume compatibility merely
because practice mode works. Different native toolchains may produce different
behavior even when the source revisions match.

## Logs and bug reports

The launcher prints both log locations:

- Match CSVs: `build-linux/bin/portable/rollback_log/boj_*.csv`.
- Emulator log: `${XDG_CACHE_HOME}/rpcs3/RPCS3.log` when set; otherwise
  `${XDG_CONFIG_HOME}/rpcs3/RPCS3.log` when set; otherwise `~/.cache/rpcs3/RPCS3.log`.
  Older emulator logs are retained there as `RPCS3_prev_*.log`.
- Build details: `build-linux/build-info.txt`, `configure.log`, and `build.log`.

Linux logs/cache are shared with other RPCS3 instances using the same XDG paths,
even with portable game data. Avoid simultaneous instances sharing that log path
when collecting a report. Save logs before another run overwrites them. Review
logs for account names, paths, network addresses, or other personal information
before posting them publicly. Never upload credentials, firmware or game files.

For a report, include the RPCS3/GGPO revisions, distribution/version, compiler and
LLVM versions, CPU/GPU and driver, settings changes, reproduction steps, both
players' relevant match logs, and whether the failure occurs offline too. State
whether the game maintains 60 FPS and whether either player uses Windows.

## Validation and limitations

Known before this source release: a full Ubuntu 26.04 x86-64 build with Clang/LLVM
22 and Qt 6.10.2; Vulkan game rendering and practice mode with BLUS30359 update
1.03; GGPO's 55-test matrix passed across five build configurations. The GPU VM
used for gameplay runs below 60 FPS, so it is not a performance reference.

See [release validation](LINUX_RELEASE.md) for fresh clean-checkout and distro
checks. Package installation/configuration checks are not gameplay validation.
Real Linux-to-Linux matches, mixed Windows/Linux matches, long-session stability,
and native-toolchain determinism remain unverified until testers establish them.
The optional Windows native-code module and separately simulated sound have not
been ported. The native recompiler may be a future milestone.

Asset-free regressions:

```sh
python3 tests/scripts/test_play_online.py
python3 tests/scripts/test_relaunch.py
(cd ../ggpo && sh tests/run_linux.sh)
```

The GGPO matrix additionally needs GCC, Clang, Ninja, Python and zlib headers.
Synthetic tests exercise transport, snapshots and packet compatibility; they do
not prove Tekken online synchronization. For game tests, start with matching
Linux builds, play several full matches including rematches, retain both logs,
and record any desync, missing audio, freeze, crash or failed relaunch.

## Experimental spectator diagnostics

On `fix/linux-spectator-sync`, spectator diagnostics are enabled by default with
the normal rollback launcher. Update and rebuild that branch before collecting
a new session. No settings change is needed on the Windows fighters just to
collect the Linux spectator trace. This does not establish that arbitrary build
versions are compatible.

The existing `RPCS3.log` contains `Spectator` entries covering:

- The next required frame for each fighter, its ready flags, the next 32 slot
  flags, the game's shared ready gate, and the highest available counters.
- Input-store ranges and counts of accepted, duplicate, rejected, backwards and
  nonconsecutive offers, including stores that clear a present next-slot flag.
- Actual spectator request attempts and type-9 responses: the last 32 ranges per
  report, in observed order, with an explicit omitted count if that limit is hit.
- Sampled request-pending, response-wait and input-wait state, plus role changes,
  game modes, counter resets, stalls and resumed simulation progress.

Summaries are emitted at most once every two seconds during a stable mode, plus
mode/role/reset and recovery events. Memory use is bounded; input contents and
peer identities are not recorded. Set `RB_SPECTATOR_DIAGNOSTICS=0` before launching
to disable the extra logging and transport observers.

Interpret the fields carefully: available counters are high-water marks, not
proof of contiguous inputs. Slot bits can be stale after ring reuse; a set bit
alone does not certify a frame. `cleared_next` can also count normal ring-slot
reuse. `cleared_pending` narrows this to present slots between the simulated
frame and the available counter, with `last_pending_clear` identifying the frame.
Store ranges describe calls into the input manager, not packet boundaries.
Request counts are send attempts, not delivery acknowledgments; response counts
are observations after the game decompresses received type-9 messages, not
proof decompression succeeded or their inputs were accepted. Sampled pending state can miss a request and response within one
task iteration. Response counts of zero or one reset the game's request clock; zero carries no
inputs. The request tag byte is recorded without inferring its meaning. No
response tag is inferred.

For another freeze, save the spectator's `RPCS3.log` (or `.log.gz`) before more
launches rotate it, and ideally a fighter's log from the same match. Record the
approximate time, exact builds and whether both fighters continued normally.
Look for both `Spectator diagnostic call hook ... installed` messages at startup;
an `unavailable` warning means request/response tracing is incomplete.

Run the game-free regression with Python and a C++20 compiler:

```sh
python3 tests/scripts/test_spectator_input.py
```

This exercises diagnostics enabled/disabled, forwarding of transport arguments
and return values, dropped/late/duplicate 17-frame batches, ring wrap and round
resets. It reproduces a late batch clearing a newer input's ready flag while the
available counter stays ahead. That is a characterization of a possible failure,
not proof this ordering caused a real session's freeze. The test does not run
the guest transport, validate live call-site dispatch, or prove online recovery.
This diagnostic change leaves input acceptance and recovery behavior unchanged.

RPCS3 retains its GPLv2 license. GGPO retains its MIT license. Preserve their
copyright and license notices when redistributing source or future binaries.
