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

Release preparation is in progress. Final validation results will replace this
paragraph before the prerelease tag is created.

## Known limits

Practice mode works on the Ubuntu development VM. Actual two-player rollback,
Windows/Linux interoperability, and determinism across native toolchains remain
unverified. The VM's roughly 41 FPS does not establish full-speed performance.
The optional ps3recomp-generated native module is not supported on Linux.

Use the same release and game profile for paired tests and report exact toolchain
versions. Start with offline practice, then Linux-to-Linux Player Match. Include
both peers' reviewed logs when reporting a desync.
