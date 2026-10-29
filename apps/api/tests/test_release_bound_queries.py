"""Release-scoped gene/variant query contracts (pure unit tests)."""

from __future__ import annotations

import uuid
from importlib import import_module
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.schemas.genomic import GeneListParams
from app.schemas.popgen import AlleleFreqRequest
from app.schemas.variant import ExportRequest, VariantFilterParams
from app.services.clickhouse_service import ClickHouseService
from app.services.gene_service import GeneService
from app.services.popgen_service import PopGenService
from app.services.release_context import ReleaseContext
from app.services.variant_service import VariantService


def _context(release_id: int = 7):
    return ReleaseContext(
        release_id=release_id,
        assembly_id=3,
        assembly="Wm82.a4.v1",
    )


class _ScalarRows:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _PgResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._rows)

    def all(self) -> list[Any]:
        """Row-tuple access, mirroring SQLAlchemy's ``Result.all()``.

        Services that select ``(entity, aggregate)`` pairs read rows through
        this method, so the fake result must expose it or those queries look
        like a driver error instead of a test-double gap.
        """
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _SequenceDb:
    def __init__(self, *rows: Any):
        self._rows = list(rows)
        self.statements: list[Any] = []

    async def execute(self, statement):
        self.statements.append(statement)
        row = self._rows.pop(0) if self._rows else None
        return _PgResult([] if row is None else [row])


class _EmptyGeneDb:
    def __init__(self):
        self.last_stmt = None

    async def execute(self, statement):
        self.last_stmt = statement
        return _PgResult([])


class _ClickHouseResult:
    def __init__(
        self,
        *,
        columns: tuple[str, ...] = (),
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.column_names = columns
        self.result_rows = rows or []
        self.row_count = len(self.result_rows)
        self.first_row = self.result_rows[0] if self.result_rows else (0,)


class _CapturingClickHouse:
    def __init__(self, result: _ClickHouseResult | None = None) -> None:
        self.result = result or _ClickHouseResult()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query(self, query: str, parameters: dict[str, Any] | None = None):
        self.calls.append((query, parameters or {}))
        return self.result


def _clickhouse_service(client: _CapturingClickHouse) -> ClickHouseService:
    service = ClickHouseService()
    service._client = client  # noqa: SLF001 - injected unit-test client
    return service


@pytest.mark.asyncio
async def test_active_release_context_is_resolved_before_queries():
    release_context = import_module("app.services.release_context")
    release = SimpleNamespace(
        id=7,
        assembly_id=3,
        assembly="Wm82.a4.v1",
        status="published",
    )
    db = _SequenceDb(release)

    context = await release_context.resolve_release_context(db)

    assert context.release_id == 7
    assert context.release_key == "7"
    assert context.assembly_id == 3
    assert "active_release" in str(db.statements[0])


@pytest.mark.asyncio
async def test_explicit_published_release_context_is_resolved():
    release_context = import_module("app.services.release_context")
    release = SimpleNamespace(
        id=9,
        assembly_id=None,
        assembly=None,
        status="published",
    )
    db = _SequenceDb(release)

    context = await release_context.resolve_release_context(db, requested_release_id=9)

    assert context.release_id == 9
    sql = str(db.statements[0])
    assert "releases.id" in sql
    assert "releases.status" in sql


@pytest.mark.asyncio
async def test_missing_active_release_fails_closed():
    release_context = import_module("app.services.release_context")

    with pytest.raises(ServiceUnavailableError, match="active data release"):
        await release_context.resolve_release_context(_SequenceDb())


@pytest.mark.asyncio
async def test_unknown_explicit_release_is_not_found():
    release_context = import_module("app.services.release_context")

    with pytest.raises(NotFoundError, match="Release 404"):
        await release_context.resolve_release_context(_SequenceDb(), requested_release_id=404)


@pytest.mark.asyncio
async def test_release_dependency_accepts_static_page_header_pin():
    release_context = import_module("app.services.release_context")
    release = SimpleNamespace(
        id=9,
        assembly_id=None,
        assembly=None,
        status="published",
    )

    context = await release_context.get_release_context(
        db=_SequenceDb(release),
        release_id=None,
        pinned_release_id=9,
    )

    assert context.release_id == 9


@pytest.mark.asyncio
async def test_release_dependency_rejects_conflicting_query_and_header_pins():
    release_context = import_module("app.services.release_context")
    db = _SequenceDb()

    with pytest.raises(ValidationError, match="Conflicting release ids"):
        await release_context.get_release_context(
            db=db,
            release_id=7,
            pinned_release_id=8,
        )

    assert db.statements == []


@pytest.mark.asyncio
async def test_gene_list_storage_query_is_always_release_scoped():
    db = _EmptyGeneDb()

    await GeneService().list_genes(
        db,
        GeneListParams(chromosome="Gm01", limit=20),
        release_context=_context(),
    )

    sql = str(db.last_stmt)
    assert "assemblies.release_id" in sql
    assert "chromosomes.name" in sql


@pytest.mark.asyncio
async def test_gene_detail_storage_query_is_always_release_scoped():
    db = _SequenceDb()

    with pytest.raises(NotFoundError):
        await GeneService().get_gene(
            db,
            "Glyma.01G000100",
            release_context=_context(),
        )

    sql = str(db.statements[0])
    assert "assemblies.release_id" in sql


class _CapturingRegionStore:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def query_variants_by_region(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.kwargs = kwargs
        return []


@pytest.mark.asyncio
async def test_popgen_region_query_propagates_release_context():
    store = _CapturingRegionStore()
    context = _context()
    service = PopGenService(variant_service=store)

    await service.allele_frequencies(
        _EmptyGeneDb(),
        AlleleFreqRequest(
            assembly="Wm82.a4.v1",
            chromosome="Gm01",
            start=1,
            end=10,
        ),
        release_context=context,
    )

    assert store.kwargs is not None
    assert store.kwargs["release_context"] == context


@pytest.mark.asyncio
async def test_variant_sql_binds_release_filters_and_boundary_cursor():
    client = _CapturingClickHouse()
    service = _clickhouse_service(client)
    params = VariantFilterParams(
        assembly="Wm82.a4.v1",
        chromosome="Gm01' OR 1=1 --",
        start=0,
        end=100,
        ref="A",
        alt="T",
        consequence="missense_variant",
    )

    await service.query_variants(
        params=params,
        release_context=_context(),
        limit=25,
        cursor_key=(0, 41),
    )

    sql, bound = client.calls[0]
    assert "release_key = %(release_key)s" in sql
    assert "assembly_key = %(assembly)s" in sql
    assert "chromosome = %(chromosome)s" in sql
    assert "ref_allele = %(ref)s" in sql
    assert "alt_allele = %(alt)s" in sql
    assert "consequence = %(consequence)s" in sql
    assert "position > %(cursor_pos)s" in sql
    assert "position = %(cursor_pos)s AND variant_id > %(cursor_variant_id)s" in sql
    assert "ORDER BY position ASC, variant_id ASC" in " ".join(sql.split())
    assert "Gm01' OR 1=1 --" not in sql
    assert bound == {
        "release_key": "7",
        "assembly": "Wm82.a4.v1",
        "chromosome": "Gm01' OR 1=1 --",
        "start": 0,
        "end": 100,
        "ref": "A",
        "alt": "T",
        "consequence": "missense_variant",
        "cursor_pos": 0,
        "cursor_variant_id": 41,
        "lim": 25,
    }


@pytest.mark.asyncio
async def test_variant_region_detail_and_count_sql_are_release_scoped():
    count_result = _ClickHouseResult(columns=("total",), rows=[(0,)])
    client = _CapturingClickHouse(count_result)
    service = _clickhouse_service(client)
    context = _context()

    await service.query_variants_by_region(
        release_context=context,
        assembly="Wm82.a4.v1",
        chromosome="Gm01",
        start=0,
        end=0,
        max_results=1,
    )
    await service.get_variant_by_id("41", release_context=context)
    await service.count_variants(VariantFilterParams(), release_context=context)

    assert len(client.calls) == 3
    for sql, bound in client.calls:
        assert "release_key = %(release_key)s" in sql
        assert bound["release_key"] == "7"


@pytest.mark.asyncio
async def test_region_query_without_release_context_fails_before_clickhouse():
    client = _CapturingClickHouse()
    service = _clickhouse_service(client)

    with pytest.raises(ServiceUnavailableError, match="Release context"):
        await service.query_variants_by_region(
            assembly="Wm82.a4.v1",
            chromosome="Gm01",
            start=0,
            end=1,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_variant_export_writes_durable_event_pinned_to_release():
    variants_route = import_module("app.api.v1.variants")

    class _Db:
        def __init__(self):
            self.commits = 0
            self.added = []

        async def flush(self):
            pass

        def add(self, event):
            self.added.append(event)
            self.event = event

        async def commit(self):
            self.commits += 1

        async def execute(self, *args, **kwargs):
            # The route asks the release's own facts whether the resolved
            # namespace exists before it queues anything: an export of a
            # namespace the release does not publish is refused instead of
            # producing an empty artifact.
            class _Result:
                def first(self):
                    return (1,)

            return _Result()

    db = _Db()
    with patch.object(variants_route, "dispatch_task", create=True) as dispatch:
        response = await variants_route.export_variants(
            ExportRequest(filters={"chromosome": "Gm01"}),
            db=db,
            release_context=_context(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status == "pending"
    assert db.commits == 1
    assert dispatch.call_count == 0
    assert db.event.aggregate_type == "variant_export"
    assert db.event.aggregate_id == response.export_id
    assert db.event.event_type == "variant_export_requested"
    assert db.event.payload == {
        "task_name": variants_route.EXPORT_VARIANTS_TASK,
        "kwargs": {
            "export_id": response.export_id,
            # The release's assembly scope is written into the command's
            # filters: the worker constrains its SQL by this key, so the
            # artifact cannot span assembly namespaces.
            "filters": {
                "chromosome": "Gm01",
                "release_key": "7",
                "assembly": "Wm82.a4.v1",
            },
            "format": "tsv",
            "compress": True,
        },
    }
    # The durable export record is written in the same transaction as the
    # command event, so a committed request always has both.
    record = next(item for item in db.added if item.__class__.__name__ == "VariantExport")
    assert str(record.id) == response.export_id
    assert record.release_key == "7"
    assert record.assembly_key == "Wm82.a4.v1"
    # The record and the command state the same namespace.
    assert record.assembly_key == record.filters["assembly"]
    assert record.status.value == "pending"


class _InMemoryVariantStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = sorted(rows, key=lambda row: (row["position"], row["variant_id"]))
        self.cursor_keys: list[tuple[int, int] | None] = []

    async def query_variants(
        self,
        *,
        params,
        release_context,
        limit: int,
        cursor_key: tuple[int, int] | None,
    ) -> list[dict[str, Any]]:
        del params, release_context
        self.cursor_keys.append(cursor_key)
        rows = self.rows
        if cursor_key is not None:
            rows = [row for row in rows if (row["position"], row["variant_id"]) > cursor_key]
        return rows[:limit]


def _variant(variant_id: int, position: int) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "chromosome": "Gm01",
        "position": position,
        "ref_allele": "A",
        "alt_allele": "T",
        "variant_type": "SNP",
    }


@pytest.mark.asyncio
async def test_same_position_variants_paginate_without_skip_or_duplicate():
    store = _InMemoryVariantStore(
        [_variant(41, 0), _variant(42, 0), _variant(43, 0), _variant(44, 1)]
    )
    service = VariantService(variant_service=store)
    context = _context()

    first = await service.list_variants(
        None,
        VariantFilterParams(limit=2),
        release_context=context,
    )
    second = await service.list_variants(
        None,
        VariantFilterParams(limit=2, cursor=first.next_cursor),
        release_context=context,
    )

    assert [item.variant_id for item in first.items] == ["41", "42"]
    assert [item.variant_id for item in second.items] == ["43", "44"]
    assert store.cursor_keys == [None, (0, 42)]


def test_variant_cursor_rejects_cross_release_filter_replay_and_tampering():
    variant_service = import_module("app.services.variant_service")
    release_context = import_module("app.services.release_context")
    context = release_context.ReleaseContext(
        release_id=7,
        assembly_id=3,
        assembly="Wm82.a4.v1",
    )
    params = VariantFilterParams(chromosome="Gm01")
    cursor = variant_service.encode_cursor(
        100,
        41,
        release_context=context,
        params=params,
    )

    assert variant_service.decode_cursor(
        cursor,
        release_context=context,
        params=params,
    ) == (100, 41)
    with pytest.raises(ValidationError, match="context"):
        variant_service.decode_cursor(
            cursor,
            release_context=release_context.ReleaseContext(release_id=8),
            params=params,
        )
    with pytest.raises(ValidationError, match="context"):
        variant_service.decode_cursor(
            cursor,
            release_context=context,
            params=VariantFilterParams(chromosome="Gm02"),
        )

    payload, signature = cursor.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{payload}.{replacement}{signature[1:]}"
    with pytest.raises(ValidationError, match="signature"):
        variant_service.decode_cursor(
            tampered,
            release_context=context,
            params=params,
        )
    with pytest.raises(ValidationError, match="encoding"):
        variant_service.decode_cursor(
            "💣.AAAA",
            release_context=context,
            params=params,
        )


def test_gene_cursor_rejects_cross_release_replay():
    gene_service = import_module("app.services.gene_service")
    release_context = import_module("app.services.release_context")
    context = release_context.ReleaseContext(release_id=7)
    params = GeneListParams(chromosome="Gm01")
    cursor = gene_service.encode_cursor(
        "Glyma.01G000100",
        501,
        release_context=context,
        params=params,
    )

    # The sort key is (accession, gene_pk): accessions repeat across
    # assemblies, so the surrogate key is the stable tiebreaker.
    assert gene_service.decode_cursor(
        cursor,
        release_context=context,
        params=params,
    ) == ("Glyma.01G000100", 501)
    with pytest.raises(ValidationError, match="context"):
        gene_service.decode_cursor(
            cursor,
            release_context=release_context.ReleaseContext(release_id=8),
            params=params,
        )
    with pytest.raises(ValidationError, match="context"):
        gene_service.decode_cursor(
            cursor,
            release_context=context,
            params=GeneListParams(chromosome="Gm02"),
        )


def test_list_openapi_exposes_release_and_allele_consequence_filters():
    main = import_module("app.main")
    schema = main.app.openapi()

    variant_parameters = {
        parameter["name"] for parameter in schema["paths"]["/api/v1/variants"]["get"]["parameters"]
    }
    gene_parameters = {
        parameter["name"] for parameter in schema["paths"]["/api/v1/genes"]["get"]["parameters"]
    }

    assert {"release_id", "ref", "alt", "consequence"} <= variant_parameters
    assert "release_id" in gene_parameters
