#!/usr/bin/env bash
# Create one NEW isolated qualification environment; never update/delete an existing prefix.
set -euo pipefail
SOURCE="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"
: "${UV_BIN:?Supply an executable uv 0.11.33 path}"
: "${PYTHON314:?Supply an existing CPython 3.14 interpreter path}"
: "${ENV_PREFIX:?Supply a NEW environment path inside an ignored directory}"
: "${OUTPUT_DIR:?Supply a NEW evidence path inside an ignored directory}"
UV_BIN="$(realpath "$UV_BIN")"
PYTHON314="$(realpath "$PYTHON314")"
# Reject the original spelling too: realpath would otherwise hide a dangling symlink.
for target in "$ENV_PREFIX" "$OUTPUT_DIR"; do
  [[ ! -e "$target" && ! -L "$target" ]] || { echo "Existing target rejected: $target" >&2; exit 2; }
done
ENV_PREFIX="$(realpath -m "$ENV_PREFIX")"
OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"
[[ "$("$UV_BIN" --version)" =~ ^uv\ 0\.11\.33($|\ ) ]] || { echo 'uv 0.11.33 required' >&2; exit 2; }
"$PYTHON314" -I -c 'import platform,sys; assert sys.version_info[:2] == (3,14); assert platform.system() == "Linux" and platform.machine() == "x86_64"'
for target in "$ENV_PREFIX" "$OUTPUT_DIR"; do
  [[ ! -e "$target" && ! -L "$target" ]] || { echo "Existing target rejected: $target" >&2; exit 2; }
  case "$target/" in "$SOURCE/"*) echo 'Target must be outside profile source' >&2; exit 2;; esac
 done
case "$OUTPUT_DIR/" in "$ENV_PREFIX/"*) echo 'Targets must not nest' >&2; exit 2;; esac
case "$ENV_PREFIX/" in "$OUTPUT_DIR/"*) echo 'Targets must not nest' >&2; exit 2;; esac
# mkdir (no -p) reserves the new final paths atomically. Parents must already exist.
mkdir "$OUTPUT_DIR"
mkdir "$ENV_PREFIX"
export UV_CACHE_DIR="$OUTPUT_DIR/uv-cache" UV_PYTHON_DOWNLOADS=never
export UV_PYTHON_INSTALL_DIR="$OUTPUT_DIR/python" PYTHONDONTWRITEBYTECODE=1
"$PYTHON314" -I "$SOURCE/run_bounded.py" --output "$OUTPUT_DIR/create" --seconds 30 -- \
  "$UV_BIN" --no-config venv --python "$PYTHON314" "$ENV_PREFIX"
"$PYTHON314" -I "$SOURCE/run_bounded.py" --output "$OUTPUT_DIR/install" --seconds 240 -- \
  "$UV_BIN" --no-config pip sync --python "$ENV_PREFIX/bin/python" \
  --require-hashes "$SOURCE/requirements.lock"
"$PYTHON314" -I "$SOURCE/run_bounded.py" --output "$OUTPUT_DIR/check" --seconds 30 -- \
  "$UV_BIN" --no-config pip check --python "$ENV_PREFIX/bin/python"
"$PYTHON314" -I "$SOURCE/run_bounded.py" --output "$OUTPUT_DIR/smoke" --seconds 180 -- \
  "$ENV_PREFIX/bin/python" "$SOURCE/toyqualify.py" --output "$OUTPUT_DIR/toy"
