"""R03: assembly-scoped gene_pk resolution against real PostgreSQL.

v4/v5 are separate namespaces: the same accession legitimately exists in
both. These tests prove that the worker resolves gene identity per assembly,
rejects unknown/ambiguous assemblies loudly (no silent default), and keeps
cross-assembly ambiguous accessions out of unscoped maps instead of guessing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from soymutdb_worker.tasks.gene_resolution import (
    AssemblyResolutionError,
    resolve_gene_pk_map,
)

# Reuse the shared integration fixture (Alembic-upgraded disposable PG).
from tests.test_module_tsv_postgres_integration import (  # noqa: F401
    postgres_engine,
)


def _seed_cross_assembly_genes(engine) -> dict[str, int]:
    """Seed v4 + v5 assemblies sharing one accession; return mapping."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO assemblies (id, name, species, version, is_default) "
                "VALUES (9001, 'Glycine_max_v4', 'Glycine max', 'v4', false), "
                "       (9002, 'Glycine_max_v5', 'Glycine max', 'v5', false)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chromosomes (id, assembly_id, name, length, \"order\") "
                "VALUES (9001, 9001, 'chr01', 100000, 0), "
                "       (9002, 9002, 'chr01', 100000, 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO genes "
                "  (gene_pk, accession, assembly_id, chromosome_id, biotype, "
                "   start, \"end\", strand) "
                "VALUES "
                "  (900101, 'Glyma.01G000100', 9001, 9001, 'protein_coding', "
                "   1000, 2000, '+'), "
                "  (900201, 'Glyma.01G000100', 9002, 9002, 'protein_coding', "
                "   3000, 4000, '+'), "
                "  (900102, 'Glyma.01G000200', 9001, 9001, 'protein_coding', "
                "   5000, 6000, '-')"
            )
        )
    return {"v4": 900101, "v5": 900201}


def _cleanup(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("genes"):
        return
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM genes WHERE gene_pk IN (900101, 900102, 900201)")
        )
        connection.execute(
            text("DELETE FROM chromosomes WHERE id IN (9001, 9002)")
        )
        connection.execute(text("DELETE FROM assemblies WHERE id IN (9001, 9002)"))


@pytest.fixture(scope="module")
def cross_assembly_engine(postgres_engine) -> Iterator[object]:
    seeded = _seed_cross_assembly_genes(postgres_engine)
    try:
        yield postgres_engine
    finally:
        _cleanup(postgres_engine)
        del seeded


def test_same_accession_resolves_per_assembly(cross_assembly_engine):
    """R03: same accession across v4/v5 resolves to each assembly's gene_pk."""
    factory = sessionmaker(bind=cross_assembly_engine, expire_on_commit=False)
    with factory() as session:
        v4_map = resolve_gene_pk_map(session, assembly="Glycine_max_v4")
        v5_map = resolve_gene_pk_map(session, assembly="v5")

    assert v4_map["Glyma.01G000100"] == 900101
    assert v5_map["Glyma.01G000100"] == 900201
    # The v5-only view must not contain v4-only accessions.
    assert "Glyma.01G000200" not in v5_map
    assert v5_map["Glyma.01G000100"] != v4_map["Glyma.01G000100"]


def test_unscoped_resolution_excludes_cross_assembly_ambiguous(
    cross_assembly_engine,
):
    """A bare accession shared by v4/v5 is ambiguous and must not be guessed."""
    factory = sessionmaker(bind=cross_assembly_engine, expire_on_commit=False)
    with factory() as session:
        unscoped = resolve_gene_pk_map(session)

    assert "Glyma.01G000100" not in unscoped
    assert unscoped["Glyma.01G000200"] == 900102


def test_unknown_assembly_fails_loudly(cross_assembly_engine):
    factory = sessionmaker(bind=cross_assembly_engine, expire_on_commit=False)
    with factory() as session:
        with pytest.raises(AssemblyResolutionError, match="unknown assembly"):
            resolve_gene_pk_map(session, assembly="Wm82.v99")


def test_ambiguous_assembly_string_fails_loudly(cross_assembly_engine):
    """A string matching several assemblies never falls back to a default."""
    with cross_assembly_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO assemblies (id, name, species, version, is_default) "
                "VALUES (9003, 'v4-clone', 'Glycine max', 'v4', false)"
            )
        )
    try:
        factory = sessionmaker(bind=cross_assembly_engine, expire_on_commit=False)
        with factory() as session:
            with pytest.raises(AssemblyResolutionError, match="ambiguous assembly"):
                resolve_gene_pk_map(session, assembly="v4")
    finally:
        with cross_assembly_engine.begin() as connection:
            connection.execute(text("DELETE FROM assemblies WHERE id = 9003"))
