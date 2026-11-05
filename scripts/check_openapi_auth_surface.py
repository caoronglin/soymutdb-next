#!/usr/bin/env python3
"""Pin the published OpenAPI authentication surface against committed bytes.

``check-contract.sh`` proves that a *fresh* export equals the committed
snapshot. That is self-consistency, not correctness: reverting ``app/main.py``
and ``packages/api-client/openapi.json`` together drops the security schemes
and per-operation ``security`` while the export still equals the snapshot, so
the gate stays green. The live-export test (``apps/api/tests/
test_openapi_contract.py``) only asserts two schemes are *present* and two
hardcoded admin paths are secured; it needs a 3.15 venv and cannot run in the
offline contracts layer.

This guard reads committed bytes only -- the snapshot and the three source
files that actually decide the surface. It needs no API import, no 3.15 venv,
no wheel, and no database. Run directly or via ``--self-test``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
MAIN = ROOT / "apps" / "api" / "app" / "main.py"
DEPS = ROOT / "apps" / "api" / "app" / "api" / "v1" / "deps.py"
AUTH = ROOT / "apps" / "api" / "app" / "api" / "v1" / "auth.py"
CONFIG = ROOT / "apps" / "api" / "app" / "core" / "config.py"

METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

# The refresh cookie name is a runtime setting, not a hardcoded string in the
# snapshot. Derive it from the committed default so the two cannot drift.
_COOKIE_NAME = re.compile(r'refresh_cookie_name:\s*str\s*=\s*"([^"]+)"')

# The three auth bootstrap operations are deliberately public: they are how a
# client obtains (or rotates) the credentials the protected surface needs.
PUBLIC_AUTH = {
    ("/api/v1/auth/register", "post"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/refresh", "post"),
}

# Reviewed literal floor: the non-admin operations that must require
# HTTPBearer in the published snapshot. This is NOT derived from
# openapi.json -- a co-revert that drops `security` from these ops and
# re-exports the snapshot keeps every export==snapshot gate green, and
# the old `protected < len(admin)` bound can never fire because admin
# is a subset of protected. Any deliberate change is an explicit,
# reviewable edit to this set in the same commit as the re-export.
NON_ADMIN_PROTECTED = frozenset({
    ("/api/v1/analyses", "get"),
    ("/api/v1/analyses/uploads", "post"),
    ("/api/v1/analyses/{analysis_type}/submit", "post"),
    ("/api/v1/analyses/{job_id}", "get"),
    ("/api/v1/analyses/{job_id}/download", "get"),
    ("/api/v1/auth/change-password", "post"),
    ("/api/v1/auth/logout", "post"),
    ("/api/v1/auth/me", "get"),
    ("/api/v1/blast/databases/{database_id}", "patch"),
    ("/api/v1/blast/index-builds", "post"),
    ("/api/v1/blast/index-builds/{build_id}", "get"),
    ("/api/v1/blast/jobs", "get"),
    ("/api/v1/blast/jobs", "post"),
    ("/api/v1/blast/jobs/{job_id}", "get"),
    ("/api/v1/blast/jobs/{job_id}/cancel", "post"),
    ("/api/v1/blast/jobs/{job_id}/hits/{subject_id}/genome-target", "get"),
    ("/api/v1/blast/jobs/{job_id}/results", "get"),
    ("/api/v1/blast/jobs/{job_id}/retry", "post"),
    ("/api/v1/comparative/artifacts", "post"),
    ("/api/v1/content/snapshot", "get"),
    ("/api/v1/exports/query", "post"),
    ("/api/v1/gwas/submit", "post"),
    ("/api/v1/gwas/uploads", "post"),
    ("/api/v1/gwas/{job_id}", "get"),
    ("/api/v1/gwas/{job_id}/results", "get"),
    ("/api/v1/notifications", "get"),
    ("/api/v1/notifications/read", "post"),
    ("/api/v1/notifications/unread-count", "get"),
    ("/api/v1/releases", "get"),
    ("/api/v1/releases/{release_id}", "get"),
    ("/api/v1/search/internal", "get"),
    ("/api/v1/seeds/requests", "get"),
    ("/api/v1/seeds/requests/{request_id}", "patch"),
    ("/api/v1/site/about", "get"),
    ("/api/v1/site/branding", "get"),
    ("/api/v1/site/content", "get"),
    ("/api/v1/site/footer", "get"),
    ("/api/v1/site/home", "get"),
    ("/api/v1/table-views/{kind}", "get"),
    ("/api/v1/tracks", "get"),
    ("/api/v1/tracks/jbrowse-config", "get"),
    ("/api/v1/tracks/{track_id}", "get"),
    ("/api/v1/tracks/{track_id}/signed-url", "get"),
    ("/api/v1/variants/export", "post"),
    ("/api/v1/variants/export/{export_id}", "get"),
    ("/api/v1/variants/export/{export_id}/download", "get"),
    ("/api/v1/variants/export/{export_id}/manifest", "get"),
    ("/api/v1/widget/{name}", "get"),
})
# pinned count: 48 non-admin protected, checked below


def _operations(document: dict) -> list[tuple[str, str, dict]]:
    out = []
    for path, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                out.append((path, method, operation))
    return out


def _bearer(operation: dict) -> bool:
    """Whether the operation declares the HTTPBearer requirement."""
    return any("HTTPBearer" in req for req in operation.get("security", []))


def failures(snapshot: str, main: str, deps: str, auth: str, config: str) -> list[str]:
    found: list[str] = []
    document = json.loads(snapshot)
    schemes = document.get("components", {}).get("securitySchemes", {})

    # 1. Both schemes must be declared with the exact runtime shape. Presence
    #    alone (what the live-export test asserts) is not a contract: a scheme
    #    retyped as http/basic or with a different cookie name still "exists".
    bearer = schemes.get("HTTPBearer")
    if not isinstance(bearer, dict) or bearer.get("type") != "http" or bearer.get("scheme") != "bearer":
        found.append("HTTPBearer is not declared as an http/bearer security scheme")
    cookie_name = _COOKIE_NAME.search(config)
    if cookie_name is None:
        found.append("config.py no longer declares the refresh cookie name")
    else:
        refresh = schemes.get("refreshCookie")
        if not isinstance(refresh, dict) or refresh.get("type") != "apiKey" or refresh.get("in") != "cookie":
            found.append("refreshCookie is not declared as a cookie apiKey security scheme")
        elif refresh.get("name") != cookie_name.group(1):
            found.append(
                f"refreshCookie declares {refresh.get('name')!r}; config.py declares "
                f"{cookie_name.group(1)!r}"
            )

    # 2. Every /api/v1/admin/* operation must require HTTPBearer. Admin routers
    #    enforce get_current_user + require_admin_roles per route; the published
    #    document is the only machine-readable statement of that boundary, and
    #    the generated client deliberately drops `security` entirely.
    operations = _operations(document)
    admin = [(p, m, o) for p, m, o in operations if p.startswith("/api/v1/admin/")]
    if not admin:
        found.append("openapi.json declares no /api/v1/admin/* operations at all")
    for path, method, operation in admin:
        if not _bearer(operation):
            found.append(f"{method.upper()} {path} does not require HTTPBearer")

    # 3. A reviewed literal floor on the non-admin protected surface. The old
    #    `protected < len(admin)` bound could never fire: admin is a subset of
    #    protected, so protected >= len(admin) by construction. Stripping
    #    `security` from every one of the 48 non-admin operations left the
    #    count equal to len(admin) and kept this guard green. Compare the exact
    #    published set against an independent hand-written lock instead, so a
    #    co-revert (or a re-export that drops one) is caught in both directions.
    published_non_admin = {
        (p, m)
        for p, m, o in operations
        if not p.startswith("/api/v1/admin/") and _bearer(o)
    }
    if published_non_admin != NON_ADMIN_PROTECTED:
        missing = sorted(NON_ADMIN_PROTECTED - published_non_admin)
        extra = sorted(published_non_admin - NON_ADMIN_PROTECTED)
        if missing:
            found.append(
                f"{len(missing)} pinned non-admin operations no longer require "
                f"HTTPBearer (e.g. {missing[0][1].upper()} {missing[0][0]}): "
                "a published-operation co-revert is not allowed"
            )
        if extra:
            found.append(
                f"{len(extra)} non-admin operations now require HTTPBearer but "
                "are not in the reviewed floor: update NON_ADMIN_PROTECTED in "
                "the same commit as the re-export"
            )

    # 4. The auth bootstrap endpoints must stay public. A blanket top-level
    #    `security` (or a hand-edit adding it to login/register/refresh) would
    #    make the platform unusable, and no byte-diff gate names that cause.
    if document.get("security"):
        found.append("openapi.json declares a global security requirement")
    for path, method, operation in operations:
        if (path, method) in PUBLIC_AUTH and _bearer(operation):
            found.append(f"{method.upper()} {path} is public by design but requires HTTPBearer")

    # 5. Source pins: the four files that actually decide the surface must
    #    still contain the behavior the snapshot claims. A co-revert of
    #    snapshot + source is exactly the class this guard exists to catch.
    if 'security_schemes.setdefault(\n        "refreshCookie"' not in main:
        found.append("main.py no longer injects the refreshCookie security scheme")
    if '"HTTPBearer" in security_schemes' not in main:
        found.append("main.py no longer binds the HTTPBearer description")
    if "bearer_scheme = HTTPBearer(auto_error=False)" not in deps:
        found.append("deps.py no longer defines the bearer scheme")
    if "request.cookies.get(settings.refresh_cookie_name)" not in auth:
        found.append("auth.py no longer reads the refresh token from the cookie")

    return found


def _load() -> tuple[str, str, str, str, str]:
    return (
        SNAPSHOT.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        DEPS.read_text(encoding="utf-8"),
        AUTH.read_text(encoding="utf-8"),
        CONFIG.read_text(encoding="utf-8"),
    )


def _mutate(snapshot: str, main: str, deps: str, auth: str, config: str, *, kind: str):
    """Return a copy with one specific regression applied."""
    doc = json.loads(snapshot)
    if kind == "drop_refresh_scheme":
        doc["components"]["securitySchemes"].pop("refreshCookie", None)
    elif kind == "retype_bearer":
        doc["components"]["securitySchemes"]["HTTPBearer"] = {
            "type": "http", "scheme": "basic"
        }
    elif kind == "rename_cookie":
        doc["components"]["securitySchemes"]["refreshCookie"]["name"] = "wrong"
    elif kind == "drop_admin_security":
        for p, item in doc["paths"].items():
            if p.startswith("/api/v1/admin/"):
                for m, op in item.items():
                    if m in METHODS:
                        op.pop("security", None)
    elif kind == "global_security":
        doc["security"] = [{"HTTPBearer": []}]
    elif kind == "secure_login":
        doc["paths"]["/api/v1/auth/login"]["post"]["security"] = [{"HTTPBearer": []}]
    elif kind == "co_revert_source":
        main = main.replace(
            'security_schemes.setdefault(\n        "refreshCookie"',
            'security_schemes.setdefault(\n        "_removed"',
        )
    elif kind == "strip_non_admin_security":
        # The whole co-revert the old `protected < len(admin)` bound missed:
        # drop `security` from EVERY non-admin protected operation, keep admin.
        for path, item in doc["paths"].items():
            if path.startswith("/api/v1/admin/"):
                continue
            for method, op in item.items():
                if method in METHODS and isinstance(op, dict):
                    op.pop("security", None)
    elif kind == "drop_one_non_admin_security":
        target = sorted(NON_ADMIN_PROTECTED)[0]
        doc["paths"][target[0]][target[1]].pop("security", None)
    elif kind == "phantom_non_admin_security":
        # A genuinely public non-admin operation gains HTTPBearer without the
        # floor being reviewed. Pick one outside PUBLIC_AUTH so check 4 does not
        # fire and check 3's `extra` direction is the one that bites.
        doc["paths"]["/api/v1/assemblies"]["get"]["security"] = [
            {"HTTPBearer": []}
        ]
    else:
        raise ValueError(kind)
    return (json.dumps(doc), main, deps, auth, config)


def _self_test() -> int:
    base = _load()
    clean = failures(*base)
    if clean:
        print("openapi-auth-surface: self-test setup is dirty: " + "; ".join(clean), file=sys.stderr)
        return 1
    cases = [
        "drop_refresh_scheme",
        "retype_bearer",
        "rename_cookie",
        "drop_admin_security",
        "global_security",
        "secure_login",
        "co_revert_source",
        "strip_non_admin_security",
        "drop_one_non_admin_security",
        "phantom_non_admin_security",
    ]
    problems = []
    for kind in cases:
        mutant = _mutate(*base, kind=kind)
        result = failures(*mutant)
        if not result:
            problems.append(f"{kind}: regression was NOT detected")
    if problems:
        for problem in problems:
            print(f"openapi-auth-surface: FAIL self-test: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-auth-surface: OK ({len(cases)} ablations)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run in-file ablations")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    found = failures(*_load())
    if found:
        for problem in found:
            print(f"openapi-auth-surface: FAIL: {problem}", file=sys.stderr)
        return 1
    print("openapi-auth-surface: OK (auth surface pinned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
