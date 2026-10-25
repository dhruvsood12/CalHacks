#!/usr/bin/env bash
# A1: frozen features for 3 backbones x 2 crop modes, then linear probes.
# Square crops first so the baseline exists early; 3:4 crops second.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
for mode in square portrait34; do
  for bb in siglip2 dinov2 convnext; do
    $PY -m ml.extract_features --backbone "$bb" --crop-mode "$mode" --workers "${WORKERS:-8}" 2>&1 | grep -v Warning
    $PY -m ml.probe --only "$bb-$mode"
  done
done
echo "A1 DONE"
