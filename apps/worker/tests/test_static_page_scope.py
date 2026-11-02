"""Release scope and bounded batching for the static gene-page build.

Two failure modes are locked here.  The first is publishing without a scope:
``upload_s3=True`` used to accept ``release_id=None`` and then write objects
into the release-less ``{assembly_id}/genes/`` namespace, so a draft or unknown
release could land behind a public URL.  The second is reading without a bound:
the gene list was materialised in one ``.all()`` before any work started, so a
large genome loaded every gene row into worker memory at once.

The contract now: the public path requires an existing ``published`` release
and joins ``assemblies`` to scope both the count and every keyset page, and the
walk advances by ``gene_pk`` in pages of at most ``_GENE_CHUNK`` rows, each read
inside its own short read-only repeatable-read snapshot.

Scope of the evidence, stated plainly: these are compiled-statement and
fake-session tests.  They assert the SQL that PostgreSQL would receive and
simulate the keyset walk by deriving page contents from the bound keyset
parameter, but no test here executes against a live PostgreSQL server.  Real
execution of the isolation statement and of the join against the API-owned
``assemblies.release_id`` column is a PostgreSQL integration concern, not
something this module proves.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import dialect as pg_dialect
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList
from sqlalchemy.sql.expression import Insert, TextClause

from soymutdb_worker.tables import assemblies
from soymutdb_worker.tasks import static_pages
from soymutdb_worker.tasks.static_pages import (
    _SNAPSHOT_ISOLATION_SQL,
    build_static_pages,
    gene_metadata_statement,
    gene_scope_count_statement,
    iter_gene_batches,
    require_published_release,
)

_PG = pg_dialect()


def _sql(stmt) -> str:
    """Compile a statement the way PostgreSQL would receive it."""
    return str(_compile(stmt))


def _params(stmt) -> dict:
    """Return the bound parameter values the statement will be sent with."""
    return dict(_compile(stmt).params)


def _compile(stmt):
    return stmt.compile(dialect=_PG, compile_kwargs={"render_postcompile": True})


def _bound(stmt, column_name):
    """Return the bound value of a ``column = :param`` predicate, if present."""
    for criterion in _criteria(stmt):
        if not isinstance(criterion, BinaryExpression):
            continue
        left, right = criterion.left, criterion.right
        if isinstance(left, Column) and left.name == column_name:
            if isinstance(right, BindParameter):
                return right.value
    return None


def _bound_in(stmt, column_name):
    """Return the values of a ``column IN (...)`` predicate, if present."""
    if column_name + " IN (" not in _sql(stmt):
        return None
    prefix = column_name + "_"
    values = [v for k, v in _params(stmt).items() if k.startswith(prefix)]
    flat: list = []
    for value in values:
        flat.extend(value if isinstance(value, (list, tuple)) else [value])
    return flat or None


def _criteria(stmt) -> list:
    """Flatten the WHERE clause into its individual predicate criteria."""
    whereclause = stmt.whereclause
    if whereclause is None:
        return []
    if isinstance(whereclause, BooleanClauseList):
        found: list = []
        for clause in whereclause.clauses:
            if isinstance(clause, BooleanClauseList):
                found.extend(_criteria(type("W", (), {"whereclause": clause})()))
            else:
                found.append(clause)
        return found
    return [whereclause]


# ---------------------------------------------------------------------------
# Statement level: the SQL that reaches PostgreSQL
# ---------------------------------------------------------------------------


def test_release_scope_joins_assemblies_and_filters_on_its_release() -> None:
    stmt = gene_metadata_statement(release_id=7)
    sql = _sql(stmt)
    assert "JOIN assemblies ON genes.assembly_id = assemblies.id" in sql
    assert "assemblies.release_id = " in sql
    assert 7 in _params(stmt).values()


def test_omitted_release_keeps_the_unscoped_internal_query() -> None:
    """The internal (upload_s3=False) rebuild path still has no release join."""
    assert "assemblies" not in _sql(gene_metadata_statement(release_id=None))


def test_page_is_keyset_ordered_and_capped() -> None:
    stmt = gene_metadata_statement(after_gene_pk=41)
    sql = _sql(stmt)
    assert "ORDER BY genes.gene_pk" in sql
    assert "genes.gene_pk > " in sql
    assert 41 in _params(stmt).values()
    assert stmt._limit == static_pages._GENE_CHUNK
    assert "LIMIT" in sql


def test_first_page_has_no_keyset_predicate() -> None:
    assert "gene_pk >" not in _sql(gene_metadata_statement())


def test_accession_filter_is_applied() -> None:
    stmt = gene_metadata_statement(gene_ids=["Glyma.01G000100"])
    assert "genes.accession IN (" in _sql(stmt)
    assert "Glyma.01G000100" in _params(stmt).values()


def test_count_statement_shares_the_page_scope() -> None:
    count_stmt = gene_scope_count_statement(release_id=7)
    count_sql = _sql(count_stmt)
    page_sql = _sql(gene_metadata_statement(release_id=7))
    assert "assemblies.release_id = " in count_sql
    assert 7 in _params(count_stmt).values()
    assert "count(*)" in count_sql.lower()
    assert "WHERE assemblies.release_id = " in page_sql
    assert "LIMIT" not in count_sql


def test_unscoped_count_has_no_assemblies_join() -> None:
    assert "assemblies" not in _sql(gene_scope_count_statement())


def test_snapshot_statement_is_read_only_and_repeatable_read() -> None:
    assert "ISOLATION LEVEL REPEATABLE READ" in _SNAPSHOT_ISOLATION_SQL
    assert "READ ONLY" in _SNAPSHOT_ISOLATION_SQL


def test_worker_tables_expose_the_narrow_release_column() -> None:
    assert "release_id" in assemblies.c


# ---------------------------------------------------------------------------
# Fake session harness
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, *, scalar=None, rows=()) -> None:
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def all(self) -> list:
        return list(self._rows)


def _gene_row(gene_pk: int, accession: str, assembly_id: int, assembly_release: int | None):
    return SimpleNamespace(
        gene_pk=gene_pk,
        accession=accession,
        assembly_id=assembly_id,
        name="name-" + accession,
        biotype="mRNA",
        start=100,
        end=200,
        strand="+",
        description=None,
        chromosome_name="Chr01",
        assembly_release=assembly_release,
    )


class FakeSession:
    def __init__(self, db: FakeDatabase) -> None:
        self.db = db
        self.statements: list = []
        self.closed = False

    def execute(self, stmt, *args, **kwargs) -> FakeResult:
        self.statements.append(stmt)
        return self.db.dispatch(stmt)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeDatabase:
    """Answers the worker's statements from an in-memory gene fixture.

    Gene pages are derived from the bound keyset parameter of the incoming
    statement, not from a queue of pre-canned batches, so a broken cursor
    (re-reading page one, skipping rows, or ignoring the cap) shows up as wrong
    rows rather than as a green test.
    """

    def __init__(self, genes=(), release_status="published", fail_gene_pks=()) -> None:
        self.genes = list(genes)
        self.release_status = release_status
        self.release_statuses: list = []
        self.fail_gene_pks = set(fail_gene_pks)
        self.sessions: list = []
        self.gene_pages: list = []
        self.counts: list = []
        self.upserts: list = []
        self.snapshot_sql: list = []

    def dispatch(self, stmt) -> FakeResult:
        if isinstance(stmt, TextClause):
            self.snapshot_sql.append(str(stmt))
            return FakeResult()
        if isinstance(stmt, Insert):
            self.upserts.append(stmt)
            return FakeResult()

        names = {d["name"] for d in stmt.column_descriptions}

        if names == {"status"}:
            if self.release_statuses:
                if len(self.release_statuses) > 1:
                    self.release_status = self.release_statuses.pop(0)
                else:
                    self.release_status = self.release_statuses[0]
            return FakeResult(scalar=self.release_status)
        if "gene_pk" in names:
            after = _bound(stmt, "gene_pk")
            release = _bound(stmt, "release_id")
            rows = self._matching(release, _bound_in(stmt, "accession"))
            if after is not None:
                rows = [r for r in rows if r.gene_pk > after]
            rows = rows[: getattr(stmt, "_limit", None) or len(rows)]
            self.gene_pages.append(
                {
                    "after": after,
                    "release": release,
                    "sql": _sql(stmt),
                    "limit": getattr(stmt, "_limit", None),
                    "rows": rows,
                }
            )
            return FakeResult(rows=rows)
        if "count" in names:
            # The per-gene expression summary also counts, but it filters on
            # expression_data.gene_id; the scoped gene count never does.
            if _bound(stmt, "gene_id") is None:
                total = len(
                    self._matching(_bound(stmt, "release_id"), _bound_in(stmt, "accession"))
                )
                self.counts.append(_sql(stmt))
                return FakeResult(scalar=total)
            gene_id = _bound(stmt, "gene_id")
            if gene_id in self.fail_gene_pks:
                raise RuntimeError("expression read failed for gene " + str(gene_id))
            return FakeResult(scalar=0)
        if "library_name" in names:
            return FakeResult(rows=[])
        if "homolog_species" in names:
            return FakeResult(rows=[])
        raise AssertionError("unexpected statement: " + _sql(stmt))

    def _matching(self, release, accessions=None) -> list:
        rows = sorted(self.genes, key=lambda r: r.gene_pk)
        if release is not None:
            rows = [r for r in rows if r.assembly_release == release]
        if accessions is not None:
            rows = [r for r in rows if r.accession in accessions]
        return rows

    @contextmanager
    def patched(self, monkeypatch):
        @contextmanager
        def fake_get_db():
            session = FakeSession(self)
            self.sessions.append(session)
            try:
                yield session
            finally:
                session.closed = True

        monkeypatch.setattr(static_pages, "get_db", fake_get_db)
        monkeypatch.setattr(static_pages, "get_setting", lambda key, default=None: default)
        yield fake_get_db


class FakeSelf:
    def __init__(self) -> None:
        self.states: list = []

    def update_state(self, state=None, meta=None, **kwargs) -> None:
        self.states.append({"state": state, "meta": meta})


class RecordingS3Client:
    def __init__(self) -> None:
        self.keys: list = []

    def put_object(self, **kwargs) -> None:
        self.keys.append(kwargs["Key"])


def _run(**kwargs):
    fake_self = FakeSelf()
    result = build_static_pages.run.__func__(self=fake_self, **kwargs)
    return result, fake_self


# ---------------------------------------------------------------------------
# Fail-closed release validation on the public path
# ---------------------------------------------------------------------------


def test_public_build_without_a_release_is_rejected(monkeypatch) -> None:
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7)])
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        with pytest.raises(ValueError, match="requires an explicit release_id"):
            _run(gene_ids=None, release_id=None, upload_s3=True)

    assert s3.keys == []
    assert db.upserts == []


def test_storage_is_not_touched_when_the_release_is_invalid(monkeypatch) -> None:
    """The client is built only after the scope validates, so a bad scope
    never reaches out to object storage."""
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7)], release_status="draft")
    s3_calls: list = []
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3_calls.append(1))

    with db.patched(monkeypatch):
        with pytest.raises(ValueError, match="refusing to publish"):
            _run(gene_ids=None, release_id=7, upload_s3=True)

    assert s3_calls == []


@pytest.mark.parametrize("status", ["draft", "validated", "ready", "rolled_back"])
def test_public_build_of_an_unpublished_release_is_rejected(status, monkeypatch) -> None:
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7)], release_status=status)
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        with pytest.raises(ValueError, match="refusing to publish"):
            _run(gene_ids=None, release_id=7, upload_s3=True)

    assert s3.keys == []


def test_public_build_of_an_unknown_release_is_rejected(monkeypatch) -> None:
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7)], release_status=None)
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        with pytest.raises(ValueError, match="does not exist"):
            _run(gene_ids=None, release_id=999, upload_s3=True)

    assert s3.keys == []


def test_require_published_release_accepts_published() -> None:
    class _Result:
        def scalar_one_or_none(self):
            return "published"

    class _Session:
        def execute(self, stmt, *a, **kw):
            return _Result()

    require_published_release(_Session(), 7)  # must not raise


# ---------------------------------------------------------------------------
# Batching, keyset advance, and progress
# ---------------------------------------------------------------------------


def test_every_page_is_capped_and_cursor_starts_unset(monkeypatch) -> None:
    monkeypatch.setattr(static_pages, "_GENE_CHUNK", 2)
    genes = [_gene_row(i, "G" + str(i), 1, 7) for i in range(1, 6)]
    db = FakeDatabase(genes=genes)

    with db.patched(monkeypatch):
        batches = list(iter_gene_batches(release_id=7))

    assert [[r.gene_pk for r in b] for b in batches] == [[1, 2], [3, 4], [5]]
    assert [page["after"] for page in db.gene_pages] == [None, 2, 4, 5]
    assert all(page["limit"] == 2 for page in db.gene_pages)
    assert all("LIMIT" in page["sql"] for page in db.gene_pages)
    assert all(len(page["rows"]) <= 2 for page in db.gene_pages)


def test_each_page_is_read_in_its_own_read_only_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(static_pages, "_GENE_CHUNK", 1)
    db = FakeDatabase(genes=[_gene_row(i, "G" + str(i), 1, 7) for i in range(1, 4)])

    with db.patched(monkeypatch):
        list(iter_gene_batches(release_id=7))

    assert db.snapshot_sql, "no snapshot isolation statement was issued"
    assert set(db.snapshot_sql) == {_SNAPSHOT_ISOLATION_SQL}
    # Every session that ran a statement opened with the isolation statement,
    # and every session was closed, so no long-lived read transaction lingers.
    for session in db.sessions:
        if session.statements:
            assert isinstance(session.statements[0], TextClause)
        assert session.closed


def test_keyset_advances_past_a_row_that_fails_to_process(monkeypatch) -> None:
    monkeypatch.setattr(static_pages, "_GENE_CHUNK", 2)
    genes = [_gene_row(i, "G" + str(i), 1, 7) for i in range(1, 6)]
    db = FakeDatabase(genes=genes, fail_gene_pks={2})

    with db.patched(monkeypatch):
        result, fake_self = _run(gene_ids=None, release_id=7, upload_s3=False)

    assert result == {"processed": 4, "failed": 1, "total": 5}
    # The failed row did not rewind or stall the cursor: every gene was visited.
    assert [page["after"] for page in db.gene_pages] == [None, 2, 4, 5]
    assert len(db.upserts) == 4
    assert fake_self.states[-1]["meta"] == {
        "progress": 100,
        "processed": 4,
        "failed": 1,
        "total": 5,
    }


def test_progress_reports_totals_from_the_scoped_count(monkeypatch) -> None:
    genes = [_gene_row(i, "G" + str(i), 1 if i % 2 else 2, 7 if i % 2 else 8) for i in range(1, 7)]
    db = FakeDatabase(genes=genes)

    with db.patched(monkeypatch):
        result, fake_self = _run(gene_ids=None, release_id=7, upload_s3=False)

    # Only the odd rows belong to release 7; release 8's genes are never read.
    assert result == {"processed": 3, "failed": 0, "total": 3}
    assert len(db.counts) == 1
    assert "assemblies.release_id = " in db.counts[0]
    assert all("assemblies.release_id = " in page["sql"] for page in db.gene_pages)
    assert all(page["release"] == 7 for page in db.gene_pages)
    assert fake_self.states[-1]["meta"]["total"] == 3


def test_empty_selection_returns_early_without_reading_or_uploading(monkeypatch) -> None:
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7)])
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        result, fake_self = _run(gene_ids=["absent"], release_id=7, upload_s3=True)

    assert result == {"processed": 0, "total": 0}
    assert db.gene_pages == []
    assert s3.keys == []
    assert fake_self.states == []


def test_unscoped_internal_mode_still_allowed_without_upload(monkeypatch) -> None:
    """upload_s3=False keeps the historical release-less internal rebuild."""
    db = FakeDatabase(genes=[_gene_row(1, "G1", 1, 7), _gene_row(2, "G2", 2, 8)])

    with db.patched(monkeypatch):
        result, _ = _run(gene_ids=None, release_id=None, upload_s3=False)

    assert result == {"processed": 2, "failed": 0, "total": 2}
    assert db.counts and "assemblies" not in db.counts[0]


def test_published_release_uploads_release_and_assembly_scoped_keys(monkeypatch) -> None:
    genes = [
        _gene_row(1, "Glyma.01G000100", 1, 7),
        _gene_row(2, "Glyma.01G000100", 2, 7),
    ]
    db = FakeDatabase(genes=genes)
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        result, _ = _run(gene_ids=None, release_id=7, upload_s3=True)

    assert result == {"processed": 2, "failed": 0, "total": 2}
    # v4 and v5 rows share an accession; release + assembly keep them apart.
    assert s3.keys == [
        "7/1/genes/Glyma.01G000100.json.gz",
        "7/1/genes/Glyma.01G000100.html.gz",
        "7/2/genes/Glyma.01G000100.json.gz",
        "7/2/genes/Glyma.01G000100.html.gz",
    ]


def test_rollback_mid_build_stops_further_public_uploads(monkeypatch) -> None:
    """The release is re-checked per batch, not only at start of build."""
    monkeypatch.setattr(static_pages, "_GENE_CHUNK", 2)
    genes = [_gene_row(i, "G" + str(i), 1, 7) for i in range(1, 7)]
    db = FakeDatabase(genes=genes)
    # initial check, first batch check, second batch check -> rolled back
    db.release_statuses = ["published", "published", "rolled_back"]
    s3 = RecordingS3Client()
    monkeypatch.setattr(static_pages, "get_s3_client", lambda: s3)

    with db.patched(monkeypatch):
        with pytest.raises(ValueError, match="refusing to publish"):
            _run(gene_ids=None, release_id=7, upload_s3=True)

    # Batch one was published; nothing from batch two or later reached the bucket.
    assert s3.keys == [
        "7/1/genes/G1.json.gz",
        "7/1/genes/G1.html.gz",
        "7/1/genes/G2.json.gz",
        "7/1/genes/G2.html.gz",
    ]


def test_accession_selection_narrows_the_count(monkeypatch) -> None:
    genes = [_gene_row(i, "G" + str(i), 1, 7) for i in range(1, 4)]
    db = FakeDatabase(genes=genes)

    with db.patched(monkeypatch):
        result, _ = _run(gene_ids=["G2"], release_id=7, upload_s3=False)

    assert result == {"processed": 1, "failed": 0, "total": 1}
    assert "genes.accession IN (" in db.counts[0]
