"""Verified, bounded legacy fact transfer. The caller owns commit/rollback.

Source factories must return fresh, ordered snapshots while legacy writers
are stopped. No source operation mutates ClickHouse. Existing PostgreSQL
facts are never overwritten; mismatch rolls back the entire release transfer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .legacy_fact_source import LegacySourceConfig, LegacySourceError, http_fact_source
from .tasks.postgres_variant_store import FACT_COLUMNS, FACTS
from .tasks.variant_finalize import BASE_COLUMNS


def _digest_row(digest, row: Mapping) -> None:
    values = []
    for name in FACT_COLUMNS:
        value = row[name]
        if name in {"quality_score", "allele_frequency"}:
            value = float(value)
        elif isinstance(value, Decimal):
            value = int(value)
        values.append(value)
    digest.update(json.dumps(values, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8") + b"\n")


def transfer_release(
    session: Session, source: Callable[[], Iterable[tuple]], *, release_id: int,
    source_version: str, assembly_map: Mapping[str, int], apply: bool = False,
    batch_size: int = 500,
) -> dict:
    """Verify explicit identity mappings, stream facts, then verify both stores.

    Dry-run never locks or writes. Apply locks the authoritative release until
    the caller commits. Published releases are allowed here solely for legacy
    transfer, unlike ordinary ingestion. Every target fact must match source.
    """
    if not 1 <= batch_size <= 1000 or not assembly_map:
        raise ValueError("A bounded batch size and explicit assembly map are required")
    if len(set(assembly_map.values())) != len(assembly_map):
        raise ValueError("Assembly namespaces must not be collapsed")
    release_sql = "SELECT version FROM releases WHERE id = :id"
    if apply:
        release_sql += " FOR UPDATE"
    version = session.execute(text(release_sql), {"id": release_id}).scalar_one()
    if version != source_version:
        raise ValueError("Source release version does not match authoritative identity")
    for label, identity in assembly_map.items():
        row = session.execute(text(
            "SELECT name, version FROM assemblies WHERE id = :id"
        ), {"id": identity}).mappings().one()
        if not label or label not in {row["name"], row["version"]}:
            raise ValueError("Assembly map must match an explicit database label")

    def scan(write: bool):
        digest = hashlib.sha256()
        count = 0
        previous = -1
        batch = []
        for raw in source():
            row = dict(zip(BASE_COLUMNS, raw, strict=True))
            if row.pop("release_key") != source_version:
                raise ValueError("Source returned facts from another release")
            label = row["assembly_key"]
            if label not in assembly_map:
                raise ValueError("Unmapped assembly namespace")
            identity = int(row["variant_id"])
            if not previous < identity <= 18446744073709551615:
                raise ValueError("Source variant identities must be unique and ordered")
            previous = identity
            row.update(release_id=release_id, assembly_id=assembly_map[label])
            _digest_row(digest, row)
            count += 1
            if write:
                batch.append(row)
                if len(batch) == batch_size:
                    session.execute(insert(FACTS).values(batch).on_conflict_do_nothing())
                    batch.clear()
        if batch:
            session.execute(insert(FACTS).values(batch).on_conflict_do_nothing())
        return count, digest.hexdigest()

    source_count, source_digest = scan(apply)
    target_digest = hashlib.sha256()
    target_count = 0
    result = session.execute(
        select(FACTS).where(FACTS.c.release_id == release_id)
        .order_by(FACTS.c.variant_id).execution_options(stream_results=True, yield_per=500)
    )
    try:
        for row in result.mappings():
            _digest_row(target_digest, row)
            target_count += 1
    finally:
        result.close()
    matches = (source_count, source_digest) == (target_count, target_digest.hexdigest())
    if apply:
        if not matches:
            raise ValueError("Target payload verification failed; rollback is required")
        if scan(False) != (source_count, source_digest):
            raise ValueError("Source changed during transfer; rollback is required")
        session.execute(text(
            "INSERT INTO native_variant_backfills "
            "(release_id,source_version,source_count,payload_sha256,assembly_map) "
            "VALUES (:release_id,:version,:count,:digest,CAST(:mapping AS JSONB)) "
            "ON CONFLICT (release_id) DO NOTHING"
        ), {"release_id": release_id, "version": source_version, "count": source_count,
            "digest": source_digest, "mapping": json.dumps(dict(assembly_map), sort_keys=True)})
        receipt = session.execute(text(
            "SELECT source_version,source_count,payload_sha256,assembly_map "
            "FROM native_variant_backfills WHERE release_id=:release_id"
        ), {"release_id": release_id}).mappings().one()
        recorded = (receipt["source_version"], receipt["source_count"],
                    receipt["payload_sha256"], receipt["assembly_map"])
        expected = (source_version, source_count, source_digest, dict(assembly_map))
        if recorded != expected:
            raise ValueError("Existing backfill receipt differs; rollback is required")
    return {
        "release_id": release_id, "source_count": source_count,
        "target_count": target_count, "payload_sha256": source_digest,
        "matches": matches, "applied": apply,
    }


def clickhouse_source(client, source_version: str) -> Callable[[], Iterable[tuple]]:
    """Read-only ordered source with fixed columns and a bound release key.

    Retained for compatibility with historical driver-based callers and their
    tests. The CLI no longer uses it: the legacy driver cannot be installed on
    this runtime, so legacy_fact_source.http_fact_source speaks the same query
    over plain HTTPS instead.
    """
    def rows():
        with client.query_row_block_stream(
            "SELECT " + ", ".join(BASE_COLUMNS)
            + " FROM variant_facts WHERE release_key = {release:String} ORDER BY variant_id",
            parameters={"release": source_version},
            settings={"readonly": 1, "max_block_size": 1000},
        ) as blocks:
            for block in blocks:
                yield from block
    return rows


def main() -> None:
    """Run explicitly against operator-supplied connection settings."""
    import argparse
    import os

    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--assembly-map", required=True, help='JSON, e.g. {"v4":4,"v5":5}')
    parser.add_argument("--apply", action="store_true", help="Commit a verified transfer")
    parser.add_argument("--source-frozen", action="store_true",
                        help="Confirm all legacy writers are stopped")
    args = parser.parse_args()
    if args.apply and not args.source_frozen:
        parser.error("--apply requires --source-frozen")
    mapping = json.loads(args.assembly_map)
    if not isinstance(mapping, dict) or any(
        not isinstance(key, str) or type(value) is not int or value <= 0
        for key, value in mapping.items()
    ):
        parser.error("--assembly-map must map labels to positive integer identities")
    # No development defaults: accidentally omitted operator configuration must
    # never connect this migration to an unintended database.
    try:
        source_config = LegacySourceConfig.from_env()
    except LegacySourceError as exc:
        parser.error(str(exc))
    engine = create_engine(os.environ["BACKFILL_POSTGRES_URL"], pool_size=1, max_overflow=0,
                           isolation_level="REPEATABLE READ")
    try:
        with Session(engine) as session:
            report = transfer_release(
                session, http_fact_source(source_config, args.source_version),
                release_id=args.release_id, source_version=args.source_version,
                assembly_map=mapping, apply=args.apply,
            )
            if args.apply:
                session.commit()
            else:
                session.rollback()
        print(json.dumps(report, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
