#!/usr/bin/env bash
#SBATCH --job-name=fetch-images
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=runs/logs/%x-%j.log
# A trains on train + val only; the test split is never downloaded to the training box.
set -euo pipefail
cd "${WORK:-$HOME/CalHacks}"
.venv/bin/python scripts/fetch_images.py --split train --workers 32
.venv/bin/python scripts/fetch_images.py --split val --workers 32
.venv/bin/python - <<'PY'
import csv, pathlib
for s in ("train", "val"):
    rows = list(csv.DictReader(open(f"data/{s}.csv")))
    missing = sum(not pathlib.Path("data", r["path"]).exists() for r in rows)
    print(s, len(rows), "rows,", missing, "missing")
PY
