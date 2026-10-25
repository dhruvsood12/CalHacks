#!/usr/bin/env bash
# Launch one detached training run on one GPU (returns immediately; log in runs/logs/).
# Usage: bash ml/pod/launch_train.sh <gpu> <backbone> <crop_mode> <recipe> <seed>
set -euo pipefail
cd "${WORK:-/root/CalHacks}"
export PATH=/root/venv/bin:$PATH OMP_NUM_THREADS=${OMP_NUM_THREADS:-8} MKL_NUM_THREADS=${MKL_NUM_THREADS:-8}
GPU=$1 BB=$2 MODE=$3 RECIPE=$4 SEED=$5
LOG=runs/logs/$BB-$RECIPE-s$SEED.log
CUDA_VISIBLE_DEVICES=$GPU setsid nohup bash -c "
  python -m ml.train --backbone $BB --crop-mode $MODE --recipe $RECIPE --seed $SEED --epochs ${EPOCHS:-10} \
    --batch ${BATCH:-64} --workers 10 2>&1 | grep -v Warning
  echo PIPELINE_DONE $BB-$RECIPE-s$SEED
" > "$LOG" 2>&1 < /dev/null &
echo "launched $BB $MODE $RECIPE seed $SEED on GPU $GPU -> $LOG"
