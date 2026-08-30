#!/usr/bin/env bash
# Append a scoped pg_stat_statements Top-20 snapshot to the operator baseline log.
set -euo pipefail

: "${POSTGRES_SERVICE:=postgres}"
: "${POSTGRES_DB:=soymutdb}"
: "${POSTGRES_USER:=soymutdb}"
: "${SLOW_QUERY_LOG:=docs/ops/slow-query-log.md}"

psql_args=(-X -v ON_ERROR_STOP=1 -q -t -A -F $'\t' -U "$POSTGRES_USER" -d "$POSTGRES_DB")
if [[ -n "${POSTGRES_HOST:-}" ]]; then
  psql_args+=(-h "$POSTGRES_HOST")
fi
if [[ -n "${POSTGRES_PORT:-}" ]]; then
  psql_args+=(-p "$POSTGRES_PORT")
fi

run_psql() {
  local statement=$1
  if [[ -n "${POSTGRES_PSQL:-}" ]]; then
    "$POSTGRES_PSQL" "${psql_args[@]}" -c "$statement"
  else
    docker compose exec -T "$POSTGRES_SERVICE" psql "${psql_args[@]}" -c "$statement"
  fi
}

read -r -d "" sql <<'SQL' || true
WITH scoped AS (
  SELECT total_exec_time, calls, mean_exec_time, queryid,
    left(regexp_replace(query, E'\s+', ' ', 'g'), 240) AS query_sample
  FROM pg_stat_statements
  WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
    AND query NOT ILIKE '%pg_stat_statements%'
)
SELECT round(total_exec_time::numeric, 1) AS total_ms, calls,
  round(mean_exec_time::numeric, 2) AS mean_ms,
  coalesce(round(((total_exec_time / nullif(sum(total_exec_time) OVER (), 0)) * 100)::numeric, 1), 0) AS pct,
  queryid::text AS query_id, query_sample
FROM scoped
ORDER BY total_exec_time DESC
LIMIT 20;
SQL

stats_reset=$(run_psql "SELECT coalesce(to_char(stats_reset AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS UTC'), 'unknown') FROM pg_stat_statements_info;")
stats_reset=${stats_reset:-unknown}

mkdir -p "$(dirname "$SLOW_QUERY_LOG")"
if [[ ! -f "$SLOW_QUERY_LOG" ]]; then
  printf "# Slow-query baseline log\n\nWeekly pg_stat_statements Top-20 snapshots. Query samples are normalized, capped, and scoped to the selected database.\n" > "$SLOW_QUERY_LOG"
fi

{
  printf "\n## %s\n\n" "$(date -u +%FT%TZ)"
  printf "_Cumulative statistics for database %s since %s; this report does not reset shared statistics._\n\n" "$POSTGRES_DB" "$stats_reset"
  printf "| total ms | calls | mean ms | %% | query id | query sample |\n| ---: | ---: | ---: | ---: | ---: | --- |\n"
  run_psql "$sql" | awk -F $'\t' 'NF == 6 {
    gsub(/\|/, "\\|", $6)
    gsub(/`/, "\\`", $6)
    printf "| %s | %s | %s | %s | `%s` | `%s` |\n", $1, $2, $3, $4, $5, $6
  }'
} >> "$SLOW_QUERY_LOG"

echo "Appended Top-20 slow-query baseline to $SLOW_QUERY_LOG"
