"""W1 ablation experiments: identity / public-boundary invariants.

Scratch (not committed) ablation suite for workstream W1. Each test runs the
REAL production code path twice:

* 对照 (control): real route/service/dependency chain, no production edits.
* 消融 (ablation): exactly ONE protective factor is neutralised via
  ``monkeypatch`` and the observable behaviour is re-measured.

A test PASSES only when it has demonstrated the expected flip while asserting
the control observation too. Where the ablation is an inline predicate with no
named helper, the endpoint/method is re-expressed with that single condition
removed; the reference copy is always called out in the print tag.

Anchor tests (apps/api/tests):
- test_mutants.py::test_public_responses_carry_public_id_only            (ID-01)
- test_mutants.py::test_internal_persistence_key_is_not_a_public_locator (ID-02)
- test_search_contract.py::test_internal_search_sets_private_no_store_header (ID-03)
- test_search_internal_http.py::test_internal_search_anonymous_error_is_private_no_store
- test_search_internal_http.py::test_internal_search_privileged_error_is_private_no_store
- test_search_database_integration.py::test_internal_search_returns_both_identities_and_matched_field (ID-04)
- test_mutants.py::test_non_public_mutant_line_is_not_disclosed          (neg)
- test_mutants.py::test_public_routes_exclude_draft_and_unreleased_records (neg)
- test_mutants.py::test_public_mutant_routes_fail_closed_without_active_release (neg)
- test_mutants.py::test_missing_public_id_records_fail_closed            (neg)
- test_search_database_integration.py::test_external_mutant_search_uses_public_id_only
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders

from app.api.v1 import deps as deps_module
from app.api.v1 import mutants as mutants_module
from app.core.database import get_db
from app.core.security import RoleName, create_access_token
from app.core.site_variant import SiteVariant
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.variant import MutantLine, Phenotype, VariantSummary
from app.schemas.search import (
    MatchType,
    SearchHit,
    SearchResultType,
)
from app.schemas.variant import MutantLineResponse
from app.services import search_service
from app.services.release_context import ReleaseContext, get_release_context
from app.services.search_service import SearchService

MUTANTS = "/api/v1/mutants"
INTERNAL_SEARCH = "/api/v1/search/internal"


def _emit(tag: str, **kw: Any) -> None:
    print(f"ABLATION-RESULT {tag} " + json.dumps(kw, default=str, sort_keys=True))


async def _published_release(db_session, slug: str = "abl-id") -> Release:
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return release


def _collect_routes(routes, prefix: str = ""):
    collected = []
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            context = route.include_context
            collected.extend(
                _collect_routes(
                    route.original_router.routes, prefix + (context.prefix or "")
                )
            )
        else:
            collected.append((prefix + (getattr(route, "path", "") or ""), route))
    return collected


def _route(app, path: str, method: str):
    for full_path, route in _collect_routes(app.routes):
        if full_path == path and method in (getattr(route, "methods", None) or set()):
            return route
    raise AssertionError(f"route {method} {path} not found")


def _invalidate_effective_contexts(app) -> None:
    """Force FastAPI 0.137 to rebuild its cached _EffectiveRouteContext."""
    for route in app.routes:
        if type(route).__name__ == "_IncludedRouter":
            route._effective_candidates = []
            route._effective_candidates_version = None


def _replace_endpoint(app, monkeypatch, path: str, method: str, fn):
    """Swap the endpoint of the shared APIRoute (FastAPI rebuilds its views)."""
    route = _route(app, path, method)
    monkeypatch.setattr(route, "endpoint", fn)
    monkeypatch.setattr(route.dependant, "call", fn)
    _invalidate_effective_contexts(app)
    return route


def _find_dep(dependant, name: str):
    for dep in dependant.dependencies:
        if getattr(dep.call, "__name__", "") == name:
            return dep
        found = _find_dep(dep, name)
        if found is not None:
            return found
    return None


class _LeakyMutantLineResponse(MutantLineResponse):
    internal_id: str = ""


# --------------------------------------------------------------------------- ID-01
@pytest.mark.asyncio
async def test_abl_id01_public_http_projection_hides_internal_key(
    client, db_session, app, monkeypatch
):
    """ID-01: the public list schema must not carry the persistence key.

    Ablation: ``_to_response`` echoes ``ml.id`` as ``internal_id`` and the
    endpoint returns a raw JSONResponse so the extra field survives.
    """
    release = await _published_release(db_session, "abl-id01")
    line = MutantLine(name="dual-id", public_id="SMDATA001", release_id=release.id)
    db_session.add(line)
    await db_session.commit()

    control = await client.get(MUTANTS)
    [item] = control.json()
    _emit(
        "ID-01.control",
        status=control.status_code,
        item=sorted(item),
        has_internal_id='"internal_id"' in control.text,
    )
    assert control.status_code == 200
    assert item["public_id"] == "SMDATA001"
    assert "id" not in item and "internal_id" not in item
    assert f'"{line.id}"' not in control.text

    async def leaky_list(
        db: AsyncSession = Depends(get_db),
        release_context: ReleaseContext = Depends(get_release_context),
        mutagen: str | None = None,
        limit: int = 50,
    ):
        variant_count = func.count(VariantSummary.id).label("variant_count")
        stmt = (
            select(MutantLine, variant_count)
            .outerjoin(VariantSummary, VariantSummary.mutant_line_id == MutantLine.id)
            .where(*mutants_module._visible_public_conditions(release_context.release_id))
            .group_by(MutantLine.id)
        )
        rows = (await db.execute(stmt)).all()
        payload = [
            {
                "public_id": ml.public_id,
                "name": ml.name,
                "internal_id": str(ml.id),  # <-- the ablated projection
                "variant_count": count,
            }
            for ml, count in rows
        ]
        return JSONResponse(content=payload)

    _replace_endpoint(app, monkeypatch, MUTANTS, "GET", leaky_list)
    ablated = await client.get(MUTANTS)
    [ablated_item] = ablated.json()
    _emit(
        "ID-01.ablation_expose_persistence_key",
        status=ablated.status_code,
        item=sorted(ablated_item),
        has_internal_id='"internal_id"' in ablated.text,
        leaked_id=str(line.id) in ablated.text,
    )
    assert ablated.status_code == 200
    assert ablated_item.get("internal_id") == str(line.id)
    assert f'"{line.id}"' in ablated.text


@pytest.mark.asyncio
async def test_abl_id01_search_projection_hides_internal_key(db_session, monkeypatch):
    """ID-01 (search surface): external hits must not echo the persistence key."""
    release = await _published_release(db_session, "abl-id01s")
    line = MutantLine(name="lab-1", public_id="SMPUB00001", release_id=release.id)
    db_session.add(line)
    await db_session.commit()

    service = SearchService()
    control = await service.global_search(
        db_session, "SMPUB00001", types=[SearchResultType.MUTANT_LINE]
    )
    _emit(
        "ID-01s.control",
        ids=[h.id for h in control.results],
        has_internal_id='"internal_id"' in control.model_dump_json(),
    )
    assert [h.id for h in control.results] == ["SMPUB00001"]
    assert '"internal_id"' not in control.model_dump_json()

    original = SearchService._search_mutant_lines

    async def leaky_projection(
        self, db, query, pattern, limit, offset=0, *, cursor_key=None,
        release_id, site_variant,
    ):
        hits = await original(
            self, db, query, pattern, limit, offset,
            cursor_key=cursor_key, release_id=release_id, site_variant=site_variant,
        )
        if site_variant == SiteVariant.EXTERNAL and hits:
            rows = (
                await db.execute(
                    select(MutantLine.public_id, MutantLine.id).where(
                        MutantLine.public_id.in_([h.id for h in hits])
                    )
                )
            ).all()
            by_public = {public_id: internal for public_id, internal in rows}
            for hit in hits:
                # <-- the public hit is re-keyed to the persistence key
                hit.id = str(by_public.get(hit.id, ""))
        return hits

    monkeypatch.setattr(SearchService, "_search_mutant_lines", leaky_projection)
    ablated = await service.global_search(
        db_session, "SMPUB00001", types=[SearchResultType.MUTANT_LINE]
    )
    _emit(
        "ID-01s.ablation_expose_persistence_key",
        ids=[h.id for h in ablated.results],
        leaked=str(line.id) in [h.id for h in ablated.results],
    )
    assert [h.id for h in ablated.results] == [str(line.id)]
    assert all(h.id != "SMPUB00001" for h in ablated.results)


# --------------------------------------------------------------------------- ID-02
@pytest.mark.asyncio
async def test_abl_id02_internal_key_is_not_a_public_locator(
    client, db_session, app, monkeypatch
):
    """ID-02: an existing internal id yields the same 404 as an unknown token."""
    release = await _published_release(db_session, "abl-id02")
    line = MutantLine(name="hidden-key", public_id="SMHIDDEN01", release_id=release.id)
    db_session.add(line)
    await db_session.commit()

    control = await client.get(f"{MUTANTS}/{line.id}")
    _emit(
        "ID-02.control",
        status=control.status_code,
        code=control.json().get("error", {}).get("code"),
        public_id_of_row=line.public_id,
    )
    assert control.status_code == 404
    assert control.json()["error"]["code"] == "not_found"

    original = mutants_module.get_mutant_line

    async def ablated_detail(
        public_id: str,
        db: AsyncSession = Depends(get_db),
        release_context: ReleaseContext = Depends(get_release_context),
    ):
        token = public_id.strip()
        if token.isdigit():
            variant_count = func.count(VariantSummary.id).label("variant_count")
            row = (
                await db.execute(
                    select(MutantLine, variant_count)
                    .outerjoin(
                        VariantSummary, VariantSummary.mutant_line_id == MutantLine.id
                    )
                    .where(
                        MutantLine.id == int(token),
                        *mutants_module._visible_public_conditions(
                            release_context.release_id
                        ),
                    )
                    .group_by(MutantLine.id)
                )
            ).one_or_none()
            if row is not None:
                return mutants_module._to_detail(row[0], row[1])
        return await original(public_id, db, release_context)

    _replace_endpoint(app, monkeypatch, f"{MUTANTS}/{{public_id}}", "GET", ablated_detail)
    ablated = await client.get(f"{MUTANTS}/{line.id}")
    _emit(
        "ID-02.ablation_internal_key_becomes_locator",
        status=ablated.status_code,
        public_id=ablated.json().get("public_id"),
    )
    assert ablated.status_code == 200
    assert ablated.json()["public_id"] == "SMHIDDEN01"

    # And unknown integers still 404, so the ablated oracle is still bounded.
    missing = await client.get(f"{MUTANTS}/999999")
    assert missing.status_code == 404


# --------------------------------------------------------------------------- ID-03
async def _make_user(db_session, role_name: str, username: str) -> User:
    role = (
        await db_session.execute(select(Role).where(Role.name == role_name))
    ).scalar_one()
    user = User(
        username=username,
        email=f"{username}@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_abl_id03_internal_role_gate_is_load_bearing(
    client, db_session, app, monkeypatch
):
    """ID-03: an authenticated but under-privileged caller is refused (403)."""
    release = await _published_release(db_session, "abl-id03")
    db_session.add(
        MutantLine(name="http-lab-1", public_id="SMHTTP001", release_id=release.id)
    )
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "abl-res")
    viewer = await _make_user(db_session, RoleName.VIEWER.value, "abl-view")
    await db_session.commit()

    anon = await client.get(INTERNAL_SEARCH, params={"query": "SMHTTP001"})
    viewer_resp = await client.get(
        INTERNAL_SEARCH,
        params={"query": "SMHTTP001"},
        headers={"Authorization": f"Bearer {create_access_token(subject=str(viewer.id))}"},
    )
    res_resp = await client.get(
        INTERNAL_SEARCH,
        params={"query": "SMHTTP001"},
        headers={
            "Authorization": f"Bearer {create_access_token(subject=str(researcher.id))}"
        },
    )
    _emit(
        "ID-03.control",
        anonymous=anon.status_code,
        viewer=viewer_resp.status_code,
        researcher=res_resp.status_code,
        header=res_resp.headers.get("Cache-Control"),
    )
    assert anon.status_code == 401
    assert viewer_resp.status_code == 403
    assert res_resp.status_code == 200
    assert res_resp.headers.get("Cache-Control") == "private, no-store"

    monkeypatch.setattr(
        deps_module, "has_role", lambda roles, required: True  # <-- gate dropped
    )
    ablated_viewer = await client.get(
        INTERNAL_SEARCH,
        params={"query": "SMHTTP001"},
        headers={"Authorization": f"Bearer {create_access_token(subject=str(viewer.id))}"},
    )
    _emit(
        "ID-03.ablation_drop_role_gate",
        viewer=ablated_viewer.status_code,
        data=ablated_viewer.json().get("total_count"),
    )
    assert ablated_viewer.status_code == 200
    assert ablated_viewer.json()["total_count"] == 1


@pytest.mark.asyncio
async def test_abl_id03_cache_control_is_load_bearing(
    client, db_session, monkeypatch
):
    """ID-03: the private,no-store assignment must actually reach the wire."""
    release = await _published_release(db_session, "abl-id03c")
    db_session.add(
        MutantLine(name="http-lab-c", public_id="SMHTTP002", release_id=release.id)
    )
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "abl-res-c")
    await db_session.commit()

    headers = {
        "Authorization": f"Bearer {create_access_token(subject=str(researcher.id))}"
    }
    control = await client.get(INTERNAL_SEARCH, params={"query": "SMHTTP002"}, headers=headers)
    _emit("ID-03c.control", header=control.headers.get("Cache-Control"))
    assert control.status_code == 200
    assert control.headers.get("Cache-Control") == "private, no-store"

    original = MutableHeaders.__setitem__

    def drop_cache_control(self, key, value):
        if key.lower() != "cache-control":  # <-- the assignment becomes a no-op
            original(self, key, value)

    monkeypatch.setattr(MutableHeaders, "__setitem__", drop_cache_control)
    ablated = await client.get(
        INTERNAL_SEARCH, params={"query": "SMHTTP002"}, headers=headers
    )
    _emit("ID-03c.ablation_drop_cache_control", header=ablated.headers.get("Cache-Control"))
    assert ablated.status_code == 200
    assert ablated.headers.get("Cache-Control") is None


# --------------------------------------------------------------------------- ID-04
@pytest.mark.asyncio
async def test_abl_id04_matched_field_annotation_is_load_bearing(
    client, db_session, monkeypatch
):
    """ID-04: internal lookup must report *which* identity matched."""
    release = await _published_release(db_session, "abl-id04")
    line = MutantLine(name="lab-2", public_id="SMPUB00002", release_id=release.id)
    db_session.add(line)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "abl-res-04")
    await db_session.commit()
    auth = {
        "Authorization": f"Bearer {create_access_token(subject=str(researcher.id))}"
    }

    by_public = await client.get(
        INTERNAL_SEARCH, params={"query": "SMPUB00002"}, headers=auth
    )
    by_internal = await client.get(
        INTERNAL_SEARCH, params={"query": str(line.id)}, headers=auth
    )
    control = by_internal.json()["mutants"][0]
    _emit(
        "ID-04.control",
        by_public_field=by_public.json()["mutants"][0]["matched_field"],
        by_internal_field=control["matched_field"],
        by_internal_public_id=control["public_id"],
        by_internal_type=control["match_type"],
    )
    assert by_public.json()["mutants"][0]["matched_field"] == "public_id"
    assert control["matched_field"] == "internal_id"
    assert control["public_id"] == "SMPUB00002"
    assert control["internal_id"] == str(line.id)
    assert control["match_type"] == MatchType.EXACT.value

    original = SearchService._internal_search_mutants

    async def drop_annotation(self, db, query, pattern, *, release_id, limit):
        items = await original(
            self, db, query, pattern, release_id=release_id, limit=limit
        )
        for item in items:
            if item.matched_field == "internal_id":
                item.matched_field = "name"  # <-- annotation dropped
        return items

    monkeypatch.setattr(SearchService, "_internal_search_mutants", drop_annotation)
    ablated = await client.get(
        INTERNAL_SEARCH, params={"query": str(line.id)}, headers=auth
    )
    ablated_item = ablated.json()["mutants"][0]
    _emit(
        "ID-04.ablation_drop_matched_field",
        by_internal_field=ablated_item["matched_field"],
        row_found=ablated_item["public_id"],
    )
    assert ablated_item["matched_field"] == "name"
    assert ablated_item["public_id"] == "SMPUB00002"


@pytest.mark.asyncio
async def test_abl_id04_internal_id_sql_branch_is_load_bearing(
    client, db_session, monkeypatch
):
    """ID-04: the dedicated internal-id SQL branch must actually match rows."""
    release = await _published_release(db_session, "abl-id04b")
    line = MutantLine(name="lab-3", public_id="SMPUB00003", release_id=release.id)
    db_session.add(line)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "abl-res-04b")
    await db_session.commit()
    auth = {
        "Authorization": f"Bearer {create_access_token(subject=str(researcher.id))}"
    }

    control = await client.get(
        INTERNAL_SEARCH, params={"query": str(line.id)}, headers=auth
    )
    _emit(
        "ID-04b.control",
        mutants=[m["public_id"] for m in control.json()["mutants"]],
        matched_field=control.json()["mutants"][0]["matched_field"],
    )
    assert [m["public_id"] for m in control.json()["mutants"]] == ["SMPUB00003"]

    original = SearchService._internal_search_mutants

    async def drop_sql_branch(self, db, query, pattern, *, release_id, limit):
        items = await original(
            self, db, query, pattern, release_id=release_id, limit=limit
        )
        # the only rows whose matched_field is internal_id came from that branch
        return [item for item in items if item.matched_field != "internal_id"]

    monkeypatch.setattr(SearchService, "_internal_search_mutants", drop_sql_branch)
    ablated = await client.get(
        INTERNAL_SEARCH, params={"query": str(line.id)}, headers=auth
    )
    _emit(
        "ID-04b.ablation_drop_internal_id_sql_branch",
        mutants=[m["public_id"] for m in ablated.json()["mutants"]],
    )
    assert ablated.json()["mutants"] == []


# --------------------------------------------------------------------------- negatives
def _drop_condition(original, release_id, needle: str):
    return tuple(c for c in original(release_id) if needle not in str(c))


@pytest.mark.asyncio
async def test_abl_neg_embargoed_row_leaks_when_is_public_predicate_dropped(
    client, db_session, monkeypatch
):
    release = await _published_release(db_session, "abl-neg-emb")
    db_session.add_all(
        [
            MutantLine(name="public-line", public_id="SMOPEN001", release_id=release.id),
            MutantLine(
                name="embargoed-line",
                public_id="SMEMBRG01",
                is_public=False,
                release_id=release.id,
            ),
        ]
    )
    await db_session.commit()

    control = await client.get(MUTANTS)
    _emit(
        "NEG-EMB.control",
        names=[line["name"] for line in control.json()],
        embargoed_detail=(await client.get(f"{MUTANTS}/SMEMBRG01")).status_code,
    )
    assert [line["name"] for line in control.json()] == ["public-line"]
    assert (await client.get(f"{MUTANTS}/SMEMBRG01")).status_code == 404

    original = mutants_module._visible_public_conditions
    monkeypatch.setattr(
        mutants_module,
        "_visible_public_conditions",
        lambda release_id: _drop_condition(original, release_id, "is_public"),
    )
    ablated = await client.get(MUTANTS)
    _emit(
        "NEG-EMB.ablation_drop_is_public",
        names=sorted(line["name"] for line in ablated.json()),
        embargoed_detail=(await client.get(f"{MUTANTS}/SMEMBRG01")).status_code,
    )
    assert "embargoed-line" in [line["name"] for line in ablated.json()]
    assert (await client.get(f"{MUTANTS}/SMEMBRG01")).status_code == 200
    assert original is not None


@pytest.mark.asyncio
async def test_abl_neg_draft_and_unreleased_leak_when_release_predicate_dropped(
    client, db_session, monkeypatch
):
    published = await _published_release(db_session, "abl-neg-rel")
    draft = Release(version="draft-rel", name="draft", status=ReleaseStatus.DRAFT)
    inactive = Release(
        version="inactive-rel", name="inactive", status=ReleaseStatus.PUBLISHED
    )
    db_session.add_all([draft, inactive])
    await db_session.flush()
    db_session.add_all(
        [
            MutantLine(name="visible", public_id="SMVISIBLE1", release_id=published.id),
            MutantLine(name="draft", public_id="SMDRAFT001", release_id=draft.id),
            MutantLine(name="inactive", public_id="SMINACTIV1", release_id=inactive.id),
            MutantLine(name="null-release", public_id="SMNULLREL1"),
        ]
    )
    await db_session.commit()

    control = await client.get(MUTANTS)
    _emit("NEG-REL.control", names=[line["name"] for line in control.json()])
    assert [line["name"] for line in control.json()] == ["visible"]

    original2 = mutants_module._visible_public_conditions

    monkeypatch.setattr(
        mutants_module,
        "_visible_public_conditions",
        lambda release_id: _drop_condition(original2, release_id, "release_id"),
    )
    ablated = await client.get(MUTANTS)
    _emit(
        "NEG-REL.ablation_drop_release_scope",
        names=sorted(line["name"] for line in ablated.json()),
    )
    assert sorted(line["name"] for line in ablated.json()) == [
        "draft",
        "inactive",
        "null-release",
        "visible",
    ]


@pytest.mark.asyncio
async def test_abl_neg_missing_public_id_leaks_when_predicate_dropped(
    client, db_session, monkeypatch
):
    release = await _published_release(db_session, "abl-neg-pid")
    db_session.add(
        MutantLine(name="no-public-id", public_id=None, release_id=release.id)
    )
    await db_session.commit()

    control = await client.get(MUTANTS)
    _emit("NEG-PID.control", body=control.json())
    assert control.json() == []

    original3 = mutants_module._visible_public_conditions

    monkeypatch.setattr(
        mutants_module,
        "_visible_public_conditions",
        lambda release_id: _drop_condition(original3, release_id, "public_id"),
    )
    ablated = await client.get(MUTANTS)
    _emit(
        "NEG-PID.ablation_drop_public_id_predicate",
        names=[line["name"] for line in ablated.json()],
        public_id=ablated.json()[0]["public_id"],
    )
    assert [line["name"] for line in ablated.json()] == ["no-public-id"]
    assert ablated.json()[0]["public_id"] == ""


@pytest.mark.asyncio
async def test_abl_neg_no_active_release_fails_closed(client, db_session, app):
    db_session.add(MutantLine(name="orphan", public_id="SMORPHAN01"))
    await db_session.commit()

    control = await client.get(MUTANTS)
    _emit("NEG-NORELEASE.control", status=control.status_code)
    assert control.status_code == 503

    app.dependency_overrides[get_release_context] = lambda: ReleaseContext(
        release_id=999
    )
    ablated = await client.get(MUTANTS)
    _emit(
        "NEG-NORELEASE.ablation_drop_fail_closed",
        status=ablated.status_code,
        body=ablated.json(),
    )
    assert ablated.status_code == 200
    assert ablated.json() == []


@pytest.mark.asyncio
async def test_abl_neg_unpublished_leaks_into_external_search_when_is_public_dropped(
    db_session, monkeypatch
):
    """Search surface: the external ``is_public`` predicate must exclude rows."""
    release = await _published_release(db_session, "abl-neg-search")
    published = MutantLine(name="lab-1", public_id="SMPUB00001", release_id=release.id)
    embargoed = MutantLine(
        name="lab-secret", public_id="SMSECRET01", is_public=False, release_id=release.id
    )
    db_session.add_all([published, embargoed])
    await db_session.commit()

    service = SearchService()
    control = await service.global_search(
        db_session, "SMSECRET01", types=[SearchResultType.MUTANT_LINE]
    )
    _emit("NEG-SEARCH.control", ids=[h.id for h in control.results])
    assert control.results == []

    original = SearchService._search_mutant_lines

    async def drop_is_public(
        self, db, query, pattern, limit, offset=0, *, cursor_key=None,
        release_id, site_variant,
    ):
        if site_variant == SiteVariant.EXTERNAL:
            conditions = [
                # MutantLine.is_public removed
                MutantLine.is_deleted.is_(False),
                MutantLine.public_id.is_not(None),
                MutantLine.release_id == release_id,
                MutantLine.public_id.ilike(pattern, escape="\\"),
            ]
            stmt = select(MutantLine).where(search_service.and_(*conditions))
            rows = (await db.execute(stmt)).scalars().all()
            return [
                SearchHit(
                    id=ml.public_id or "",
                    type=SearchResultType.MUTANT_LINE,
                    title=ml.public_id or "",
                    subtitle=ml.description,
                    score=1.0,
                    url=f"/api/v1/mutants/{ml.public_id}",
                    match_type=MatchType.TEXT,
                    metadata={
                        "_cursor": {"rank": 1, "score": 1.0, "public_id": ml.public_id}
                    },
                )
                for ml in rows
            ]
        return await original(
            self, db, query, pattern, limit, offset,
            cursor_key=cursor_key, release_id=release_id, site_variant=site_variant,
        )

    monkeypatch.setattr(SearchService, "_search_mutant_lines", drop_is_public)
    ablated = await service.global_search(
        db_session, "SMSECRET01", types=[SearchResultType.MUTANT_LINE]
    )
    _emit("NEG-SEARCH.ablation_drop_is_public", ids=[h.id for h in ablated.results])
    assert [h.id for h in ablated.results] == ["SMSECRET01"]


# --------------------------------------------------------------------------- INERT probe
@pytest.mark.asyncio
async def test_inert_external_search_public_id_not_null_predicate_is_redundant(
    db_session, monkeypatch
):
    """INERT probe: ``public_id IS NOT NULL`` is redundant in the external SQL.

    A NULL ``public_id`` cannot satisfy ``public_id ILIKE <pattern>``, so
    dropping the NOT NULL predicate cannot change the result set. The probe
    asserts an *unchanged* observation (a null-public_id row stays absent).
    """
    release = await _published_release(db_session, "inert-pid")
    db_session.add(
        MutantLine(name="no-public-id", public_id=None, release_id=release.id)
    )
    db_session.add(
        MutantLine(name="yes-public-id", public_id="SMLAB00009", release_id=release.id)
    )
    await db_session.commit()

    service = SearchService()
    control = await service.global_search(
        db_session, "SMLAB", types=[SearchResultType.MUTANT_LINE]
    )
    _emit("INERT-PID.control", ids=[h.id for h in control.results])
    assert [h.id for h in control.results] == ["SMLAB00009"]

    original = SearchService._search_mutant_lines

    async def drop_not_null(
        self, db, query, pattern, limit, offset=0, *, cursor_key=None,
        release_id, site_variant,
    ):
        if site_variant == SiteVariant.EXTERNAL:
            conditions = [
                MutantLine.is_public.is_(True),
                MutantLine.is_deleted.is_(False),
                # MutantLine.public_id.is_not(None) removed
                MutantLine.release_id == release_id,
                MutantLine.public_id.ilike(pattern, escape="\\"),
            ]
            stmt = select(MutantLine).where(search_service.and_(*conditions))
            rows = (await db.execute(stmt)).scalars().all()
            return [
                SearchHit(
                    id=ml.public_id or "",
                    type=SearchResultType.MUTANT_LINE,
                    title=ml.public_id or "",
                    subtitle=ml.description,
                    score=1.0,
                    url=f"/api/v1/mutants/{ml.public_id}",
                    match_type=MatchType.TEXT,
                    metadata={
                        "_cursor": {"rank": 1, "score": 1.0, "public_id": ml.public_id}
                    },
                )
                for ml in rows
            ]
        return await original(
            self, db, query, pattern, limit, offset,
            cursor_key=cursor_key, release_id=release_id, site_variant=site_variant,
        )

    monkeypatch.setattr(SearchService, "_search_mutant_lines", drop_not_null)
    ablated = await service.global_search(
        db_session, "SMLAB", types=[SearchResultType.MUTANT_LINE]
    )
    _emit("INERT-PID.ablation_drop_public_id_not_null", ids=[h.id for h in ablated.results])
    assert [h.id for h in ablated.results] == ["SMLAB00009"]
