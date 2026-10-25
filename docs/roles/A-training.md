# Role A: Model training, inference and the API host (owner: Nirvaan, has the GPU)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`. Read PLAN §3–§4 first.

**Your lane:** `ml/`, plus `serve/app.py`, `serve/classifier.py`, `serve/requirements.txt` and `serve/tests/`.

**You own the GPU queue.** Your job is to keep it busy from G0 to G3 and turn its output into an artifact B can calibrate and the iPhone can call.

**The split with B:** you train, B judges. You never read test data, and B never changes training code. That separation is a deliberate guard against fooling ourselves.

## Inputs you already have
- `data/train.csv`, `data/val.csv`: image paths are relative to `data/`.
- `data/images/`: 29,571 JPEGs. Copy them to the GPU box:
  ```bash
  rsync -a ~/CalHacks/data/images/ <gpu>:~/CalHacks/data/images/
  ```
- `contracts/categories.json`: **class index order. Model output index i = `classes[i]`.**
- `contracts/predictor.md`: the Python interface B calls (`ml/infer.py`).
- `contracts/model_meta.schema.json`: the artifact metadata.

## Rules specific to you
- **You never touch test.** CI blocks any code in `ml/` or `serve/` from reading `test.csv`. Every choice (backbone, epochs, learning rate, ensemble) is made on **val**.
- The dataloader returns `(image_tensor, label_index)` only. No metadata.
- **Eval/inference transform:** resize the short side, then center-crop a square. **Never pad.**
- Weights never go in git. Use `artifacts/` (gitignored) and copy them by `scp`/`rsync`.

## GPU queue (target times, PT)
| Start | Job | Output |
|---|---|---|
| 19:15 | Feature cache + linear probe × 3 backbones × 2 crop modes (square vs 3:4, PLAN §3.4 step 1) | `reports/probe_bakeoff.json`, probe heads, probe `val_logits.npz` |
| ~20:00 | LP-FT SigLIP 2, default recipe (seed 13) | `runs/<run>/best.pt`, `val_logits.npz` |
| ~20:50 | LP-FT DINOv2, default recipe | same |
| ~21:40 | LP-FT ConvNeXt, default recipe | same |
| ~22:45 | **Alternative recipe** (learning rate 1e-4, LLRD 0.65, label smoothing 0, seed 7) on the top-2 backbones, by B's val table | same |
| ~01:00 | Ensemble choice on val (B's table), export, hand to B for calibration | `artifacts/<v>/` |
| after G3 | Stretch: confident-learning retrain (val-gated), Core ML export | |

**Time one epoch first** and post it. If the GPU is slower than expected, cut in this order: the alternative recipe on backbone #2, then ConvNeXt's full fine-tune (keep its probe). **Never cut the val evaluation.**

## Steps
### A0. Environment (by G0, 19:15)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r ml/requirements.txt
python -c "import timm; print(timm.__version__); [timm.create_model(n, pretrained=True, num_classes=17, **kw) for n, kw in [('vit_base_patch16_siglip_384.v2_webli', {}), ('vit_base_patch14_dinov2.lvd142m', {'img_size': 378}), ('convnext_base.fb_in22k_ft_in1k_384', {})]]; print('all 3 load')"
python scripts/verify_data.py --images   # 0 failure(s) on the GPU box
nvidia-smi --query-gpu=name,memory.total --format=csv
```
Write the GPU name and memory into PLAN §10 (in a `shared` PR, or just post it in team chat).

### A1. Data + baselines (by G1, 20:00)
- `ml/data.py`:
  - a `Dataset` over a split CSV (raises if given `test.csv`)
  - train and eval transforms exactly as in PLAN §3.4, with a `crop_mode` of `square` or `portrait34` (a fixed 3:4 crop). Both are crop-only: **never pad or squash**.
  - per-backbone normalization from `timm.data.resolve_model_data_config`
  - DINOv2 runs at `img_size=378` (a multiple of 14)
- `ml/extract_features.py --backbone <name> --crop-mode <square|portrait34>`: frozen features for train and val → `runs/features/<name>-<mode>/{train,val}.npz`.
- `ml/probe.py`: L2 logistic regression, with `C` chosen on val.
  - Writes `reports/probe_bakeoff.json` with `val_top1`, `val_top3`, `val_macro_f1` and `C` per backbone × crop mode.
  - **Pick the crop mode per backbone by val macro-F1.** Fine-tuning uses that mode.
  - Also writes probe `val_logits.npz` (B evaluates the probes with the same code as everything else).
  - Saves the head weights.
  - **These probes are the "frozen features" baseline the fine-tuned model must beat.**

### A2. LP-FT training (from ~20:00, back to back)
`ml/train.py --backbone <name> --crop-mode <mode> --seed 13 [--recipe default|alt]`, recipe as in PLAN §3.4:
- head initialized from the probe
- **default:** AdamW wd 0.05, layer-wise LR decay 0.75, top-layer learning rate 5e-5, head 1e-3, cosine schedule, 1 warmup epoch, 10 epochs, label smoothing 0.1
- **alt:** top-layer learning rate 1e-4, LLRD 0.65, label smoothing 0
- both: bf16, gradient clip 1.0, batch 64 (gradient accumulation if needed)

Each epoch logs val top-1, top-3 and macro-F1 to `runs/<run>/metrics.jsonl`. Keep the best val macro-F1 checkpoint.

At the end, write `runs/<run>/val_logits.npz` (format in `contracts/predictor.md`) and **send it to B right away**. B's calibration and val analysis run off these files, not off the model.

### A3. Inference library + artifact (by ~01:00, early version by 22:00)
- `ml/infer.py` implements `contracts/predictor.md`:
  - `Predictor.from_artifact(dir)`
  - `.logits(paths)` (batched, eval transform, returns `(N, 17)` raw logits)
  - ensemble support: each member has its own backbone and preprocessing (`members[]` in `model_meta.json`), and their softmax probabilities are averaged
  - optional horizontal-flip test-time augmentation, behind a flag. Kept only if B's val numbers improve.
- `ml/export.py --runs <run> [<run> ...]` → `artifacts/<model_version>/{model_meta.json, member_*.pt}`.
  - It leaves `temperature`/`abstain_threshold` as `null`. **B fills them in** with `eval/calibrate.py`.
- **Ship an early artifact (any finished run) to B by 22:00,** so B's eval and serving code is tested on a real model early.

### A4. API host (by G2 for the shape, G3 for the real model)
- `serve/app.py` (FastAPI):
  - `POST /classify` (multipart `image`)
  - `POST /report` (delegates to B's `serve/claude_report.py`)
  - `GET /health`

  Responses must validate against `contracts/`. CORS on.
- `serve/classifier.py`:
  - `StubClassifier`: deterministic fake from the image hash, used until the artifact exists
  - `ModelClassifier`: `ml/infer.py` + temperature + softmax + top-3 + abstain
  - selected by `CLASSIFIER=stub|model`
- `serve/tests/test_contracts.py`: validates every route's response against the schemas. CI runs it.
- Run it on the GPU box: `uvicorn serve.app:app --host 0.0.0.0 --port 8000`, plus `cloudflared tunnel --url http://localhost:8000` for a public HTTPS URL. **iOS requires HTTPS.** Pin the URL in team chat.
- Measure `/classify` p50 latency over 20 val images and put it in your G3 PR.

### A5. Stretch (only after G3, only if everything above is merged)
- **Core ML on-device classification** (`coremltools`): the photo never leaves the phone for classification. Hand C the `.mlpackage` only if its val top-1 matches PyTorch within 0.5 points.
- **Noise-cleaned retrain** (PLAN §3.4 stretch), val-gated.

## What you hand to others
| To | What | When |
|---|---|---|
| B | `val_logits.npz` for every finished run | as each run ends |
| B | early artifact, then the final ensemble artifact | 22:00, then ~01:00 |
| C | public API URL (stub shape works from G2; real model at G3) | G2 / G3 |
| B (for the model card) | training configs, run times, GPU | G4 |

## Done means
- `reports/probe_bakeoff.json` is committed, with the command you ran in the PR.
- The final artifact loads in `ModelClassifier`, and `/classify` on 5 val images B picks returns the right top-1 for the images B expects.
- The iPhone gets real `/classify` responses over the tunnel. Attach a screenshot or curl transcript to the G3 PR.
