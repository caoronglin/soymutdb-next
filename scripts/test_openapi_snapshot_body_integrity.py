"""Pin every body in both committed artifacts to independent literal baselines.

The snapshot guard (``test_openapi_snapshot_contract.py``) and the envelope
guard (``test_openapi_422_unified_envelope.py``) pin the *shape* of error
responses and the path/schema floors. This guard pins the per-component
distribution of **every** ``$ref`` body in both committed artifacts -- to
literals in this file, not to the artifacts themselves:

* ``_RESPONSE_BODY_BASELINE`` -- the exact count of each component referenced
  from a path operation's ``responses`` (136 components, 722 occurrences);
* ``_REQUEST_BODY_BASELINE`` -- the exact count of each component referenced
  from a path operation's ``requestBody`` (82 components, 85 occurrences).

Why both are needed
-------------------
The first version of this guard compared ``expected`` (recomputed from
whichever JSON it received) against ``actual`` (counted in the client), with a
one-sided ``have < want`` check and a single aggregate ``_CLIENT_BODY_TOTAL``
pin. Three classes of drift survived it, all reproduced on live bytes:

1. the 85 request-body lines had **no per-component assertion at all** -- only
   the aggregate total saw them. A real regenerate that retyped a request body
   in *both* artifacts (``UserCreate`` -> ``NewsCreate``, say) kept the total at
   807 and kept both halves agreeing with each other, so every guard stayed
   GREEN while the client typed a request body the API never accepts;
2. a per-component *count shift* between two request bodies (one occurrence of
   ``BlastSubmitRequest`` retyped to ``ReleaseActionRequest``) likewise kept
   the total at 807 and stayed GREEN;
3. the same one-sided, self-referential equality on the **response** side let
   a coordinated retype of a ``200`` (both halves together) stay GREEN.

``expected`` being recomputed from the supplied JSON is the root cause: when
both halves move together, equality is preserved. The fix is the same idiom as
``_ERROR_RESPONSE_BASELINE`` and ``_SNAPSHOT_FLOOR`` -- independent fixed
points that are literals in this file, not derived from either artifact. The
snapshot's response and request distributions must each equal their baseline
exactly, and the generated client's per-component counts must equal the sum of
the two baselines exactly. Nothing is one-sided and nothing is self-referential,
so a coordinated regenerate of both halves cannot pass by moving together --
for *distribution*. Which operation declares each body is pinned separately by
``_BODY_PAIR_DIGEST`` below.

The distribution literals are the one place a human may edit to make a red
guard green, so ``_PINNED_ARTIFACTS`` records which committed bytes they were
counted from. Re-pinning the counts alone -- the regenerate that drifts both
halves and then "fixes" the numbers it broke -- is reported as the artifact
having moved. ``_BODY_PAIR_DIGEST`` is the fourth literal: a permutation that
preserves every count still changes the pair set, so it has its own pin.

The snapshot's top-level ``tags`` catalog went from 6 to 50 entries in #205.
That block is not a body: neither baseline count nor ``_BODY_PAIR_DIGEST`` moves
with it, so only ``snapshot_blob`` follows the artifact.

The generator prints response and request bodies as the same
``"application/json": components["schemas"][...];`` line, which is why the
client total (807) exceeds the response-only count (722): the 85 request
occurrences are the surplus. Splitting the baseline makes that surplus an
explicit, pinned part of the contract instead of an absorbed difference.

Distribution is not topology
----------------------------
The two baselines pin *how many* of each component exist, not *which operation*
declares each one. A permutation of two same-count bodies -- register and
login swapping ``UserCreate`` / ``LoginRequest``, say -- preserves every count,
keeps both halves agreeing and leaves no component undeclared, yet the client
types the wrong request body on the login form. 105 of 136 response components
and 79 of 82 request components sit at count 1, so nearly any two are
swappable. ``_BODY_PAIR_DIGEST`` closes that: it pins the sorted
``(method, path, status|requestBody, component)`` tuples, so topology and
distribution are frozen together. Canonical form (regenerate with it):

* uppercase the HTTP method;
* sort the 807 tuples by the tuple itself (method, path, status, component);
* join each tuple's four fields with one space, records with ``\n``;
* ``sha256`` of that UTF-8 string, no trailing newline.

The baselines stay as the *readable* diagnostic; the digest is the strict pin.

Reads committed bytes only: stdlib, no API venv, no Python 3.15, no PostgreSQL.
Run directly or collect with pytest:
    python3 scripts/test_openapi_snapshot_body_integrity.py
    pytest scripts/test_openapi_snapshot_body_integrity.py -q
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from named_guard_diagnostics import describe_assertion
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name

METHODS = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
COMPONENT_PREFIX = "#/components/schemas/"

# The pin prints every `$ref` body - response or request - as this one line.
BODY = re.compile(r'"application/json": components\["schemas"\]\["(\w+)"\];')

# Independent fixed points. Neither is computed from the supplied artifacts, so
# a coordinated edit to snapshot + client cannot preserve equality. Both are
# exact in both directions: a body the runtime never sends is as wrong as a
# dropped one. Update in the same commit as an intentional contract change and
# say why. (BlastSubmitRequest, ReleaseActionRequest and ImportInspectionRequest
# each appear twice among the request bodies.)

_RESPONSE_BODY_BASELINE = {
    "AboutContentResponse": 1,
    "ActiveReleaseResponse": 1,
    "AdminDashboardSeries": 1,
    "AdminDashboardStats": 1,
    "AdminFeaturesResponse": 2,
    "AdminPluginResponse": 2,
    "AdminPluginsResponse": 1,
    "AdminPublicationListResponse": 1,
    "AdminPublicationResponse": 2,
    "AdminSiteBrandResponse": 2,
    "AlleleFreqResponse": 1,
    "AnalysesDownloadResponse": 1,
    "AnalysesJobListResponse": 1,
    "AnalysesJobResponse": 1,
    "AnalysesSubmitResponse": 1,
    "AnalysesUploadResponse": 1,
    "AnalyticsSummary": 1,
    "ArtifactResponse": 2,
    "AssemblyDetailResponse": 1,
    "BlastDatabaseStateResponse": 1,
    "BlastGenomeTargetResponse": 2,
    "BlastIndexBuildResponse": 2,
    "BlastJobListResponse": 1,
    "BlastJobResponse": 6,
    "BlastResultResponse": 2,
    "ChromosomeDensity": 1,
    "ContentVersionResponse": 1,
    "DashboardStats": 1,
    "DatasetVersionResponse": 1,
    "DeletedNewsListResponse": 1,
    "DiversityResponse": 1,
    "ErrorResponse": 272,
    "ExpPatternResponse": 1,
    "ExportDownloadResponse": 1,
    "ExportManifestResponse": 1,
    "ExportQueryResponse": 1,
    "ExportResponse": 1,
    "ExportStatusResponse": 1,
    "ExternalArticlePreviewResponse": 1,
    "FamilyDetailResponse": 1,
    "FamilyListResponse": 1,
    "FooterContentResponse": 1,
    "FormatInspectResponse": 1,
    "GeneDetail": 1,
    "GeneListResponse": 1,
    "GlobalSearchResponse": 1,
    "GwasJobResponse": 2,
    "GwasResultResponse": 1,
    "GwasUploadResponse": 1,
    "HomeContentResponse": 1,
    "HomepageStats": 1,
    "ImportDraftResponse": 6,
    "ImportInspectionResponse": 2,
    "InternalSearchResponse": 1,
    "KmerResponse": 1,
    "LayoutResponse": 2,
    "LdResponse": 1,
    "LocalTestPreviewMeta": 1,
    "MarkReadResponse": 1,
    "MediaAssetListResponse": 1,
    "MediaAssetResponse": 3,
    "MemberComparisonResponse": 1,
    "MutantLineDetail": 1,
    "NewsDetailResponse": 4,
    "NewsFeaturedResponse": 1,
    "NewsListResponse": 2,
    "NewsReorderResponse": 1,
    "NewsResponse": 1,
    "NotificationListResponse": 1,
    "OntologyRelationshipGraphResponse": 1,
    "OntologySearchResponse": 1,
    "OntologyTermResponse": 1,
    "OrfResponse": 1,
    "OrthologResponse": 1,
    "OverlapResponse": 1,
    "PageDefinitionListResponse": 1,
    "PageDefinitionResponse": 2,
    "PageDefinitionVersionResponse": 1,
    "PageTemplateListResponse": 1,
    "PageTemplateResponse": 3,
    "PageTemplateValidationResponse": 1,
    "PreviewGeneSearchResponse": 1,
    "PreviewMutationSiteItem": 1,
    "PreviewMutationSiteSearchResponse": 1,
    "PreviewResponse": 1,
    "PreviewTokenResponse": 1,
    "PublicBlastSubmission": 1,
    "PublicCapabilitiesResponse": 1,
    "PublicPageDefinitionResponse": 1,
    "PublicationListResponse": 1,
    "PublicationManifestResponse": 1,
    "PublicationTargetListResponse": 1,
    "PublishRequestResponse": 1,
    "RegionStructureResponse": 1,
    "RegistryResponse": 1,
    "ReleaseResponse": 1,
    "ResolvedTableView": 1,
    "ReverseComplementResponse": 1,
    "SeedInventoryResponse": 1,
    "SeedRequestListResponse": 1,
    "SeedRequestStatsResponse": 1,
    "SeqFetchResponse": 1,
    "SequenceAlignResponse": 1,
    "SequenceCapabilitiesResponse": 1,
    "SequenceMatchResponse": 1,
    "SequenceStatsResponse": 1,
    "SettingsDocumentResponse": 3,
    "SettingsHistoryResponse": 1,
    "SettingsSchemaResponse": 1,
    "SettingsValidateResponse": 1,
    "SignedUrlResponse": 2,
    "SiteBrandResponse": 1,
    "SpeciesInstanceHealthResponse": 1,
    "SpeciesInstanceListResponse": 1,
    "SpeciesInstanceResponse": 2,
    "StaticPageDetailResponse": 6,
    "StaticPageMigrationDryRunResponse": 1,
    "StaticPageResponse": 1,
    "TableViewTemplateListResponse": 1,
    "TableViewTemplateResponse": 2,
    "TokenResponse": 2,
    "TranslateResponse": 1,
    "UnreadCountResponse": 1,
    "UploadPresignResponse": 1,
    "UserResponse": 2,
    "ValidationErrorResponse": 268,
    "VariantDetail": 1,
    "VariantListResponse": 1,
    "VariantTypeDistribution": 1,
    "WidgetHealthResponse": 1,
    "WidgetListResponse": 1,
    "WidgetResponse": 3,
    "app__schemas__content__PublicationResponse": 1,
    "app__schemas__publication__PublicationResponse": 3,
    "app__schemas__seed__SeedRequestResponse": 2,
    "app__schemas__seed_request__SeedRequestResponse": 2,
}

_REQUEST_BODY_BASELINE = {
    "AlleleFreqRequest": 1,
    "AnalysesSubmitRequest": 1,
    "AnalysesUploadRequest": 1,
    "ArtifactRequest": 1,
    "BlastDatabaseStateUpdate": 1,
    "BlastIndexBuildRequest": 1,
    "BlastSubmitRequest": 2,
    "DataPatchCreateRequest": 1,
    "DatasetVersionCreateRequest": 1,
    "DiversityRequest": 1,
    "EnrichmentRequest": 1,
    "ExpPatternRequest": 1,
    "ExportQueryRequest": 1,
    "ExportRequest": 1,
    "ExternalArticlePreviewRequest": 1,
    "FeatureUpdateRequest": 1,
    "FieldMappingUpdateRequest": 1,
    "FormatInspectRequest": 1,
    "GwasSubmitRequest": 1,
    "GwasUploadRequest": 1,
    "ImportCommitRequest": 1,
    "ImportCreateRequest": 1,
    "ImportDraftCreateRequest": 1,
    "ImportInspectionRequest": 2,
    "ImportValidationRequest": 1,
    "KmerRequest": 1,
    "LayoutUpdateRequest": 1,
    "LdRequest": 1,
    "LoginRequest": 1,
    "MarkReadRequest": 1,
    "MediaAssetCompleteRequest": 1,
    "MediaAssetUpdateRequest": 1,
    "MultipartCompletePathRequest": 1,
    "MultipartStartRequest": 1,
    "NewsCreate": 1,
    "NewsReorderRequest": 1,
    "NewsUpdate": 1,
    "OrfRequest": 1,
    "OverlapRequest": 1,
    "PageDefinitionCreate": 1,
    "PageDefinitionUpdate": 1,
    "PageTemplateCreate": 1,
    "PageTemplateUpdate": 1,
    "PasswordChangeRequest": 1,
    "PluginStateUpdateRequest": 1,
    "PreviewMutationSiteUpdate": 1,
    "PreviewRequest": 1,
    "PublicationCreate": 1,
    "PublicationRequest": 1,
    "PublicationRollbackRequest": 1,
    "PublicationUpdate": 1,
    "PublishRequest": 1,
    "ReleaseActionRequest": 2,
    "ReleaseCreateRequest": 1,
    "ReleaseReadyRequest": 1,
    "ReverseComplementRequest": 1,
    "SeqFetchRequest": 1,
    "SequenceAlignRequest": 1,
    "SequenceMatchRequest": 1,
    "SequenceStatsRequest": 1,
    "SettingsPatchRequest": 1,
    "SettingsRollbackRequest": 1,
    "SettingsValidateRequest": 1,
    "SiteBrandPatchRequest": 1,
    "SpeciesInstanceCreate": 1,
    "SpeciesInstanceUpdate": 1,
    "StaticBuildRequest": 1,
    "StaticPageCreate": 1,
    "StaticPageMigrationDryRunRequest": 1,
    "StaticPageUpdate": 1,
    "TableViewTemplateCreate": 1,
    "TableViewTemplateUpdate": 1,
    "TranslateRequest": 1,
    "UploadPresignRequest": 1,
    "UserCreate": 1,
    "WidgetCreate": 1,
    "WidgetPreviewRequest": 1,
    "WidgetUpdate": 1,
    "app__schemas__seed__SeedRequestCreate": 1,
    "app__schemas__seed__SeedRequestUpdate": 1,
    "app__schemas__seed_request__SeedRequestCreate": 1,
    "app__schemas__seed_request__SeedRequestUpdate": 1,
}

# A loud aggregate pin, redundant with the two baselines above but a one-line
# "806 not 807" is a better first signal than a 218-component diff.
_CLIENT_BODY_TOTAL = 807

# What the three distribution literals are a count *of*: the committed artifact
# blobs they were counted from, by object id. Without this a regenerate moves
# both halves and then re-pins the numbers passes -- the guard would be
# asserting that a baseline equals itself. Recorded, not derived: recomputing
# these from the artifacts would make the pin self-referential again, which is
# the whole failure this file replaced.
_PINNED_ARTIFACTS = {
    "snapshot_blob": "943b9463d9d180d4483936dfa7c81c5afb6e4753",
    "generated_blob": "5f2c4a407d96083abdac8ac67e44a40f3ed68a89",
}

# Strict topology pin. The two baselines above cannot see a permutation of two
# same-count bodies between operations; this digest of the sorted (method, path,
# status|requestBody, component) tuples can. Independent of both artifacts, as
# literal as the baselines. Regenerate with _body_pair_digest() on an
# intentionally changed contract and update in the same commit, with a reason.
_BODY_PAIR_DIGEST = "f3382283236a34ddf96d10ce984a36bc6266f87d2c63de13aa066f54611a3ecc"


def _operations(document: dict) -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for path, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                out.append((path, method, operation))
    return out


def _ref_bodies(node: dict) -> list[str]:
    """Component names referenced as a $ref body schema under ``node``."""
    names: list[str] = []
    for media in (node.get("content") or {}).values():
        schema = (media or {}).get("schema") or {}
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        if ref:
            names.append(ref.split("/")[-1])
    return names


def _response_bodies(document: dict) -> dict[str, int]:
    """Per-component count of bodies declared in path operations' responses."""
    counts: dict[str, int] = {}
    for _path, _method, operation in _operations(document):
        for response in operation.get("responses", {}).values():
            for name in _ref_bodies(response):
                counts[name] = counts.get(name, 0) + 1
    return counts


def _request_bodies(document: dict) -> dict[str, int]:
    """Per-component count of bodies declared in path operations' requestBody."""
    counts: dict[str, int] = {}
    for _path, _method, operation in _operations(document):
        for name in _ref_bodies(operation.get("requestBody") or {}):
            counts[name] = counts.get(name, 0) + 1
    return counts


def _body_pairs(document: dict) -> list[tuple[str, str, str, str]]:
    """Every (method, path, status|requestBody, component) body declaration."""
    pairs: list[tuple[str, str, str, str]] = []
    for path, method, operation in _operations(document):
        for status, response in operation.get("responses", {}).items():
            for name in _ref_bodies(response):
                pairs.append((method, path, status, name))
        for name in _ref_bodies(operation.get("requestBody") or {}):
            pairs.append((method, path, "requestBody", name))
    return pairs


def _body_pair_digest(document: dict) -> str:
    """sha256 of the canonical, sorted body-pair set (see module docstring).

    Uppercase the method, sort by the tuple itself, join fields with one space
    and records with a newline; hash the UTF-8 bytes with no trailing newline.
    """
    canonical = sorted(
        (method.upper(), path, status, component)
        for method, path, status, component in _body_pairs(document)
    )
    blob = "\n".join(" ".join(pair) for pair in canonical)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _client_bodies(generated: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in BODY.finditer(generated):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


def _expected_client_bodies() -> dict[str, int]:
    """The client prints response and request bodies as the same line."""
    out = dict(_RESPONSE_BODY_BASELINE)
    for name, count in _REQUEST_BODY_BASELINE.items():
        out[name] = out.get(name, 0) + count
    return out


def _git_blob(path: Path) -> str:
    """The object id git would store for these bytes (``hash-object``)."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _baseline_moved_with_the_artifacts() -> list[str]:
    """A baseline edit is only legitimate alongside the artifact edit it pins.

    The distribution literals above are the one place in this file a human may
    edit to make a red guard green. Nothing so far tied that edit to the
    artifacts it describes, so a regenerate that drifts both halves *and*
    re-pins the counts passed every check -- the guard compared a baseline to
    itself.

    ``_PINNED_ARTIFACTS`` records which bytes the numbers were counted from. It
    is a literal too, so updating it is part of the same deliberate act: you
    cannot re-pin the counts without also saying which artifacts produced them,
    and a reviewer sees both in the diff.
    """
    found: list[str] = []
    actual = {
        "snapshot_blob": _git_blob(SNAPSHOT),
        "generated_blob": _git_blob(GENERATED),
    }
    for name, pinned in _PINNED_ARTIFACTS.items():
        if actual[name] != pinned:
            found.append(
                f"the baseline literals were recorded against a different "
                f"artifact: {name} is {actual[name]}, _PINNED_ARTIFACTS pins "
                f"{pinned}. Re-pin the counts and both blob ids together, and "
                "say in the commit why the contract changed"
            )
    return found


def _diff(pinned: dict[str, int], actual: dict[str, int]) -> str:
    """A short, name-level rendering of a distribution mismatch."""
    changed = [
        f"{name} {pinned.get(name, 0)}->{actual.get(name, 0)}"
        for name in sorted(set(pinned) | set(actual))
        if pinned.get(name, 0) != actual.get(name, 0)
    ]
    return ", ".join(changed[:6]) + (" ..." if len(changed) > 6 else "")


def failures(document: dict, generated: str, smoke: str) -> list[str]:
    found: list[str] = []

    operations = _operations(document)
    if not operations:
        found.append("no path operation declares a responses object at all")

    responses = _response_bodies(document)
    requests = _request_bodies(document)
    if not responses:
        found.append("the snapshot declares no response body referencing a component")
    if not requests:
        found.append("the snapshot declares no request body referencing a component")

    client = _client_bodies(generated)
    total = sum(client.values())
    if total != _CLIENT_BODY_TOTAL:
        found.append(
            f"generated client declares {total} application/json component "
            f"body(s), not the pinned {_CLIENT_BODY_TOTAL}: a body was added or "
            "removed in the client half alone"
        )

    # Independent fixed points, exact in both directions. A regenerate of both
    # halves from a drifted backend cannot pass by moving them together.
    if responses != _RESPONSE_BODY_BASELINE:
        found.append(
            "snapshot response bodies differ from the pinned "
            f"_RESPONSE_BODY_BASELINE: {_diff(_RESPONSE_BODY_BASELINE, responses)}"
        )
    if requests != _REQUEST_BODY_BASELINE:
        found.append(
            "snapshot request bodies differ from the pinned "
            f"_REQUEST_BODY_BASELINE: {_diff(_REQUEST_BODY_BASELINE, requests)}"
        )

    # Strict topology pin. The two baselines are multisets, blind to a
    # permutation of two same-count bodies between operations; the digest of
    # the declared pair set sees it. The baselines remain the readable
    # diagnostic, this is the strict pin.
    digest = _body_pair_digest(document)
    if digest != _BODY_PAIR_DIGEST:
        found.append(
            "snapshot body-pair set moved: the pinned _BODY_PAIR_DIGEST is "
            f"{_BODY_PAIR_DIGEST}, the declared pairs hash to {digest}"
        )

    # Exact, two-directional cross-artifact equality against the baselines.
    # Nothing is one-sided: every body in either half is accounted for.
    expected = _expected_client_bodies()
    for name in sorted(set(expected) | set(client)):
        want, have = expected.get(name, 0), client.get(name, 0)
        if have != want:
            found.append(
                f"generated client declares {have} {name} body(s); the pinned "
                f"contract declares {want}"
            )

    # A component the client references but the snapshot does not declare would
    # be a response (or request) the exported contract has no schema for.
    schemas = document.get("components", {}).get("schemas", {})
    for name in sorted(client):
        if name not in schemas:
            found.append(
                f"generated client references {name}, which the snapshot does "
                "not declare in components.schemas"
            )

    # An operation with no 2xx at all is a hole the counts cannot describe.
    for path, method, operation in _operations(document):
        if not any(code.startswith("2") for code in operation.get("responses", {})):
            found.append(f"{method.upper()} {path} declares no 2xx response")

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer does not invoke the body-integrity guard")

    # Last, so a baseline that merely drifted from its artifacts is reported
    # after the distribution diff that says *what* drifted.
    found.extend(_baseline_moved_with_the_artifacts())

    return found


def _load() -> tuple[dict, str, str]:
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def _first_operation(document: dict) -> tuple[str, str, str]:
    """First operation that declares a component-ref 200, plus that ref."""
    for path, method, operation in _operations(document):
        response = operation.get("responses", {}).get("200") or {}
        schema = ((response.get("content") or {}).get("application/json") or {}).get("schema") or {}
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        if ref:
            return path, method, ref.split("/")[-1]
    raise AssertionError("no operation declares a component-ref 200 response")


def _any(failures_: list[str], marker: str) -> bool:
    return any(marker in failure for failure in failures_)


def _retype_first_request(document: dict, old: str, new: str) -> None:
    """Retype the first ``requestBody`` $ref equal to ``old``, in place."""
    for _path, _method, operation in _operations(document):
        for media in ((operation.get("requestBody") or {}).get("content") or {}).values():
            schema = (media or {}).get("schema") or {}
            if isinstance(schema, dict) and schema.get("$ref") == f"{COMPONENT_PREFIX}{old}":
                schema["$ref"] = f"{COMPONENT_PREFIX}{new}"
                return
    raise AssertionError(f"no requestBody declares {old}")


def _swap_client_lines(generated: str, first: str, second: str) -> str:
    """Exchange the first occurrence of two distinct body lines, in place."""
    a = f'"application/json": components["schemas"]["{first}"];'
    b = f'"application/json": components["schemas"]["{second}"];'
    placeholder = '"application/json": components["schemas"]["__SWAP__"];'
    assert a in generated and b in generated
    return generated.replace(a, placeholder, 1).replace(b, a, 1).replace(
        placeholder, b, 1
    )


def test_committed_tree_digest_matches_the_pinned_pair_set() -> None:
    document, _generated, _smoke = _load()
    assert _body_pair_digest(document) == _BODY_PAIR_DIGEST
    assert len(_body_pairs(document)) == _CLIENT_BODY_TOTAL


def test_coordinated_request_body_permutation_is_rejected() -> None:
    """register/login swap request bodies in BOTH halves; counts untouched.

    The two baselines are multisets, so a permutation of two count-1 components
    leaves every assertion above GREEN while the client types the wrong body on
    the login form. Only the pair-set digest sees the topology change.
    """
    document, generated, smoke = _load()
    register = document["paths"]["/api/v1/auth/register"]["post"]["requestBody"]
    login = document["paths"]["/api/v1/auth/login"]["post"]["requestBody"]
    register_ref = register["content"]["application/json"]["schema"]
    login_ref = login["content"]["application/json"]["schema"]
    assert register_ref["$ref"] == f"{COMPONENT_PREFIX}UserCreate"
    assert login_ref["$ref"] == f"{COMPONENT_PREFIX}LoginRequest"
    register_ref["$ref"] = f"{COMPONENT_PREFIX}LoginRequest"
    login_ref["$ref"] = f"{COMPONENT_PREFIX}UserCreate"
    generated = _swap_client_lines(generated, "UserCreate", "LoginRequest")
    found = failures(document, generated, smoke)
    assert _response_bodies(document) == _RESPONSE_BODY_BASELINE
    assert _request_bodies(document) == _REQUEST_BODY_BASELINE
    assert _any(found, "_BODY_PAIR_DIGEST"), found


def test_coordinated_response_body_permutation_is_rejected() -> None:
    """Two 200s swap their success components in BOTH halves; counts untouched."""
    document, generated, smoke = _load()
    genes = document["paths"]["/api/v1/genes"]["get"]["responses"]["200"]
    detail = document["paths"]["/api/v1/genes/{gene_id}"]["get"]["responses"]["200"]
    g_ref = genes["content"]["application/json"]["schema"]["$ref"]
    d_ref = detail["content"]["application/json"]["schema"]["$ref"]
    assert g_ref == f"{COMPONENT_PREFIX}GeneListResponse"
    assert d_ref == f"{COMPONENT_PREFIX}GeneDetail"
    genes["content"]["application/json"]["schema"]["$ref"] = d_ref
    detail["content"]["application/json"]["schema"]["$ref"] = g_ref
    generated = _swap_client_lines(generated, "GeneListResponse", "GeneDetail")
    found = failures(document, generated, smoke)
    assert _response_bodies(document) == _RESPONSE_BODY_BASELINE
    assert _any(found, "_BODY_PAIR_DIGEST"), found


def test_committed_tree_has_matching_response_bodies() -> None:
    found = failures(*_load())
    assert not found, found


def test_success_body_dropped_from_the_client_is_rejected() -> None:
    """The client losing a 200 body the snapshot still declares."""
    document, generated, smoke = _load()
    _path, _method, name = _first_operation(document)
    line = f'"application/json": components["schemas"]["{name}"];'
    assert line in generated
    assert _any(failures(document, generated.replace(line, "", 1), smoke), "body(s)")


def test_success_body_dropped_from_the_snapshot_is_rejected() -> None:
    """Removing a 200's content contracts the declared response distribution.

    The first version of this guard asserted *no* failure here (the client
    would print more of that body than the snapshot declared -- a "surplus",
    invisible to a one-sided check). With an independent baseline the
    contraction itself is a mismatch, so this now fails closed and the name
    means what it says.
    """
    document, generated, smoke = _load()
    path, method, _name = _first_operation(document)
    document["paths"][path][method]["responses"]["200"].pop("content", None)
    assert _any(failures(document, generated, smoke), "_RESPONSE_BODY_BASELINE")


def test_retyped_success_body_is_rejected() -> None:
    """A 200 retyped to another declared schema, in BOTH halves at once."""
    document, generated, smoke = _load()
    path, method, name = _first_operation(document)
    response = document["paths"][path][method]["responses"]["200"]
    schema = response["content"]["application/json"]["schema"]
    assert schema["$ref"] == f"{COMPONENT_PREFIX}{name}"
    schema["$ref"] = f"{COMPONENT_PREFIX}ErrorResponse"
    old_line = f'components["schemas"]["{name}"]'
    assert old_line in generated
    generated = generated.replace(old_line, 'components["schemas"]["ErrorResponse"]', 1)
    found = failures(document, generated, smoke)
    assert _any(found, "_RESPONSE_BODY_BASELINE"), found
    assert _any(found, "pinned contract declares"), found


def test_coordinated_response_body_drift_is_rejected() -> None:
    """A count shift between two success components in BOTH halves at once.

    This is the "client regenerated from a newer backend than the snapshot"
    case the snapshot guard's per-schema field-set check cannot see: one
    operation's ``200`` moves from ``GeneListResponse`` to ``GeneDetail`` and
    the generated client moves with it. Total stays 807, both halves agree,
    no component is undeclared -- the old one-sided guard stayed GREEN.
    """
    document, generated, smoke = _load()
    assert _response_bodies(document).get("GeneListResponse") == 1
    for _path, _method, operation in _operations(document):
        for response in operation.get("responses", {}).values():
            for media in (response.get("content") or {}).values():
                schema = (media or {}).get("schema") or {}
                if isinstance(schema, dict) and schema.get("$ref") == f"{COMPONENT_PREFIX}GeneListResponse":
                    schema["$ref"] = f"{COMPONENT_PREFIX}GeneDetail"
                    break
            else:
                continue
            break
        else:
            continue
        break
    old_line = 'components["schemas"]["GeneListResponse"]'
    assert generated.count(old_line) == 1
    generated = generated.replace(old_line, 'components["schemas"]["GeneDetail"]', 1)
    found = failures(document, generated, smoke)
    assert _any(found, "_RESPONSE_BODY_BASELINE"), found
    assert _any(found, "pinned contract declares"), found


def test_coordinated_request_body_drift_is_rejected() -> None:
    """The named gap: a request body retyped in BOTH halves, total still 807.

    The 85 request lines had only an aggregate pin. A real regenerate from a
    backend that renamed a request schema moved snapshot + client together and
    stayed GREEN on all three guards. Now the request baseline is literal.
    """
    document, generated, smoke = _load()
    _retype_first_request(document, "UserCreate", "NewsCreate")
    old_line = 'components["schemas"]["UserCreate"]'
    assert old_line in generated
    generated = generated.replace(old_line, 'components["schemas"]["NewsCreate"]', 1)
    found = failures(document, generated, smoke)
    assert _any(found, "_REQUEST_BODY_BASELINE"), found
    assert _any(found, "pinned contract declares"), found


def test_request_body_count_shift_is_rejected() -> None:
    """One occurrence of a doubled request component retyped in both halves:
    same total, same component set, different distribution."""
    document, generated, smoke = _load()
    assert sum(_request_bodies(document).get(n, 0) for n in ("BlastSubmitRequest",)) == 2
    _retype_first_request(document, "BlastSubmitRequest", "ReleaseActionRequest")
    old_line = 'components["schemas"]["BlastSubmitRequest"]'
    assert generated.count(old_line) == 2
    generated = generated.replace(old_line, 'components["schemas"]["ReleaseActionRequest"]', 1)
    found = failures(document, generated, smoke)
    assert _any(found, "_REQUEST_BODY_BASELINE"), found


def test_request_bodies_are_pinned_in_the_snapshot_half() -> None:
    """A snapshot-only request-body edit fails even with the client untouched."""
    document, generated, smoke = _load()
    _retype_first_request(document, "UserCreate", "NewsCreate")
    found = failures(document, generated, smoke)
    # The snapshot baseline is the independent fixed point that fires here;
    # the client is unchanged, so it still matches the pinned distribution.
    assert _any(found, "_REQUEST_BODY_BASELINE"), found


def test_client_missing_a_response_body_is_rejected() -> None:
    document, generated, smoke = _load()
    _path, _method, name = _first_operation(document)
    line = f'"application/json": components["schemas"]["{name}"];'
    assert line in generated
    assert _any(failures(document, generated.replace(line, "", 1), smoke), "body(s)")


def test_client_with_an_extra_body_is_rejected() -> None:
    document, generated, smoke = _load()
    line = '"application/json": components["schemas"]["ErrorResponse"];'
    found = failures(document, generated + "\n" + line, smoke)
    assert _any(found, "not the pinned"), found
    assert _any(found, "pinned contract declares"), found


def test_client_referencing_an_undeclared_component_is_rejected() -> None:
    document, generated, smoke = _load()
    injected = generated + '\n"application/json": components["schemas"]["GhostResponse"];'
    assert _any(failures(document, injected, smoke),
                "does not declare in components.schemas")


def test_operation_without_a_success_response_is_rejected() -> None:
    document, generated, smoke = _load()
    path, method, _name = _first_operation(document)
    responses = document["paths"][path][method]["responses"]
    for code in [code for code in responses if code.startswith("2")]:
        del responses[code]
    assert _any(failures(document, generated, smoke), "declares no 2xx response")


def test_repinned_baseline_without_the_artifacts_is_rejected() -> None:
    """The gap this guard had: fix the counts, leave the artifacts behind.

    A regenerate that drifts both halves is caught by the baselines -- unless
    the same commit also re-pins them, at which point the guard would be
    comparing a baseline to itself. Reported as the artifact moving, not as a
    distribution mismatch, because the distribution was just made to agree.
    """
    document, generated, smoke = _load()
    saved = {
        name: globals()[name]
        for name in (
            "_RESPONSE_BODY_BASELINE",
            "_REQUEST_BODY_BASELINE",
            "_CLIENT_BODY_TOTAL",
            "_PINNED_ARTIFACTS",
        )
    }
    # Re-pin every count to whatever the current snapshot / client say -- what
    # a regenerate would do if it also "fixed" the red numbers.
    globals()["_RESPONSE_BODY_BASELINE"] = _response_bodies(document)
    globals()["_REQUEST_BODY_BASELINE"] = _request_bodies(document)
    globals()["_CLIENT_BODY_TOTAL"] = sum(_client_bodies(generated).values())
    # ...and say the numbers came from somewhere the artifacts no longer are.
    globals()["_PINNED_ARTIFACTS"] = {
        "snapshot_blob": "0" * 40,
        "generated_blob": "0" * 40,
    }
    try:
        found = failures(document, generated, smoke)
    finally:
        globals().update(saved)
    # The distribution checks are all green now; only the artifact pin speaks.
    assert not _any(found, "_RESPONSE_BODY_BASELINE"), found
    assert not _any(found, "_REQUEST_BODY_BASELINE"), found
    assert not _any(found, "pinned contract declares"), found
    assert _any(found, "_PINNED_ARTIFACTS"), found


def test_a_repin_that_matches_the_artifacts_passes() -> None:
    """The pin must be satisfiable: it tracks the bytes, not one frozen pair.

    A deliberate contract change re-pins the counts *and* both blob ids in the
    same commit. This proves the second half is enough -- the check is not a
    tripwire on any regenerate, only on one that skips the record.
    """
    document, generated, smoke = _load()
    saved = {
        name: globals()[name]
        for name in (
            "_RESPONSE_BODY_BASELINE",
            "_REQUEST_BODY_BASELINE",
            "_CLIENT_BODY_TOTAL",
            "_PINNED_ARTIFACTS",
        )
    }
    globals()["_RESPONSE_BODY_BASELINE"] = _response_bodies(document)
    globals()["_REQUEST_BODY_BASELINE"] = _request_bodies(document)
    globals()["_CLIENT_BODY_TOTAL"] = sum(_client_bodies(generated).values())
    globals()["_PINNED_ARTIFACTS"] = {
        "snapshot_blob": _git_blob(SNAPSHOT),
        "generated_blob": _git_blob(GENERATED),
    }
    try:
        found = failures(document, generated, smoke)
    finally:
        globals().update(saved)
    assert found == [], found


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, smoke = _load()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "", 1)
    assert unwired != smoke
    assert _any(failures(document, generated, unwired), "body-integrity guard")


_SUCCESS_LINE = "openapi-snapshot-bodies: OK"


def _run() -> int:
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
            problems.append(f"{test.__name__}: {describe_assertion(exc, test)}")
    if problems:
        for problem in problems:
            print(f"openapi-snapshot-bodies: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"{_SUCCESS_LINE} ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
