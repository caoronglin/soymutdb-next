#!/usr/bin/env python3
"""Fair A/B measurement harness for PostgreSQL query candidates.

## Why this exists

The earlier draft claimed a "~100x single-factor" win from adding one index.
The audit (D-08) rejected it for three reasons, all of which this harness
structurally prevents rather than merely documents:

1. **Both arms ANALYZE first.** Statistics are a variable; if one arm gets a
   fresh ANALYZE and the other does not, the measurement is not single-factor.
2. **Root-level readings only.** The draft compared a Seq Scan's sub-node
   ``actual time`` against the Nested Loop's root. `extract_run` reads the
   **root node** of ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` — Execution
   Time, Planning Time and the buffer counters are root fields.
3. **Alternating, repeated arms.** ``plan_rounds`` interleaves A and B for N
   rounds after an equal warm-up, so drift in cache temperature or background
   load cannot be attributed to either arm. `compare` reports median, min, max
   and sample count — never a single cherry-picked run.

## What it refuses to do

Hard constraint H-09: experiments run only against a named, disposable test
database. `assert_isolated_target` rejects any DSN whose database name is not
explicitly opted in, and `FORBIDDEN_SQL` refuses session termination, cluster
configuration and restart statements outright, so a mistyped DSN cannot reach a
shared database even if the name check were bypassed.

This module has **no database driver import**: it plans and compares, and the
caller supplies a ``execute`` callable. That keeps it importable (and testable)
on a machine with no PostgreSQL, which is exactly the state this was written in.

Usage:

    plan = build_plan("db-01-transcripts-gene-id", rounds=5)
    rows = plan_rounds(plan, execute=my_psql_execute)
    print(render_report(plan, rows))
"""
from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------------------
# Refusals. These are the statements that turn "a query experiment" into an incident
# on someone else's database (H-09). Matched against the normalised statement text.
# --------------------------------------------------------------------------------------
FORBIDDEN_SQL: tuple[str, ...] = (
    r"\bpg_terminate_backend\b",
    r"\bpg_cancel_backend\b",
    r"\balter\s+system\b",
    r"\bpg_reload_conf\b",
    r"\bpg_ctl\s+(restart|reload|stop)\b",
    r"\bshutdown\b",
    r"\bdrop\s+database\b",
    r"\bvacuum\s+full\b",
    r"\breindex\s+database\b",
)

# A DSN is only accepted when the database name matches this. It is deliberately
# narrow: "soymutdb" (the shared database) does not match, "soymutdb_abtest_01"
# does. The caller may narrow further, never widen.
REQUIRED_DATABASE_NAME = re.compile(r"^soymutdb_abtest_[a-z0-9_]+$")


class IsolationError(RuntimeError):
    """Raised when a statement or target would violate the experiment rules."""


def normalize_sql(sql: str) -> str:
    """Collapse whitespace and strip comments so refusals cannot be evaded."""
    without_block_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    without_line_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    return " ".join(without_line_comments.split())


def assert_sql_allowed(sql: str) -> str:
    """Return the normalised statement, or refuse it."""
    normalized = normalize_sql(sql)
    for pattern in FORBIDDEN_SQL:
        if re.search(pattern, normalized, flags=re.I):
            raise IsolationError(
                f"statement refused by the experiment harness: {normalized!r} "
                f"matches {pattern!r}. Experiments may not terminate sessions, "
                f"change cluster configuration, restart the server, or drop a database."
            )
    return normalized


def assert_isolated_target(dsn: str) -> str:
    """Require an explicitly disposable test database, and say which one."""
    match = re.search(r"/([^/?#]+)(?:\?|$)", dsn)
    database = match.group(1) if match else ""
    if not REQUIRED_DATABASE_NAME.match(database):
        raise IsolationError(
            f"refusing to run against database {database or '<unknown>'!r}: the "
            f"experiment harness only accepts a disposable copy named like "
            f"'soymutdb_abtest_<suffix>'. Clone a schema snapshot into such a "
            f"database first (see scripts/db_experiment.py --init)."
        )
    return database


# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Arm:
    """One side of the comparison.

    ``analyse`` is executed for *both* arms before any timing, so the only
    difference between the arms is ``treatment``.
    """

    name: str
    treatment: tuple[str, ...] = ()
    analyse: tuple[str, ...] = ("ANALYZE;",)


@dataclass(frozen=True)
class Round:
    """One alternating observation."""

    index: int
    arm: str
    execution_ms: float
    planning_ms: float
    shared_hit: int
    shared_read: int
    plan_signature: str
    rows: int


@dataclass
class ExperimentPlan:
    """A candidate, its two arms, and the statistics the run must produce."""

    experiment_id: str
    hypothesis: str
    database: str
    table: str
    arms: tuple[Arm, ...]
    query_sql: str
    params: dict[str, Any] = field(default_factory=dict)
    rounds: int = 5
    warmup_rounds: int = 1

    def __post_init__(self) -> None:
        if len(self.arms) != 2:
            raise ValueError(f"an A/B plan needs exactly 2 arms, got {len(self.arms)}")
        names = [arm.name for arm in self.arms]
        if names[0] == names[1]:
            raise ValueError("arm names must differ")
        if self.rounds < 5:
            # The audit's minimum: fewer rounds cannot separate a real effect
            # from cache noise, and a 1- or 3-run "stable" number is what
            # produced the retracted 100x figure.
            raise ValueError(f"at least 5 alternating rounds are required, got {self.rounds}")


def build_plan(
    experiment_id: str,
    *,
    hypothesis: str,
    database: str,
    table: str,
    query_sql: str,
    treatment: Sequence[str],
    params: dict[str, Any] | None = None,
    rounds: int = 5,
    warmup_rounds: int = 1,
) -> ExperimentPlan:
    """A one-factor plan: control has no DDL, treatment has exactly the candidate."""
    return ExperimentPlan(
        experiment_id=experiment_id,
        hypothesis=hypothesis,
        database=database,
        table=table,
        arms=(
            Arm(name="control"),
            Arm(name="treatment", treatment=tuple(treatment)),
        ),
        query_sql=query_sql,
        params=params or {},
        rounds=rounds,
        warmup_rounds=warmup_rounds,
    )


# --------------------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------------------

Execute = Callable[[str, dict[str, Any]], str]


def _plan_signature(plan_doc: Any) -> str:
    """A short fingerprint of node types, so a changed plan cannot be compared."""
    if isinstance(plan_doc, list):
        plan_doc = plan_doc[0] if plan_doc else {}
    plan_doc = plan_doc.get("Plan", plan_doc) or {}
    node_types: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            return
        label = node.get("Node Type", "?")
        relation = node.get("Relation Name")
        node_types.append(f"{label}:{relation}" if relation else str(label))
        for child in node.get("Plans", []) or []:
            walk(child)

    walk(plan_doc)
    return "|".join(node_types)


def extract_run(explain_json: str) -> dict[str, Any]:
    """Root-level Execution Time, Planning Time and buffer counters.

    Deliberately refuses sub-node numbers: a `Seq Scan`'s ``actual time`` is a
    slice of one side of a join, and comparing it to a root total is the exact
    mistake D-08 rejected.
    """
    try:
        document = json.loads(explain_json)
    except json.JSONDecodeError as error:  # pragma: no cover - defensive
        raise ValueError(f"EXPLAIN output is not JSON: {error}") from error
    if isinstance(document, list):
        if not document:
            raise ValueError("EXPLAIN returned an empty plan document")
        document = document[0]
    if "Execution Time" not in document:
        raise ValueError(
            "EXPLAIN output has no root 'Execution Time'; it was probably run "
            "without ANALYZE, so there is nothing to time."
        )
    return {
        "execution_ms": float(document["Execution Time"]),
        "planning_ms": float(document.get("Planning Time", 0.0)),
        "shared_hit": int(document.get("Shared Hit Blocks", 0)),
        "shared_read": int(document.get("Shared Read Blocks", 0)),
        "plan_signature": _plan_signature(document),
        "rows": int((document.get("Plan") or {}).get("Actual Rows", 0)),
    }


def plan_rounds(plan: ExperimentPlan, execute: Execute) -> list[Round]:
    """Run warm-up, then alternate arms, collecting one root reading per round.

    ``execute`` receives SQL and the plan's params and must return the raw
    ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` document. DDL and ANALYZE go
    through the same refusals as queries.
    """
    for arm in plan.arms:
        for statement in (*arm.analyse, *arm.treatment):
            assert_sql_allowed(statement)

    measured: list[Round] = []
    index = 0
    for round_index in range(plan.warmup_rounds + plan.rounds):
        for arm in plan.arms:
            if round_index < plan.warmup_rounds:
                execute(plan.query_sql, plan.params)
                continue
            index += 1
            # Re-assert statistics for both arms every round, so an ANALYZE
            # cannot drift in mid-run and quietly become the second variable.
            for statement in arm.analyse:
                execute(statement, plan.params)
            for statement in arm.treatment:
                execute(statement, plan.params)
            sample = extract_run(execute(plan.query_sql, plan.params))
            measured.append(Round(index=index, arm=arm.name, **sample))
    return measured


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmSummary:
    name: str
    samples: int
    median_ms: float
    min_ms: float
    max_ms: float
    plan_signatures: tuple[str, ...]

    @property
    def spread_ms(self) -> float:
        return self.max_ms - self.min_ms


@dataclass(frozen=True)
class Comparison:
    experiment_id: str
    control: ArmSummary
    treatment: ArmSummary
    same_plan: bool
    same_rows: bool

    @property
    def speedup(self) -> float | None:
        if self.treatment.median_ms == 0:
            return None
        return self.control.median_ms / self.treatment.median_ms

    @property
    def stable_shape(self) -> bool:
        """Each arm kept exactly one plan shape across all of its own rounds.

        This is the comparability test an experiment actually needs. `same_plan`
        demands the two arms be *identical*, which is correct for an experiment
        that varies statistics or cache state and wrong for one that varies the
        plan itself: an index treatment is supposed to turn a Seq Scan into an
        Index Scan, so `same_plan` is false by construction and no index
        experiment could ever clear it.

        What a drift looks like — one arm producing Seq Scan on round 1 and
        Bitmap Index Scan on round 4 — is a shape that is not constant *within*
        that arm, and that is a genuine fault: the candidate changed, or the
        optimiser re-evaluated on new statistics mid-run.
        """
        return (
            len(self.control.plan_signatures) == 1
            and len(self.treatment.plan_signatures) == 1
        )

    @property
    def is_decisive(self) -> bool:
        """A verdict is only reportable when the arms are actually comparable."""
        return (
            self.stable_shape
            and self.same_rows
            and self.control.samples >= 5
            and self.treatment.samples >= 5
        )


def summarise(name: str, rows: Iterable[Round]) -> ArmSummary:
    times = [row.execution_ms for row in rows]
    signatures = tuple(sorted({row.plan_signature for row in rows}))
    return ArmSummary(
        name=name,
        samples=len(times),
        median_ms=statistics.median(times) if times else float("nan"),
        min_ms=min(times) if times else float("nan"),
        max_ms=max(times) if times else float("nan"),
        plan_signatures=signatures,
    )


def compare(plan: ExperimentPlan, rows: Sequence[Round]) -> Comparison:
    by_arm: dict[str, list[Round]] = {}
    for row in rows:
        by_arm.setdefault(row.arm, []).append(row)
    control = summarise(plan.arms[0].name, by_arm.get(plan.arms[0].name, []))
    treatment = summarise(plan.arms[1].name, by_arm.get(plan.arms[1].name, []))
    return Comparison(
        experiment_id=plan.experiment_id,
        control=control,
        treatment=treatment,
        same_plan=set(control.plan_signatures) == set(treatment.plan_signatures),
        same_rows={row.rows for row in by_arm.get(plan.arms[0].name, [])} == {
            row.rows for row in by_arm.get(plan.arms[1].name, [])
        },
    )


def render_report(plan: ExperimentPlan, rows: Sequence[Round]) -> str:
    """Markdown report. Separates sample-level evidence from any end-to-end claim."""
    result = compare(plan, rows)
    lines = [
        f"## {plan.experiment_id}",
        "",
        f"- Hypothesis: {plan.hypothesis}",
        f"- Database: `{plan.database}` (disposable copy)",
        f"- Table: `{plan.table}`",
        f"- Rounds: {plan.rounds} alternating, after {plan.warmup_rounds} warm-up",
        "",
        "| arm | samples | median ms | min ms | max ms | spread ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for arm in (result.control, result.treatment):
        lines.append(
            f"| {arm.name} | {arm.samples} | {arm.median_ms:.3f} | "
            f"{arm.min_ms:.3f} | {arm.max_ms:.3f} | {arm.spread_ms:.3f} |"
        )
    lines += [
        "",
        f"- Speedup (median ratio): "
        f"{result.speedup:.1f}x" if result.speedup else "- Speedup: n/a",
        f"- Each arm held one plan shape: {result.stable_shape}",
        f"- Arms share a plan shape: {result.same_plan}",
        f"- Same result cardinality: {result.same_rows}",
        f"- Decisive: {result.is_decisive}",
    ]
    if not result.same_plan and result.stable_shape:
        lines += [
            "",
            "The arms do **not** share a plan shape, and that is the point of this "
            "run: the treatment changed how the database executes the query. The "
            "ratio above therefore compares two different access paths, not two "
            "measurements of the same one. It is reportable, but only as a "
            "statement about this fixture.",
        ]
    lines += [
        "",
        "### Evidence grade",
        "",
        "This is a **query-level** measurement on an isolated copy. It is not an",
        "end-to-end improvement, and an index shipped on this basis still needs a",
        "migration with upgrade/downgrade coverage plus traffic evidence.",
        "",
        "A ratio is only as stable as the smaller arm. When the treatment median is",
        "a few hundredths of a millisecond, ordinary scheduling noise moves it by",
        "enough to swing the ratio by tens of percent between runs. Re-run the whole",
        "experiment at least three times and report the spread, not one number.",
    ]
    return "\n".join(lines)