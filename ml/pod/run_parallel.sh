#!/usr/bin/env bash
# One backbone per GPU: probes on both crop modes -> val-chosen crop -> LP-FT.
# Survives SSH disconnects (nohup); logs in runs/logs/<backbone>.log
set -euo pipefail
cd "${WORK:-/root/CalHacks}"
export PATH=/root/venv/bin:$PATH
# The container gets ~41 cores but torch sees the host's 128; cap threads per process
# so three pipelines (plus their DataLoader workers) don't oversubscribe the CPU.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-8} MKL_NUM_THREADS=${MKL_NUM_THREADS:-8}
i=0
for bb in ${BACKBONES:-siglip2 dinov2 convnext}; do
  CUDA_VISIBLE_DEVICES=$i nohup bash -c "
    set -eo pipefail
    for mode in square portrait34; do
      python -m ml.extract_features --backbone $bb --crop-mode \$mode --batch 128 --workers 10 2>&1 | grep -v Warning
      python -m ml.probe --only $bb-\$mode
    done
    MODE=\$(python -m ml.probe --chosen-crop $bb)
    echo \"training $bb with crop mode \$MODE\"
    python -m ml.train --backbone $bb --crop-mode \$MODE --recipe ${RECIPE:-default} --seed ${SEED:-13} --epochs ${EPOCHS:-10} --batch ${BATCH:-64} --workers 10 2>&1 | grep -v Warning \\
      || { echo \"RETRY $bb at batch 32 x accum 2 (likely OOM)\"; rm -f runs/$bb-\$MODE-lpft-${RECIPE:-default}-s${SEED:-13}/metrics.jsonl; \\
           python -m ml.train --backbone $bb --crop-mode \$MODE --recipe ${RECIPE:-default} --seed ${SEED:-13} --epochs ${EPOCHS:-10} --batch 32 --accum 2 --workers 10 2>&1 | grep -v Warning; }
    echo PIPELINE_DONE $bb
  " > runs/logs/$bb.log 2>&1 &
  echo "started $bb on GPU $i (pid $!)"
  i=$((i+1))
done
