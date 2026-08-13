#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLICKHOUSE_MIGRATION_ROOT:-/opt/soymutdb}"
if [[ ! -f "${ROOT}/migrate_clickhouse_lib.py" ]]; then
  ROOT="${SCRIPT_DIR}"
fi
PYTHON="${CLICKHOUSE_MIGRATION_PYTHON:-${ROOT}/../venv/bin/python}"
[[ -x "${PYTHON}" ]] || PYTHON="$(command -v python3 || true)"
[[ -n "${PYTHON}" ]] || { echo "python3 is required" >&2; exit 1; }
if [[ -f "${ROOT}/upgrade_variant_facts_schema.sql" ]]; then
  SQL_FILE="${CH_MIGRATION_SQL:-${ROOT}/upgrade_variant_facts_schema.sql}"
else
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  SQL_FILE="${CH_MIGRATION_SQL:-${REPO_ROOT}/infra/clickhouse/upgrade_variant_facts_schema.sql}"
fi
export ROOT SQL_FILE
DRY_RUN="${1:-}"
exec "${PYTHON}" - "${DRY_RUN}" <<'PY'
import importlib.util, os, sys
from pathlib import Path

root = Path(os.environ["ROOT"])
spec = importlib.util.spec_from_file_location("migrate_clickhouse_lib", root / "migrate_clickhouse_lib.py")
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)
dry_run = sys.argv[1] == "--dry-run"
sql = Path(os.environ["SQL_FILE"]).read_text()
client = None
if not dry_run:
    try:
        import clickhouse_connect
    except ImportError as exc:
        raise SystemExit("clickhouse-connect is required for ClickHouse migration") from exc
    client = clickhouse_connect.get_client(
        host=os.getenv("SOYMUTDB_CLICKHOUSE_HOST", "127.0.0.1"),
        port=int(os.getenv("SOYMUTDB_CLICKHOUSE_PORT", "8123")),
        username=os.getenv("SOYMUTDB_CLICKHOUSE_USER", "default"),
        password=os.getenv("SOYMUTDB_CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("SOYMUTDB_CLICKHOUSE_DATABASE", "soymutdb"),
    )
try:
    result = lib.run_migration(client, sql, float(os.getenv("CH_EMPTY_KEY_THRESHOLD", "0.05")), dry_run=dry_run)
    print("[ok]", result)
except Exception as exc:
    print("[ERROR]", exc, file=sys.stderr)
    raise SystemExit(1)
PY
