#!/usr/bin/env bash
# Experimental: preserve playback progress only for fully matching voices.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
export T6_AUDIO_VOICE_RUNTIME=keep
exec bash "$script_dir/play_audio_capture.sh" "$@"
