# linux-test-1 — experimental Linux source release

Linux port of Ekspym's RPCS3/GGPO rollback code for Tekken 6 BLUS30359 v1.03.
Start with [LINUX_TESTING.md](LINUX_TESTING.md). This prerelease supplies source,
not an AppImage or other binary. Firmware and game/update files are not included.

## Source identity

- RPCS3: the `linux-test-1` tag in `ilevn/rpcs3`.
- GGPO: `5a2880560952540e8bba9e6fcf9f916a03fd9a44` in `ilevn/ggpo`.
- RPCS3 upstream base: `084b1c53c472292966fa7bd68ab0b253e07c9d13`.
- GGPO upstream base: `2fc5dbb` from Ekspym's `tekken6-rollback` branch.

## Validation

Validated from the release preparation sources:

| Environment | Checks | Result |
|---|---|---|
| Ubuntu 26.04, GCC 15.2 / Clang 22 | GGPO five-configuration matrix, packet fixtures, installed C consumer | 55 tests passed; fixtures and consumer passed |
| Ubuntu 26.04 | Launcher and process-relaunch regressions | Passed; optional Windows-batch comparison also passed on editing host |
| Arch, Clang/LLVM 23.1.1, Qt 6.12.0 | Package install, actual RPCS3 configure, C++23/Qt-private probe, selected source compilation, GGPO Release | Passed; GGPO 11/11 |
| Fedora 44, Clang/LLVM 22.1.8, Qt 6.11.2 | Same checks as Arch | Passed; GGPO 11/11 |

Arch additionally used FFmpeg 9.0.2, OpenCV 5.0.0 and SDL 3.4.18; Fedora used
FFmpeg 8.1.3, OpenCV 4.13.0 and SDL 3.4.18. Selected source compilation covered
LLVM/JIT translation, media handling, camera tracking and the updater. These
checks did not link or launch the full emulator on Arch/Fedora.

The original Ubuntu development checkout completed a full build and reached
practice mode. A separate full rebuild from the committed release checkout is
still running and is not counted as a passed check for this prerelease. The
release checkout itself passed configuration, launcher/relaunch regressions, and
build-helper rejection checks for mismatched GGPO and invalid build options.

Container images used for package/configuration checks:

- Arch `archlinux:base`: `sha256:4e77cf2ea5f410e6f8be5abf93ccf17ce2436e87a138c167208356711a405dbd`.
- Fedora `registry.fedoraproject.org/fedora:44`: `sha256:1ff9eb02e4e2d7fb1175becac7139b2960c4fdcccedce81c86ec25b98ef3124d`.

## Known limits

Practice mode works on the Ubuntu development VM. Actual two-player rollback,
Windows/Linux interoperability, and determinism across native toolchains remain
unverified. The VM's roughly 41 FPS does not establish full-speed performance.
The optional ps3recomp-generated native module is not supported on Linux.

Use the same release and game profile for paired tests and report exact toolchain
versions. Start with offline practice, then Linux-to-Linux Player Match. Include
both peers' reviewed logs when reporting a desync.
