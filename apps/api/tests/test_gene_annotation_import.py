"""Parsing contracts and PostgreSQL-backed release-scoped annotation import."""

from __future__ import annotations

import hashlib
from io import StringIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assembly,
    Chromosome,
    Gene,
    GeneAnnotation,
    GeneAnnotationSet,
    Release,
    ReleaseStatus,
)
from app.services import gene_annotation_import_service as import_service
from app.services.gene_annotation_import_service import (
    GeneAnnotationImportError,
    import_gene_annotation_tsv,
    iter_gene_annotation_tsv,
)

pytestmark = pytest.mark.integration


def test_parser_collapses_exact_duplicates_but_preserves_evidence() -> None:
    stream = StringIO(
        "gene_id\tterm_id\tterm_name\tevidence_code\treference\n"
        "Glyma.01G000100\tGO:0008150\tbiological process\tIEA\tPMID:1\n"
        "Glyma.01G000100\tGO:0008150\tbiological process\tIEA\tPMID:1\n"
        "Glyma.01G000100\tGO:0008150\tbiological process\tEXP\tPMID:2\n"
    )

    rows = list(iter_gene_annotation_tsv(stream, ontology="go"))

    assert len(rows) == 2
    assert {row.evidence_code for row in rows} == {"IEA", "EXP"}


@pytest.mark.parametrize(
    ("contents", "ontology", "message"),
    [
        ("gene_id\tterm_id\nG1\tGO:1\n", "go", "missing required columns"),
        (
            "gene_id\tterm_id\tterm_name\nG1\tGO:1\tA\nG2\tGO:1\tB\n",
            "go",
            "conflicting names",
        ),
        (
            "gene_id\tterm_id\tterm_name\tontology\nG1\tGO:1\tA\tkegg\n",
            "go",
            "does not match",
        ),
        (
            "gene_id\tterm_id\tterm_name\tprivate_column\nG1\tGO:1\tA\tx\n",
            "go",
            "unsupported columns",
        ),
    ],
)
def test_parser_rejects_ambiguous_or_unsupported_tsv(
    contents: str, ontology: str, message: str
) -> None:
    with pytest.raises(GeneAnnotationImportError, match=message):
        list(iter_gene_annotation_tsv(StringIO(contents), ontology=ontology))


async def test_import_is_idempotent_atomic_and_release_scoped(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = uuid4().hex[:12]
    release = Release(
        version=f"annotation-{token}",
        name="Annotation import test",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(release)
    await db_session.flush()

    assembly = Assembly(
        name=f"AnnotationTest.{token}",
        version="v5",
        species="Glycine max",
        release_id=release.id,
    )
    db_session.add(assembly)
    await db_session.flush()
    release.assembly_id = assembly.id

    chromosome = Chromosome(
        assembly_id=assembly.id,
        name="Chr01",
        length=100_000,
    )
    db_session.add(chromosome)
    await db_session.flush()
    db_session.add(
        Gene(
            accession="Glyma.01G000100",
            assembly_id=assembly.id,
            chromosome_id=chromosome.id,
            start=1,
            end=100,
            strand="+",
        )
    )
    await db_session.flush()

    contents = (
        "gene_id\tterm_id\tterm_name\tevidence_code\treference\n"
        "Glyma.01G000100\tGO:0008150\tbiological process\tIEA\tPMID:1\n"
    )
    digest = hashlib.sha256(contents.encode()).hexdigest()
    kwargs = {
        "release_id": release.id,
        "assembly_id": assembly.id,
        "ontology": "go",
        "source_name": "Synthetic annotation fixture",
        "source_version": "1",
        "source_url": "https://example.org/annotations/v1",
        "source_sha256": digest,
    }

    imported = await import_gene_annotation_tsv(
        db_session, StringIO(contents), **kwargs
    )
    assert imported.row_count == 1
    assert imported.already_imported is False

    repeated = await import_gene_annotation_tsv(
        db_session, StringIO(contents), **kwargs
    )
    assert repeated.annotation_set_id == imported.annotation_set_id
    assert repeated.already_imported is True

    set_row = await db_session.scalar(
        select(GeneAnnotationSet).where(GeneAnnotationSet.id == imported.annotation_set_id)
    )
    annotation_rows = (
        await db_session.scalars(
            select(GeneAnnotation).where(
                GeneAnnotation.release_id == release.id,
                GeneAnnotation.assembly_id == assembly.id,
            )
        )
    ).all()
    assert set_row is not None
    assert set_row.source_sha256 == digest
    assert len(annotation_rows) == 1

    # Force a batch boundary so a later invalid gene proves savepoint rollback.
    monkeypatch.setattr(import_service, "ANNOTATION_BATCH_SIZE", 1)
    invalid_contents = (
        "gene_id\tterm_id\tterm_name\n"
        "Glyma.01G000100\tGO:0008150\tbiological process\n"
        "Missing.Gene\tGO:0003674\tmolecular function\n"
    )
    invalid_digest = hashlib.sha256(invalid_contents.encode()).hexdigest()
    second_release = Release(
        version=f"annotation-rollback-{token}",
        name="Annotation rollback test",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(second_release)
    await db_session.flush()
    second_assembly = Assembly(
        name=f"AnnotationRollback.{token}",
        version="v5",
        species="Glycine max",
        release_id=second_release.id,
    )
    db_session.add(second_assembly)
    await db_session.flush()
    second_release.assembly_id = second_assembly.id
    second_chromosome = Chromosome(
        assembly_id=second_assembly.id,
        name="Chr01",
        length=100_000,
    )
    db_session.add(second_chromosome)
    await db_session.flush()
    db_session.add(
        Gene(
            accession="Glyma.01G000100",
            assembly_id=second_assembly.id,
            chromosome_id=second_chromosome.id,
            start=1,
            end=100,
            strand="+",
        )
    )
    await db_session.flush()

    with pytest.raises(GeneAnnotationImportError, match="absent from the selected assembly"):
        await import_gene_annotation_tsv(
            db_session,
            StringIO(invalid_contents),
            **{
                **kwargs,
                "release_id": second_release.id,
                "assembly_id": second_assembly.id,
                "source_sha256": invalid_digest,
            },
        )

    rolled_back = await db_session.scalar(
        select(GeneAnnotationSet).where(
            GeneAnnotationSet.release_id == second_release.id,
            GeneAnnotationSet.assembly_id == second_assembly.id,
        )
    )
    assert rolled_back is None
