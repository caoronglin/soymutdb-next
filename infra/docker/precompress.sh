#!/bin/sh
# Pre-compress static assets (.js/.css/.html/.svg/.json/.woff/.woff2/.ttf) with
# gzip -9 so nginx gzip_static can serve pre-compressed files without on-the-fly
# compression. Shared by Dockerfile.web and Dockerfile.admin.
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
\) -exec gzip -k -9 {} \;
