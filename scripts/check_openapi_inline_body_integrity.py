#!/usr/bin/env python3
"""Pin the inline (non-``$ref``) bodies in both committed OpenAPI artifacts.

The three landed guards freeze the *component* bodies:

* ``test_openapi_422_unified_envelope.py`` -- ``_ERROR_RESPONSE_BASELINE``
  (4xx/5xx status distribution);
* ``test_openapi_snapshot_body_integrity.py`` -- ``_RESPONSE_BODY_BASELINE``,
  ``_REQUEST_BODY_BASELINE`` and ``_CLIENT_BODY_TOTAL`` (per-component ``$ref``
  distributions and their aggregate);
* ``test_openapi_snapshot_contract.py`` -- ``_SNAPSHOT_FLOOR`` (path/schema
  floors) and the byte-level export fixed point.

PR #190 adds ``_PINNED_ARTIFACTS``: blob ids of the two artifacts the literals
were counted from. That is a provenance note, not a description of the inline
surface -- re-pinning both blob ids alongside a regenerate is one deliberate
act, and every guard then agrees with the new bytes.

The gap this guard closes, reproduced on live ``05a1d4bb`` and on PR #190's
head ``944e23e7``: retyping one inline ``application/json`` schema in BOTH
artifacts (``object<string>`` -> ``object<number>``) keeps all seven OpenAPI
guards GREEN, including ``_PINNED_ARTIFACTS`` once the two blob ids are
re-pinned. 75 declared bodies are not ``$ref`` bodies -- 71 inline
``application/json`` responses, 1 inline request, and 3 non-JSON media
(``image/svg+xml``, 2 x ``text/html``). None of them has an independent fixed
point: the component baselines cannot see them, the snapshot floor counts
paths/schemas, and the byte fixed point only proves the snapshot equals its
own normalizer.

``_INLINE_BODY_BASELINE`` is a literal in this file, keyed by operation, not
derived from either artifact. The committed snapshot's inline distribution
must equal it exactly, and the generated client's inline shapes and non-JSON
media must equal their pins exactly. A coordinated regenerate that drifts an
inline body in both halves now fails here.

Reads committed bytes only: stdlib, no API venv, no Python 3.15, no wheel, no
PostgreSQL, no ``node_modules``. Run directly, collect with pytest, or run the
in-file ablations with ``--self-test``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
GENERATED = ROOT / "packages" / "api-client" / "src" / "generated" / "openapi.d.ts"
SMOKE = ROOT / "scripts" / "smoke.sh"
SELF = Path(__file__).name

METHODS = frozenset({"get", "put", "post", "patch", "delete", "options", "head", "trace"})

# Independent fixed point: the declared inline (non-$ref) body of each
# operation, by method + path + response code (or "requestBody"). Literal here,
# not recomputed from the artifacts: a regenerate that moves both halves and
# re-pins the provenance blob ids must still be caught. Update in the same
# commit as an intentional contract change and say why.
_INLINE_BODY_BASELINE = {
    'GET /api/v1/admin/audit-logs 200': 'application/json object<*>',
    'GET /api/v1/admin/audit-logs/export 200': 'application/json empty',
    'GET /api/v1/admin/audit-logs/export-excel 200': 'application/json empty',
    'GET /api/v1/admin/audit-logs/online-duration 200': 'application/json array<object<*>>',
    'GET /api/v1/admin/audit-logs/stats 200': 'application/json object<*>',
    'GET /api/v1/admin/build-static/status 200': 'application/json object<*>',
    'GET /api/v1/admin/content/pages 200': 'application/json object<*>',
    'GET /api/v1/admin/content/pages/{page_id}/versions 200':
        'application/json array<ref:ContentVersionResponse>',
    'GET /api/v1/admin/imports 200': 'application/json object<*>',
    'GET /api/v1/admin/imports/studio/dataset-versions 200':
        'application/json array<ref:DatasetVersionResponse>',
    'GET /api/v1/admin/imports/studio/drafts 200':
        'application/json array<ref:ImportDraftListItemResponse>',
    'GET /api/v1/admin/imports/{import_id} 200': 'application/json object<*>',
    'GET /api/v1/admin/imports/{import_id}/status 200': 'application/json object<*>',
    'GET /api/v1/admin/modules/{module_key}/template 200': 'application/json empty',
    'GET /api/v1/admin/page-builder/pages/{page_id}/versions 200':
        'application/json array<ref:PageDefinitionVersionResponse>',
    'GET /api/v1/admin/releases/{release_id} 200': 'application/json object<*>',
    'GET /api/v1/admin/settings/{section} 200': 'application/json object<*>',
    'GET /api/v1/admin/timeout-config 200': 'application/json object<integer>',
    'GET /api/v1/assemblies 200': 'application/json array<ref:AssemblySummaryResponse>',
    'GET /api/v1/blast/databases 200': 'application/json array<ref:BlastDatabaseResponse>',
    'GET /api/v1/content/downloads 200': 'application/json array<ref:DownloadFileResponse>',
    'GET /api/v1/content/news 200': 'application/json array<ref:NewsResponse>',
    'GET /api/v1/content/pages 200': 'application/json array<ref:StaticPageResponse>',
    'GET /api/v1/content/publications 200':
        'application/json array<ref:app__schemas__content__PublicationResponse>',
    'GET /api/v1/content/snapshot 200': 'application/json object<*>',
    'GET /api/v1/expression/genes/{gene_id}/expression 200': 'application/json object<*>',
    'GET /api/v1/expression/libraries 200': 'application/json object<*>',
    'GET /api/v1/expression/libraries/{public_id} 200': 'application/json object<*>',
    'GET /api/v1/expression/search 200': 'application/json object<*>',
    'GET /api/v1/genes/assemblies 200': 'application/json array<ref:AssemblyResponse>',
    'GET /api/v1/genes/assemblies/{assembly_id}/chromosomes 200':
        'application/json array<ref:ChromosomeResponse>',
    'GET /api/v1/genes/{gene_id}/genome-view.svg 200': 'image/svg+xml empty',
    'GET /api/v1/health/live 200': 'application/json object<string>',
    'GET /api/v1/health/ready 200': 'application/json object<*>',
    'GET /api/v1/homologs/genes/{gene_id}/homologs 200': 'application/json object<*>',
    'GET /api/v1/homologs/search 200': 'application/json object<*>',
    'GET /api/v1/jobs/events 200': 'application/json empty',
    'GET /api/v1/mutants 200': 'application/json array<ref:MutantLineResponse>',
    'GET /api/v1/mutants/{public_id}/phenotypes 200':
        'application/json array<ref:PhenotypeResponse>',
    'GET /api/v1/page-definitions/published-routes 200':
        'application/json array<ref:PublishedPageDefinitionRoute>',
    'GET /api/v1/preview/test-data/mutation-sites/by-gene 200':
        'application/json array<ref:PreviewMutationSiteItem>',
    'GET /api/v1/releases 200': 'application/json array<ref:ReleaseResponse>',
    'GET /api/v1/search/suggest 200': 'application/json array<object<*>>',
    'GET /api/v1/seeds/inventory 200': 'application/json array<ref:SeedInventoryResponse>',
    'GET /api/v1/seeds/requests 200':
        'application/json array<ref:app__schemas__seed__SeedRequestResponse>',
    'GET /api/v1/site/content 200': 'application/json object<string>',
    'GET /api/v1/sra/run/{accession} 200': 'application/json object<*>',
    'GET /api/v1/sra/samples 200': 'application/json object<*>',
    'GET /api/v1/stats/chromosome-density 200':
        'application/json array<ref:ChromosomeDensitySummary>',
    'GET /api/v1/stats/discovery-trend 200': 'application/json array<ref:DiscoveryTrendPoint>',
    'GET /api/v1/stats/mutagens 200': 'application/json array<ref:MutagenCount>',
    'GET /api/v1/stats/releases 200': 'application/json array<ref:ReleaseSummary>',
    'GET /api/v1/stats/summary/impact 200': 'application/json array<ref:ImpactSummaryItem>',
    'GET /api/v1/stats/summary/variant-types 200':
        'application/json array<ref:VariantTypeSummaryItem>',
    'GET /api/v1/tracks 200': 'application/json array<object<*>>',
    'GET /api/v1/tracks/categories 200': 'application/json array<object<*>>',
    'GET /api/v1/tracks/jbrowse-config 200': 'application/json object<*>',
    'GET /api/v1/tracks/{track_id} 200': 'application/json object<*>',
    'GET /api/v1/variants/region 200': 'application/json array<ref:VariantResponse>',
    'GET /api/v1/widget/{name} 200': 'text/html string',
    'GET /health 200': 'application/json object<string>',
    'POST /api/v1/admin/build-static 201': 'application/json object<*>',
    'POST /api/v1/admin/imports 201': 'application/json object<*>',
    'POST /api/v1/admin/imports/uploads/multipart 201': 'application/json object<*>',
    'POST /api/v1/admin/imports/uploads/multipart/{upload_id}/complete 200':
        'application/json object<*>',
    'POST /api/v1/admin/imports/{import_id}/retry 200': 'application/json object<*>',
    'POST /api/v1/admin/releases 201': 'application/json object<*>',
    'POST /api/v1/admin/releases/{release_id}/publish 200': 'application/json object<*>',
    'POST /api/v1/admin/releases/{release_id}/ready 200': 'application/json object<*>',
    'POST /api/v1/admin/releases/{release_id}/rollback 200': 'application/json object<*>',
    'POST /api/v1/admin/releases/{release_id}/validate 200': 'application/json object<*>',
    'POST /api/v1/admin/widgets/{name}/preview 200': 'text/html string',
    'POST /api/v1/tools/enrichment 200': 'application/json other:79099c57',
    'PUT /api/v1/admin/settings/{section} 200': 'application/json object<*>',
    'PUT /api/v1/admin/settings/{section} requestBody': 'application/json object<*>',
}

# The generated client prints inline ``application/json`` bodies as anonymous
# object types, and the three non-JSON media as their own content keys. Both
# distributions are pinned exactly, so a shape retyped in the snapshot alone,
# in the client alone, or in both together fails.
_CLIENT_INLINE_SHAPES = {
    '[key:string]:number;': 1,
    '[key:string]:string;': 3,
    '[key:string]:unknown;': 33,
    '[key:string]:unknown;[]': 4,
}
_CLIENT_MEDIA = {'image/svg+xml': 1, 'text/html': 2}

CLIENT_INLINE = re.compile(r'"application/json":\s*\{\n(.*?)\n\s*\}(\[\])?;', re.S)
NON_JSON_MEDIA = ("image/svg+xml", "text/html")


def _strip_title(node):
    if isinstance(node, dict):
        return {k: _strip_title(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_title(v) for v in node]
    return node


def _label(schema) -> str:
    """A stable, human-readable label for an inline schema shape."""
    schema = _strip_title(schema)
    if not schema:
        return "empty"
    if not isinstance(schema, dict):
        digest = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        return "other:" + digest[:8]
    if "$ref" in schema:
        return "ref:" + schema["$ref"].split("/")[-1]
    kind = schema.get("type")
    if kind == "array":
        return "array<" + _label(schema.get("items") or {}) + ">"
    if kind == "object":
        extra = schema.get("additionalProperties")
        inner = "*" if extra is True else _label(extra if extra is not None else {})
        return "object<" + inner + ">"
    if isinstance(kind, str):
        return kind
    return "other:" + hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:8]


def _operations(document: dict):
    for path, item in sorted(document.get("paths", {}).items()):
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                yield method.upper(), path, operation


def _snapshot_inline(document: dict) -> dict[str, str]:
    """Every declared body that is not a direct ``$ref`` to a component."""
    found: dict[str, str] = {}
    for method, path, operation in _operations(document):
        for code, response in (operation.get("responses") or {}).items():
            for media, value in (response.get("content") or {}).items():
                schema = (value or {}).get("schema") or {}
                if media == "application/json" and isinstance(schema, dict) and "$ref" in schema:
                    continue
                found[f"{method} {path} {code}"] = f"{media} {_label(schema)}"
        request = operation.get("requestBody") or {}
        for media, value in (request.get("content") or {}).items():
            schema = (value or {}).get("schema") or {}
            if media == "application/json" and isinstance(schema, dict) and "$ref" in schema:
                continue
            found[f"{method} {path} requestBody"] = f"{media} {_label(schema)}"
    return found


def _client_inline(generated: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for body, array in CLIENT_INLINE.findall(generated):
        key = re.sub(r"\s+", "", body) + ("[]" if array else "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _client_media(generated: str) -> dict[str, int]:
    return {media: generated.count(f'"{media}"') for media in NON_JSON_MEDIA}


def failures(
    document: dict,
    generated: str,
    smoke: str,
    *,
    baseline: dict[str, str] | None = None,
) -> list[str]:
    found: list[str] = []
    pinned = _INLINE_BODY_BASELINE if baseline is None else baseline
    actual = _snapshot_inline(document)

    missing = sorted(set(pinned) - set(actual))
    extra = sorted(set(actual) - set(pinned))
    changed = sorted(k for k in set(pinned) & set(actual) if pinned[k] != actual[k])
    for key in missing:
        found.append(f"{key}: inline body no longer declared")
    for key in extra:
        found.append(f"{key}: unexpected inline body declared")
    for key in changed:
        found.append(f"{key}: inline body retyped {pinned[key]} -> {actual[key]}")
    if missing or extra or changed:
        found.append(
            "the snapshot's inline-body distribution differs from "
            "_INLINE_BODY_BASELINE: a coordinated edit to both artifacts "
            "cannot be seen by comparing them to each other"
        )

    client_shapes = _client_inline(generated)
    if client_shapes != _CLIENT_INLINE_SHAPES:
        found.append(
            f"the generated client's inline shapes are {client_shapes}, not the "
            f"pinned {_CLIENT_INLINE_SHAPES}"
        )
    client_media = _client_media(generated)
    if client_media != _CLIENT_MEDIA:
        found.append(
            f"the generated client's non-JSON media are {client_media}, not the "
            f"pinned {_CLIENT_MEDIA}"
        )

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer does not invoke the inline-body guard")
    return found


def _load():
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


# ---------------------------------------------------------------------------
# pytest-collectible proofs
# ---------------------------------------------------------------------------


def test_committed_tree_has_pinned_inline_bodies() -> None:
    assert failures(*_load()) == []


def test_coordinated_inline_drift_is_rejected() -> None:
    """Retype one inline schema in BOTH halves; the pin must fail."""
    document, generated, smoke = _load()
    before = _snapshot_inline(document).get("GET /api/v1/health/live 200")
    assert before == "application/json object<string>"
    for _method, path, operation in _operations(document):
        if path == "/api/v1/health/live":
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            schema["additionalProperties"]["type"] = "number"
            break
    needle = "                        [key: string]: string;"
    assert needle in generated
    generated = generated.replace(needle, "                        [key: string]: number;", 1)
    found = failures(document, generated, smoke)
    assert any("retyped" in failure for failure in found), found


def test_a_dropped_inline_body_is_rejected() -> None:
    document, generated, smoke = _load()
    for _method, path, operation in _operations(document):
        if path == "/api/v1/health/live":
            operation["responses"]["200"].pop("content", None)
            break
    assert any("no longer declared" in failure for failure in failures(document, generated, smoke))


def test_a_phantom_inline_body_is_rejected() -> None:
    document, generated, smoke = _load()
    for _method, path, operation in _operations(document):
        if path == "/api/v1/health/live":
            operation["responses"]["418"] = {
                "content": {"application/json": {"schema": {"type": "object"}}}
            }
            break
    found = failures(document, generated, smoke)
    assert any("unexpected inline body" in failure for failure in found)


def test_client_shape_retyped_alone_is_rejected() -> None:
    document, generated, smoke = _load()
    before = _client_inline(generated)
    assert before.get("[key:string]:string;") == 3
    needle = "                        [key: string]: string;"
    assert needle in generated
    generated = generated.replace(needle, "                        [key: string]: boolean;", 1)
    assert _client_inline(generated) != before
    assert any("inline shapes" in failure for failure in failures(document, generated, smoke))


def test_non_json_media_dropped_is_rejected() -> None:
    document, generated, smoke = _load()
    generated = generated.replace('"image/svg+xml": unknown;', "", 1)
    assert any("non-JSON media" in failure for failure in failures(document, generated, smoke))


def test_repinning_the_baseline_alone_is_not_enough() -> None:
    """A literal bump without an artifact change must still fail the pin."""
    document, generated, smoke = _load()
    bumped = dict(_INLINE_BODY_BASELINE)
    bumped["GET /api/v1/health/live 200"] = "application/json object<number>"
    found = failures(document, generated, smoke, baseline=bumped)
    assert any("retyped" in failure for failure in found)


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, smoke = _load()
    unwired = smoke.replace(f"scripts/{SELF}", "", 1)
    assert unwired != smoke
    assert any("does not invoke" in failure for failure in failures(document, generated, unwired))


def _self_test() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            problems.append(f"{test.__name__}: {exc or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-inline-bodies: FAIL self-test: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-inline-bodies: OK ({len(tests)} checks)")
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
            print(f"openapi-inline-bodies: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-inline-bodies: OK ({len(_INLINE_BODY_BASELINE)} pinned bodies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
