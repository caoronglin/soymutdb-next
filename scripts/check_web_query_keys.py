#!/usr/bin/env python3
"""Check real React route reads, not the retired Vue views directory.

This is a source guard, not a runtime isolation proof. Cache behavior is tested
with QueryClient in assemblies-query-options.test.ts.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES_DIR = ROOT / "apps/web/src/routes"
GENERATED = {"node_modules", "dist", "coverage", ".turbo"}
FACTORY_RE = re.compile(r"\b(?:assembliesQueryOptions|assemblyChromosomesQueryOptions)\s*\(")


def call_arguments(text: str, open_index: int) -> str:
    """Return the balanced argument text of the call whose `(` is at `open_index`.

    A regex like `\\(([^)]*)\\)` stops at the first `)`, so a real call such as

        assembliesQueryOptions({ releaseId: getReleaseId(), siteVariant: SITE })

    is read as `{ releaseId: getReleaseId(` — the context looks truncated and
    every scoped call is reported as missing `siteVariant`. Balance the brackets
    instead, and step over string literals so a `)` inside text cannot close the
    call early.
    """
    depth = 0
    quote: str | None = None
    index = open_index
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
        index += 1
    return text[open_index + 1 :]


def route_files(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
        and not any(part in GENERATED or part.startswith(".umi")
                    for part in path.relative_to(directory).parts)
        and not re.search(r"\.(?:test|spec)\.tsx?$", path.name)
        and not path.name.endswith(".gen.ts")
    )


def inspect_source(content: str) -> tuple[list[str], bool]:
    content = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", content)
    failures: list[str] = []
    # Keep import aliases observable rather than assuming the original spelling.
    aliases = set(re.findall(
        r"\b(?:getAssemblies|getAssemblyChromosomes)\s+as\s+(\w+)", content
    ))
    body = re.sub(r"\bimport\s+[\s\S]*?\s+from\s+['\"][^'\"]+['\"];?", "", content)
    direct = bool(re.search(r"\b(?:getAssemblies|getAssemblyChromosomes)\b", body))
    direct = direct or any(re.search(rf"\b{re.escape(alias)}\b", body) for alias in aliases)
    # A transport-only tools forwarding module is not a React query consumer.
    query_consumer = bool(re.search(r"\b(?:useQuery|useSuspenseQuery|fetchQuery|prefetchQuery)\b", body))
    factory_calls = [call_arguments(body, match.end() - 1)
                     for match in FACTORY_RE.finditer(body)]
    consumer = bool(factory_calls) or (direct and query_consumer)
    if direct and query_consumer:
        failures.append("bypasses the assembly query factory (direct API read)")
    if re.search(r"queryKeys\s*\.\s*assemblies\b", body):
        failures.append("references queryKeys.assemblies directly")
    if re.search(r"queryKey\s*:\s*\[[^\]]*['\"]assemblies['\"]", body):
        failures.append("contains a handwritten assemblies query key")
    if query_consumer and re.search(r"['\"]/genes/assemblies(?:/[^'\"]*)?['\"]", body):
        failures.append("queries the assembly endpoint outside the factory")
    for args in factory_calls:
        # Context may be an existing typed variable; literal contexts must be explicit.
        if not args.strip():
            failures.append("calls an assembly factory without deployment context")
        elif args.lstrip().startswith("{") and not all(
            re.search(rf"\b{field}\b", args) for field in ("releaseId", "siteVariant")
        ):
            failures.append("assembly factory context omits releaseId or siteVariant")
    return failures, consumer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes-dir", type=Path, default=ROUTES_DIR)
    directory = parser.parse_args(argv).routes_dir
    files = route_files(directory)
    failures = []
    consumers = []
    if not files:
        failures.append("empty React route scan")
    for path in files:
        issues, consumer = inspect_source(path.read_text(encoding="utf-8"))
        if consumer:
            consumers.append(path.relative_to(directory).as_posix())
        failures.extend(f"{path}: {issue}" for issue in issues)
    if not consumers:
        failures.append("no actual assembly query consumers found")
    if failures:
        print("Portal query-key architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"Portal query-key architecture check passed ({len(files)} React modules, "
          f"{len(consumers)} assembly consumer modules):")
    for consumer in consumers:
        print(f"  - {consumer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
