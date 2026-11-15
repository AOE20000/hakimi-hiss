#!/bin/sh
set -eu

case "$0" in
    */*)
        script_parent=${0%/*}
        [ -n "$script_parent" ] || script_parent=/
        ;;
    *)
        script_parent=.
        ;;
esac
SCRIPT_DIR=$(CDPATH= cd -- "$script_parent" && pwd)
SERVER="$SCRIPT_DIR/mcp_server.py"
if [ ! -f "$SERVER" ]; then
    echo "[hakimi-hiss] mcp_server.py not found at $SERVER" >&2
    exit 1
fi

is_py310() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' </dev/null >/dev/null 2>&1
}

old_ifs_set=0
old_ifs=
if [ "${IFS+x}" = "x" ]; then
    old_ifs_set=1
    old_ifs=$IFS
fi

restore_shell_opts() {
    set +f
    if [ "$old_ifs_set" -eq 1 ]; then
        IFS=$old_ifs
    else
        unset IFS
    fi
}

CLEAN_DIR=
normalize_dir() {
    raw=$1
    stripped=
    while :; do
        case "$raw" in
            *\"*)
                stripped=${stripped}${raw%%\"*}
                raw=${raw#*\"}
                ;;
            *)
                stripped=${stripped}${raw}
                break
                ;;
        esac
    done
    while :; do
        case "$stripped" in
            ""|/) break ;;
            */) stripped=${stripped%/} ;;
            *) break ;;
        esac
    done
    CLEAN_DIR=$stripped
}

FOUND_PY=
try_dir() {
    normalize_dir "$1"
    dir=$CLEAN_DIR
    [ -n "$dir" ] || return 1
    case "$dir" in
        *[Ww][Ii][Nn][Dd][Oo][Ww][Ss][Aa][Pp][Pp][Ss]*) return 1 ;;
    esac
    [ -d "$dir" ] || return 1

    for name in python3 python python3.exe python.exe; do
        if [ "$dir" = "/" ]; then
            cand="/$name"
        else
            cand="$dir/$name"
        fi
        if [ -f "$cand" ] && [ ! -d "$cand" ] && [ -x "$cand" ] && is_py310 "$cand"; then
            FOUND_PY=$cand
            return 0
        fi
    done
    return 1
}

try_subdir() {
    normalize_dir "$1"
    [ -n "$CLEAN_DIR" ] || return 1
    if [ "$CLEAN_DIR" = "/" ]; then
        try_dir "/$2"
    else
        try_dir "$CLEAN_DIR/$2"
    fi
}

probe_fallbacks() {
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        try_subdir "$VIRTUAL_ENV" "bin" && return 0
        try_subdir "$VIRTUAL_ENV" "Scripts" && return 0
    fi
    if [ -n "${CONDA_PREFIX:-}" ]; then
        try_subdir "$CONDA_PREFIX" "bin" && return 0
        try_dir "$CONDA_PREFIX" && return 0
    fi
    for fallback_dir in "/opt/homebrew/bin" "/usr/local/bin"; do
        try_dir "$fallback_dir" && return 0
    done
    if [ -n "${HOME:-}" ]; then
        try_subdir "$HOME" ".local/bin" && return 0
    fi
    for fallback_dir in \
        "/Library/Frameworks/Python.framework/Versions/Current/bin" \
        "/opt/local/bin"
    do
        try_dir "$fallback_dir" && return 0
    done
    if [ -n "${SCOOP:-}" ]; then
        try_subdir "$SCOOP" "shims" && return 0
    fi
    if [ -n "${HOME:-}" ]; then
        try_subdir "$HOME" "scoop/shims" && return 0
    fi
    return 1
}

set -f
IFS=':'
for dir in ${PATH:-}; do
    if try_dir "$dir"; then
        break
    fi
done
restore_shell_opts

if [ -z "$FOUND_PY" ]; then
    probe_fallbacks || true
fi

if [ -n "$FOUND_PY" ]; then
    exec "$FOUND_PY" -u "$SERVER" "$@"
fi

if command -v py >/dev/null 2>&1 && py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' </dev/null >/dev/null 2>&1; then
    exec py -3 -u "$SERVER" "$@"
fi

echo "[hakimi-hiss] Python >= 3.10 not found in PATH or fallback locations" >&2
exit 1
