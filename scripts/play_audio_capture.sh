#!/usr/bin/env bash
# Opt-in recorder around the normal rollback launcher; no game settings altered.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
export RPCS3_EXE="${RPCS3_EXE:-$script_dir/../build-linux/bin/rpcs3}"
exec python3 "$script_dir/audio_capture.py" -- bash "$script_dir/play_online.sh" "$@"
