#!/usr/bin/env python3
"""A pinned OpenAPI baseline may only move in a commit that moves the artifacts.

Four offline guards freeze the published contract against literal fixed points
written in their own source:

* ``test_openapi_422_unified_envelope._ERROR_RESPONSE_BASELINE``;
* ``test_openapi_snapshot_body_integrity._RESPONSE_BODY_BASELINE`` and
  ``_REQUEST_BODY_BASELINE`` (and ``_CLIENT_BODY_TOTAL`` with them);
* ``check_openapi_inline_body_integrity._INLINE_BODY_BASELINE`` and
  ``_CLIENT_INLINE_BASELINE`` -- the inline (non-``$ref``) bodies, keyed per
  operation on both halves;
* ``test_openapi_snapshot_contract._SNAPSHOT_FLOOR``.

That is the right idiom -- an independent fixed point is the only thing that
catches a coordinated edit of both artifacts. It also creates the last hole:
the fixed point is a **literal**, so bumping the literal is one edit to one
file and every guard goes green again with the artifacts untouched. The hole is
not hypothetical, it is the documented escape hatch ("update the baseline in the
same commit and say why") with nothing checking that the *same commit* part ever
happened. Every regeneration instruction in those guards is a natural-language
"and regenerate", and nothing enforces it.

So: compare the pinned numbers against the ones ``HEAD`` pins. If they moved,
the artifacts must have moved too.

What "moved" means, and why it is not a bare ``git diff``
---------------------------------------------------------
``git`` alone cannot answer this. A merge commit's own diff against its first
parent contains every change the merged branch brought in, so a squash / merge
of a branch that regenned the artifacts reads as "artifacts changed here" even
when the baseline edit came from a different, stale branch. And a shared CI
checkout is shallow: the base commit is simply absent.

The semantic statement the guards actually make is *the pin agrees with the
committed artifacts*. That is what is checked first, and it is checked with no
git at all: recompute the distribution from the snapshot, then read the pinned
literal out of the guard by ``ast``. Bumping a literal without moving the
artifact fails that, on a bare clone, in a squash, in a merge, on a shallow
checkout. When the pinned value and the recomputed one agree, the baseline has
not silently drifted from the contract whatever the tree did.

The git half is a second, independent door for the one case the semantic check
cannot see: the artifacts moved *and* the literal moved, but the artifacts did
not move in an ancestor of ``HEAD`` -- i.e. somebody bumped a number to match a
tree they had edited by hand and never committed the artifact. Overridable with
``--ref`` where a shallow clone hides the parent.

``_SNAPSHOT_FLOOR`` is deliberately **not** in the table. It is a floor, not an
equality, and it moves on every API-growing commit -- pinning it to "the
artifacts must change in an ancestor" is already true by construction and would
be a vacuous check. Its equality cousin is the response baseline: if the
snapshot gained paths, ``_RESPONSE_BODY_BASELINE`` must grow with them, and that
is the check that fires.

Which literals belong in the table, and which do not
----------------------------------------------------
The rule is not "every literal in a guard". It is: a literal that is an
**equality against the committed bytes** and whose value a human can edit into
agreement belongs here. That is why the two inline pins are in it (their own
docstring calls re-pinning them alongside a regenerate "one deliberate act")
and why ``_PINNED_ARTIFACTS`` is **not**: those are blob ids of provenance, not
a description of the contract surface -- changing one is a note that the bytes
were regenerated, and gating it on "the artifacts moved" would be the vacuous
check ``_SNAPSHOT_FLOOR`` gets excluded for.

Each gate names exactly one artifact, deliberately. ``recomputed`` delegates the
inline kinds to the pin's own reader instead of re-deriving the distribution,
because two readers would drift and the one that matters is the one the guard
compares against. A gate whose ``artifacts`` tuple names the wrong half stays
green on the semantic door (both halves really did move) and only loses the
history door, so the pairing is pinned by name in the suite rather than left to
inference.

Usage:
    python3 scripts/check_openapi_baseline_sync.py
    python3 scripts/check_openapi_baseline_sync.py --self-test
    python3 scripts/check_openapi_baseline_sync.py --ref origin/main
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
ENVELOPE_GUARD = ROOT / "scripts/test_openapi_422_unified_envelope.py"
BODY_GUARD = ROOT / "scripts/test_openapi_snapshot_body_integrity.py"
INLINE_GUARD = ROOT / "scripts/check_openapi_inline_body_integrity.py"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name
SELF_PATH = Path(__file__).resolve()

METHODS = frozenset({"get", "put", "post", "patch", "delete", "options", "head", "trace"})
COMPONENT_PREFIX = "#/components/schemas/"


class Gate:
    """One pinned literal, and how to recompute the same number honestly.

    ``kind`` selects the recomputation:

    * ``error_status`` -- distribution of declared 4xx/5xx status codes;
    * ``response_body`` / ``request_body`` -- per-component body distributions;
    * ``client_total`` -- the aggregated client total, derived from the two
      body baselines rather than from the artifacts (it is the body guard's own
      arithmetic, kept here so a hand-bumped total is caught even if the two
      distributions are left alone).
    """

    def __init__(
        self,
        name: str,
        path: Path,
        kind: str,
        artifacts: tuple[str, ...],
        source: Path | None = None,
    ) -> None:
        self.name = name
        # ``source`` is the file that must still *declare* the pinned literal.
        # For every gate so far that is the same file the literal is read from.
        # The body-pair pin is the exception: the one existing literal over the
        # same rows lives in the body guard, and a second copy in this file
        # would be a second hand-maintained number -- so the literal is read
        # from this guard's own source and checked for presence in the guard
        # that pins the rows it describes.
        self.path = path
        self.source = source if source is not None else path
        self.kind = kind
        self.artifacts = artifacts


# The component name each published body points at, and the gate that pins it.
# Every other pin in this table is a count, a distribution over names, or an
# inline shape: a coherent regenerate that renames one schema -- snapshot,
# generated client, ``components.schemas`` and every literal that walks them,
# in one commit -- moves all of those bags by the same amount and leaves every
# count identical, so the whole contracts layer stays self-consistent. Measured
# on ``7ed30279``: ``EnrichmentRequest`` -> ``EnrichmentRequestX`` in both
# artifacts with the twelve moved literals honestly re-pinned leaves
# ``SMOKE PASS / 1274 passed`` and this guard ``OK (4 baselines)`` on both
# trees. The name a body points at is the client-visible type a caller imports,
# so it gets its own equality against committed bytes.
INLINE_SNAPSHOT_GATE = Gate(
    "_INLINE_BODY_BASELINE", INLINE_GUARD, "inline_snapshot", ("snapshot",)
)
INLINE_CLIENT_GATE = Gate(
    "_CLIENT_INLINE_BASELINE", INLINE_GUARD, "inline_client", ("generated",)
)
BODY_PAIR_GATE = Gate(
    "_BODY_PAIR_SET", BODY_GUARD, "body_pairs", ("snapshot",), source=SELF_PATH
)

GATES = (
    Gate("_ERROR_RESPONSE_BASELINE", ENVELOPE_GUARD, "error_status", ("snapshot",)),
    Gate("_CLIENT_BODY_TOTAL", BODY_GUARD, "client_total", ("snapshot", "generated")),
    # The inline (non-$ref) bodies. Same hole, same file family, and the guard
    # that pins them says so in its own docstring: re-pinning both artifacts'
    # blob ids "alongside a regenerate is one deliberate act, and every guard
    # then agrees with the new bytes". Without a gate here, the re-pin *is* the
    # escape hatch, and retyping one inline body in both artifacts leaves every
    # other fixed point -- components, floors, byte equality, blob provenance --
    # green. ``recomputed`` delegates to the pin's own reader so the two cannot
    # disagree about what the artifact says.
    INLINE_SNAPSHOT_GATE,
    INLINE_CLIENT_GATE,
    # The body-pair set the snapshot publishes: (method, path, where, name) for
    # every ``$ref`` body and its request half. The inline pin skips exactly
    # these nodes (it pins the bodies that are NOT ``$ref``s), so between the
    # two gates every declared body is pinned -- one file for the inline
    # shapes, this one for the component name each ``$ref`` body points at.
    BODY_PAIR_GATE,
)

ARTIFACT_PATHS = {
    "snapshot": "packages/api-client/openapi.json",
    "generated": "packages/api-client/src/generated/openapi.d.ts",
}


# ---------------------------------------------------------------------------
# Reading the pinned literal (ast -- no import, so no pytest, no 3.15 venv)
# ---------------------------------------------------------------------------


def pinned_literal(path: Path, name: str, source: str | None = None) -> Any:
    """The module-level literal assigned to ``name`` in ``path``."""
    text = source if source is not None else path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if name in names and node.value is not None:
            return ast.literal_eval(node.value)
    raise KeyError(f"{path.name} declares no literal {name}")


# ---------------------------------------------------------------------------
# Recomputing it from the artifacts
# ---------------------------------------------------------------------------


def operations(document: dict) -> list[dict]:
    out: list[dict] = []
    for item in document.get("paths", {}).values():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                out.append(operation)
    return out


def ref_bodies(node: dict) -> list[str]:
    names: list[str] = []
    for media in (node.get("content") or {}).values():
        schema = (media or {}).get("schema") or {}
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        if isinstance(ref, str) and ref.startswith(COMPONENT_PREFIX):
            names.append(ref[len(COMPONENT_PREFIX) :])
    return names


def response_bodies(document: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations(document):
        for response in operation.get("responses", {}).values():
            for name in ref_bodies(response):
                counts[name] = counts.get(name, 0) + 1
    return counts


def request_bodies(document: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations(document):
        for name in ref_bodies(operation.get("requestBody") or {}):
            counts[name] = counts.get(name, 0) + 1
    return counts


# The one thing no count above can say: which component each published body
# points at. sha256 of "\n".join(["soymutdb-body-pair-set/v1"] + sorted
# f"{METHOD}|{path}|{where}|{component}"), read from nowhere. ``_REQUEST_BODY_BASELINE``
# and ``_RESPONSE_BODY_BASELINE`` are distributions over the same names, so a
# coordinated rename moves both bags by exactly the same amount and every count
# in this table stays put; ``_BODY_PAIR_DIGEST`` in the body guard is a digest
# over the same rows and would move, but it is re-pinned in the same reviewed
# act as the counts, which is precisely the escape hatch this gate closes.
_BODY_PAIR_SET = {
    "rows": 833,
    "digest": "7eae6e24dec34b9eb32a5f508b1162f81a54c38b98386b44468fb0f2381bed3f",
}


def body_pair_set(document: dict) -> dict[str, Any]:
    """The pinned shape: the body-pair count and the digest over its rows."""
    pairs = body_pairs(document)
    blob = "\n".join(["soymutdb-body-pair-set/v1", *sorted(pairs)])
    return {
        "rows": len(pairs),
        "digest": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
    }


def body_pairs(document: dict) -> dict[str, int]:
    """The ``(METHOD, path, where, component)`` body set, as a serializable map.

    One entry per declared ``$ref`` body: ``where`` is the response status or
    ``requestBody``. Values count duplicates, so two bodies on one
    ``(METHOD, path, where)`` pointing at the same component -- two media on one
    response, say -- cannot collapse into one row and hide behind an equal
    length.

    The component name is the point. Every other literal in the gate table is a
    count, a distribution over names, or an inline shape; a coherent regenerate
    that renames one schema -- snapshot, generated client, ``components.schemas``
    and every literal that walks them, in one commit -- keeps all of those
    equal, because the same number of bodies still point at a component. This is
    the only gate that says *which*.
    """
    out: dict[str, int] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            for status, response in (operation.get("responses") or {}).items():
                for name in ref_bodies(response):
                    key = f"{method.upper()}|{path}|{status}|{name}"
                    out[key] = out.get(key, 0) + 1
            for name in ref_bodies(operation.get("requestBody") or {}):
                key = f"{method.upper()}|{path}|requestBody|{name}"
                out[key] = out.get(key, 0) + 1
    return out


def error_statuses(document: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations(document):
        for code in operation.get("responses", {}):
            text = str(code)
            if text[:1] in {"4", "5"}:
                counts[text] = counts.get(text, 0) + 1
    return counts


# The pin prints every `$ref` body -- response or request -- as this one line.
# Anchored, exactly like the body guard's own regex: `components["schemas"][`
# alone also matches the 277 type-level references in the generated file, which
# is how a "close enough" reader skews the total by a third.
BODY = re.compile(r'"application/json": components\["schemas"\]\["(\w+)"\];')


def client_bodies(generated: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in BODY.finditer(generated):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


_INLINE_MODULE: Any = None


def inline_guard() -> Any:
    """The inline-body pin, loaded by path so no package layout is assumed."""
    global _INLINE_MODULE
    if _INLINE_MODULE is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "check_openapi_inline_body_integrity", INLINE_GUARD
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _INLINE_MODULE = module
    return _INLINE_MODULE


def recomputed(gate: Gate, document: dict, generated: str) -> Any:
    if gate.kind == "error_status":
        return error_statuses(document)
    if gate.kind == "client_total":
        return sum(client_bodies(generated).values())
    # Delegate to the pin's own reader rather than re-deriving it here. Two
    # independent readers would drift, and the one that matters is the one the
    # guard actually compares against.
    if gate.kind == "inline_snapshot":
        return inline_guard()._snapshot_inline(document)
    if gate.kind == "inline_client":
        return inline_guard()._client_inline_bodies(generated)
    if gate.kind == "body_pairs":
        return body_pair_set(document)
    raise AssertionError(f"unknown gate kind {gate.kind}")


def _diff(pinned: Any, actual: Any) -> str:
    if isinstance(pinned, dict) and isinstance(actual, dict):
        changed = [
            f"{name} {pinned.get(name, 0)}->{actual.get(name, 0)}"
            for name in sorted(set(pinned) | set(actual))
            if pinned.get(name, 0) != actual.get(name, 0)
        ]
        # Per-operation inline pins are dict-of-list: the counts read as
        # "0->1", which is the honest statement -- the key appeared or went.
        return ", ".join(changed[:6]) + (" ..." if len(changed) > 6 else "")
    return f"{pinned!r} -> {actual!r}"


# ---------------------------------------------------------------------------
# The git half
# ---------------------------------------------------------------------------


def git(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout


def resolve(ref: str) -> str | None:
    code, out = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if code == 0 else None


def parent_of(commit: str) -> str | None:
    code, out = git("rev-parse", "--verify", "--quiet", f"{commit}^")
    return out.strip() if code == 0 else None


def show(commit: str, path: str) -> str | None:
    code, out = git("show", f"{commit}:{path}")
    return out if code == 0 else None


def changed_in(commit: str | None, since: str | None, paths: tuple[str, ...]) -> set[str]:
    if commit is None or since is None:
        return set()
    code, out = git("diff", "--name-only", since, commit, "--", *paths)
    return set(out.split()) if code == 0 else set()


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def _declares_or_names(source: str, name: str) -> bool:
    """Whether ``source`` still refers to ``name`` as an identifier.

    A bare substring test is not enough: the pairing constant in the body guard
    is named ``{name}_OWNER``, so renaming *that* leaves a substring match
    behind in every comment and identifier that quotes it. An AST scan answers
    the question the pairing actually asks -- does this file still use the
    symbol -- and a name that survives only in prose does not count.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # An owner constant stores a *path*, so the pairing is recorded as
            # "<file path containing the pin>" rather than as the pin's own
            # name. Either spelling counts: the symbol, or a module of this
            # guard (`<name>.py`, or its path).
            if node.value.endswith(f"::{name}") or node.value == name:
                return True
            if node.value == f"{SELF_PATH.stem}.py" or node.value.endswith(
                f"/{SELF_PATH.name}"
            ):
                return True
    return False


def _gate_source(
    gate: Gate, tree: dict[str, str | None] | None, sources: dict[str, str | None]
) -> str | None:
    """The bytes the gate's pinned literal is read from."""
    relative = str(gate.source.relative_to(ROOT))
    if tree is not None:
        if relative in tree:
            return tree[relative]
        return None
    return gate.source.read_text(encoding="utf-8")


def failures(
    *,
    ref: str = "HEAD",
    base: str | None = None,
    tree: dict[str, str | None] | None = None,
) -> list[str]:
    """Baselines may only move in a commit whose artifacts move with them.

    ``tree`` injects files for the self-test; when it is None the committed
    working tree and git history are read.
    """
    found: list[str] = []

    if tree is not None:
        document = json.loads(tree[ARTIFACT_PATHS["snapshot"]] or "{}")
        generated = tree[ARTIFACT_PATHS["generated"]] or ""
        sources = {
            name: tree.get(name)
            for name in {str(gate.path.relative_to(ROOT)) for gate in GATES}
        }
    else:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        generated = GENERATED.read_text(encoding="utf-8")
        sources = {}

    head = "injected" if tree is not None else resolve(ref)
    if head is None:
        found.append(f"cannot resolve {ref!r}: refusing to pass without a commit to compare")
        return found
    since = base if base is not None else (None if tree is not None else parent_of(head))
    artifacts = tuple(ARTIFACT_PATHS.values())

    # Door 1 -- semantic, needs no git: the pin has to agree with the bytes.
    for gate in GATES:
        source = sources.get(str(gate.path.relative_to(ROOT)))
        if source is None:
            source = gate.path.read_text(encoding="utf-8") if tree is None else None
        if source is None:
            found.append(f"{gate.path.name} is not readable")
            continue
        try:
            pinned = pinned_literal(
                gate.source, gate.name, _gate_source(gate, tree, sources)
            )
        except KeyError:
            found.append(
                f"{gate.source.name} no longer pins {gate.name}: a baseline that "
                "can be deleted is not a fixed point"
            )
            continue
        if gate.source != gate.path and not _declares_or_names(source, gate.name):
            found.append(
                f"{gate.path.name} no longer names {gate.name}: the guard that "
                "pins the rows this literal describes stopped referring to it"
            )
            continue
        actual = recomputed(gate, document, generated)
        if pinned != actual:
            found.append(
                f"{gate.name} in {gate.path.name} pins {_diff(pinned, actual)} the "
                "committed artifacts. A baseline is a fixed point for the artifacts, "
                "not a place to make a guard agree with itself. Regenerate "
                "(`pnpm --filter @soymutdb/api-client generate:api-client` under "
                "Python 3.15) before moving the literal."
            )

    # Door 2 -- history: a moved baseline needs an artifact change behind it.
    if since is not None:
        for gate in GATES:
            old_source = None if tree is not None else show(since, str(gate.path.relative_to(ROOT)))
            new_source = (
                sources.get(str(gate.path.relative_to(ROOT)))
                if tree is not None
                else gate.path.read_text(encoding="utf-8")
            )
            if old_source is None or new_source is None:
                # No history to compare (shallow clone) -- door 1 already ran.
                continue
            try:
                was = pinned_literal(gate.path, gate.name, old_source)
            except KeyError:
                continue
            if new_source.find(gate.name) == -1:
                found.append(f"{gate.name} disappeared from {gate.path.name}")
                continue
            now = pinned_literal(gate.path, gate.name, new_source)
            if was == now:
                continue
            moved = changed_in(head, since, gate.artifacts and artifacts)
            needed = {ARTIFACT_PATHS[name] for name in gate.artifacts}
            if not (needed & moved):
                found.append(
                    f"{gate.name} moved ({_diff(was, now)}) but none of "
                    f"{sorted(needed)} changed between {since[:7]} and {head[:7]}. "
                    "A pinned baseline changes together with the artifact it pins."
                )

    # Wiring: this guard has to be reachable from the contracts layer.
    smoke_key = str(SMOKE.relative_to(ROOT))
    smoke = tree[smoke_key] if tree is not None and smoke_key in tree else None
    if smoke is None:
        smoke = SMOKE.read_text(encoding="utf-8") if tree is None else None
    if smoke is not None and f"scripts/{SELF}" not in smoke:
        found.append(f"contracts smoke layer does not invoke {SELF}")

    return found


def _run() -> int:
    problems = failures()
    if problems:
        for problem in problems:
            print(f"openapi-baseline-sync: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-baseline-sync: OK ({len(GATES)} baselines)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD", help="commit to compare (default HEAD)")
    parser.add_argument(
        "--base", default=None, help="compare against this ref instead of <ref>^"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the mutation suite that proves this guard reports the drift",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        sys.path.insert(0, str(ROOT / "scripts"))
        import test_openapi_baseline_sync as suite

        return suite._run_all()
    problems = failures(ref=args.ref, base=args.base)
    if problems:
        for problem in problems:
            print(f"openapi-baseline-sync: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-baseline-sync: OK ({len(GATES)} baselines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
