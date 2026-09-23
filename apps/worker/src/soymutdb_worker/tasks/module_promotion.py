"""ADR-0004 promotion: ``module_data_rows`` staging -> canonical read tables.

The ``module_tsv`` import writes validated rows into the generic staging table
``module_data_rows``, which has **no reader** in the portal path. This module
performs the explicit promotion step the ADR requires, per ``module_key``.

Design decisions (recorded in the ADR-0004 amendment)

* Promotion runs **inside the import transaction**, after staging is written
  and validated. "Staged but not promoted" therefore cannot be committed: a
  failed promotion rolls the staging rows back too, and the data set is never
  marked ready.
* The target mapping is explicit: only ``genes`` has a canonical destination
  today; any other ``module_key`` fails closed rather than silently writing
  staging that nothing reads.
* Genes are assembly-scoped reference data (``uq_gene_assembly_accession``), so
  promotion upserts by ``(assembly_id, accession)``. Draft-release data stays
  invisible because the portal resolves only PUBLISHED releases.
* Chromosomes referenced by staged genes are created when absent, using the
  observed maximum gene end as the provisional length. An existing length is
  never shortened; a later reference import may extend it.
* An empty staging set never deletes canonical rows: an empty/failed import is
  not an instruction to delete every gene.
* Retries are idempotent: the importer clears staging before rewriting and the
  upserts are keyed by stable identity, so a re-run reproduces the same rows.
* Staging is read with keyset pagination (``row_key > last``) so a 2M-row module
  never has to fit in memory while the same session also writes the upserts.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from soymutdb_worker.tables import module_data_rows

# module_key -> canonical destination table. Extending this mapping is the
# deliberate act the ADR asks for; an unmapped key must fail closed.
PROMOTION_TARGETS: dict[str, str] = {"genes": "genes"}

# The staging table is shared by every module; only the columns promotion needs
# are declared here, on a private metadata (the worker's shared `tables.py`
# definitions are abbreviated subsets and cannot be used for INSERT/upsert).
_promotion_metadata = MetaData()

_releases = Table(
    "releases",
    _promotion_metadata,
    Column("id", Integer, primary_key=True),
    Column("assembly_id", Integer),
)

_assemblies = Table(
    "assemblies",
    _promotion_metadata,
    Column("id", Integer, primary_key=True),
    Column("release_id", Integer),
    Column("name", String(128)),
)

_chromosomes = Table(
    "chromosomes",
    _promotion_metadata,
    Column("id", Integer, primary_key=True),
    Column("assembly_id", Integer, nullable=False),
    Column("name", String(64), nullable=False),
    Column("length", BigInteger, nullable=False),
    Column("order", Integer, nullable=False),
)

_genes = Table(
    "genes",
    _promotion_metadata,
    Column("gene_pk", BigInteger, primary_key=True),
    Column("accession", String(64), nullable=False),
    Column("assembly_id", Integer, nullable=False),
    Column("chromosome_id", Integer, nullable=False),
    Column("name", String(256)),
    Column("biotype", String(64)),
    Column("start", BigInteger),
    Column("end", BigInteger),
    Column("strand", String(1)),
    Column("description", Text),
    Column("attributes", JSONB),
    # TimestampMixin columns: declared here so the upsert's updated_at actually
    # updates instead of being silently dropped as an unknown column key.
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

_PROMOTION_BATCH_SIZE = 5_000


class PromotionError(RuntimeError):
    """Promotion cannot proceed; the import transaction must roll back."""


@dataclass(frozen=True)
class PromotionResult:
    module_key: str
    target: str
    promoted_rows: int
    chromosomes_created: int
    chromosomes_extended: int

    def as_evidence(self) -> dict[str, object]:
        return {
            "module_key": self.module_key,
            "target": self.target,
            "promoted_rows": self.promoted_rows,
            "chromosomes_created": self.chromosomes_created,
            "chromosomes_extended": self.chromosomes_extended,
        }


def _resolve_assembly_id(session: Session, release_id: int) -> int:
    """Resolve the canonical assembly for a release, or fail closed.

    ``releases.assembly_id`` is the explicit pin. When it is unset the release
    must own exactly one assembly row; zero or several is ambiguous and must not
    be guessed.
    """
    pinned = session.execute(
        select(_releases.c.assembly_id).where(_releases.c.id == release_id)
    ).scalar_one_or_none()
    if pinned:
        exists = session.execute(
            select(_assemblies.c.id).where(_assemblies.c.id == pinned)
        ).scalar_one_or_none()
        if exists is None:
            raise PromotionError(
                f"release {release_id} pins assembly_id={pinned}, which does not exist"
            )
        return int(pinned)

    owned = (
        session.execute(
            select(_assemblies.c.id)
            .where(_assemblies.c.release_id == release_id)
            .order_by(_assemblies.c.id)
        )
        .scalars()
        .all()
    )
    if len(owned) == 1:
        return int(owned[0])
    if not owned:
        raise PromotionError(
            f"release {release_id} has no assembly; link an assembly before importing module rows"
        )
    raise PromotionError(
        f"release {release_id} owns {len(owned)} assemblies; set releases.assembly_id "
        "to disambiguate before importing module rows"
    )


def _ensure_chromosome(
    session: Session,
    *,
    assembly_id: int,
    name: str,
    observed_end: int,
    order: int,
) -> tuple[int, bool, bool]:
    """Return ``(chromosome_id, created, extended)`` for one chromosome name."""
    existing = session.execute(
        select(_chromosomes.c.id, _chromosomes.c.length).where(
            _chromosomes.c.assembly_id == assembly_id,
            _chromosomes.c.name == name,
        )
    ).one_or_none()
    if existing is None:
        chromosome_id = session.execute(
            pg_insert(_chromosomes)
            .values(
                assembly_id=assembly_id,
                name=name,
                length=observed_end,
                order=order,
            )
            .on_conflict_do_update(
                index_elements=["assembly_id", "name"],
                set_={"length": func.greatest(_chromosomes.c.length, observed_end)},
            )
            .returning(_chromosomes.c.id)
        ).scalar_one()
        return int(chromosome_id), True, False

    chromosome_id, length = int(existing[0]), int(existing[1])
    if observed_end > length:
        session.execute(
            update(_chromosomes)
            .where(_chromosomes.c.id == chromosome_id)
            .values(length=observed_end)
        )
        return chromosome_id, False, True
    return chromosome_id, False, False


def _gene_payload(
    row: dict,
    *,
    assembly_id: int,
    chromosome_id: int,
) -> dict[str, object]:
    mutation_feature = row.get("mutation_feature")
    return {
        "accession": str(row["gene_id"]),
        "assembly_id": assembly_id,
        "chromosome_id": chromosome_id,
        "name": None,
        "biotype": "protein_coding",
        "start": int(row["start"]),
        "end": int(row["end"]),
        # The genes module schema has no strand column; '+' is the reference
        # default and is recorded explicitly so no reader sees NULL.
        "strand": "+",
        "description": None,
        "attributes": (
            {"mutation_feature": str(mutation_feature)} if mutation_feature else None
        ),
    }


def _upsert_genes(session: Session, payload: list[dict[str, object]]) -> None:
    if not payload:
        return
    statement = pg_insert(_genes)
    session.execute(
        statement.values(payload).on_conflict_do_update(
            index_elements=["assembly_id", "accession"],
            set_={
                "chromosome_id": statement.excluded.chromosome_id,
                "name": statement.excluded.name,
                "biotype": statement.excluded.biotype,
                "start": statement.excluded.start,
                "end": statement.excluded.end,
                "strand": statement.excluded.strand,
                "description": statement.excluded.description,
                "attributes": statement.excluded.attributes,
                "updated_at": func.now(),
            },
        )
    )


def promote_module_rows(
    session: Session,
    *,
    module_key: str,
    release_id: int,
) -> PromotionResult:
    """Promote staged rows for one module into its canonical table.

    Runs inside the caller's transaction; the caller must roll back if this
    raises. Only ``genes`` is mapped today and an unmapped key is an error, not
    a silent no-op (ADR-0004: staging must not remain write-only).
    """
    target = PROMOTION_TARGETS.get(module_key)
    if target is None:
        raise PromotionError(
            f"module {module_key!r} has no canonical promotion target; refusing to "
            "commit staging that no reader consumes"
        )

    assembly_id = _resolve_assembly_id(session, release_id)

    chromosomes_created = 0
    chromosomes_extended = 0
    chromosome_ids: dict[str, int] = {}
    chromosome_order: dict[str, int] = {}
    payload: list[dict[str, object]] = []
    promoted_rows = 0
    last_row_key: str | None = None

    while True:
        statement = (
            select(module_data_rows.c.row_key, module_data_rows.c.data)
            .where(
                module_data_rows.c.module_key == module_key,
                module_data_rows.c.release_id == release_id,
            )
            .order_by(module_data_rows.c.row_key)
            .limit(_PROMOTION_BATCH_SIZE)
        )
        if last_row_key is not None:
            statement = statement.where(module_data_rows.c.row_key > last_row_key)
        batch = session.execute(statement).all()
        if not batch:
            break

        for row_key, data in batch:
            row = dict(data)
            name = str(row["chromosome"])
            observed_end = max(int(row["end"]), int(row["start"]))
            if name not in chromosome_ids:
                chromosome_order[name] = len(chromosome_order)
            chromosome_id, created, extended = _ensure_chromosome(
                session,
                assembly_id=assembly_id,
                name=name,
                observed_end=observed_end,
                order=chromosome_order[name],
            )
            chromosome_ids[name] = chromosome_id
            chromosomes_created += int(created)
            chromosomes_extended += int(extended)
            payload.append(
                _gene_payload(
                    row,
                    assembly_id=assembly_id,
                    chromosome_id=chromosome_id,
                )
            )
        _upsert_genes(session, payload)
        promoted_rows += len(payload)
        payload.clear()
        last_row_key = str(batch[-1][0])

    return PromotionResult(
        module_key=module_key,
        target=target,
        promoted_rows=promoted_rows,
        chromosomes_created=chromosomes_created,
        chromosomes_extended=chromosomes_extended,
    )
