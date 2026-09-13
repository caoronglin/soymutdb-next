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

# Every Dockerfile the release pipeline builds, from the single image list.
# A Dockerfile that is built but not guarded is exactly the case this script
# exists for: its COPY source can be gitignored and the failure only appears in
# a real image build.
# shellcheck source=scripts/list-images.sh
source "${REPO_ROOT}/scripts/list-images.sh"

fail=0

# Walk `name|context|dockerfile` entries rather than bare paths: a COPY source is
# resolved against the BUILD CONTEXT, and apps/mcp-server builds from its own
# directory (`context: apps/mcp-server`) rather than the repo root. Checking it
# against the repo root reported `MISSING COPY source: pyproject.toml` for a
# Dockerfile that builds fine.
while IFS='|' read -r image_name image_context image_dockerfile; do
  df="$REPO_ROOT/${image_dockerfile}"
  context_dir="$REPO_ROOT/${image_context}"
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

    # Source may be `dir/` (dir exists) or a file, resolved against the context.
    if [ ! -e "${context_dir}/$src" ]; then
      echo "MISSING COPY source: ${image_dockerfile} (context ${image_context}) -> $src"
      fail=1
    fi
  done < "$df"
done < <(soymutdb_image_entry)

if [ "$fail" -eq 0 ]; then
  echo "OK: all Dockerfile COPY sources exist."
fi
exit "$fail"
