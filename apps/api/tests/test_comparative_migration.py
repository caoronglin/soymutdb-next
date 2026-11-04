"""Migration 0055: comparative-genomics relations, upgrade and downgrade.

The schema is the contract, so these tests assert the *constraints*, not just
the table names: a relationship type outside the vocabulary must be rejected by
the database, not by a client, and a succeeded artifact without an object must
be impossible to store.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0055_homolog_comparative.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("migration_0055", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_after_0054() -> None:
    module = _migration_module()
    assert module.revision == "0055"
    assert module.down_revision == "0054"
    assert module.branch_labels is None
    assert module.depends_on is None


@pytest.fixture
def schema():
    url = os.environ.get("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL is required")
    sync_url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    name = "comparative_" + uuid.uuid4().hex[:10]
    admin = create_engine(sync_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(sync_url, connect_args={"options": f"-csearch_path={name}"})
    try:
        with engine.begin() as connection:
            # Parents the migration's foreign keys point at.
            # The real ``assemblies`` table carries ``UNIQUE (id, release_id)``
            # (migration 0001), which is what makes the composite FK below
            # expressible. Modelling it here keeps the test honest about the
            # constraint the production schema relies on.
            connection.execute(
                text(
                    "CREATE TABLE assemblies ("
                    "  id integer primary key, release_id integer, "
                    "  UNIQUE (id, release_id))"
                )
            )
            connection.execute(text("INSERT INTO assemblies VALUES (1, 7)"))
        _run(engine, "upgrade")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        admin.dispose()


def _run(engine, action: str) -> None:
    """Run one migration hook inside an Alembic operations context.

    ``op`` is a proxy installed by the context manager, so the module can be
    executed exactly as Alembic executes it instead of calling ``upgrade()`` on
    an unbound proxy.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration_module(), action)()


_FAMILY_INSERT = """
INSERT INTO gene_families
    (assembly_id, release_id, level, external_id, name, method, source_name,
     source_version, source_url, source_sha256)
VALUES (1, 7, :level, 'PF00001', 'Family', 'hmmsearch', 'fixture', '1',
        'https://example.org', :sha)
RETURNING id
"""


def test_upgrade_creates_the_three_relations(schema) -> None:
    with schema.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            ).scalars()
        )
    assert {"gene_families", "gene_family_members", "comparative_artifacts"} <= tables


def test_relationship_type_vocabulary_is_enforced_by_the_database(schema) -> None:
    """A typo must fail the write, not reach the portal as a new category."""
    with schema.begin() as connection:
        family_id = connection.execute(
            text(_FAMILY_INSERT), {"level": "gene_family", "sha": "a" * 64}
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO gene_family_members "
                "(family_id, assembly_id, release_id, gene_accession, species, "
                " relationship_type) VALUES (:f, 1, 7, 'G1', 'soybean', 'one_to_one')"
            ),
            {"f": family_id},
        )

    with pytest.raises(IntegrityError):
        with schema.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO gene_family_members "
                    "(family_id, assembly_id, release_id, gene_accession, species, "
                    " relationship_type) VALUES (:f, 1, 7, 'G2', 'soybean', 'related')"
                ),
                {"f": family_id},
            )


def test_confidence_outside_zero_to_one_is_rejected(schema) -> None:
    with schema.begin() as connection:
        family_id = connection.execute(
            text(_FAMILY_INSERT), {"level": "gene_family", "sha": "a" * 64}
        ).scalar_one()

    with pytest.raises(IntegrityError):
        with schema.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO gene_family_members "
                    "(family_id, assembly_id, release_id, gene_accession, species, "
                    " relationship_type, confidence) "
                    "VALUES (:f, 1, 7, 'G1', 'soybean', 'one_to_one', 1.5)"
                ),
                {"f": family_id},
            )


def test_family_scope_is_unique_per_release_and_assembly(schema) -> None:
    with schema.begin() as connection:
        connection.execute(text(_FAMILY_INSERT), {"level": "gene_family", "sha": "a" * 64})

    with pytest.raises(IntegrityError):
        with schema.begin() as connection:
            connection.execute(
                text(_FAMILY_INSERT), {"level": "gene_family", "sha": "b" * 64}
            )


def test_a_succeeded_artifact_cannot_exist_without_an_object(schema) -> None:
    """The row and the object are one claim; a half-written one is unreadable."""
    with pytest.raises(IntegrityError):
        with schema.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO comparative_artifacts "
                    "(job_id, artifact_type, assembly_id, release_id, method, "
                    " input_sha256, state) "
                    "VALUES (gen_random_uuid(), 'msa', 1, 7, 'mafft', :sha, 'succeeded')"
                ),
                {"sha": "b" * 64},
            )

    with schema.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO comparative_artifacts "
                "(job_id, artifact_type, assembly_id, release_id, method, "
                " input_sha256, state, object_key) "
                "VALUES (gen_random_uuid(), 'msa', 1, 7, 'mafft', :sha, 'succeeded', "
                "        'comparative/7/msa/x.txt')"
            ),
            {"sha": "b" * 64},
        )


def test_downgrade_removes_everything_it_added(schema) -> None:
    _run(schema, "downgrade")
    with schema.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            ).scalars()
        )
    assert not {"gene_families", "gene_family_members", "comparative_artifacts"} & tables
    # The parent table the migration depended on must survive the downgrade.
    assert "assemblies" in tables
