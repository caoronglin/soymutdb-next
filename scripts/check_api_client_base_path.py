#!/usr/bin/env python3
"""Guard the api-client transport against a duplicated ``/api/v1`` prefix.

``client.ts`` ``buildUrl()`` prepends ``apiBaseUrl`` (default ``/api/v1``) to
every relative path. PR #117 shipped ``BASE = "/api/v1/tools/sequence"`` and
all nine operations silently resolved to ``/api/v1/api/v1/tools/sequence/*``:
the client unit tests asserted the doubled URL and the OpenAPI/snapshot gates
read schemas, not ``.ts`` path construction. The five failing vitest cases were
the only thing that caught it, on CI.

This guard reads the committed api-client sources independently of the test
runner: no relative path handed to the transport may already carry the base.
It resolves named constants and ``${...}`` template literals so a ``BASE = "/api/v1/..."``
constant is caught even when the call site is ``request(BASE)``. Absolute
``http(s)://`` URLs are left to ``buildUrl`` and are never flagged.

Run with ``--src-dir`` to point at a synthetic tree in the self-test.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "packages/api-client/src"

# Transport entry points whose first argument is a path. The generated client
# types and vitest files are not call sites.
CALL = re.compile(
    r"\b(?:request|requestBlob|authRequest|authRequestBlob)"
    r"(?:<[^>]*>)?\(\s*(?P<arg>[^,)]+)"
)
HTTP_CALL = re.compile(
    r"\bhttp\.(?:get|post|put|patch|delete|request)"
    r"(?:<[^>]*>)?\(\s*(?P<arg>[^,)]+)"
)
# A bare string constant carrying a path (BASE = "/tools/...", PATH = ..., etc).
CONST = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<quote>[\"'`])(?P<value>[^\"'`]*)(?P=quote)"
)
PREFIX = "/api/v1"


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(?m)//[^\n]*", "", text)


def is_bad_path(value: str) -> bool:
    """A relative path that buildUrl would prefix a second time."""
    if value.startswith(("http://", "https://")):
        return False
    # Strip template interpolation so `${BASE}/x` still exposes its literal head.
    head = re.sub(r"\$\{[^}]*\}", "", value)
    return head.startswith(PREFIX)


def inspect(files: dict[str, str]) -> list[str]:
    """Return violations for {relative filename: source text}."""
    failures: list[str] = []
    # Resolve string constants across the whole package so `request(BASE)`
    # is judged on the constant's value, not on its name.
    constants: dict[str, tuple[str, str]] = {}
    for name, text in files.items():
        body = strip_comments(text)
        for m in CONST.finditer(body):
            constants[m.group("name")] = (name, m.group("value"))

    def resolve(arg: str, filename: str) -> list[tuple[str, str]]:
        resolved: list[tuple[str, str]] = []
        literal = re.fullmatch(r"\s*([\"'`])([^\"'`]*)\1\s*", arg)
        if literal:
            value = literal.group(2)
            resolved.append((filename, value))
            # A template literal like `${BASE}${path}` / `${BASE}/capabilities`
            # hides the bad prefix behind an interpolation. Substitute the
            # first referenced constant so the effective head is checked too.
            for ref in re.findall(r"\$\{\s*([A-Za-z_$][\w$]*)\s*\}", value):
                if ref in constants:
                    origin, const_value = constants[ref]
                    effective = value.replace("${" + ref + "}", const_value, 1)
                    resolved.append((origin, effective))
                    break
        elif re.fullmatch(r"\s*[A-Za-z_$][\w$]*\s*", arg):
            key = arg.strip()
            if key in constants:
                resolved.append(constants[key])
        return resolved

    bodies: dict[str, str] = {name: strip_comments(text) for name, text in files.items()}
    for name, body in bodies.items():
        calls = list(CALL.finditer(body)) + list(HTTP_CALL.finditer(body))
        for m in calls:
            arg = m.group("arg").strip()
            line = body[: m.start()].count("\n") + 1
            for origin, value in resolve(arg, name):
                if is_bad_path(value):
                    failures.append(
                        f"{name}:{line}: request path {value!r} already carries "
                        f"'{PREFIX}'; buildUrl prefixes it again"
                        + (f" (via {origin})" if origin != name else "")
                    )
    # Flag a bad constant even when no single call site is visible in its own
    # file (e.g. defined in one module, consumed in another). Line numbers come
    # from the declaring file, not from whichever file happened to use it.
    for const_name, (origin, value) in constants.items():
        if not is_bad_path(value):
            continue
        body = bodies.get(origin, "")
        for i, ln in enumerate(body.split("\n"), 1):
            if re.search(r"\b" + re.escape(const_name) + r"\b\s*=", ln):
                failures.append(
                    f"{origin}:{i}: constant {const_name} = {value!r} "
                    f"already carries '{PREFIX}'"
                )
                break
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [f for f in failures if not (f in seen or seen.add(f))]
    return unique


def collect(src: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not src.is_dir():
        return result
    for path in sorted(src.rglob("*.ts")):
        if path.name.endswith(".test.ts") or ".test." in path.name:
            continue
        if "generated" in path.parts or path.name.endswith(".d.ts"):
            continue
        result[path.relative_to(src).as_posix()] = path.read_text(encoding="utf-8")
    return result


def self_test() -> int:
    cases = [
        ("clean relative literal", {"a.ts": 'request("/tools/seqfetch", {});\n'}, 0),
        ("clean BASE constant", {
            "a.ts": 'const BASE = "/tools/sequence";\nrequest(BASE, {});\n',
        }, 0),
        ("doubled literal", {"a.ts": 'request("/api/v1/tools/sequence", {});\n'}, 1),
        ("doubled BASE constant", {
            "a.ts": 'const BASE = "/api/v1/tools/sequence";\nrequest(BASE, {});\n',
        }, 2),  # both the call site and the declaration
        ("absolute URL allowed", {
            "a.ts": 'request("https://api.example/tools/x", {});\n',
        }, 0),
        ("comment is ignored", {
            "a.ts": '// request("/api/v1/x", {});\nrequest("/tools/x", {});\n',
        }, 0),
        ("template literal with bad head", {
            "a.ts": 'request(`/api/v1/tools/${id}`, {});\n',
        }, 1),  # the literal head still starts with /api/v1
        ("template literal with clean head", {
            "a.ts": 'request(`/tools/${id}`, {});\n',
        }, 0),
        ("BASE defined in another module", {
            "a.ts": 'export const BASE = "/api/v1/tools/sequence";\n',
            "b.ts": 'import { BASE } from "./a";\nrequest(BASE, {});\n',
        }, 2),
        ("http.get bad path", {
            "a.ts": 'http.get("/api/v1/genes", {});\n',
        }, 1),
        # The exact PR #117 shape: a bad BASE interpolated into templates.
        ("interpolated bad BASE", {
            "a.ts": 'const BASE = "/api/v1/tools/sequence";\n'
                   'request(`${BASE}${path}`, {});\n'
                   'request(`${BASE}/capabilities`, {});\n',
        }, 3),
        ("interpolated clean BASE", {
            "a.ts": 'const BASE = "/tools/sequence";\n'
                   'request(`${BASE}${path}`, {});\n'
                   'request(`${BASE}/capabilities`, {});\n',
        }, 0),
    ]
    failures = 0
    for label, files, expected in cases:
        got = len(inspect(files))
        if got != expected:
            print(f"SELF-TEST FAIL [{label}]: expected {expected} violation(s), got {got}")
            failures += 1
    if failures:
        return 1
    print(f"api-client base-path guard self-test passed ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-dir", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    files = collect(args.src_dir)
    if not files:
        print("api-client base-path guard: no source files found", file=sys.stderr)
        return 1
    violations = inspect(files)
    if violations:
        print("api-client base-path guard failed:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(f"api-client base-path guard passed ({len(files)} source files, 0 violations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
