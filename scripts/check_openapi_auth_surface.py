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

    # 3. A lower bound on the whole protected surface: a co-revert that strips
    #    `security` from every operation at once cannot hide behind the admin
    #    check (admin would also be empty, which check 2 catches) -- but a
    #    wholesale renumbering that keeps admin while dropping the other 46
    #    protected operations would otherwise go unnoticed.
    protected = sum(1 for _, _, o in operations if _bearer(o))
    if protected < len(admin):
        found.append(
            f"only {protected} operations require HTTPBearer; {len(admin)} admin "
            "operations alone need it"
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
