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
   what the running app exports). It also rejects a rebinding of those names
   in ``create_app``'s scope and an in-place mutation of the watched
   constants: both leave the call-site text and the module literal intact
   while changing what ``FastAPI(...)`` actually receives.

Unlike the error envelope's ``required`` rules, these facts are plain literals
(a triple-quoted string, a list of dicts, a version string, a config default),
so pinning them does not mean re-deriving pydantic's behaviour and cannot rot
across pydantic versions.

The tag catalog has a SECOND, different property. ``info.title`` /
``info.version`` / ``info.description`` are invariants: their *value* is the
contract, so a lock is the right authority. The catalog's *completeness* is a
derived quantity: it moves whenever a router adds or drops a tag. A lock can
freeze the six names it was written with, but it cannot notice that a seventh
router showed up -- the stale lock stays green. So this guard also asserts a
non-constant invariant, with an authority that does NOT move with the catalog:

    every tag a router emits (``tags=[...]`` literals in ``apps/api/app``)
      == every tag the published operations carry (``paths.*.*.tags[]``)
      == the declared catalog (top-level ``tags[]``)

Both sides are read from committed bytes. The router source is upstream of the
export, and the snapshot's operation tags are downstream of it, so a
source+snapshot+golden co-revert that invents a tag still fails here: no router
emits it. Conversely a legitimate new router plus a catalog entry stays green,
which is the whole point -- a lock would have gone stale. This invariant reads
NO golden content; blessing the golden cannot move it. It also reports the
``declared-but-unused`` direction, which a byte lock cannot see.

Usage:
    python3 scripts/check_openapi_document_metadata.py
    python3 scripts/check_openapi_document_metadata.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import copy
import functools
import json
import symtable
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
ROUTER_ROOT = ROOT / "apps/api/app"
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


_ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
)


def router_sources() -> dict[str, str]:
    """Committed router source bytes. These are upstream of every export."""
    out: dict[str, str] = {}
    for path in sorted(ROUTER_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "tags=" in text:
            out[str(path.relative_to(ROOT))] = text
    return out


def router_tag_names(sources: dict[str, str]) -> set[str]:
    """Tag names a router actually emits, from ``tags=[...]`` literals.

    ``APIRouter(tags=[...])`` and route decorators are the origin of
    ``paths.*.*.tags[]``; ``export_contract.py`` copies them verbatim. Only
    those call shapes are read, so an unrelated ``tags=`` kwarg (e.g.
    ``bleach.clean(..., tags=[...])``) cannot be mistaken for a tag. A
    non-literal ``tags=`` (e.g. ``tags=app.openapi_tags``) is a pass-through,
    not a declaration, and is deliberately skipped.
    """
    names: set[str] = set()
    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            raise ValueError(f"{path} no longer parses: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_router = (isinstance(func, ast.Name) and func.id == "APIRouter") or (
                isinstance(func, ast.Attribute) and func.attr == "APIRouter"
            )
            is_route = isinstance(func, ast.Attribute) and func.attr in _ROUTE_METHODS
            if not (is_router or is_route):
                continue
            for keyword in node.keywords:
                if keyword.arg != "tags" or not isinstance(
                    keyword.value, (ast.List, ast.Tuple)
                ):
                    continue
                for value in ast.literal_eval(keyword.value):
                    if isinstance(value, str):
                        names.add(value)
    return names


def _kw_expr(kwargs: dict[str, ast.expr], name: str) -> str | None:
    """Unparsed value of a ``FastAPI(...)`` keyword, or None if absent."""
    value = kwargs.get(name)
    return ast.unparse(value) if value is not None else None


# The three keyword values whose *spelling* ``_kw_expr`` pins. A local
# rebinding of any root of these expressions inside ``create_app`` would make
# the running app export different metadata while leaving the call-site text
# (and therefore the byte lock and the parsed-call check) unchanged.
_WATCHED_KWARGS = ("title", "description", "openapi_tags")


def _watched_names(main: str) -> set[str]:
    """Root names referenced by the watched ``FastAPI(...)`` keyword values."""
    kwargs = _fastapi_kwargs(ast.parse(main))
    names: set[str] = set()
    for name in _WATCHED_KWARGS:
        value = kwargs.get(name)
        if value is None:
            continue
        for node in ast.walk(value):
            if isinstance(node, ast.Name):
                names.add(node.id)
    return names


def _shadowed_wiring_names(main: str) -> list[str]:
    """Names rebound in ``create_app``'s own scope before ``FastAPI(...)``.

    ``_kw_expr`` proves the keyword still *reads* ``OPENAPI_DESCRIPTION``; it
    cannot prove that name still resolves to the module-level constant. A local
    assignment, parameter, import or augmented assign in ``create_app``
    rebinds it, so the running app publishes different bytes than the locked
    snapshot while every existing check stays green. A bare ``global``
    declaration is deliberately NOT flagged: it binds to the module scope the
    constant already lives in, so the value read by ``FastAPI(...)`` is
    unchanged. A ``global`` plus a rebind IS flagged -- the rebind sets
    ``is_assigned()``. Use the standard library symbol table (real scope
    resolution), not a textual walk, so a same-name local in a nested helper
    is not a false positive.
    """
    watched = _watched_names(main)
    if not watched:
        return []
    table = symtable.symtable(main, "<main>", "exec")
    create_app = next(
        (child for child in table.get_children() if child.get_name() == "create_app"),
        None,
    )
    if create_app is None:
        return []
    return sorted(
        symbol.get_name()
        for symbol in create_app.get_symbols()
        if symbol.get_name() in watched and (symbol.is_local() or symbol.is_assigned())
    )


# A watched constant can drift without any rebinding: ``OPENAPI_TAGS.clear()``
# or ``OPENAPI_TAGS[0] = {...}`` mutates the same object the module-level
# literal points at, so ``FastAPI(...)`` publishes a hollow catalog while the
# spelling, the module literal, the snapshot and the golden all stay put.
# Scope resolution cannot see this. Fail closed: any method call on a watched
# root must be in this reviewed read-only allowlist, and any subscript or
# attribute store rooted at a watched name is rejected. The committed
# ``create_app`` uses none of these, so a new unknown shape reddens the guard
# instead of silently passing.
_READONLY_METHODS = frozenset(
    ("copy", "count", "index", "get", "items", "keys", "values")
)


def _root_name(node: ast.expr) -> str | None:
    """Innermost Name at the base of an attribute/subscript chain, if any."""
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _mutated_wiring_names(main: str) -> list[str]:
    """Watched names mutated in place anywhere inside ``create_app``."""
    tree = ast.parse(main)
    create_app = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "create_app"),
        None,
    )
    if create_app is None:
        return []
    watched = _watched_names(main)
    found: set[str] = set()
    for node in ast.walk(create_app):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            root = _root_name(node.func.value)
            if root in watched and node.func.attr not in _READONLY_METHODS:
                found.add(f"{root}.{node.func.attr}()")
        if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            root = _root_name(node.value)
            if root in watched:
                found.add(f"assignment via {root}")
    return sorted(found)


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
        "description_expr": _kw_expr(kwargs, "description"),
        "tags_expr": _kw_expr(kwargs, "openapi_tags"),
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
    routers: dict[str, str],
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
    if facts["description_expr"] != "OPENAPI_DESCRIPTION":
        found.append("create_app() no longer passes OPENAPI_DESCRIPTION as description")
    if facts["tags_expr"] != "OPENAPI_TAGS":
        found.append("create_app() no longer passes OPENAPI_TAGS as openapi_tags")
    try:
        shadowed = _shadowed_wiring_names(main)
    except (SyntaxError, ValueError) as exc:
        # ``symtable`` compiles, so it rejects a few shapes ``ast.parse``
        # accepts (e.g. duplicate parameters). Report a clean FAIL instead of
        # letting the exception escape the guard (the #166 StopIteration class).
        found.append(f"main.py does not compile as a metadata source: {exc}")
    else:
        if shadowed:
            found.append(
                "create_app() rebinds metadata names in its local scope ("
                + ", ".join(shadowed)
                + "): the FastAPI(...) call would read a different value than "
                "the locked module-level constant"
            )
        mutated = _mutated_wiring_names(main)
        if mutated:
            found.append(
                "create_app() mutates metadata constants in place ("
                + ", ".join(mutated)
                + "): the FastAPI(...) call would read a different value than "
                "the locked module-level constant"
            )

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

    # 6. Catalog COMPLETENESS -- a derived invariant, not a frozen value.
    #    Checks 1-3 freeze the catalog's bytes; they cannot tell whether those
    #    bytes still describe the document. The router source is upstream of
    #    the export, so it is an authority that does not move with the lock.
    #    This block deliberately reads no golden content.
    try:
        emitted = router_tag_names(routers)
    except ValueError as exc:
        found.append(str(exc))
        return found
    published_tags = published.get("tags")
    entries = (
        [t for t in published_tags if isinstance(t, dict)]
        if isinstance(published_tags, list)
        else []
    )
    names = [t.get("name") for t in entries]
    catalog = {n for n in names if isinstance(n, str)}
    if len(names) != len(catalog):
        found.append("openapi.json publishes duplicate or non-string tag names")

    operation_tags: set[str] = set()
    for path_item in document.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation_tags.update(
                    tag
                    for tag in (operation.get("tags") or [])
                    if isinstance(tag, str)
                )

    missing = (emitted | operation_tags) - catalog
    if missing:
        found.append(
            "tag catalog is incomplete (routers/operations emit undeclared tags): "
            + ", ".join(sorted(missing))
        )
    phantom = catalog - (emitted | operation_tags)
    if phantom:
        found.append(
            "tag catalog declares names no router emits (phantom entries): "
            + ", ".join(sorted(phantom))
        )
    unpublished = operation_tags - emitted
    if unpublished:
        found.append(
            "openapi.json publishes operation tags no router declares: "
            + ", ".join(sorted(unpublished))
        )

    return found


# ---------------------------------------------------------------------------
# Self-test: each case is a real regression class, not a mock of the guard
# ---------------------------------------------------------------------------


def _load() -> tuple[str, str, str, str, str, str, dict[str, str]]:
    return (
        SNAPSHOT.read_text(encoding="utf-8"),
        GENERATED.read_text(encoding="utf-8"),
        GOLDEN.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        CONFIG.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
        router_sources(),
    )


def run() -> list[str]:
    return failures(*_load())


def self_test() -> tuple[list[str], int, int, frozenset[str]]:
    problems: list[str] = []
    base = _load()

    def check(label: str, mutate, needle: str) -> None:
        parts = copy.deepcopy(base)
        found = failures(*mutate(*parts))
        if not any(needle in item for item in found):
            problems.append(
                f"{label}: guard stayed green (or missed `{needle}`); got {found}"
            )

    def check_only(label: str, mutate, needle: str, absent: tuple[str, ...]) -> None:
        """The derived invariant fires AND every golden-lock check stays green."""
        parts = copy.deepcopy(base)
        found = failures(*mutate(*parts))
        if not any(needle in item for item in found):
            problems.append(f"{label}: missed `{needle}`; got {found}")
        for word in absent:
            if any(word in item for item in found):
                problems.append(
                    f"{label}: golden lock also fired (`{word}`), not isolated; got {found}"
                )
        if any("duplicate or non-string" in item for item in found):
            problems.append(f"{label}: catalog shape check noise; got {found}")

    def check_clean(label: str, mutate) -> None:
        """A legitimate co-change must stay green -- the invariant is not a lock."""
        parts = copy.deepcopy(base)
        found = failures(*mutate(*parts))
        if found:
            problems.append(f"{label}: legitimate co-change was rejected; got {found}")

    def router_safe(fn):
        """Adapt a legacy six-input ablator to the seven-input signature."""
        @functools.wraps(fn)
        def wrapper(snapshot, generated, golden, main, config, smoke, routers):
            return (*fn(snapshot, generated, golden, main, config, smoke), routers)
        return wrapper

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

    def source_wiring_unwired_with_decoy_comment(snapshot, generated, golden, main, config, smoke):
        # Unwire the real FastAPI kwargs but keep the wiring literals present as
        # an inert comment. A whole-file substring check stays green; the AST
        # keyword check must not.
        main = main.replace(
            "description=OPENAPI_DESCRIPTION,", 'description="A rewritten description",', 1
        ).replace(
            "openapi_tags=OPENAPI_TAGS,", 'openapi_tags=[{"name": "x", "description": "y"}],', 1
        )
        main = main.replace(
            "    app = FastAPI(",
            "    # description=OPENAPI_DESCRIPTION, openapi_tags=OPENAPI_TAGS,\n"
            "    app = FastAPI(",
            1,
        )
        return snapshot, generated, golden, main, config, smoke

    def source_wiring_shadowed_by_local_rebinding(snapshot, generated, golden, main, config, smoke):
        # Keep every FastAPI(...) keyword byte-for-byte as committed; rebind the
        # names it references in create_app's own scope, BEFORE the call. The
        # running app then exports "(rewritten)" / a hollow tag list, while the
        # module-level literals (and the golden/snapshot) are untouched. A
        # parsed-call / substring guard cannot see this: the expression text is
        # still OPENAPI_DESCRIPTION / OPENAPI_TAGS, it just resolves elsewhere.
        main = main.replace(
            '    """Create and configure the FastAPI application."""\n    app = FastAPI(',
            '    """Create and configure the FastAPI application."""\n'
            '    OPENAPI_DESCRIPTION = "(rewritten)"\n'
            '    OPENAPI_TAGS = [{"name": "x"}]\n'
            '    app = FastAPI(',
            1,
        )
        return snapshot, generated, golden, main, config, smoke

    def source_wiring_mutated_in_place(snapshot, generated, golden, main, config, smoke):
        # No rebinding at all: mutate the same object the module-level literal
        # points at, before FastAPI(...). The keyword spelling, the module
        # literal, the snapshot and the golden are all byte-for-byte unchanged;
        # only the running app's published catalog is hollow. A scope-resolution
        # guard cannot see this, so this row pins the in-place check.
        main = main.replace(
            '    """Create and configure the FastAPI application."""\n    app = FastAPI(',
            '    """Create and configure the FastAPI application."""\n'
            '    OPENAPI_TAGS.clear()\n'
            '    OPENAPI_TAGS.append({"name": "x", "description": "y"})\n'
            '    app = FastAPI(',
            1,
        )
        return snapshot, generated, golden, main, config, smoke

    def source_wiring_uncompilable(snapshot, generated, golden, main, config, smoke):
        # ast.parse accepts duplicate parameters; symtable (which compiles)
        # rejects them. A guard that called symtable without guarding would let
        # a SyntaxError escape as a traceback instead of a clean FAIL.
        main = main.replace(
            "def create_app() -> FastAPI:", "def create_app(x, x) -> FastAPI:", 1
        )
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
        (
            "description/tags unwired with decoy comment",
            source_wiring_unwired_with_decoy_comment,
            "OPENAPI_DESCRIPTION as description",
        ),
        (
            "description/tags shadowed by local rebinding",
            source_wiring_shadowed_by_local_rebinding,
            "rebinds metadata names in its local scope",
        ),
        (
            "description/tags mutated in place",
            source_wiring_mutated_in_place,
            "mutates metadata constants in place",
        ),
        (
            "create_app does not compile under symtable",
            source_wiring_uncompilable,
            "does not compile as a metadata source",
        ),
        ("config app_name renamed", source_config_renamed, "no longer matches the golden lock"),
        ("create_app deleted", delete_create_app, "no longer defines create_app"),
        ("generated client leaks metadata", generated_leaks_metadata, "single-artifact premise"),
        ("smoke wiring dropped", smoke_unwired, "no longer collects the metadata guard"),
    ]
    for label, mutate, needle in ablations:
        check(label, router_safe(mutate), needle)

    def new_router_without_catalog(snapshot, generated, golden, main, config, smoke, routers):
        routers = dict(routers)
        routers["apps/api/app/api/v1/brand_new.py"] = (
            "from fastapi import APIRouter\n"
            'router = APIRouter(prefix="/brand-new", tags=["brand-new"])\n'
        )
        return snapshot, generated, golden, main, config, smoke, routers

    def invented_tag_blessed_everywhere(snapshot, generated, golden, main, config, smoke, routers):
        # THE bless channel: source + snapshot + golden agree on a tag no router
        # emits. The three-way lock is green by construction; only the
        # router-derived completeness invariant can see it.
        entry = {"name": "made-up", "description": "x"}
        main = main.replace(
            "OPENAPI_TAGS = [\n",
            'OPENAPI_TAGS = [\n    {"name": "made-up", "description": "x"},\n',
            1,
        )
        document = json.loads(snapshot)
        document["tags"].insert(0, entry)
        snapshot = json.dumps(document, ensure_ascii=False)
        lock = json.loads(golden)
        lock["tags"].insert(0, entry)
        return (
            snapshot, generated, json.dumps(lock, ensure_ascii=False),
            main, config, smoke, routers,
        )

    def operation_tag_hand_edited(snapshot, generated, golden, main, config, smoke, routers):
        document = json.loads(snapshot)
        operation = next(
            op
            for item in document["paths"].values()
            for op in item.values()
            if isinstance(op, dict) and op.get("tags")
        )
        operation["tags"] = operation["tags"] + ["hand-edited"]
        return (
            json.dumps(document, ensure_ascii=False), generated, golden,
            main, config, smoke, routers,
        )

    def phantom_catalog_entry(snapshot, generated, golden, main, config, smoke, routers):
        # A router is retired: its file is gone and no operation carries the
        # tag, but the reviewed catalog (main/golden/snapshot) is untouched.
        # A byte lock cannot see a stale entry; the derived invariant can.
        routers = {k: v for k, v in routers.items() if "table_views.py" not in k}
        document = json.loads(snapshot)
        for item in document["paths"].values():
            for op in item.values():
                if isinstance(op, dict) and "table-views" in (op.get("tags") or []):
                    op["tags"] = [t for t in op["tags"] if t != "table-views"]
        return (
            json.dumps(document, ensure_ascii=False), generated, golden,
            main, config, smoke, routers,
        )

    def duplicate_catalog_name(snapshot, generated, golden, main, config, smoke, routers):
        document = json.loads(snapshot)
        document["tags"].append(dict(document["tags"][0]))
        return (
            json.dumps(document, ensure_ascii=False), generated, golden,
            main, config, smoke, routers,
        )

    derived = [
        (
            "new router, catalog not updated",
            new_router_without_catalog,
            "tag catalog is incomplete",
        ),
        ("operation tag hand-edited", operation_tag_hand_edited, "tag catalog is incomplete"),
        ("phantom catalog entry", phantom_catalog_entry, "phantom entries"),
        ("duplicate catalog name", duplicate_catalog_name, "duplicate or non-string"),
    ]
    for label, mutate, needle in derived:
        check(label, mutate, needle)

    check_only(
        "invented tag blessed in all three artifacts",
        invented_tag_blessed_everywhere,
        "phantom entries",
        (
            "golden lock",
            "no longer matches",
            "tag catalog is incomplete",
            "duplicate or non-string",
        ),
    )

    def legitimate_new_router(snapshot, generated, golden, main, config, smoke, routers):
        # The positive control: a real new router plus a catalog entry in main,
        # golden AND snapshot. A frozen name table would go stale here; the
        # invariant must stay green.
        routers = dict(routers)
        routers["apps/api/app/api/v1/brand_new.py"] = (
            "from fastapi import APIRouter\n"
            'router = APIRouter(prefix="/brand-new", tags=["brand-new"])\n'
        )
        main = main.replace(
            "OPENAPI_TAGS = [\n",
            "OPENAPI_TAGS = [\n"
            '    {"name": "brand-new", "description": "A newly registered router."},\n',
            1,
        )
        document = json.loads(snapshot)
        document["tags"].insert(
            0, {"name": "brand-new", "description": "A newly registered router."}
        )
        document["paths"]["/api/v1/brand-new"] = {
            "get": {"tags": ["brand-new"], "responses": {"200": {"description": "OK"}}}
        }
        snapshot = json.dumps(document, ensure_ascii=False)
        lock = json.loads(golden)
        lock["tags"].insert(
            0, {"name": "brand-new", "description": "A newly registered router."}
        )
        return (
            snapshot, generated, json.dumps(lock, ensure_ascii=False),
            main, config, smoke, routers,
        )

    check_clean("legitimate new router + catalog entry", legitimate_new_router)

    labels = frozenset(
        [label for label, _, _ in ablations]
        + [label for label, _, _ in derived]
        + ["invented tag blessed in all three artifacts"]
    )
    count = len(ablations) + len(derived) + 1
    if len(labels) != count:
        problems.append("self-test has duplicate case labels")
    return problems, count, 1, labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        problems, ablations, positives, _labels = self_test()
        for problem in problems:
            print(f"openapi-document-metadata: FAIL: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(
            f"openapi-document-metadata: OK "
            f"({ablations} ablations, {positives} positive control)"
        )
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
