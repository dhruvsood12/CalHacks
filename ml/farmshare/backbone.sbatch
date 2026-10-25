#!/usr/bin/env bash
#SBATCH --job-name=a-backbone
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=runs/logs/%x-%j.log
# One backbone end to end on one GPU: frozen features for both crop modes -> probes ->
# val-chosen crop -> LP-FT. Submit once per backbone so the three run in parallel:
#   sbatch [partition/qos/gres flags] --export=ALL,BB=siglip2,RECIPE=default,SEED=13 ml/farmshare/backbone.sbatch
set -euo pipefail
cd "${WORK:-$HOME/CalHacks}"
PY=.venv/bin/python
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
if [ "${SKIP_PROBES:-0}" != "1" ]; then
  for mode in square portrait34; do
    $PY -m ml.extract_features --backbone "$BB" --crop-mode "$mode" --batch 128 --workers 14 2>&1 | grep -v Warning
    $PY -m ml.probe --only "$BB-$mode"
  done
fi
MODE=${MODE:-$($PY -m ml.probe --chosen-crop "$BB")}
echo "training $BB with crop mode $MODE, recipe ${RECIPE:-default}, seed ${SEED:-13}"
$PY -m ml.train --backbone "$BB" --crop-mode "$MODE" --recipe "${RECIPE:-default}" --seed "${SEED:-13}" \
  --epochs "${EPOCHS:-10}" --batch "${BATCH:-64}" --workers 14 2>&1 | grep -v Warning
