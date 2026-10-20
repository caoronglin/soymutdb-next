"""Canonical annotation CLI: real savepoints, release guards, and byte provenance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Assembly, Chromosome, Gene, GeneAnnotation, GeneAnnotationSet, Release
from app.models.content import ReleaseStatus
from app.services.gene_annotation_import_service import GeneAnnotationImportError

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "annotation_cli_under_test", ROOT / "apps/api/scripts/import_gene_annotations.py"
)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
CONTENTS = b"gene_id\tterm_id\tterm_name\nG1\tGO:1\tfixture term\n"


@pytest_asyncio.fixture
async def cli_scope(db_session, db_connection, monkeypatch):
    token = uuid4().hex[:12]
    release = Release(version=f"ann-cli-{token}", name="CLI fixture", status="draft")
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(
        name=f"CLI.{token}", version="v5", species="Glycine max", release_id=release.id
    )
    db_session.add(assembly)
    await db_session.flush()
    chromosome = Chromosome(assembly_id=assembly.id, name="chr01", length=1000)
    db_session.add(chromosome)
    await db_session.flush()
    db_session.add(
        Gene(
            accession="G1", assembly_id=assembly.id, chromosome_id=chromosome.id,
            start=1, end=90, strand="+",
        )
    )
    await db_session.commit()  # Releases a savepoint, never commits the fixture's outer tx.
    factory = async_sessionmaker(
        db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    monkeypatch.setattr(cli, "get_engine", lambda: SimpleNamespace(dispose=AsyncMock()))
    return argparse.Namespace(
        release_id=release.id, assembly_id=assembly.id, ontology="go",
        source_name="Synthetic CLI fixture", source_version="1",
        source_url="https://example.org/fixture/v1", dry_run=False,
    ), factory


async def _snapshot(factory, release_id):
    async with factory() as db:
        return await db.scalar(
            select(GeneAnnotationSet).where(GeneAnnotationSet.release_id == release_id)
        )


@pytest.mark.integration
async def test_dry_run_then_commit_and_repeat_preserves_snapshot_identity(cli_scope):
    args, factory = cli_scope
    digest = hashlib.sha256(CONTENTS).hexdigest()
    args.dry_run = True
    preview = await cli._run(args, io.BytesIO(CONTENTS), digest)
    assert preview["dry_run"] is True
    assert preview["row_count"] == 1
    assert await _snapshot(factory, args.release_id) is None
    args.dry_run = False
    imported = await cli._run(args, io.BytesIO(CONTENTS), digest)
    repeated = await cli._run(args, io.BytesIO(CONTENTS), digest)
    assert imported["already_imported"] is False
    assert repeated["already_imported"] is True
    assert repeated["annotation_set_id"] == imported["annotation_set_id"]
    snapshot = await _snapshot(factory, args.release_id)
    assert snapshot.row_count == 1
    async with factory() as db:
        count = await db.scalar(select(func.count()).select_from(GeneAnnotation).where(
            GeneAnnotation.annotation_set_id == snapshot.id
        ))
    assert count == snapshot.row_count


@pytest.mark.integration
@pytest.mark.parametrize("status", [s for s in ReleaseStatus if s != ReleaseStatus.DRAFT])
@pytest.mark.parametrize("existing", [False, True])
async def test_every_non_draft_release_rejects_import(cli_scope, status, existing):
    args, factory = cli_scope
    imported = None
    if existing:
        imported = await cli._run(args, io.BytesIO(CONTENTS), hashlib.sha256(CONTENTS).hexdigest())
    async with factory.begin() as db:
        release = await db.get(Release, args.release_id)
        release.status = status
    with pytest.raises(GeneAnnotationImportError, match="only for draft releases"):
        await cli._run(args, io.BytesIO(CONTENTS), hashlib.sha256(CONTENTS).hexdigest())
    snapshot = await _snapshot(factory, args.release_id)
    if existing:
        assert snapshot.id == imported["annotation_set_id"]
        assert snapshot.source_sha256 == imported["source_sha256"]
    else:
        assert snapshot is None


@pytest.mark.integration
async def test_changed_snapshot_is_rejected_without_replacement(cli_scope):
    args, factory = cli_scope
    first = await cli._run(args, io.BytesIO(CONTENTS), hashlib.sha256(CONTENTS).hexdigest())
    changed = CONTENTS.replace(b"GO:1", b"GO:2")
    with pytest.raises(GeneAnnotationImportError, match="different annotation snapshot"):
        await cli._run(args, io.BytesIO(changed), hashlib.sha256(changed).hexdigest())
    snapshot = await _snapshot(factory, args.release_id)
    assert snapshot.id == first["annotation_set_id"]
    assert snapshot.source_sha256 == hashlib.sha256(CONTENTS).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize("existing", [False, True])
async def test_bytes_changed_after_checksum_roll_back_even_on_idempotent_path(cli_scope, existing):
    args, factory = cli_scope
    digest = hashlib.sha256(CONTENTS).hexdigest()
    if existing:
        await cli._run(args, io.BytesIO(CONTENTS), digest)
    changed = CONTENTS.replace(b"GO:1", b"GO:2")
    with pytest.raises(GeneAnnotationImportError, match="changed between checksum and import"):
        await cli._run(args, io.BytesIO(changed), digest)
    snapshot = await _snapshot(factory, args.release_id)
    if existing:
        assert snapshot.source_sha256 == digest
    else:
        assert snapshot is None


@pytest.mark.integration
async def test_idempotent_import_rejects_corrupted_row_count(cli_scope):
    args, factory = cli_scope
    digest = hashlib.sha256(CONTENTS).hexdigest()
    first = await cli._run(args, io.BytesIO(CONTENTS), digest)
    async with factory.begin() as db:
        snapshot = await db.get(GeneAnnotationSet, first["annotation_set_id"])
        snapshot.row_count = 2
    with pytest.raises(GeneAnnotationImportError, match="row_count does not match"):
        await cli._run(args, io.BytesIO(CONTENTS), digest)


@pytest.mark.integration
async def test_unknown_gene_late_batch_rolls_back_and_does_not_skip(cli_scope, monkeypatch):
    from app.services import gene_annotation_import_service

    args, factory = cli_scope
    monkeypatch.setattr(gene_annotation_import_service, "ANNOTATION_BATCH_SIZE", 1)
    async with factory.begin() as db:
        other = Assembly(
            name=f"Other.{uuid4().hex[:12]}", version="v4", species="Glycine max",
            release_id=args.release_id,
        )
        db.add(other)
        await db.flush()
        chromosome = Chromosome(assembly_id=other.id, name="chr01", length=1000)
        db.add(chromosome)
        await db.flush()
        db.add(Gene(
            accession="OTHER_ASSEMBLY_GENE", assembly_id=other.id,
            chromosome_id=chromosome.id, start=1, end=90, strand="+",
        ))
    unknown = CONTENTS + b"OTHER_ASSEMBLY_GENE\tGO:2\tfixture term two\n"
    with pytest.raises(GeneAnnotationImportError, match="absent from the selected assembly"):
        await cli._run(args, io.BytesIO(unknown), hashlib.sha256(unknown).hexdigest())
    assert await _snapshot(factory, args.release_id) is None


@pytest.mark.integration
async def test_assembly_bound_to_another_release_is_rejected(cli_scope):
    args, factory = cli_scope
    async with factory.begin() as db:
        other = Release(version=f"other-{uuid4().hex[:12]}", name="Other", status="draft")
        db.add(other)
        await db.flush()
        args.release_id = other.id
    with pytest.raises(GeneAnnotationImportError, match="does not belong to release"):
        await cli._run(args, io.BytesIO(CONTENTS), hashlib.sha256(CONTENTS).hexdigest())
    assert await _snapshot(factory, args.release_id) is None


def test_hashing_reader_covers_bom_crlf_and_buffer_boundaries():
    contents = b"\xef\xbb\xbf" + (CONTENTS.replace(b"\n", b"\r\n") * 500)
    source = io.BytesIO(contents)
    digest = cli._sha256_file(source)
    assert source.tell() == 0
    reader = cli._HashingReader(source)
    with io.TextIOWrapper(io.BufferedReader(reader), encoding="utf-8-sig", newline="") as stream:
        while stream.read(7):
            pass
    assert reader.hexdigest == digest == hashlib.sha256(contents).hexdigest()


def test_root_cli_uses_canonical_argument_contract():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/import_annotations.py"), "--help"],
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert "--sha256" in result.stdout
    assert "--on-unknown-genes" not in result.stdout
    assert "--declared-sha256" not in result.stdout


def test_cli_rejects_declared_digest_before_opening_database(tmp_path, monkeypatch):
    source = tmp_path / "fixture.tsv"
    source.write_bytes(CONTENTS)
    monkeypatch.setattr(cli, "get_engine", lambda: pytest.fail("digest guard reached DB"))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            str(source), "--release-id", "1", "--assembly-id", "1", "--ontology", "go",
            "--source-name", "Fixture", "--source-version", "1",
            "--source-url", "https://example.org/v1", "--sha256", "0" * 64,
        ])
    assert exc.value.code == 2
