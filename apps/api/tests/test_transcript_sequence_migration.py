"""0060 transcript residue store: additive upgrade, reversible downgrade.

The residue store is a new table with no data migration, so both directions must
be symmetric. Two layers, because each catches what the other cannot:

* offline ``alembic --sql``: the emitted DDL, which is what a review reads;
* a real PostgreSQL server (``SOYMUTDB_TEST_DATABASE_URL``): ``CREATE TABLE`` can
  compile as text and still fail against a live catalogue -- a check constraint
  naming a function, a foreign key to a table created by an earlier revision, or
  a downgrade that drops an object the upgrade did not create.

The predicate functions (``sha256 ~ ...``, ``char_length``) are exactly the kind
of DDL that only a live server validates, so the roundtrip also inserts a lying
row and asserts the database refuses it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0060_transcript_sequences.py"
SCRATCH_DATABASE = "soymutdb_residues_0060_rt"
TABLE = "transcript_sequences"
CHAINS = (
    "ck_transcript_sequences_molecule",
    "ck_transcript_sequences_length",
    "ck_transcript_sequences_sha256_shape",
)


def _server_url() -> str | None:
    url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql+asyncpg://"):
        return None
    return url


def _alembic_environment() -> dict[str, str]:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(workspace_root / "packages/jobs-py/src"),
            str(API_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    return environment


def _offline_alembic(command: str, revision_range: str) -> str:
    environment = _alembic_environment()
    environment["SOYMUTDB_DATABASE_URL"] = "postgresql+asyncpg://offline:offline@localhost/offline"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, revision_range, "--sql"],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _alembic(command: str, revision: str, url: str) -> None:
    environment = _alembic_environment()
    environment["SOYMUTDB_DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, revision],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_0060_offline_upgrade_creates_the_store_and_its_constraints() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0059:0060")

    assert f"CREATE TABLE {TABLE}" in sql
    assert "transcript_id VARCHAR(64) NOT NULL" in sql
    assert "molecule VARCHAR(16) NOT NULL" in sql
    assert "sequence TEXT NOT NULL" in sql
    assert "FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE" in sql
    assert "PRIMARY KEY (transcript_id, molecule)" in sql
    for constraint in CHAINS:
        assert constraint in sql
    # Additive only: no existing table is rewritten.
    assert "ALTER TABLE transcripts" not in sql


def test_0060_offline_downgrade_drops_only_the_new_table() -> None:
    sql = _offline_alembic("downgrade", "0060:0059")
    assert f"DROP TABLE {TABLE}" in sql
    assert "DROP TABLE transcripts" not in sql


async def _create_database(server_url: str) -> bool:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = server_url.rpartition("/")[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE}")
            await connection.exec_driver_sql(f"CREATE DATABASE {SCRATCH_DATABASE}")
    except Exception:
        return False
    finally:
        await engine.dispose()
    return True


async def _drop_database(server_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = server_url.rpartition("/")[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE} WITH (FORCE)"
            )
    except Exception:
        pass
    finally:
        await engine.dispose()


async def _table_exists(url: str) -> bool:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            found = await connection.exec_driver_sql(
                "SELECT to_regclass('public." + TABLE + "') IS NOT NULL"
            )
            return bool(found.scalar())
    finally:
        await engine.dispose()


async def _constraint_names(url: str) -> list[str]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.exec_driver_sql(
                "SELECT conname FROM pg_constraint WHERE conrelid = "
                "'public." + TABLE + "'::regclass AND contype = 'c'"
            )
            return sorted(row[0] for row in rows)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_0060_upgrade_and_downgrade_against_a_real_postgres() -> None:
    server_url = _server_url()
    if server_url is None:
        pytest.skip("set SOYMUTDB_TEST_DATABASE_URL to a PostgreSQL server")
    if not await _create_database(server_url):
        pytest.skip("could not create the scratch database")
    url = server_url.rpartition("/")[0] + "/" + SCRATCH_DATABASE
    try:
        _alembic("upgrade", "0059", url)
        assert await _table_exists(url) is False

        _alembic("upgrade", "head", url)
        assert await _table_exists(url) is True
        assert await _constraint_names(url) == sorted(CHAINS)

        # The database, not only the importer, refuses a row whose length
        # disagrees with the residues it publishes -- and accepts one that agrees.
        # The parent rows are written through the models so the test exercises
        # the migrated DDL, not a second copy of it.
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.models import (
            Assembly,
            Chromosome,
            Gene,
            Release,
            ReleaseStatus,
            Transcript,
            TranscriptSequence,
        )

        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                release = Release(
                    version="shape-0060", name="Shape 0060", status=ReleaseStatus.DRAFT
                )
                session.add(release)
                await session.flush()
                assembly = Assembly(
                    name="Shape.a6.0060",
                    version="a6",
                    species="Glycine max",
                    release_id=release.id,
                )
                session.add(assembly)
                await session.flush()
                chromosome = Chromosome(assembly_id=assembly.id, name="Gm01", length=1_000)
                session.add(chromosome)
                await session.flush()
                gene = Gene(
                    accession="Glyma.99G000001",
                    assembly_id=assembly.id,
                    chromosome_id=chromosome.id,
                    start=1,
                    end=100,
                    strand="+",
                )
                session.add(gene)
                await session.flush()
                session.add(
                    Transcript(
                        id="shape-tx",
                        gene_id=gene.gene_pk,
                        start=1,
                        end=100,
                        strand="+",
                    )
                )
                await session.flush()

                publisher = hashlib.sha256(b"ACGT").hexdigest()
                session.add(
                    TranscriptSequence(
                        transcript_id="shape-tx",
                        molecule="cds",
                        length=4,
                        sha256=publisher,
                        sequence="ACGT",
                    )
                )
                await session.flush()

                session.add(
                    TranscriptSequence(
                        transcript_id="shape-tx",
                        molecule="protein",
                        length=99,
                        sha256=publisher,
                        sequence="MKV",
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
        finally:
            await engine.dispose()

        _alembic("downgrade", "0059", url)
        assert await _table_exists(url) is False

        _alembic("upgrade", "head", url)
        assert await _table_exists(url) is True
    finally:
        await _drop_database(server_url)
