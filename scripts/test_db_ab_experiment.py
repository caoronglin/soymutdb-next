"""Tests for the A/B experiment harness.

The harness exists to make three audited mistakes impossible rather than merely
discouraged (design-audit D-08), so each of those has a test that fails if the
protection is removed:

1. asymmetric statistics — both arms ANALYZE every round;
2. cherry-picked sub-node timings — only root-level readings are accepted;
3. single-run claims — fewer than 5 alternating rounds is rejected.

And the isolation rules (H-09) are tested with real refusals, because a guard
that has never been seen to refuse is a guard nobody knows works.
"""
from __future__ import annotations

import json

import pytest

from scripts import db_ab_experiment as ab


def explain(execution_ms: float, *, rows: int = 1, shared_hit: int = 10, node: str = "Index Scan") -> str:
    """A minimal EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) document."""
    return json.dumps(
        {
            "Plan": {
                "Node Type": "Nested Loop",
                "Actual Rows": rows,
                "Plans": [
                    {"Node Type": "Index Scan", "Relation Name": "t", "Actual Rows": rows},
                    {"Node Type": node, "Relation Name": "g", "Actual Rows": rows},
                ],
            },
            "Planning Time": 0.100,
            "Execution Time": execution_ms,
            "Shared Hit Blocks": shared_hit,
            "Shared Read Blocks": 0,
        }
    )


def plan(**overrides) -> ab.ExperimentPlan:
    defaults = {
        "experiment_id": "db-01",
        "hypothesis": "an index on gene_id removes the seq scan",
        "database": "soymutdb_abtest_01",
        "table": "transcripts",
        "query_sql": "SELECT id FROM transcripts WHERE gene_id = $1",
        "treatment": ["CREATE INDEX ix_t_gene ON transcripts (gene_id);"],
        "rounds": 5,
    }
    defaults.update(overrides)
    return ab.build_plan(**defaults)


# --------------------------------------------------------------------------------------
# Isolation (H-09)
# --------------------------------------------------------------------------------------


class TestIsolation:
    @pytest.mark.parametrize(
        "database",
        ["soymutdb", "postgres", "soymutdb_abtest", "prod", "", "abtest"],
    )
    def test_refuses_any_database_that_is_not_an_opted_in_copy(self, database: str) -> None:
        dsn = f"postgresql+asyncpg://u:p@127.0.0.1:55432/{database}"
        with pytest.raises(ab.IsolationError, match="disposable copy"):
            ab.assert_isolated_target(dsn)

    @pytest.mark.parametrize(
        "database",
        ["soymutdb_abtest_01", "soymutdb_abtest_rnaseq", "soymutdb_abtest_2026_10"],
    )
    def test_accepts_an_explicitly_named_copy(self, database: str) -> None:
        dsn = f"postgresql+asyncpg://u:p@127.0.0.1:55432/{database}?sslmode=disable"
        assert ab.assert_isolated_target(dsn) == database

    def test_a_shared_database_name_cannot_slip_in_as_a_suffix(self) -> None:
        # `soymutdb_abtest_01` is fine; `soymutdb` and `soymutdb_production` are not.
        assert ab.assert_isolated_target("postgresql://h/soymutdb_abtest_01")
        for name in ("soymutdb", "soymutdb_production", "soymutdb2"):
            with pytest.raises(ab.IsolationError):
                ab.assert_isolated_target(f"postgresql://h/{name}")

    @pytest.mark.parametrize(
        "statement",
        [
            "SELECT pg_terminate_backend(42)",
            "ALTER SYSTEM SET work_mem = '1GB'",
            "SELECT pg_reload_conf()",
            "DROP DATABASE soymutdb",
            "VACUUM FULL transcripts",
            "REINDEX DATABASE soymutdb",
            "-- harmless\nSELECT 1; pg_cancel_backend(1)",
            "/* comment */ ALTER SYSTEM SET x = 1",
        ],
    )
    def test_refuses_statements_that_reach_beyond_one_experiment(self, statement: str) -> None:
        with pytest.raises(ab.IsolationError):
            ab.assert_sql_allowed(statement)

    def test_allows_ordinary_experiment_ddl_and_queries(self) -> None:
        for statement in [
            "ANALYZE transcripts;",
            "CREATE INDEX CONCURRENTLY ix ON transcripts (gene_id);",
            "SELECT * FROM pg_stat_user_tables WHERE relname = 'transcripts'",
            "DROP INDEX IF EXISTS ix_transcripts_gene_id;",
        ]:
            assert ab.assert_sql_allowed(statement)

    def test_refusals_survive_comment_obfuscation(self) -> None:
        # A guard that matches the literal keyword only is trivially bypassed.
        with pytest.raises(ab.IsolationError):
            ab.assert_sql_allowed("ALTER /* x */ SYSTEM SET work_mem = '1GB'")
        with pytest.raises(ab.IsolationError):
            ab.assert_sql_allowed("select pg_terminate_backend(1)")


# --------------------------------------------------------------------------------------
# Plan invariants (D-08 method defects)
# --------------------------------------------------------------------------------------


class TestPlanInvariants:
    def test_rejects_fewer_than_five_rounds(self) -> None:
        for rounds in (1, 2, 3, 4):
            with pytest.raises(ValueError, match="at least 5 alternating rounds"):
                plan(rounds=rounds)

    def test_requires_exactly_two_distinct_arms(self) -> None:
        with pytest.raises(ValueError, match="exactly 2 arms"):
            ab.ExperimentPlan(
                experiment_id="x",
                hypothesis="h",
                database="soymutdb_abtest_01",
                table="t",
                arms=(ab.Arm(name="only"),),
                query_sql="SELECT 1",
            )
        with pytest.raises(ValueError, match="must differ"):
            ab.ExperimentPlan(
                experiment_id="x",
                hypothesis="h",
                database="soymutdb_abtest_01",
                table="t",
                arms=(ab.Arm(name="same"), ab.Arm(name="same")),
                query_sql="SELECT 1",
            )

    def test_control_arm_carries_no_treatment(self) -> None:
        built = plan()
        assert built.arms[0].treatment == ()
        assert built.arms[1].treatment == ("CREATE INDEX ix_t_gene ON transcripts (gene_id);",)

    def test_the_plan_is_single_factor(self) -> None:
        """The only asymmetry between the arms may be the candidate itself."""
        built = plan()
        control, treatment = built.arms
        assert control.analyse == treatment.analyse, "statistics treatment must be identical"
        assert treatment.treatment, "the candidate must actually be applied"


# --------------------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------------------


class TestMeasurement:
    def test_reads_root_level_numbers_not_sub_nodes(self) -> None:
        run = ab.extract_run(explain(4.270))
        assert run["execution_ms"] == 4.270
        assert run["planning_ms"] == 0.100
        assert run["shared_hit"] == 10

    def test_refuses_an_explain_without_analyze(self) -> None:
        document = json.dumps({"Plan": {"Node Type": "Seq Scan"}, "Planning Time": 0.1})
        with pytest.raises(ValueError, match="no root 'Execution Time'"):
            ab.extract_run(document)

    def test_refuses_malformed_or_empty_output(self) -> None:
        with pytest.raises(ValueError, match="not JSON"):
            ab.extract_run("Seq Scan on transcripts")
        with pytest.raises(ValueError, match="empty plan"):
            ab.extract_run("[]")

    def test_a_changed_plan_is_visible_in_the_signature(self) -> None:
        indexed = ab.extract_run(explain(0.1, node="Index Scan"))
        scanned = ab.extract_run(explain(0.1, node="Seq Scan"))
        assert indexed["plan_signature"] != scanned["plan_signature"]
        assert "Index Scan:t" in indexed["plan_signature"]

    def test_both_arms_are_analysed_every_measured_round(self) -> None:
        statements: list[str] = []
        delays = iter([9.0] * 40)

        def execute(sql: str, params: dict) -> str:
            statements.append(" ".join(sql.split()))
            # The real executor wraps the query in EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON).
            if sql.strip().upper().startswith("SELECT ID FROM"):
                return explain(next(delays) if len(statements) % 2 else 9.0)
            return ""

        built = plan()
        ab.plan_rounds(built, execute)

        # The invariant is symmetry, not a total: every measured round must
        # analyse for both arms, so statistics can never be the second variable.
        # warm-up rounds execute the query only (they exist to warm caches).
        assert len([s for s in statements if s.startswith("ANALYZE")]) == 10, (
            "expected rounds x arms ANALYZE statements, got "
            f"{[s for s in statements if s.startswith('ANALYZE')]}"
        )
        assert len([s for s in statements if s.startswith("ANALYZE")]) % 2 == 0

    def test_treatment_ddl_runs_once_per_measured_round_of_that_arm(self) -> None:
        statements: list[str] = []

        def execute(sql: str, params: dict) -> str:
            statements.append(" ".join(sql.split()))
            return explain(1.0) if sql.strip().upper().startswith("SELECT ID FROM") else ""

        ab.plan_rounds(plan(), execute)
        created = [s for s in statements if s.startswith("CREATE INDEX")]
        assert len(created) == 5, "only the treatment arm may create the index"

    def test_forbidden_statements_in_a_plan_are_refused_before_execution(self) -> None:
        executed: list[str] = []

        def execute(sql: str, params: dict) -> str:
            executed.append(sql)
            return explain(1.0)

        dangerous = ab.ExperimentPlan(
            experiment_id="bad",
            hypothesis="h",
            database="soymutdb_abtest_01",
            table="t",
            arms=(
                ab.Arm(name="control"),
                ab.Arm(name="treatment", treatment=("SELECT pg_terminate_backend(1);",)),
            ),
            query_sql="SELECT 1",
        )
        with pytest.raises(ab.IsolationError):
            ab.plan_rounds(dangerous, execute)
        assert executed == [], "nothing may run once a statement is refused"


# --------------------------------------------------------------------------------------
# Comparison and reporting
# --------------------------------------------------------------------------------------


class TestComparison:
    def _rows(self, control_ms: float, treatment_ms: float) -> list[ab.Round]:
        rows: list[ab.Round] = []
        index = 0
        for _ in range(5):
            for arm, value in (("control", control_ms), ("treatment", treatment_ms)):
                index += 1
                rows.append(
                    ab.Round(
                        index=index,
                        arm=arm,
                        execution_ms=value,
                        planning_ms=0.1,
                        shared_hit=1,
                        shared_read=0,
                        plan_signature="Nested Loop",
                        rows=1,
                    )
                )
        return rows

    def _two_shaped_rows(self) -> list[ab.Round]:
        """Rows whose arms differ from each other but never from themselves."""
        return [
            row.__class__(
                **{
                    **row.__dict__,
                    "plan_signature": "Seq Scan" if row.arm == "control" else "Bitmap Index Scan",
                }
            )
            for row in self._rows(4.0, 2.0)
        ]

    def test_reports_median_and_sample_count(self) -> None:
        built = plan()
        result = ab.compare(built, self._rows(4.0, 2.0))
        assert result.control.samples == 5
        assert result.treatment.samples == 5
        assert result.control.median_ms == 4.0
        assert result.speedup == pytest.approx(2.0)
        assert result.is_decisive

    def test_a_shape_that_drifts_within_one_arm_makes_the_result_not_decisive(self) -> None:
        """Drift *inside* one arm is a real fault, and must stay non-decisive.

        This case used to be named "a plan change between arms", because the
        gate then compared the two arms to each other. A cross-arm difference is
        the normal result of an index experiment; a mid-run change within a
        single arm is not — it means the candidate, the statistics or the
        optimiser moved underneath the measurement. Only the second one is
        disqualifying.
        """
        rows = self._rows(4.0, 2.0)
        rows[0] = rows[0].__class__(**{**rows[0].__dict__, "plan_signature": "Seq Scan"})
        result = ab.compare(plan(), rows)
        assert not result.stable_shape
        assert not result.is_decisive

    def test_an_index_experiment_is_decisive_although_its_arms_differ(self) -> None:
        """The treatment is *supposed* to change the plan; that difference is the effect.

        Cross-arm shape equality can never hold for an index experiment, so
        requiring it would leave this whole class of measurement permanently
        undecidable. Comparability is per arm: each arm must hold one shape
        across all of its own rounds.
        """
        result = ab.compare(plan(), self._two_shaped_rows())
        assert not result.same_plan
        assert result.stable_shape
        assert result.same_rows
        assert result.is_decisive

    def test_report_names_a_cross_arm_shape_difference_as_the_measured_effect(self) -> None:
        report = ab.render_report(plan(), self._two_shaped_rows())
        assert "do **not** share a plan shape" in report
        assert "different access paths" in report

    def test_a_shrinking_treatment_median_must_not_be_quoted_from_one_run(self) -> None:
        """The report has to warn about ratio instability, not just print the ratio.

        Measured W6 runs of the same fixture and the same configuration produced
        ratios of 219x, 269x and 326x. The control median barely moved; the
        treatment median sat around 0.04 ms, so ordinary noise dominated the
        denominator. Printing one ratio invites exactly the claim the audit
        retracted, so the stability caveat ships with every report.
        """
        report = ab.render_report(plan(), self._rows(4.0, 0.04))
        assert "at least three times" in report
        assert "spread" in report

    def test_different_result_cardinality_makes_the_result_not_decisive(self) -> None:
        rows = self._rows(4.0, 2.0)
        rows[0] = rows[0].__class__(**{**rows[0].__dict__, "rows": 99})
        result = ab.compare(plan(), rows)
        assert not result.same_rows
        assert not result.is_decisive

    def test_too_few_samples_are_never_decisive(self) -> None:
        result = ab.compare(plan(), self._rows(4.0, 2.0)[:4])
        assert not result.is_decisive

    def test_zero_treatment_time_does_not_report_infinite_speedup(self) -> None:
        result = ab.compare(plan(), self._rows(4.0, 0.0))
        assert result.speedup is None

    def test_report_states_the_evidence_grade(self) -> None:
        report = ab.render_report(plan(), self._rows(4.0, 2.0))
        assert "query-level" in report
        assert "not an" in report and "end-to-end" in report
        assert "soymutdb_abtest_01" in report
        assert "| control | 5 |" in report