#!/usr/bin/env python3
"""Freeze the published OpenAPI document-level metadata against a golden lock.

``packages/api-client/scripts/check-contract.sh`` proves a self-consistency
property: a fresh export equals the committed ``openapi.json``, and the
generated ``openapi.d.ts`` equals a regeneration from it. It does not prove
the published document still *says the reviewed contract*. The 422 guard, the
behavior guard (#166), the auth-surface guard (#169), the envelope-shape guard
(#171) and the body-integrity guard (#168) pin per-operation or per-schema
facts; none reads the top-level ``info``/``tags`` block.

That block is client-visible and lives in exactly one committed artifact:
``openapi-typescript`` drops ``info`` and top-level ``tags`` entirely, so
``openapi.d.ts`` carries neither. ``normalize()`` in ``export_contract.py``
only walks ``components.schemas``, so the export-normalizer fixed-point test
cannot see it either. A coordinated edit -- change ``main.py``'s
``OPENAPI_DESCRIPTION`` / ``OPENAPI_TAGS`` / ``version`` constant, re-export
the snapshot -- keeps *every* existing gate green while the published metadata
drifts. Both halves agree with each other by construction.

This is the same genus #162 names for the kernel error codes: **a derived
expectation cannot freeze a value**. Pinning "published == source" is vacuous
against a co-revert of both. The fix is a hand-written, reviewed lock that
sits *downstream* of the source:

    packages/api-client/openapi-document-metadata.golden.json

It is NOT generated from ``main.py`` or ``openapi.json``. Any deliberate
change to the title / version / description prose / tag catalog is an explicit,
reviewable edit to that file, followed by regenerating the snapshot. The guard
compares three things against committed bytes, all stdlib only (no Python 3.15
venv, no FastAPI import, no service, no pydantic inference to copy):

1. the published ``info``/``tags`` == the golden (catches a source+snapshot
   co-revert, which leaves the golden stale);
2. the source constants in ``main.py``/``core/config.py`` == the golden
   (catches a source-only drift that would mislead a regeneration);
3. ``create_app()`` still feeds those constants into ``FastAPI(...)``
   (catches a rewiring that would make the snapshot's metadata diverge from
   what the running app exports).

Unlike the error envelope's ``required`` rules, these facts are plain literals
(a triple-quoted string, a list of dicts, a version string, a config default),
so pinning them does not mean re-deriving pydantic's behaviour and cannot rot
across pydantic versions.

Usage:
    python3 scripts/check_openapi_document_metadata.py
    python3 scripts/check_openapi_document_metadata.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
GOLDEN = ROOT / "packages/api-client/openapi-document-metadata.golden.json"
MAIN = ROOT / "apps/api/app/main.py"
CONFIG = ROOT / "apps/api/app/core/config.py"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name
WIRED_AS = "scripts/test_openapi_document_metadata_guard.py"

# Keys the golden locks. ``_comment`` is documentation, not contract.
LOCKED_KEYS = ("title", "version", "description", "tags")
REQUIRED_TAG_KEYS = ("name", "description")


# ---------------------------------------------------------------------------
# Source-side reading (stdlib ast, no imports of the app)
# ---------------------------------------------------------------------------


def _assignments(tree: ast.Module) -> dict[str, ast.expr]:
    """Map name -> value expression for module-level simple assignments."""
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    out[target.id] = value
    return out


def _fastapi_kwargs(tree: ast.Module) -> dict[str, ast.expr]:
    """Keyword arguments of the ``FastAPI(...)`` call inside ``create_app``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "FastAPI")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "FastAPI")
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    return {}


def _config_default(tree: ast.Module, name: str) -> ast.expr | None:
    """An annotated assignment default, e.g. ``app_name: str = "SoyMutDB"``.

    ``config.py`` declares these as pydantic ``BaseSettings`` fields inside a
    class, not at module level, so walk the whole tree.
    """
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
    return None


def _literal(expr: ast.expr | None) -> Any:
    return None if expr is None else ast.literal_eval(expr)


def source_facts(main: str, config: str) -> dict[str, Any]:
    """Derive the metadata the backend *intends* to publish from source bytes."""
    main_tree = ast.parse(main)
    cfg_tree = ast.parse(config)
    assignments = _assignments(main_tree)
    kwargs = _fastapi_kwargs(main_tree)
    title_expr = kwargs.get("title")
    return {
        "title": _literal(_config_default(cfg_tree, "app_name")),
        "version": _literal(kwargs.get("version")),
        "description": _literal(assignments.get("OPENAPI_DESCRIPTION")),
        "tags": _literal(assignments.get("OPENAPI_TAGS")),
        "title_expr": ast.unparse(title_expr) if title_expr is not None else None,
        "has_create_app": any(
            isinstance(n, ast.FunctionDef) and n.name == "create_app"
            for n in main_tree.body
        ),
        "passes_description": "description=OPENAPI_DESCRIPTION" in main,
        "passes_tags": "openapi_tags=OPENAPI_TAGS" in main,
    }


def published_facts(document: dict[str, Any]) -> dict[str, Any]:
    info = document.get("info")
    if not isinstance(info, dict):
        return {}
    return {
        "title": info.get("title"),
        "version": info.get("version"),
        "description": info.get("description"),
        "tags": document.get("tags"),
    }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def failures(
    snapshot: str,
    generated: str,
    golden: str,
    main: str,
    config: str,
    smoke: str,
) -> list[str]:
    found: list[str] = []
    try:
        document: dict[str, Any] = json.loads(snapshot)
    except json.JSONDecodeError as exc:
        return [f"openapi.json is not valid JSON: {exc}"]
    try:
        locked: dict[str, Any] = json.loads(golden)
    except json.JSONDecodeError as exc:
        return [f"openapi-document-metadata.golden.json is not valid JSON: {exc}"]
    try:
        facts = source_facts(main, config)
    except (SyntaxError, ValueError) as exc:
        return [f"main.py/config.py no longer parse as the metadata source: {exc}"]

    # Reject a hollow / duplicated-key lock: a truncated golden must fail loudly
    # rather than read as "no drift". object_pairs_hook keeps duplicate keys.
    def _no_dupes(pairs):
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate key {key!r}")
            out[key] = value
        return out
    try:
        json.loads(golden, object_pairs_hook=_no_dupes)
    except ValueError as exc:
        return [f"golden lock has duplicate keys: {exc}"]
    for key in LOCKED_KEYS:
        if key not in locked:
            found.append(f"golden lock is missing the reviewed `{key}`")
    if any(isinstance(locked.get(k), str) and not locked[k] for k in ("title", "version", "description")):
        found.append("golden lock carries an empty title/version/description")

    published = published_facts(document)
    if not published:
        return ["openapi.json has no `info` object"]

    # 1. Published == golden. This is the authority a co-revert cannot move:
    #    changing main.py + re-exporting the snapshot keeps them agreeing with
    #    each other, but not with the reviewed lock.
    for key in LOCKED_KEYS:
        if key in locked and published.get(key) != locked[key]:
            found.append(f"published `info/{key}` no longer matches the golden lock")

    # Tag catalog well-formedness (independent of the golden): an empty
    # catalog or a hollowed tag is a regression even if someone edited the lock.
    tags = published.get("tags")
    if not isinstance(tags, list) or not tags:
        found.append("openapi.json publishes an empty or missing tag catalog")
    else:
        for index, tag in enumerate(tags):
            if not isinstance(tag, dict) or any(
                not tag.get(key) for key in REQUIRED_TAG_KEYS
            ):
                found.append(f"tags[{index}] is missing a name or description")

    # 2. Source == golden. A source-only drift would mislead the next
    #    regeneration into publishing a contract nobody reviewed.
    for key in LOCKED_KEYS:
        if key in locked and facts.get(key) != locked[key]:
            found.append(f"source constant for `{key}` no longer matches the golden lock")

    # 3. create_app still feeds those constants into FastAPI. Without this, a
    #    rewiring (hardcoded title / dropped description / dropped tags) makes
    #    the running app export metadata that diverges from the snapshot.
    if not facts["has_create_app"]:
        found.append("main.py no longer defines create_app()")
    if facts["title_expr"] != "settings.app_name":
        found.append("create_app() no longer sets the title from settings.app_name")
    if not facts["passes_description"]:
        found.append("create_app() no longer passes OPENAPI_DESCRIPTION as description")
    if not facts["passes_tags"]:
        found.append("create_app() no longer passes OPENAPI_TAGS as openapi_tags")

    # 4. The generated client must NOT start encoding this metadata. Its
    #    absence is the premise for "one committed artifact"; if a future
    #    generator emits info/tags, a human must re-derive the wiring. Use the
    #    full description / a structural marker as the needle -- the bare app
    #    name legitimately appears in per-operation prose.
    distinctive = (locked.get("description"), "export interface info", "export type info")
    for needle in distinctive:
        if isinstance(needle, str) and needle and needle in generated:
            found.append(
                "openapi.d.ts now carries document-level metadata; the "
                "single-artifact premise of this guard is stale"
            )
            break

    # 5. Wiring: a guard nothing calls is worse than none.
    if WIRED_AS not in smoke and f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer no longer collects the metadata guard")

    return found


# ---------------------------------------------------------------------------
# Self-test: each case is a real regression class, not a mock of the guard
# ---------------------------------------------------------------------------


def _load() -> tuple[str, str, str, str, str, str]:
    return (
        SNAPSHOT.read_text(encoding="utf-8"),
        GENERATED.read_text(encoding="utf-8"),
        GOLDEN.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        CONFIG.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def run() -> list[str]:
    return failures(*_load())


def self_test() -> list[str]:
    problems: list[str] = []
    base = _load()

    def check(label: str, mutate, needle: str) -> None:
        parts = copy.deepcopy(base)
        parts = mutate(*parts)
        found = failures(*parts)
        if not any(needle in item for item in found):
            problems.append(
                f"{label}: guard stayed green (or missed `{needle}`); got {found}"
            )

    def edit_snapshot(fn):
        def mutate(snapshot, generated, golden, main, config, smoke):
            document = json.loads(snapshot)
            fn(document)
            return json.dumps(document, ensure_ascii=False), generated, golden, main, config, smoke
        return mutate

    def edit_golden(fn):
        def mutate(snapshot, generated, golden, main, config, smoke):
            document = json.loads(golden)
            fn(document)
            return snapshot, generated, json.dumps(document, ensure_ascii=False), main, config, smoke
        return mutate

    def drop_title(document):
        document["info"]["title"] = "NotSoyMutDB"

    def drop_version(document):
        document["info"]["version"] = "0.0.0"

    def drop_description(document):
        document["info"]["description"] = "placeholder"

    def drop_tags(document):
        document["tags"] = []

    def reorder_tags(document):
        document["tags"] = list(reversed(document["tags"]))

    def hollow_tag(document):
        document["tags"][0] = {"name": "health"}

    def invented_tag(document):
        document["tags"].append({"name": "made-up", "description": "x"})

    def coordinated_co_revert(snapshot, generated, golden, main, config, smoke):
        # THE adversarial case: source AND snapshot change to the SAME new
        # value, so export==snapshot stays green and a published==source guard
        # would be vacuous. Only the golden lock makes this fail.
        new = "A completely rewritten description both halves now agree on."
        start = main.index("OPENAPI_DESCRIPTION = \"\"\"") + len("OPENAPI_DESCRIPTION = \"\"\"")
        end = main.index("\"\"\"", start)
        main = main[:start] + "\n" + new + "\n" + main[end:]
        document = json.loads(snapshot)
        document["info"]["description"] = "\n" + new + "\n"
        return json.dumps(document, ensure_ascii=False), generated, golden, main, config, smoke

    def golden_edited(snapshot, generated, golden, main, config, smoke):
        # Someone moves the lock to bless a drift without review -> the source
        # and snapshot must then disagree with each other's derived value.
        document = json.loads(golden)
        document["version"] = "9.9.9"
        return snapshot, generated, json.dumps(document, ensure_ascii=False), main, config, smoke

    def golden_hollow(snapshot, generated, golden, main, config, smoke):
        return snapshot, generated, "{}", main, config, smoke

    def source_constant_drift(snapshot, generated, golden, main, config, smoke):
        main = main.replace('version="2.0.0"', 'version="3.0.0"', 1)
        return snapshot, generated, golden, main, config, smoke

    def source_title_unwired(snapshot, generated, golden, main, config, smoke):
        main = main.replace("title=settings.app_name,", 'title="Hardcoded",', 1)
        return snapshot, generated, golden, main, config, smoke

    def source_description_unwired(snapshot, generated, golden, main, config, smoke):
        main = main.replace("description=OPENAPI_DESCRIPTION,", 'description="x",', 1)
        return snapshot, generated, golden, main, config, smoke

    def source_config_renamed(snapshot, generated, golden, main, config, smoke):
        config = config.replace('app_name: str = "SoyMutDB"', 'app_name: str = "OtherDB"', 1)
        return snapshot, generated, golden, main, config, smoke

    def delete_create_app(snapshot, generated, golden, main, config, smoke):
        main = main.replace("def create_app() -> FastAPI:", "def _retired_create_app() -> FastAPI:", 1)
        return snapshot, generated, golden, main, config, smoke

    def generated_leaks_metadata(snapshot, generated, golden, main, config, smoke):
        generated += "\n// " + json.loads(snapshot)["info"]["description"] + " leaked\n"
        return snapshot, generated, golden, main, config, smoke

    def smoke_unwired(snapshot, generated, golden, main, config, smoke):
        return snapshot, generated, golden, main, config, smoke.replace(WIRED_AS, "", 1)

    ablations = [
        ("info.title drift", edit_snapshot(drop_title), "no longer matches the golden lock"),
        ("info.version drift", edit_snapshot(drop_version), "no longer matches the golden lock"),
        ("info.description drift", edit_snapshot(drop_description), "no longer matches the golden lock"),
        ("tag catalog emptied", edit_snapshot(drop_tags), "no longer matches the golden lock"),
        ("tag order changed", edit_snapshot(reorder_tags), "no longer matches the golden lock"),
        ("tag hollowed", edit_snapshot(hollow_tag), "no longer matches the golden lock"),
        ("tag invented", edit_snapshot(invented_tag), "no longer matches the golden lock"),
        ("coordinated co-revert (source+snapshot)", coordinated_co_revert, "no longer matches the golden lock"),
        ("golden edited to bless drift", golden_edited, "no longer matches the golden lock"),
        ("golden hollowed", golden_hollow, "missing the reviewed"),
        ("source version drift", source_constant_drift, "no longer matches the golden lock"),
        ("title unwired from settings", source_title_unwired, "settings.app_name"),
        ("description unwired", source_description_unwired, "OPENAPI_DESCRIPTION"),
        ("config app_name renamed", source_config_renamed, "no longer matches the golden lock"),
        ("create_app deleted", delete_create_app, "no longer defines create_app"),
        ("generated client leaks metadata", generated_leaks_metadata, "single-artifact premise"),
        ("smoke wiring dropped", smoke_unwired, "no longer collects the metadata guard"),
    ]
    for label, mutate, needle in ablations:
        check(label, mutate, needle)

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        problems = self_test()
        for problem in problems:
            print(f"openapi-document-metadata: FAIL: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"openapi-document-metadata: OK ({17} ablations)")
        return 0

    found = run()
    for item in found:
        print(f"openapi-document-metadata: FAIL: {item}", file=sys.stderr)
    if found:
        return 1
    print("openapi-document-metadata: OK (document metadata frozen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
