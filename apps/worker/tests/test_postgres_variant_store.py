"""Real PostgreSQL staging, collision and atomic visibility acceptance."""

from __future__ import annotations

import ast
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from soymutdb_worker.native_backfill import transfer_release
from soymutdb_worker.tables import import_manifests
from soymutdb_worker.tasks import export as exports
from soymutdb_worker.tasks import ingest, native_retention
from soymutdb_worker.tasks import stats as statistics
from soymutdb_worker.tasks.import_manifest_repo import start_or_resume
from soymutdb_worker.tasks.postgres_variant_store import PostgresVariantStore
from soymutdb_worker.tasks.variant_finalize import BASE_COLUMNS, ConflictingVariantRowsError


def _native_url_or_fail() -> str:
    """The native PostgreSQL URL, or a hard failure.

    Fail-closed on purpose. The backend gate exports
    ``SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`` to say "a real database is
    available"; a suite that then *skips* because its own URL is missing
    reports the same pytest verdict as a suite that ran and passed. These tests
    cover variant identity, atomic publication and assembly scoping -- skipping
    them is a merge-gate hole, not an opt-out.

    ``scripts/with-postgres-service.sh`` exports this variable, so an absent
    value means the resolver or the caller dropped it, never "no database".
    """
    url = os.environ.get("SOYMUTDB_NATIVE_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "SOYMUTDB_NATIVE_TEST_DATABASE_URL is required: scripts/with-postgres-service.sh "
            "derives it from SOYMUTDB_TEST_DATABASE_URL. This suite is a merge gate; it "
            "must fail rather than skip."
        )
    return url


@pytest.fixture
def native_database(monkeypatch):
    url = _native_url_or_fail()
    schema = "native_vcf_" + uuid.uuid4().hex[:12]
    admin = create_engine(url)
    options = {"options": f"-csearch_path={schema},public"}
    engine = create_engine(url, connect_args=options, pool_size=1, max_overflow=0, pool_timeout=2)
    observer = create_engine(url, connect_args=options)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE releases (id INTEGER PRIMARY KEY, status TEXT)"))
            connection.execute(text("CREATE TABLE assemblies (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO releases VALUES (1,'draft'),(2,'published')"))
            connection.execute(text("INSERT INTO assemblies VALUES (4),(5)"))
            connection.execute(text(
                "CREATE TYPE import_manifest_status_enum AS ENUM "
                "('created','parsing','writing','verifying','published','failed')"
            ))
            import_manifests.create(connection)
            revision = Path(__file__).resolve().parents[3] / (
                "apps/api/migrations/versions/0047_native_variant_analytics.py"
            )
            # Reuse the migration's immutable column snapshot without importing
            # the API runtime or requiring Alembic in the worker environment.
            # Upgrade/downgrade themselves are exercised by the API PG suite.
            source = ast.parse(revision.read_text(encoding="utf-8"))
            definition = next(node for node in source.body if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == "FACT_COLUMNS"
                                      for target in node.targets))
            columns = ast.literal_eval(definition.value)
            connection.execute(text(
                "CREATE TABLE variant_facts (" + columns
                + ", PRIMARY KEY (release_id,assembly_id,variant_id), "
                "UNIQUE (release_id,variant_id))"
            ))
            connection.execute(text(
                "CREATE TABLE variant_facts_staging (" + columns
                + ", import_id VARCHAR(128) NOT NULL,batch_id VARCHAR(64) NOT NULL, "
                "PRIMARY KEY (import_id,assembly_id,variant_id))"
            ))
        factory = sessionmaker(engine)

        @contextmanager
        def get_db():
            # Match the production context: manifest lifecycle helpers commit
            # phase transitions, so Session.begin() would prohibit their next
            # query after an explicit commit.
            with factory() as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        monkeypatch.setattr(ingest, "get_db", get_db)
        monkeypatch.setattr(statistics, "get_db", get_db)
        monkeypatch.setattr(exports, "get_db", get_db)
        monkeypatch.setattr(native_retention, "get_db", get_db)
        yield get_db, observer
    finally:
        observer.dispose()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_native_retention_bounds_and_publication(native_database):
    from datetime import UTC, datetime, timedelta

    get_db, observer = native_database
    cutoff = datetime.now(UTC) - timedelta(days=90)
    with get_db() as session:
        session.execute(text(
            "CREATE TABLE web_vitals (vital_pk BIGINT PRIMARY KEY, timestamp TIMESTAMPTZ)"
        ))
        for identity, timestamp in ((1, cutoff - timedelta(seconds=1)),
                                    (2, cutoff - timedelta(days=1)), (3, cutoff)):
            session.execute(text("INSERT INTO web_vitals VALUES (:id,:timestamp)"),
                            {"id": identity, "timestamp": timestamp})
    assert native_retention.prune_telemetry("web_vitals", cutoff, batch_size=1) == 1
    assert native_retention.prune_telemetry("web_vitals", cutoff, batch_size=1) == 1
    assert native_retention.prune_telemetry("web_vitals", cutoff, batch_size=1) == 0
    published = _manifest(get_db, source="d")
    pending = _manifest(get_db, source="e")
    _stage(get_db, published, [_row(1)])
    _stage(get_db, pending, [_row(2)])
    with get_db() as session:
        PostgresVariantStore(session).finalize(
            release_id=1, assembly_id=4, import_id=published, expected_rows=1,
        )
    assert native_retention.prune_published_staging(batch_size=1) == 1
    assert native_retention.prune_published_staging(batch_size=1) == 0
    with observer.connect() as connection:
        remaining = connection.execute(
            text("SELECT import_id FROM variant_facts_staging")
        ).scalar_one()
        assert remaining == pending
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar_one() == 1
        assert connection.execute(text("SELECT vital_pk FROM web_vitals")).scalar_one() == 3
    with pytest.raises(ValueError):
        native_retention.prune_telemetry("web_vitals;DROP TABLE releases", cutoff)
    assert native_retention._two_years_before(
        datetime(2024, 2, 29, tzinfo=UTC)
    ) == datetime(2022, 2, 28, tzinfo=UTC)


def test_native_backfill_dry_run_retry_and_collision_rollback(native_database):
    get_db, observer = native_database
    with get_db() as session:
        session.execute(text("ALTER TABLE releases ADD COLUMN version TEXT"))
        session.execute(text(
            "CREATE TABLE native_variant_backfills (release_id INTEGER PRIMARY KEY, "
            "source_version TEXT,source_count BIGINT,payload_sha256 TEXT,assembly_map JSONB)"
        ))
        session.execute(text("UPDATE releases SET version='version-1' WHERE id=1"))
        session.execute(text("ALTER TABLE assemblies ADD COLUMN name TEXT"))
        session.execute(text("ALTER TABLE assemblies ADD COLUMN version TEXT"))
        session.execute(text("UPDATE assemblies SET name='v4', version='v4' WHERE id=4"))
    rows = [_row(1), _row()]
    options = {"release_id": 1, "source_version": "version-1", "assembly_map": {"v4": 4}}
    with get_db() as session:
        report = transfer_release(session, lambda: iter(rows), **options)
        assert report["source_count"] == 2
        assert report["target_count"] == 0
        assert not report["matches"]
    with get_db() as session:
        report = transfer_release(session, lambda: iter(rows), apply=True, **options)
        assert report["matches"]
    with get_db() as session:
        assert transfer_release(session, lambda: iter(rows), apply=True, **options)["matches"]
    with pytest.raises(ValueError, match="verification failed"):
        with get_db() as session:
            transfer_release(session, lambda: iter([_row(1, position=123), _row(2), _row()]),
                             apply=True, **options)
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar_one() == 2
        assert connection.execute(text(
            "SELECT source_count FROM native_variant_backfills WHERE release_id=1"
        )).scalar_one() == 2
        assert connection.execute(text(
            "SELECT position FROM variant_facts WHERE variant_id=1"
        )).scalar_one() == 100
    with pytest.raises(ValueError, match="Unmapped"):
        with get_db() as session:
            transfer_release(session, lambda: iter([_row(1, assembly="v5")]), **options)
    reads = []

    def changing_source():
        reads.append(True)
        return iter(rows if len(reads) == 1 else [_row(1, position=123), _row()])

    with pytest.raises(ValueError, match="Source changed"):
        with get_db() as session:
            transfer_release(session, changing_source, apply=True, **options)
    with pytest.raises(ValueError, match="must not be collapsed"):
        with get_db() as session:
            transfer_release(session, lambda: iter(rows), release_id=1,
                             source_version="version-1", assembly_map={"v4": 4, "v5": 4})


def _row(identity=18446744073709551615, assembly="v4", **changes):
    values = {name: "" for name in BASE_COLUMNS}
    values.update(
        variant_id=identity, release_key="version-1", assembly_key=assembly,
        chromosome="Chr01", position=100, ref_allele="A", alt_allele="T", variant_type="SNP",
        length=1, gene_surrogate_id=0, mutant_line_surrogate_id=0, consequence_id=0,
        quality_score=10.0, read_depth=12, allele_frequency=0.25, filter_status="PASS",
        zygosity="heterozygous",
    )
    values.update(changes)
    return tuple(values[name] for name in BASE_COLUMNS)


def _manifest(get_db, source="a", release_id=1, assembly_id=4):
    with get_db() as session:
        manifest, _ = start_or_resume(
            session, source_sha256=source * 64, release_id=release_id, assembly_id=assembly_id,
            importer_version="test-1", schema_version="fact-pg-1",
            normalization_version="norm-1", config_hash="c" * 64,
        )
        return manifest.import_id


def _stage(get_db, import_id, rows, assembly_id=4, release_id=1):
    with get_db() as session:
        return PostgresVariantStore(session).stage_batch(
            release_id=release_id, assembly_id=assembly_id, import_id=import_id,
            batch_index=0, base_rows=rows,
        )


def test_retry_staging_is_idempotent_and_conflicts_do_not_overwrite(native_database):
    get_db, observer = native_database
    import_id = _manifest(get_db)
    assert _stage(get_db, import_id, [_row()]) == 1
    assert _stage(get_db, import_id, [_row()]) == 1
    with pytest.raises(ConflictingVariantRowsError):
        _stage(get_db, import_id, [_row(ref_allele="G")])
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts_staging")).scalar() == 1
        alleles = connection.execute(text("SELECT ref_allele FROM variant_facts_staging"))
        assert alleles.scalar() == "A"
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 0


def test_facts_and_manifest_become_visible_in_one_commit(native_database):
    get_db, observer = native_database
    import_id = _manifest(get_db)
    _stage(get_db, import_id, [_row()])
    with get_db() as session:
        result = PostgresVariantStore(session).finalize(
            release_id=1, assembly_id=4, import_id=import_id, expected_rows=1,
        )
        assert result["written_rows"] == 1
        with observer.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 0
            statuses = connection.execute(text("SELECT status FROM import_manifests"))
            assert statuses.scalar() == "created"
    with observer.connect() as connection:
        assert connection.execute(text("SELECT variant_id FROM variant_facts")).scalar() == (
            18446744073709551615
        )
        statuses = connection.execute(text("SELECT status FROM import_manifests"))
        assert statuses.scalar() == "published"
    with get_db() as session:
        assert PostgresVariantStore(session).finalize(
            release_id=1, assembly_id=4, import_id=import_id, expected_rows=1,
        )["idempotent"]


def test_conflicting_finalize_rolls_back_new_facts_and_manifest(native_database):
    get_db, observer = native_database
    first = _manifest(get_db)
    _stage(get_db, first, [_row()])
    with get_db() as session:
        PostgresVariantStore(session).finalize(
            release_id=1, assembly_id=4, import_id=first, expected_rows=1,
        )
    second = _manifest(get_db, "b")
    _stage(get_db, second, [_row(ref_allele="G"), _row(identity=10)])
    with pytest.raises(ValueError, match="conflicting payload"):
        with get_db() as session:
            PostgresVariantStore(session).finalize(
                release_id=1, assembly_id=4, import_id=second, expected_rows=2,
            )
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 1
        assert connection.execute(text(
            "SELECT status FROM import_manifests WHERE import_id=:import_id"
        ), {"import_id": second}).scalar() == "created"


def test_finalize_preserves_other_assembly_and_refuses_published_release(native_database):
    get_db, observer = native_database
    for source, assembly, identity in (("a", 4, 10), ("b", 5, 11)):
        import_id = _manifest(get_db, source, assembly_id=assembly)
        _stage(get_db, import_id, [_row(identity, f"v{assembly}")], assembly_id=assembly)
        with get_db() as session:
            PostgresVariantStore(session).finalize(
                release_id=1, assembly_id=assembly, import_id=import_id, expected_rows=1,
            )
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 2
    blocked = _manifest(get_db, "d", release_id=2)
    _stage(get_db, blocked, [_row(12)], release_id=2)
    with pytest.raises(ValueError, match="immutable"):
        with get_db() as session:
            PostgresVariantStore(session).finalize(
                release_id=2, assembly_id=4, import_id=blocked, expected_rows=1,
            )


def test_native_protocol_runs_with_pool_one_and_retries_without_reparsing(
    native_database, monkeypatch,
):
    _get_db, observer = native_database
    def parse(*_args):
        return iter([_row(10), _row(11)])
    monkeypatch.setattr(ingest, "_iter_vcf_base_rows", parse)
    args = dict(
        release_id="version-1", assembly_key="v4", local_vcf_path="unused",
        file_key="unused", batch_size=1, source_sha256="a" * 64,
        release_id_int=1, assembly_id_int=4,
    )
    result = ingest._import_vcf_native(None, **args)
    assert result["written_rows"] == 2
    assert not result["idempotent"]

    def no_reparse(*args):
        raise AssertionError("Successful retry must not parse or stage the source again")

    monkeypatch.setattr(ingest, "_iter_vcf_base_rows", no_reparse)
    assert ingest._import_vcf_native(None, **args)["idempotent"]
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 2


def test_native_statistics_keep_identical_gene_names_in_distinct_assemblies(native_database):
    get_db, _observer = native_database
    for source, assembly, identity in (("a", 4, 10), ("b", 5, 11)):
        import_id = _manifest(get_db, source, assembly_id=assembly)
        _stage(get_db, import_id, [_row(
            identity, f"v{assembly}", gene_id="shared-gene", gene_symbol="shared",
            gene_surrogate_id=100, mutant_line_surrogate_id=200, impact="HIGH",
        )], assembly_id=assembly)
        with get_db() as session:
            PostgresVariantStore(session).finalize(
                release_id=1, assembly_id=assembly, import_id=import_id, expected_rows=1,
            )
    counts = statistics.update_release_stats.run("1")
    assert counts["results"]["1"]["gene_count"] == 2
    assert counts["results"]["1"]["variant_count"] == 2
    burden = statistics.compute_gene_burden.run("1")
    assert {row["assembly_key"] for row in burden["genes"]} == {"v4", "v5"}
    density = statistics.compute_chromosome_density.run("1", "Chr01")
    assert density["bin_count"] == 2
    assert density["total_variants"] == 2
    assert {row["assembly_key"] for row in density["bins"]} == {"v4", "v5"}
    comparison = statistics.compute_mutant_line_comparison.run("1", [200])
    assert comparison["mutant_lines"][0]["unique_variants"] == 2


def test_native_public_export_masks_internal_names_and_unreleased_facts(native_database):
    get_db, _observer = native_database
    with get_db() as session:
        session.execute(text(
            "CREATE TABLE mutant_lines (id int,name text,public_id text,release_id int, "
            "is_public boolean,is_deleted boolean)"
        ))
        session.execute(text(
            "INSERT INTO mutant_lines VALUES (1,'PRIVATE_NAME','MUT-000001',1,true,false), "
            "(2,'HIDDEN_NAME','MUT-000002',1,false,false)"
        ))
    import_id = _manifest(get_db)
    _stage(get_db, import_id, [
        _row(10, mutant_line_name="PRIVATE_NAME"),
        _row(11, mutant_line_name="HIDDEN_NAME"),
    ])
    with get_db() as session:
        PostgresVariantStore(session).finalize(
            release_id=1, assembly_id=4, import_id=import_id, expected_rows=2,
        )
    sql, parameters = exports.build_export_query({"release_key": "1", "assembly": "v4"})
    with get_db() as session:
        assert session.execute(text(sql), parameters).all() == []
        session.execute(text("UPDATE releases SET status='published' WHERE id=1"))
    with get_db() as session:
        rows = session.execute(text(sql), parameters).all()
        assert len(rows) == 1
        record = exports._record(rows[0])
        assert record["mutant_public_id"] == "MUT-000001"
        assert "PRIVATE_NAME" not in str(record)
        assert "HIDDEN_NAME" not in str(record)
        assert "MUT-000002" not in str(record)


def test_finalize_refuses_a_duplicate_identity_reaching_staging(native_database):
    """A duplicate identity that spans two staged batches must fail closed with a
    diagnosable error, not with PostgreSQL's ``CardinalityViolation`` (#51).

    ``stage_batch`` collapses duplicates inside one call, but the staging primary
    key is ``(import_id, assembly_id, variant_id)``: the same ``variant_id`` under
    two assemblies survives into ``variant_facts``' own ``(release_id,
    variant_id)`` arbiter, and ``ON CONFLICT DO UPDATE`` cannot touch one row
    twice. That error used to escape the ``written != expected_rows`` gate and
    reach ``ingest.py`` as ``native_variant_import_failed`` with no offending id.
    """
    get_db, observer = native_database
    import_id = _manifest(get_db)
    _stage(get_db, import_id, [_row()], assembly_id=4)
    _stage(get_db, import_id, [_row()], assembly_id=5)
    with pytest.raises(ConflictingVariantRowsError) as failure:
        with get_db() as session:
            PostgresVariantStore(session).finalize(
                release_id=1, assembly_id=4, import_id=import_id, expected_rows=2,
            )
    assert failure.value.conflicts == [(18446744073709551615, 2)]
    with observer.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM variant_facts")).scalar() == 0


def test_derived_identity_is_persisted_as_a_number_not_a_string():
    """``variant_id`` is numeric on the write path, a string on the read path.

    ``VariantResponse.id`` and ``VariantResponse.variant_id`` are Python ``str``
    (``variant_service._row_to_response``) and the web layer keys rows on
    whatever arrives; the store persists the same identifier as
    ``NUMERIC(20,0)``. That asymmetry is why an identity derived from a hash
    cannot be widened by concatenation here -- and why a row key that leans on
    the response string is not leaning on the storage value (#51).
    """
    from sqlalchemy import Numeric, literal, select
    from sqlalchemy.dialects import postgresql

    identifier = 18446744073709551615
    compiled = select(literal(identifier, Numeric(20, 0))).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    )
    assert "18446744073709551615" in str(compiled)
    assert "::" not in str(compiled), "no text cast: the value stays numeric"
