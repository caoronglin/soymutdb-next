"""Resolve protein/transcript BLAST subjects to assembly-scoped gene loci.

Biological correctness red line: ``blastp``/``blastx``/``tblastn`` subject
coordinates are amino-acid (or translated) positions along a *sequence*, not
genomic coordinates. They must never be used to build a genome-browser link.
A link is produced only after an **explicit, provenance-bearing relation** maps
the subject identifier to a gene record in the searched assembly and release.

Accepted subject forms, all scoped by ``assembly_id`` and ``release_id``:

1. exact gene accession (``genes.accession``);
2. exact transcript id (``transcripts.id`` -> ``genes.gene_pk``);
3. exact, sourced alias (``gene_aliases.alias`` -> ``genes.gene_pk``).

Every one of the three joins ``genes`` and filters ``genes.assembly_id``
itself. A transcript id or an alias is a plain string that the same value can
carry in v4 and v5, so "the gene row I found is in the right assembly" cannot
be established afterwards: the resolution would first collect both namespaces
and only then rely on one of them being absent.

No suffix stripping, fuzzy matching, coordinate coincidence or string
similarity. Ambiguous matches are reported ``unresolved`` with a reason; they
never silently pick one. Nothing here invents a cross-assembly (v4/v5)
equivalence. A missing relation is a first-class result, not a zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from soymutdb_worker.tables import (
    assemblies,
    chromosomes,
    gene_aliases,
    genes,
    transcripts,
)

#: Programs whose subject coordinates are NOT genomic and require resolution.
PROTEIN_SUBJECT_PROGRAMS = frozenset({"blastp", "blastx", "tblastn"})


@dataclass(frozen=True)
class GeneLocus:
    gene_id: str
    chromosome: str
    start: int
    end: int
    strand: str
    assembly_id: int
    release_id: int


def _unresolved(reason: str) -> dict[str, Any]:
    return {"status": "unresolved", "reason": reason}


class BlastGenomeResolver:
    """Batch-resolve subject IDs through explicit, assembly-scoped relations."""

    def __init__(self, session: Any, *, assembly_id: int, release_id: int) -> None:
        self._session = session
        self.assembly_id = int(assembly_id)
        self.release_id = int(release_id)
        self._scope = self._check_scope()

    def _check_scope(self) -> bool:
        """Refuse to resolve in an assembly that is not in this release."""
        row = self._session.execute(
            select(assemblies.c.id).where(
                assemblies.c.id == self.assembly_id,
                assemblies.c.release_id == self.release_id,
            )
        ).first()
        return row is not None

    def _gene_rows(self, gene_pks: set[int]) -> dict[int, GeneLocus]:
        """Load loci for *gene_pks*, scoped by assembly on BOTH tables.

        ``genes.assembly_id`` and ``chromosomes.assembly_id`` are joined
        separately: two assemblies can reuse chromosome names, so the join key
        alone cannot prove the chromosome belongs to the searched assembly.
        """
        if not gene_pks or not self._scope:
            return {}
        result: dict[int, GeneLocus] = {}
        statement = (
            select(
                genes.c.gene_pk,
                genes.c.accession,
                genes.c.chromosome_id,
                genes.c.start,
                genes.c.end,
                genes.c.strand,
                chromosomes.c.name,
            )
            .select_from(
                genes.join(
                    chromosomes,
                    (genes.c.chromosome_id == chromosomes.c.id)
                    & (chromosomes.c.assembly_id == genes.c.assembly_id),
                )
            )
            .where(
                genes.c.gene_pk.in_(sorted(gene_pks)),
                genes.c.assembly_id == self.assembly_id,
            )
        )
        for (
            gene_pk, accession, chromosome_id, start, end, strand, chromosome_name,
        ) in self._rows(statement):
            if (
                chromosome_id is None or start is None or end is None
                or start < 1 or end < start or not chromosome_name
            ):
                continue
            result[int(gene_pk)] = GeneLocus(
                gene_id=str(accession),
                chromosome=str(chromosome_name),
                start=int(start),
                end=int(end),
                strand=str(strand or "+"),
                assembly_id=self.assembly_id,
                release_id=self.release_id,
            )
        return result

    def _rows(self, statement: Any) -> list[tuple[Any, ...]]:
        """Execute a two-or-more-column select and return plain tuples."""
        return [tuple(row) for row in self._session.execute(statement).all()]

    def resolve(self, subject_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return a resolution record per subject ID (never omitted).

        The value is either ``{"status": "resolved", ...locus}`` or
        ``{"status": "unresolved", "reason": ...}``. No amino-acid coordinate
        is ever copied into a result.
        """
        unique = sorted({str(value).strip() for value in subject_ids if str(value).strip()})
        output: dict[str, dict[str, Any]] = {
            key: _unresolved("empty_subject_id") if not key else _unresolved("no_relation")
            for key in unique
        }
        if not self._scope:
            return {key: _unresolved("assembly_outside_release") for key in unique}
        if not unique:
            return output

        gene_pks: set[int] = set()
        owner: dict[str, set[int]] = {key: set() for key in unique}

        # (1) exact gene accession in this assembly.
        for key, gene_pk in self._rows(
            select(genes.c.accession, genes.c.gene_pk).where(
                genes.c.accession.in_(unique),
                genes.c.assembly_id == self.assembly_id,
            )
        ):
            owner[str(key)].add(int(gene_pk))
            gene_pks.add(int(gene_pk))

        # (2) exact transcript id -> gene_pk, limited to genes of this assembly.
        for key, gene_pk in self._rows(
            select(transcripts.c.id, transcripts.c.gene_id)
            .select_from(transcripts.join(genes, transcripts.c.gene_id == genes.c.gene_pk))
            .where(
                transcripts.c.id.in_(unique),
                genes.c.assembly_id == self.assembly_id,
            )
        ):
            owner[str(key)].add(int(gene_pk))
            gene_pks.add(int(gene_pk))

        # (3) exact, sourced alias -> gene_pk (explicit relation only), limited
        # to genes of this assembly: an alias is a string, not a namespace.
        for key, gene_pk in self._rows(
            select(gene_aliases.c.alias, gene_aliases.c.gene_id)
            .select_from(gene_aliases.join(genes, gene_aliases.c.gene_id == genes.c.gene_pk))
            .where(
                gene_aliases.c.alias.in_(unique),
                gene_aliases.c.source.is_not(None),
                genes.c.assembly_id == self.assembly_id,
            )
        ):
            owner[str(key)].add(int(gene_pk))
            gene_pks.add(int(gene_pk))

        loci = self._gene_rows(gene_pks)
        for key in unique:
            candidates = {p for p in owner[key] if p in loci}
            if not candidates:
                output[key] = _unresolved("no_exact_relation")
                continue
            if len(candidates) > 1:
                output[key] = _unresolved("ambiguous_relation")
                continue
            locus = loci[next(iter(candidates))]
            output[key] = {
                "status": "resolved",
                "gene_id": locus.gene_id,
                "chromosome": locus.chromosome,
                "start": locus.start,
                "end": locus.end,
                "strand": locus.strand,
                "assembly_id": locus.assembly_id,
                "release_id": locus.release_id,
                "relation": "explicit_subject_match",
            }
        return output


def annotate_hits(
    hits: list[dict[str, Any]],
    resolutions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach a resolution record to every hit without touching coordinates."""
    return [
        {**hit, "genome_resolution": resolutions.get(str(hit.get("subject_id", "")).strip(),
                                                      _unresolved("not_analyzed"))}
        for hit in hits
    ]


__all__ = [
    "PROTEIN_SUBJECT_PROGRAMS", "BlastGenomeResolver", "GeneLocus", "annotate_hits",
]
