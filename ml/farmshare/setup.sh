#!/usr/bin/env bash
# One-time FarmShare setup, run on a login node: clone, venv, deps. Light work only;
# the image download runs as a CPU batch job (fetch.sbatch), not on the login node.
set -euo pipefail
WORK=${WORK:-$HOME/CalHacks}
[ -d "$WORK/.git" ] || git clone https://github.com/dhruvsood12/CalHacks.git "$WORK"
cd "$WORK"
git fetch -q origin && git checkout -q "${BRANCH:-a/probe-bakeoff}" && git pull -q
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r ml/requirements.txt -r scripts/requirements.txt
.venv/bin/python -c "import torch, timm; print('torch', torch.__version__, 'cuda build', torch.version.cuda, '| timm', timm.__version__)"
