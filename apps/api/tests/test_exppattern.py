"""Tests for the expression-pattern tool (``POST /api/v1/tools/exppattern``).

Covers: matrix structure, z-score scaling, clustering ordering (both SciPy
hierarchical and mean-sort fallback), missing-gene handling, condition
filtering, and the 50 genes × 200 conditions scale limit (422).
Uses mocked DB session — no PostgreSQL required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.schemas.exppattern import ExpPatternResponse
from app.services import exppattern_service
from app.services.release_context import ReleaseContext, get_release_context

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_exec_result(scalars_list=None):
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_list or []
    r.scalars.return_value.first.return_value = (
        scalars_list[0] if scalars_list else None
    )
    return r


def _make_rows_result(rows=None):
    """Result of ``.all()`` (used by the accession -> gene_pk resolution)."""
    r = MagicMock()
    r.all.return_value = rows or []
    return r


# Stable surrogate keys for the accessions used throughout this module. The
# service resolves accessions to ``gene_pk`` before querying expression rows,
# so a mocked expression row must carry the *resolved* key, not the accession.
ACCESSION_TO_PK = {"G1": 101, "G2": 102, "G3": 103}


def test_exppattern_response_rejects_invalid_row_order():
    with pytest.raises(ValueError, match="row_order must be a permutation"):
        ExpPatternResponse(
            assembly_id=1,
            release_id=7,
            assembly_name="Wm82.v5",
            assembly_version="v5",
            genes=["G1", "G2"],
            conditions=["leaf"],
            matrix=[[1.0], [2.0]],
            row_order=[0, 0],
            clustering="hierarchical",
            value_range=(1.0, 2.0),
            missing_genes=[],
            scale="none",
        )


def _make_accession_result(accessions):
    """Assembly-scoped accession -> surrogate-key query result."""
    return _make_rows_result([(a, ACCESSION_TO_PK[a]) for a in accessions])


def _make_assembly(assembly_id=1, name="Wm82.v5", version="v5"):
    assembly = MagicMock()
    assembly.id = assembly_id
    assembly.name = name
    assembly.version = version
    assembly.release_id = 7
    return assembly


def _make_lib(lib_id: int, name: str, assembly_id: int = 1):
    lib = MagicMock()
    lib.id = lib_id
    lib.library_name = name
    lib.tissue = "leaf"
    lib.treatment = "control"
    lib.assembly_id = assembly_id
    return lib


def _make_expr(gene_id: str | int, library, fpkm: float | None):
    """An expression row. ``gene_id`` here is the resolved ``gene_pk``.

    Accepts a bare accession for readability and resolves it to the surrogate
    key the service expects.
    """
    ed = MagicMock()
    ed.gene_id = ACCESSION_TO_PK[gene_id] if isinstance(gene_id, str) else gene_id
    ed.library_id = library.id
    ed.fpkm = fpkm
    ed.library = library
    return ed


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    default_result = _make_exec_result()
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


@pytest.fixture
def libraries():
    return [_make_lib(1, "Leaf Control"), _make_lib(2, "Root Drought")]


@pytest.fixture
async def client(mock_session):
    """Test client with the *mock_session* injected."""
    from app.api.v1.tools_exppattern import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    async def override_release_context():
        return ReleaseContext(release_id=7, assembly_id=1, assembly="Wm82.v5")

    app.dependency_overrides[get_release_context] = override_release_context

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _setup_data(
    mock_session, libraries, expr_rows, accessions=None, *, assembly_id=1
):
    """Configure the four expected executes of the service.

    Order: assembly -> scoped expression libraries -> accession/gene_pk
    resolution -> expression rows. ``accessions`` defaults to every accession referenced by
    ``expr_rows`` (plus any passed explicitly).
    """
    if accessions is None:
        resolved_pks = {row.gene_id for row in expr_rows}
        accessions = [a for a, pk in ACCESSION_TO_PK.items() if pk in resolved_pks]
    mock_session.execute.side_effect = [
        _make_exec_result(
            scalars_list=[
                _make_assembly(
                    assembly_id,
                    "Wm82.v5" if assembly_id == 1 else f"Assembly.{assembly_id}",
                    "v5" if assembly_id == 1 else f"v{assembly_id}",
                )
            ]
        ),
        _make_exec_result(scalars_list=libraries),
        _make_accession_result(accessions),
        _make_exec_result(scalars_list=expr_rows),
    ]


# ---------------------------------------------------------------------------
# Matrix structure & values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMatrixStructure:
    async def test_matrix_structure_raw_values(
        self, client, mock_session, libraries
    ):
        """scale=none returns raw fpkm values in a gene × condition matrix."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G1", libraries[1], 20.0),
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G2", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1", "G2"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genes"] == ["G1", "G2"]
        assert data["conditions"] == ["Leaf Control", "Root Drought"]
        assert data["matrix"] == [[10.0, 20.0], [1.0, 3.0]]
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "input"
        assert data["missing_genes"] == []
        assert data["value_range"] == [1.0, 20.0]
        assert data["assembly_id"] == 1
        assert data["assembly_name"] == "Wm82.v5"
        assert data["assembly_version"] == "v5"
        assert data["release_id"] == 7

    async def test_assembly_scope_is_applied_to_library_and_gene_queries(
        self, client, mock_session
    ):
        """Same accession names resolve only inside the selected assembly."""
        assembly_id = 2
        library = _make_lib(9, "Leaf Control", assembly_id=assembly_id)
        _setup_data(
            mock_session,
            [library],
            [_make_expr("G1", library, 7.5)],
            assembly_id=assembly_id,
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": assembly_id, "genes": ["G1"], "scale": "none"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["assembly_id"] == assembly_id
        assert data["assembly_name"] == "Assembly.2"
        assert data["matrix"] == [[7.5]]
        assembly_sql = str(mock_session.execute.call_args_list[0].args[0])
        library_sql = str(mock_session.execute.call_args_list[1].args[0])
        gene_sql = str(mock_session.execute.call_args_list[2].args[0])
        expression_sql = str(mock_session.execute.call_args_list[3].args[0])
        assert "assemblies.release_id" in assembly_sql
        assert "expression_libraries.assembly_id" in library_sql
        assert "genes.assembly_id" in gene_sql
        assert "expression_libraries.assembly_id" in expression_sql

    async def test_unknown_assembly_returns_not_found(self, client, mock_session):
        mock_session.execute.return_value = _make_exec_result()
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 9999, "genes": ["G1"]},
        )
        assert response.status_code == 404
        assert mock_session.execute.await_count == 1

    async def test_zscore_default(self, client, mock_session, libraries):
        """Default scale=zscore standardizes each gene row (ddof=0)."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 1.0),
                _make_expr("G1", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["G1"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scale"] == "zscore"
        # mean=2, std=1 -> [-1, 1]
        assert data["matrix"] == [[-1.0, 1.0]]

    async def test_zscore_constant_row_is_zero(self, client, mock_session, libraries):
        """A constant row has undefined z-score -> zeros (no NaN)."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 5.0),
                _make_expr("G1", libraries[1], 5.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["G1"]}
        )
        assert response.status_code == 200
        assert response.json()["matrix"] == [[0.0, 0.0]]

    async def test_condition_filtering(self, client, mock_session, libraries):
        """Passing conditions restricts the matrix columns to those libraries."""
        _setup_data(
            mock_session,
            [libraries[0]],
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G2", libraries[0], 2.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={
                "assembly_id": 1, "genes": ["G1", "G2"],
                "conditions": ["Leaf Control"],
                "scale": "none",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conditions"] == ["Leaf Control"]
        assert data["matrix"] == [[10.0], [2.0]]

    async def test_duplicate_genes_deduplicated(self, client, mock_session, libraries):
        """Duplicate gene ids are returned once (row order preserved)."""
        _setup_data(
            mock_session,
            libraries,
            [_make_expr("G1", libraries[0], 10.0)],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1", "G1", "G2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genes"] == ["G1", "G2"]
        assert len(data["matrix"]) == 2


# ---------------------------------------------------------------------------
# Assembly-scoped accession resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAssemblyScopedResolution:
    async def test_ambiguous_accession_across_assemblies_is_rejected(
        self, client, mock_session, libraries
    ):
        """The same accession in two assemblies must not silently mix v4/v5."""
        r = MagicMock()
        r.all.return_value = [("G1", 101), ("G1", 201)]
        mock_session.execute.side_effect = [
            _make_exec_result(scalars_list=[_make_assembly()]),
            _make_exec_result(scalars_list=libraries),
            r,
        ]
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["G1"]}
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"].get("details", {}).get("code") == "ambiguous_assembly"
        assert body["error"]["details"]["accessions"] == ["G1"]

    async def test_unknown_accession_yields_null_row_without_data_query(
        self, client, mock_session, libraries
    ):
        """An accession with no gene row is 'missing', not an error."""
        _setup_data(mock_session, libraries, [], accessions=[])
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["NOPE"], "scale": "none"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["missing_genes"] == ["NOPE"]
        assert data["matrix"] == [[None, None]]
        # libraries + accession resolution; the expression query still runs but
        # matches nothing because no surrogate key was resolved.
        assert mock_session.execute.await_count == 4


# ---------------------------------------------------------------------------
# Missing genes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMissingGenes:
    async def test_missing_gene_gets_null_row(
        self, client, mock_session, libraries
    ):
        """A gene without expression records yields a null row + annotation."""
        _setup_data(
            mock_session,
            libraries,
            [_make_expr("G1", libraries[0], 10.0)],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1", "G2"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["missing_genes"] == ["G2"]
        assert data["matrix"] == [[10.0, None], [None, None]]
        # value_range covers only non-null cells
        assert data["value_range"] == [10.0, 10.0]

    async def test_all_missing_value_range_none(self, client, mock_session, libraries):
        """All cells missing -> value_range is [None, None]."""
        _setup_data(mock_session, libraries, [])
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["G1"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matrix"] == [[None, None]]
        assert data["value_range"] == [None, None]
        assert data["missing_genes"] == ["G1"]


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClustering:
    async def test_mean_sort_fallback(
        self, client, mock_session, libraries, monkeypatch
    ):
        """Without SciPy, rows are sorted by mean expression (annotated)."""
        monkeypatch.setattr(exppattern_service, "pdist", None)
        monkeypatch.setattr(exppattern_service, "linkage", None)
        monkeypatch.setattr(exppattern_service, "leaves_list", None)
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G1", libraries[1], 20.0),
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G2", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1", "G2"], "scale": "none", "cluster_rows": True},
        )
        assert response.status_code == 200
        data = response.json()
        # G1 mean=15 > G2 mean=2 -> G1 first
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "mean_sort"
        assert data["matrix"][0] == [10.0, 20.0]

    async def test_hierarchical_clustering(
        self, client, mock_session, libraries, monkeypatch
    ):
        """With SciPy available, linkage+leaves_list drive the row order."""
        fake_linkage = MagicMock(return_value=object())
        fake_leaves = MagicMock(return_value=[1, 0])
        fake_pdist = MagicMock(return_value=[1.0])
        monkeypatch.setattr(exppattern_service, "pdist", fake_pdist)
        monkeypatch.setattr(exppattern_service, "linkage", fake_linkage)
        monkeypatch.setattr(exppattern_service, "leaves_list", fake_leaves)
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 1.0),
                _make_expr("G1", libraries[1], 3.0),
                _make_expr("G2", libraries[0], 10.0),
                _make_expr("G2", libraries[1], 20.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1", "G2"], "cluster_rows": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["clustering"] == "hierarchical"
        assert data["row_order"] == [1, 0]
        # distance computed on the imputed matrix (no NaN)
        assert fake_pdist.call_args.args[0] == [[-1.0, 1.0], [-1.0, 1.0]]

    async def test_no_clustering_when_disabled(
        self, client, mock_session, libraries
    ):
        """cluster_rows=false keeps input order and reports clustering=input."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G1", libraries[0], 10.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G2", "G1"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "input"


# ---------------------------------------------------------------------------
# Scale limits (422)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestScaleLimits:
    async def test_too_many_genes_422(self, client, mock_session):
        """More than 50 genes is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": [f"G{i}" for i in range(51)]},
        )
        assert response.status_code == 422
        assert "error" in response.json()

    async def test_too_many_conditions_422(self, client, mock_session):
        """More than 200 conditions is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1"], "conditions": [f"L{i}" for i in range(201)]},
        )
        assert response.status_code == 422
        assert "error" in response.json()

    async def test_db_resolved_conditions_over_limit_422(
        self, client, mock_session
    ):
        """>200 libraries resolved from DB (no conditions given) -> 422."""
        libs = [_make_lib(i, f"L{i}") for i in range(201)]
        _setup_data(mock_session, libs, [])
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["G1"]}
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error"]["code"] == "validation_error"

    async def test_empty_genes_422(self, client, mock_session):
        """Empty or blank-only genes list is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": []}
        )
        assert response.status_code == 422
        response = await client.post(
            "/api/v1/tools/exppattern", json={"assembly_id": 1, "genes": ["  "]}
        )
        assert response.status_code == 422

    async def test_invalid_scale_422(self, client, mock_session):
        """Unknown scale value is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"assembly_id": 1, "genes": ["G1"], "scale": "log2"},
        )
        assert response.status_code == 422
