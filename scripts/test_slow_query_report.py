"""Behavioral contract for the pg_stat_statements baseline report script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "scripts" / "slow-query-report.sh"


def test_report_scopes_to_selected_database_and_escapes_markdown(tmp_path: Path) -> None:
    query_log = tmp_path / "queries.sql"
    fake_psql = tmp_path / "fake-psql"
    fake_psql.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s' \"$*\" >> \"${QUERY_LOG:?}\"\n"
        "printf '\\n' >> \"${QUERY_LOG:?}\"\n"
        "if [[ \"$*\" == *pg_stat_statements_info* ]]; then\n"
        "  printf '2026-08-30 00:00:00 UTC\\n'\n"
        "else\n"
        "  printf '10.0\\t2\\t5.00\\t100.0\\t42\\tSELECT $1 | `identifier`\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_psql.chmod(0o755)
    report_log = tmp_path / "slow-query-log.md"

    result = subprocess.run(
        ["bash", str(REPORT)],
        cwd=ROOT,
        env={
            **os.environ,
            "POSTGRES_PSQL": str(fake_psql),
            "QUERY_LOG": str(query_log),
            "SLOW_QUERY_LOG": str(report_log),
            "POSTGRES_DB": "baseline_db",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "55432",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    text = report_log.read_text(encoding="utf-8")
    assert "Cumulative statistics for database baseline_db since 2026-08-30 00:00:00 UTC" in text
    assert "| 10.0 | 2 | 5.00 | 100.0 | `42` | `SELECT $1 \\| \\`identifier\\`` |" in text
    calls = query_log.read_text(encoding="utf-8")
    assert "-t" in calls
    assert "-h 127.0.0.1" in calls
    assert "-p 55432" in calls
    assert "dbid = (SELECT oid FROM pg_database WHERE datname = current_database())" in calls
    assert "LIMIT 20" in calls
