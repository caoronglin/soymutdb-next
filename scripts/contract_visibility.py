#!/usr/bin/env python3
"""Reconcile handwritten api-client routes with the exported OpenAPI paths."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_CALL_RE = re.compile(r"\bhttp\.(get|post|put|patch|delete)\s*<[^>]*>\s*\(\s*[`\"]([^`\"]+)")
_CALL_RE_PLAIN = re.compile(r"\bhttp\.(get|post|put|patch|delete)\s*\(\s*[`\"]([^`\"]+)")
_TEMPLATE_RE = re.compile(r"\$\{[^}]+\}")


def _normalize_route(route: str) -> str:
    route = _TEMPLATE_RE.sub("{id}", route)
    return route.split("?", 1)[0].rstrip("/") or "/"


def _route_key(method: str, route: str) -> str:
    return f"{method.upper()} {_normalize_route(route)}"


def _load_baseline(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def check_contract_visibility(
    *, schema_path: Path, client_paths: list[Path], baseline_path: Path
) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    openapi_routes = {
        _route_key(method, path.removeprefix("/api/v1"))
        for path, item in schema.get("paths", {}).items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    client_routes: set[str] = set()
    for path in client_paths:
        text = path.read_text(encoding="utf-8")
        matches = _CALL_RE.findall(text) + _CALL_RE_PLAIN.findall(text)
        client_routes.update(_route_key(method, route) for method, route in matches)

    drift = sorted(client_routes - openapi_routes)
    baseline = _load_baseline(baseline_path)
    baseline_debt = sorted(set(drift) & set(baseline))
    new_drift = sorted(set(drift) - set(baseline))
    return {
        "status": "PASS" if not new_drift else "FAIL",
        "openapi_routes": sorted(openapi_routes),
        "client_routes": sorted(client_routes),
        "drift": drift,
        "baseline_debt": baseline_debt,
        "new_drift": new_drift,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--client-root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    args = parser.parse_args(argv)
    paths = sorted(
        path
        for path in args.client_root.glob("*.ts")
        if not path.name.endswith(".test.ts") and "/generated/" not in str(path)
    )
    report = check_contract_visibility(
        schema_path=args.schema, client_paths=paths, baseline_path=args.baseline
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["baseline_debt"]:
        print(f"CONTRACT DEBT: {len(report['baseline_debt'])} allowlisted route(s)", file=sys.stderr)
    if report["new_drift"]:
        print("NEW CONTRACT DRIFT:", file=sys.stderr)
        print("\n".join(f"- {entry}" for entry in report["new_drift"]), file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
