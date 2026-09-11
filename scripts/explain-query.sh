#!/usr/bin/env bash
# Explain a read-only query through the Compose PostgreSQL service.
set -euo pipefail

: "${Q:?Usage: make explain-query Q='SELECT ...'}"
: "${POSTGRES_SERVICE:=postgres}"
: "${POSTGRES_DB:=soymutdb}"
: "${POSTGRES_USER:=soymutdb}"

query="${Q#${Q%%[![:space:]]*}}"
case "$query" in
  SELECT*|WITH*|EXPLAIN*) ;;
  *) echo "Only SELECT, WITH, or EXPLAIN statements are allowed." >&2; exit 2 ;;
esac

# A read-only transaction also rejects data-modifying CTEs.
docker compose exec -T "$POSTGRES_SERVICE" psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "BEGIN READ ONLY; EXPLAIN (ANALYZE, BUFFERS, VERBOSE) $query; ROLLBACK;"
