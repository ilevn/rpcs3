#!/usr/bin/env bash
# Native source build for the experimental x86-64 Linux rollback port.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [[ ${1:-} == --help ]]; then
    cat <<'EOF'
Usage: scripts/build_linux.sh [--configure-only]
Environment: GGPO_SOURCE_DIR, BUILD_DIR, BUILD_JOBS (default 2), CC, CXX,
LLVM_CONFIG (llvm-config executable), LLVM_DIR (CMake package directory).
Requires the clean GGPO revision recorded in scripts/ggpo-revision.
Does not install packages, fetch sources, or change existing configurations.
EOF
    exit 0
fi
[[ $# == 0 || ( $# == 1 && $1 == --configure-only ) ]] || { echo 'Unknown arguments; use --help.' >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'This release targets x86-64 Linux.' >&2; exit 1; }
jobs=${BUILD_JOBS:-2}
[[ $jobs =~ ^[1-9][0-9]*$ ]] || { echo 'BUILD_JOBS must be a positive integer.' >&2; exit 1; }
for tool in git cmake ninja python3 pkg-config; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
ggpo=${GGPO_SOURCE_DIR:-"$root/../ggpo"}
expected=$(tr -d '\r\n' < "$root/scripts/ggpo-revision")
[[ $expected =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid GGPO revision file.' >&2; exit 1; }
[[ -f $ggpo/CMakeLists.txt ]] || { echo 'Clone https://github.com/ilevn/ggpo beside rpcs3, then check out scripts/ggpo-revision.' >&2; exit 1; }
actual=$(git -C "$ggpo" rev-parse HEAD)
[[ $actual == "$expected" ]] || { echo "GGPO revision mismatch: expected $expected, found $actual. Check out the pinned revision before building." >&2; exit 1; }
[[ -z $(git -C "$ggpo" status --porcelain --untracked-files=normal) ]] || { echo 'GGPO has local changes; use a clean checkout for the test release.' >&2; exit 1; }
if [[ -n ${CC:-} && -z ${CXX:-} || -z ${CC:-} && -n ${CXX:-} ]]; then
    echo 'Set CC and CXX together to select a matching compiler pair.' >&2
    exit 1
fi
if [[ -z ${CC:-} ]]; then
    if command -v clang >/dev/null && command -v clang++ >/dev/null; then CC=clang; else CC=cc; fi
fi
if [[ -z ${CXX:-} ]]; then
    if [[ $CC == clang ]]; then CXX=clang++; else CXX=c++; fi
fi
command -v "$CC" >/dev/null
command -v "$CXX" >/dev/null
if [[ -z ${LLVM_DIR:-} ]]; then
    if [[ -z ${LLVM_CONFIG:-} ]]; then
        for candidate in llvm-config llvm-config-23 llvm-config-22 llvm-config-21 llvm-config-20 llvm-config-19 llvm-config-18; do
            if command -v "$candidate" >/dev/null; then
                version=$("$candidate" --version)
                major=${version%%.*}
                if [[ $major =~ ^[0-9]+$ ]] && (( major >= 18 )); then LLVM_CONFIG=$candidate; break; fi
            fi
        done
    fi
    [[ -n ${LLVM_CONFIG:-} ]] || { echo 'Install LLVM development packages, or set LLVM_CONFIG / LLVM_DIR.' >&2; exit 1; }
    LLVM_DIR=$("$LLVM_CONFIG" --cmakedir)
fi
build=${BUILD_DIR:-"$root/build-linux"}
mkdir -p -- "$build"
build=$(cd -- "$build" && pwd -P)
{
    printf 'RPCS3 commit: '; git -C "$root" rev-parse HEAD
    printf 'GGPO commit: %s\nLLVM CMake directory: %s\n' "$actual" "$LLVM_DIR"
    git -C "$root" describe --always --dirty
    "$CC" --version
    "$CXX" --version
    cmake --version
    if [[ -f /etc/os-release ]]; then cat /etc/os-release; fi
    pkg-config --modversion Qt6Core libavcodec sdl3
} > "$build/build-info.txt"
cat "$build/build-info.txt"
args=( -S "$root" -B "$build" -G Ninja
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_C_COMPILER=$CC" "-DCMAKE_CXX_COMPILER=$CXX"
    "-DLLVM_DIR=$LLVM_DIR" -DBUILD_LLVM=OFF "-DGGPO_SOURCE_DIR=$(cd -- "$ggpo" && pwd -P)"
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DUSE_LTO=OFF -DUSE_NATIVE_INSTRUCTIONS=OFF
    -DUSE_SYSTEM_FFMPEG=ON -DUSE_SYSTEM_SDL=ON -DUSE_SYSTEM_CURL=ON
    -DUSE_SYSTEM_OPENCV=ON -DUSE_DISCORD_RPC=OFF )
if command -v ld.lld >/dev/null; then args+=( -DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=lld ); fi
cmake "${args[@]}" 2>&1 | tee "$build/configure.log"
if [[ ${1:-} != --configure-only ]]; then
    cmake --build "$build" --parallel "$jobs" 2>&1 | tee "$build/build.log"
    printf '\nLaunch with: RPCS3_EXE=%q %q\n' "$build/bin/rpcs3" "$root/scripts/play_online.sh"
fi
