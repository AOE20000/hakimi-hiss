#!/usr/bin/env python3
"""Hakimi Hiss Duel (哈基米哈气审查) interactive channel engine.

Manages persistent subagent conversation bindings, bug hunting with real-time
deduplication & @file scope enforcement (Round 1 / 一胜), cross-fixing &
perfection judging (Round 2 / 二胜), 【啥子】 tagging, and manual resets.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import difflib
import hashlib
import json
import os
import posixpath
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PLUGIN_ROOT / "data"
STATE_FILE = DATA_DIR / "arena_state.json"
LOCK_DIR = DATA_DIR / "arena_state.lock"

VALID_AGENTS = ("A", "B")
VALID_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
VALID_FIX_STATUSES = ("FIXED", "CANT_FIX")
VALID_CROSS_FIX_MODES = ("auto", "worktree", "wave")
VALID_VERIFY_VERDICTS = ("VERIFIED", "REJECT_WITH_HISS")
VALID_INTEGRATE_ACTIONS = ("status", "merge", "cleanup")
VALID_VERDICTS = ("PERFECT", "PASS", "FAILED")
VALID_BUG_STATUSES = (
    "OPEN",
    "IN_CROSS_FIX",
    "PENDING_JUDGE",
    "FIXED_PERFECT",
    "FIXED_PASS",
    "FIX_FAILED",
    "SHAZI_FAILED",
)

VERDICT_POINTS = {
    "PERFECT": 2,
    "PASS": 1,
    "FAILED": -1,
}

AGENT_PROFILES = {
    "A": {
        "name": "哈基米A（橘座）",
        "specialty": "逻辑漏洞、并发竞态、空指针与契约错配",
    },
    "B": {
        "name": "哈基米B（狸花）",
        "specialty": "边界条件、安全注入、资源泄漏与异常吞没",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _default_agent_state(agent_id: str) -> dict[str, Any]:
    profile = AGENT_PROFILES[agent_id]
    return {
        "id": agent_id,
        "name": profile["name"],
        "specialty": profile["specialty"],
        "conv_id": None,
        "round1_wins": 0,
        "round2_wins": 0,
        "duplicate_attempts": 0,
        "shazi_count": 0,
        "shazi_badges": [],
    }


def _default_workspace_state() -> dict[str, Any]:
    return {
        "phase": "IDLE",
        "round_number": 0,
        "scope_mode": "project",
        "target_files": [],
        "agents": {
            "A": _default_agent_state("A"),
            "B": _default_agent_state("B"),
        },
        "next_bug_seq": 1,
        "bugs": [],
        "current_cross_fix_bug_ids": [],
        "cross_fix_plan": None,
        "file_leases": {},
        "worktrees": None,
        "round1_result": None,
        "round2_result": None,
        "history": [],
        "updated_at": _now_iso(),
    }


_PROCESS_THREAD_LOCK = threading.Lock()


def _is_pid_alive(pid: int) -> bool:
    """Check cross-platform whether a process ID is currently alive."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            synchronize = 0x00100000
            query_limited = 0x1000
            error_access_denied = 5
            wait_timeout = 0x00000102
            handle = kernel32.OpenProcess(synchronize | query_limited, False, int(pid))
            if not handle:
                return kernel32.GetLastError() == error_access_denied
            try:
                return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


def _write_lock_owner(lock_dir: Path, token: str) -> None:
    owner_file = lock_dir / "owner.json"
    payload = json.dumps(
        {
            "token": token,
            "pid": os.getpid(),
            "acquired_at": time.time(),
        },
        ensure_ascii=False,
    )
    owner_file.write_text(payload, encoding="utf-8")


def _read_lock_owner_info(lock_dir: Path) -> dict[str, Any] | None:
    owner_file = lock_dir / "owner.json"
    try:
        data = json.loads(owner_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return None


def _read_lock_owner_token(lock_dir: Path) -> str | None:
    info = _read_lock_owner_info(lock_dir)
    if info and isinstance(info.get("token"), str):
        return info["token"]
    return None


def _lock_effective_mtime(lock_dir: Path) -> float | None:
    try:
        mtime = lock_dir.stat().st_mtime
    except OSError:
        return None
    hb_file = lock_dir / "heartbeat"
    try:
        if hb_file.exists():
            mtime = max(mtime, hb_file.stat().st_mtime)
    except OSError:
        pass
    return mtime


def _touch_lock_heartbeat(lock_dir: Path, my_token: str) -> None:
    if _read_lock_owner_token(lock_dir) != my_token:
        return
    try:
        os.utime(lock_dir, None)
        return
    except OSError:
        pass
    if _read_lock_owner_token(lock_dir) != my_token:
        return
    try:
        (lock_dir / "heartbeat").write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _reclaim_stale_lock(lock_dir: Path, expected_token: str | None, stale_after_s: float = 30.0) -> None:
    reclaim_dir = lock_dir.with_name(f"{lock_dir.name}.reclaim")
    try:
        os.mkdir(reclaim_dir)
    except FileExistsError:
        try:
            if time.time() - reclaim_dir.stat().st_mtime > 10.0:
                shutil.rmtree(reclaim_dir, ignore_errors=True)
        except OSError:
            pass
        return
    except OSError:
        return

    try:
        effective_mtime = _lock_effective_mtime(lock_dir)
        if effective_mtime is None or time.time() - effective_mtime <= stale_after_s:
            return
        owner_info = _read_lock_owner_info(lock_dir)
        cur_token = owner_info.get("token") if owner_info and isinstance(owner_info.get("token"), str) else None
        if expected_token is not None and cur_token is not None and cur_token != expected_token:
            return
        owner_pid = owner_info.get("pid") if owner_info else None
        if isinstance(owner_pid, int) and not isinstance(owner_pid, bool) and _is_pid_alive(owner_pid):
            return
        trash_dir = lock_dir.with_name(f"{lock_dir.name}.stale.{os.getpid()}.{time.time_ns()}")
        try:
            os.replace(lock_dir, trash_dir)
        except OSError:
            # Windows may reject os.replace when directory is non-empty or already removed; fallback to rmtree
            shutil.rmtree(lock_dir, ignore_errors=True)
        else:
            shutil.rmtree(trash_dir, ignore_errors=True)
    finally:
        shutil.rmtree(reclaim_dir, ignore_errors=True)


def _release_owned_lock(lock_dir: Path, my_token: str) -> None:
    reclaim_dir = lock_dir.with_name(f"{lock_dir.name}.reclaim")
    reclaim_acquired = False
    for _ in range(50):
        try:
            os.mkdir(reclaim_dir)
            reclaim_acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - reclaim_dir.stat().st_mtime > 10.0:
                    shutil.rmtree(reclaim_dir, ignore_errors=True)
                    continue
            except OSError:
                pass
            time.sleep(0.005)
        except OSError:
            break

    try:
        cur_token = _read_lock_owner_token(lock_dir)
        if cur_token != my_token:
            return
        trash_dir = lock_dir.with_name(f"{lock_dir.name}.releasing.{os.getpid()}.{time.time_ns()}")
        try:
            os.replace(lock_dir, trash_dir)
        except OSError:
            if _read_lock_owner_token(lock_dir) == my_token:
                shutil.rmtree(lock_dir, ignore_errors=True)
        else:
            shutil.rmtree(trash_dir, ignore_errors=True)
    finally:
        if reclaim_acquired:
            shutil.rmtree(reclaim_dir, ignore_errors=True)


@contextmanager
def _state_lock(
    timeout_s: float = 10.0,
    stale_after_s: float = 30.0,
    heartbeat_interval_s: float = 5.0,
) -> Iterator[None]:
    """Cross-platform directory-based mutex with PID liveness check, heartbeat renewal, and ownership token."""
    lock_dir = LOCK_DIR
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s

    remaining = max(0.0, deadline - time.monotonic())
    if not _PROCESS_THREAD_LOCK.acquire(timeout=remaining):
        raise TimeoutError("获取哈基米通道锁超时，请稍后重试。")

    acquired = False
    my_token = f"{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{secrets.token_hex(6)}"
    try:
        while time.monotonic() < deadline:
            try:
                os.mkdir(lock_dir)
                try:
                    _write_lock_owner(lock_dir, my_token)
                except OSError:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                    raise
                acquired = True
                break
            except FileExistsError:
                try:
                    effective_mtime = _lock_effective_mtime(lock_dir)
                    if effective_mtime is not None and time.time() - effective_mtime > stale_after_s:
                        observed_token = _read_lock_owner_token(lock_dir)
                        _reclaim_stale_lock(lock_dir, observed_token, stale_after_s=stale_after_s)
                        continue
                except OSError:
                    pass
                time.sleep(0.03)
        if not acquired:
            raise TimeoutError("获取哈基米通道锁超时，请稍后重试。")
        stop_heartbeat = threading.Event()
        hb_interval = max(0.02, min(heartbeat_interval_s, stale_after_s / 3.0))

        def _heartbeat_loop() -> None:
            while not stop_heartbeat.wait(hb_interval):
                _touch_lock_heartbeat(lock_dir, my_token)

        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            name="hakimi-lock-heartbeat",
            daemon=True,
        )
        hb_thread.start()
        try:
            yield
        finally:
            stop_heartbeat.set()
            hb_thread.join(timeout=1.0)
            _release_owned_lock(lock_dir, my_token)
    finally:
        _PROCESS_THREAD_LOCK.release()


def _load_root_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"version": 1, "workspaces": {}}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            raw = STATE_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("workspaces"), dict):
                return data
            raise RuntimeError(f"状态文件 {STATE_FILE} 顶层结构损坏（缺少有效的 workspaces 字典），已拒绝覆盖以保护历史数据。")
        except PermissionError as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.02)
                continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"读取或解析状态文件 {STATE_FILE} 失败，已中止操作以防止覆盖现有历史数据: {exc}") from exc
    raise RuntimeError(f"读取状态文件 {STATE_FILE} 权限受限，已中止操作以防止覆盖现有历史数据: {last_exc}") from last_exc


def _save_root_state(root: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_FILE.parent / f"arena_state.{os.getpid()}.{time.time_ns()}.tmp"
    payload = json.dumps(root, ensure_ascii=False, indent=2)
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        last_exc: PermissionError | None = None
        for attempt in range(5):
            try:
                os.replace(tmp_path, STATE_FILE)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.02 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _strip_quotes(raw: str) -> str:
    s = raw.strip()
    while s:
        prev = s
        while len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1].strip()
        if s and (s[0] in ('"', "'") or s[-1] in ('"', "'")):
            s = s.strip('"').strip("'").strip()
        if s == prev:
            break
    return s


def _norm_drive_path(drive: str, rest: str) -> str:
    d = drive.lower()
    if not rest:
        return f"{d}:/"
    norm_rest = posixpath.normpath("/" + rest).lstrip("/")
    if norm_rest in ("", "."):
        return f"{d}:/"
    return f"{d}:/{norm_rest}".lower()


def _normalize_workspace_key(workspace: str | None) -> str:
    if not workspace or not isinstance(workspace, str) or not workspace.strip():
        return "default"
    cleaned = _strip_quotes(workspace).replace("\\", "/")
    if not cleaned or cleaned in ("default", "__default__"):
        return cleaned or "default"

    def _norm_abs_str(raw_abs: str) -> str:
        unc_prefix = "//" if raw_abs.startswith("//") else ""
        collapsed = re.sub(r"/+", "/", raw_abs)
        if unc_prefix and not collapsed.startswith("//"):
            collapsed = "/" + collapsed
        m_drv = re.match(r"^([A-Za-z]):(?:/(.*))?$", collapsed)
        if m_drv:
            return _norm_drive_path(m_drv.group(1), m_drv.group(2) or "")
        if collapsed.startswith("/"):
            norm = posixpath.normpath(collapsed)
            return norm.lower() if os.name == "nt" else norm
        return collapsed

    unc_prefix = "//" if cleaned.startswith("//") else ""
    collapsed = re.sub(r"/+", "/", cleaned)
    if unc_prefix and not collapsed.startswith("//"):
        collapsed = "/" + collapsed

    m_drive = re.match(r"^([A-Za-z]):(?:/(.*))?$", collapsed)
    if m_drive or collapsed.startswith("/"):
        return _norm_abs_str(collapsed)

    if "\x00" not in cleaned:
        try:
            resolved = Path(cleaned).resolve().as_posix()
        except (OSError, ValueError):
            resolved = os.path.abspath(cleaned).replace("\\", "/")
        return _norm_abs_str(resolved)
    return cleaned


def _find_workspace_key(workspaces: dict[str, Any], norm_key: str) -> str:
    if norm_key in workspaces:
        return norm_key
    for existing_key in workspaces:
        if isinstance(existing_key, str) and _normalize_workspace_key(existing_key) == norm_key:
            return existing_key
    return norm_key


def _repair_ws_structure(ws: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_workspace_state()
    for field, default_val in defaults.items():
        if field == "agents":
            continue
        if field not in ws or (ws[field] is None and default_val is not None):
            if isinstance(default_val, list):
                ws[field] = list(default_val)
            else:
                ws[field] = default_val
    if not isinstance(ws.get("bugs"), list):
        ws["bugs"] = []
    if not isinstance(ws.get("target_files"), list):
        ws["target_files"] = []
    if not isinstance(ws.get("history"), list):
        ws["history"] = []
    if not isinstance(ws.get("current_cross_fix_bug_ids"), list):
        ws["current_cross_fix_bug_ids"] = []
    if not isinstance(ws.get("file_leases"), dict):
        ws["file_leases"] = {}
    if "cross_fix_plan" not in ws or (ws["cross_fix_plan"] is not None and not isinstance(ws["cross_fix_plan"], dict)):
        ws["cross_fix_plan"] = None
    if "worktrees" not in ws or (ws["worktrees"] is not None and not isinstance(ws["worktrees"], dict)):
        ws["worktrees"] = None
    if not isinstance(ws.get("round_number"), int) or isinstance(ws.get("round_number"), bool):
        try:
            ws["round_number"] = int(ws["round_number"])
        except (TypeError, ValueError):
            ws["round_number"] = 0
    if not isinstance(ws.get("next_bug_seq"), int) or isinstance(ws.get("next_bug_seq"), bool):
        try:
            ws["next_bug_seq"] = max(1, int(ws["next_bug_seq"]))
        except (TypeError, ValueError):
            ws["next_bug_seq"] = len(ws["bugs"]) + 1

    agents = ws.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        ws["agents"] = agents
    for aid in VALID_AGENTS:
        default_agent = _default_agent_state(aid)
        if aid not in agents or not isinstance(agents[aid], dict):
            agents[aid] = default_agent
        else:
            for ak, av in default_agent.items():
                if ak not in agents[aid]:
                    agents[aid][ak] = list(av) if isinstance(av, list) else av
            if not isinstance(agents[aid].get("shazi_badges"), list):
                agents[aid]["shazi_badges"] = []
    return ws


def _get_ws_state(root: dict[str, Any], workspace: str | None) -> tuple[str, dict[str, Any]]:
    norm_key = _normalize_workspace_key(workspace)
    workspaces = root.setdefault("workspaces", {})
    key = _find_workspace_key(workspaces, norm_key)
    ws = workspaces.get(key)
    if not isinstance(ws, dict):
        ws = _default_workspace_state()
        workspaces[key] = ws
    _repair_ws_structure(ws)
    return key, ws


def _normalize_path(path_str: str, workspace: str | None = None, extra_roots: list[str] | None = None) -> str:
    if not isinstance(path_str, str):
        return ""
    cleaned = _clean_file_token(path_str).replace("\\", "/")
    if not cleaned:
        return ""
    cleaned = re.sub(r"/+", "/", cleaned)

    def _norm_basic(p: str) -> str:
        m = re.match(r"^([A-Za-z]):(?:/(.*))?$", p)
        if m:
            return _norm_drive_path(m.group(1), m.group(2) or "")
        np = posixpath.normpath(p)
        while np.startswith("./"):
            np = np[2:]
        if np != "/" and np.endswith("/"):
            np = np.rstrip("/")
        return np.lower() if os.name == "nt" else np

    cand_has_drive = bool(re.match(r"^[A-Za-z]:(/|$)", cleaned))
    if not cleaned.startswith("/") and not cand_has_drive:
        rel_norm = posixpath.normpath(cleaned)
        if rel_norm == ".." or rel_norm.startswith("../"):
            return _norm_basic(cleaned)

    roots_to_try: list[str] = []
    if extra_roots:
        for rt in extra_roots:
            rt_key = _normalize_workspace_key(rt)
            if rt_key and rt_key not in ("default", "__default__"):
                roots_to_try.append(rt_key)
    ws_key = _normalize_workspace_key(workspace)
    if ws_key not in ("default", "__default__"):
        roots_to_try.append(ws_key)

    for root_key in roots_to_try:
        ws_path = Path(root_key)
        if ws_path.is_absolute() and "\x00" not in cleaned:
            try:
                ws_root = ws_path.resolve()
                if cleaned.startswith("/") or cand_has_drive:
                    cand_resolved = Path(cleaned).resolve()
                else:
                    cand_resolved = (ws_root / posixpath.normpath(cleaned)).resolve()
                if cand_resolved != ws_root and cand_resolved.is_relative_to(ws_root):
                    return _norm_basic(cand_resolved.relative_to(ws_root).as_posix())
            except (OSError, ValueError):
                pass
        # Cross-platform string prefix fallback (e.g. logical Windows path tested on POSIX)
        cand_basic = _norm_basic(cleaned)
        ws_norm_prefix = _norm_basic(root_key).rstrip("/")
        if ws_norm_prefix and cand_basic.startswith(ws_norm_prefix + "/"):
            return _norm_basic(cand_basic[len(ws_norm_prefix) + 1 :])

    return _norm_basic(cleaned)


def _active_extra_roots(ws: dict[str, Any], agent_id: str | None = None) -> list[str]:
    wt = ws.get("worktrees")
    if not isinstance(wt, dict) or not wt.get("enabled"):
        return []

    candidates: list[tuple[int, str]] = []
    target_agents = (agent_id,) if agent_id in VALID_AGENTS else VALID_AGENTS
    for aid in target_agents:
        entry = wt.get(aid)
        if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"].strip():
            candidates.append((0, entry["path"]))

    repo_root = wt.get("repo_root")
    if isinstance(repo_root, str) and repo_root.strip():
        candidates.append((1, repo_root))

    def _root_sort_key(item: tuple[int, str]) -> tuple[int, int, int]:
        is_repo, raw = item
        norm = _normalize_workspace_key(raw)
        try:
            depth = len(Path(norm).resolve().parts) if Path(norm).is_absolute() else len(Path(norm).parts)
        except OSError:
            depth = len(Path(norm).parts)
        return (-depth, -len(norm), is_repo)

    candidates.sort(key=_root_sort_key)

    roots: list[str] = []
    seen: set[str] = set()
    for _, raw in candidates:
        norm = _normalize_workspace_key(raw)
        if norm and norm not in seen:
            seen.add(norm)
            roots.append(raw)
    return roots


def _path_matches_target(candidate: str, targets: list[str], workspace: str | None = None) -> bool:
    cand_norm = _normalize_path(candidate, workspace=workspace)
    if not cand_norm:
        return False
    for tgt in targets:
        tgt_norm = _normalize_path(tgt, workspace=workspace)
        if not tgt_norm:
            continue
        if cand_norm == tgt_norm:
            return True
    return False


_ASCII_STOPWORDS = frozenset(
    {"a", "an", "the", "in", "on", "of", "to", "for", "by", "at", "or", "and", "is", "are", "be", "with"}
)


def _tokenize(text: str) -> set[str]:
    split_camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text.strip())
    lowered = re.sub(r"\s+", " ", split_camel.lower())
    words: set[str] = set()
    for ident in re.findall(r"[a-z0-9_]+", lowered):
        parts = [p for p in ident.split("_") if p and p not in _ASCII_STOPWORDS]
        words.update(parts)
        if "_" not in ident and ident not in _ASCII_STOPWORDS:
            words.add(ident)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    for run in cjk_runs:
        if len(run) == 1:
            words.add(run)
        else:
            for i in range(len(run) - 1):
                words.add(run[i : i + 2])
    return words


def _text_similarity(a: str, b: str) -> float:
    toks_a = _tokenize(a)
    toks_b = _tokenize(b)
    jaccard = (len(toks_a & toks_b) / len(toks_a | toks_b)) if (toks_a and toks_b) else 0.0
    a_norm = re.sub(r"\s+", " ", a.strip().lower())
    b_norm = re.sub(r"\s+", " ", b.strip().lower())
    seq_ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio() if (a_norm and b_norm) else 0.0
    # Only promote pure character sequence similarity when strings are near-identical typos/copies;
    # otherwise rely on token overlap so unrelated English titles cannot collide via shared letters.
    if seq_ratio >= 0.72:
        return max(jaccard, seq_ratio)
    return jaccard


def _line_distance(s1: int, e1: int, s2: int, e2: int) -> int:
    if max(s1, s2) <= min(e1, e2):
        return 0
    return min(abs(s1 - e2), abs(s2 - e1))


def _is_duplicate_bug(
    existing: dict[str, Any],
    norm_file: str,
    line_start: int,
    line_end: int,
    title: str,
    description: str,
    category: str,
    workspace: str | None = None,
) -> bool:
    ex_raw_file = existing.get("file") or existing.get("file_norm") or ""
    ex_norm = _normalize_path(str(ex_raw_file), workspace=workspace) if workspace else str(existing.get("file_norm", ""))
    if not ex_norm:
        ex_norm = str(existing.get("file_norm", ""))
    if ex_norm != norm_file:
        return False

    ex_title = str(existing.get("title", ""))
    ex_desc = str(existing.get("description", ""))
    ex_cat = str(existing.get("category", "")).strip().lower()
    cat_norm = category.strip().lower()

    if ex_title.strip().lower() == title.strip().lower():
        return True

    title_sim = _text_similarity(ex_title, title)
    full_sim = _text_similarity(f"{ex_title} {ex_desc}", f"{title} {description}")
    if title_sim >= 0.65 or full_sim >= 0.65:
        return True

    ex_start = int(existing.get("line_start", 0))
    ex_end = int(existing.get("line_end", ex_start))
    dist = _line_distance(line_start, line_end, ex_start, ex_end)

    if dist == 0:
        # Overlapping lines on the same file: require actual semantic token overlap even if category
        # or line span matches, so wide-span bugs do not shadow-block unrelated defects.
        if full_sim >= 0.28 or title_sim >= 0.35:
            return True
        same_cat = bool(cat_norm and ex_cat and cat_norm == ex_cat)
        if same_cat and (full_sim >= 0.18 or (title_sim >= 0.30 and full_sim >= 0.14)):
            return True
        if line_start == ex_start and line_end == ex_end and (full_sim >= 0.16 or (title_sim >= 0.25 and full_sim >= 0.12)):
            return True

    if dist <= 5 and (full_sim >= 0.42 or title_sim >= 0.45 or (cat_norm and cat_norm == ex_cat and full_sim >= 0.25)):
        return True

    return False


def _build_scoreboard(ws: dict[str, Any]) -> dict[str, Any]:
    bugs = ws.get("bugs", [])
    a_found = sum(1 for b in bugs if b.get("finder") == "A")
    b_found = sum(1 for b in bugs if b.get("finder") == "B")
    shazi_bugs = [b["id"] for b in bugs if b.get("shazi_tag")]
    return {
        "round_number": ws.get("round_number", 0),
        "phase": ws.get("phase", "IDLE"),
        "current_bug_counts": {"A": a_found, "B": b_found, "total": len(bugs)},
        "round1_wins": {
            "A": ws["agents"]["A"]["round1_wins"],
            "B": ws["agents"]["B"]["round1_wins"],
        },
        "round2_wins": {
            "A": ws["agents"]["A"]["round2_wins"],
            "B": ws["agents"]["B"]["round2_wins"],
        },
        "duplicate_attempts": {
            "A": ws["agents"]["A"]["duplicate_attempts"],
            "B": ws["agents"]["B"]["duplicate_attempts"],
        },
        "shazi_counts": {
            "A": ws["agents"]["A"]["shazi_count"],
            "B": ws["agents"]["B"]["shazi_count"],
        },
        "shazi_bug_ids": shazi_bugs,
    }


_KNOWN_EXTENSIONLESS_FILENAMES = frozenset(
    {
        "makefile",
        "dockerfile",
        "containerfile",
        "jenkinsfile",
        "vagrantfile",
        "procfile",
        "rakefile",
        "gemfile",
        "brewfile",
        "pipfile",
        "podfile",
        "readme",
        "license",
        "licence",
        "copying",
        "notice",
        "changelog",
        "authors",
        "contributors",
        "codeowners",
        "owners",
        "cname",
        "build",
        "workspace",
    }
)
_KNOWN_FILE_EXTENSIONS = frozenset(
    {
        "py",
        "pyi",
        "pyx",
        "pxd",
        "js",
        "mjs",
        "cjs",
        "jsx",
        "ts",
        "mts",
        "cts",
        "tsx",
        "json",
        "jsonc",
        "json5",
        "md",
        "mdx",
        "rst",
        "txt",
        "yml",
        "yaml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "env",
        "properties",
        "sh",
        "bash",
        "zsh",
        "fish",
        "ksh",
        "cmd",
        "bat",
        "ps1",
        "psm1",
        "psd1",
        "c",
        "h",
        "cc",
        "hh",
        "cpp",
        "hpp",
        "cxx",
        "hxx",
        "cs",
        "fs",
        "go",
        "mod",
        "sum",
        "rs",
        "java",
        "kt",
        "kts",
        "scala",
        "groovy",
        "gradle",
        "swift",
        "m",
        "mm",
        "rb",
        "rake",
        "gemspec",
        "php",
        "pl",
        "pm",
        "lua",
        "r",
        "dart",
        "ex",
        "exs",
        "erl",
        "hrl",
        "clj",
        "cljs",
        "hs",
        "ml",
        "mli",
        "sql",
        "graphql",
        "gql",
        "proto",
        "thrift",
        "html",
        "htm",
        "css",
        "scss",
        "sass",
        "less",
        "svg",
        "xml",
        "xsl",
        "xsd",
        "vue",
        "svelte",
        "astro",
        "tf",
        "tfvars",
        "hcl",
        "nix",
        "cmake",
        "mk",
        "lock",
        "log",
        "csv",
        "tsv",
        "diff",
        "patch",
        "example",
        "sample",
        "template",
    }
)


def _clean_file_token(token: str) -> str:
    if not isinstance(token, str):
        return ""
    s = token.strip()
    while s:
        prev = s
        s = _strip_quotes(s)
        if s.startswith("@"):
            s = s[1:].strip()
        if s == prev:
            break
    return s


def _candidate_path_exists(raw_tok: str, roots: list[Path]) -> bool:
    cleaned = _clean_file_token(raw_tok)
    if not cleaned or "\x00" in cleaned:
        return False
    p = Path(cleaned)
    try:
        if p.is_absolute():
            return p.exists()
        for r in roots:
            if (r / cleaned).exists():
                return True
        return p.exists()
    except (OSError, ValueError):
        return False


def _split_files_string(
    raw: str,
    workspace: str | None = None,
    extra_roots: list[str] | None = None,
) -> list[str]:
    text = raw.strip()
    if not text:
        return []

    has_delim = False
    has_quotes = False
    in_quote: str | None = None
    for ch_c in text:
        if in_quote:
            if ch_c == in_quote:
                in_quote = None
            continue
        if ch_c in ('"', "'"):
            has_quotes = True
            in_quote = ch_c
        elif ch_c in (",", ";", "\n", "\r"):
            has_delim = True

    if has_delim:
        parts: list[str] = []
        buf: list[str] = []
        in_quote = None
        for ch_c in text:
            if in_quote:
                buf.append(ch_c)
                if ch_c == in_quote:
                    in_quote = None
            elif ch_c in ('"', "'"):
                in_quote = ch_c
                buf.append(ch_c)
            elif ch_c in (",", ";", "\n", "\r"):
                seg = "".join(buf).strip()
                if seg:
                    parts.append(seg)
                buf = []
            else:
                buf.append(ch_c)
        seg = "".join(buf).strip()
        if seg:
            parts.append(seg)
        return parts

    if has_quotes:
        parts = []
        buf = []
        in_quote = None
        for ch_c in text:
            if in_quote:
                buf.append(ch_c)
                if ch_c == in_quote:
                    in_quote = None
            elif ch_c in ('"', "'"):
                in_quote = ch_c
                buf.append(ch_c)
            elif ch_c.isspace():
                seg = "".join(buf).strip()
                if seg:
                    parts.append(seg)
                buf = []
            else:
                buf.append(ch_c)
        seg = "".join(buf).strip()
        if seg:
            parts.append(seg)
        return parts

    ws_parts = text.split()
    if len(ws_parts) <= 1:
        return ws_parts

    candidate_roots: list[Path] = []
    for rt in [*(extra_roots or []), workspace]:
        if isinstance(rt, str) and rt.strip():
            rt_key = _normalize_workspace_key(rt)
            if rt_key not in ("default", "__default__") and "\x00" not in rt_key:
                rp = Path(rt_key)
                if rp.is_absolute() and rp not in candidate_roots:
                    candidate_roots.append(rp)

    if _candidate_path_exists(text, candidate_roots):
        return [text]

    if all(_candidate_path_exists(part, candidate_roots) for part in ws_parts):
        return ws_parts

    def _looks_like_standalone_path(tok: str) -> bool:
        if tok.startswith("@"):
            return len(tok) > 1
        norm_tok = tok.replace("\\", "/")
        if "/" in norm_tok:
            return True if norm_tok.split("/", 1)[0] in (".", "..") or norm_tok.startswith("/") else _looks_like_standalone_path(norm_tok.rsplit("/", 1)[-1])
        base = norm_tok
        if base in ("", ".", "..") or base.endswith("."):
            return False
        if base.startswith("."):
            return len(base) >= 2 and base[1] != "."
        if base.lower() in _KNOWN_EXTENSIONLESS_FILENAMES:
            return True
        if "." in base:
            ext = base.rsplit(".", 1)[-1].lower()
            return ext in _KNOWN_FILE_EXTENSIONS
        return False

    if all(_looks_like_standalone_path(p) for p in ws_parts):
        return ws_parts
    return [text]


def _parse_files_arg(
    files_arg: str | list[str] | None,
    workspace: str | None = None,
    extra_roots: list[str] | None = None,
) -> list[str]:
    if not files_arg:
        return []
    if isinstance(files_arg, list):
        raw_items = [x for x in files_arg if isinstance(x, str)]
    elif isinstance(files_arg, str):
        raw_items = _split_files_string(files_arg, workspace=workspace, extra_roots=extra_roots)
    else:
        return []

    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        cleaned = _clean_file_token(item)
        if not cleaned:
            continue
        norm = _normalize_path(cleaned, workspace=workspace, extra_roots=extra_roots)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm if extra_roots else cleaned.replace("\\", "/"))
    return result


# ---------------------------------------------------------------------------
# Public API functions (used by both CLI and MCP server)
# ---------------------------------------------------------------------------


def _load_root_state_readonly() -> tuple[dict[str, Any] | None, str | None]:
    if not STATE_FILE.exists():
        return {"version": 1, "workspaces": {}}, None
    for attempt in range(3):
        try:
            raw = STATE_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("workspaces"), dict):
                return data, None
            return None, "通道状态文件顶层结构无效。"
        except PermissionError:
            if attempt < 2:
                time.sleep(0.01)
            else:
                return None, "读取通道状态文件权限被拒绝。"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"读取通道状态失败: {exc}"
    return None, "读取通道状态失败。"


def _peek_ws_state(root: dict[str, Any], workspace: str | None) -> tuple[str, dict[str, Any]]:
    norm_key = _normalize_workspace_key(workspace)
    workspaces = root.get("workspaces", {})
    key = _find_workspace_key(workspaces, norm_key) if isinstance(workspaces, dict) else norm_key
    stored = workspaces.get(key) if isinstance(workspaces, dict) else None
    if not isinstance(stored, dict):
        return key, _default_workspace_state()
    ws = dict(stored)
    agents_src = ws.get("agents") if isinstance(ws.get("agents"), dict) else {}
    ws["agents"] = {
        aid: dict(agents_src[aid]) if isinstance(agents_src.get(aid), dict) else _default_agent_state(aid)
        for aid in VALID_AGENTS
    }
    _repair_ws_structure(ws)
    return key, ws


def _validate_report_file_path(raw_file: str, ws_key: str) -> str | None:
    if not isinstance(raw_file, str):
        return "文件路径必须是字符串。"
    if "\x00" in raw_file:
        return "文件路径不能包含空字节。"
    cleaned = _clean_file_token(raw_file).replace("\\", "/")
    if not cleaned:
        return "文件路径不能为空。"

    has_drive = bool(re.match(r"^[A-Za-z]:", cleaned))
    is_abs = cleaned.startswith("/") or has_drive
    is_default_ws = ws_key in ("default", "__default__")

    if is_abs:
        if has_drive and (len(cleaned) < 3 or cleaned[2] != "/"):
            return f"不支持的盘符相对路径: {raw_file}"
        if cleaned.startswith("//"):
            return f"不支持的网络 UNC 路径: {raw_file}"
        if is_default_ws or not Path(ws_key).is_absolute():
            return f"当前未绑定本地工作区目录，禁止上报工作区外绝对路径: {raw_file}"
        try:
            ws_root = Path(ws_key).resolve()
            cand_resolved = Path(cleaned).resolve()
        except OSError as exc:
            return f"无效文件路径 '{raw_file}': {exc}"
        if cand_resolved == ws_root or not cand_resolved.is_relative_to(ws_root):
            return f"路径越界！文件 {raw_file} 不在工作区 {ws_key} 目录内。"
        return None

    norm_rel = posixpath.normpath(cleaned)
    if norm_rel in ("", ".", "..") or norm_rel.startswith("../"):
        return f"禁止路径穿越或无效相对路径: {raw_file}"

    if not is_default_ws and Path(ws_key).is_absolute():
        try:
            ws_root = Path(ws_key).resolve()
            cand_resolved = (ws_root / norm_rel).resolve()
        except OSError as exc:
            return f"无效文件路径 '{raw_file}': {exc}"
        if cand_resolved == ws_root or not cand_resolved.is_relative_to(ws_root):
            return f"路径越界！文件 {raw_file} 解析后超出工作区 {ws_key} 目录。"

    return None


def _worktrees_root() -> Path:
    return DATA_DIR / "worktrees"


def _same_resolved_path(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _run_git(cwd: Path | str, args: list[str], timeout: int = 30) -> tuple[bool, str, str]:
    """Run a git CLI command non-interactively and return (ok, stdout, stderr)."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", str(exc)
    return proc.returncode == 0, (proc.stdout or "").rstrip(), (proc.stderr or "").strip()


def _ensure_git_info_exclude(ws_path: Path) -> None:
    """Exclude Python bytecode and in-repo channel runtime files via .git/info/exclude."""
    ok_gd, git_dir_out, _ = _run_git(ws_path, ["rev-parse", "--git-dir"])
    if not ok_gd or not git_dir_out:
        return
    git_dir = Path(git_dir_out)
    if not git_dir.is_absolute():
        git_dir = ws_path / git_dir
    exclude_file = git_dir / "info" / "exclude"
    try:
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
    except OSError:
        return

    patterns = ["__pycache__/", "*.py[cod]"]
    try:
        ws_resolved = ws_path.resolve()
        data_parent = STATE_FILE.parent.resolve()
        if data_parent == ws_resolved or data_parent.is_relative_to(ws_resolved):
            rel_dir = "" if data_parent == ws_resolved else f"{data_parent.relative_to(ws_resolved).as_posix().rstrip('/')}/"
            patterns.append(f"/{rel_dir}arena_state.*.tmp")
        for target_path, suffix in (
            (STATE_FILE, ""),
            (LOCK_DIR, "/"),
            (_worktrees_root(), "/"),
        ):
            p_res = target_path.resolve()
            if p_res != ws_resolved and p_res.is_relative_to(ws_resolved):
                rel = p_res.relative_to(ws_resolved).as_posix().rstrip("/")
                patterns.append(f"/{rel}{suffix}")
                if target_path == LOCK_DIR:
                    patterns.append(f"/{rel}.*/")
    except OSError:
        pass

    existing_lines = {ln.strip() for ln in existing.splitlines()}
    to_add = [pat for pat in patterns if pat not in existing_lines]
    if not to_add:
        return
    sep = "" if (not existing or existing.endswith(("\n", "\r"))) else "\n"
    header = "# hakimi-hiss runtime excludes\n" if "# hakimi-hiss runtime excludes" not in existing_lines else ""
    try:
        with open(exclude_file, "a", encoding="utf-8") as fh:
            fh.write(sep + header + "\n".join(to_add) + "\n")
    except OSError:
        pass


def _init_git_repo_baseline(ws_path: Path) -> dict[str, Any]:
    """Initialize a fresh Git repository and create an initial baseline commit."""
    if not shutil.which("git"):
        return {"ok": False, "error": "系统未安装 git 命令"}

    ok_init, _, err_init = _run_git(ws_path, ["init"])
    if not ok_init:
        return {"ok": False, "error": f"git init 失败：{err_init or 'unknown git error'}"}

    _ensure_git_info_exclude(ws_path)

    ok_add, _, err_add = _run_git(ws_path, ["add", "-A"])
    if not ok_add:
        return {"ok": False, "error": f"git add -A 失败：{err_add or 'unknown git error'}"}

    ok_cm, _, err_cm = _run_git(
        ws_path,
        [
            "-c",
            "user.name=Hakimi Agent",
            "-c",
            "user.email=hakimi@duel.local",
            "commit",
            "--allow-empty",
            "-m",
            "hakimi-hiss: initial baseline commit",
            "--no-verify",
        ],
    )
    if not ok_cm:
        return {"ok": False, "error": f"创建基线提交失败：{err_cm or 'unknown git error'}"}

    return {"ok": True, "error": None}


def _probe_git_worktree_ready(workspace_key: str, auto_init: bool = True) -> dict[str, Any]:
    """Check whether workspace_key is a clean Git repository root ready for isolated worktrees.

    When auto_init is True and the workspace directory is not yet inside a Git repository,
    automatically initialize Git and create an initial baseline commit if git CLI is installed.
    """
    if not workspace_key or workspace_key in ("default", "__default__"):
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": False,
            "fallback_reason": "未绑定具体项目目录（workspace 为 default），自动降级为波次乒乓模式。",
        }
    ws_path = Path(workspace_key)
    if not ws_path.is_dir():
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": False,
            "fallback_reason": f"工作区路径 '{workspace_key}' 不存在或不是目录，自动降级为波次乒乓模式。",
        }

    auto_initialized_git = False
    ok_top, top_out, top_err = _run_git(ws_path, ["rev-parse", "--show-toplevel"])
    if not ok_top or not top_out:
        if auto_init and not (ws_path / ".git").exists():
            init_res = _init_git_repo_baseline(ws_path)
            if init_res["ok"]:
                auto_initialized_git = True
                ok_top, top_out, top_err = _run_git(ws_path, ["rev-parse", "--show-toplevel"])
            else:
                return {
                    "ready": False,
                    "repo_root": None,
                    "base_head": None,
                    "auto_initialized_git": False,
                    "fallback_reason": (
                        f"当前工作区尚无 Git 仓库且自动初始化失败（{init_res['error']}），自动降级为波次乒乓模式。"
                    ),
                }
        if not ok_top or not top_out:
            detail = f" ({top_err})" if top_err else ""
            return {
                "ready": False,
                "repo_root": None,
                "base_head": None,
                "auto_initialized_git": auto_initialized_git,
                "fallback_reason": f"当前工作区不是 Git 仓库（或系统未安装 git）{detail}，自动降级为波次乒乓模式。",
            }

    if not _same_resolved_path(Path(top_out), ws_path):
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": f"当前目录为 Git 子目录（仓库根为 {top_out}），为避免相对路径错位，自动降级为波次乒乓模式。",
        }

    ok_head, head_out, head_err = _run_git(ws_path, ["rev-parse", "--verify", "HEAD"])
    if not ok_head or not head_out:
        detail = f" ({head_err})" if head_err else ""
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": f"Git 仓库尚无有效提交（unborn HEAD）{detail}，无法派生并行 worktree，自动降级为波次乒乓模式。",
        }

    ok_st, dirty_out, st_err = _run_git(ws_path, ["status", "--porcelain"])
    if not ok_st:
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": f"检查 Git 工作区状态失败 ({st_err})，自动降级为波次乒乓模式。",
        }
    if dirty_out.strip():
        dirty_count = len(dirty_out.splitlines())
        return {
            "ready": False,
            "repo_root": None,
            "base_head": None,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": f"Git 工作区存在 {dirty_count} 项未提交改动（dirty working tree），为保护本地现场，自动降级为波次乒乓模式。",
        }

    return {
        "ready": True,
        "repo_root": str(ws_path.resolve()),
        "base_head": head_out,
        "auto_initialized_git": auto_initialized_git,
        "fallback_reason": None,
    }


def _cleanup_round2_worktrees(ws: dict[str, Any], force: bool = True) -> dict[str, Any]:
    """Remove any Round 2 Git worktrees and temporary branches tracked in workspace state."""
    wt = ws.get("worktrees")
    if not isinstance(wt, dict):
        ws["worktrees"] = None
        return {"cleaned": False, "removed_paths": [], "deleted_branches": [], "errors": []}

    repo_str = wt.get("repo_root")
    repo_root = Path(repo_str) if isinstance(repo_str, str) and repo_str.strip() else None
    repo_exists = bool(repo_root and repo_root.is_dir())
    removed_paths: list[str] = []
    deleted_branches: list[str] = []
    errors: list[str] = []
    parent_dirs: set[Path] = set()

    for aid in VALID_AGENTS:
        entry = wt.get(aid)
        if not isinstance(entry, dict):
            continue
        p_str = entry.get("path")
        branch = entry.get("branch")
        wt_still_exists = False
        branch_still_exists = False
        if isinstance(p_str, str) and p_str.strip():
            wt_path = Path(p_str)
            parent_dirs.add(wt_path.parent)
            rm_err_msg = ""
            if repo_exists and repo_root is not None:
                rm_args = ["worktree", "remove"]
                if force:
                    rm_args.append("--force")
                rm_args.append(str(wt_path))
                ok_rm, _, err_rm = _run_git(repo_root, rm_args)
                if ok_rm:
                    removed_paths.append(str(wt_path))
                else:
                    rm_err_msg = err_rm
            if wt_path.exists() and force:
                try:
                    shutil.rmtree(wt_path, ignore_errors=False)
                    if str(wt_path) not in removed_paths:
                        removed_paths.append(str(wt_path))
                except OSError as exc:
                    if rm_err_msg:
                        errors.append(f"worktree remove {aid}: {rm_err_msg}; rmtree {aid}: {exc}")
                    else:
                        errors.append(f"rmtree {aid}: {exc}")
            elif wt_path.exists():
                errors.append(f"worktree remove {aid}: {rm_err_msg or f'目录仍存在 {wt_path}'}")
            wt_still_exists = wt_path.exists()

        if isinstance(branch, str) and branch.strip() and repo_exists and repo_root is not None:
            del_flag = "-D" if force else "-d"
            ok_br, _, err_br = _run_git(repo_root, ["branch", del_flag, branch])
            if ok_br:
                deleted_branches.append(branch)
            else:
                ok_chk, _, _ = _run_git(repo_root, ["show-ref", "--verify", f"refs/heads/{branch}"])
                if ok_chk:
                    branch_still_exists = True
                    errors.append(f"branch {del_flag} {branch}: {err_br}")

        if not wt_still_exists and not branch_still_exists:
            wt.pop(aid, None)

    if repo_exists and repo_root is not None:
        _run_git(repo_root, ["worktree", "prune"])

    for pdir in parent_dirs:
        try:
            if pdir.is_dir() and not any(pdir.iterdir()):
                pdir.rmdir()
        except OSError:
            pass

    if not errors:
        ws["worktrees"] = None
    else:
        wt["cleanup_errors"] = list(errors)

    return {
        "cleaned": len(errors) == 0,
        "removed_paths": removed_paths,
        "deleted_branches": deleted_branches,
        "errors": errors,
    }


def _create_round2_worktrees(ws_key: str, probe: dict[str, Any], round_number: int) -> dict[str, Any]:
    """Create isolated Git worktrees for A and B anchored at the repository's current HEAD."""
    repo_root = Path(probe["repo_root"])
    base_head = probe["base_head"]
    ws_hash = hashlib.sha1(ws_key.encode("utf-8", errors="replace")).hexdigest()[:10]
    wt_base = _worktrees_root() / ws_hash
    wt_base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(2)

    # Prune stale .git/worktrees metadata unconditionally before creating fresh worktrees
    _run_git(repo_root, ["worktree", "prune"])

    created_entries: dict[str, dict[str, Any]] = {}
    for aid in VALID_AGENTS:
        wt_path = wt_base / f"{aid.lower()}-{stamp}"
        branch = f"hakimi-hiss/{ws_hash}/r{round_number}-{stamp}-{aid.lower()}"
        if wt_path.exists():
            _run_git(repo_root, ["worktree", "remove", "--force", str(wt_path)])
            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
            _run_git(repo_root, ["worktree", "prune"])

        ok_add, _, err_add = _run_git(repo_root, ["worktree", "add", "-b", branch, str(wt_path), base_head])
        if not ok_add:
            # Roll back partial creation cleanly
            partial_ws = {
                "worktrees": {
                    "enabled": True,
                    "repo_root": str(repo_root),
                    **created_entries,
                }
            }
            _cleanup_round2_worktrees(partial_ws, force=True)
            return {
                "ok": False,
                "error": f"创建哈基米{aid}独立 Git worktree 失败：{err_add or 'unknown git error'}",
            }
        created_entries[aid] = {
            "path": str(wt_path),
            "branch": branch,
            "merged": False,
            "last_commit": base_head,
        }

    return {
        "ok": True,
        "worktrees": {
            "enabled": True,
            "mode": "GIT_WORKTREE_PARALLEL",
            "repo_root": str(repo_root),
            "base_head": base_head,
            "created_at": _now_iso(),
            **created_entries,
        },
    }


def _auto_commit_worktree(wt_path: Path, commit_msg: str) -> dict[str, Any]:
    """Commit any pending dirty edits in a cat's worktree branch before inspection/merge."""
    if not wt_path.is_dir():
        return {"ok": False, "error": f"worktree 目录不存在：{wt_path}"}

    ok_st, dirty_out, err_st = _run_git(wt_path, ["status", "--porcelain"])
    if not ok_st:
        return {"ok": False, "error": f"读取 worktree 状态失败：{err_st}"}

    committed_now = False
    if dirty_out.strip():
        ok_add, _, err_add = _run_git(wt_path, ["add", "-A"])
        if not ok_add:
            return {"ok": False, "error": f"git add -A 失败：{err_add}"}
        ok_cm, _, err_cm = _run_git(
            wt_path,
            [
                "-c",
                "user.name=Hakimi Agent",
                "-c",
                "user.email=hakimi@duel.local",
                "commit",
                "-m",
                commit_msg,
                "--no-verify",
            ],
        )
        if not ok_cm:
            return {"ok": False, "error": f"自动提交 worktree 改动失败：{err_cm}"}
        committed_now = True

    ok_hd, head_sha, err_hd = _run_git(wt_path, ["rev-parse", "HEAD"])
    if not ok_hd or not head_sha:
        return {"ok": False, "error": f"获取 worktree HEAD 失败：{err_hd}"}

    return {"ok": True, "head": head_sha, "committed_now": committed_now}


def _worktree_has_unmerged_changes(repo_root: Path, wt_path: Path) -> bool:
    """Return True if a worktree has dirty edits or commits not reachable from main repo HEAD."""
    if not wt_path.is_dir():
        return False
    ok_st, dirty_out, _ = _run_git(wt_path, ["status", "--porcelain"])
    if ok_st and dirty_out.strip():
        return True
    ok_hd, wt_head, _ = _run_git(wt_path, ["rev-parse", "HEAD"])
    if not ok_hd or not wt_head.strip():
        return False
    ok_cnt, cnt_out, _ = _run_git(repo_root, ["rev-list", "--count", f"HEAD..{wt_head.strip()}"])
    if ok_cnt:
        try:
            return int(cnt_out.strip() or "0") > 0
        except ValueError:
            return False
    return False


def _build_wave_schedule(
    tasks_a: list[dict[str, Any]],
    tasks_b: list[dict[str, Any]],
    ws_key: str,
    round_number: int,
    extra_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Partition cross-fix bugs into parallel disjoint wave + file-disjoint alternating turns."""

    def _bug_file(bug: dict[str, Any]) -> str:
        raw = bug.get("file") or bug.get("file_norm") or ""
        return _normalize_path(raw, workspace=ws_key, extra_roots=extra_roots)

    files_a = {_bug_file(b) for b in tasks_a if _bug_file(b)}
    files_b = {_bug_file(b) for b in tasks_b if _bug_file(b)}
    overlap_files = sorted(files_a & files_b)
    overlap_set = set(overlap_files)

    disjoint_a = [b for b in tasks_a if _bug_file(b) not in overlap_set]
    disjoint_b = [b for b in tasks_b if _bug_file(b) not in overlap_set]

    waves: list[dict[str, Any]] = []
    if disjoint_a or disjoint_b:
        waves.append(
            {
                "wave": len(waves),
                "type": "PARALLEL_DISJOINT",
                "parallel_safe": True,
                "A": [b["id"] for b in disjoint_a],
                "B": [b["id"] for b in disjoint_b],
                "A_files": sorted({_bug_file(b) for b in disjoint_a if _bug_file(b)}),
                "B_files": sorted({_bug_file(b) for b in disjoint_b if _bug_file(b)}),
                "note": "无文件重叠区，A 与 B 可同时并行修改。",
            }
        )

    if overlap_files:
        # Alternate which cat gets index-0 overlapping files first across rounds.
        a_gets_even_ping = (round_number % 2) == 1
        ping_a_files = {f for idx, f in enumerate(overlap_files) if (idx % 2 == 0) == a_gets_even_ping}
        ping_b_files = overlap_set - ping_a_files

        ping_a = [b for b in tasks_a if _bug_file(b) in ping_a_files]
        ping_b = [b for b in tasks_b if _bug_file(b) in ping_b_files]
        pong_a = [b for b in tasks_a if _bug_file(b) in ping_b_files]
        pong_b = [b for b in tasks_b if _bug_file(b) in ping_a_files]

        if ping_a or ping_b:
            waves.append(
                {
                    "wave": len(waves),
                    "type": "PING_PONG_TURN",
                    "turn": "PING",
                    "parallel_safe": True,
                    "A": [b["id"] for b in ping_a],
                    "B": [b["id"] for b in ping_b],
                    "A_files": sorted({_bug_file(b) for b in ping_a if _bug_file(b)}),
                    "B_files": sorted({_bug_file(b) for b in ping_b if _bug_file(b)}),
                    "note": "重叠文件首轮交错编辑（双方各持不同重叠文件，互不踩踏）。",
                }
            )
        if pong_a or pong_b:
            waves.append(
                {
                    "wave": len(waves),
                    "type": "PING_PONG_TURN",
                    "turn": "PONG",
                    "parallel_safe": True,
                    "A": [b["id"] for b in pong_a],
                    "B": [b["id"] for b in pong_b],
                    "A_files": sorted({_bug_file(b) for b in pong_a if _bug_file(b)}),
                    "B_files": sorted({_bug_file(b) for b in pong_b if _bug_file(b)}),
                    "note": "重叠文件次轮交换编辑：请先重读对方上一波修改后的最新文件再落盘。",
                }
            )

    return {
        "overlapping_files": overlap_files,
        "waves": waves,
    }


def _release_agent_leases_for_file(
    ws: dict[str, Any],
    holder: str,
    file_norm: str | None = None,
) -> list[str]:
    """Release active file leases held by holder (for a specific file or all files)."""
    leases = ws.setdefault("file_leases", {})
    if not isinstance(leases, dict):
        ws["file_leases"] = {}
        return []
    released: list[str] = []
    for fpath in list(leases.keys()):
        entry = leases.get(fpath)
        if not isinstance(entry, dict) or entry.get("holder") == holder:
            if file_norm is None or fpath == file_norm:
                del leases[fpath]
                released.append(fpath)
    return released


def cmd_status(workspace: str | None = None) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    root, err = _load_root_state_readonly()
    if err is not None or root is None:
        return {"ok": False, "error": err or "读取通道状态失败。"}
    key, ws = _peek_ws_state(root, workspace)
    return {
        "ok": True,
        "workspace": key,
        "phase": ws["phase"],
        "round_number": ws["round_number"],
        "scope_mode": ws["scope_mode"],
        "target_files": ws["target_files"],
        "agents": ws["agents"],
        "bugs": ws["bugs"],
        "cross_fix_plan": ws.get("cross_fix_plan"),
        "file_leases": ws.get("file_leases", {}),
        "worktrees": ws.get("worktrees"),
        "round1_result": ws["round1_result"],
        "round2_result": ws["round2_result"],
        "scoreboard": _build_scoreboard(ws),
        "updated_at": ws["updated_at"],
    }


def cmd_bind_agents(
    workspace: str | None = None,
    agent_a: str | None = None,
    agent_b: str | None = None,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}

    a_clean: str | None = None
    if agent_a is not None:
        if not isinstance(agent_a, str):
            return {"ok": False, "error": "agent_a 必须是字符串。"}
        a_clean = agent_a.strip()
        if not a_clean:
            return {"ok": False, "error": "agent_a 不能为空白字符串。"}

    b_clean: str | None = None
    if agent_b is not None:
        if not isinstance(agent_b, str):
            return {"ok": False, "error": "agent_b 必须是字符串。"}
        b_clean = agent_b.strip()
        if not b_clean:
            return {"ok": False, "error": "agent_b 不能为空白字符串。"}

    if a_clean is None and b_clean is None:
        return {"ok": False, "error": "至少需要提供 agent_a 或 agent_b 中的一个有效 conversationId。"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)
        final_a = a_clean if a_clean is not None else ws["agents"]["A"].get("conv_id")
        final_b = b_clean if b_clean is not None else ws["agents"]["B"].get("conv_id")
        if final_a and final_b and final_a == final_b:
            return {
                "ok": False,
                "error": f"哈基米A与哈基米B不能绑定相同的 conversationId ({final_a})。",
            }
        if a_clean is not None:
            ws["agents"]["A"]["conv_id"] = a_clean
        if b_clean is not None:
            ws["agents"]["B"]["conv_id"] = b_clean
        ws["updated_at"] = _now_iso()
        _save_root_state(root)
        return {
            "ok": True,
            "workspace": key,
            "agents": {
                "A": {"name": ws["agents"]["A"]["name"], "conv_id": ws["agents"]["A"]["conv_id"]},
                "B": {"name": ws["agents"]["B"]["name"], "conv_id": ws["agents"]["B"]["conv_id"]},
            },
            "message": "哈基米子代理长期上下文绑定已更新。",
        }


def cmd_start_hunt(
    workspace: str | None = None,
    scope: str = "project",
    files: str | list[str] | None = None,
    keep_bugs: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if scope is not None and not isinstance(scope, str):
        return {"ok": False, "error": "scope 必须是字符串 (project 或 files)。"}
    parsed_files = _parse_files_arg(files, workspace=workspace)
    scope_mode = scope.strip().lower() if scope else "project"
    if parsed_files and scope_mode == "project":
        scope_mode = "files"
    if scope_mode not in ("project", "files"):
        return {"ok": False, "error": f"无效 scope: {scope}，仅支持 project 或 files。"}
    if scope_mode == "files" and not parsed_files:
        return {"ok": False, "error": "scope 为 files 时必须提供至少一个目标文件。"}
    if scope_mode == "files":
        ws_preview = _normalize_workspace_key(workspace)
        for tf in parsed_files:
            tf_err = _validate_report_file_path(tf, ws_preview)
            if tf_err:
                return {"ok": False, "error": f"target_files 包含非法路径 '{tf}': {tf_err}"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] in ("ROUND1_HUNTING", "ROUND2_CROSS_FIXING") and not force:
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前赛程正处于 {ws['phase']} 进行中，请先结算/验收本局，或传入 force=True / --force 强制重开。",
            }

        has_prior_data = (
            ws["bugs"]
            or ws["round1_result"] is not None
            or ws["round2_result"] is not None
            or any(ws["agents"][aid]["duplicate_attempts"] for aid in VALID_AGENTS)
        )
        if ws.get("round_number", 0) > 0 and has_prior_data:
            ws["history"].append(
                {
                    "round_number": ws["round_number"],
                    "scope_mode": ws["scope_mode"],
                    "target_files": list(ws["target_files"]),
                    "bugs_count": len(ws["bugs"]),
                    "bugs": copy.deepcopy(ws["bugs"]),
                    "duplicate_attempts": {
                        "A": ws["agents"]["A"]["duplicate_attempts"],
                        "B": ws["agents"]["B"]["duplicate_attempts"],
                    },
                    "round1_result": copy.deepcopy(ws["round1_result"]),
                    "round2_result": copy.deepcopy(ws["round2_result"]),
                    "archived_at": _now_iso(),
                }
            )
        _cleanup_round2_worktrees(ws, force=True)
        ws["file_leases"] = {}
        ws["cross_fix_plan"] = None
        ws["current_cross_fix_bug_ids"] = []

        if not keep_bugs:
            ws["bugs"] = []
            ws["next_bug_seq"] = 1
        else:
            for bug in ws["bugs"]:
                if bug.get("status") in ("IN_CROSS_FIX", "PENDING_JUDGE"):
                    bug["status"] = "OPEN"
                    bug["cross_verify"] = None

        for aid in VALID_AGENTS:
            ws["agents"][aid]["duplicate_attempts"] = 0

        ws["round_number"] = int(ws.get("round_number", 0)) + 1
        ws["phase"] = "ROUND1_HUNTING"
        ws["scope_mode"] = scope_mode
        ws["target_files"] = parsed_files if scope_mode == "files" else []
        ws["round1_result"] = None
        ws["round2_result"] = None
        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        scope_desc = (
            f"指定 @ 文件 ({', '.join(ws['target_files'])})"
            if scope_mode == "files"
            else "整个项目代码库"
        )
        return {
            "ok": True,
            "workspace": key,
            "phase": ws["phase"],
            "round_number": ws["round_number"],
            "scope_mode": ws["scope_mode"],
            "target_files": ws["target_files"],
            "agent_a_conv_id": ws["agents"]["A"]["conv_id"],
            "agent_b_conv_id": ws["agents"]["B"]["conv_id"],
            "message": f"第 {ws['round_number']} 轮【哈气找Bug赛（一胜）】已开启！审查范围：{scope_desc}。",
        }


def cmd_report_bug(
    reporter: str,
    file: str,
    line_start: int,
    title: str,
    description: str,
    workspace: str | None = None,
    line_end: int | None = None,
    severity: str = "MEDIUM",
    category: str = "logic",
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"accepted": False, "reason": "INVALID_WORKSPACE", "message": "workspace 必须是字符串。"}
    if not isinstance(reporter, str):
        return {"accepted": False, "reason": "INVALID_AGENT", "message": f"reporter 必须是字符串 (A 或 B)，收到: {reporter!r}"}
    rep = reporter.strip().upper()
    if rep not in VALID_AGENTS:
        return {"accepted": False, "reason": "INVALID_AGENT", "message": f"reporter 必须是 A 或 B，收到: {reporter}"}

    if not isinstance(severity, str):
        return {"accepted": False, "reason": "INVALID_SEVERITY", "message": f"severity 必须是字符串 (HIGH/MEDIUM/LOW)，收到: {severity!r}"}
    sev = severity.strip().upper()
    if sev not in VALID_SEVERITIES:
        return {"accepted": False, "reason": "INVALID_SEVERITY", "message": f"无效 severity '{severity}'，仅支持 HIGH / MEDIUM / LOW。"}

    if category is None:
        cat_clean = "logic"
    elif not isinstance(category, str):
        return {"accepted": False, "reason": "INVALID_CATEGORY", "message": f"category 必须是字符串，收到: {category!r}"}
    else:
        cat_clean = category.strip() or "logic"

    if not isinstance(title, str) or not title.strip():
        return {"accepted": False, "reason": "INVALID_TITLE", "message": "Bug 标题不能为空或纯空白。"}
    if not isinstance(description, str) or not description.strip():
        return {"accepted": False, "reason": "INVALID_DESCRIPTION", "message": "Bug 描述不能为空或纯空白。"}

    if isinstance(line_start, bool) or isinstance(line_start, float):
        return {"accepted": False, "reason": "INVALID_LINE_RANGE", "message": f"line_start 必须是正整数，收到: {line_start!r}"}
    try:
        l_start = int(line_start)
    except (TypeError, ValueError):
        return {"accepted": False, "reason": "INVALID_LINE_RANGE", "message": f"line_start 必须是正整数，收到: {line_start!r}"}
    if l_start < 1:
        return {"accepted": False, "reason": "INVALID_LINE_RANGE", "message": f"line_start 必须 >= 1，收到: {l_start}"}

    if line_end is not None:
        if isinstance(line_end, bool) or isinstance(line_end, float):
            return {"accepted": False, "reason": "INVALID_LINE_RANGE", "message": f"line_end 必须是整数，收到: {line_end!r}"}
        try:
            l_end = int(line_end)
        except (TypeError, ValueError):
            return {"accepted": False, "reason": "INVALID_LINE_RANGE", "message": f"line_end 必须是整数，收到: {line_end!r}"}
        if l_end < l_start:
            return {
                "accepted": False,
                "reason": "INVALID_LINE_RANGE",
                "message": f"line_end ({l_end}) 不能小于 line_start ({l_start})。",
            }
    else:
        l_end = l_start

    if not isinstance(file, str) or not file.strip():
        return {"accepted": False, "reason": "INVALID_FILE", "message": "文件路径不能为空。"}

    ws_key_preview = _normalize_workspace_key(workspace)
    path_err = _validate_report_file_path(file, ws_key_preview)
    if path_err:
        return {"accepted": False, "reason": "INVALID_FILE", "message": path_err}

    norm_file = _normalize_path(file, workspace=ws_key_preview)
    if not norm_file:
        return {"accepted": False, "reason": "INVALID_FILE", "message": "文件路径不能为空。"}

    title_clean = title.strip()
    desc_clean = description.strip()

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)
        norm_file = _normalize_path(file, workspace=key) or norm_file

        if ws["phase"] != "ROUND1_HUNTING":
            return {
                "accepted": False,
                "reason": "WRONG_PHASE",
                "phase": ws["phase"],
                "message": f"当前阶段为 {ws['phase']}，不在 ROUND1_HUNTING 找 Bug 阶段，暂不接收新 Bug。",
            }

        if ws["scope_mode"] == "files" and not _path_matches_target(file, ws["target_files"], workspace=key):
            return {
                "accepted": False,
                "reason": "OUT_OF_SCOPE",
                "target_files": ws["target_files"],
                "message": f"哈气越界！本局仅限审查指定的 @ 文件 {ws['target_files']}，不能上报 {file}！",
            }

        for existing in ws["bugs"]:
            if _is_duplicate_bug(
                existing,
                norm_file,
                l_start,
                l_end,
                title_clean,
                desc_clean,
                cat_clean,
                workspace=key,
            ):
                ws["agents"][rep]["duplicate_attempts"] += 1
                ws["updated_at"] = _now_iso()
                _save_root_state(root)
                return {
                    "accepted": False,
                    "reason": "DUPLICATE",
                    "duplicate_of": existing["id"],
                    "claimed_by": existing["finder"],
                    "message": (
                        f"哈——！慢了一爪！这只虫子已被 {ws['agents'][existing['finder']]['name']} "
                        f"抢先叼走登记为 {existing['id']}（{existing['file']}:{existing['line_start']}），不可重复填报！"
                    ),
                }

        seq = int(ws.get("next_bug_seq", 1))
        bug_id = f"BUG-{seq:03d}"
        ws["next_bug_seq"] = seq + 1
        assigned_fixer = "B" if rep == "A" else "A"

        bug_record = {
            "id": bug_id,
            "round_number": ws["round_number"],
            "finder": rep,
            "assigned_fixer": assigned_fixer,
            "file": _clean_file_token(file).replace("\\", "/") or file.strip().replace("\\", "/"),
            "file_norm": norm_file,
            "line_start": l_start,
            "line_end": l_end,
            "severity": sev,
            "category": cat_clean,
            "title": title_clean,
            "description": desc_clean,
            "status": "OPEN",
            "shazi_tag": False,
            "shazi_reasons": [],
            "fix_attempts": [],
            "judge_verdict": None,
            "judge_comment": None,
            "reported_at": _now_iso(),
        }
        ws["bugs"].append(bug_record)
        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        cur_round = int(ws.get("round_number", 1))
        a_count = sum(1 for b in ws["bugs"] if int(b.get("round_number", cur_round)) == cur_round and b["finder"] == "A")
        b_count = sum(1 for b in ws["bugs"] if int(b.get("round_number", cur_round)) == cur_round and b["finder"] == "B")
        return {
            "accepted": True,
            "workspace": key,
            "bug_id": bug_id,
            "bug": bug_record,
            "current_scores": {"A": a_count, "B": b_count},
            "message": f"嘶哈！{ws['agents'][rep]['name']} 成功抢先叼住 {bug_id}！当前战况 A={a_count} : B={b_count}。",
        }


def cmd_list_bugs(
    workspace: str | None = None,
    finder: str | None = None,
    assigned_to: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}

    f_up: str | None = None
    if finder is not None:
        if not isinstance(finder, str):
            return {"ok": False, "error": "finder 必须是字符串 (A 或 B)。"}
        if finder != "":
            f_up = finder.strip().upper()
            if f_up not in VALID_AGENTS:
                return {"ok": False, "error": f"无效 finder '{finder}'，仅支持 A 或 B。"}

    a_up: str | None = None
    if assigned_to is not None:
        if not isinstance(assigned_to, str):
            return {"ok": False, "error": "assigned_to 必须是字符串 (A 或 B)。"}
        if assigned_to != "":
            a_up = assigned_to.strip().upper()
            if a_up not in VALID_AGENTS:
                return {"ok": False, "error": f"无效 assigned_to '{assigned_to}'，仅支持 A 或 B。"}

    s_up: str | None = None
    if status is not None:
        if not isinstance(status, str):
            return {"ok": False, "error": "status 必须是字符串。"}
        if status != "":
            s_up = status.strip().upper()
            if s_up not in VALID_BUG_STATUSES:
                return {
                    "ok": False,
                    "error": f"无效 status '{status}'，可选值: {', '.join(VALID_BUG_STATUSES)}。",
                }

    root, err = _load_root_state_readonly()
    if err is not None or root is None:
        return {"ok": False, "error": err or "读取通道状态失败。"}
    key, ws = _peek_ws_state(root, workspace)
    bugs = ws["bugs"]
    if f_up:
        bugs = [b for b in bugs if b.get("finder") == f_up]
    if a_up:
        bugs = [b for b in bugs if b.get("assigned_fixer") == a_up]
    if s_up:
        bugs = [b for b in bugs if b.get("status") == s_up]
    return {
        "ok": True,
        "workspace": key,
        "phase": ws["phase"],
        "count": len(bugs),
        "bugs": bugs,
    }


def _clear_bug_shazi_penalty(ws: dict[str, Any], bug: dict[str, Any]) -> None:
    bid = str(bug.get("id", ""))
    penalized = bug.get("shazi_penalized_agent")
    old_badge = bug.get("shazi_badge")
    had_tag = bool(bug.get("shazi_tag"))

    if penalized not in VALID_AGENTS and had_tag:
        # Backward compatibility with legacy state lacking shazi_penalized_agent
        candidate_agents: list[str] = []
        if bug.get("assigned_fixer") in VALID_AGENTS and (bug.get("fix_attempts") or bug.get("judge_verdict") == "FAILED"):
            candidate_agents.append(bug["assigned_fixer"])
        elif bug.get("assigned_fixer") in VALID_AGENTS:
            candidate_agents.append(bug["assigned_fixer"])
        if bug.get("finder") in VALID_AGENTS and bug["finder"] not in candidate_agents:
            candidate_agents.append(bug["finder"])
        for cid in candidate_agents:
            badges = ws["agents"][cid].get("shazi_badges", [])
            if any(bid and bid in str(b) for b in badges):
                penalized = cid
                break

    if penalized in VALID_AGENTS:
        agent = ws["agents"][penalized]
        badges = agent.setdefault("shazi_badges", [])
        removed = False
        if old_badge and old_badge in badges:
            idx = len(badges) - 1 - badges[::-1].index(old_badge)
            badges.pop(idx)
            removed = True
        elif bid:
            for idx in range(len(badges) - 1, -1, -1):
                if bid in str(badges[idx]):
                    badges.pop(idx)
                    removed = True
                    break
        if removed or (had_tag and bug.get("shazi_penalized_agent") == penalized):
            agent["shazi_count"] = max(0, int(agent.get("shazi_count", 0)) - 1)

    bug["shazi_tag"] = False
    bug.pop("shazi_penalized_agent", None)
    bug.pop("shazi_badge", None)


def _apply_bug_shazi_penalty(ws: dict[str, Any], bug: dict[str, Any], target_agent: str, badge: str) -> bool:
    bid = str(bug.get("id", ""))
    old_agent = bug.get("shazi_penalized_agent")
    if old_agent in VALID_AGENTS and old_agent != target_agent:
        _clear_bug_shazi_penalty(ws, bug)
        old_agent = None

    agent = ws["agents"][target_agent]
    badges = agent.setdefault("shazi_badges", [])
    if bug.get("shazi_tag") and (old_agent == target_agent or any(bid and bid in str(b) for b in badges)):
        old_badge = bug.get("shazi_badge")
        if old_badge and old_badge in badges:
            idx = len(badges) - 1 - badges[::-1].index(old_badge)
            badges[idx] = badge
        elif bid:
            for idx in range(len(badges) - 1, -1, -1):
                if bid in str(badges[idx]):
                    badges[idx] = badge
                    break
        bug["shazi_tag"] = True
        bug["shazi_penalized_agent"] = target_agent
        bug["shazi_badge"] = badge
        return False

    agent["shazi_count"] = int(agent.get("shazi_count", 0)) + 1
    badges.append(badge)
    bug["shazi_tag"] = True
    bug["shazi_penalized_agent"] = target_agent
    bug["shazi_badge"] = badge
    return True


def cmd_settle_round1(workspace: str | None = None) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] != "ROUND1_HUNTING":
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 ROUND1_HUNTING 阶段可结算第一局（禁止重复结算刷分）。",
            }

        bugs = ws["bugs"]
        cur_round = int(ws.get("round_number", 1))
        round_bugs = [b for b in bugs if int(b.get("round_number", cur_round)) == cur_round]

        def _sev_breakdown(agent_id: str) -> dict[str, int]:
            own = [b for b in round_bugs if b.get("finder") == agent_id]
            return {
                "total": len(own),
                "HIGH": sum(1 for b in own if b.get("severity") == "HIGH"),
                "MEDIUM": sum(1 for b in own if b.get("severity") == "MEDIUM"),
                "LOW": sum(1 for b in own if b.get("severity") == "LOW"),
                "duplicate_attempts": ws["agents"][agent_id]["duplicate_attempts"],
            }

        stats_a = _sev_breakdown("A")
        stats_b = _sev_breakdown("B")

        if stats_a["total"] > stats_b["total"]:
            winner = "A"
            ws["agents"]["A"]["round1_wins"] += 1
            banner = f"🏆 一胜归属：{ws['agents']['A']['name']}（{stats_a['total']} vs {stats_b['total']}）！哈气声震慑全场！"
        elif stats_b["total"] > stats_a["total"]:
            winner = "B"
            ws["agents"]["B"]["round1_wins"] += 1
            banner = f"🏆 一胜归属：{ws['agents']['B']['name']}（{stats_b['total']} vs {stats_a['total']}）！哈气声震慑全场！"
        else:
            winner = "DRAW"
            banner = f"🤝 第一局平手（{stats_a['total']} vs {stats_b['total']}）！两只哈基米互相哈气不相上下！"

        ws["phase"] = "SUSPENDED_ROUND1"
        ws["round1_result"] = {
            "round_number": cur_round,
            "winner": winner,
            "banner": banner,
            "stats": {"A": stats_a, "B": stats_b},
            "settled_at": _now_iso(),
        }
        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        return {
            "ok": True,
            "workspace": key,
            "phase": ws["phase"],
            "round_number": cur_round,
            "round1_winner": winner,
            "banner": banner,
            "stats": {"A": stats_a, "B": stats_b},
            "round_bugs": round_bugs,
            "bugs": bugs,
            "agent_a_conv_id": ws["agents"]["A"]["conv_id"],
            "agent_b_conv_id": ws["agents"]["B"]["conv_id"],
            "next_actions": [
                "插件已挂起并交回全部去重 Bug 给铲屎官。",
                "铲屎官可选择直接自己修复这些 Bug；",
                "或调用 start-cross-fix 发起第二局【交叉修 Bug 赛（二胜）】：A 修 B 找到的 Bug，B 修 A 找到的 Bug。",
            ],
        }


def cmd_start_cross_fix(
    workspace: str | None = None,
    only_shazi: bool = False,
    mode: str | None = "auto",
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if mode is None:
        mode_clean = "auto"
    elif not isinstance(mode, str) or not mode.strip():
        return {"ok": False, "error": f"mode 必须是 auto / worktree / wave，收到: {mode!r}"}
    else:
        mode_clean = mode.strip().lower()
    if mode_clean not in VALID_CROSS_FIX_MODES:
        return {
            "ok": False,
            "error": f"无效 mode '{mode}'，可选值为: {', '.join(VALID_CROSS_FIX_MODES)}。",
        }

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] not in ("SUSPENDED_ROUND1", "SUSPENDED_ROUND2"):
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 SUSPENDED_ROUND1 或 SUSPENDED_ROUND2 挂起状态下可开启交叉修复。",
            }

        planned_a: list[dict[str, Any]] = []
        planned_b: list[dict[str, Any]] = []

        for bug in ws["bugs"]:
            if only_shazi:
                is_target = bool(bug.get("shazi_tag")) or bug.get("status") == "SHAZI_FAILED"
            else:
                is_target = bug.get("status") in {"OPEN", "SHAZI_FAILED", "FIX_FAILED"}
            if not is_target:
                continue
            # Enforce cross-fix assignment: A fixes B's bugs, B fixes A's bugs
            fixer = "B" if bug["finder"] == "A" else "A"
            if fixer == "A":
                planned_a.append(bug)
            else:
                planned_b.append(bug)

        if not planned_a and not planned_b:
            msg = "没有符合条件的待修复 Bug（请确认已找到 Bug，或是否误加了 only_shazi）。"
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": msg,
                "message": msg,
            }

        round_no = int(ws.get("round_number", 1))
        has_dual_fixers = bool(planned_a and planned_b)
        execution_mode = "WAVE_PING_PONG"
        fallback_reason: str | None = None
        auto_initialized_git = False
        new_worktrees: dict[str, Any] | None = None

        if not has_dual_fixers:
            execution_mode = "SINGLE_FIXER_DIRECT"
        elif mode_clean == "wave":
            execution_mode = "WAVE_PING_PONG"
            fallback_reason = "显式指定 mode=wave（波次乒乓模式）。"
        else:
            probe = _probe_git_worktree_ready(key)
            auto_initialized_git = bool(probe.get("auto_initialized_git"))
            if probe["ready"]:
                wt_res = _create_round2_worktrees(key, probe, round_no)
                if wt_res["ok"]:
                    execution_mode = "GIT_WORKTREE_PARALLEL"
                    new_worktrees = wt_res["worktrees"]
                elif mode_clean == "worktree":
                    return {
                        "ok": False,
                        "workspace": key,
                        "phase": ws["phase"],
                        "auto_initialized_git": auto_initialized_git,
                        "reason": "WORKTREE_CREATE_FAILED",
                        "error": wt_res["error"],
                    }
                else:
                    execution_mode = "WAVE_PING_PONG"
                    fallback_reason = wt_res["error"]
            elif mode_clean == "worktree":
                return {
                    "ok": False,
                    "workspace": key,
                    "phase": ws["phase"],
                    "auto_initialized_git": auto_initialized_git,
                    "reason": "WORKTREE_UNAVAILABLE",
                    "error": f"mode=worktree 要求工作区为干净 Git 仓库根目录：{probe['fallback_reason']}",
                }
            else:
                execution_mode = "WAVE_PING_PONG"
                fallback_reason = probe["fallback_reason"]

        if execution_mode == "GIT_WORKTREE_PARALLEL" and isinstance(new_worktrees, dict):
            if isinstance(ws.get("worktrees"), dict):
                old_holder = {"worktrees": ws["worktrees"]}
                old_clean = _cleanup_round2_worktrees(old_holder, force=True)
                if not old_clean.get("cleaned") and isinstance(old_holder.get("worktrees"), dict):
                    new_worktrees["previous_cleanup_errors"] = old_holder["worktrees"].get(
                        "cleanup_errors", old_clean.get("errors", [])
                    )
            ws["worktrees"] = new_worktrees
        else:
            clean_res = _cleanup_round2_worktrees(ws, force=True)
            if clean_res.get("cleaned"):
                ws["worktrees"] = None
            elif isinstance(ws.get("worktrees"), dict):
                ws["worktrees"]["enabled"] = False

        tasks_for_a: list[dict[str, Any]] = []
        tasks_for_b: list[dict[str, Any]] = []
        for bug in planned_a:
            bug["assigned_fixer"] = "A"
            bug["status"] = "IN_CROSS_FIX"
            bug["cross_verify"] = None
            tasks_for_a.append(bug)
        for bug in planned_b:
            bug["assigned_fixer"] = "B"
            bug["status"] = "IN_CROSS_FIX"
            bug["cross_verify"] = None
            tasks_for_b.append(bug)

        ws["file_leases"] = {}

        schedule = _build_wave_schedule(
            tasks_for_a,
            tasks_for_b,
            key,
            round_no,
            extra_roots=_active_extra_roots(ws),
        )
        overlapping_files = schedule["overlapping_files"]

        if execution_mode == "GIT_WORKTREE_PARALLEL" and new_worktrees is not None:
            parallel_safe = True
            waves: list[dict[str, Any]] = [
                {
                    "wave": 0,
                    "type": "GIT_WORKTREE_PARALLEL",
                    "parallel_safe": True,
                    "A": [b["id"] for b in tasks_for_a],
                    "B": [b["id"] for b in tasks_for_b],
                    "A_worktree": new_worktrees["A"]["path"],
                    "B_worktree": new_worktrees["B"]["path"],
                    "note": (
                        "A 与 B 分别在各自隔离的 Git worktree 中真并行修改，互不踩踏；"
                        "各自汇报验证结果后，调用 hakimi_integrate_worktrees(action='merge') 合回主仓库并由铲屎官终验裁决。"
                    ),
                }
            ]
        elif execution_mode == "SINGLE_FIXER_DIRECT":
            parallel_safe = True
            waves = [
                {
                    "wave": 0,
                    "type": "SINGLE_FIXER_DIRECT",
                    "parallel_safe": True,
                    "A": [b["id"] for b in tasks_for_a],
                    "B": [b["id"] for b in tasks_for_b],
                    "note": "仅单侧存在待修 Bug，直接在当前工作区完成修复即可。",
                }
            ]
        else:
            parallel_safe = len(overlapping_files) == 0
            waves = schedule["waves"]

        plan = {
            "execution_mode": execution_mode,
            "requested_mode": mode_clean,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": fallback_reason,
            "overlapping_files": overlapping_files,
            "parallel_safe": parallel_safe,
            "waves": waves,
            "created_at": _now_iso(),
        }
        ws["cross_fix_plan"] = plan
        ws["phase"] = "ROUND2_CROSS_FIXING"
        ws["round2_result"] = None
        ws["current_cross_fix_bug_ids"] = [b["id"] for b in tasks_for_a + tasks_for_b]
        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        git_init_prefix = "（检测到工作区尚无 Git 仓库，已自动初始化 Git 并创建基线提交。）" if auto_initialized_git else ""
        if execution_mode == "GIT_WORKTREE_PARALLEL" and new_worktrees is not None:
            mode_msg = (
                f" 已启用【Git Worktree 真并行隔离】{git_init_prefix}："
                f"A 工作目录={new_worktrees['A']['path']}（分支 {new_worktrees['A']['branch']}），"
                f"B 工作目录={new_worktrees['B']['path']}（分支 {new_worktrees['B']['branch']}）。"
                "双方可同时并行修改（含重叠文件），完成后请调用 hakimi_integrate_worktrees(action='merge') 合回主仓库。"
            )
        elif execution_mode == "SINGLE_FIXER_DIRECT":
            mode_msg = " 仅单方存在待修任务，已采用单侧直修模式。"
        else:
            fb_prefix = f"（降级原因：{fallback_reason}）" if fallback_reason else ""
            if overlapping_files:
                mode_msg = (
                    f" 已启用【波次乒乓协同】{git_init_prefix}{fb_prefix}：共拆分 {len(waves)} 个波次，"
                    f"重叠文件 {overlapping_files} 按先手均衡原则交替修改，修改前请先调用 hakimi_claim_files 抢占软锁。"
                )
            else:
                mode_msg = f" 已启用【波次乒乓协同】{git_init_prefix}{fb_prefix}：双方修复文件互不重叠，可在 Wave 0 安全并行。"

        return {
            "ok": True,
            "workspace": key,
            "phase": ws["phase"],
            "only_shazi": only_shazi,
            "execution_mode": execution_mode,
            "requested_mode": mode_clean,
            "auto_initialized_git": auto_initialized_git,
            "fallback_reason": fallback_reason,
            "worktrees": new_worktrees,
            "waves": waves,
            "cross_fix_plan": plan,
            "tasks_for_A": tasks_for_a,
            "tasks_for_B": tasks_for_b,
            "overlapping_files": overlapping_files,
            "parallel_safe": parallel_safe,
            "agent_a_conv_id": ws["agents"]["A"]["conv_id"],
            "agent_b_conv_id": ws["agents"]["B"]["conv_id"],
            "message": (
                f"第二局【交叉修 Bug 赛（二胜）】启动！A 需修复 B 找到的 {len(tasks_for_a)} 个 Bug，"
                f"B 需修复 A 找到的 {len(tasks_for_b)} 个 Bug。{mode_msg}"
            ),
        }


def cmd_claim_files(
    claimer: str,
    files: str | list[str],
    release: bool = False,
    note: str = "",
    workspace: str | None = None,
) -> dict[str, Any]:
    """Acquire or release cooperative file edit leases during Round 2 cross-fixing."""
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if not isinstance(claimer, str) or not claimer.strip():
        return {"ok": False, "error": f"claimer 必须是字符串 (A 或 B)，收到: {claimer!r}"}
    cl = claimer.strip().upper()
    if cl not in VALID_AGENTS:
        return {"ok": False, "error": f"claimer 必须是 A 或 B，收到: {claimer}"}

    if not isinstance(files, (list, str)):
        return {"ok": False, "error": "files 必须是文件路径字符串或字符串数组。"}

    if note is None:
        note_clean = ""
    elif isinstance(note, str):
        note_clean = note.strip()
    else:
        note_clean = str(note).strip()

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)
        if ws["phase"] != "ROUND2_CROSS_FIXING":
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 ROUND2_CROSS_FIXING 交叉修复阶段可申请/释放文件软锁。",
            }

        extra_roots = _active_extra_roots(ws, agent_id=cl)
        if isinstance(files, list):
            raw_items = [x for x in files if isinstance(x, str)]
        else:
            raw_items = _split_files_string(files, workspace=key, extra_roots=extra_roots)

        wt = ws.get("worktrees")
        opp_wt_path: Path | None = None
        opp_wt_norm_prefix = ""
        if isinstance(wt, dict) and wt.get("enabled"):
            opp = "B" if cl == "A" else "A"
            opp_entry = wt.get(opp)
            if isinstance(opp_entry, dict) and isinstance(opp_entry.get("path"), str) and opp_entry["path"].strip():
                opp_key = _normalize_workspace_key(opp_entry["path"])
                opp_wt_norm_prefix = opp_key.lower() if os.name == "nt" else opp_key
                try:
                    opp_wt_path = Path(opp_key).resolve()
                except OSError:
                    opp_wt_path = Path(opp_key)

        norm_paths: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            if "\x00" in item:
                return {"ok": False, "error": "包含非法文件路径（文件路径不能包含空字节）。"}
            tok = _clean_file_token(item)
            if not tok:
                continue
            tok_slash = tok.replace("\\", "/")
            if tok_slash.startswith("//"):
                return {"ok": False, "error": f"包含非法文件路径 '{tok}'（不支持的网络 UNC 路径）。"}
            has_drive = bool(re.match(r"^[A-Za-z]:", tok_slash))
            if has_drive and (len(tok_slash) < 3 or tok_slash[2] != "/"):
                return {"ok": False, "error": f"包含非法文件路径 '{tok}'（不支持的盘符相对路径）。"}

            if opp_wt_path is not None:
                tok_posix = re.sub(r"/+", "/", tok_slash)
                tok_is_abs = tok_posix.startswith("/") or bool(re.match(r"^[A-Za-z]:/", tok_posix))
                in_opp_wt = False
                try:
                    if tok_is_abs:
                        cand_p = Path(tok_posix).resolve()
                        in_opp_wt = cand_p == opp_wt_path or cand_p.is_relative_to(opp_wt_path)
                    elif key not in ("default", "__default__") and Path(key).is_absolute():
                        cand_p = (Path(key) / posixpath.normpath(tok_posix)).resolve()
                        in_opp_wt = cand_p == opp_wt_path or cand_p.is_relative_to(opp_wt_path)
                except OSError:
                    pass
                if not in_opp_wt and opp_wt_norm_prefix:
                    cand_cmp = tok_posix.rstrip("/").lower() if os.name == "nt" else tok_posix.rstrip("/")
                    if cand_cmp == opp_wt_norm_prefix or cand_cmp.startswith(opp_wt_norm_prefix + "/"):
                        in_opp_wt = True
                if in_opp_wt:
                    return {"ok": False, "error": f"包含非法文件路径 '{tok}'（禁止越权访问对方工作树）。"}

            tok_is_abs = tok_slash.startswith("/") or has_drive
            if tok_is_abs:
                allowed_roots = [r for r in (*extra_roots, key) if r not in ("default", "__default__") and Path(r).is_absolute()]
                if not allowed_roots:
                    err = _validate_report_file_path(tok, key)
                    return {"ok": False, "error": err or f"包含非法文件路径 '{tok}'。"}
                if not any(_validate_report_file_path(tok, r) is None for r in allowed_roots):
                    err = _validate_report_file_path(tok, key)
                    return {"ok": False, "error": err or f"包含非法文件路径 '{tok}'（不允许越出工作区）。"}
            else:
                path_err = _validate_report_file_path(tok, key)
                if path_err:
                    return {"ok": False, "error": path_err}
                for root_cand in extra_roots:
                    if root_cand not in ("default", "__default__") and Path(root_cand).is_absolute():
                        extra_err = _validate_report_file_path(tok, root_cand)
                        if extra_err:
                            return {"ok": False, "error": extra_err}

            norm = _normalize_path(tok, workspace=key, extra_roots=extra_roots)
            is_outside_abs = bool(
                norm
                and key not in ("default", "__default__")
                and (norm.startswith("/") or re.match(r"^[A-Za-z]:(?:/|$)", norm))
            )
            if not norm or norm in (".", "..") or norm.startswith("../") or is_outside_abs:
                return {"ok": False, "error": f"包含非法文件路径 '{tok}'（不允许越出工作区）。"}
            if norm not in seen:
                seen.add(norm)
                norm_paths.append(norm)

        if not norm_paths:
            return {"ok": False, "error": "files 不能为空，请提供至少一个有效文件路径。"}

        leases = ws.setdefault("file_leases", {})
        if not isinstance(leases, dict):
            leases = {}
            ws["file_leases"] = leases

        if release:
            released: list[str] = []
            not_held_by_caller: list[str] = []
            for fp in norm_paths:
                entry = leases.get(fp)
                if isinstance(entry, dict) and entry.get("holder") == cl:
                    del leases[fp]
                    released.append(fp)
                else:
                    not_held_by_caller.append(fp)
            ws["updated_at"] = _now_iso()
            _save_root_state(root)
            return {
                "ok": True,
                "workspace": key,
                "claimer": cl,
                "action": "release",
                "released_files": released,
                "not_held_by_caller": not_held_by_caller,
                "file_leases": leases,
                "message": f"{ws['agents'][cl]['name']} 已释放文件锁: {released or '（无匹配锁）'}",
            }

        conflicts: list[dict[str, Any]] = []
        for fp in norm_paths:
            entry = leases.get(fp)
            if isinstance(entry, dict) and entry.get("holder") in VALID_AGENTS and entry.get("holder") != cl:
                conflicts.append(
                    {
                        "file": fp,
                        "holder": entry["holder"],
                        "claimed_at": entry.get("claimed_at"),
                        "note": entry.get("note", ""),
                    }
                )
        if conflicts:
            return {
                "ok": False,
                "workspace": key,
                "reason": "FILE_LOCKED",
                "conflicts": conflicts,
                "file_leases": leases,
                "error": f"文件已被对方哈基米占用锁定，请等待对方完成修改并释放锁后再操作: {conflicts}",
            }

        now = _now_iso()
        for fp in norm_paths:
            leases[fp] = {
                "holder": cl,
                "claimed_at": now,
                "note": note_clean,
            }
        ws["updated_at"] = now
        _save_root_state(root)
        return {
            "ok": True,
            "workspace": key,
            "claimer": cl,
            "action": "claim",
            "claimed_files": norm_paths,
            "file_leases": leases,
            "message": f"{ws['agents'][cl]['name']} 已锁定文件 {norm_paths}，请尽快改完并用 latest 读取确保上下文同步。",
        }


def cmd_report_fix(
    fixer: str,
    bug_id: str,
    status: str,
    summary: str,
    workspace: str | None = None,
    files_changed: str | list[str] | None = None,
    verify_cmd: str | None = None,
    verify_passed: bool | None = None,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if not isinstance(fixer, str) or not fixer.strip():
        return {"ok": False, "error": f"fixer 必须是字符串 (A 或 B)，收到: {fixer!r}"}
    fx = fixer.strip().upper()
    if fx not in VALID_AGENTS:
        return {"ok": False, "error": f"fixer 必须是 A 或 B，收到: {fixer}"}

    if not isinstance(status, str) or not status.strip():
        return {"ok": False, "error": f"status 必须是字符串 (FIXED 或 CANT_FIX)，收到: {status!r}"}
    st = status.strip().upper()
    if st not in VALID_FIX_STATUSES:
        return {"ok": False, "error": f"status 必须是 FIXED 或 CANT_FIX，收到: {status}"}

    if not isinstance(bug_id, str) or not bug_id.strip():
        return {"ok": False, "error": "bug_id 不能为空。"}
    bid = bug_id.strip().upper()

    if not isinstance(summary, str) or not summary.strip():
        return {"ok": False, "error": "修复摘要 summary 不能为空或纯空白。"}

    if files_changed is not None and not isinstance(files_changed, (str, list)):
        return {"ok": False, "error": "files_changed 必须是字符串或字符串数组。"}

    if verify_cmd is not None and not isinstance(verify_cmd, str):
        return {"ok": False, "error": "verify_cmd 必须是字符串。"}
    v_cmd = verify_cmd.strip() or None if isinstance(verify_cmd, str) else None

    if verify_passed is not None and not isinstance(verify_passed, bool):
        return {"ok": False, "error": f"verify_passed 必须是布尔值 (true/false)，收到: {verify_passed!r}"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] != "ROUND2_CROSS_FIXING":
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，不在 ROUND2_CROSS_FIXING 交叉修复阶段，禁止提交修复报告。",
            }

        bug = next((b for b in ws["bugs"] if b["id"] == bid), None)
        if not bug:
            return {"ok": False, "error": f"找不到 Bug {bid}。"}

        if bug.get("assigned_fixer") != fx:
            return {
                "ok": False,
                "error": f"{bid} 由 {bug['finder']} 发现，只能由 {bug['assigned_fixer']} 交叉修复，{fx} 不可越权插手！",
            }

        tracked_set = {
            str(i).strip().upper()
            for i in (ws.get("current_cross_fix_bug_ids") or [])
            if isinstance(i, str) and i.strip()
        }
        allowed_fix_statuses = {"IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED"}
        if bid in tracked_set:
            allowed_fix_statuses.add("SHAZI_FAILED")
        if bug.get("status") not in allowed_fix_statuses:
            return {
                "ok": False,
                "bug_id": bid,
                "bug_status": bug.get("status"),
                "error": f"{bid} 当前状态为 {bug.get('status')}，仅 IN_CROSS_FIX、PENDING_JUDGE 或 FIX_FAILED 状态允许提交修复报告。",
            }

        extra_roots = _active_extra_roots(ws, agent_id=fx)
        changed_list = _parse_files_arg(files_changed, workspace=key, extra_roots=extra_roots) if files_changed else []
        attempt = {
            "attempt_no": len(bug.get("fix_attempts", [])) + 1,
            "fixer": fx,
            "status": st,
            "summary": summary.strip(),
            "files_changed": changed_list,
            "verify_cmd": v_cmd,
            "verify_passed": verify_passed,
            "reported_at": _now_iso(),
        }
        bug.setdefault("fix_attempts", []).append(attempt)
        bug["status"] = "PENDING_JUDGE" if st == "FIXED" else "FIX_FAILED"
        bug["cross_verify"] = None

        wt = ws.get("worktrees")
        if isinstance(wt, dict) and wt.get("enabled"):
            fx_entry = wt.get(fx)
            if isinstance(fx_entry, dict) and fx_entry.get("merged"):
                fx_entry["merged"] = False
                wt["all_merged"] = False

        # Auto-release file leases held by fixer when no other active IN_CROSS_FIX bug of fixer uses those files
        still_needed: set[str] = set()
        for other in ws["bugs"]:
            if other["id"] != bid and other.get("assigned_fixer") == fx and other.get("status") == "IN_CROSS_FIX":
                of = _normalize_path(
                    other.get("file_norm") or other.get("file") or "",
                    workspace=key,
                    extra_roots=extra_roots,
                )
                if of:
                    still_needed.add(of)

        lease_candidates: list[str] = []
        primary_fn = _normalize_path(
            bug.get("file_norm") or bug.get("file") or "",
            workspace=key,
            extra_roots=extra_roots,
        )
        if primary_fn:
            lease_candidates.append(primary_fn)
        for cf in changed_list:
            norm_cf = _normalize_path(cf, workspace=key, extra_roots=extra_roots)
            if norm_cf and norm_cf not in lease_candidates:
                lease_candidates.append(norm_cf)

        auto_released: list[str] = []
        for lf in lease_candidates:
            if lf not in still_needed:
                auto_released.extend(_release_agent_leases_for_file(ws, fx, lf))

        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        return {
            "ok": True,
            "workspace": key,
            "bug_id": bid,
            "bug_status": bug["status"],
            "attempt": attempt,
            "auto_released_files": auto_released,
            "message": f"{ws['agents'][fx]['name']} 已提交 {bid} 的修复报告（状态：{bug['status']}），等待铲屎官核查并提交二胜裁决！",
        }


def cmd_report_verify(
    verifier: str,
    bug_id: str,
    verdict: str,
    note: str = "",
    workspace: str | None = None,
) -> dict[str, Any]:
    """Allow original bug finder to cross-verify (or hiss-reject) the opponent's fix."""
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if not isinstance(verifier, str) or not verifier.strip():
        return {"ok": False, "error": f"verifier 必须是字符串 (A 或 B)，收到: {verifier!r}"}
    vf = verifier.strip().upper()
    if vf not in VALID_AGENTS:
        return {"ok": False, "error": f"verifier 必须是 A 或 B，收到: {verifier}"}

    if not isinstance(bug_id, str) or not bug_id.strip():
        return {"ok": False, "error": "bug_id 不能为空。"}
    bid = bug_id.strip().upper()

    if not isinstance(verdict, str) or not verdict.strip():
        return {"ok": False, "error": f"verdict 必须是 VERIFIED 或 REJECT_WITH_HISS，收到: {verdict!r}"}
    vd = verdict.strip().upper()
    if vd not in VALID_VERIFY_VERDICTS:
        return {"ok": False, "error": f"无效 verdict '{verdict}'，仅支持 VERIFIED 或 REJECT_WITH_HISS。"}

    if note is None:
        note_clean = ""
    elif isinstance(note, str):
        note_clean = note.strip()
    else:
        note_clean = str(note).strip()

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] != "ROUND2_CROSS_FIXING":
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 ROUND2_CROSS_FIXING 阶段可执行互哈互验。",
            }

        bug = next((b for b in ws["bugs"] if b["id"] == bid), None)
        if not bug:
            return {"ok": False, "error": f"找不到 Bug {bid}。"}

        if bug.get("finder") != vf or bug.get("assigned_fixer") == vf:
            return {
                "ok": False,
                "error": f"{bid} 仅允许由原发现者（哈基米{bug.get('finder')}）进行互哈互验，修复者不可自查放行！",
            }

        tracked_set = {
            str(i).strip().upper()
            for i in (ws.get("current_cross_fix_bug_ids") or [])
            if isinstance(i, str) and i.strip()
        }
        allowed_verify_statuses = {"PENDING_JUDGE", "FIX_FAILED"}
        if bid in tracked_set:
            allowed_verify_statuses.add("SHAZI_FAILED")
        if bug.get("status") not in allowed_verify_statuses:
            return {
                "ok": False,
                "bug_id": bid,
                "bug_status": bug.get("status"),
                "error": f"{bid} 当前状态为 {bug.get('status')}，修复者尚未提交修复报告（需 PENDING_JUDGE 或 FIX_FAILED）。",
            }

        if vd == "VERIFIED" and bug.get("status") != "PENDING_JUDGE":
            return {
                "ok": False,
                "workspace": key,
                "bug_id": bid,
                "bug_status": bug.get("status"),
                "error": f"{bid} 当前状态为 {bug.get('status')}（未修复完成），禁止以 VERIFIED 盖章放行；仅允许 REJECT_WITH_HISS 打回重修。",
            }

        if vd == "REJECT_WITH_HISS" and not note_clean:
            note_clean = "原发现者复验未通过（哈气打回重修）。"

        verify_record = {
            "verifier": vf,
            "fixer": bug.get("assigned_fixer"),
            "verdict": vd,
            "note": note_clean,
            "verified_at": _now_iso(),
        }
        bug["cross_verify"] = verify_record
        bug.setdefault("cross_verify_history", []).append(verify_record)
        if vd == "REJECT_WITH_HISS":
            bug["status"] = "IN_CROSS_FIX"

        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        if vd == "REJECT_WITH_HISS":
            msg = (
                f"{ws['agents'][vf]['name']} 对 {bid} 哈气打回（REJECT_WITH_HISS）！"
                f"状态已退回 IN_CROSS_FIX，请哈基米{bug.get('assigned_fixer')}返工重修：{note_clean}"
            )
        else:
            msg = f"{ws['agents'][vf]['name']} 已互验放行 {bid}（VERIFIED），等待铲屎官最终裁决。"

        return {
            "ok": True,
            "workspace": key,
            "bug_id": bid,
            "bug_status": bug["status"],
            "cross_verify": verify_record,
            "message": msg,
        }


def cmd_integrate_worktrees(
    action: str = "status",
    workspace: str | None = None,
    cleanup: bool = True,
    abort_on_conflict: bool = True,
) -> dict[str, Any]:
    """Inspect, merge, or clean up isolated Round 2 Git worktrees."""
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if not isinstance(action, str) or not action.strip():
        return {"ok": False, "error": f"action 必须是 status / merge / cleanup，收到: {action!r}"}
    act = action.strip().lower()
    if act not in VALID_INTEGRATE_ACTIONS:
        return {"ok": False, "error": f"无效 action '{action}'，仅支持 status / merge / cleanup。"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)
        wt = ws.get("worktrees")

        if act == "status":
            if not isinstance(wt, dict) or not wt.get("repo_root"):
                return {
                    "ok": True,
                    "workspace": key,
                    "enabled": False,
                    "worktrees": None,
                    "message": "当前工作区未启用 Round 2 Git worktree 隔离。",
                }
            base_head = wt.get("base_head", "HEAD")
            agents_status: dict[str, Any] = {}
            for aid in VALID_AGENTS:
                entry = wt.get(aid)
                if not isinstance(entry, dict):
                    entry = {}
                p_str = entry.get("path", "")
                branch = entry.get("branch", "")
                p_obj = Path(p_str) if p_str else None
                exists = bool(p_obj and p_obj.is_dir())
                dirty_files: list[str] = []
                commits_ahead = 0
                changed_files: list[str] = []
                if exists and p_obj is not None:
                    ok_d, d_out, _ = _run_git(p_obj, ["status", "--porcelain"])
                    if ok_d and d_out.strip():
                        dirty_files = d_out.splitlines()
                    ok_cnt, cnt_out, _ = _run_git(p_obj, ["rev-list", "--count", f"{base_head}..HEAD"])
                    if ok_cnt and cnt_out.isdigit():
                        commits_ahead = int(cnt_out)
                    ok_cf, cf_out, _ = _run_git(p_obj, ["diff", "--name-only", f"{base_head}..HEAD"])
                    if ok_cf and cf_out.strip():
                        changed_files = cf_out.splitlines()
                agents_status[aid] = {
                    "path": p_str,
                    "branch": branch,
                    "exists": exists,
                    "merged": bool(entry.get("merged", False)),
                    "dirty_files": dirty_files,
                    "commits_ahead": commits_ahead,
                    "changed_files": changed_files,
                }
            res_status: dict[str, Any] = {
                "ok": True,
                "workspace": key,
                "enabled": bool(wt.get("enabled", True)),
                "repo_root": wt.get("repo_root"),
                "base_head": base_head,
                "agents": agents_status,
            }
            if wt.get("cleanup_errors"):
                res_status["cleanup_errors"] = list(wt["cleanup_errors"])
            return res_status

        if act == "cleanup":
            if not isinstance(wt, dict):
                return {"ok": True, "workspace": key, "cleaned": False, "message": "当前无待清理的 Git worktree。"}
            clean_res = _cleanup_round2_worktrees(ws, force=True)
            ws["updated_at"] = _now_iso()
            _save_root_state(root)
            if not clean_res["cleaned"]:
                return {
                    "ok": False,
                    "workspace": key,
                    **clean_res,
                    "error": f"清理第2局 Git worktree 失败，已保留残留条目供继续追踪重试: {'; '.join(clean_res['errors'])}",
                    "message": "第2局 Git worktree 清理未完成，状态指针已保留以便排查或重试。",
                }
            return {
                "ok": True,
                "workspace": key,
                **clean_res,
                "message": "已清理第2局 Git worktree 目录与临时分支。",
            }

        # action == "merge"
        if ws["phase"] not in ("ROUND2_CROSS_FIXING", "SUSPENDED_ROUND2"):
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 ROUND2_CROSS_FIXING 或 SUSPENDED_ROUND2 阶段可合并第2局 worktree。",
            }
        if not isinstance(wt, dict) or not wt.get("repo_root"):
            return {
                "ok": False,
                "workspace": key,
                "error": "当前未开启 Git worktree 隔离模式，无需合并 worktree。",
            }

        repo_root = Path(wt["repo_root"])
        if not repo_root.is_dir():
            return {"ok": False, "workspace": key, "error": f"主仓库目录不存在：{repo_root}"}

        ok_main_st, main_dirty, err_main_st = _run_git(repo_root, ["status", "--porcelain"])
        if not ok_main_st:
            return {"ok": False, "workspace": key, "error": f"检查主仓库状态失败：{err_main_st}"}
        if main_dirty.strip():
            return {
                "ok": False,
                "workspace": key,
                "reason": "DIRTY_MAIN_REPO",
                "error": "主仓库当前存在未提交改动，请先暂存/清理主工作区后再合并 worktree。",
            }

        ok_orig, orig_head, err_orig = _run_git(repo_root, ["rev-parse", "HEAD"])
        if not ok_orig or not orig_head:
            return {"ok": False, "workspace": key, "error": f"获取主仓库 HEAD 失败：{err_orig}"}

        # Step 1: auto-commit any uncommitted edits inside each worktree
        commit_summary: dict[str, Any] = {}
        for aid in VALID_AGENTS:
            entry = wt.get(aid)
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            cm_res = _auto_commit_worktree(
                Path(entry["path"]),
                f"hakimi-hiss: Round 2 cross-fix edits by Hakimi-{aid}",
            )
            if not cm_res["ok"]:
                return {"ok": False, "workspace": key, "failed_agent": aid, "error": cm_res["error"]}
            entry["last_commit"] = cm_res["head"]
            commit_summary[aid] = cm_res

        # Step 2: sequentially merge A & B branches into main repo
        merged_agents: list[str] = []
        skipped_agents: list[str] = []
        for aid in VALID_AGENTS:
            entry = wt.get(aid)
            if not isinstance(entry, dict) or not entry.get("branch"):
                continue
            branch = entry["branch"]
            ok_ahead, ahead_out, _ = _run_git(repo_root, ["rev-list", "--count", f"HEAD..{branch}"])
            ahead_cnt = int(ahead_out) if ok_ahead and ahead_out.isdigit() else 1
            if ahead_cnt == 0:
                entry["merged"] = True
                skipped_agents.append(aid)
                continue

            ok_mg, _, err_mg = _run_git(
                repo_root,
                [
                    "-c",
                    "user.name=Hakimi Agent",
                    "-c",
                    "user.email=hakimi@duel.local",
                    "merge",
                    "--no-ff",
                    "--no-edit",
                    "-m",
                    f"hakimi-hiss: integrate Round 2 fixes from Hakimi-{aid} ({branch})",
                    branch,
                ],
            )
            if not ok_mg:
                ok_u, u_out, _ = _run_git(repo_root, ["diff", "--name-only", "--diff-filter=U"])
                conflicting_files = u_out.splitlines() if ok_u and u_out.strip() else []
                if abort_on_conflict:
                    _run_git(repo_root, ["merge", "--abort"])
                    _run_git(repo_root, ["reset", "--hard", orig_head])
                    for rst_aid in VALID_AGENTS:
                        if isinstance(wt.get(rst_aid), dict):
                            wt[rst_aid]["merged"] = False
                    ws["updated_at"] = _now_iso()
                    _save_root_state(root)
                    return {
                        "ok": False,
                        "workspace": key,
                        "reason": "MERGE_CONFLICT",
                        "failed_agent": aid,
                        "conflicting_files": conflicting_files,
                        "worktrees_preserved": True,
                        "orig_head": orig_head,
                        "error": (
                            f"合并哈基米{aid}分支 ({branch}) 时发生冲突"
                            f"（冲突文件：{conflicting_files or [err_mg]}），"
                            f"已原子回滚主仓库至 {orig_head[:8]} 并保留双方 worktree 供排查。"
                        ),
                        "git_error": err_mg,
                    }
                ws["updated_at"] = _now_iso()
                _save_root_state(root)
                return {
                    "ok": False,
                    "workspace": key,
                    "reason": "MERGE_CONFLICT",
                    "failed_agent": aid,
                    "merged_agents": merged_agents,
                    "conflicting_files": conflicting_files,
                    "worktrees_preserved": True,
                    "error": f"合并哈基米{aid}分支 ({branch}) 时发生冲突，已在主工作区保留冲突标记待手工解决。",
                    "git_error": err_mg,
                }
            entry["merged"] = True
            merged_agents.append(aid)

        _, merged_head, _ = _run_git(repo_root, ["rev-parse", "HEAD"])
        clean_res: dict[str, Any] | None = None
        if cleanup:
            clean_res = _cleanup_round2_worktrees(ws, force=True)
            cleaned_up_ok = bool(clean_res.get("cleaned"))
            if not cleaned_up_ok and isinstance(ws.get("worktrees"), dict):
                ws["worktrees"]["enabled"] = False
                ws["worktrees"]["all_merged"] = True
        else:
            cleaned_up_ok = False
            wt["all_merged"] = True

        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        if cleanup and cleaned_up_ok:
            cleanup_msg = "临时 worktree 与分支已自动清理。"
        elif cleanup:
            cleanup_msg = f"但临时 worktree 清理未完全成功（已保留状态指针以便重试 action=cleanup）: {'; '.join((clean_res or {}).get('errors', []))}"
        else:
            cleanup_msg = "已保留 worktree 目录（可使用 action=cleanup 清理）。"

        return {
            "ok": True,
            "workspace": key,
            "orig_head": orig_head,
            "merged_head": merged_head,
            "merged_agents": merged_agents,
            "skipped_no_changes": skipped_agents,
            "auto_commits": commit_summary,
            "cleaned_up": cleaned_up_ok,
            "cleanup_result": clean_res,
            "message": f"第2局双猫 worktree 已成功集成到主仓库 ({merged_head[:8]})！{cleanup_msg}",
        }


def cmd_judge_round2(
    verdicts: str | list[dict[str, Any]],
    workspace: str | None = None,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if isinstance(verdicts, str):
        try:
            verdict_list = json.loads(verdicts)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"verdicts JSON 解析失败: {exc}"}
    else:
        verdict_list = verdicts

    if not isinstance(verdict_list, list) or not verdict_list:
        return {"ok": False, "error": "verdicts 必须是非空 JSON 数组。"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)

        if ws["phase"] != "ROUND2_CROSS_FIXING":
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "error": f"当前阶段为 {ws['phase']}，仅在 ROUND2_CROSS_FIXING 阶段可执行二胜裁决（不可在裁决结束后重复刷分）。",
            }

        tracked = ws.get("current_cross_fix_bug_ids")
        tracked_set = (
            {str(i).strip().upper() for i in tracked if isinstance(i, str) and i.strip()}
            if isinstance(tracked, list)
            else set()
        )
        bug_map = {b["id"]: b for b in ws["bugs"]}
        validated_items: list[tuple[dict[str, Any], str, str, str]] = []
        seen_bids: set[str] = set()

        for item in verdict_list:
            if not isinstance(item, dict):
                return {"ok": False, "error": f"无效评判项: {item}"}
            raw_bid = item.get("bug_id")
            raw_v = item.get("verdict")
            if not isinstance(raw_bid, str) or not raw_bid.strip():
                return {"ok": False, "error": f"评判项缺少有效的 bug_id: {item}"}
            if not isinstance(raw_v, str) or not raw_v.strip():
                return {"ok": False, "error": f"评判项缺少有效的 verdict: {item}"}

            bid = raw_bid.strip().upper()
            v = raw_v.strip().upper()
            raw_comment = item.get("comment")
            if raw_comment is None:
                comment = ""
            elif isinstance(raw_comment, str):
                comment = raw_comment.strip()
            else:
                comment = str(raw_comment).strip()

            if bid in seen_bids:
                return {"ok": False, "error": f"verdicts 中包含重复 Bug ID: {bid}，禁止重复计分。"}
            seen_bids.add(bid)

            if bid not in bug_map:
                return {"ok": False, "error": f"评判引用了不存在的 Bug ID: {bid}"}
            if tracked_set and bid not in tracked_set:
                return {
                    "ok": False,
                    "workspace": key,
                    "phase": ws["phase"],
                    "error": f"Bug {bid} 不在本轮交叉修复任务清单 ({', '.join(sorted(tracked_set))}) 中，禁止跨轮/越范围评判。",
                }
            if v not in VALID_VERDICTS:
                return {"ok": False, "error": f"无效 verdict '{v}'（仅支持 PERFECT / PASS / FAILED）"}

            bug = bug_map[bid]
            fixer = bug.get("assigned_fixer")
            if fixer not in VALID_AGENTS:
                return {"ok": False, "error": f"Bug {bid} 缺少有效的 assigned_fixer ({fixer!r})。"}
            allowed_judge_statuses = {"IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED"}
            if bid in tracked_set:
                allowed_judge_statuses.add("SHAZI_FAILED")
            if bug.get("status") not in allowed_judge_statuses:
                return {
                    "ok": False,
                    "error": f"Bug {bid} 当前状态为 {bug.get('status')}，不属于本轮待裁决交叉修复任务。",
                }

            validated_items.append((bug, fixer, v, comment))

        if tracked_set:
            round2_active = [
                bug_map[tid]
                for tid in (str(i).strip().upper() for i in tracked if isinstance(i, str) and i.strip())
                if tid in bug_map
                and bug_map[tid].get("status") in ("IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED", "SHAZI_FAILED")
            ]
        else:
            round2_active = [
                b for b in ws["bugs"] if b.get("status") in ("IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED")
            ]

        missing_ids = [b["id"] for b in round2_active if b["id"] not in seen_bids]
        if missing_ids:
            return {
                "ok": False,
                "workspace": key,
                "phase": ws["phase"],
                "missing_bug_ids": missing_ids,
                "error": f"裁决不完整！以下本轮交叉修复任务未出现在 verdicts 中（不可局部逃避统计）: {', '.join(missing_ids)}",
            }

        applied: list[dict[str, Any]] = []
        new_shazi: list[dict[str, Any]] = []

        for bug, fixer, v, comment in validated_items:
            bid = bug["id"]
            bug["judge_verdict"] = v
            bug["judge_comment"] = comment

            if v == "PERFECT":
                _clear_bug_shazi_penalty(ws, bug)
                bug["status"] = "FIXED_PERFECT"
            elif v == "PASS":
                _clear_bug_shazi_penalty(ws, bug)
                bug["status"] = "FIXED_PASS"
            else:
                bug["status"] = "SHAZI_FAILED"
                reason = comment or "交叉修复未通过铲屎官验收"
                bug.setdefault("shazi_reasons", []).append(f"[{_now_iso()}] {reason}")
                badge = f"【啥子】修 {bid} 翻车：{reason}"
                _apply_bug_shazi_penalty(ws, bug, fixer, badge)
                new_shazi.append({"agent": fixer, "bug_id": bid, "badge": badge})

            applied.append({"bug_id": bid, "fixer": fixer, "verdict": v, "comment": comment})

        def _calc_fixer_stats(agent_id: str) -> dict[str, Any]:
            judged = [a for a in applied if a["fixer"] == agent_id]
            perfect = sum(1 for a in judged if a["verdict"] == "PERFECT")
            passed = sum(1 for a in judged if a["verdict"] == "PASS")
            failed = sum(1 for a in judged if a["verdict"] == "FAILED")
            score = sum(VERDICT_POINTS[a["verdict"]] for a in judged)
            total = len(judged)
            perfection_rate = round((perfect / total) * 100.0, 1) if total > 0 else None
            return {
                "assigned_judged": total,
                "perfect": perfect,
                "pass": passed,
                "failed": failed,
                "score": score,
                "perfection_rate": perfection_rate,
            }

        stats_a = _calc_fixer_stats("A")
        stats_b = _calc_fixer_stats("B")

        # Determine Round 2 winner (二胜)
        if stats_a["assigned_judged"] == 0 and stats_b["assigned_judged"] == 0:
            winner = "DRAW"
            banner = "🤝 本轮无交叉修复评判记录。"
        elif stats_a["assigned_judged"] > 0 and stats_b["assigned_judged"] == 0:
            if stats_a["failed"] == 0:
                winner = "A"
                ws["agents"]["A"]["round2_wins"] += 1
                banner = f"🏆 二胜归属：{ws['agents']['A']['name']}（独立完成 {stats_a['assigned_judged']} 项修复，零翻车）！"
            else:
                winner = "DRAW"
                banner = f"🤝 {ws['agents']['A']['name']} 出现修复翻车（被贴【啥子】），B 暂无待修任务，本轮判平。"
        elif stats_b["assigned_judged"] > 0 and stats_a["assigned_judged"] == 0:
            if stats_b["failed"] == 0:
                winner = "B"
                ws["agents"]["B"]["round2_wins"] += 1
                banner = f"🏆 二胜归属：{ws['agents']['B']['name']}（独立完成 {stats_b['assigned_judged']} 项修复，零翻车）！"
            else:
                winner = "DRAW"
                banner = f"🤝 {ws['agents']['B']['name']} 出现修复翻车（被贴【啥子】），A 暂无待修任务，本轮判平。"
        else:
            key_a = (stats_a["score"], stats_a["perfection_rate"] or 0.0, -stats_a["failed"])
            key_b = (stats_b["score"], stats_b["perfection_rate"] or 0.0, -stats_b["failed"])
            if key_a > key_b:
                winner = "A"
                ws["agents"]["A"]["round2_wins"] += 1
                banner = (
                    f"🏆 二胜归属：{ws['agents']['A']['name']}！"
                    f"（A 得分 {stats_a['score']} / 完美率 {stats_a['perfection_rate']}% vs "
                    f"B 得分 {stats_b['score']} / 完美率 {stats_b['perfection_rate']}%）"
                )
            elif key_b > key_a:
                winner = "B"
                ws["agents"]["B"]["round2_wins"] += 1
                banner = (
                    f"🏆 二胜归属：{ws['agents']['B']['name']}！"
                    f"（B 得分 {stats_b['score']} / 完美率 {stats_b['perfection_rate']}% vs "
                    f"A 得分 {stats_a['score']} / 完美率 {stats_a['perfection_rate']}%）"
                )
            else:
                winner = "DRAW"
                banner = f"🤝 第二局平手（双方同分 {stats_a['score']} 分，完美率 {stats_a['perfection_rate']}%）！"

        cross_verify_summary = {
            "verified": sum(1 for bug, _, _, _ in validated_items if (bug.get("cross_verify") or {}).get("verdict") == "VERIFIED"),
            "rejected": sum(1 for bug, _, _, _ in validated_items if (bug.get("cross_verify") or {}).get("verdict") == "REJECT_WITH_HISS"),
            "unverified": sum(1 for bug, _, _, _ in validated_items if not bug.get("cross_verify")),
        }

        wt = ws.get("worktrees")
        worktree_warning: str | None = None
        if isinstance(wt, dict) and wt.get("enabled"):
            repo_root_str = wt.get("repo_root")
            repo_root_p = Path(repo_root_str) if isinstance(repo_root_str, str) and repo_root_str else None
            unmerged_agents: list[str] = []
            for aid in VALID_AGENTS:
                entry = wt.get(aid)
                if not isinstance(entry, dict):
                    continue
                is_unmerged = not entry.get("merged")
                if not is_unmerged and repo_root_p is not None and entry.get("path"):
                    if _worktree_has_unmerged_changes(repo_root_p, Path(entry["path"])):
                        entry["merged"] = False
                        wt["all_merged"] = False
                        is_unmerged = True
                if is_unmerged:
                    unmerged_agents.append(aid)
            if unmerged_agents:
                worktree_warning = (
                    f"检测到哈基米 {'/'.join(unmerged_agents)} 的第2局 Git worktree 尚未合回主仓库，"
                    "如需合入主工作区并清理临时分支，请调用 hakimi_integrate_worktrees(action='merge')。"
                )

        ws["phase"] = "SUSPENDED_ROUND2"
        ws["current_cross_fix_bug_ids"] = []
        ws["file_leases"] = {}
        ws["round2_result"] = {
            "winner": winner,
            "banner": banner,
            "stats": {"A": stats_a, "B": stats_b},
            "cross_verify_summary": cross_verify_summary,
            "worktree_warning": worktree_warning,
            "applied_verdicts": applied,
            "new_shazi": new_shazi,
            "judged_at": _now_iso(),
        }
        ws["updated_at"] = _now_iso()
        _save_root_state(root)

        return {
            "ok": True,
            "workspace": key,
            "phase": ws["phase"],
            "round2_winner": winner,
            "banner": banner,
            "stats": {"A": stats_a, "B": stats_b},
            "cross_verify_summary": cross_verify_summary,
            "worktree_warning": worktree_warning,
            "new_shazi": new_shazi,
            "scoreboard": _build_scoreboard(ws),
        }


def cmd_mark_shazi(
    target_type: str,
    target_id: str,
    reason: str = "",
    clear: bool = False,
    workspace: str | None = None,
) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    if not isinstance(target_type, str) or not target_type.strip():
        return {"ok": False, "error": f"target_type 必须是 bug 或 agent，收到: {target_type!r}"}
    if not isinstance(target_id, str) or not target_id.strip():
        return {"ok": False, "error": "target_id 不能为空。"}
    if reason is None:
        reason_clean = ""
    elif isinstance(reason, str):
        reason_clean = reason.strip()
    else:
        reason_clean = str(reason).strip()

    t_type = target_type.strip().lower()
    t_id = target_id.strip().upper()
    if t_type not in ("bug", "agent"):
        return {"ok": False, "error": f"target_type 必须是 bug 或 agent，收到: {target_type}"}

    with _state_lock():
        root = _load_root_state()
        key, ws = _get_ws_state(root, workspace)
        tracked = ws.get("current_cross_fix_bug_ids")
        tracked_set = (
            {str(i).strip().upper() for i in tracked if isinstance(i, str) and i.strip()}
            if isinstance(tracked, list)
            else set()
        )

        if t_type == "bug":
            bug = next((b for b in ws["bugs"] if b["id"] == t_id), None)
            if not bug:
                return {"ok": False, "error": f"找不到 Bug {t_id}。"}
            is_active_r2 = ws.get("phase") == "ROUND2_CROSS_FIXING" and (
                t_id in tracked_set or bug.get("status") in ("IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED")
            )
            if clear:
                _clear_bug_shazi_penalty(ws, bug)
                if bug["status"] == "SHAZI_FAILED":
                    bug["status"] = "IN_CROSS_FIX" if is_active_r2 else "OPEN"
                msg = f"已清除 {t_id} 上的【啥子】标记（当前状态：{bug['status']}）。"
            else:
                why = reason_clean or "铲屎官手动贴上【啥子】标记，需重新审查或修复"
                # Attribute responsibility accurately:
                # - Bugs with fix_attempts or already/actively in cross-fix belong to assigned_fixer.
                # - Otherwise preserve existing shazi_penalized_agent if already SHAZI_FAILED, else attribute to finder.
                if (
                    bug.get("fix_attempts")
                    or bug.get("status") in ("IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED")
                    or t_id in tracked_set
                ):
                    responsible = (
                        bug.get("assigned_fixer")
                        if bug.get("assigned_fixer") in VALID_AGENTS
                        else bug.get("finder")
                    )
                elif bug.get("status") == "SHAZI_FAILED" and bug.get("shazi_penalized_agent") in VALID_AGENTS:
                    responsible = bug.get("shazi_penalized_agent")
                else:
                    responsible = bug.get("finder")

                if responsible in VALID_AGENTS:
                    badge = f"【啥子】{t_id}：{why}"
                    _apply_bug_shazi_penalty(ws, bug, responsible, badge)
                bug["shazi_tag"] = True
                bug.setdefault("shazi_reasons", []).append(f"[{_now_iso()}] {why}")
                if is_active_r2:
                    if bug.get("status") not in ("IN_CROSS_FIX", "PENDING_JUDGE", "FIX_FAILED"):
                        bug["status"] = "IN_CROSS_FIX"
                    msg = (
                        f"已给 {t_id} 贴上【啥子】标记！该 Bug 为第2局进行中任务，"
                        f"保留当前状态 {bug['status']} 以继续交叉修/验并完整纳入二胜裁决与统计。"
                    )
                else:
                    bug["status"] = "SHAZI_FAILED"
                    msg = f"已给 {t_id} 贴上【啥子】标记！状态已重置为 SHAZI_FAILED，可再次发起复审或重修。"
            ws["updated_at"] = _now_iso()
            _save_root_state(root)
            return {"ok": True, "workspace": key, "bug": bug, "message": msg}

        if t_id not in VALID_AGENTS:
            return {"ok": False, "error": f"agent target_id 必须是 A 或 B，收到: {target_id}"}

        agent = ws["agents"][t_id]
        if clear:
            agent["shazi_count"] = 0
            agent["shazi_badges"] = []
            for bug in ws["bugs"]:
                if bug.get("shazi_penalized_agent") == t_id or (
                    bug.get("shazi_tag")
                    and not bug.get("shazi_penalized_agent")
                    and bug.get("assigned_fixer") == t_id
                ):
                    bug["shazi_tag"] = False
                    bug.pop("shazi_penalized_agent", None)
                    bug.pop("shazi_badge", None)
                    if bug.get("status") == "SHAZI_FAILED":
                        if ws.get("phase") == "ROUND2_CROSS_FIXING" and bug.get("id") in tracked_set:
                            bug["status"] = "IN_CROSS_FIX"
                        else:
                            bug["status"] = "OPEN"
            msg = f"已清空 {agent['name']} 的全部【啥子】标记！"
        else:
            why = reason_clean or "在哈气审查中犯蠢，荣获【啥子】称号"
            agent["shazi_count"] += 1
            agent["shazi_badges"].append(f"【啥子】{why}")
            msg = f"已给 {agent['name']} 贴上【啥子】标记（累计 {agent['shazi_count']} 次）：{why}"
        ws["updated_at"] = _now_iso()
        _save_root_state(root)
        return {"ok": True, "workspace": key, "agent": agent, "message": msg}


def cmd_reset(workspace: str | None = None, force: bool = False) -> dict[str, Any]:
    if workspace is not None and not isinstance(workspace, str):
        return {"ok": False, "error": "workspace 必须是字符串。"}
    with _state_lock():
        root = _load_root_state()
        norm_key = _normalize_workspace_key(workspace)
        workspaces = root.get("workspaces", {})
        key = _find_workspace_key(workspaces, norm_key) if isinstance(workspaces, dict) else norm_key
        if not isinstance(workspaces, dict) or key not in workspaces or not isinstance(workspaces[key], dict):
            return {
                "ok": False,
                "workspace": norm_key,
                "error": f"工作区 '{norm_key}' 不存在，未执行重置（不会创建空条目）。",
            }
        ws = workspaces[key]
        phase = ws.get("phase", "IDLE")
        if phase in ("ROUND1_HUNTING", "ROUND2_CROSS_FIXING") and not force:
            return {
                "ok": False,
                "workspace": key,
                "phase": phase,
                "error": f"当前赛程处于 {phase} 进行中，已拦截重置以防误删当前进度与历史记录；如确需重置请传入 force=True / --force。",
            }
        try:
            clean_wt = _cleanup_round2_worktrees(ws, force=True)
        except Exception as exc:  # pragma: no cover - defensive cleanup on reset
            clean_wt = {"cleaned": False, "errors": [str(exc)]}
        prev_a = ws.get("agents", {}).get("A", {}).get("conv_id")
        prev_b = ws.get("agents", {}).get("B", {}).get("conv_id")
        root["workspaces"][key] = _default_workspace_state()
        _save_root_state(root)
        return {
            "ok": True,
            "workspace": key,
            "previous_conv_ids": {"A": prev_a, "B": prev_b},
            "cleaned_worktrees": clean_wt,
            "phase": "IDLE",
            "message": "哈基米通道状态、战绩、Bug 列表、Git worktree 与长期子代理上下文绑定已全部重置。",
        }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _ci_upper_choice(valid: tuple[str, ...]):
    def _convert(value: str) -> str:
        norm = value.strip().upper()
        if norm not in valid:
            raise argparse.ArgumentTypeError(
                f"invalid choice: {value!r} (choose from {', '.join(valid)})"
            )
        return norm

    return _convert


def _ci_lower_choice(valid: tuple[str, ...]):
    def _convert(value: str) -> str:
        norm = value.strip().lower()
        if norm not in valid:
            raise argparse.ArgumentTypeError(
                f"invalid choice: {value!r} (choose from {', '.join(valid)})"
            )
        return norm

    return _convert


def _opt_bool_choice(value: str) -> bool:
    norm = value.strip().lower()
    if norm in ("true", "1", "yes"):
        return True
    if norm in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean: {value!r} (choose true/false)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hakimi Hiss Duel interaction channel CLI")
    parser.add_argument("--workspace", default=None, help="Optional workspace key/path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show current arena state and scoreboard")

    p_bind = sub.add_parser("bind-agents", help="Bind persistent subagent conversationIds")
    p_bind.add_argument("--agent-a", default=None)
    p_bind.add_argument("--agent-b", default=None)

    p_start = sub.add_parser("start-hunt", help="Start Round 1 bug hunt")
    p_start.add_argument("--scope", type=_ci_lower_choice(("project", "files")), choices=("project", "files"), default="project")
    p_start.add_argument("--files", default="")
    p_start.add_argument("--keep-bugs", action="store_true")
    p_start.add_argument("--force", action="store_true", help="Force restart when an active round is already in progress")

    p_rep = sub.add_parser("report-bug", help="Report a newly found bug (deduplicated)")
    p_rep.add_argument("--reporter", required=True, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_rep.add_argument("--file", required=True)
    p_rep.add_argument("--line-start", required=True, type=int)
    p_rep.add_argument("--line-end", type=int, default=None)
    p_rep.add_argument("--severity", default="MEDIUM", type=_ci_upper_choice(VALID_SEVERITIES), choices=VALID_SEVERITIES)
    p_rep.add_argument("--category", default="logic")
    p_rep.add_argument("--title", required=True)
    p_rep.add_argument("--description", required=True)

    p_list = sub.add_parser("list-bugs", help="List bugs in channel")
    p_list.add_argument("--finder", default=None, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_list.add_argument("--assigned-to", default=None, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_list.add_argument("--status", default=None, type=_ci_upper_choice(VALID_BUG_STATUSES), choices=VALID_BUG_STATUSES)

    sub.add_parser("settle-round1", help="Tally Round 1, crown 一胜, and suspend for 铲屎官")

    p_cross = sub.add_parser("start-cross-fix", help="Start Round 2 cross-fix duel")
    p_cross.add_argument("--only-shazi", action="store_true")
    p_cross.add_argument(
        "--mode",
        default="auto",
        type=_ci_lower_choice(VALID_CROSS_FIX_MODES),
        choices=VALID_CROSS_FIX_MODES,
        help="Execution mode: auto (git worktree -> wave fallback), worktree, or wave",
    )

    p_claim = sub.add_parser("claim-files", help="Acquire or release cooperative file locks in Round 2")
    p_claim.add_argument("--claimer", required=True, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_claim.add_argument("--files", required=True)
    p_claim.add_argument("--release", action="store_true")
    p_claim.add_argument("--note", default="")

    p_fix = sub.add_parser("report-fix", help="Submit cross-fix result")
    p_fix.add_argument("--fixer", required=True, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_fix.add_argument("--bug-id", required=True)
    p_fix.add_argument("--status", required=True, type=_ci_upper_choice(VALID_FIX_STATUSES), choices=VALID_FIX_STATUSES)
    p_fix.add_argument("--summary", required=True)
    p_fix.add_argument("--files-changed", default="")
    p_fix.add_argument("--verify-cmd", default=None)
    p_fix.add_argument("--verify-passed", default=None, type=_opt_bool_choice)

    p_verify = sub.add_parser("report-verify", help="Cross-verify opponent's fix (original finder only)")
    p_verify.add_argument("--verifier", required=True, type=_ci_upper_choice(VALID_AGENTS), choices=VALID_AGENTS)
    p_verify.add_argument("--bug-id", required=True)
    p_verify.add_argument("--verdict", required=True, type=_ci_upper_choice(VALID_VERIFY_VERDICTS), choices=VALID_VERIFY_VERDICTS)
    p_verify.add_argument("--note", default="")

    p_int = sub.add_parser("integrate-worktrees", help="Inspect, merge, or clean up Round 2 Git worktrees")
    p_int.add_argument(
        "--action",
        default="status",
        type=_ci_lower_choice(VALID_INTEGRATE_ACTIONS),
        choices=VALID_INTEGRATE_ACTIONS,
    )
    p_int.add_argument("--no-cleanup", action="store_true")
    p_int.add_argument("--keep-conflict", action="store_true")

    p_judge = sub.add_parser("judge-round2", help="Judge Round 2 fixes, crown 二胜, tag 啥子")
    p_judge.add_argument("--verdicts", required=True, help="JSON array of {bug_id, verdict, comment}")

    p_shazi = sub.add_parser("mark-shazi", help="Manually add or clear 【啥子】 tag")
    p_shazi.add_argument("--target-type", required=True, type=_ci_lower_choice(("bug", "agent")), choices=("bug", "agent"))
    p_shazi.add_argument("--target-id", required=True)
    p_shazi.add_argument("--reason", default="")
    p_shazi.add_argument("--clear", action="store_true")

    p_reset = sub.add_parser("reset", help="Reset channel state and persistent agent bindings")
    p_reset.add_argument("--force", action="store_true", help="Force reset even while a round is active")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            res = cmd_status(workspace=args.workspace)
        elif args.command == "bind-agents":
            res = cmd_bind_agents(workspace=args.workspace, agent_a=args.agent_a, agent_b=args.agent_b)
        elif args.command == "start-hunt":
            res = cmd_start_hunt(workspace=args.workspace, scope=args.scope, files=args.files, keep_bugs=args.keep_bugs, force=args.force)
        elif args.command == "report-bug":
            res = cmd_report_bug(
                workspace=args.workspace,
                reporter=args.reporter,
                file=args.file,
                line_start=args.line_start,
                line_end=args.line_end,
                severity=args.severity,
                category=args.category,
                title=args.title,
                description=args.description,
            )
        elif args.command == "list-bugs":
            res = cmd_list_bugs(
                workspace=args.workspace,
                finder=args.finder,
                assigned_to=args.assigned_to,
                status=args.status,
            )
        elif args.command == "settle-round1":
            res = cmd_settle_round1(workspace=args.workspace)
        elif args.command == "start-cross-fix":
            res = cmd_start_cross_fix(workspace=args.workspace, only_shazi=args.only_shazi, mode=args.mode)
        elif args.command == "claim-files":
            res = cmd_claim_files(
                workspace=args.workspace,
                claimer=args.claimer,
                files=args.files,
                release=args.release,
                note=args.note,
            )
        elif args.command == "report-fix":
            res = cmd_report_fix(
                workspace=args.workspace,
                fixer=args.fixer,
                bug_id=args.bug_id,
                status=args.status,
                summary=args.summary,
                files_changed=args.files_changed,
                verify_cmd=args.verify_cmd,
                verify_passed=args.verify_passed,
            )
        elif args.command == "report-verify":
            res = cmd_report_verify(
                workspace=args.workspace,
                verifier=args.verifier,
                bug_id=args.bug_id,
                verdict=args.verdict,
                note=args.note,
            )
        elif args.command == "integrate-worktrees":
            res = cmd_integrate_worktrees(
                action=args.action,
                workspace=args.workspace,
                cleanup=not args.no_cleanup,
                abort_on_conflict=not args.keep_conflict,
            )
        elif args.command == "judge-round2":
            res = cmd_judge_round2(verdicts=args.verdicts, workspace=args.workspace)
        elif args.command == "mark-shazi":
            res = cmd_mark_shazi(
                workspace=args.workspace,
                target_type=args.target_type,
                target_id=args.target_id,
                reason=args.reason,
                clear=args.clear,
            )
        elif args.command == "reset":
            res = cmd_reset(workspace=args.workspace, force=args.force)
        else:
            res = {"ok": False, "error": f"Unknown command: {args.command}"}
    except Exception as exc:
        res = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("ok") is False or res.get("accepted") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
