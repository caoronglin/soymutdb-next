#!/usr/bin/env bash
# =============================================================================
# Verify every `COPY` source referenced by the repo's Dockerfiles exists in
# the build context (repo root).
#
# Regression guard: Docker COPY fails at build time when a source is missing
# (e.g. `.npmrc` was gitignored and never committed). This script checks all
# COPY sources up front, in CI and as a pre-commit hook.
#
# Usage: bash scripts/check-dockerfile-copy.sh
# Exit 0 = all COPY sources exist; exit 1 = one or more missing.
# =============================================================================
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILES=(
  "$REPO_ROOT/infra/docker/Dockerfile.api"
  "$REPO_ROOT/infra/docker/Dockerfile.worker"
  "$REPO_ROOT/apps/jbrowse/Dockerfile"
)

fail=0

for df in "${DOCKERFILES[@]}"; do
  [ -f "$df" ] || { echo "MISSING Dockerfile: $df"; fail=1; continue; }

  # Walk COPY lines, joining backslash continuations.
  # Skip multi-stage `--from=<stage>` sources and `.` / `./` destinations.
  line=""
  while IFS= read -r raw || [ -n "$raw" ]; do
    if [ -n "$line" ]; then
      line="$line $raw"
    else
      line="$raw"
    fi
    # Backslash continuation → keep accumulating.
    if [[ "$line" == *\\ ]]; then
      line="${line%\\}"
      continue
    fi

    trimmed="$(printf '%s' "$line" | sed 's/^[[:space:]]*//')"
    line=""
    [[ "$trimmed" =~ ^# ]] && continue
    [[ "$trimmed" =~ ^COPY[[:space:]] ]] || continue

    # Multi-stage `COPY --from=<stage> ...` sources live inside the build
    # image, not in the build context — skip those lines entirely.
    [[ "$trimmed" == *"--from="* ]] && continue

    # First token after COPY (+ optional --flag=value args).
    src=""
    for tok in $trimmed; do
      [ "$tok" = "COPY" ] && continue
      [[ "$tok" == --* ]] && continue
      src="$tok"
      break
    done
    [ -z "$src" ] && continue

    # Strip `--from=` isn't a source path; ignore wildcard and `./`.
    [[ "$src" == .* || "$src" == *"*"* ]] && continue

    # Source may be `dir/` (dir exists) or a file.
    if [ ! -e "$REPO_ROOT/$src" ]; then
      echo "MISSING COPY source: $df -> $src"
      fail=1
    fi
  done < "$df"
done

if [ "$fail" -eq 0 ]; then
  echo "OK: all Dockerfile COPY sources exist."
fi
exit "$fail"
