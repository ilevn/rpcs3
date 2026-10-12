#!/usr/bin/env bash
# Tekken 6 BLUS30359 v1.03, emulated rollback profile from play_online.bat.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: play_online.sh [auto|DELAY] [boot] [fast]
  DELAY: nonnegative integer frame delay; default auto.
  boot: start installed BLUS30359 directly; otherwise open the game list.
  fast: shorten graphics waits during restore (may cause visual artifacts).
Options boot and fast can be given in either order after the optional delay.
RPCS3_EXE overrides the default ../build-linux/bin/rpcs3 executable.
Uses the executable's portable/ directory; never overwrites a different game profile.
EOF
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
rpc_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
rpc_delay=auto
rpc_boot=0
rpc_fast=0
if [[ ${1:-} == --help || ${1:-} == -h ]]; then usage; exit 0; fi
if [[ $# -gt 0 && $1 != boot && $1 != fast ]]; then
    rpc_delay=$1
    shift
fi
if [[ $rpc_delay != auto ]]; then
    [[ $rpc_delay =~ ^[0-9]{1,10}$ ]] || fail 'Delay must be auto or a nonnegative integer.'
    (( 10#$rpc_delay <= 2147483647 )) || fail 'Delay exceeds the supported integer range.'
fi
for rpc_option in "$@"; do
    case "$rpc_option" in
        boot) [[ $rpc_boot == 0 ]] || fail 'Duplicate boot option.'; rpc_boot=1 ;;
        fast) [[ $rpc_fast == 0 ]] || fail 'Duplicate fast option.'; rpc_fast=1 ;;
        *) usage >&2; fail "Unknown option: $rpc_option" ;;
    esac
done
rpc_exe=${RPCS3_EXE:-"$rpc_script_dir/../build-linux/bin/rpcs3"}
[[ -f $rpc_exe && -x $rpc_exe ]] || fail "RPCS3 executable not found: $rpc_exe (set RPCS3_EXE)."
rpc_exe=$(realpath -- "$rpc_exe")
rpc_portable="$(dirname -- "$rpc_exe")/portable"
rpc_profile="$rpc_script_dir/config_BLUS30359.yml"
rpc_config="$rpc_portable/custom_configs/config_BLUS30359.yml"
mkdir -p -- "$rpc_portable/custom_configs" "$rpc_portable/rollback_log"
# noclobber prevents replacing an existing profile, including during concurrent launches.
if [[ ! -e $rpc_config && ! -L $rpc_config ]]; then
    (set -o noclobber; cat -- "$rpc_profile" > "$rpc_config") || fail "Cannot install profile: $rpc_config"
fi
cmp -s -- "$rpc_profile" "$rpc_config" || fail "Game profile differs: $rpc_config
Back up your existing profile, then copy $rpc_profile to that path before playing.
Both players must use the matching rollback profile."
# Avoid inherited debug/native flags changing the packaged emulated profile.
# Native ELF loading and separately simulated sound are not supported yet.
for rpc_variable in "${!RB_@}"; do unset "$rpc_variable"; done
export RB_ONLINE_LEAD="$rpc_delay"
export RB_ONLINE_PREDICT='1'
export RB_ONLINE_MAX_PREDICT='5'
export RB_ONLINE_MAX_RESIM='20'
export RB_ONLINE_MAX_PREDICT_AGE='8'
export RB_ONLINE_STRESS_RING='1'
export RB_SNAP_FOREIGN='3'
export RB_SNAP_FOREIGN_THREADS='fios,hddfile,LOADALL,NU::File'
export RB_ONLINE_PREDICT_MODES='4'
export RB_ONLINE_NET_EXCLUDE='0'
export RB_RESIM_SKIP='90cbb0,90d1d0,915690,910798,91de98,90f0a8,90c598,905ae8,9063e0,9064c0,9065e0,906668,906750,9067d8,9068c0,906958,9069e0,906a80'
export RB_CATCHUP='1'
export RB_ONLINE_RESIM_SAVE='1'
export RB_RESIM_DRAWROOT='1'
export RB_FILM_UNDO='1'
export RB_SNAP_FILE_FOREIGN_THREADS='fios'
export RB_SIDE_HEAP='1'
export RB_SNAP_RING='0'
export RB_SNAP_STRESS_EVERY='999999999'
export RB_SNAP_RANGES='0x00A70000-0x00A80000,0x00C89000-0x00C8F000,0x00D142AC-0x00D142B0,0x00D2A500-0x00D2AA40,0x00D60000-0x00D66000,0x10000000-0x10000200,0x1038A000-0x10398000,0x36F00000-0x37000000,~0x00B00000-0x00C89000,~0x11A00000-0x11E00000,~0x11E00000-0x12100000,~0x37000000-0x37600000,~0x35000000-0x36F00000,~0x30000000-0x35000000,~0x123F0000-0x134A0000,~0x10130000-0x10150000,~0x10380000-0x1038A000,~0x10398000-0x103B1000,~0x10640000-0x10641000,~0x106E0000-0x106F0000,~0x107F0000-0x10810000,~0x10C99000-0x10C9A000,~0x10D39000-0x10D3A000,~0x1169C000-0x1169D000,~0x10090000-0x10130000,~0x10150000-0x10380000,~0x103B1000-0x10640000,~0x10641000-0x106E0000,~0x106F0000-0x107F0000,~0x10810000-0x10C99000,~0x10C9A000-0x10D39000,~0x10D3A000-0x1169C000,~0x1169D000-0x11A00000,~0x12100000-0x123F0000,~0x134A0000-0x14000000'
export RB_SNAP_EXCLUDE='0x00BCC000-0x00BD0000,0x30100000-0x30500000,0x30500000-0x31700000,0x00C89898-0x00C898B0,0x12000000-0x12005F00,0x373FB000-0x373FC200,0x00D2A400-0x00D2AA40'
export RB_SNAP_CALIBRATE_FROM='+60'
export RB_SNAP_SAVE_AT='+300'
export RB_SNAP_RESTORE_AT='999999999'
export RB_SNAP_CONT_CAL='1'
export RB_SNAP_TRACK='1'
export RB_SNAP_COOL_RANGES='12000000-14000000,30000000-38000000'
export RB_SNAP_IDLE_WAIT='0x00C898A8'
export RB_SNAP_SAVE_IDLE='1'
export RB_RSX_HOLD='1'
export RB_SNAP_WAIT_FLIP='0'
export RB_FAST_RESIM='1'
export RB_VIRTUAL_TB='1'
export RB_FIXED_TIME='1790942400'
export RB_SYNC_ADDR='0x00D142AC'
export RB_MODE='off'
if [[ $rpc_fast == 1 ]]; then export RB_DRAW_IDLE_RSX=1; else export RB_DRAW_IDLE_RSX=2; fi
export RB_ONLINE_HASH_OUT
rpc_match_log=$(mktemp "$rpc_portable/rollback_log/boj_XXXXXXXX")
RB_ONLINE_HASH_OUT="$rpc_match_log.csv"
mv -- "$rpc_match_log" "$RB_ONLINE_HASH_OUT"
# Match fs::get_cache_dir(): Linux logs use XDG cache, even in portable mode.
# Preserve set-but-empty XDG variables just as getenv() does in RPCS3.
if [[ ${XDG_CACHE_HOME+x} ]]; then rpc_cache=$XDG_CACHE_HOME
elif [[ ${XDG_CONFIG_HOME+x} ]]; then rpc_cache=$XDG_CONFIG_HOME
elif [[ ${HOME+x} ]]; then rpc_cache=$HOME/.cache
else rpc_cache=./cache
fi
rpc_log_dir="$rpc_cache/rpcs3"
# The emulator starts with portable/ as its working directory.
if [[ $rpc_log_dir != /* ]]; then rpc_log_dir="$rpc_portable/$rpc_log_dir"; fi
if [[ -f $rpc_log_dir/RPCS3.log ]]; then
    rpc_previous=$(mktemp "$rpc_log_dir/RPCS3_prev_XXXXXXXX")
    cp -- "$rpc_log_dir/RPCS3.log" "$rpc_previous"
    mv -- "$rpc_previous" "$rpc_previous.log"
fi
printf 'Tekken 6 rollback: delay %s, max prediction 5 frames, emulated code\nRPCS3: %s\nConfiguration: %s\nMatch log: %s\nEmulator log: %s/RPCS3.log\n' "$rpc_delay" "$rpc_exe" "$rpc_portable" "$RB_ONLINE_HASH_OUT" "$rpc_log_dir"
cd -- "$rpc_portable"
if [[ $rpc_boot == 1 ]]; then exec "$rpc_exe" '%RPCS3_GAMEID%:BLUS30359'; fi
exec "$rpc_exe"
