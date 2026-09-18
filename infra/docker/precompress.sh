#!/bin/sh
# Pre-compress static assets (.js/.css/.html/.svg/.json/.woff/.woff2/.ttf) with
# gzip -9 so nginx gzip_static can serve pre-compressed files without on-the-fly
# compression. Shared by Dockerfile.web and Dockerfile.admin.
#
# Refreshes stale archives. `gzip -k` refuses to overwrite an existing .gz
# ("already exists; not overwritten") and leaves the OLD body in place, so a
# changed source keeps its previous compressed payload — which nginx
# gzip_static then serves. The guard below rewrites the .gz whenever it is
# missing or older than its source, and skips the work when it is current.
#
# This was NOT a build breaker, and the distinction matters for anyone reading
# the history: `-exec … \;` never propagates a command failure (only `-exec … +`
# does), so a refusal here could not abort the image build. The real risk was
# silently serving a stale body. Fonts are the case that matters most, because
# .woff/.woff2/.ttf are compressed only here, never by the build chain.
#
# Division of labour: the web/admin build chain covers
# .html/.css/.js/.svg/.json/.xml/.txt; this script adds the font extensions.
# Both run on the container path only — the Pages/gh-pages path sets no
# SOYMUTDB_EMIT_GZ and ships no .gz at all.
# Verified by scripts/test_dockerfile_contracts.py::test_precompress_refreshes_stale_archives.
set -e
target_dir="${1:?usage: precompress.sh <dist-dir>}"
find "$target_dir" -type f \( \
    -name "*.js" -o \
    -name "*.css" -o \
    -name "*.html" -o \
    -name "*.svg" -o \
    -name "*.json" -o \
    -name "*.woff" -o \
    -name "*.woff2" -o \
    -name "*.ttf" \
\) -exec sh -c '
    for f do
        # Up to date already → leave it alone (keeps the script idempotent).
        # Older or missing → (re)compress, overwriting a stale .gz.
        [ -e "$f.gz" ] && [ "$f.gz" -nt "$f" ] || gzip -9 -f -k "$f"
    done
' sh {} +
