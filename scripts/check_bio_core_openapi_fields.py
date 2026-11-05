#!/usr/bin/env python3
"""Per-endpoint field ledger: OpenAPI snapshot == Pydantic model == kernel keys.

``GET /tools/sequence/capabilities`` advertises ``programs``, the compute
operations a client may call.  The bytes say something narrower than the spec
table it claims to summarise:

* ``/tools/intervals/overlap`` is served, schematised, exported into
  ``packages/api-client/openapi.json`` and listed in spec §7.1 — but it is
  served by its own router, so it never enters the roster.  A client that
  enumerates ``programs`` cannot discover an endpoint the roster exists to
  describe;
* the roster mixes path segments (``"reverse-complement"``, ``"kmers"``) with
  verb labels (``"align"``, ``"stats"``, ``"orfs"``, ``"translate"``).  Checked
  against ``openapi.json`` alone, three of the six verbs name no path at all —
  the translation was never pinned, so the list only looks complete because
  everybody reads it against the router instead of against the document.

Neither is visible to any existing gate.  ``check-contract.sh`` diffs
``app.main:app`` against ``openapi.json`` (a Python mirror compared with
itself); the numeric parity guard compares constants; the surface guard derives
its program list from ``@router.post`` decorators, i.e. from the router, and so
inherits the bug it is supposed to catch.  This file compares, per endpoint,

    OpenAPI response schema  ==  Pydantic response model  ==  kernel dict keys

and pins ``programs`` to the paths ``openapi.json`` actually serves.  ``engine``
is skipped throughout: it is the implementation identity the service fills from
the live bridge, never a value copied out of a kernel result.  Fields the
Python layer owns by design (``engine``, the echo of a request field, a value
read from PostgreSQL, a wrapper list or per-question struct) are declared in the
tables below with a reason, so the ledger says *which side owns the value*
instead of accepting whatever is there.

Sources are read as bytes: no wheel, no cargo, no FastAPI import, no PostgreSQL,
so this runs before the expensive build.  ``--self-test`` injects one-sided
mutations into copies of those bytes and asserts each is caught.

Usage:
    python3 scripts/check_bio_core_openapi_fields.py --self-test
    python3 scripts/check_bio_core_openapi_fields.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "packages/api-client/openapi.json"
SCHEMA_PY = ROOT / "apps/api/app/schemas/sequence_tools.py"
SEQUENCE_SERVICE_PY = ROOT / "apps/api/app/services/sequence_tools_service.py"
OVERLAP_SERVICE_PY = ROOT / "apps/api/app/services/interval_overlap_service.py"
BINDINGS_RS = ROOT / "packages/bio-core/src/bindings.rs"

PREFIX = "/api/v1"

#: Value the service fills from the live bridge status, never from a kernel dict.
ENGINE_FIELD = "engine"

#: Response fields whose value the *Python* side owns, per model, with a reason.
#: A field that is not a kernel key and not listed here is a hole: the service
#: would have to invent it.
PYTHON_OWNED: dict[str, dict[str, str]] = {
    "MatchHit": {
        "start": "1-based conversion of the kernel start0 (hit_dict sets both)",
        "end": "the kernel end0 is already the 1-based inclusive end",
    },
    "OrfCandidate": {
        "start": "1-based conversion of the kernel start0",
        "end": "the kernel end0 is already the 1-based inclusive end",
    },
    "SequenceMatchResponse": {
        "count": "len() of the truncated hit list",
        "method": "echo of the request's mode",
    },
    "SequenceAlignResponse": {
        "mode": "echo of the request's mode",
        "coordinate_system": "constant: public coordinates are 1-based inclusive",
    },
    "OrfResponse": {
        "candidates": "shapes the kernel's Vec<OrfCandidate>",
        "count": "len() of that list",
    },
    "KmerResponse": {
        "items": "shapes the kernel's (kmer, count) pairs",
    },
    "KmerItem": {
        "kmer": "first element of a kernel (kmer, count) pair",
        "count": "second element of a kernel (kmer, count) pair",
    },
    "FormatInspectResponse": {
        "fmt": "echo of the request's fmt",
        "valid": "true once the kernel validator returned",
        "record_count": "the bed validator returns a bare count",
    },
    "OverlapResponse": {
        "assembly": "resolved from PostgreSQL against the published ReleaseContext",
        "release": "resolved from the ReleaseContext",
        "queries": "shapes one kernel OverlapQuery per requested region",
        "coordinate_system": "constant: public coordinates are 1-based inclusive",
    },
    "OverlapQueryResult": {
        "query": "echo of the requested region (1-based inclusive)",
    },
    "ReverseComplementResponse": {
        "alphabet": "echo of the requested alphabet",
        "length": "len() of the returned sequence",
    },
}

# One row per advertised compute/format endpoint.
#   label, path, Pydantic response model, kernel binding, body shaping,
#   service file that shapes the body.
# Shaping tells the guard how the service turns kernel output into the model:
#   scalar  -> one kernel string/number becomes one response field
#   list    -> kernel returns Vec<dict>; the model names the item fields
#   call    -> ``Model(**raw, ...)``; kernel dict keys are the field source
#   explicit-> the service reads keys one by one off ``raw``
#   count   -> the validator returns a bare integer
#   overlap -> per-region dicts assembled from two Rust files
ENDPOINTS: tuple[tuple[str, str, str, str, str, Path], ...] = (
    ("sequence/reverse-complement", "/tools/sequence/reverse-complement",
     "ReverseComplementResponse", "reverse_complement", "scalar", SEQUENCE_SERVICE_PY),
    ("sequence/match", "/tools/sequence/match",
     "SequenceMatchResponse", "find_matches", "list", SEQUENCE_SERVICE_PY),
    ("sequence/align", "/tools/sequence/align",
     "SequenceAlignResponse", "align_pairwise", "call", SEQUENCE_SERVICE_PY),
    ("sequence/stats", "/tools/sequence/stats",
     "SequenceStatsResponse", "sequence_statistics", "call", SEQUENCE_SERVICE_PY),
    ("sequence/orfs", "/tools/sequence/orfs",
     "OrfResponse", "find_orfs", "list", SEQUENCE_SERVICE_PY),
    ("sequence/translate", "/tools/sequence/translate",
     "TranslateResponse", "translate_sequence", "call", SEQUENCE_SERVICE_PY),
    ("sequence/kmers", "/tools/sequence/kmers",
     "KmerResponse", "kmer_counts", "explicit", SEQUENCE_SERVICE_PY),
    ("sequence/inspect", "/tools/sequence/inspect",
     "FormatInspectResponse", "validate_fasta", "count", SEQUENCE_SERVICE_PY),
    ("intervals/overlap", "/tools/intervals/overlap",
     "OverlapResponse", "overlap_intervals", "overlap", OVERLAP_SERVICE_PY),
)

#: Nested item model per response model, for the list-shaped endpoints.
ITEM_MODELS: dict[str, str] = {
    "SequenceMatchResponse": "MatchHit",
    "OrfResponse": "OrfCandidate",
    "KmerResponse": "KmerItem",
    "OverlapResponse": "OverlapQueryResult",
}

#: Endpoints whose response is a single kernel value, not a dict.
SCALAR_KERNEL_FIELD: dict[str, str] = {
    "ReverseComplementResponse": "sequence",
}


def _fail(label: str, detail: str) -> str:
    return f"{label}: {detail}"


# --- OpenAPI ---------------------------------------------------------------


def openapi_response_schema(doc: dict, path: str) -> str:
    entry = doc["paths"][f"{PREFIX}{path}"]
    operation = entry.get("post") or entry.get("get")
    if operation is None:
        raise ValueError(f"{path}: no GET/POST in the OpenAPI snapshot")
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


def openapi_fields(doc: dict, model: str) -> set[str]:
    return set(doc["components"]["schemas"][model]["properties"])


#: Path prefixes the ``programs`` roster is responsible for.  BLAST, seqfetch,
#: ld, enrichment and the other pre-existing /tools routers are outside this
#: document's scope (spec §7.1 is the *new* surface); adding them here would
#: turn an honest roster into a false claim about routers it never described.
ROSTER_PREFIXES: tuple[str, ...] = ("tools/sequence/", "tools/intervals/")


def served_paths(doc: dict) -> set[str]:
    """Compute paths under the roster prefixes, minus GET-only capabilities."""
    out: set[str] = set()
    for path, entry in doc["paths"].items():
        if not path.startswith(PREFIX + "/"):
            continue
        relative = path[len(PREFIX) + 1:]
        if not relative.startswith(ROSTER_PREFIXES):
            continue
        if set(entry) == {"get"}:
            continue  # capabilities is a description, not a compute program
        out.add(relative)
    return out


# --- Pydantic --------------------------------------------------------------


def pydantic_fields(schema_py: str, model: str) -> set[str]:
    match = re.search(
        rf"^class {model}\(BaseModel\):\n(.*?)(?=^class |\Z)", schema_py, re.M | re.S
    )
    if match is None:
        raise ValueError(f"{model}: Pydantic model not found")
    fields = set()
    for line in match.group(1).splitlines():
        field = re.match(r"    ([a-z][a-z0-9_]*)\s*:", line)
        if field:
            fields.add(field.group(1))
    if not fields:
        raise ValueError(f"{model}: model has no fields")
    return fields


def pydantic_programs(schema_py: str) -> list[str]:
    match = re.search(
        r"programs:\s*list\[str\]\s*=\s*Field\(\s*default_factory=lambda:\s*\[(.*?)\]\s*\)",
        schema_py,
        re.S,
    )
    if match is None:
        raise ValueError("programs: Pydantic default list not found")
    # Labels are path segments: hyphens and slashes both occur
    # (``reverse-complement``, ``intervals/overlap``).
    return re.findall(r'"([a-z][a-z0-9/-]*)"', match.group(1))


# --- Kernel ----------------------------------------------------------------


def kernel_binding_body(bindings_rs: str, function: str) -> str:
    match = re.search(rf"^fn {function}\(.*?^\}}\n", bindings_rs, re.M | re.S)
    if match is None:
        raise ValueError(f"{function}: kernel binding not found")
    return match.group(0)


def kernel_keys(bindings_rs: str, function: str) -> set[str]:
    """Keys a binding emits.

    A binding either builds a dict (``set_item``), returns a bare string (both
    reverse complement and the bed validator do), or returns a Vec of dicts
    built by a helper.  Returning an empty set for the first two is honest --
    the caller decides what a scalar endpoint means -- but silently accepting an
    empty set for a dict-shaped binding would hide a deleted key, so the field
    ledger below compares against the declared kernel keys per model instead.
    """
    body = kernel_binding_body(bindings_rs, function)
    return set(re.findall(r'set_item\(\s*"([a-z][a-z0-9_]*)"', body))


def hit_dict_keys(bindings_rs: str) -> set[str]:
    match = re.search(r"fn hit_dict\b.*?^\}\n", bindings_rs, re.M | re.S)
    if match is None:
        raise ValueError("hit_dict: shared kernel hit dict not found")
    keys = set(re.findall(r'set_item\(\s*"([a-z][a-z0-9_]*)"', match.group(0)))
    if not keys:
        raise ValueError("hit_dict: emits no keys")
    return keys


def orf_dict_keys(bindings_rs: str) -> set[str]:
    """Keys of one ORF dict; ``find_orfs`` builds them inline, not via a helper."""
    return kernel_keys(bindings_rs, "find_orfs")


def overlap_kernel_keys(bindings_rs: str) -> set[str]:
    """Keys ``overlap_intervals`` emits per requested region."""
    return kernel_keys(bindings_rs, "overlap_intervals")


def overlap_hit_keys(bindings_rs: str) -> set[str]:
    """A kernel overlap hit is the tuple (start0, end0, overlap_bp, record_index).

    The binding builds that tuple by hand, so the names the service may read are
    fixed here rather than parsed out of a Rust struct that the FFI does not use.
    """
    body = kernel_binding_body(bindings_rs, "overlap_intervals")
    if "overlap_bp" not in body or "record_index" not in body:
        raise ValueError("overlap_intervals: hit tuple shape changed")
    return {"start0", "end0", "overlap_bp", "record_index"}


# --- Service shaping -------------------------------------------------------


def service_raw_reads(service_py: str, binding: str) -> set[str]:
    """Keys one service function reads off a kernel dict, e.g. ``raw["k"]``.

    Scoped to the function that calls ``_call("<binding>", ...)``: every
    endpoint lives in the same module, so a module-wide scan would let the
    alignment endpoint's ``raw["cigar"]`` be reported against k-mers.
    """
    marker = f'_call(\n            "{binding}"'
    index = service_py.find(marker)
    if index == -1:
        marker = f'_call("{binding}"'
        index = service_py.find(marker)
    if index == -1:
        raise ValueError(f"{binding}: no service call site found")
    tail = service_py[index:]
    end = tail.find("\nasync def ")
    body = tail[:end] if end != -1 else tail
    return set(re.findall(r'\braw\[\s*"([a-z][a-z0-9_]*)"\s*\]', body))


# --- Comparison ------------------------------------------------------------


def _owned(model: str, field: str) -> str | None:
    """Why the Python layer owns this field, or None if it must come from Rust."""
    if field == ENGINE_FIELD:
        return "implementation identity filled from the live bridge status"
    return PYTHON_OWNED.get(model, {}).get(field)


def check(sources: dict[str, str]) -> list[str]:
    """Return every mismatch; an empty list means the three sides agree."""
    errors: list[str] = []
    try:
        doc = json.loads(sources[str(OPENAPI)])
        schema_py = sources[str(SCHEMA_PY)]
        bindings = sources[str(BINDINGS_RS)]
        hit_keys = hit_dict_keys(bindings)
        orf_keys = orf_dict_keys(bindings)
        overlap_keys = overlap_kernel_keys(bindings)
        overlap_hits = overlap_hit_keys(bindings)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot read a source: {exc}"]

    # 1. programs must name exactly the compute paths the document serves.
    try:
        advertised = pydantic_programs(schema_py)
    except ValueError as exc:
        return [str(exc)]
    served = served_paths(doc)
    # programs name the segment after the router prefix ("kmers",
    # "reverse-complement"), which is what a client appends to /tools/sequence/.
    # Everything else drops the ``tools/`` router prefix only, so
    # ``/tools/intervals/overlap`` compares as ``intervals/overlap`` — the
    # namespace is part of the label, not noise to be stripped.
    served = {
        name.removeprefix("tools/sequence/")
        if name.startswith("tools/sequence/")
        else name.removeprefix("tools/")
        for name in served
    }
    if not advertised or not served:
        errors.append("programs: a roster side is empty; refusing a vacuous pass")
    else:
        for name in sorted(served - set(advertised)):
            errors.append(
                _fail(
                    f"program {name!r}",
                    "served and schematised under /tools but absent from programs, "
                    "so a client enumerating programs cannot discover it",
                )
            )
        for name in sorted(set(advertised) - served):
            errors.append(
                _fail(f"program {name!r}", "advertised in programs but no such path is served")
            )

    # 2. Per endpoint: OpenAPI == Pydantic, and every unowned field has a kernel key.
    for label, path, model, binding, shaping, service_path in ENDPOINTS:
        try:
            oa_model = openapi_response_schema(doc, path)
            oa = openapi_fields(doc, oa_model)
            py = pydantic_fields(schema_py, model)
            kernel_set = overlap_keys if shaping == "overlap" else kernel_keys(bindings, binding)
        except (KeyError, ValueError) as exc:
            errors.append(_fail(label, f"cannot read one side: {exc}"))
            continue
        if not oa or not py:
            errors.append(_fail(label, "a side is empty; refusing a vacuous pass"))
            continue
        if not kernel_set and shaping in {"call", "explicit"}:
            errors.append(
                _fail(label, "the kernel emits no dict keys for a dict-shaped response")
            )
            continue

        if oa_model != model:
            errors.append(
                _fail(
                    label,
                    f"OpenAPI response schema is {oa_model!r} but the model is {model!r}",
                )
            )

        for name in sorted(oa ^ py):
            errors.append(
                _fail(
                    label,
                    f"field {name!r} exists on only one side "
                    f"({'OpenAPI' if name in oa else 'Pydantic'}); "
                    "the snapshot and the model disagree",
                )
            )

        for name in sorted(py - kernel_set):
            if shaping in {"scalar", "list", "count"}:
                continue  # the binding returns a value, not a dict of keys
            if _owned(model, name) is None:
                errors.append(
                    _fail(
                        label,
                        f"response field {name!r} has no kernel key behind it "
                        f"(kernel emits {sorted(kernel_set)}) and is not declared "
                        "as Python-owned; the service would have to invent it",
                    )
                )

        # A key the service reads off the kernel dict, which the kernel stopped
        # emitting, is a request-time KeyError. ``**raw`` unpacking is already
        # covered by the ownership check above, so only the explicit readers
        # (``raw["k"]``) need their own pass.
        service_py = sources[str(service_path)]
        if shaping == "explicit":
            try:
                reads = service_raw_reads(service_py, binding)
            except ValueError as exc:
                errors.append(_fail(label, str(exc)))
                continue
            for name in sorted(reads):
                if name not in kernel_set and name not in PYTHON_OWNED.get(model, {}):
                    errors.append(
                        _fail(
                            label,
                            f"service reads raw[{name!r}] but the kernel does not emit "
                            "it; every request would raise KeyError",
                        )
                    )

        # 3. Nested item models are compared the same way: the kernel emits the
        #    keys the item model names, and nothing else may be invented.
        item_model = ITEM_MODELS.get(model)
        if item_model:
            try:
                item_fields = pydantic_fields(schema_py, item_model)
                oa_item = openapi_fields(doc, item_model)
            except (KeyError, ValueError) as exc:
                errors.append(_fail(f"{label} item", str(exc)))
                continue
            for name in sorted(oa_item ^ item_fields):
                errors.append(
                    _fail(
                        f"{label} item {item_model}",
                        f"field {name!r} exists on only one side "
                        f"({'OpenAPI' if name in oa_item else 'Pydantic'})",
                    )
                )
            item_kernel = {
                "OverlapQueryResult": overlap_keys | overlap_hits,
                "MatchHit": hit_keys,
                "OrfCandidate": orf_keys,
                # A k-mer item is a (kmer, count) tuple in the FFI, not a dict,
                # so the two names are the only keys it can carry.
                "KmerItem": {"kmer", "count"},
            }[item_model]
            for name in sorted(item_fields - item_kernel):
                if _owned(item_model, name) is None:
                    errors.append(
                        _fail(
                            f"{label} item {item_model}",
                            f"item field {name!r} has no kernel key behind it "
                            f"(kernel emits {sorted(item_kernel)})",
                        )
                    )

        # 4. Scalar endpoints: the response field must be the kernel's value.
        scalar = SCALAR_KERNEL_FIELD.get(model)
        if scalar is not None:
            emitted = {scalar} | set(PYTHON_OWNED.get(model, {}))
            for name in sorted(py - emitted):
                if _owned(model, name) is None:
                    errors.append(
                        _fail(
                            label,
                            f"response field {name!r} has no kernel value behind it",
                        )
                    )

    return errors


def load_sources() -> dict[str, str]:
    return {
        str(path): path.read_text(encoding="utf-8")
        for path in (
            OPENAPI,
            SCHEMA_PY,
            SEQUENCE_SERVICE_PY,
            OVERLAP_SERVICE_PY,
            BINDINGS_RS,
        )
    }


#: Drifts the live tree carries today, pinned by value and message so a *new*
#: one cannot hide behind them and this entry cannot survive a fix silently.
#: Removing the cause must therefore also remove the entry: ``--self-test``
#: asserts the baseline reproduces exactly.
KNOWN_DRIFT: tuple[tuple[str, str], ...] = ()


def _known(error: str) -> bool:
    return any(error == f"{label}: {detail}" for label, detail in KNOWN_DRIFT)


def new_drift(errors: list[str]) -> list[str]:
    """Errors that are NOT pinned in KNOWN_DRIFT."""
    return [e for e in errors if not _known(e)]


def self_test() -> int:
    """Every one-sided mutation must be caught; the clean tree must match."""
    base = load_sources()
    # The clean tree must reproduce KNOWN_DRIFT exactly: a drift that was fixed
    # but left behind here, or a new one hiding among them, both turn red.
    clean = check(base)
    missing = [f"{label}: {detail}" for label, detail in KNOWN_DRIFT if f"{label}: {detail}" not in clean]
    if missing:
        for entry in missing:
            print(f"FAIL self-test: baseline entry no longer reproduces: {entry}")
        return 1
    unexpected = new_drift(clean)
    if unexpected:
        print(f"FAIL self-test: clean tree has unrecorded drift: {unexpected}")
        return 1

    cases: list[tuple[str, str, str, str]] = [
        (
            "drop a served path from the programs roster",
            str(SCHEMA_PY),
            '            "kmers",\n',
            "",
        ),
        (
            "advertise a program no path serves",
            str(SCHEMA_PY),
            '            "kmers",\n',
            '            "kmers",\n            "phantom",\n',
        ),
        (
            "drop a response field from the OpenAPI snapshot",
            str(OPENAPI),
            '          "distinct_kmers": {\n            "type": "integer",\n            "title": "Distinct Kmers"\n          },\n',
            "",
        ),
        (
            "drop a Pydantic response field",
            str(SCHEMA_PY),
            "    distinct_kmers: int\n",
            "",
        ),
        (
            "rename a kernel dict key",
            str(BINDINGS_RS),
            'd.set_item("distinct_kmers", r.distinct_kmers)?;',
            'd.set_item("distinct_kmer", r.distinct_kmers)?;',
        ),
        (
            "kernel stops emitting a key the service reads",
            str(BINDINGS_RS),
            'd.set_item("valid_windows", r.valid_windows)?;\n',
            "",
        ),
        (
            "a response field with no kernel key and no declared owner",
            str(SCHEMA_PY),
            "    distinct_kmers: int\n",
            "    distinct_kmers: int\n    phantom_metric: int\n",
        ),
        (
            "kernel drops a key the overlap service reads",
            str(BINDINGS_RS),
            'd.set_item("covered_bp", q.covered_bp)?;\n',
            "",
        ),
        (
            "an item field the kernel does not emit",
            str(SCHEMA_PY),
            "class KmerItem(BaseModel):\n    kmer: str\n    count: int\n",
            "class KmerItem(BaseModel):\n    kmer: str\n    count: int\n    phantom: int\n",
        ),
    ]

    failures = 0
    for label, path, old, new in cases:
        mutated = dict(base)
        text = mutated[path]
        if old not in text:
            print(f"FAIL {label}: anchor not found")
            failures += 1
            continue
        mutated[path] = text.replace(old, new, 1)
        if mutated[path] == text:
            print(f"FAIL {label}: mutation did not apply")
            failures += 1
            continue
        found = new_drift(check(mutated))
        if not found:
            print(f"FAIL {label}: drift was not caught")
            failures += 1
        else:
            print(f"PASS {label}: {found[0]}")

    print(f"collected {len(cases)} / {len(cases) - failures} passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove drifts are caught")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    errors = check(load_sources())
    missing = [f"{label}: {detail}" for label, detail in KNOWN_DRIFT if f"{label}: {detail}" not in errors]
    for entry in missing:
        print(f"OPENAPI FIELD DRIFT (recorded, but not reproduced): {entry}", file=sys.stderr)
    for error in new_drift(errors):
        print(f"OPENAPI FIELD DRIFT: {error}", file=sys.stderr)
    if missing or new_drift(errors):
        print("response fields disagree with the kernel they are built from", file=sys.stderr)
        return 1
    print("bio-core OpenAPI field ledger: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
