#!/usr/bin/env python3
"""Configure portable mcp_config.json for the current host OS (Windows / POSIX)."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
MCP_CONFIG_PATH = PLUGIN_ROOT / "mcp_config.json"

def _escape_cmd_metachars(expr: str) -> str:
    """Escape cmd metacharacters for passing an inner command through `cmd /c` without quotes."""
    return "".join("^" + ch if ch in "()&<>^|" else ch for ch in expr)


_WINDOWS_CMD_INNER = (
    "(set _D=)& "
    "(if defined PLUGIN_ROOT (set _P=!PLUGIN_ROOT:/=\\!& pushd !_P! 2>nul && ((if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=!CD!))& popd)))& "
    "(if not defined _D if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=.))& "
    "(if not defined _D if defined ANTIGRAVITY_GEMINI_DIR (set _G=!ANTIGRAVITY_GEMINI_DIR:/=\\!& set _R=config& (if defined ANTIGRAVITY_CONFIG_REL_DIR (set _R=!ANTIGRAVITY_CONFIG_REL_DIR:/=\\!))& pushd !_G!\\!_R!\\plugins\\hakimi-hiss 2>nul && ((if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=!CD!))& popd)))& "
    "(if not defined _D if defined USERPROFILE (set _U=!USERPROFILE:/=\\!& (if defined ANTIGRAVITY_CONFIG_REL_DIR (set _R=!ANTIGRAVITY_CONFIG_REL_DIR:/=\\!& pushd !_U!\\.gemini\\!_R!\\plugins\\hakimi-hiss 2>nul && ((if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=!CD!))& popd)))& (if not defined _D (pushd !_U!\\.gemini\\config\\plugins\\hakimi-hiss 2>nul && ((if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=!CD!))& popd)))& (if not defined _D (pushd !_U!\\.agents\\plugins\\hakimi-hiss 2>nul && ((if exist skills\\hakimi-hiss\\scripts\\launch_mcp.cmd (set _D=!CD!))& popd)))))& "
    "(if defined _D (cd /d !_D! && call skills\\hakimi-hiss\\scripts\\launch_mcp.cmd) else (echo [hakimi-hiss] launch_mcp.cmd not found>&2 & exit /b 1))"
)

WINDOWS_CMD_EXPR = "cmd /d /q /v:on /c " + _escape_cmd_metachars(_WINDOWS_CMD_INNER)

POSIX_SH_EXPR = (
    'set -e; '
    'rel=${ANTIGRAVITY_CONFIG_REL_DIR:-config}; '
    'rel=${rel#/}; rel=${rel%/}; '
    '[ -n "$rel" ] || rel=config; '
    'gem_d=""; '
    '[ -z "${ANTIGRAVITY_GEMINI_DIR:-}" ] || gem_d="${ANTIGRAVITY_GEMINI_DIR%/}/$rel/plugins/hakimi-hiss"; '
    'home_r=""; home_c=""; home_a=""; '
    'if [ -n "${HOME:-}" ]; then '
    'h="${HOME%/}"; '
    'home_r="$h/.gemini/$rel/plugins/hakimi-hiss"; '
    'home_c="$h/.gemini/config/plugins/hakimi-hiss"; '
    'home_a="$h/.agents/plugins/hakimi-hiss"; '
    'fi; '
    'for d in "${PLUGIN_ROOT:-}" "." "$gem_d" "$home_r" "$home_c" "$home_a"; do '
    '[ -n "$d" ] || continue; '
    'case "$d" in /) l="/skills/hakimi-hiss/scripts/launch_mcp.sh" ;; '
    '*) l="${d%/}/skills/hakimi-hiss/scripts/launch_mcp.sh" ;; esac; '
    'if [ -f "$l" ]; then exec sh "$l"; fi; '
    'done; '
    'echo "[hakimi-hiss] launch_mcp.sh not found" >&2; exit 1'
)


def build_config(target: str) -> dict:
    resolved = target
    if resolved == "auto":
        resolved = "windows" if os.name == "nt" else "posix"

    if resolved == "windows":
        entry = {
            "command": "cmd",
            "args": ["/d", "/q", "/c", WINDOWS_CMD_EXPR],
        }
    elif resolved == "posix":
        entry = {
            "command": "sh",
            "args": ["-c", POSIX_SH_EXPR],
        }
    elif resolved == "python3":
        entry = {
            "command": "python3",
            "args": ["-u", "${PLUGIN_ROOT}/skills/hakimi-hiss/scripts/mcp_server.py"],
        }
    else:
        raise ValueError(f"Unsupported target: {target}")

    return {"mcpServers": {"hakimi-hiss-channel": entry}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure hakimi-hiss mcp_config.json for current OS.")
    parser.add_argument(
        "--target",
        choices=["auto", "windows", "posix", "python3"],
        default="auto",
        help="Target MCP launch strategy (default: auto-detect OS).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print config without writing file.")
    args = parser.parse_args()

    sh_path = PLUGIN_ROOT / "skills" / "hakimi-hiss" / "scripts" / "launch_mcp.sh"
    if sh_path.exists() and os.name != "nt":
        sh_path.chmod(sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    cfg = build_config(args.target)
    rendered = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    if not args.dry_run:
        MCP_CONFIG_PATH.write_text(rendered, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "target": args.target,
                "os_name": os.name,
                "config_path": str(MCP_CONFIG_PATH),
                "dry_run": args.dry_run,
                "config": cfg,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
