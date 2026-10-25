#!/usr/bin/env bash
# Queue the alternative recipe (lr 1e-4, LLRD 0.65, label smoothing 0, seed 7) on a GPU as soon as
# that GPU's default-recipe pipeline finishes. Usage: bash ml/pod/run_alt.sh <backbone> <gpu> <crop_mode>
set -euo pipefail
cd "${WORK:-/root/CalHacks}"
export PATH=/root/venv/bin:$PATH OMP_NUM_THREADS=${OMP_NUM_THREADS:-8} MKL_NUM_THREADS=${MKL_NUM_THREADS:-8}
BB=$1 GPU=$2 MODE=$3
nohup bash -c "
  until grep -q 'PIPELINE_DONE $BB' runs/logs/$BB.log; do sleep 15; done
  echo \"starting alt recipe for $BB on GPU $GPU\"
  CUDA_VISIBLE_DEVICES=$GPU python -m ml.train --backbone $BB --crop-mode $MODE --recipe alt --seed 7 \
    --epochs ${EPOCHS:-10} --batch ${BATCH:-64} --workers 10 2>&1 | grep -v Warning
  echo PIPELINE_DONE $BB-alt
" > runs/logs/$BB-alt.log 2>&1 < /dev/null &
echo "queued alt recipe for $BB on GPU $GPU (pid $!)"
