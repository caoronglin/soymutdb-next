#!/usr/bin/env python3
"""Probe what ``finalize()`` does when a duplicate identity reaches staging (#51).

``apps/worker/src/soymutdb_worker/tasks/postgres_variant_store.py`` builds one
statement whose ``ON CONFLICT`` arbiter is ``(release_id, variant_id)``, i.e. the
``uq_variant_facts_release_identity`` unique constraint -- *not* the three-column
primary key. This script rebuilds that statement against a real PostgreSQL
server and reports which of three distinct failures each staging shape produces,
so the difference between them stops being an argument.

It deliberately does not import the worker: this is a database-shape probe, not
a unit test, and it must run on whatever Python the workstation happens to have.

    A  one distinct row                  -> PASS (the rewrite path works)
    B  arbiter constraint absent         -> InvalidColumnReference, SQLSTATE 42P10.
                                            Parse-time: an EMPTY staging explodes.
    S2 same identity, same assembly      -> not constructible (staging PK refuses)
    S3 same identity, two assemblies     -> CardinalityViolation, SQLSTATE 21000

S3 is the finding. ``variant_facts_staging`` keys on
``(import_id, assembly_id, variant_id)``, so two assemblies are two staged rows
by construction; ``variant_facts`` then collapses them onto one
``(release_id, variant_id)`` arbiter, and PostgreSQL refuses to touch one row
twice. The statement raises before ``RETURNING`` yields a single row, so the
``written != expected_rows`` gate never runs and the caller sees an error with no
``variant_id`` in it.

Safety: refuses unless the database is loopback (Unix socket or 127.0.0.1) and
``--allow-create`` was passed, because it creates and drops the two tables it
probes. Use a throwaway database.

Usage
    python3 scripts/dev/verify-variant-finalize-conflict.py \\
        --dsn postgresql+psycopg2://postgres@/postgres?host=/tmp&port=5433 \\
        --allow-create

Exit codes: 0 every shape matched its expected verdict, 1 a verdict drifted,
2 refused (unsafe config or missing dependency).
"""

from __future__ import annotations

import argparse
import re
import sys

DDL = (
    """CREATE TABLE verify_conflict_releases (id integer PRIMARY KEY)""",
    """CREATE TABLE verify_conflict_assemblies (id integer PRIMARY KEY)""",
    """CREATE TABLE verify_conflict_facts (
        release_id integer NOT NULL, assembly_id integer NOT NULL,
        variant_id numeric(20,0) NOT NULL, assembly_key text NOT NULL,
        chromosome text NOT NULL, "position" bigint NOT NULL,
        ref_allele text NOT NULL, alt_allele text NOT NULL,
        PRIMARY KEY (release_id, assembly_id, variant_id),
        CONSTRAINT verify_conflict_release_identity UNIQUE (release_id, variant_id))""",
    """CREATE TABLE verify_conflict_staging (
        release_id integer NOT NULL, assembly_id integer NOT NULL,
        variant_id numeric(20,0) NOT NULL, assembly_key text NOT NULL,
        chromosome text NOT NULL, "position" bigint NOT NULL,
        ref_allele text NOT NULL, alt_allele text NOT NULL,
        import_id text NOT NULL, batch_id text NOT NULL,
        PRIMARY KEY (import_id, assembly_id, variant_id))""",
)

DROP = tuple(
    f"DROP TABLE IF EXISTS {name}"
    for name in (
        "verify_conflict_staging",
        "verify_conflict_facts",
        "verify_conflict_assemblies",
        "verify_conflict_releases",
    )
)

COLUMNS = (
    "release_id", "assembly_id", "variant_id", "assembly_key",
    "chromosome", "position", "ref_allele", "alt_allele",
)
IMPORT_ID = "verify-import"

# (label, staged rows as (assembly_id, keyword arguments), expected verdict)
SHAPES: tuple[tuple[str, list[tuple[int, dict]], tuple[str, str | None]], ...] = (
    ("A  one distinct row", [(4, {"variant_id": 10, "position": 100})], ("ok", None)),
    ("S2 same identity, same assembly",
     [(4, {"variant_id": 11, "position": 200})], ("staging", None)),
    ("S3 same identity, two assemblies",
     [(4, {"variant_id": 12, "position": 300}),
      (5, {"variant_id": 12, "position": 300})], ("error", "21000")),
    # The arbiter shape itself, staged EMPTY: the failure is parse-time, so it
    # needs no data at all.
    ("B  arbiter constraint absent", [], ("error", "42P10")),
)


def _refuse(message: str) -> int:
    print(f"refused: {message}", file=sys.stderr)
    return 2


def _dsn_is_loopback(dsn: str) -> bool:
    host = re.search(r"host=([^&]+)", dsn)
    if host:
        return host.group(1) in {"/tmp", "/var/run/postgresql"}
    netloc = dsn.split("://", 1)[-1].split("/", 1)[0]
    hostname = netloc.rsplit("@", 1)[-1].split(":", 1)[0]
    return hostname in {"", "127.0.0.1", "localhost"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", required=True, help="SQLAlchemy URL for a throwaway database")
    parser.add_argument("--allow-create", action="store_true",
                        help="required: this probe creates and drops its own tables")
    parser.add_argument("--keep", action="store_true", help="leave the probe tables behind")
    arguments = parser.parse_args()

    if not _dsn_is_loopback(arguments.dsn):
        return _refuse("the DSN is not loopback; this probe creates and drops tables")
    if not arguments.allow_create:
        return _refuse("--allow-create is required; this probe owns its two tables")
    try:
        from sqlalchemy import (
            BigInteger,
            Integer,
            Numeric,
            Text,
            column,
            create_engine,
            func,
            literal,
            select,
            table,
            text,
            tuple_,
        )
        from sqlalchemy.dialects.postgresql import insert
    except ModuleNotFoundError as error:
        return _refuse(f"missing dependency: {error}. `pip install sqlalchemy psycopg2-binary`")
    from sqlalchemy.exc import SQLAlchemyError

    def column_type(name: str):
        if name == "variant_id":
            return Numeric(20, 0)
        if name in {"release_id", "assembly_id"}:
            return Integer
        if name == "position":
            return BigInteger
        return Text

    facts = table("verify_conflict_facts", *(column(n, column_type(n)) for n in COLUMNS))
    staging = table("verify_conflict_staging", *(column(n, column_type(n)) for n in COLUMNS),
                    column("import_id", Text), column("batch_id", Text))
    release_identity = "verify_conflict_release_identity"

    def staged_row(assembly_id: int, **overrides) -> dict:
        row = {"release_id": 1, "assembly_id": assembly_id, "variant_id": 0,
               "assembly_key": "Wm82.a4.v1", "chromosome": "Chr01", "position": 0,
               "ref_allele": "A", "alt_allele": "T", "import_id": IMPORT_ID, "batch_id": "b0"}
        row.update(overrides)
        return row

    def finalize(connection, expected_rows: int) -> int:
        """The exact shape of postgres_variant_store.finalize(), minus the fixtures."""
        conflict_columns = ["release_id", "variant_id"]
        connection.execute(select(literal(1)))  # open the transaction explicitly
        incoming = select(*(staging.c[name] for name in COLUMNS)).where(
            staging.c.import_id == IMPORT_ID
        )
        statement = insert(facts).from_select(COLUMNS, incoming)
        identical = tuple_(*(facts.c[name] for name in COLUMNS)).is_not_distinct_from(
            tuple_(*(statement.excluded[name] for name in COLUMNS))
        )
        statement = statement.on_conflict_do_update(
            index_elements=conflict_columns,
            set_={"variant_id": statement.excluded.variant_id}, where=identical,
        ).returning(facts.c.variant_id)
        published = statement.cte("verify_published")
        written = connection.execute(
            select(func.count()).select_from(published)
        ).scalar_one()
        if written != expected_rows:
            raise ValueError("Existing variant identity has a conflicting payload")
        return written

    engine = create_engine(arguments.dsn)
    failures = 0
    verdicts: list[tuple[str, str]] = []
    try:
        with engine.connect() as connection:
            for statement in (*DROP, *DDL):
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO verify_conflict_releases VALUES (1)"))
            connection.execute(text("INSERT INTO verify_conflict_assemblies VALUES (4),(5)"))
            connection.commit()

            for label, rows, (expected_kind, expected_sqlstate) in SHAPES:
                connection.execute(text("DELETE FROM verify_conflict_facts"))
                connection.execute(text("DELETE FROM verify_conflict_staging"))
                if expected_kind == "staging":
                    # The duplicate cannot be staged through the primary key; feed
                    # it through the same INSERT the worker uses to show that the
                    # refusal comes from the table, not from the option.
                    try:
                        connection.execute(insert(staging).values(
                            [staged_row(assembly_id, **overrides)
                             for assembly_id, overrides in rows * 2]
                        ))
                        verdicts.append((label, "DRIFT: staging accepted the duplicate"))
                        failures += 1
                        connection.rollback()
                    except SQLAlchemyError:
                        connection.rollback()
                        verdicts.append((label, "staging PK refuses it (never reaches finalize)"))
                    continue

                if expected_sqlstate == "42P10":
                    connection.execute(text(
                        f"ALTER TABLE verify_conflict_facts DROP CONSTRAINT {release_identity}"
                    ))
                staged = [staged_row(assembly, **overrides) for assembly, overrides in rows]
                if staged:
                    connection.execute(insert(staging).values(staged))
                expected_rows = len(rows)
                try:
                    written = finalize(connection, expected_rows)
                except SQLAlchemyError as error:
                    connection.rollback()
                    sqlstate = getattr(getattr(error, "orig", None), "diag", None)
                    sqlstate = getattr(sqlstate, "sqlstate", None)
                    if expected_kind == "ok" or sqlstate != expected_sqlstate:
                        verdicts.append((label, f"DRIFT: SQLSTATE {sqlstate} {type(error).__name__}"))
                        failures += 1
                    else:
                        message = getattr(error.orig, "diag", None)
                        message = (getattr(message, "message_primary", "") or "").splitlines()[0]
                        verdicts.append((label, f"SQLSTATE {sqlstate}: {message[:200]}"))
                else:
                    connection.rollback()
                    if expected_kind == "ok":
                        verdicts.append((label, f"wrote {written} row(s)"))
                    else:
                        verdicts.append((label, "DRIFT: statement succeeded"))
                        failures += 1
                if expected_sqlstate == "42P10":
                    connection.execute(text(
                        f"ALTER TABLE verify_conflict_facts DROP CONSTRAINT IF EXISTS "
                        f"{release_identity}"
                    ))
                    connection.execute(text(
                        "ALTER TABLE verify_conflict_facts ADD CONSTRAINT "
                        f"{release_identity} UNIQUE (release_id, variant_id)"
                    ))
                    connection.commit()

            if not arguments.keep:
                for statement in DROP:
                    connection.execute(text(statement))
                connection.commit()
    finally:
        engine.dispose()

    for label, verdict in verdicts:
        print(f"{label:34} {verdict}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
