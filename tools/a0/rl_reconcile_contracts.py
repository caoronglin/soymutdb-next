"""静态、fail-closed 的 API/client/Web/Admin/Worker 契约映射器。

本模块只读取调用方明确提供的 project root 下的源码文本；不导入应用、不读取环境、
不连接数据库、不启动服务，也不写入 docs/ 或 artifacts/。输出只保留相对路径、
短摘要和 canonical digest，供后续报告渲染使用。
"""

from __future__ import annotations

import argparse as rl_argparse
import ast as rl_ast
import hashlib as rl_hashlib
import json as rl_json
import re as rl_re
from collections.abc import Iterable as rl_Iterable
from pathlib import Path as rl_Path
from typing import Any as rl_Any

rl_SCHEMA_VERSION = "a0.contract-reconciliation.v1"
rl_STATUS_BLOCKED = "BLOCKED"
rl_STATUS_OBSERVED = "observed"
rl_STATUS_MISSING = "missing"
rl_STATUS_UNRESOLVED = "unresolved"
rl_SUPPORTED_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head"}
)
rl_SENSITIVE_RE = rl_re.compile(
    r"(?i)(?:https?://\S+|\b(?:password|passwd|secret|token|api[_-]?key|authorization)\b\s*[=:]\s*[^\s,;]+)"
)
rl_ROUTE_DECORATOR_RE = rl_re.compile(
    r"@router\.(?P<method>get|post|put|patch|delete|options|head)\(\s*(?P<path>[\"'][^\"']*[\"'])",
    rl_re.IGNORECASE,
)
rl_ROUTER_PREFIX_RE = rl_re.compile(
    r"\brouter\s*=\s*APIRouter\([^\n]*?prefix\s*=\s*([\"'][^\"']*[\"'])"
)
rl_CLIENT_CALL_RE = rl_re.compile(
    r"\b(?:http|api|client)\.(?P<method>get|post|put|patch|delete)\(\s*(?P<path>[\"'`][^\"'`]*[\"'`])",
    rl_re.IGNORECASE,
)
rl_WORKER_TASK_RE = rl_re.compile(
    r"(?:@(?:\w+\.)?task\(|name\s*=\s*)[^\n]*?name\s*=\s*[\"'](?P<name>[^\"']+)[\"']",
    rl_re.IGNORECASE,
)
rl_WORKER_DECORATOR_RE = rl_re.compile(
    r"@(?:\w+\.)?task\([^\n]*?name\s*=\s*[\"'](?P<name>[^\"']+)[\"']",
    rl_re.IGNORECASE,
)
rl_SEND_TASK_RE = rl_re.compile(r"\bsend_task\(\s*[\"'](?P<name>[^\"']+)[\"']")
rl_DEFAULT_IGNORES = frozenset(
    {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv"}
)


def rl_sha256_json(rl_value: rl_Any) -> str:
    """Digest canonical JSON without retaining source text."""

    rl_payload = rl_json.dumps(
        rl_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{rl_hashlib.sha256(rl_payload).hexdigest()}"


def rl_safe_path(rl_path: rl_Path, rl_root: rl_Path) -> str:
    try:
        return rl_path.resolve().relative_to(rl_root.resolve()).as_posix()
    except ValueError:
        return "<outside-project>"


def rl_redact_summary(rl_value: str) -> str:
    """Keep summaries short and never emit URL/credential-shaped source text."""

    rl_redacted = rl_SENSITIVE_RE.sub("<redacted>", rl_value)
    rl_redacted = " ".join(rl_redacted.split())
    return rl_redacted[:180]


def rl_source_record(rl_path: str, rl_text: str, rl_summary: str) -> dict[str, str]:
    return {
        "rl_path": rl_path,
        "rl_summary": rl_redact_summary(rl_summary),
        "rl_digest": f"sha256:{rl_hashlib.sha256(rl_text.encode('utf-8')).hexdigest()}",
    }


def rl_empty_fact(rl_status: str, rl_summary: str) -> dict[str, str]:
    return {"rl_status": rl_status, "rl_summary": rl_summary}


def rl_normalize_path(rl_path: str) -> str:
    rl_normalized = rl_path.replace("\\", "/")
    if not rl_normalized.startswith("/"):
        return rl_normalized
    return "<absolute-path>"


def rl_join_route(rl_prefix: str, rl_path: str) -> str:
    rl_value = f"{rl_prefix.rstrip('/')}/{rl_path.lstrip('/')}"
    rl_value = rl_value.replace("//", "/")
    return rl_value if rl_value != "/" else ""


def rl_literal_string(rl_node: rl_ast.AST) -> str | None:
    if isinstance(rl_node, rl_ast.Constant) and isinstance(rl_node.value, str):
        return rl_node.value
    return None


def rl_parse_python_routes(
    rl_text: str, rl_path: str
) -> tuple[list[dict[str, rl_Any]], list[str]]:
    """Extract only literal router declarations/decorators from Python source."""

    rl_findings: list[str] = []
    try:
        rl_tree = rl_ast.parse(rl_text, filename=rl_path)
    except (SyntaxError, ValueError):
        return [], [f"rl_parse_blocked:{rl_path}"]

    rl_prefixes: dict[str, str] = {}
    rl_routes: list[dict[str, rl_Any]] = []
    for rl_node in rl_ast.walk(rl_tree):
        if isinstance(rl_node, rl_ast.Assign):
            if len(rl_node.targets) != 1 or not isinstance(
                rl_node.targets[0], rl_ast.Name
            ):
                continue
            rl_target = rl_node.targets[0].id
            if not isinstance(rl_node.value, rl_ast.Call):
                continue
            if (
                not isinstance(rl_node.value.func, rl_ast.Name)
                or rl_node.value.func.id != "APIRouter"
            ):
                continue
            rl_prefix = ""
            for rl_keyword in rl_node.value.keywords:
                if rl_keyword.arg == "prefix":
                    rl_prefix = rl_literal_string(rl_keyword.value) or ""
                    if rl_keyword.value is not None and not rl_prefix:
                        rl_findings.append(f"rl_unresolved_router_prefix:{rl_path}")
            rl_prefixes[rl_target] = rl_prefix

    # 只为最小静态 fixture 和无 prefix 的 root router 保留 literal AST 规则；
    # 无法证明 prefix 时不把相对路径猜成完整 API route。
    if not rl_prefixes:
        for rl_node in rl_ast.walk(rl_tree):
            if not isinstance(rl_node, (rl_ast.FunctionDef, rl_ast.AsyncFunctionDef)):
                continue
            for rl_decorator in rl_node.decorator_list:
                if not isinstance(rl_decorator, rl_ast.Call) or not isinstance(
                    rl_decorator.func, rl_ast.Attribute
                ):
                    continue
                if (
                    not isinstance(rl_decorator.func.value, rl_ast.Name)
                    or rl_decorator.func.value.id != "router"
                ):
                    continue
                rl_method = rl_decorator.func.attr.lower()
                if rl_method not in rl_SUPPORTED_METHODS or not rl_decorator.args:
                    continue
                rl_route_path = rl_literal_string(rl_decorator.args[0])
                if rl_route_path is None:
                    rl_findings.append(
                        f"rl_unresolved_route_path:{rl_path}:{rl_node.name}"
                    )
                    continue
                rl_routes.append(
                    {
                        "rl_method": rl_method.upper(),
                        "rl_route": rl_route_path or "",
                        "rl_source": rl_path,
                        "rl_function": rl_node.name,
                        "rl_authorization": "unverified",
                        "rl_summary": (
                            f"{rl_method.upper()} {rl_route_path or '/'} "
                            f"({rl_node.name})"
                        ),
                    }
                )
        if rl_routes:
            return rl_routes, rl_findings

    for rl_node in rl_ast.walk(rl_tree):
        if not isinstance(rl_node, (rl_ast.FunctionDef, rl_ast.AsyncFunctionDef)):
            continue
        for rl_decorator in rl_node.decorator_list:
            if not isinstance(rl_decorator, rl_ast.Call) or not isinstance(
                rl_decorator.func, rl_ast.Attribute
            ):
                continue
            if not isinstance(rl_decorator.func.value, rl_ast.Name):
                continue
            if rl_decorator.func.value.id not in rl_prefixes:
                continue
            rl_method = rl_decorator.func.attr.lower()
            if rl_method not in rl_SUPPORTED_METHODS:
                continue
            if not rl_decorator.args:
                rl_findings.append(f"rl_unresolved_route_path:{rl_path}:{rl_node.name}")
                continue
            rl_route_path = rl_literal_string(rl_decorator.args[0])
            if rl_route_path is None:
                rl_findings.append(f"rl_unresolved_route_path:{rl_path}:{rl_node.name}")
                continue
            rl_route = rl_join_route(
                rl_prefixes[rl_decorator.func.value.id], rl_route_path
            )
            rl_authorization = "unverified"
            rl_decorator_text = rl_ast.get_source_segment(rl_text, rl_decorator) or ""
            rl_function_text = rl_ast.get_source_segment(rl_text, rl_node) or ""
            if (
                "require_role" in rl_decorator_text
                or "_require_admin" in rl_function_text
            ):
                rl_authorization = "observed_guard_reference"
            rl_routes.append(
                {
                    "rl_method": rl_method.upper(),
                    "rl_route": rl_route,
                    "rl_source": rl_path,
                    "rl_function": rl_node.name,
                    "rl_authorization": rl_authorization,
                    "rl_summary": f"{rl_method.upper()} {rl_route} ({rl_node.name})",
                }
            )
    return rl_routes, rl_findings


def rl_parse_client_calls(
    rl_text: str, rl_path: str
) -> tuple[list[dict[str, str]], list[str]]:
    rl_calls: list[dict[str, str]] = []
    rl_findings: list[str] = []
    for rl_match in rl_CLIENT_CALL_RE.finditer(rl_text):
        rl_raw_path = rl_match.group("path")[1:-1]
        if "${" in rl_raw_path or "{" in rl_raw_path:
            # 为什么：动态 URL 只能证明存在调用表达式，不能猜测其具体 route 关系。
            rl_findings.append(f"rl_unresolved_dynamic_client_path:{rl_path}")
            rl_path_value = "<dynamic-path>"
        else:
            rl_path_value = rl_raw_path
        rl_calls.append(
            {
                "rl_method": rl_match.group("method").upper(),
                "rl_route": rl_path_value,
                "rl_source": rl_path,
                "rl_summary": f"{rl_match.group('method').upper()} {rl_path_value}",
            }
        )
    return rl_calls, rl_findings


def rl_parse_worker_tasks(
    rl_text: str, rl_path: str
) -> tuple[list[dict[str, str]], list[str]]:
    rl_tasks: list[dict[str, str]] = []
    rl_findings: list[str] = []
    rl_seen: set[str] = set()
    for rl_match in rl_WORKER_DECORATOR_RE.finditer(rl_text):
        rl_name = rl_match.group("name")
        if rl_name in rl_seen:
            continue
        rl_seen.add(rl_name)
        rl_tasks.append(
            {
                "rl_task_name": rl_name,
                "rl_source": rl_path,
                "rl_summary": f"registered {rl_name}",
            }
        )
    if "@" in rl_text and "task" in rl_text and not rl_tasks:
        rl_findings.append(f"rl_unresolved_worker_registry:{rl_path}")
    return rl_tasks, rl_findings


def rl_iter_source_files(rl_root: rl_Path) -> rl_Iterable[rl_Path]:
    for rl_path in sorted(rl_root.rglob("*")):
        if not rl_path.is_file() or any(
            rl_part in rl_DEFAULT_IGNORES for rl_part in rl_path.parts
        ):
            continue
        if rl_path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            yield rl_path


def rl_reconcile_contracts(rl_project_root: str | rl_Path) -> dict[str, rl_Any]:
    """Return deterministic path/summary/digest-only contract facts."""

    rl_root = rl_Path(rl_project_root).expanduser().resolve()
    rl_routes: list[dict[str, rl_Any]] = []
    rl_clients: list[dict[str, str]] = []
    rl_workers: list[dict[str, str]] = []
    rl_unresolved: set[str] = set()
    rl_sources: list[dict[str, str]] = []
    rl_source_counts = {"api": 0, "client": 0, "web": 0, "admin": 0, "worker": 0}

    if not rl_root.exists() or not rl_root.is_dir():
        rl_unresolved.add("rl_project_root_unavailable")
    else:
        for rl_path in rl_iter_source_files(rl_root):
            rl_relative = rl_safe_path(rl_path, rl_root)
            try:
                rl_text = rl_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                rl_unresolved.add(f"rl_unreadable_source:{rl_relative}")
                continue
            rl_source_kind = (
                "api"
                if rl_relative.startswith("apps/api/") and rl_path.suffix == ".py"
                else "worker"
                if rl_relative.startswith("apps/worker/") and rl_path.suffix == ".py"
                else "client"
                if rl_relative.startswith("packages/api-client/")
                else "web"
                if rl_relative.startswith("apps/web/")
                else "admin"
                if rl_relative.startswith("apps/admin/")
                else None
            )
            if rl_source_kind is None:
                continue
            rl_source_counts[rl_source_kind] += 1
            rl_sources.append(
                rl_source_record(rl_relative, rl_text, f"{rl_source_kind} source")
            )
            if rl_source_kind == "api":
                rl_found_routes, rl_findings = rl_parse_python_routes(
                    rl_text, rl_relative
                )
                rl_routes.extend(rl_found_routes)
                rl_unresolved.update(rl_findings)
                for rl_send_match in rl_SEND_TASK_RE.finditer(rl_text):
                    rl_workers.append(
                        {
                            "rl_task_name": rl_send_match.group("name"),
                            "rl_source": rl_relative,
                            "rl_summary": f"API dispatch {rl_send_match.group('name')}",
                        }
                    )
            elif rl_source_kind == "worker":
                rl_found_workers, rl_findings = rl_parse_worker_tasks(
                    rl_text, rl_relative
                )
                rl_workers.extend(rl_found_workers)
                rl_unresolved.update(rl_findings)
            else:
                rl_found_clients, rl_findings = rl_parse_client_calls(
                    rl_text, rl_relative
                )
                rl_clients.extend(rl_found_clients)
                rl_unresolved.update(rl_findings)

    rl_route_keys = {(rl_row["rl_method"], rl_row["rl_route"]) for rl_row in rl_routes}
    rl_rows: list[dict[str, rl_Any]] = []
    rl_required_relations = (
        ("search", "GET", "/api/v1/search"),
        ("search_suggest", "GET", "/api/v1/search/suggest"),
        ("releases", "GET", "/api/v1/releases"),
        ("content", "GET", "/api/v1/content/news"),
        ("admin_imports", "GET", "/api/v1/admin/imports"),
        ("admin_static_build", "POST", "/api/v1/admin/build-static"),
        ("health", "GET", "/health"),
        ("genes", "GET", "/api/v1/genes"),
        ("variants", "GET", "/api/v1/variants"),
        ("mutants", "GET", "/api/v1/mutants"),
    )
    for rl_relation, rl_method, rl_route in rl_required_relations:
        rl_api_match = rl_method, rl_route
        rl_route_observed = rl_api_match in rl_route_keys
        rl_client_match = next(
            (
                rl_row
                for rl_row in rl_clients
                if rl_row["rl_method"] == rl_method
                and rl_row["rl_route"] == rl_route.removeprefix("/api/v1")
            ),
            None,
        )
        rl_row_unresolved: list[str] = []
        if not rl_route_observed:
            rl_row_unresolved.append("rl_missing_route")
        if rl_client_match is None:
            rl_row_unresolved.append("rl_missing_client_consumer")
        # 为什么：UI affordance、client function 或 route existence 都不是 capability proof。
        rl_row_unresolved.append("rl_authorization_unverified")
        rl_rows.append(
            {
                "rl_relation": rl_relation,
                "rl_route": (
                    {
                        "rl_status": rl_STATUS_OBSERVED,
                        "rl_method": rl_method,
                        "rl_path": rl_route,
                    }
                    if rl_route_observed
                    else rl_empty_fact(
                        rl_STATUS_MISSING, "route 未在静态 API source 中证明"
                    )
                ),
                "rl_client": (
                    rl_source_record(
                        rl_client_match["rl_source"],
                        rl_client_match["rl_summary"],
                        rl_client_match["rl_summary"],
                    )
                    | {
                        "rl_status": rl_STATUS_OBSERVED,
                        "rl_method": rl_method,
                        "rl_path": rl_client_match["rl_route"],
                    }
                    if rl_client_match
                    else rl_empty_fact(
                        rl_STATUS_MISSING, "client consumer 未被静态 source 证明"
                    )
                ),
                "rl_admin": rl_empty_fact(
                    rl_STATUS_UNRESOLVED,
                    "Admin call-site relationship requires exact route evidence",
                ),
                "rl_worker": rl_empty_fact(
                    rl_STATUS_UNRESOLVED,
                    "Worker relationship requires exact task registry evidence",
                ),
                "rl_authorization": {
                    "rl_status": "unverified",
                    "rl_summary": "静态 source 未提供可独立验证的 capability proof",
                },
                "rl_unresolved": sorted(rl_row_unresolved),
            }
        )

    rl_task_names = {
        rl_task["rl_task_name"] for rl_task in rl_workers if "rl_task_name" in rl_task
    }
    rl_static_task = "soymutdb_worker.tasks.static_pages.build_static_pages"
    if (
        any(rl_static_task in rl_worker["rl_summary"] for rl_worker in rl_workers)
        and rl_static_task not in rl_task_names
    ):
        rl_unresolved.add("rl_static_dispatch_task_name_mismatch")
    if not rl_task_names:
        rl_unresolved.add("rl_worker_registry_unverified")
    if not rl_routes:
        rl_unresolved.add("rl_api_routes_unverified")
    if not rl_clients:
        rl_unresolved.add("rl_client_consumers_unverified")
    if not rl_source_counts["admin"]:
        rl_unresolved.add("rl_admin_consumers_unverified")

    rl_sources.sort(key=lambda rl_source: rl_source["rl_path"])
    rl_rows.sort(key=lambda rl_row: rl_row["rl_relation"])
    rl_unresolved_list = sorted(
        rl_unresolved
        | {rl_code for rl_row in rl_rows for rl_code in rl_row["rl_unresolved"]}
    )
    rl_report: dict[str, rl_Any] = {
        "rl_schema_version": rl_SCHEMA_VERSION,
        "rl_status": rl_STATUS_BLOCKED if rl_unresolved_list else "PASS",
        "rl_sources": rl_sources,
        "rl_source_counts": rl_source_counts,
        "rl_rows": rl_rows,
        "rl_worker_tasks": sorted(
            rl_workers,
            key=lambda rl_worker: (
                rl_worker.get("rl_task_name", ""),
                rl_worker["rl_source"],
            ),
        ),
        "rl_unresolved": rl_unresolved_list,
        "rl_runtime_live_evidence": {
            "rl_status": "BLOCKED",
            "rl_summary": "未连接数据库、未启动服务，runtime/live evidence 仍为前置阻断。",
        },
    }
    rl_report["rl_report_digest"] = rl_sha256_json(rl_report)
    return rl_report


def rl_main(rl_argv: list[str] | None = None) -> int:
    rl_parser = rl_argparse.ArgumentParser(description=__doc__)
    rl_parser.add_argument("--project-root", required=True)
    rl_parser.add_argument("--output")
    rl_args = rl_parser.parse_args(rl_argv)
    rl_report = rl_reconcile_contracts(rl_args.project_root)
    rl_payload = (
        rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    if rl_args.output:
        rl_output = rl_Path(rl_args.output)
        rl_output.parent.mkdir(parents=True, exist_ok=True)
        rl_output.write_text(rl_payload, encoding="utf-8")
    else:
        print(rl_payload, end="")
    return 0 if rl_report["rl_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(rl_main())


__all__ = ["rl_main", "rl_reconcile_contracts", "rl_sha256_json"]
