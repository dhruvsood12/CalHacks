#!/usr/bin/env bash
# One-time setup on a RunPod pod (PyTorch template): repo, deps, train+val images.
# The test split is never downloaded to the training machine.
set -euo pipefail
WORK=${WORK:-/root/CalHacks}
[ -d "$WORK/.git" ] || git clone -q https://github.com/dhruvsood12/CalHacks.git "$WORK"
cd "$WORK"
git fetch -q origin && git checkout -q "${BRANCH:-a/probe-bakeoff}" && git pull -q
# The image's CUDA torch lives in the (PEP 668-managed) system Python. A venv with
# --system-site-packages reuses it and takes the extra packages without touching the system.
[ -x /root/venv/bin/python ] || python -m venv --system-site-packages /root/venv
export PATH=/root/venv/bin:$PATH
python -m pip install -q "timm>=1.0.15" scikit-learn pandas tqdm matplotlib jsonschema
python -c "import torch, timm; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.device_count(), 'GPUs | timm', timm.__version__)"
mkdir -p runs/logs
python scripts/fetch_images.py --split train --workers 48
python scripts/fetch_images.py --split val --workers 48
python - <<'PY'
import csv, pathlib
for s in ("train", "val"):
    rows = list(csv.DictReader(open(f"data/{s}.csv")))
    missing = sum(not pathlib.Path("data", r["path"]).exists() for r in rows)
    print(f"{s}: {len(rows)} rows, {missing} missing")
PY
echo BOOTSTRAP_DONE
