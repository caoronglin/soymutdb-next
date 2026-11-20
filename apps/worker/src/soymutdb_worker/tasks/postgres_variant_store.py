"""Native, transaction-scoped VCF staging and atomic fact publication.

The caller owns the session and commits. No operation opens another pooled
connection; this works with a worker pool of one. Identical retries are accepted
and conflicting payloads fail closed, never overwriting published facts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from soymutdb_import_protocol import ImportManifestStatus, can_transition
from sqlalchemy import (
    BigInteger,
    Integer,
    Numeric,
    Text,
    column,
    func,
    select,
    table,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from soymutdb_worker.tables import import_manifests, releases

from .variant_finalize import BASE_COLUMNS, ConflictingVariantRowsError, deterministic_batch_id

FACT_COLUMNS = ("release_id", "assembly_id", *(
    name for name in BASE_COLUMNS if name != "release_key"
))


def _column(name):
    if name == "variant_id":
        return column(name, Numeric(20, 0))
    if name in {"release_id", "assembly_id", "consequence_id"}:
        return column(name, Integer)
    if name in {
        "position", "length", "gene_surrogate_id", "mutant_line_surrogate_id", "read_depth",
    }:
        return column(name, BigInteger)
    if name in {"quality_score", "allele_frequency"}:
        from sqlalchemy import Double

        return column(name, Double)
    return column(name, Text)


FACTS = table("variant_facts", *(_column(name) for name in FACT_COLUMNS))
STAGING = table(
    "variant_facts_staging", *(_column(name) for name in FACT_COLUMNS),
    column("import_id", Text), column("batch_id", Text),
)


class PostgresVariantStore:
    def __init__(self, session: Session):
        self.session = session

    def stage_batch(
        self, *, release_id: int, assembly_id: int, import_id: str,
        batch_index: int, base_rows: list[tuple],
    ) -> int:
        batch_id = deterministic_batch_id(import_id, batch_index)
        payloads: dict[int, dict] = {}
        for raw in base_rows:
            if len(raw) != len(BASE_COLUMNS):
                raise ValueError("Variant row has an invalid shape")
            row = dict(zip(BASE_COLUMNS, raw, strict=True))
            row.pop("release_key")
            row.update(release_id=release_id, assembly_id=assembly_id,
                       import_id=import_id, batch_id=batch_id)
            identity = int(row["variant_id"])
            if identity in payloads and payloads[identity] != row:
                raise ConflictingVariantRowsError([(identity, 2)])
            payloads[identity] = row
        rows = list(payloads.values())
        for offset in range(0, len(rows), 500):
            batch = rows[offset:offset + 500]
            statement = insert(STAGING).values(batch)
            identical = tuple_(*(STAGING.c[name] for name in FACT_COLUMNS)).is_not_distinct_from(
                tuple_(*(statement.excluded[name] for name in FACT_COLUMNS))
            )
            statement = statement.on_conflict_do_update(
                index_elements=["import_id", "assembly_id", "variant_id"],
                set_={"batch_id": statement.excluded.batch_id}, where=identical,
            ).returning(STAGING.c.variant_id)
            inserted = {int(identity) for identity in self.session.execute(statement).scalars()}
            conflicts = [(int(row["variant_id"]), 2) for row in batch
                         if int(row["variant_id"]) not in inserted]
            if conflicts:
                raise ConflictingVariantRowsError(conflicts)
        return len(rows)

    def finalize(
        self, *, release_id: int, assembly_id: int, import_id: str, expected_rows: int,
    ) -> dict:
        # The same release row is locked by lifecycle publication. Facts cannot
        # race a publish or mutate a release which became public while parsing.
        status = self.session.execute(
            select(releases.c.status).where(releases.c.id == release_id).with_for_update()
        ).scalar_one()
        manifest = self.session.execute(
            select(import_manifests).where(import_manifests.c.import_id == import_id)
            .with_for_update()
        ).mappings().one()
        if manifest["release_id"] != release_id or manifest["assembly_id"] != assembly_id:
            raise ValueError("Import manifest scope does not match the facts")
        if manifest["status"] == ImportManifestStatus.PUBLISHED.value:
            return {"status": "published", "import_id": import_id,
                    "written_rows": int(manifest["written_rows"] or 0), "idempotent": True}
        if str(status) == "published":
            raise ValueError("Published release facts are immutable")
        scope = STAGING.c.import_id == import_id
        # A duplicate identity in staging can only come from two assemblies
        # (the staging PK blocks same-assembly duplicates). Left unchecked it is
        # either collapsed onto variant_facts' single (release_id, variant_id)
        # arbiter -- SQLSTATE 21000, no RETURNING row -- or, on the real path,
        # rejected by the scope guard below as a generic ValueError. Either way
        # the offending id is lost. Fail closed with the ids instead.
        duplicates = self.session.execute(
            select(STAGING.c.variant_id, func.count().label("payloads"))
            .select_from(STAGING).where(scope)
            .group_by(STAGING.c.variant_id)
            .having(func.count() > 1)
        ).all()
        if duplicates:
            raise ConflictingVariantRowsError([
                (int(row.variant_id), int(row.payloads)) for row in duplicates
            ])
        invalid = self.session.execute(select(func.count()).select_from(STAGING).where(
            scope, (STAGING.c.release_id != release_id) | (STAGING.c.assembly_id != assembly_id),
        )).scalar_one()
        count = self.session.execute(
            select(func.count()).select_from(STAGING).where(scope)
        ).scalar_one()
        if invalid or count != expected_rows:
            raise ValueError("Staged variant count or scope does not match the source")

        incoming = select(*(STAGING.c[name] for name in FACT_COLUMNS)).where(scope)
        statement = insert(FACTS).from_select(FACT_COLUMNS, incoming)
        identical = tuple_(*(FACTS.c[name] for name in FACT_COLUMNS)).is_not_distinct_from(
            tuple_(*(statement.excluded[name] for name in FACT_COLUMNS))
        )
        statement = statement.on_conflict_do_update(
            index_elements=["release_id", "variant_id"],
            set_={"variant_id": statement.excluded.variant_id}, where=identical,
        ).returning(FACTS.c.variant_id)
        # Count RETURNING rows on the server rather than buffering the complete
        # release in the DBAPI client. Every collision must be an identical retry.
        published = statement.cte("published_facts")
        written = self.session.execute(select(func.count()).select_from(published)).scalar_one()
        if written != expected_rows:
            raise ValueError("Existing variant identity has a conflicting payload")

        current = str(manifest["status"])
        for target in (
            ImportManifestStatus.PARSING, ImportManifestStatus.WRITING,
            ImportManifestStatus.VERIFYING, ImportManifestStatus.PUBLISHED,
        ):
            if current == target.value:
                continue
            if can_transition(current, target):
                self.session.execute(update(import_manifests).where(
                    import_manifests.c.import_id == import_id,
                ).values(status=target.value, updated_at=datetime.now(UTC)))
                current = target.value
        if current != ImportManifestStatus.PUBLISHED.value:
            raise ValueError("Import manifest cannot advance to publication")
        self.session.execute(update(import_manifests).where(
            import_manifests.c.import_id == import_id,
        ).values(expected_rows=expected_rows, written_rows=written,
                 completed_at=datetime.now(UTC), failure_code=None))
        return {"status": "published", "import_id": import_id,
                "written_rows": written, "idempotent": False}
