"""Comparative-genomics reads and artifact dispatch.

The one rule this module exists to enforce: **similarity is not orthology**.

A BLAST hit says two sequences align. It does not say the genes are orthologs,
paralogs, or related at all in the lineage sense -- a top hit can be a
paralog, a pseudogene, or a repeat. Nothing in this module derives a
relationship from a hit count, an e-value or an identity percentage: the
relationship type comes from the imported row, and a row that does not state
one does not become an ortholog by being the best hit.

Reads are always bound to the resolved release and to an explicit assembly.
Absent data is reported as ``no_data``; it is never rounded to an empty list.
"""

from __future__ import annotations

import hashlib
import uuid
from itertools import groupby

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.comparative import (
    ArtifactType,
    ComparativeArtifact,
    ComparativeArtifactState,
    GeneFamily,
    GeneFamilyMember,
    RelationshipType,
)
from ..models.genomic import Assembly, Gene
from ..models.homolog import GeneHomolog
from ..schemas.comparative import (
    ArtifactResponse,
    FamilyDetailResponse,
    FamilyListResponse,
    FamilyMemberResponse,
    FamilyResponse,
    MemberComparisonResponse,
    OrthologRecord,
    OrthologResponse,
    SpeciesCoverageResponse,
)
from ..schemas.gene_evidence import EvidenceTag
from .release_context import ReleaseContext

#: Artifact methods the worker may run. Kept here (not in the worker) because
#: the API refuses an unknown method before it reaches the queue; the worker
#: re-checks against the same tuple.
ALLOWED_ARTIFACT_METHODS: tuple[str, ...] = ("mafft", "muscle", "iqtree", "fasttree")

#: Bucket name for comparative artifacts. Objects are written by the worker.
ARTIFACT_BUCKET_PREFIX = "comparative"


def family_evidence(family: GeneFamily) -> EvidenceTag:
    """Evidence class of a family grouping.

    A family is a computational grouping produced by a pipeline; it is
    ``predicted`` unless the source explicitly says it was curated, which the
    import format does not express today. It is never ``experimental``: no
    experiment establishes a gene family.
    """
    del family
    return EvidenceTag(kind="predicted", source="gene_families")


def homology_evidence(source: str | None) -> EvidenceTag:
    """Evidence class of one homolog row.

    Always ``transferred``: the statement is about another locus, transferred
    here by homology. ``source`` names where the row came from, or states that
    the import did not say.
    """
    if source:
        return EvidenceTag(kind="transferred", source=source[:256])
    return EvidenceTag(kind="transferred", source="homolog_import")


def relationship_type_for_membership(members: list[GeneFamilyMember]) -> str:
    """Derive the family-level relationship type from its member rows.

    The members are authoritative: if they disagree the family is described as
    ``many_to_many``, which under-claims rather than over-claims a pairing. This
    is a summary of stated rows, not an inference about biology.
    """
    stated = {member.relationship_type for member in members}
    if len(stated) == 1:
        return stated.pop()
    return RelationshipType.MANY_TO_MANY.value


def relationship_type_for_orthologs(
    rows: list[GeneHomolog],
) -> str:
    """Classify a gene's ortholog set without pretending to pair them.

    ``gene_homologs`` has no pairing column: it records that a gene has a
    homolog in another species. A single row in a species is reported as
    ``one_to_one`` only when the source recorded exactly one counterpart there;
    several counterparts in the same species are ``one_to_many``; a species
    represented more than once across the set is ``many_to_many``.
    """
    by_species: dict[str, int] = {}
    for row in rows:
        by_species[row.homolog_species] = by_species.get(row.homolog_species, 0) + 1
    if not by_species:
        return RelationshipType.MANY_TO_MANY.value
    if all(count == 1 for count in by_species.values()):
        return RelationshipType.ONE_TO_ONE.value
    if len(by_species) == 1:
        return RelationshipType.ONE_TO_MANY.value
    return RelationshipType.MANY_TO_MANY.value


def input_fingerprint(member_ids: list[str]) -> str:
    """Stable hash of the ordered member set an artifact is computed from.

    Order matters: an alignment is a function of its input order, so two
    requests with the same members in a different order are different inputs
    and must not silently share an artifact.
    """
    digest = hashlib.sha256()
    for member in member_ids:
        digest.update(member.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


class ComparativeService:
    """Reads over family/orthology data; dispatch for derived artifacts."""

    # -- families ---------------------------------------------------------

    async def list_families(
        self,
        db: AsyncSession,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
        level: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> FamilyListResponse:
        conditions = [GeneFamily.release_id == release_context.release_id]
        scoped_assembly = assembly_id if assembly_id is not None else release_context.assembly_id
        if scoped_assembly is not None:
            conditions.append(GeneFamily.assembly_id == scoped_assembly)
        if level is not None:
            if level not in {"gene_family", "gene_subfamily"}:
                raise ValidationError(f"Unknown family level {level!r}")
            conditions.append(GeneFamily.level == level)
        where = and_(*conditions)

        total = int(await db.scalar(select(func.count()).select_from(GeneFamily).where(where)) or 0)
        result = await db.execute(
            select(GeneFamily, func.count(GeneFamilyMember.id))
            .outerjoin(
                GeneFamilyMember,
                and_(
                    GeneFamilyMember.family_id == GeneFamily.id,
                    GeneFamilyMember.release_id == GeneFamily.release_id,
                ),
            )
            .where(where)
            .group_by(GeneFamily.id)
            .order_by(GeneFamily.external_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            self._family_response(family, int(member_count or 0))
            for family, member_count in result.all()
        ]
        return FamilyListResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_family(
        self,
        db: AsyncSession,
        family_id: int,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> FamilyDetailResponse:
        family = await self._scoped_family(
            db, family_id, release_context=release_context, assembly_id=assembly_id
        )
        members = await self._members(db, family)
        coverage = self._coverage(members)
        base = self._family_response(family, len(members))
        return FamilyDetailResponse(
            **base.model_dump(),
            members=[self._member_response(member) for member in members],
            coverage=coverage,
            relationship_types=[relationship_type_for_membership(members)],
        )

    async def compare_families(
        self,
        db: AsyncSession,
        left_id: int,
        right_id: int,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> MemberComparisonResponse:
        left = await self._scoped_family(
            db, left_id, release_context=release_context, assembly_id=assembly_id
        )
        right = await self._scoped_family(
            db, right_id, release_context=release_context, assembly_id=assembly_id
        )
        left_members = await self._members(db, left)
        right_members = await self._members(db, right)
        left_by_gene = {member.gene_accession: member for member in left_members}
        right_by_gene = {member.gene_accession: member for member in right_members}
        shared = [left_by_gene[gene] for gene in left_by_gene.keys() & right_by_gene.keys()]
        only_left = [left_by_gene[gene] for gene in left_by_gene.keys() - right_by_gene.keys()]
        only_right = [right_by_gene[gene] for gene in right_by_gene.keys() - left_by_gene.keys()]
        # Coverage spans both sides so a species present in only one family is
        # visible as such rather than disappearing from the comparison.
        species = sorted({member.species for member in (*left_members, *right_members)})
        coverage = self._coverage_for_species(species, [*left_members, *right_members])
        return MemberComparisonResponse(
            left=self._family_response(left, len(left_members)),
            right=self._family_response(right, len(right_members)),
            shared=[self._member_response(m) for m in shared],
            only_left=[self._member_response(m) for m in only_left],
            only_right=[self._member_response(m) for m in only_right],
            coverage=coverage,
        )

    # -- orthologs --------------------------------------------------------

    async def get_orthologs(
        self,
        db: AsyncSession,
        gene_accession: str,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
        homolog_type: str | None = None,
    ) -> OrthologResponse:
        gene = await self._scoped_gene(
            db, gene_accession, release_context=release_context, assembly_id=assembly_id
        )
        conditions = [GeneHomolog.gene_id == gene.gene_pk]
        if homolog_type is not None:
            if homolog_type not in {"ortholog", "paralog"}:
                raise ValidationError(f"Unknown homolog type {homolog_type!r}")
            conditions.append(GeneHomolog.homolog_type == homolog_type)
        result = await db.execute(
            select(GeneHomolog)
            .where(and_(*conditions))
            .order_by(GeneHomolog.homolog_species, GeneHomolog.homolog_gene_id)
        )
        rows = list(result.scalars().all())
        if not rows:
            return OrthologResponse(
                gene_id=gene.accession,
                assembly_id=gene.assembly_id,
                release_id=release_context.release_id,
                state="no_data",
                records=[],
            )
        relationship = relationship_type_for_orthologs(rows)
        records = [
            OrthologRecord(
                gene_accession=gene.accession,
                counterpart_species=row.homolog_species,
                counterpart_gene_id=row.homolog_gene_id,
                homolog_type=row.homolog_type,  # type: ignore[arg-type]
                relationship_type=relationship,  # type: ignore[arg-type]
                # The import format states no method; "blast" would be an
                # invented claim about how the row was produced.
                method=None,
                source=row.source or None,
                release_id=release_context.release_id,
                confidence=None,
                evidence=homology_evidence(row.source),
            )
            for row in rows
        ]
        return OrthologResponse(
            gene_id=gene.accession,
            assembly_id=gene.assembly_id,
            release_id=release_context.release_id,
            state="available",
            records=records,
        )

    # -- artifacts --------------------------------------------------------

    async def request_artifact(
        self,
        db: AsyncSession,
        *,
        family_id: int,
        artifact_type: str,
        method: str,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> tuple[ComparativeArtifact, list[str]]:
        """Record an artifact job for a family, frozen against its members.

        Returns the pending row plus the ordered member ids the worker must
        align. Nothing is computed here: the row and its outbox event are
        committed by the route, so a broker outage cannot lose the request and a
        re-delivery cannot produce two artifacts for one job.
        """
        if artifact_type not in {ArtifactType.MSA.value, ArtifactType.TREE.value}:
            raise ValidationError(f"Unknown artifact type {artifact_type!r}")
        if method not in ALLOWED_ARTIFACT_METHODS:
            raise ValidationError(
                f"Unknown artifact method {method!r}; "
                f"allowed: {', '.join(ALLOWED_ARTIFACT_METHODS)}"
            )
        family = await self._scoped_family(
            db, family_id, release_context=release_context, assembly_id=assembly_id
        )
        members = await self._members(db, family)
        if not members:
            raise ValidationError(
                "A family with no members cannot be aligned; import its members first",
                details={"code": "family_has_no_members"},
            )
        member_ids = [member.gene_accession for member in members]
        artifact = ComparativeArtifact(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            artifact_type=artifact_type,
            family_id=family.id,
            assembly_id=family.assembly_id,
            release_id=family.release_id,
            method=method,
            input_sha256=input_fingerprint(member_ids),
            input_member_ids=member_ids,
            state=ComparativeArtifactState.PENDING.value,
        )
        db.add(artifact)
        await db.flush()
        return artifact, member_ids

    async def get_artifact(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        *,
        release_context: ReleaseContext,
    ) -> ArtifactResponse:
        result = await db.execute(
            select(ComparativeArtifact).where(
                ComparativeArtifact.job_id == job_id,
                ComparativeArtifact.release_id == release_context.release_id,
            )
        )
        artifact = result.scalar_one_or_none()
        if artifact is None:
            raise NotFoundError(f"Comparative artifact {job_id} not found")
        return ArtifactResponse(
            artifact_type=artifact.artifact_type,  # type: ignore[arg-type]
            job_id=artifact.job_id,
            state=artifact.state,  # type: ignore[arg-type]
            method=artifact.method,
            input_sha256=artifact.input_sha256,
            input_member_ids=list(artifact.input_member_ids or []),
            # The download URL is minted by the route (pre-signing needs the
            # object store), never embedded in the stored row.
            download_url=None,
            error_message=artifact.error_message,
            created_at=artifact.created_at,
            completed_at=artifact.completed_at,
        )

    async def artifact_object_key(
        self, db: AsyncSession, job_id: uuid.UUID, *, release_id: int
    ) -> str | None:
        """Object key of a succeeded artifact, or ``None`` while it is pending."""
        result = await db.execute(
            select(ComparativeArtifact.object_key).where(
                ComparativeArtifact.job_id == job_id,
                ComparativeArtifact.release_id == release_id,
            )
        )
        return result.scalar_one_or_none()

    # -- internals --------------------------------------------------------

    async def _scoped_family(
        self,
        db: AsyncSession,
        family_id: int,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None,
    ) -> GeneFamily:
        conditions = [
            GeneFamily.id == family_id,
            GeneFamily.release_id == release_context.release_id,
        ]
        scoped_assembly = assembly_id if assembly_id is not None else release_context.assembly_id
        if scoped_assembly is not None:
            conditions.append(GeneFamily.assembly_id == scoped_assembly)
        result = await db.execute(select(GeneFamily).where(and_(*conditions)))
        family = result.scalar_one_or_none()
        if family is None:
            raise NotFoundError(f"Gene family {family_id} not found in this release")
        return family

    async def _scoped_gene(
        self,
        db: AsyncSession,
        accession: str,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None,
    ) -> Gene:
        conditions = [
            Gene.accession == accession,
            Assembly.release_id == release_context.release_id,
        ]
        # An explicit ``assembly_id`` wins; otherwise the resolved release
        # context's own assembly applies. Only a request with neither is
        # ambiguous, and that case errors instead of picking a version.
        scoped_assembly = assembly_id if assembly_id is not None else release_context.assembly_id
        if scoped_assembly is not None:
            conditions.append(Gene.assembly_id == scoped_assembly)
        result = await db.execute(
            select(Gene).join(Assembly, Gene.assembly_id == Assembly.id).where(and_(*conditions))
        )
        genes = list(result.scalars().all())
        if not genes:
            raise NotFoundError(f"Gene {accession} not found in this release")
        if len(genes) > 1:
            raise ValidationError(
                f"Gene {accession} exists in multiple assemblies; supply assembly_id",
                details={
                    "code": "ambiguous_assembly",
                    "assemblies": [
                        {"assembly_id": gene.assembly_id, "accession": gene.accession}
                        for gene in genes
                    ],
                },
            )
        return genes[0]

    async def _members(self, db: AsyncSession, family: GeneFamily) -> list[GeneFamilyMember]:
        result = await db.execute(
            select(GeneFamilyMember)
            .where(
                GeneFamilyMember.family_id == family.id,
                GeneFamilyMember.release_id == family.release_id,
                GeneFamilyMember.assembly_id == family.assembly_id,
            )
            .order_by(GeneFamilyMember.species, GeneFamilyMember.gene_accession)
        )
        return list(result.scalars().all())

    @staticmethod
    def _coverage(members: list[GeneFamilyMember]) -> list[SpeciesCoverageResponse]:
        species = [member.species for member in members]
        return ComparativeService._coverage_for_species(sorted(set(species)), members)

    @staticmethod
    def _coverage_for_species(
        species: list[str], members: list[GeneFamilyMember]
    ) -> list[SpeciesCoverageResponse]:
        counts: dict[str, int] = {}
        for key, group in groupby(
            sorted(member.species for member in members), key=lambda value: value
        ):
            counts[key] = len(list(group))
        return [
            SpeciesCoverageResponse(
                species=name,
                state="available" if counts.get(name) else "no_data",
                # ``None`` -- not 0 -- when the species contributed nothing:
                # absence of a row is not a measured zero.
                member_count=counts.get(name),
            )
            for name in species
        ]

    @staticmethod
    def _family_response(family: GeneFamily, member_count: int) -> FamilyResponse:
        return FamilyResponse(
            family_id=family.id,
            level=family.level,  # type: ignore[arg-type]
            external_id=family.external_id,
            name=family.name,
            method=family.method,
            method_version=family.method_version,
            source_name=family.source_name,
            source_version=family.source_version,
            source_url=family.source_url,
            release_id=family.release_id,
            assembly_id=family.assembly_id,
            member_count=member_count,
            evidence=family_evidence(family),
        )

    @staticmethod
    def _member_response(member: GeneFamilyMember) -> FamilyMemberResponse:
        return FamilyMemberResponse(
            gene_accession=member.gene_accession,
            species=member.species,
            relationship_type=member.relationship_type,  # type: ignore[arg-type]
            method=member.method,
            confidence=member.confidence,
            evidence=member.evidence,
        )


__all__ = [
    "ALLOWED_ARTIFACT_METHODS",
    "ARTIFACT_BUCKET_PREFIX",
    "ComparativeService",
    "family_evidence",
    "homology_evidence",
    "input_fingerprint",
    "relationship_type_for_membership",
    "relationship_type_for_orthologs",
]
