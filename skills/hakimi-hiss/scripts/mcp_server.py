#!/usr/bin/env python3
"""Zero-dependency MCP Stdio server for Hakimi Hiss Duel (哈基米哈气审查)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import hakimi_channel as ch  # noqa: E402

SERVER_INFO = {
    "name": "hakimi-hiss-channel",
    "version": "1.0.0",
}
PROTOCOL_VERSION = "2024-11-05"


def _tool_def(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool_def(
        "hakimi_status",
        "查询哈基米哈气审查通道的当前阶段、双方长期子代理 conversationId、Bug 清单与一胜/二胜/啥子战绩。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识（默认 default）"},
        },
    ),
    _tool_def(
        "hakimi_bind_agents",
        "持久化绑定哈基米A与哈基米B的长期子代理 conversationId，后续回合可继续唤醒保留上下文。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "agent_a": {"type": "string", "minLength": 1, "description": "哈基米A（橘座）的 conversationId"},
            "agent_b": {"type": "string", "minLength": 1, "description": "哈基米B（狸花）的 conversationId"},
        },
    ),
    _tool_def(
        "hakimi_start_hunt",
        "开启第一局【哈气找Bug赛（一胜）】。默认审查整个项目；若指定了 @ 文件列表则自动限定只审指定文件。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "scope": {"type": "string", "enum": ["project", "files"], "description": "审查范围：project（默认全项目）或 files（仅限指定文件）"},
            "files": {"type": "array", "items": {"type": "string", "minLength": 1}, "description": "当用户 @ 了特定文件时传入文件路径列表"},
            "keep_bugs": {"type": "boolean", "description": "是否保留已有 Bug（用于复审或追加审查）"},
            "force": {"type": "boolean", "description": "若当前已有进行中轮次，是否强制重开第一局"},
        },
    ),
    _tool_def(
        "hakimi_report_bug",
        "子代理A或B向插件通道填报发现的 Bug。内置范围校验与实时防重（同一文件重叠/相近行号或相似问题将被拒收）。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "reporter": {"type": "string", "enum": ["A", "B"], "description": "发现者：A 或 B"},
            "file": {"type": "string", "minLength": 1, "description": "Bug 所在文件路径"},
            "line_start": {"type": "integer", "minimum": 1, "description": "起始行号（>= 1）"},
            "line_end": {"type": "integer", "minimum": 1, "description": "结束行号（>= line_start）"},
            "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"], "description": "严重程度"},
            "category": {"type": "string", "minLength": 1, "description": "缺陷分类（如 logic/concurrency/security/boundary/resource）"},
            "title": {"type": "string", "minLength": 1, "description": "简短精准的 Bug 标题"},
            "description": {"type": "string", "minLength": 1, "description": "Bug 根因与复现/影响说明"},
        },
        required=["reporter", "file", "line_start", "title", "description"],
    ),
    _tool_def(
        "hakimi_list_bugs",
        "列出通道中已登记的 Bug，可用于查看对手已占坑的问题避免重复，或拉取自己被分配交叉修复的任务。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "finder": {"type": "string", "enum": ["A", "B"], "description": "按发现者过滤"},
            "assigned_to": {"type": "string", "enum": ["A", "B"], "description": "按交叉修复负责人过滤"},
            "status": {
                "type": "string",
                "enum": [
                    "OPEN",
                    "IN_CROSS_FIX",
                    "PENDING_JUDGE",
                    "FIXED_PERFECT",
                    "FIXED_PASS",
                    "FIX_FAILED",
                    "SHAZI_FAILED",
                ],
                "description": "按状态过滤（OPEN / IN_CROSS_FIX / PENDING_JUDGE / FIXED_PERFECT / FIXED_PASS / FIX_FAILED / SHAZI_FAILED）",
            },
        },
    ),
    _tool_def(
        "hakimi_settle_round1",
        "结算第一局找 Bug 战况，决出【一胜】得主，并将插件挂起、返回全部去重 Bug 给铲屎官。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
        },
    ),
    _tool_def(
        "hakimi_start_cross_fix",
        "开启第二局【交叉修Bug赛（二胜）】：分配 A 修 B 找到的 Bug，B 修 A 找到的 Bug。非 Git 目录默认自动 git init 并创建基线后开启双 worktree 真并行，否则自动降级为波次乒乓协同。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "only_shazi": {"type": "boolean", "description": "是否仅重修带【啥子】标记或修复失败的 Bug"},
            "mode": {
                "type": "string",
                "enum": ["auto", "worktree", "wave"],
                "description": "执行模式：auto（默认，若无 .git 则自动 git init 后开启双 worktree 真并行，否则优雅降级波次乒乓）/ worktree / wave",
            },
        },
    ),
    _tool_def(
        "hakimi_claim_files",
        "波次乒乓或交叉修复期间，用于申请或释放文件修改软锁（防止两只哈基米互相覆盖同一文件）。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "claimer": {"type": "string", "enum": ["A", "B"], "description": "申请/释放锁的子代理：A 或 B"},
            "files": {
                "anyOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "array", "items": {"type": "string", "minLength": 1}},
                ],
                "description": "待锁定或释放的文件路径（字符串或路径数组）",
            },
            "release": {"type": "boolean", "description": "为 true 时释放锁，默认 false 为申请锁定"},
            "note": {"type": "string", "description": "可选锁定备注"},
        },
        required=["claimer", "files"],
    ),
    _tool_def(
        "hakimi_report_fix",
        "子代理A或B在交叉修复后向通道回报修复结果（含可选自测验证命令与结果）。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "fixer": {"type": "string", "enum": ["A", "B"], "description": "修复者：A 或 B"},
            "bug_id": {"type": "string", "minLength": 1, "description": "Bug 编号（如 BUG-001）"},
            "status": {"type": "string", "enum": ["FIXED", "CANT_FIX"], "description": "修复状态"},
            "summary": {"type": "string", "minLength": 1, "description": "修复改动与验证摘要"},
            "files_changed": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string", "minLength": 1}},
                ],
                "description": "改动文件路径（支持单个/分隔符字符串或路径数组，worktree 绝对路径会自动归一化）",
            },
            "verify_cmd": {"type": "string", "description": "可选：自测/回归验证命令（如 pytest tests/test_x.py）"},
            "verify_passed": {"type": "boolean", "description": "可选：自测命令是否全部通过"},
        },
        required=["fixer", "bug_id", "status", "summary"],
    ),
    _tool_def(
        "hakimi_report_verify",
        "按需可选（互哈互验）：主 AI 或铲屎官主动判断有必要时指派原 Bug 发现者复验对手提交的修复，可放行（VERIFIED）或哈气打回重修（REJECT_WITH_HISS）；无需额外互验时可直接跳过。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "verifier": {"type": "string", "enum": ["A", "B"], "description": "复验者：必须是原 Bug 发现者 A 或 B"},
            "bug_id": {"type": "string", "minLength": 1, "description": "Bug 编号（如 BUG-001）"},
            "verdict": {
                "type": "string",
                "enum": ["VERIFIED", "REJECT_WITH_HISS"],
                "description": "复验结论：VERIFIED（确认修复）或 REJECT_WITH_HISS（哈气打回重修）",
            },
            "note": {"type": "string", "description": "复验说明（打回时建议写明未修复点或新回归问题）"},
        },
        required=["verifier", "bug_id", "verdict"],
    ),
    _tool_def(
        "hakimi_integrate_worktrees",
        "查看、合并或清理第2局隔离的 Git worktree 与临时分支（action: status / merge / cleanup）。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "action": {
                "type": "string",
                "enum": ["status", "merge", "cleanup"],
                "description": "操作类型：status（查看进度）、merge（自动提交并合回主仓库）、cleanup（清理 worktree 与分支）",
            },
            "cleanup": {"type": "boolean", "description": "action=merge 成功后是否自动清理临时 worktree 与分支，默认 true"},
            "abort_on_conflict": {"type": "boolean", "description": "合并冲突时是否原子回滚主仓库并保留双 worktree，默认 true"},
        },
    ),
    _tool_def(
        "hakimi_judge_round2",
        "铲屎官验收第二局交叉修复结果，按完美度打分决出【二胜】；评定为 FAILED 的修复自动贴上【啥子】标记。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "verdicts": {
                "type": "array",
                "minItems": 1,
                "description": "验收评判列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "bug_id": {"type": "string", "minLength": 1},
                        "verdict": {"type": "string", "enum": ["PERFECT", "PASS", "FAILED"]},
                        "comment": {"type": "string"},
                    },
                    "required": ["bug_id", "verdict"],
                },
            },
        },
        required=["verdicts"],
    ),
    _tool_def(
        "hakimi_mark_shazi",
        "手动给指定 Bug 或子代理（A/B）贴上或清除【啥子】标记；被标记的 Bug 状态重置为 SHAZI_FAILED 以便再次复审或重修。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "target_type": {"type": "string", "enum": ["bug", "agent"], "description": "标记对象类型"},
            "target_id": {"type": "string", "minLength": 1, "description": "Bug 编号（如 BUG-001）或代理编号（A / B）"},
            "reason": {"type": "string", "description": "贴上【啥子】标记的原因"},
            "clear": {"type": "boolean", "description": "设为 true 则清除【啥子】标记"},
        },
        required=["target_type", "target_id"],
    ),
    _tool_def(
        "hakimi_reset",
        "手动重置通道全部状态、战绩与长期子代理绑定（并返回原 conversationId 供铲屎官清理）。",
        {
            "workspace": {"type": "string", "minLength": 1, "description": "可选工作区标识"},
            "force": {"type": "boolean", "description": "若当前已有进行中轮次，是否强制重置工作区状态与子代理绑定（默认 false）"},
        },
    ),
]


_MAX_FRAME_BYTES = 16 * 1024 * 1024


class _FrameParseError(Exception):
    def __init__(self, message: str, framed: bool = False) -> None:
        super().__init__(message)
        self.framed = framed


def _require_params(args: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in args or args[key] is None]
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")


def _opt_str_or_none(args: dict[str, Any], key: str) -> str | None:
    if key not in args or args[key] is None:
        return None
    val = args[key]
    if not isinstance(val, str):
        raise ValueError(f"Parameter '{key}' must be a string")
    return val


def _opt_str_default(args: dict[str, Any], key: str, default: str) -> str:
    if key not in args or args[key] is None:
        return default
    val = args[key]
    if not isinstance(val, str):
        raise ValueError(f"Parameter '{key}' must be a string")
    return val


def _opt_bool(args: dict[str, Any], key: str, default: bool = False) -> bool:
    if key not in args or args[key] is None:
        return default
    val = args[key]
    if isinstance(val, bool):
        return val
    raise ValueError(f"Parameter '{key}' must be a boolean")


def _opt_bool_or_none(args: dict[str, Any], key: str) -> bool | None:
    if key not in args or args[key] is None:
        return None
    val = args[key]
    if isinstance(val, bool):
        return val
    raise ValueError(f"Parameter '{key}' must be a boolean")


def _call_start_hunt(a: dict[str, Any]) -> dict[str, Any]:
    return ch.cmd_start_hunt(
        workspace=_opt_str_or_none(a, "workspace"),
        scope=_opt_str_default(a, "scope", "project"),
        files=a.get("files"),
        keep_bugs=_opt_bool(a, "keep_bugs", False),
        force=_opt_bool(a, "force", False),
    )


def _call_report_bug(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("reporter", "file", "line_start", "title", "description"))
    return ch.cmd_report_bug(
        workspace=_opt_str_or_none(a, "workspace"),
        reporter=a["reporter"],
        file=a["file"],
        line_start=a["line_start"],
        line_end=a.get("line_end"),
        severity=_opt_str_default(a, "severity", "MEDIUM"),
        category=_opt_str_default(a, "category", "logic"),
        title=a["title"],
        description=a["description"],
    )


def _call_start_cross_fix(a: dict[str, Any]) -> dict[str, Any]:
    return ch.cmd_start_cross_fix(
        workspace=_opt_str_or_none(a, "workspace"),
        only_shazi=_opt_bool(a, "only_shazi", False),
        mode=_opt_str_default(a, "mode", "auto"),
    )


def _call_claim_files(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("claimer", "files"))
    return ch.cmd_claim_files(
        workspace=_opt_str_or_none(a, "workspace"),
        claimer=a["claimer"],
        files=a["files"],
        release=_opt_bool(a, "release", False),
        note=_opt_str_default(a, "note", ""),
    )


def _call_report_fix(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("fixer", "bug_id", "status", "summary"))
    return ch.cmd_report_fix(
        workspace=_opt_str_or_none(a, "workspace"),
        fixer=a["fixer"],
        bug_id=a["bug_id"],
        status=a["status"],
        summary=a["summary"],
        files_changed=a.get("files_changed"),
        verify_cmd=_opt_str_or_none(a, "verify_cmd"),
        verify_passed=_opt_bool_or_none(a, "verify_passed"),
    )


def _call_report_verify(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("verifier", "bug_id", "verdict"))
    return ch.cmd_report_verify(
        workspace=_opt_str_or_none(a, "workspace"),
        verifier=a["verifier"],
        bug_id=a["bug_id"],
        verdict=a["verdict"],
        note=_opt_str_default(a, "note", ""),
    )


def _call_integrate_worktrees(a: dict[str, Any]) -> dict[str, Any]:
    return ch.cmd_integrate_worktrees(
        workspace=_opt_str_or_none(a, "workspace"),
        action=_opt_str_default(a, "action", "status"),
        cleanup=_opt_bool(a, "cleanup", True),
        abort_on_conflict=_opt_bool(a, "abort_on_conflict", True),
    )


def _call_judge_round2(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("verdicts",))
    return ch.cmd_judge_round2(
        workspace=_opt_str_or_none(a, "workspace"),
        verdicts=a["verdicts"],
    )


def _call_mark_shazi(a: dict[str, Any]) -> dict[str, Any]:
    _require_params(a, ("target_type", "target_id"))
    return ch.cmd_mark_shazi(
        workspace=_opt_str_or_none(a, "workspace"),
        target_type=a["target_type"],
        target_id=a["target_id"],
        reason=_opt_str_default(a, "reason", ""),
        clear=_opt_bool(a, "clear", False),
    )


DISPATCH: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "hakimi_status": lambda a: ch.cmd_status(workspace=_opt_str_or_none(a, "workspace")),
    "hakimi_bind_agents": lambda a: ch.cmd_bind_agents(
        workspace=_opt_str_or_none(a, "workspace"),
        agent_a=a.get("agent_a"),
        agent_b=a.get("agent_b"),
    ),
    "hakimi_start_hunt": _call_start_hunt,
    "hakimi_report_bug": _call_report_bug,
    "hakimi_list_bugs": lambda a: ch.cmd_list_bugs(
        workspace=_opt_str_or_none(a, "workspace"),
        finder=a.get("finder"),
        assigned_to=a.get("assigned_to"),
        status=a.get("status"),
    ),
    "hakimi_settle_round1": lambda a: ch.cmd_settle_round1(workspace=_opt_str_or_none(a, "workspace")),
    "hakimi_start_cross_fix": _call_start_cross_fix,
    "hakimi_claim_files": _call_claim_files,
    "hakimi_report_fix": _call_report_fix,
    "hakimi_report_verify": _call_report_verify,
    "hakimi_integrate_worktrees": _call_integrate_worktrees,
    "hakimi_judge_round2": _call_judge_round2,
    "hakimi_mark_shazi": _call_mark_shazi,
    "hakimi_reset": lambda a: ch.cmd_reset(
        workspace=_opt_str_or_none(a, "workspace"),
        force=_opt_bool(a, "force", False),
    ),
}


def _send_message(msg: Any, use_content_length: bool = False) -> None:
    encoded = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    out = sys.stdout.buffer
    if use_content_length:
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        out.write(header + encoded)
    else:
        out.write(encoded + b"\n")
    out.flush()


def _is_header_line(stripped: bytes) -> bool:
    if b":" not in stripped:
        return False
    name = stripped.split(b":", 1)[0]
    return bool(name) and all(48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122 or b == 45 for b in name)


def _read_exact(inp: Any, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = inp.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_message() -> tuple[Any | None, bool]:
    """Read one JSON-RPC message (supports both NDJSON and Content-Length framing)."""
    inp = sys.stdin.buffer
    while True:
        line = inp.readline()
        if not line:
            return None, False
        stripped = line.strip()
        if not stripped:
            continue
        if _is_header_line(stripped):
            headers: list[bytes] = [stripped]
            while True:
                hdr = inp.readline()
                if not hdr:
                    raise _FrameParseError("Unexpected EOF while reading frame headers", framed=True)
                hdr_stripped = hdr.strip()
                if not hdr_stripped:
                    break
                headers.append(hdr_stripped)

            content_length: int | None = None
            for hdr_line in headers:
                if b":" not in hdr_line:
                    raise _FrameParseError("Malformed frame header", framed=True)
                h_name, h_val = hdr_line.split(b":", 1)
                if h_name.strip().lower() == b"content-length":
                    raw_len = h_val.strip().decode("latin-1")
                    if not (raw_len.isascii() and raw_len.isdigit()):
                        raise _FrameParseError(f"Invalid Content-Length header: {raw_len!r}", framed=True)
                    parsed_len = int(raw_len)
                    if parsed_len <= 0 or parsed_len > _MAX_FRAME_BYTES:
                        raise _FrameParseError(f"Content-Length out of range: {parsed_len}", framed=True)
                    if content_length is not None and content_length != parsed_len:
                        raise _FrameParseError("Conflicting Content-Length headers", framed=True)
                    content_length = parsed_len

            if content_length is None:
                raise _FrameParseError("Missing Content-Length header", framed=True)

            body = _read_exact(inp, content_length)
            if len(body) < content_length:
                raise _FrameParseError(
                    f"Truncated message body: expected {content_length} bytes, got {len(body)}",
                    framed=True,
                )
            try:
                return json.loads(body.decode("utf-8")), True
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _FrameParseError(f"Parse error: {exc}", framed=True) from exc

        try:
            return json.loads(stripped.decode("utf-8")), False
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _FrameParseError(f"Parse error: {exc}", framed=False) from exc


def _handle_single_request(req: Any) -> dict[str, Any] | None:
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

    if "id" not in req:
        return None

    req_id = req["id"]
    if req_id is not None and (isinstance(req_id, bool) or not isinstance(req_id, (str, int, float))):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: invalid id"}}

    if "jsonrpc" in req and req["jsonrpc"] != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request: jsonrpc must be '2.0'"},
        }

    method = req.get("method")
    if not isinstance(method, str) or not method:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request: method must be a non-empty string"},
        }

    raw_params = req.get("params")
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Invalid params: 'params' must be an object"},
        }

    if method == "initialize":
        client_proto = params.get("protocolVersion") or PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: 'name' must be a non-empty string"},
            }
        raw_args = params.get("arguments")
        if raw_args is None:
            arguments: dict[str, Any] = {}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: 'arguments' must be an object"},
            }
        handler = DISPATCH.get(name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        try:
            payload = handler(arguments)
            is_err = (
                not isinstance(payload, dict)
                or payload.get("ok") is False
                or (payload.get("accepted") is False and payload.get("reason") != "DUPLICATE")
                or bool(payload.get("error"))
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": is_err,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _handle_request(req: Any) -> Any:
    if isinstance(req, list):
        if not req:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: empty batch"}}
        responses = [resp for item in req if (resp := _handle_single_request(item)) is not None]
        return responses if responses else None
    return _handle_single_request(req)


def main() -> int:
    while True:
        try:
            req, framed = _read_message()
        except _FrameParseError as exc:
            try:
                _send_message(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}},
                    use_content_length=exc.framed,
                )
            except (BrokenPipeError, OSError):
                break
            continue
        except (BrokenPipeError, OSError):
            break
        except Exception as exc:
            try:
                _send_message(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                    use_content_length=False,
                )
            except (BrokenPipeError, OSError):
                break
            continue
        if req is None:
            break
        try:
            resp = _handle_request(req)
        except Exception as exc:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": f"Internal error: {exc}"}}
        if resp is not None:
            try:
                _send_message(resp, use_content_length=framed)
            except (BrokenPipeError, OSError):
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
