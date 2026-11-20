"""Assembly-scoped gene_pk resolution for worker imports.

Gene identity is ``(assembly, accession)``: v4 and v5 are separate
namespaces and the same accession may legitimately exist in both. A bare
accession is therefore ambiguous whenever multiple assemblies are loaded,
and must never be resolved by string similarity, coordinate proximity or a
silent default.

Resolution is batched (one SELECT per import, never per row). Unknown or
ambiguous assemblies fail loudly via :class:`AssemblyResolutionError` so the
import task records FAILED with an explicit reason; ambiguous accessions
under an unscoped query are *excluded* and reported to the caller, which
skips those rows with an auditable count instead of guessing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from ..tables import assemblies, genes


class AssemblyResolutionError(RuntimeError):
    """Raised when an assembly identifier cannot be resolved.

    ``unknown`` covers no match; ``ambiguous`` covers several matches. Both
    block the import rather than falling back to a default assembly.
    """


def resolve_assembly_id(session: Any, assembly: str) -> int:
    """Map an assembly name (or version) to exactly one ``assemblies.id``."""
    matcher: ColumnElement[bool] = or_(
        assemblies.c.name == assembly,
        assemblies.c.version == assembly,
    )
    rows = session.execute(select(assemblies.c.id).where(matcher)).all()
    ids = [row[0] for row in rows]
    if not ids:
        raise AssemblyResolutionError(
            f"unknown assembly {assembly!r}: no assemblies row matches name or version"
        )
    if len(ids) > 1:
        raise AssemblyResolutionError(
            f"ambiguous assembly {assembly!r}: matches multiple assemblies {ids}"
        )
    return ids[0]


def resolve_gene_accessions(
    session: Any, *, assembly: str = "", assembly_id: int | None = None
) -> tuple[dict[str, int], set[str]]:
    """Return ``(accession -> gene_pk, ambiguous accessions)`` for the scope.

    With ``assembly`` set, resolution is restricted to that assembly;
    accessions are unique within an assembly (``uq_gene_assembly_accession``),
    so any duplicate there is a uniqueness-contract violation and raises.
    Without it, accessions shared across assemblies are returned in the
    ambiguous set so callers can reject or disambiguate instead of guessing.

    ``assembly_id`` lets a caller that already resolved the assembly avoid a
    second lookup.
    """
    if assembly and assembly_id is None:
        assembly_id = resolve_assembly_id(session, assembly)

    statement = select(genes.c.accession, genes.c.gene_pk)
    if assembly_id is not None:
        statement = statement.where(genes.c.assembly_id == assembly_id)

    rows = session.execute(statement).all()
    counts: dict[str, int] = {}
    for accession, _pk in rows:
        counts[accession] = counts.get(accession, 0) + 1

    resolved: dict[str, int] = {}
    ambiguous: set[str] = set()
    for accession, gene_pk in rows:
        if counts[accession] != 1:
            if assembly_id is not None:
                raise AssemblyResolutionError(
                    f"ambiguous gene accession {accession!r} in assembly "
                    f"{assembly!r}: {counts[accession]} rows share it; "
                    "uniqueness contract violated"
                )
            ambiguous.add(accession)
            continue
        resolved[accession] = gene_pk
    return resolved, ambiguous


def resolve_gene_pk_map(session: Any, *, assembly: str = "") -> dict[str, int]:
    """Convenience wrapper returning only unambiguous ``accession -> gene_pk``."""
    resolved, _ambiguous = resolve_gene_accessions(session, assembly=assembly)
    return resolved


__all__ = [
    "AssemblyResolutionError",
    "resolve_assembly_id",
    "resolve_gene_accessions",
    "resolve_gene_pk_map",
]
