#!/usr/bin/env python3
"""Generate the build-time entity snapshot from the database.

Why this exists
    ``apps/web/src/lib/entity-snapshot.ts`` prerenders one document per released
    entity, and it is deliberately fail-closed: no snapshot means no entity
    documents, only the SPA shell. Something therefore has to produce the
    snapshot, and the only defensible source is the database that actually holds
    the release — not a hand-written fixture.

Contract
    * Emits exactly the whitelist the TypeScript side validates
      (``EntitySnapshot`` / ``GeneEntity`` in ``entity-snapshot.ts``). An extra
      key is a bug here, not something the build should filter.
    * One release, one site variant, named in the payload. A consumer whose pin
      disagrees rejects the file rather than publishing a mismatched document.
    * Only released, visible genes are listed. The query is the same public
      surface the portal reads: a gene is eligible when it belongs to the named
      assembly and that assembly belongs to the named release.
    * ``--limit`` exists because a full genome is 48k documents; a deployment
      chooses how much to prerender, and the default is deliberately small.

Usage
    python3 scripts/generate_entity_snapshot.py \
        --database-url postgresql://... \
        --release-id 1 \
        --assembly-id 1 \
        --site-variant external \
        --out apps/web/fixtures/entity-snapshot.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--database-url", required=True, help="psycopg2-style PostgreSQL URL")
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--assembly-id", type=int, required=True)
    parser.add_argument("--site-variant", default="external", choices=("external",))
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="maximum entities to prerender; a full genome is ~48k documents",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


async def _load(
    database_url: str, release_id: int, assembly_id: int, limit: int
) -> list[dict[str, Any]]:
    """Read the released genes through the driver the API venv actually ships.

    ``asyncpg`` is the one PostgreSQL driver installed here (the API depends on
    it), so the generator uses it rather than requiring a second, sync driver.
    """
    # asyncpg IS installed: it is the API's own driver (apps/api/.venv/bin/python).
    # The analyzer resolving this module is not that interpreter.
    import asyncpg  # type: ignore[import-not-found]  # pyright: ignore

    # `postgresql+asyncpg://` is SQLAlchemy's spelling; asyncpg wants the plain
    # scheme. Anything else is passed through untouched.
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        rows = await connection.fetch(
            """
                SELECT g.accession,
                       g.name,
                       c.name AS chromosome,
                       g.start,
                       g.end,
                       g.strand,
                       a.name AS assembly_name
                  FROM genes g
                  JOIN chromosomes c ON c.id = g.chromosome_id
                  JOIN assemblies  a ON a.id = g.assembly_id
                 WHERE g.assembly_id = $1
                   AND a.release_id = $2
                   AND g.start IS NOT NULL
                   AND g.end IS NOT NULL
                 ORDER BY c.name, g.start, g.accession
                 LIMIT $3
            """,
            assembly_id,
            release_id,
            limit,
        )
    finally:
        await connection.close()

    # `title` and `description` are the no-JS document's own copy, not app UI:
    # `entity-snapshot.ts` requires them and the prerendered body is English for
    # the same reason the news/about documents are. They follow the demo
    # fixture's shape so a real snapshot and the fixture read identically.
    entities: list[dict[str, Any]] = []
    for row in rows:
        public_id = row["accession"]
        assembly_name = row["assembly_name"]
        chromosome = row["chromosome"]
        start = int(row["start"])
        end = int(row["end"])
        entities.append(
            {
                "kind": "gene",
                "public_id": public_id,
                "symbol": row["name"],
                "assembly_id": str(assembly_id),
                "assembly_name": assembly_name,
                "release_id": release_id,
                "chromosome": chromosome,
                "start": start,
                "end": end,
                "strand": row["strand"] if row["strand"] in {"+", "-"} else ".",
                "title": f"{public_id} — Gene — SoyMutDB",
                "description": (
                    f"{public_id} on {assembly_name} {chromosome}:{start}-{end} "
                    f"(release {release_id})."
                ),
            }
        )
    return entities


async def _main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    entities = await _load(args.database_url, args.release_id, args.assembly_id, args.limit)
    if not entities:
        # An empty snapshot is legitimate (nothing released yet) but almost always
        # a wrong release/assembly id, so say so instead of writing a silent no-op.
        print(
            "refusing to write an empty snapshot: no genes matched that release/assembly. "
            "Pass the right ids, or delete the snapshot file to keep the SPA shell.",
            file=sys.stderr,
        )
        return 2

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "site_variant": args.site_variant,
        "entities": entities,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"entity snapshot: {len(entities)} gene document(s), "
        f"release {args.release_id}, assembly {args.assembly_id} -> {args.out}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    import asyncio

    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
