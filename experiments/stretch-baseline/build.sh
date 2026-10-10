#!/bin/sh
# Build the Stretch baseline renderer into /tmp (Linux-side scratch). Headers stay in research/open-source, unmodified.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-/tmp/pitchwing-stretch}"
mkdir -p "$OUT"
g++ -std=c++17 -O2 -I "$ROOT/research/open-source" "$ROOT/experiments/stretch-baseline/stretch_render.cpp" -o "$OUT/stretch_render"
echo "built $OUT/stretch_render"
