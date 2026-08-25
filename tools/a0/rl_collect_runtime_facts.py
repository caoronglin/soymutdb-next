"""Collect redacted, deterministic runtime facts without importing the app.

The collector deliberately treats source files as text.  It does not import
application modules, resolve settings, connect to a service, or choose a
runtime target.  A report is therefore an observation of the supplied tree,
not runtime evidence or a migration decision.
"""

from __future__ import annotations

import argparse as rl_argparse
import ast as rl_ast
import hashlib as rl_hashlib
import json as rl_json
import re as rl_re
import subprocess as rl_subprocess
import tomllib as rl_tomllib
from collections.abc import Callable as rl_Callable
from collections.abc import Mapping as rl_Mapping
from collections.abc import Sequence as rl_Sequence
from pathlib import Path as rl_Path
from typing import Any as rl_Any

rl_SCHEMA_VERSION = "a0.runtime-facts.v1"
rl_RUNTIME_EVIDENCE_STATUS = "BLOCKED"
rl_PRODUCER = "rl_collect_runtime_facts"
rl_OWNER = "rl_runtime_evidence_owner"
rl_REVIEWER = "rl_runtime_reviewer"
rl_VERSION_FLAGS = frozenset({"--version", "-V", "version"})
rl_URL_RE = rl_re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+")
rl_SECRET_ASSIGNMENT_RE = rl_re.compile(
    r"(?i)(\b(?:[a-z0-9]+[_-])*(?:password|passwd|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?(?:token|key|secret)"
    r"|authorization|secret(?:[_-]?(?:key|value|token))?)\b[\"']?\s*[=:]\s*)"
    r"(?:[^\s,;]+|\"[^\"]*\"|'[^']*')"
)
rl_BEARER_RE = rl_re.compile(r"(?i)\bBearer\s+[^\s,;]+")
rl_BASIC_RE = rl_re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=_-]{8,}")
rl_NO_SCHEME_CREDENTIAL_RE = rl_re.compile(
    r"(?i)(?<![A-Za-z0-9._-])[A-Za-z0-9._~-]+:[^\s/]+@"
    r"[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9._/~+-]+)?"
)
rl_ABSOLUTE_PATH_RE = rl_re.compile(
    r"(?<![A-Za-z0-9])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"
)
rl_CREDENTIAL_IMAGE_RE = rl_re.compile(
    r"(?i)(?<![A-Za-z0-9._-])"
    r"[A-Za-z0-9._~-]+:[^\s/]+@"
    r"[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9._/~+-]+"
)
rl_VERSION_RE = rl_re.compile(r"\b\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?\b")
rl_FROM_RE = rl_re.compile(r"(?im)^\s*FROM\s+(?:--\S+\s+)*([^\s]+)")
rl_SERVICE_RE = rl_re.compile(r"(?m)^  ([A-Za-z0-9][A-Za-z0-9_-]*):\s*$")
rl_IMAGE_RE = rl_re.compile(r"(?m)^\s+image:\s*([^\s#]+)")
rl_DOCKERFILE_RE = rl_re.compile(r"(?m)^\s+dockerfile:\s*([^\s#]+)")
rl_MOUNT_RE = rl_re.compile(r"(?m)^\s*-\s+([^\s:]+):[^\s]+")
rl_URL_SCHEME_RE = rl_re.compile(r"(?i)^([a-z][a-z0-9+.-]*):")
rl_CREDENTIAL_RE = rl_re.compile(r"^[^:/?#]+://[^/@:]+:([^@]*)@")
rl_SAFE_IMAGE_RE = rl_re.compile(
    r"^[a-z0-9][a-z0-9._-]*(?::[0-9]+)?"
    r"(?:/[a-z0-9][a-z0-9._-]*)*"
    r"(?::[a-z0-9][a-z0-9._-]*)?(?:@sha256:[0-9a-f]{64})?$"
)
rl_SAFE_ENTRYPOINT_RE = rl_re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?::[A-Za-z_][A-Za-z0-9_]*)?$"
)
rl_SAFE_RELATIVE_PATH_RE = rl_re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def rl_has_sensitive_shape(rl_value: str) -> bool:
    return any(
        rl_pattern.search(rl_value)
        for rl_pattern in (
            rl_URL_RE,
            rl_SECRET_ASSIGNMENT_RE,
            rl_BEARER_RE,
            rl_BASIC_RE,
            rl_CREDENTIAL_IMAGE_RE,
            rl_NO_SCHEME_CREDENTIAL_RE,
        )
    )


def rl_redact_text(rl_value: str) -> str:
    """Redact URL, auth payload, image credential and secret assignment shapes."""

    rl_redacted = rl_CREDENTIAL_IMAGE_RE.sub("<redacted-credential>", rl_value)
    rl_redacted = rl_NO_SCHEME_CREDENTIAL_RE.sub("<redacted-credential>", rl_redacted)
    rl_redacted = rl_URL_RE.sub("<redacted-url>", rl_redacted)
    rl_redacted = rl_ABSOLUTE_PATH_RE.sub("<redacted-absolute-path>", rl_redacted)
    rl_redacted = rl_BASIC_RE.sub("Basic <redacted-auth>", rl_redacted)
    rl_redacted = rl_BEARER_RE.sub("Bearer <redacted-secret>", rl_redacted)
    rl_redacted = rl_SECRET_ASSIGNMENT_RE.sub(r"\1<redacted-secret>", rl_redacted)
    return rl_redacted


def rl_safe_path(rl_relative_path: str) -> str:
    """Return a stable project-relative path representation."""

    rl_normalized = rl_relative_path.replace("\\", "/")
    if rl_normalized.startswith("//"):
        return "<unsafe-relative-path>"
    if rl_normalized.startswith("/"):
        return "<absolute-path>"
    if rl_re.match(r"^[A-Za-z]:", rl_normalized):
        return "<unsafe-relative-path>"
    if any(rl_char == "\x7f" or ord(rl_char) < 0x20 for rl_char in rl_normalized):
        return "<unsafe-relative-path>"
    if ".." in rl_normalized.split("/"):
        # 中文 why：provenance 不能输出 project root 外的路径，故只做词法拒绝。
        return "<unsafe-relative-path>"
    return rl_normalized


def rl_digest_text(rl_value: str) -> str:
    """Return a digest for command output instead of retaining that output."""

    return rl_hashlib.sha256(rl_value.encode("utf-8", errors="replace")).hexdigest()


def rl_safe_source_value(
    rl_value: str,
    rl_kind: str,
    rl_why: str = "不安全的 source-derived 值只保留 classification/digest。",
) -> dict[str, rl_Any]:
    """Return allowlisted source text or a digest-only classification."""

    rl_clean = rl_value.strip()
    rl_has_forbidden_shape = rl_has_sensitive_shape(rl_clean) or bool(
        rl_ABSOLUTE_PATH_RE.search(rl_clean)
    )
    rl_safe = (
        (
            rl_kind == "image"
            and bool(rl_SAFE_IMAGE_RE.fullmatch(rl_clean))
            and not rl_has_forbidden_shape
        )
        or (
            rl_kind == "entrypoint"
            and bool(rl_SAFE_ENTRYPOINT_RE.fullmatch(rl_clean))
            and not rl_has_forbidden_shape
        )
        or (
            rl_kind == "relative_path"
            and bool(rl_SAFE_RELATIVE_PATH_RE.fullmatch(rl_clean))
            and not rl_clean.startswith(("/", "../"))
            and ".." not in rl_clean.split("/")
            and not rl_has_forbidden_shape
        )
    )
    if rl_safe:
        return {"rl_classification": "observed", "rl_value": rl_clean}
    # 中文 why：image/entrypoint/path 可能携带凭据或跳出 project root，不能仅靠通用 redaction 放行。
    return {
        "rl_classification": "redacted_source_value",
        "rl_digest": f"sha256:{rl_digest_text(rl_clean)}",
        "rl_why": rl_why,
    }


def rl_emit_source_value(rl_value: str, rl_kind: str) -> str | dict[str, rl_Any]:
    """Emit only allowlisted source-derived text, otherwise digest metadata."""

    rl_result = rl_safe_source_value(rl_value, rl_kind)
    if rl_result["rl_classification"] == "observed":
        return rl_result["rl_value"]
    return rl_result


def rl_source_value_sort_key(rl_value: str | dict[str, rl_Any]) -> str:
    if isinstance(rl_value, str):
        return rl_value
    return rl_json.dumps(rl_value, ensure_ascii=False, sort_keys=True)


def rl_source_provenance_record(
    rl_relative_path: str,
    rl_status: str,
    rl_text: str | None = None,
    rl_bytes: bytes | None = None,
) -> dict[str, str]:
    """Build one stable source read record; unavailable sources have no digest."""

    rl_result: dict[str, str] = {
        "rl_path": rl_safe_path(rl_relative_path),
        "rl_status": rl_status,
    }
    if rl_status == "read":
        if rl_bytes is None and rl_text is None:
            raise ValueError("read provenance requires source content")
        if rl_bytes is None:
            assert rl_text is not None
            rl_digest_input = rl_text.encode("utf-8")
        else:
            rl_digest_input = rl_bytes
        rl_result["rl_digest"] = (
            f"sha256:{rl_hashlib.sha256(rl_digest_input).hexdigest()}"
        )
    return rl_result


def rl_url_metadata(rl_value: str) -> dict[str, rl_Any]:
    """Describe a URL without retaining its host, path, credentials, or value."""

    rl_stripped = rl_value.strip()
    rl_match = rl_URL_SCHEME_RE.search(rl_stripped)
    rl_scheme = rl_match.group(1).lower() if rl_match else None
    rl_has_password = bool(rl_CREDENTIAL_RE.search(rl_stripped))
    rl_is_poisoned = rl_has_password or rl_has_sensitive_shape(rl_stripped)
    return {
        "rl_present": True,
        "rl_scheme": rl_scheme,
        "rl_has_credentials": rl_has_password
        or bool(rl_NO_SCHEME_CREDENTIAL_RE.search(rl_stripped)),
        "rl_has_password": rl_has_password,
        # 中文 why：开发默认 URL 带凭据时只能记录为 poisoned/default，不能当作可用目标。
        "rl_classification": "poisoned_default"
        if rl_is_poisoned
        else "observed_default",
        "rl_redacted_value": "<redacted-url>",
    }


def rl_fact(
    rl_fact_id: str,
    rl_source: str,
    rl_why: str,
    rl_detail: str | None = None,
) -> dict[str, str]:
    """Build one explicit blocking or difference fact."""

    rl_result = {
        "rl_fact_id": rl_fact_id,
        "rl_source": rl_safe_path(rl_source),
        "rl_why": rl_why,
    }
    if rl_detail is not None:
        rl_result["rl_detail"] = rl_redact_text(rl_detail)
    return rl_result


def rl_collect_runtime_facts(
    rl_project_root: str | rl_Path,
    rl_command_versions: rl_Mapping[str, rl_Sequence[str]] | None = None,
    rl_command_runner: rl_Callable[..., rl_Any] | None = None,
) -> dict[str, rl_Any]:
    """Collect static facts from ``rl_project_root``.

    ``rl_command_versions`` is opt-in and restricted to a command whose final
    argument is a version flag.  No command is run by default.  The mapping is
    intentionally a data input rather than a profile or target selector.
    """

    rl_root = rl_Path(rl_project_root).expanduser().resolve()
    rl_blocking_facts: list[dict[str, str]] = []
    rl_difference_facts: list[dict[str, str]] = []
    rl_source_provenance: list[dict[str, str]] = []
    rl_seen_blocking: set[str] = set()
    rl_seen_difference: set[str] = set()

    def rl_add_blocking(
        rl_fact_id: str,
        rl_source: str,
        rl_why: str,
        rl_detail: str | None = None,
    ) -> None:
        if rl_fact_id not in rl_seen_blocking:
            rl_seen_blocking.add(rl_fact_id)
            rl_blocking_facts.append(rl_fact(rl_fact_id, rl_source, rl_why, rl_detail))

    def rl_add_difference(
        rl_fact_id: str,
        rl_source: str,
        rl_why: str,
        rl_detail: str | None = None,
    ) -> None:
        if rl_fact_id not in rl_seen_difference:
            rl_seen_difference.add(rl_fact_id)
            rl_difference_facts.append(
                rl_fact(rl_fact_id, rl_source, rl_why, rl_detail)
            )

    if not rl_root.exists() or not rl_root.is_dir():
        rl_add_blocking(
            "rl_project_root:unavailable",
            ".",
            "指定 project root 不存在或不是目录，不能静态读取事实。",
            str(rl_root),
        )
        return rl_build_report(
            rl_root,
            {},
            rl_blocking_facts,
            rl_difference_facts,
            rl_command_versions,
            rl_source_provenance,
        )

    rl_sources: dict[str, str | None] = {}

    def rl_read_source(rl_relative_path: str, rl_required: bool = True) -> str | None:
        rl_path = rl_root / rl_relative_path
        if not rl_path.exists():
            rl_source_provenance.append(
                rl_source_provenance_record(rl_relative_path, "missing")
            )
            if rl_required:
                rl_add_blocking(
                    f"rl_missing_file:{rl_safe_path(rl_relative_path)}",
                    rl_relative_path,
                    "必需静态输入缺失，collector 不猜测其内容。",
                )
            else:
                rl_add_difference(
                    f"rl_missing_optional_file:{rl_safe_path(rl_relative_path)}",
                    rl_relative_path,
                    "可选 wiring 输入缺失，实际运行方式无法从该文件确认。",
                )
            rl_sources[rl_relative_path] = None
            return None
        if not rl_path.is_file():
            rl_source_provenance.append(
                rl_source_provenance_record(rl_relative_path, "not_file")
            )
            rl_add_blocking(
                f"rl_not_file:{rl_safe_path(rl_relative_path)}",
                rl_relative_path,
                "静态输入路径存在但不是普通文件，不能安全解析。",
            )
            rl_sources[rl_relative_path] = None
            return None
        try:
            rl_bytes = rl_path.read_bytes()
            rl_text = rl_bytes.decode("utf-8")
        except (OSError, UnicodeError) as rl_exc:
            rl_source_provenance.append(
                rl_source_provenance_record(rl_relative_path, "unreadable")
            )
            rl_add_blocking(
                f"rl_unreadable_file:{rl_safe_path(rl_relative_path)}",
                rl_relative_path,
                "静态输入不可读取，不能静默成功。",
                type(rl_exc).__name__,
            )
            rl_sources[rl_relative_path] = None
            return None
        rl_source_provenance.append(
            rl_source_provenance_record(rl_relative_path, "read", rl_text, rl_bytes)
        )
        rl_sources[rl_relative_path] = rl_text
        return rl_text

    # 中文 why：Task 1 的 runtime/wiring 结论依赖这些实际路径；缺失时必须
    # fail-close，不能退化成“只看得到的文件”报告。
    rl_required_paths = (
        "README.md",
        "package.json",
        "apps/api/pyproject.toml",
        "apps/worker/pyproject.toml",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "apps/worker/README.md",
        "apps/api/app/main.py",
        "apps/worker/src/soymutdb_worker/main.py",
        "apps/api/app/core/config.py",
        "apps/api/app/core/database.py",
        "apps/api/migrations/env.py",
        "apps/api/alembic.ini",
        "infra/docker/Dockerfile.api",
        "infra/docker/Dockerfile.worker",
        "infra/docker/Dockerfile.web",
        "infra/docker/Dockerfile.admin",
        "apps/jbrowse/Dockerfile",
    )
    for rl_relative_path in rl_required_paths:
        rl_read_source(rl_relative_path)

    rl_ast_trees: dict[str, rl_ast.AST | None] = {}

    def rl_parse_python(rl_relative_path: str) -> rl_ast.AST | None:
        rl_text = rl_sources.get(rl_relative_path)
        if rl_text is None:
            rl_ast_trees[rl_relative_path] = None
            return None
        try:
            rl_tree = rl_ast.parse(rl_text, filename=rl_relative_path)
        except (SyntaxError, ValueError) as rl_exc:
            rl_add_blocking(
                f"rl_parse:{rl_safe_path(rl_relative_path)}",
                rl_relative_path,
                "Python 静态语法不可解析，collector 不凭经验补齐事实。",
                type(rl_exc).__name__,
            )
            rl_tree = None
        rl_ast_trees[rl_relative_path] = rl_tree
        return rl_tree

    def rl_parse_toml(rl_relative_path: str) -> dict[str, rl_Any] | None:
        rl_text = rl_sources.get(rl_relative_path)
        if rl_text is None:
            return None
        try:
            return rl_tomllib.loads(rl_text)
        except (rl_tomllib.TOMLDecodeError, ValueError) as rl_exc:
            rl_add_blocking(
                f"rl_parse:{rl_safe_path(rl_relative_path)}",
                rl_relative_path,
                "TOML 静态语法不可解析，requirements 事实不能猜测。",
                type(rl_exc).__name__,
            )
            return None

    rl_readme = rl_sources.get("README.md")
    rl_package_text = rl_sources.get("package.json")
    rl_compose_text = rl_sources.get("docker-compose.yml")
    rl_compose_dev_text = rl_sources.get("docker-compose.dev.yml")
    rl_api_pyproject = rl_parse_toml("apps/api/pyproject.toml")
    rl_worker_pyproject = rl_parse_toml("apps/worker/pyproject.toml")
    rl_config_tree = rl_parse_python("apps/api/app/core/config.py")
    rl_database_tree = rl_parse_python("apps/api/app/core/database.py")
    rl_migrations_tree = rl_parse_python("apps/api/migrations/env.py")
    rl_parse_python("apps/api/app/main.py")
    rl_parse_python("apps/worker/src/soymutdb_worker/main.py")
    rl_config_structure = rl_extract_config_structure(rl_config_tree)
    rl_database_structure = rl_extract_database_structure(rl_database_tree)
    rl_migrations_structure = rl_extract_migrations_structure(rl_migrations_tree)
    rl_add_extraction_blocking_facts(
        "apps/api/app/core/config.py", rl_config_structure, rl_add_blocking
    )
    rl_add_extraction_blocking_facts(
        "apps/api/app/core/database.py", rl_database_structure, rl_add_blocking
    )
    rl_add_extraction_blocking_facts(
        "apps/api/migrations/env.py", rl_migrations_structure, rl_add_blocking
    )

    rl_package: dict[str, rl_Any] | None = None
    if rl_package_text is not None:
        try:
            rl_package_value = rl_json.loads(rl_package_text)
            if isinstance(rl_package_value, dict):
                rl_package = rl_package_value
            else:
                raise ValueError("package.json root is not an object")
        except (rl_json.JSONDecodeError, ValueError, TypeError) as rl_exc:
            rl_add_blocking(
                "rl_parse:package.json",
                "package.json",
                "JSON 静态语法不可解析，Node baseline 不能猜测。",
                type(rl_exc).__name__,
            )

    rl_project_api = rl_api_pyproject.get("project", {}) if rl_api_pyproject else {}
    rl_project_worker = (
        rl_worker_pyproject.get("project", {}) if rl_worker_pyproject else {}
    )
    rl_api_dependencies = rl_dependency_names(rl_project_api.get("dependencies", []))
    rl_worker_dependencies = rl_dependency_names(
        rl_project_worker.get("dependencies", [])
    )
    rl_asyncpg_requirements = rl_dependency_matches(
        rl_project_api.get("dependencies", []), "asyncpg"
    )

    rl_alembic_text = rl_sources.get("apps/api/alembic.ini") or ""
    rl_config_defaults = rl_extract_python_string_assignments(rl_config_structure)
    rl_database_url_default = rl_config_defaults.get("database_url")
    rl_ini_url_match = rl_re.search(
        r"(?im)^\s*sqlalchemy\.url\s*=\s*([^\s#]+)", rl_alembic_text
    )
    rl_ini_url = rl_ini_url_match.group(1) if rl_ini_url_match else None
    if rl_ini_url is None and rl_sources.get("apps/api/alembic.ini") is not None:
        rl_add_difference(
            "rl_missing_fact:alembic.ini.sqlalchemy.url",
            "apps/api/alembic.ini",
            "alembic.ini 未声明 sqlalchemy.url，不能猜测其迁移连接配置。",
        )

    rl_script_location_match = rl_re.search(
        r"(?im)^\s*script_location\s*=\s*([^\s#]+)", rl_alembic_text
    )
    rl_script_location = (
        rl_script_location_match.group(1) if rl_script_location_match else None
    )
    if (
        rl_script_location is None
        and rl_sources.get("apps/api/alembic.ini") is not None
    ):
        rl_add_blocking(
            "rl_missing_fact:alembic.ini.script_location",
            "apps/api/alembic.ini",
            "缺少相对 migration script_location，Alembic 路径无法确认。",
        )

    rl_validate_readme_source("README.md", rl_readme, rl_add_blocking)
    rl_validate_worker_readme_source(
        "apps/worker/README.md",
        rl_sources.get("apps/worker/README.md"),
        rl_add_blocking,
    )
    rl_validate_compose_source("docker-compose.yml", rl_compose_text, rl_add_blocking)
    rl_validate_compose_source(
        "docker-compose.dev.yml", rl_compose_dev_text, rl_add_blocking
    )
    for rl_dockerfile_path in (
        "infra/docker/Dockerfile.api",
        "infra/docker/Dockerfile.worker",
        "infra/docker/Dockerfile.web",
        "infra/docker/Dockerfile.admin",
        "apps/jbrowse/Dockerfile",
    ):
        rl_validate_dockerfile_source(
            rl_dockerfile_path, rl_sources.get(rl_dockerfile_path), rl_add_blocking
        )
    rl_facts: dict[str, rl_Any] = {
        "rl_requirements": {
            "rl_readme": rl_readme_requirements(
                rl_readme, "README.md", rl_add_difference
            ),
            "rl_worker_readme": rl_readme_requirements(
                rl_sources.get("apps/worker/README.md"),
                "apps/worker/README.md",
                rl_add_difference,
            ),
            "rl_api": {
                "rl_file": "apps/api/pyproject.toml",
                "rl_present": rl_api_pyproject is not None,
                "rl_requires_python": rl_project_api.get("requires-python"),
                "rl_dependency_names": sorted(rl_api_dependencies),
                "rl_dependency_count": len(rl_api_dependencies),
            },
            "rl_worker": {
                "rl_file": "apps/worker/pyproject.toml",
                "rl_present": rl_worker_pyproject is not None,
                "rl_requires_python": rl_project_worker.get("requires-python"),
                "rl_dependency_names": sorted(rl_worker_dependencies),
                "rl_dependency_count": len(rl_worker_dependencies),
            },
        },
        "rl_node": rl_node_facts(rl_package, rl_readme),
        "rl_compose": rl_compose_facts(rl_compose_text, rl_compose_dev_text),
        "rl_docker": rl_docker_facts(rl_sources),
        "rl_api_asyncpg": {
            "rl_present": bool(rl_asyncpg_requirements),
            "rl_requirements": sorted(
                rl_safe_dependency(rl_value) for rl_value in rl_asyncpg_requirements
            ),
            "rl_why": "API 使用 async SQLAlchemy 时需要 asyncpg 方言/驱动；这里只记录声明，不安装或导入。",  # noqa: E501
        },
        "rl_config": rl_config_facts(
            rl_root,
            rl_config_structure,
            rl_config_defaults,
            rl_database_url_default,
            rl_add_difference,
        ),
        "rl_database": rl_database_facts(rl_database_structure),
        "rl_migrations_env": rl_migrations_facts(rl_migrations_structure),
        "rl_alembic": rl_alembic_facts(
            rl_alembic_text,
            rl_script_location,
            rl_ini_url,
            rl_root,
            rl_add_difference,
        ),
    }
    rl_facts["rl_execution_contexts"] = rl_execution_context_facts(rl_root, rl_sources)
    rl_facts["rl_path_drift"] = rl_path_drift_facts(
        rl_root,
        rl_sources,
        rl_compose_text,
        rl_compose_dev_text,
        rl_add_difference,
    )
    rl_facts["rl_known_paths"] = rl_known_path_facts(rl_root)

    rl_command_facts = rl_collect_command_facts(
        rl_root,
        rl_command_versions,
        rl_add_blocking,
        rl_add_difference,
        rl_command_runner,
    )
    rl_facts["rl_command_versions"] = rl_command_facts
    return rl_build_report(
        rl_root,
        rl_facts,
        rl_blocking_facts,
        rl_difference_facts,
        rl_command_versions,
        rl_source_provenance,
    )


def rl_build_report(
    rl_root: rl_Path,
    rl_facts: dict[str, rl_Any],
    rl_blocking_facts: list[dict[str, str]],
    rl_difference_facts: list[dict[str, str]],
    rl_command_versions: rl_Mapping[str, rl_Sequence[str]] | None,
    rl_source_provenance: list[dict[str, str]] | None = None,
) -> dict[str, rl_Any]:
    """Assemble a stable report envelope."""

    return rl_sanitize_report(
        {
            "rl_schema_version": rl_SCHEMA_VERSION,
            "rl_project_root": "<project-root>",
            "rl_project_root_is_absolute": rl_root.is_absolute(),
            "rl_static_only": True,
            "rl_database_connections_attempted": False,
            "rl_application_imports_attempted": False,
            "rl_producer": rl_PRODUCER,
            "rl_owner": rl_OWNER,
            "rl_reviewer": rl_REVIEWER,
            # 中文 why：静态扫描和预期角色元数据不等于独立 review 或 runtime proof。
            "rl_runtime_evidence_status": rl_RUNTIME_EVIDENCE_STATUS,
            "rl_source_provenance": sorted(
                rl_source_provenance or [],
                key=lambda rl_item: rl_item["rl_path"],
            ),
            "rl_command_versions_requested": sorted(
                rl_safe_command_name(rl_name) for rl_name in (rl_command_versions or {})
            ),
            "rl_facts": rl_sanitize_report(rl_facts),
            "rl_blocking_facts": sorted(
                rl_blocking_facts, key=lambda rl_item: rl_item["rl_fact_id"]
            ),
            "rl_difference_facts": sorted(
                rl_difference_facts, key=lambda rl_item: rl_item["rl_fact_id"]
            ),
        }
    )


def rl_sanitize_report(rl_value: rl_Any) -> rl_Any:
    """Recursively redact strings before a report can leave the process."""

    if isinstance(rl_value, str):
        return rl_redact_text(rl_value)
    if isinstance(rl_value, dict):
        return {
            rl_key: rl_sanitize_report(rl_nested_value)
            for rl_key, rl_nested_value in rl_value.items()
        }
    if isinstance(rl_value, list):
        return [rl_sanitize_report(rl_nested_value) for rl_nested_value in rl_value]
    if isinstance(rl_value, tuple):
        return [rl_sanitize_report(rl_nested_value) for rl_nested_value in rl_value]
    return rl_value


def rl_dependency_names(rl_dependencies: rl_Any) -> list[str]:
    """Extract only package names, never dependency URLs or credentials."""

    if not isinstance(rl_dependencies, list):
        return []
    rl_names: list[str] = []
    for rl_dependency in rl_dependencies:
        if not isinstance(rl_dependency, str):
            continue
        rl_match = rl_re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", rl_dependency)
        if rl_match:
            rl_names.append(rl_match.group(1).lower())
    return rl_names


def rl_dependency_matches(rl_dependencies: rl_Any, rl_name: str) -> list[str]:
    """Return dependency declarations matching one safe package name."""

    if not isinstance(rl_dependencies, list):
        return []
    rl_matches: list[str] = []
    for rl_dependency in rl_dependencies:
        if not isinstance(rl_dependency, str):
            continue
        rl_match = rl_re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", rl_dependency)
        if rl_match and rl_match.group(1).lower() == rl_name.lower():
            rl_matches.append(rl_dependency)
    return rl_matches


def rl_safe_dependency(rl_dependency: str) -> str:
    """Keep ordinary package specifiers while collapsing URL-like specs."""

    if rl_has_sensitive_shape(rl_dependency):
        return "<redacted-dependency>"
    rl_match = rl_re.match(
        r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?)\s*"
        r"([<>=!~*.\s0-9A-Za-z+_.-]*)\s*$",
        rl_dependency,
    )
    if not rl_match:
        return "<redacted-dependency>"
    return f"{rl_match.group(1)}{rl_match.group(2).strip()}"


def rl_readme_requirements(
    rl_readme: str | None,
    rl_source: str,
    rl_add_difference: rl_Any,
) -> dict[str, rl_Any]:
    """Extract README baselines without retaining prose."""

    if rl_readme is None:
        return {
            "rl_present": False,
            "rl_node_requirement": None,
            "rl_python_requirement": None,
            "rl_pnpm_requirement": None,
        }
    rl_node_match = rl_re.search(r"(?i)Node\.js\s*[≥>=]+\s*([0-9][^\s,)]+)", rl_readme)
    rl_python_match = rl_re.search(r"(?i)Python\s*[≥>=]+\s*([0-9][^\s,)]+)", rl_readme)
    rl_pnpm_match = rl_re.search(r"(?i)pnpm\s*[≥>=]+\s*([0-9][^\s,)]+)", rl_readme)
    rl_result = {
        "rl_present": True,
        "rl_node_requirement": f">={rl_node_match.group(1)}" if rl_node_match else None,
        "rl_python_requirement": f">={rl_python_match.group(1)}"
        if rl_python_match
        else None,
        "rl_pnpm_requirement": f">={rl_pnpm_match.group(1)}" if rl_pnpm_match else None,
    }
    for rl_key, rl_value in (
        ("rl_node_requirement", rl_result["rl_node_requirement"]),
        ("rl_python_requirement", rl_result["rl_python_requirement"]),
        ("rl_pnpm_requirement", rl_result["rl_pnpm_requirement"]),
    ):
        if rl_value is None:
            rl_add_difference(
                f"rl_missing_fact:README.{rl_key}",
                rl_source,
                "README 未给出该 baseline，collector 不从其它文件反推 README 事实。",
            )
    return rl_result


def rl_validate_readme_source(
    rl_source: str, rl_text: str | None, rl_add_blocking: rl_Any
) -> None:
    """Fail closed when README baseline facts cannot be extracted."""

    if rl_text is None:
        return
    rl_facts = rl_readme_requirements(rl_text, rl_source, lambda *rl_args: None)
    if not all(
        rl_facts[rl_key] is not None
        for rl_key in (
            "rl_node_requirement",
            "rl_python_requirement",
            "rl_pnpm_requirement",
        )
    ):
        rl_add_blocking(
            f"rl_parse:{rl_source}",
            rl_source,
            "README baseline 不可解析，runtime requirements 不能猜测。",
        )


def rl_validate_worker_readme_source(
    rl_source: str, rl_text: str | None, rl_add_blocking: rl_Any
) -> None:
    """Require the worker README to expose its source and entrypoint facts."""

    if rl_text is None:
        return
    if not rl_re.search(
        r"(?m)(?:apps/worker/)?src/soymutdb_worker", rl_text
    ) or not rl_re.search(r"(?m)celery\s+-A\s+soymutdb_worker\.main", rl_text):
        rl_add_blocking(
            f"rl_parse:{rl_source}",
            rl_source,
            "Worker README 缺少实际 source/entrypoint wiring，不能据此确认执行上下文。",
        )


def rl_validate_compose_source(
    rl_source: str, rl_text: str | None, rl_add_blocking: rl_Any
) -> None:
    """Require enough Compose structure to make service/image facts meaningful."""

    if rl_text is None:
        return
    rl_has_services = bool(rl_re.search(r"(?m)^services:\s*$", rl_text))
    rl_has_service = bool(rl_SERVICE_RE.search(rl_text))
    rl_has_wiring = bool(
        rl_re.search(r"(?m)^\s+(?:image|build|command|volumes):", rl_text)
    )
    if not rl_has_services or not rl_has_service or not rl_has_wiring:
        rl_add_blocking(
            f"rl_parse:{rl_source}",
            rl_source,
            "Compose services 结构不可解析，不能猜测 image/build/entrypoint wiring。",
        )


def rl_validate_dockerfile_source(
    rl_source: str, rl_text: str | None, rl_add_blocking: rl_Any
) -> None:
    """Require a Dockerfile FROM instruction before recording image facts."""

    if rl_text is None:
        return
    if not rl_FROM_RE.search(rl_text):
        rl_add_blocking(
            f"rl_parse:{rl_source}",
            rl_source,
            "Dockerfile 缺少可解析 FROM image，不能猜测运行时 image fact。",
        )


def rl_add_missing_structure_facts(
    rl_source: str,
    rl_structure_facts: dict[str, bool],
    rl_add_blocking: rl_Any,
) -> None:
    """Turn every absent minimum wiring fact into a stable blocking fact."""

    for rl_fact_name, rl_present in rl_structure_facts.items():
        if not rl_present:
            # 中文 why：静态 AST 可为空且仍然合法；缺关键 wiring 不能被当作
            # ordinary parseability difference，否则后续 consumer 会误判为安全。
            rl_add_blocking(
                f"rl_missing_fact:{rl_safe_path(rl_source)}.{rl_fact_name}",
                rl_source,
                "必需 Python wiring fact 缺失；collector fail-close 且不猜测产品行为。",
            )


def rl_dotted_name(rl_node: rl_ast.AST | None) -> str | None:
    """Resolve only static Name/Attribute dotted names."""

    if isinstance(rl_node, rl_ast.Name):
        return rl_node.id
    if isinstance(rl_node, rl_ast.Attribute):
        rl_parent = rl_dotted_name(rl_node.value)
        return f"{rl_parent}.{rl_node.attr}" if rl_parent else None
    return None


def rl_literal_string(rl_node: rl_ast.AST | None) -> str | None:
    """Read only literal strings from AST nodes."""

    if isinstance(rl_node, rl_ast.Constant) and isinstance(rl_node.value, str):
        return rl_node.value
    return None


def rl_module_import_aliases(rl_tree: rl_ast.AST | None) -> dict[str, str]:
    """Build direct top-level import aliases only."""

    rl_aliases: dict[str, str] = {}
    if not isinstance(rl_tree, rl_ast.Module):
        return rl_aliases
    rl_assigned_names: set[str] = set()
    for rl_node in rl_tree.body:
        if isinstance(rl_node, rl_ast.Import):
            for rl_alias in rl_node.names:
                rl_bound_name = rl_alias.asname or rl_alias.name.split(".", 1)[0]
                rl_aliases[rl_bound_name] = rl_alias.name
        elif isinstance(rl_node, rl_ast.ImportFrom) and rl_node.module:
            rl_import_module = rl_node.module
            if rl_node.level == 1 and rl_node.module == "config":
                rl_import_module = "app.core.config"
            elif rl_node.level == 1 and rl_node.module == "database":
                rl_import_module = "app.core.database"
            for rl_alias in rl_node.names:
                rl_bound_name = rl_alias.asname or rl_alias.name
                if rl_alias.name == "*":
                    continue
                rl_aliases[rl_bound_name] = f"{rl_import_module}.{rl_alias.name}"
        elif isinstance(rl_node, (rl_ast.Assign, rl_ast.AnnAssign)):
            if isinstance(rl_node, rl_ast.Assign):
                rl_assigned_names.update(
                    rl_target.id
                    for rl_target in rl_node.targets
                    if isinstance(rl_target, rl_ast.Name)
                )
            elif isinstance(rl_node.target, rl_ast.Name):
                rl_assigned_names.add(rl_node.target.id)
        elif isinstance(
            rl_node, (rl_ast.FunctionDef, rl_ast.AsyncFunctionDef, rl_ast.ClassDef)
        ):
            rl_assigned_names.add(rl_node.name)
    for rl_assigned_name in rl_assigned_names:
        rl_aliases.pop(rl_assigned_name, None)
    return rl_aliases


def rl_canonical_name(
    rl_node: rl_ast.AST | None,
    rl_aliases: dict[str, str],
) -> str | None:
    """Resolve a direct name or qualified name through one import alias map."""

    rl_name = rl_dotted_name(rl_node)
    if rl_name is None:
        return None
    rl_parts = rl_name.split(".")
    rl_prefix = rl_aliases.get(rl_parts[0], rl_parts[0])
    return ".".join([rl_prefix, *rl_parts[1:]]) if len(rl_parts) > 1 else rl_prefix


def rl_is_zero_arg_call(
    rl_node: rl_ast.AST | None,
    rl_callee: str,
    rl_aliases: dict[str, str],
) -> bool:
    """Match a direct zero-argument canonical call, rejecting starred args."""

    return (
        isinstance(rl_node, rl_ast.Call)
        and rl_canonical_name(rl_node.func, rl_aliases) == rl_callee
        and not rl_node.args
        and not rl_node.keywords
    )


def rl_condition_is_static_false(rl_node: rl_ast.AST) -> bool:
    """Recognize the explicit dead-code form required by this bounded checker."""

    return isinstance(rl_node, rl_ast.Constant) and rl_node.value is False


def rl_effective_statements(rl_body: list[rl_ast.stmt]) -> list[rl_ast.stmt]:
    """Keep direct statements while excluding obvious false/dead branches."""

    rl_effective: list[rl_ast.stmt] = []
    for rl_statement in rl_body:
        if isinstance(rl_statement, rl_ast.If) and rl_condition_is_static_false(
            rl_statement.test
        ):
            continue
        rl_effective.append(rl_statement)
        if isinstance(rl_statement, (rl_ast.Return, rl_ast.Raise)):
            break
    return rl_effective


def rl_direct_assignments(
    rl_body: list[rl_ast.stmt],
) -> list[rl_ast.Assign | rl_ast.AnnAssign]:
    """Return only direct assignment statements from one explicit body."""

    return [
        rl_statement
        for rl_statement in rl_body
        if isinstance(rl_statement, (rl_ast.Assign, rl_ast.AnnAssign))
    ]


def rl_extract_config_structure(rl_tree: rl_ast.AST | None) -> dict[str, rl_Any]:
    """Extract the constrained Settings/factory contract from Module.body."""

    rl_aliases = rl_module_import_aliases(rl_tree)
    rl_settings_classes = [
        rl_node
        for rl_node in (rl_tree.body if isinstance(rl_tree, rl_ast.Module) else [])
        if isinstance(rl_node, rl_ast.ClassDef) and rl_node.name == "Settings"
    ]
    rl_settings_class = (
        rl_settings_classes[0] if len(rl_settings_classes) == 1 else None
    )
    rl_settings_body = rl_settings_class.body if rl_settings_class else []
    rl_base_ok = bool(
        rl_settings_class
        and any(
            rl_canonical_name(rl_base, rl_aliases) == "pydantic_settings.BaseSettings"
            for rl_base in rl_settings_class.bases
        )
    )
    rl_model_config_call: rl_ast.Call | None = None
    rl_database_url_field: rl_ast.AnnAssign | None = None
    for rl_statement in rl_direct_assignments(rl_settings_body):
        if isinstance(rl_statement, rl_ast.Assign):
            rl_targets = rl_statement.targets
            rl_target_names = [rl_dotted_name(rl_target) for rl_target in rl_targets]
            if "model_config" in rl_target_names and isinstance(
                rl_statement.value, rl_ast.Call
            ):
                if rl_canonical_name(rl_statement.value.func, rl_aliases) == (
                    "pydantic_settings.SettingsConfigDict"
                ):
                    rl_model_config_call = rl_statement.value
        elif isinstance(rl_statement, rl_ast.AnnAssign):
            if rl_dotted_name(rl_statement.target) == "database_url":
                rl_database_url_field = rl_statement
    rl_model_keywords = {
        rl_keyword.arg: rl_literal_string(rl_keyword.value)
        for rl_keyword in (
            rl_model_config_call.keywords if rl_model_config_call else []
        )
        if rl_keyword.arg is not None
    }
    rl_factory = next(
        (
            rl_node
            for rl_node in (rl_tree.body if isinstance(rl_tree, rl_ast.Module) else [])
            if isinstance(rl_node, rl_ast.FunctionDef)
            and rl_node.name == "get_settings"
        ),
        None,
    )
    rl_factory_decorator_ok = bool(
        rl_factory
        and any(
            rl_canonical_name(
                rl_decorator.func
                if isinstance(rl_decorator, rl_ast.Call)
                else rl_decorator,
                rl_aliases,
            )
            == "functools.lru_cache"
            for rl_decorator in rl_factory.decorator_list
        )
    )
    rl_factory_return = rl_literal_string(rl_factory.returns if rl_factory else None)
    rl_factory_return_ok = bool(
        rl_factory
        and (
            rl_dotted_name(rl_factory.returns) == "Settings"
            or rl_factory_return == "Settings"
        )
    )
    rl_factory_returns = [
        rl_statement.value
        for rl_statement in (
            rl_effective_statements(rl_factory.body) if rl_factory else []
        )
        if isinstance(rl_statement, rl_ast.Return) and rl_statement.value is not None
    ]
    rl_factory_body_ok = bool(rl_factory_returns) and all(
        isinstance(rl_return, rl_ast.Call)
        and rl_dotted_name(rl_return.func) == "Settings"
        and not rl_return.args
        and not rl_return.keywords
        for rl_return in rl_factory_returns
    )
    return {
        "rl_parseable": rl_tree is not None,
        "rl_settings_source": rl_base_ok,
        "rl_settings_class": rl_settings_class,
        "rl_settings_body": rl_settings_body,
        "rl_model_config": rl_model_config_call,
        "rl_env_file": rl_model_keywords.get("env_file") == ".env",
        "rl_env_prefix": rl_model_keywords.get("env_prefix") == "SOYMUTDB_",
        "rl_database_url": bool(
            rl_database_url_field and rl_database_url_field.annotation is not None
        ),
        "rl_database_url_field": rl_database_url_field,
        "rl_factory": rl_factory,
        "rl_cache": rl_factory_decorator_ok,
        "rl_factory_return": rl_factory_return_ok,
        "rl_factory_body": rl_factory_body_ok,
        "rl_aliases": rl_aliases,
    }


def rl_extract_database_structure(rl_tree: rl_ast.AST | None) -> dict[str, rl_Any]:
    """Extract direct settings capture and get_engine wiring."""

    rl_aliases = rl_module_import_aliases(rl_tree)
    rl_body = rl_tree.body if isinstance(rl_tree, rl_ast.Module) else []
    rl_settings_capture: rl_ast.Assign | None = None
    for rl_statement in rl_direct_assignments(rl_body):
        if isinstance(rl_statement, rl_ast.Assign) and len(rl_statement.targets) == 1:
            if rl_dotted_name(rl_statement.targets[0]) == "settings":
                if rl_is_zero_arg_call(
                    rl_statement.value,
                    "app.core.config.get_settings",
                    rl_aliases,
                ):
                    rl_settings_capture = rl_statement
    rl_engine_function = next(
        (
            rl_node
            for rl_node in rl_body
            if isinstance(rl_node, rl_ast.FunctionDef) and rl_node.name == "get_engine"
        ),
        None,
    )
    rl_engine_call: rl_ast.Call | None = None
    rl_engine_url = False
    if rl_engine_function:
        for rl_statement in rl_effective_statements(rl_engine_function.body):
            for rl_node in rl_direct_call_nodes(rl_statement):
                if rl_canonical_name(rl_node.func, rl_aliases) != (
                    "sqlalchemy.ext.asyncio.create_async_engine"
                ):
                    continue
                rl_engine_call = rl_node
                rl_engine_url = bool(
                    rl_node.args
                    and rl_dotted_name(rl_node.args[0]) == "settings.database_url"
                ) or any(
                    rl_keyword.arg == "url"
                    and rl_dotted_name(rl_keyword.value) == "settings.database_url"
                    for rl_keyword in rl_node.keywords
                )
    return {
        "rl_parseable": rl_tree is not None,
        "rl_settings_capture": rl_settings_capture,
        "rl_async_engine": rl_engine_call,
        "rl_engine_url": rl_engine_url,
        "rl_database_url": rl_engine_url,
        "rl_aliases": rl_aliases,
    }


def rl_direct_call_nodes(rl_statement: rl_ast.stmt) -> list[rl_ast.Call]:
    """Inspect only direct return/call expression positions, not nested walks."""

    if isinstance(rl_statement, rl_ast.Return) and isinstance(
        rl_statement.value, rl_ast.Call
    ):
        return [rl_statement.value]
    if isinstance(rl_statement, rl_ast.Expr) and isinstance(
        rl_statement.value, rl_ast.Call
    ):
        return [rl_statement.value]
    if isinstance(rl_statement, rl_ast.Assign) and isinstance(
        rl_statement.value, rl_ast.Call
    ):
        return [rl_statement.value]
    if isinstance(rl_statement, rl_ast.AnnAssign) and isinstance(
        rl_statement.value, rl_ast.Call
    ):
        return [rl_statement.value]
    return []


def rl_extract_migrations_structure(rl_tree: rl_ast.AST | None) -> dict[str, rl_Any]:
    """Extract canonical migration imports, roles, override, and online engine."""

    rl_aliases = rl_module_import_aliases(rl_tree)
    rl_body = rl_tree.body if isinstance(rl_tree, rl_ast.Module) else []
    rl_import_events: list[str] = []
    if isinstance(rl_tree, rl_ast.Module):
        for rl_node in rl_body:
            if isinstance(rl_node, rl_ast.ImportFrom) and rl_node.module:
                rl_import_module = rl_node.module
                if rl_node.level == 1 and rl_node.module == "config":
                    rl_import_module = "app.core.config"
                elif rl_node.level == 1 and rl_node.module == "database":
                    rl_import_module = "app.core.database"
                if rl_import_module == "app.core.config":
                    rl_import_events.append("app.core.config")
                elif rl_import_module == "app.core.database":
                    rl_import_events.append("app.core.database")
                elif rl_import_module == "app.models":
                    rl_import_events.append("app.models")
            elif isinstance(rl_node, rl_ast.Import):
                for rl_alias in rl_node.names:
                    if rl_alias.name in {
                        "app.core.config",
                        "app.core.database",
                        "app.models",
                    }:
                        rl_import_events.append(rl_alias.name)
    rl_order_ok = rl_import_events[:3] == [
        "app.core.config",
        "app.core.database",
        "app.models",
    ]
    rl_settings_capture = None
    rl_config_role = None
    for rl_statement in rl_direct_assignments(rl_body):
        if (
            not isinstance(rl_statement, rl_ast.Assign)
            or len(rl_statement.targets) != 1
        ):
            continue
        rl_target = rl_dotted_name(rl_statement.targets[0])
        if rl_target == "settings" and rl_is_zero_arg_call(
            rl_statement.value, "app.core.config.get_settings", rl_aliases
        ):
            rl_settings_capture = rl_statement
        if rl_target == "config" and rl_canonical_name(
            rl_statement.value, rl_aliases
        ) == ("alembic.context.config"):
            rl_config_role = rl_statement
    rl_override_calls: list[rl_ast.Call] = []
    for rl_statement in rl_direct_assignments(rl_body):
        if not isinstance(rl_statement, rl_ast.Assign):
            continue
        if isinstance(rl_statement.value, rl_ast.Call):
            rl_override_calls.append(rl_statement.value)
    rl_valid_override_count = 0
    for rl_statement in rl_body:
        if not isinstance(rl_statement, rl_ast.Expr) or not isinstance(
            rl_statement.value, rl_ast.Call
        ):
            continue
        rl_call = rl_statement.value
        rl_call_name = rl_dotted_name(rl_call.func)
        if rl_call_name != "config.set_main_option":
            continue
        if rl_call.args or any(
            rl_keyword.arg is None for rl_keyword in rl_call.keywords
        ):
            continue
        rl_keywords = {
            rl_keyword.arg: rl_keyword.value for rl_keyword in rl_call.keywords
        }
        rl_option_node = rl_keywords.get("option")
        if rl_option_node is None:
            rl_option_node = rl_keywords.get("name")
        rl_value_node = rl_keywords.get("value")
        if rl_call.args:
            rl_option_node = rl_call.args[0] if len(rl_call.args) > 0 else None
            rl_value_node = rl_call.args[1] if len(rl_call.args) > 1 else None
        if (
            rl_literal_string(rl_option_node) == "sqlalchemy.url"
            and rl_dotted_name(rl_value_node) == "settings.database_url"
        ):
            rl_valid_override_count += 1
    rl_override_ok = rl_valid_override_count == 1
    if rl_valid_override_count == 0:
        for rl_statement in rl_body:
            if not isinstance(rl_statement, rl_ast.Expr) or not isinstance(
                rl_statement.value, rl_ast.Call
            ):
                continue
            rl_call = rl_statement.value
            if rl_dotted_name(rl_call.func) != "config.set_main_option":
                continue
            if len(rl_call.args) == 2:
                if (
                    rl_literal_string(rl_call.args[0]) == "sqlalchemy.url"
                    and rl_dotted_name(rl_call.args[1]) == "settings.database_url"
                ):
                    rl_valid_override_count += 1
            elif len(rl_call.args) == 0:
                rl_keywords = {
                    rl_keyword.arg: rl_keyword.value for rl_keyword in rl_call.keywords
                }
                rl_option_node = rl_keywords.get("option") or rl_keywords.get("name")
                rl_value_node = rl_keywords.get("value")
                if (
                    rl_literal_string(rl_option_node) == "sqlalchemy.url"
                    and rl_dotted_name(rl_value_node) == "settings.database_url"
                ):
                    rl_valid_override_count += 1
    rl_override_ok = rl_valid_override_count == 1
    rl_online_function = next(
        (
            rl_node
            for rl_node in rl_body
            if isinstance(rl_node, rl_ast.AsyncFunctionDef)
            and rl_node.name == "run_async_migrations"
        ),
        None,
    )
    rl_async_engine_call = None
    rl_async_engine_configuration = False
    if rl_online_function:
        for rl_statement in rl_effective_statements(rl_online_function.body):
            for rl_node in rl_direct_call_nodes(rl_statement):
                if rl_canonical_name(rl_node.func, rl_aliases) != (
                    "sqlalchemy.ext.asyncio.async_engine_from_config"
                ):
                    continue
                rl_async_engine_call = rl_node
                rl_async_engine_configuration = bool(rl_node.args) or any(
                    rl_keyword.arg == "configuration" for rl_keyword in rl_node.keywords
                )
    return {
        "rl_parseable": rl_tree is not None,
        "rl_config_import": "app.core.config" in rl_import_events,
        "rl_database_import": "app.core.database" in rl_import_events,
        "rl_models_import": "app.models" in rl_import_events,
        "rl_import_events": rl_import_events,
        "rl_import_order": rl_order_ok,
        "rl_settings_capture": rl_settings_capture,
        "rl_config_role": rl_config_role,
        "rl_settings_override": rl_override_ok,
        "rl_async_engine": rl_async_engine_call,
        "rl_async_online_path": rl_async_engine_configuration,
        "rl_aliases": rl_aliases,
    }


def rl_add_extraction_blocking_facts(
    rl_source: str,
    rl_structure: dict[str, rl_Any],
    rl_add_blocking: rl_Any,
) -> None:
    """Emit stable blocking facts from the same extraction used by report facts."""

    rl_required_facts = {
        "apps/api/app/core/config.py": (
            "rl_settings_source",
            "rl_env_file",
            "rl_env_prefix",
            "rl_cache",
            "rl_database_url",
            "rl_factory_return",
            "rl_factory_body",
        ),
        "apps/api/app/core/database.py": (
            "rl_settings_capture",
            "rl_async_engine",
            "rl_engine_url",
            "rl_database_url",
        ),
        "apps/api/migrations/env.py": (
            "rl_config_import",
            "rl_database_import",
            "rl_models_import",
            "rl_import_order",
            "rl_settings_capture",
            "rl_config_role",
            "rl_settings_override",
            "rl_async_engine",
            "rl_async_online_path",
        ),
    }
    for rl_fact_name in rl_required_facts.get(rl_source, ()):
        rl_value = rl_structure.get(rl_fact_name)
        rl_present = bool(rl_value)
        if not rl_present:
            rl_fact_id = (
                f"rl_import_order:{rl_source}"
                if rl_fact_name == "rl_import_order"
                else f"rl_missing_fact:{rl_safe_path(rl_source)}.{rl_fact_name}"
            )
            rl_add_blocking(
                rl_fact_id,
                rl_source,
                "canonical AST structural fact 缺失；只记录 observation，不猜测 runtime wiring。",
            )


def rl_validate_config_structure(
    rl_source: str,
    rl_text: str,
    rl_tree: rl_ast.AST | None,
    rl_add_blocking: rl_Any,
) -> None:
    """Validate minimum static settings-source facts without importing config."""

    rl_structure_facts = {
        "rl_settings_source": bool(
            rl_re.search(r"(?m)^\s*class\s+Settings\s*\(", rl_text)
            and rl_re.search(r"(?m)BaseSettings", rl_text)
        ),
        "rl_env_prefix": "SOYMUTDB_" in rl_text,
        "rl_env_file": bool(
            rl_re.search(r"(?m)env_file\s*=\s*['\"]\.env['\"]", rl_text)
        ),
        "rl_cache": "lru_cache" in rl_text,
        "rl_database_url": bool(rl_re.search(r"(?m)\bdatabase_url\b", rl_text)),
    }
    if rl_tree is None:
        rl_structure_facts = {rl_name: False for rl_name in rl_structure_facts}
    rl_add_missing_structure_facts(rl_source, rl_structure_facts, rl_add_blocking)


def rl_validate_database_structure(
    rl_source: str,
    rl_text: str,
    rl_tree: rl_ast.AST | None,
    rl_add_blocking: rl_Any,
) -> None:
    """Validate module-level settings capture and async engine references."""

    rl_structure_facts = {
        "rl_settings_capture": bool(
            rl_re.search(r"(?m)^\s*settings\s*=\s*get_settings\(\)\s*$", rl_text)
        ),
        "rl_async_engine": "create_async_engine" in rl_text,
        "rl_database_url": "settings.database_url" in rl_text,
    }
    if rl_tree is None:
        rl_structure_facts = {rl_name: False for rl_name in rl_structure_facts}
    rl_add_missing_structure_facts(rl_source, rl_structure_facts, rl_add_blocking)


def rl_validate_migrations_structure(
    rl_source: str,
    rl_text: str,
    rl_tree: rl_ast.AST | None,
    rl_add_blocking: rl_Any,
) -> None:
    """Validate migration imports, URL override, and async online path."""

    rl_imports = rl_migrations_import_facts(rl_tree)
    rl_structure_facts = {
        "rl_config_import": rl_imports["rl_config_import"],
        "rl_database_import": rl_imports["rl_database_import"],
        "rl_models_import": rl_imports["rl_models_import"],
        "rl_settings_override": bool(
            rl_re.search(
                r"config\.set_main_option\(\s*['\"]sqlalchemy\.url['\"]\s*,\s*settings\.database_url\s*\)",
                rl_text,
            )
        ),
        "rl_async_engine": "async_engine_from_config" in rl_text,
        "rl_async_online_path": bool(
            rl_re.search(r"(?m)^\s*async def\s+run_async_migrations", rl_text)
        ),
    }
    if rl_tree is None:
        rl_structure_facts = {rl_name: False for rl_name in rl_structure_facts}
    rl_add_missing_structure_facts(rl_source, rl_structure_facts, rl_add_blocking)


def rl_migrations_import_facts(rl_tree: rl_ast.AST | None) -> dict[str, bool]:
    """Extract migration import presence and retain source order separately."""

    rl_imports: list[str] = []
    if isinstance(rl_tree, rl_ast.Module):
        for rl_node in rl_tree.body:
            if isinstance(rl_node, rl_ast.ImportFrom) and rl_node.module:
                rl_imports.append(rl_node.module)
            elif isinstance(rl_node, rl_ast.Import):
                rl_imports.extend(rl_alias.name for rl_alias in rl_node.names)
    return {
        "rl_config_import": "app.core.config" in rl_imports,
        "rl_database_import": "app.core.database" in rl_imports,
        "rl_models_import": "app.models" in rl_imports,
    }


def rl_node_facts(
    rl_package: dict[str, rl_Any] | None, rl_readme: str | None
) -> dict[str, rl_Any]:
    """Collect Node and pnpm requirements from package metadata."""

    if rl_package is None:
        return {
            "rl_present": False,
            "rl_node_requirement": None,
            "rl_pnpm_requirement": None,
            "rl_package_manager": None,
        }
    rl_engines = rl_package.get("engines", {})
    if not isinstance(rl_engines, dict):
        rl_engines = {}
    rl_node_requirement = rl_engines.get("node")
    rl_pnpm_requirement = rl_engines.get("pnpm")
    rl_package_manager = rl_package.get("packageManager")
    return {
        "rl_present": True,
        "rl_node_requirement": rl_safe_metadata_value(rl_node_requirement),
        "rl_pnpm_requirement": rl_safe_metadata_value(rl_pnpm_requirement),
        "rl_package_manager": rl_safe_metadata_value(rl_package_manager),
        "rl_readme_present": rl_readme is not None,
    }


def rl_safe_metadata_value(rl_value: rl_Any) -> str | None:
    """Keep version-like metadata and redact everything else."""

    if not isinstance(rl_value, str):
        return None
    if rl_has_sensitive_shape(rl_value):
        return "<redacted>"
    return rl_value


def rl_compose_facts(
    rl_compose_text: str | None,
    rl_compose_dev_text: str | None,
) -> dict[str, rl_Any]:
    """Collect Compose images, build references, service names, and key names."""

    if rl_compose_text is None:
        return {
            "rl_present": False,
            "rl_services": [],
            "rl_images": [],
            "rl_postgresql_image": None,
            "rl_build_dockerfiles": [],
            "rl_sensitive_environment_keys": [],
        }
    rl_images = [
        rl_emit_source_value(rl_image, "image")
        for rl_image in sorted(set(rl_IMAGE_RE.findall(rl_compose_text)))
    ]
    rl_services = sorted(set(rl_SERVICE_RE.findall(rl_compose_text)))
    rl_postgres_block = rl_service_block(rl_compose_text, "postgres")
    rl_postgresql_match = rl_IMAGE_RE.search(rl_postgres_block or "")
    rl_environment_keys = sorted(
        set(
            rl_match.group(1)
            for rl_match in rl_re.finditer(
                r"(?m)^\s{6}([A-Z][A-Z0-9_]+):", rl_compose_text
            )
            if rl_match.group(1)
            in {
                "POSTGRES_PASSWORD",
                "CLICKHOUSE_PASSWORD",
                "REDIS_PASSWORD",
                "JWT_SECRET",
                "S3_SECRET_KEY",
                "MINIO_ROOT_PASSWORD",
                "GRAFANA_PASSWORD",
            }
        )
    )
    rl_dev_services = sorted(set(rl_SERVICE_RE.findall(rl_compose_dev_text or "")))
    return {
        "rl_present": True,
        "rl_services": rl_services,
        "rl_images": rl_images,
        "rl_postgresql_image": (
            rl_emit_source_value(rl_postgresql_match.group(1), "image")
            if rl_postgresql_match
            else None
        ),
        "rl_build_dockerfiles": [
            rl_emit_source_value(rl_dockerfile, "relative_path")
            for rl_dockerfile in sorted(set(rl_DOCKERFILE_RE.findall(rl_compose_text)))
        ],
        "rl_sensitive_environment_keys": rl_environment_keys,
        "rl_dev_present": rl_compose_dev_text is not None,
        "rl_dev_services": rl_dev_services,
        "rl_values_emitted": False,
        "rl_why": "Compose 环境值只保留 key/存在性；避免把 password、token 或完整 URL 写入 facts。",
    }


def rl_service_block(rl_text: str, rl_service_name: str) -> str | None:
    """Return a bounded, indentation-based service block for simple YAML facts."""

    rl_match = rl_re.search(
        rf"(?ms)^  {rl_re.escape(rl_service_name)}:\s*\n(.*?)(?=^  [A-Za-z0-9][A-Za-z0-9_-]*:\s*$|\Z)",  # noqa: E501
        rl_text,
    )
    return rl_match.group(1) if rl_match else None


def rl_docker_facts(rl_sources: dict[str, str | None]) -> dict[str, rl_Any]:
    """Collect Docker base images and redacted entrypoint tokens."""

    rl_records: list[dict[str, rl_Any]] = []
    rl_all_images: dict[str, str | dict[str, rl_Any]] = {}
    for rl_relative_path in sorted(rl_sources):
        if not rl_Path(rl_relative_path).name.lower().startswith("dockerfile"):
            continue
        rl_text = rl_sources.get(rl_relative_path)
        if rl_text is None:
            continue
        rl_images = [
            rl_emit_source_value(rl_image, "image")
            for rl_image in sorted(set(rl_FROM_RE.findall(rl_text)))
        ]
        for rl_image in rl_images:
            rl_all_images[rl_source_value_sort_key(rl_image)] = rl_image
        rl_entrypoints = rl_extract_entrypoints(rl_text)
        rl_records.append(
            {
                "rl_file": rl_relative_path,
                "rl_images": rl_images,
                "rl_entrypoints": [
                    rl_emit_source_value(rl_entrypoint, "entrypoint")
                    for rl_entrypoint in rl_entrypoints
                ],
            }
        )
    return {
        "rl_files": rl_records,
        "rl_image_refs": [rl_all_images[rl_key] for rl_key in sorted(rl_all_images)],
        "rl_values_emitted": False,
    }


def rl_extract_entrypoints(rl_text: str) -> list[str]:
    """Extract only executable/module-shaped tokens from Docker or Compose text."""

    rl_values: set[str] = set()
    for rl_match in rl_re.finditer(
        r"(?i)\buvicorn\s+([A-Za-z0-9_.:-]+)|\bcelery\s+-A\s+([A-Za-z0-9_.:-]+)",
        rl_text,
    ):
        rl_values.update(rl_value for rl_value in rl_match.groups() if rl_value)
    for rl_match in rl_re.finditer(
        r'(?i)"uvicorn"\s*,\s*"([A-Za-z0-9_.:-]+)"', rl_text
    ):
        rl_values.add(rl_match.group(1))
    for rl_match in rl_re.finditer(
        r'(?i)"celery"\s*,\s*"-A"\s*,\s*"([A-Za-z0-9_.:-]+)"', rl_text
    ):
        rl_values.add(rl_match.group(1))
    return sorted(rl_values)


def rl_extract_python_string_assignments(
    rl_tree: rl_ast.AST | dict[str, rl_Any] | None,
) -> dict[str, str]:
    """Extract literal string defaults from a parsed Python module."""

    if isinstance(rl_tree, dict):
        rl_settings_body = rl_tree.get("rl_settings_body", [])
        rl_result: dict[str, str] = {}
        for rl_statement in rl_direct_assignments(rl_settings_body):
            rl_name: str | None = None
            rl_value_node: rl_ast.AST | None = None
            if isinstance(rl_statement, rl_ast.AnnAssign):
                rl_name = rl_dotted_name(rl_statement.target)
                rl_value_node = rl_statement.value
            elif (
                isinstance(rl_statement, rl_ast.Assign)
                and len(rl_statement.targets) == 1
            ):
                rl_name = rl_dotted_name(rl_statement.targets[0])
                rl_value_node = rl_statement.value
            if rl_name is None or rl_value_node is None:
                continue
            rl_literal = rl_literal_string(rl_value_node)
            if rl_literal is not None:
                rl_result[rl_name] = rl_literal
        return rl_result
    if rl_tree is None:
        return {}
    rl_result: dict[str, str] = {}
    for rl_node in rl_ast.walk(rl_tree):
        rl_name: str | None = None
        rl_value_node: rl_ast.AST | None = None
        if isinstance(rl_node, rl_ast.Assign) and len(rl_node.targets) == 1:
            if isinstance(rl_node.targets[0], rl_ast.Name):
                rl_name = rl_node.targets[0].id
                rl_value_node = rl_node.value
        elif isinstance(rl_node, rl_ast.AnnAssign) and isinstance(
            rl_node.target, rl_ast.Name
        ):
            rl_name = rl_node.target.id
            rl_value_node = rl_node.value
        if rl_name is None or rl_value_node is None:
            continue
        try:
            rl_literal = rl_ast.literal_eval(rl_value_node)
        except (ValueError, TypeError, SyntaxError):
            continue
        if isinstance(rl_literal, str):
            rl_result[rl_name] = rl_literal
    return rl_result


def rl_config_facts(
    rl_root: rl_Path,
    rl_config_structure: dict[str, rl_Any],
    rl_config_defaults: dict[str, str],
    rl_database_url_default: str | None,
    rl_add_difference: rl_Any,
) -> dict[str, rl_Any]:
    """Record settings source/caching/default risk without reading ``.env``."""

    rl_env_prefix_match = rl_config_structure.get("rl_env_prefix")
    rl_env_file_match = rl_config_structure.get("rl_env_file")
    rl_lru_cache_present = rl_config_structure.get("rl_cache")
    rl_env_path = rl_root / ".env"
    rl_env_present = rl_env_path.is_file()
    if not rl_env_present:
        rl_add_difference(
            "rl_missing_optional_file:.env",
            "apps/api/app/core/config.py",
            "config 声明读取 .env，但仓库根目录没有该可选文件；运行时环境仍可能通过外部注入提供值。",  # noqa: E501
        )
    if rl_env_path.exists() and not rl_env_path.is_file():
        rl_add_difference(
            "rl_invalid_optional_file:.env",
            ".env",
            ".env 路径存在但不是普通文件，collector 不读取其内容。",
        )
    if not rl_env_prefix_match:
        rl_add_difference(
            "rl_missing_fact:config.env_prefix",
            "apps/api/app/core/config.py",
            "未观察到 SOYMUTDB_ 前缀，不能假设环境变量命名空间。",
        )
    if not rl_env_file_match:
        rl_add_difference(
            "rl_missing_fact:config.env_file",
            "apps/api/app/core/config.py",
            "未观察到 .env 配置声明，不能假设 dotenv 来源。",
        )
    if not rl_lru_cache_present:
        rl_add_difference(
            "rl_missing_fact:config.lru_cache",
            "apps/api/app/core/config.py",
            "未观察到 settings cache；不能假设进程内配置会被缓存。",
        )
    rl_secret_fields = sorted(
        rl_name
        for rl_name in rl_config_defaults
        if rl_re.search(r"(?i)(password|secret|token|access_key|api_key)", rl_name)
    )
    return {
        "rl_env_prefix": "SOYMUTDB_" if rl_env_prefix_match else None,
        "rl_env_file": {
            "rl_path": ".env",
            "rl_declared": bool(rl_env_file_match),
            "rl_present": rl_env_present,
            "rl_content_emitted": False,
        },
        "rl_lru_cache": bool(rl_lru_cache_present),
        "rl_database_url_default": rl_default_url_fact(rl_database_url_default),
        "rl_secret_default_fields": rl_secret_fields,
        "rl_default_values_emitted": False,
        "rl_why": "SOYMUTDB_、.env 与 lru_cache 会改变配置来源/时机；A0 只记录风险，不切换进程配置。",  # noqa: E501
        "rl_parseable": bool(rl_config_structure.get("rl_parseable")),
        "rl_settings_factory": {
            "rl_present": bool(rl_config_structure.get("rl_factory")),
            "rl_returns_settings": bool(rl_config_structure.get("rl_factory_body")),
        },
    }


def rl_default_url_fact(rl_default_url: str | None) -> dict[str, rl_Any]:
    """Classify a default URL while never returning its complete value."""

    if rl_default_url is None:
        return {
            "rl_present": False,
            "rl_classification": "missing",
            "rl_redacted_value": None,
        }
    return rl_url_metadata(rl_default_url)


def rl_database_facts(rl_database_structure: dict[str, rl_Any]) -> dict[str, rl_Any]:
    """Record module-level settings capture and lazy async engine wiring."""

    rl_module_capture = bool(rl_database_structure.get("rl_settings_capture"))
    rl_async_engine = bool(rl_database_structure.get("rl_async_engine"))
    rl_database_url_reference = bool(rl_database_structure.get("rl_engine_url"))
    return {
        "rl_parseable": bool(rl_database_structure.get("rl_parseable")),
        "rl_module_level_settings_capture": rl_module_capture,
        "rl_create_async_engine": rl_async_engine,
        "rl_database_url_from_captured_settings": rl_database_url_reference,
        "rl_settings_capture_scope": "module" if rl_module_capture else "unobserved",
        "rl_why": "module-level settings capture fixes the observed settings object before lazy engine creation; A0 does not import it to test behavior.",  # noqa: E501
    }


def rl_migrations_facts(
    rl_migrations_structure: dict[str, rl_Any],
) -> dict[str, rl_Any]:
    """Record Alembic import order, settings override, and async engine path."""

    rl_imports = rl_migrations_structure.get("rl_import_events", [])
    rl_import_order = (
        rl_imports[:3] if rl_migrations_structure.get("rl_import_order") else rl_imports
    )
    return {
        "rl_parseable": bool(rl_migrations_structure.get("rl_parseable")),
        "rl_import_order": rl_import_order,
        "rl_imports_settings": "app.core.config" in rl_imports,
        "rl_imports_database_base": "app.core.database" in rl_imports,
        "rl_imports_models": "app.models" in rl_imports,
        "rl_settings_override": bool(
            rl_migrations_structure.get("rl_settings_override")
        ),
        "rl_async_engine_from_config": bool(
            rl_migrations_structure.get("rl_async_engine")
        ),
        "rl_async_engine_online_path": bool(
            rl_migrations_structure.get("rl_async_online_path")
        ),
        "rl_why": "env.py 以 cached settings 覆盖 ini URL，再构造 async engine；这解释迁移配置来源差异，但不证明目标连接可用。",  # noqa: E501
    }


def rl_alembic_facts(
    rl_alembic_text: str,
    rl_script_location: str | None,
    rl_ini_url: str | None,
    rl_root: rl_Path,
    rl_add_difference: rl_Any,
) -> dict[str, rl_Any]:
    """Record relative migration path and poisoned development URL metadata."""

    rl_is_relative = (
        bool(rl_script_location) and not rl_Path(rl_script_location or "").is_absolute()
    )
    rl_resolved_path = None
    if rl_script_location and rl_is_relative:
        rl_resolved_path = rl_safe_path(str(rl_Path("apps/api") / rl_script_location))
        if not (rl_root / rl_resolved_path).exists():
            rl_add_difference(
                "rl_missing_path:alembic.script_location",
                "apps/api/alembic.ini",
                "相对 script_location 指向的目录不存在；A0 不创建 migration 目录。",
                rl_resolved_path,
            )
    elif rl_script_location:
        rl_add_difference(
            "rl_absolute_path:alembic.script_location",
            "apps/api/alembic.ini",
            "script_location 不是相对路径，cwd 变化不会按预期解析；A0 只记录差异。",
            rl_script_location,
        )
    rl_url_fact = rl_default_url_fact(rl_ini_url)
    if rl_ini_url and rl_url_fact["rl_classification"] == "poisoned_default":
        rl_url_fact["rl_why"] = (
            "alembic.ini 的 password-bearing development URL 只能作为 poisoned/default fact，不能作为 target fallback。"  # noqa: E501
        )
    return {
        "rl_script_location": {
            "rl_value": (
                rl_emit_source_value(rl_script_location, "relative_path")
                if rl_script_location
                else None
            ),
            "rl_is_relative": rl_is_relative,
            "rl_resolved_project_path": (
                rl_emit_source_value(rl_resolved_path, "relative_path")
                if rl_resolved_path
                else None
            ),
        },
        "rl_sqlalchemy_url": rl_url_fact,
        "rl_values_emitted": False,
        "rl_why": "relative script_location 依赖 Alembic/API cwd；ini 中的开发 URL 不代表实际 settings 或安全目标。",  # noqa: E501
    }


def rl_execution_context_facts(
    rl_root: rl_Path,
    rl_sources: dict[str, str | None],
) -> list[dict[str, rl_Any]]:
    """Return the four required cwd rows with only relative paths."""

    rl_contexts = [
        {
            "rl_context": "OpenAPI/API cwd",
            "rl_cwd": "apps/api",
            "rl_entrypoint": "app.main:app",
            "rl_source": "README.md / infra/docker/Dockerfile.api",
            "rl_cwd_exists": (rl_root / "apps/api").is_dir(),
        },
        {
            "rl_context": "Worker/root cwd",
            "rl_cwd": ".",
            "rl_entrypoint": "soymutdb_worker.main:celery_app",
            "rl_source": "apps/worker/README.md / docker-compose.yml",
            "rl_cwd_exists": rl_root.is_dir(),
        },
        {
            "rl_context": "Alembic/API cwd",
            "rl_cwd": "apps/api",
            "rl_entrypoint": "migrations/env.py",
            "rl_source": "apps/api/alembic.ini / apps/api/migrations/env.py",
            "rl_cwd_exists": (rl_root / "apps/api").is_dir(),
        },
        {
            "rl_context": "A0/root cwd",
            "rl_cwd": ".",
            "rl_entrypoint": "tools.a0.rl_collect_runtime_facts",
            "rl_source": "tools/a0/rl_collect_runtime_facts.py",
            "rl_cwd_exists": rl_root.is_dir(),
        },
    ]
    return rl_contexts


def rl_known_path_facts(rl_root: rl_Path) -> dict[str, rl_Any]:
    """Record path existence without reading environment or application state."""

    rl_paths = {
        "rl_api_source": "apps/api/app",
        "rl_worker_source": "apps/worker/src/soymutdb_worker",
        "rl_migrations_source": "apps/api/migrations",
        "rl_api_entrypoint_source": "apps/api/app/main.py",
        "rl_worker_entrypoint_source": "apps/worker/src/soymutdb_worker/main.py",
        "rl_a0_collector_source": "tools/a0/rl_collect_runtime_facts.py",
    }
    return {
        rl_key: {
            "rl_path": rl_value,
            "rl_exists": (rl_root / rl_value).exists(),
        }
        for rl_key, rl_value in rl_paths.items()
    }


def rl_path_drift_facts(
    rl_root: rl_Path,
    rl_sources: dict[str, str | None],
    rl_compose_text: str | None,
    rl_compose_dev_text: str | None,
    rl_add_difference: rl_Any,
) -> list[dict[str, rl_Any]]:
    """Find known source/entrypoint wiring differences without fixing them."""

    rl_drifts: list[dict[str, rl_Any]] = []

    def rl_add_drift(
        rl_drift_id: str,
        rl_source: str,
        rl_observed: str,
        rl_expected: str,
        rl_why: str,
        rl_source_kind: str,
    ) -> None:
        rl_observed_safe = rl_emit_source_value(rl_observed, rl_source_kind)
        rl_expected_safe = rl_emit_source_value(rl_expected, rl_source_kind)
        rl_drifts.append(
            {
                "rl_drift_id": rl_drift_id,
                "rl_source": rl_source,
                "rl_observed": rl_observed_safe,
                "rl_expected": rl_expected_safe,
                "rl_why": rl_why,
            }
        )
        rl_add_difference(
            f"rl_path_drift:{rl_drift_id}",
            rl_source,
            rl_why,
            "observed="
            + rl_json.dumps(rl_observed_safe, ensure_ascii=False, sort_keys=True)
            + "; expected="
            + rl_json.dumps(rl_expected_safe, ensure_ascii=False, sort_keys=True),
        )

    rl_api_actual = (
        "app.main:app" if (rl_root / "apps/api/app/main.py").is_file() else None
    )
    rl_worker_actual = (
        "soymutdb_worker.main:celery_app"
        if (rl_root / "apps/worker/src/soymutdb_worker/main.py").is_file()
        else None
    )
    rl_entrypoint_observations: list[tuple[str, str]] = []
    for rl_relative_path, rl_text in sorted(rl_sources.items()):
        if rl_text is None:
            continue
        for rl_entrypoint in rl_extract_entrypoints(rl_text):
            rl_entrypoint_observations.append((rl_relative_path, rl_entrypoint))
    for rl_source, rl_entrypoint in rl_entrypoint_observations:
        if (
            rl_api_actual
            and rl_entrypoint.endswith(":app")
            and rl_entrypoint != rl_api_actual
        ):
            rl_add_drift(
                f"api-entrypoint:{rl_safe_path(rl_source)}",
                rl_source,
                rl_entrypoint,
                rl_api_actual,
                "API 入口模块名与实际 app/main.py 路径不同，cwd 或 package 安装方式会改变可导入性。",  # noqa: E501
                "entrypoint",
            )
        if rl_worker_actual and rl_entrypoint.startswith("soymutdb_worker."):
            if rl_entrypoint not in {rl_worker_actual, "soymutdb_worker.main"}:
                rl_add_drift(
                    f"worker-entrypoint:{rl_safe_path(rl_source)}",
                    rl_source,
                    rl_entrypoint,
                    rl_worker_actual,
                    "Worker 入口必须和 src package 的实际模块/应用符号一致；A0 不修改启动命令。",
                    "entrypoint",
                )

    for rl_source, rl_text in (
        ("docker-compose.dev.yml", rl_compose_dev_text),
        ("docker-compose.yml", rl_compose_text),
    ):
        if rl_text is None:
            continue
        for rl_mount in rl_MOUNT_RE.findall(rl_text):
            if not rl_mount.startswith("./"):
                continue
            rl_mount_path = rl_mount[2:]
            if not (rl_root / rl_mount_path).exists():
                rl_replacement = None
                if (
                    rl_mount_path == "apps/api/src"
                    and (rl_root / "apps/api/app").exists()
                ):
                    rl_replacement = "apps/api/app"
                elif (
                    rl_mount_path == "apps/api/alembic"
                    and (rl_root / "apps/api/migrations").exists()
                ):
                    rl_replacement = "apps/api/migrations"
                if rl_replacement:
                    rl_add_drift(
                        f"mount:{rl_mount_path}",
                        rl_source,
                        rl_mount_path,
                        rl_replacement,
                        "Compose source mount 指向不存在的旧目录；记录路径漂移而不创建别名目录。",
                        "relative_path",
                    )

    rl_dev_services = set(rl_SERVICE_RE.findall(rl_compose_dev_text or ""))
    rl_prod_services = set(rl_SERVICE_RE.findall(rl_compose_text or ""))
    if "worker" in rl_dev_services and "worker" not in rl_prod_services:
        rl_add_drift(
            "service:worker",
            "docker-compose.dev.yml",
            "worker",
            "worker-default/worker-blast/worker-ingestion",
            "开发 Compose 使用聚合 worker 名称而生产 Compose 使用分队列服务，不能互换地推断 entrypoint。",  # noqa: E501
            "relative_path",
        )
    return sorted(rl_drifts, key=lambda rl_item: rl_item["rl_drift_id"])


def rl_normalize_command(
    rl_command_name: str,
    rl_command: rl_Sequence[str],
) -> tuple[str, ...] | None:
    """Validate an opt-in version command and reject arbitrary operations."""

    if not isinstance(rl_command_name, str) or not rl_command_name:
        return None
    if not isinstance(rl_command, (list, tuple)) or len(rl_command) != 2:
        return None
    rl_values = tuple(rl_command)
    for rl_value in rl_values:
        if not isinstance(rl_value, str) or not rl_value:
            return None
        if any(ord(rl_character) < 32 for rl_character in rl_value):
            return None
    if rl_values[-1] not in rl_VERSION_FLAGS:
        return None
    return rl_values


def rl_collect_command_facts(
    rl_root: rl_Path,
    rl_command_versions: rl_Mapping[str, rl_Sequence[str]] | None,
    rl_add_blocking: rl_Any,
    rl_add_difference: rl_Any,
    rl_command_runner: rl_Callable[..., rl_Any] | None = None,
) -> list[dict[str, rl_Any]]:
    """Run only explicitly supplied shell-free version commands."""

    if not rl_command_versions:
        return []
    rl_results: list[dict[str, rl_Any]] = []
    for rl_name in sorted(rl_command_versions):
        rl_command = rl_command_versions[rl_name]
        rl_safe_name = rl_safe_command_name(rl_name)
        rl_normalized = rl_normalize_command(rl_name, rl_command)
        if rl_normalized is None:
            rl_add_blocking(
                f"rl_command_invalid:{rl_safe_name}",
                "command-version input",
                "command-version 只允许 shell-free 的 version flag；拒绝任意 argv/SQL/target 输入。",  # noqa: E501
            )
            rl_results.append({"rl_name": rl_safe_name, "rl_status": "invalid"})
            continue
        rl_safe_command = ["<redacted-executable>", rl_normalized[-1]]
        rl_runner = rl_command_runner or rl_subprocess.run
        try:
            rl_completed = rl_runner(
                rl_normalized,
                cwd=str(rl_root),
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (
            FileNotFoundError,
            PermissionError,
            OSError,
            rl_subprocess.TimeoutExpired,
        ) as rl_exc:
            rl_add_blocking(
                f"rl_command_unavailable:{rl_safe_name}",
                "command-version input",
                "command unavailable/timeout；不能猜测版本，也不保存 command output。",
                type(rl_exc).__name__,
            )
            rl_results.append(
                {
                    "rl_name": rl_safe_name,
                    "rl_command": rl_safe_command,
                    "rl_status": "unavailable",
                }
            )
            continue
        rl_output = "\n".join(
            rl_part
            for rl_part in (rl_completed.stdout or "", rl_completed.stderr or "")
            if rl_part
        )
        rl_version_match = rl_VERSION_RE.search(rl_output)
        rl_status = "available" if rl_completed.returncode == 0 else "failed"
        rl_result: dict[str, rl_Any] = {
            "rl_name": rl_safe_name,
            "rl_command": rl_safe_command,
            "rl_status": rl_status,
            "rl_returncode": rl_completed.returncode,
            "rl_version": rl_version_match.group(0) if rl_version_match else None,
            "rl_output_sha256": rl_digest_text(rl_output),
            "rl_output_emitted": False,
        }
        if rl_completed.returncode != 0:
            rl_add_blocking(
                f"rl_command_failed:{rl_safe_name}",
                "command-version input",
                "version command 返回非零，不能把失败输入当作 observed version。",
                str(rl_completed.returncode),
            )
        elif rl_version_match is None:
            rl_add_blocking(
                f"rl_command_no_version:{rl_safe_name}",
                "command-version input",
                "version command 未产生可识别版本号，不能把未知版本当作 observed fact。",
            )
        rl_results.append(rl_result)
    return rl_results


def rl_safe_command_name(rl_name: str) -> str:
    """Keep command labels opaque when a caller supplies unsafe text."""

    if rl_re.fullmatch(
        r"[A-Za-z0-9_.-]+", rl_name
    ) and not rl_SECRET_ASSIGNMENT_RE.search(rl_name):
        return rl_name
    return "<redacted-command-name>"


def rl_parse_cli_commands(
    rl_specs: list[str],
) -> dict[str, tuple[str, ...]]:
    """Parse ``NAME=EXECUTABLE`` CLI inputs and append ``--version`` safely."""

    rl_commands: dict[str, tuple[str, ...]] = {}
    for rl_spec in rl_specs:
        rl_name, rl_separator, rl_executable = rl_spec.partition("=")
        if rl_separator:
            rl_commands[rl_name] = (rl_executable, "--version")
        else:
            rl_commands[rl_spec] = ("", "--version")
    return rl_commands


def rl_main(rl_argv: rl_Sequence[str] | None = None) -> int:
    """CLI entrypoint for writing an explicitly requested JSON report."""

    rl_parser = rl_argparse.ArgumentParser(description=__doc__)
    rl_parser.add_argument("--project-root", required=True, dest="rl_project_root")
    rl_parser.add_argument("--output", required=True, dest="rl_output")
    rl_parser.add_argument(
        "--command-version",
        action="append",
        default=[],
        dest="rl_command_versions",
        metavar="NAME=EXECUTABLE",
        help="optional safe version command; executable is invoked with --version",
    )
    rl_args = rl_parser.parse_args(rl_argv)
    rl_report = rl_collect_runtime_facts(
        rl_args.rl_project_root,
        rl_parse_cli_commands(rl_args.rl_command_versions),
    )
    rl_output_path = rl_Path(rl_args.rl_output).expanduser()
    rl_output_path.parent.mkdir(parents=True, exist_ok=True)
    rl_output_path.write_text(
        rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    # 中文 why：报告必须先完整落盘，blocking fact 再决定 CLI 状态；避免
    # 调用方把不完整/不安全的成功码误当成可消费 evidence。
    return 1 if rl_report["rl_blocking_facts"] else 0


if __name__ == "__main__":
    raise SystemExit(rl_main())
