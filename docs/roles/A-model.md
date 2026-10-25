# Role A: Model (owner: Nirvaan)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`. You own `ml/` and `reports/`. Read PLAN §3–§4 first: they hold the architecture, the reasons for it, and the leakage rules.

**Your deliverable:** a calibrated 17-class classifier with honest test metrics, shipped as `model_meta.json` + weights that B can load without asking you anything.

## Inputs you already have
- `data/train.csv`, `data/val.csv`: columns include `path, label, split, geohash, group`. Image paths are relative to `data/`.
- `data/images/`: 29,571 JPEGs, max side 768px (not in git; copy the folder to the GPU box).
- `contracts/categories.json`: **class index order. Your model's output index must match it.**
- `contracts/model_meta.schema.json`: the exact metadata you must ship.

## Rules specific to you
- **Only `ml/final_eval.py` may read `data/test.csv`.** CI enforces this. Every decision (backbone, epochs, learning rate, temperature, threshold, data cleaning) is made on **val**.
- Your dataloader returns `(image_tensor, label_index)`, nothing else. No metadata features.
- **Eval transform:** resize the short side, then center-crop a square. **Never pad or letterbox** (aspect-ratio shortcut, PLAN §2).
- Weights never go in git. Share them by `scp` or a cloud bucket. The path goes in your PR description.

## Steps

### A0. Environment (before G0, 18:45)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r ml/requirements.txt   # torch, timm>=1.0.15, scikit-learn, pandas, numpy, pillow, tqdm
python -c "import timm; print(timm.list_models('*siglip*384*v2*', pretrained=True)); print(timm.list_models('*dinov2*', pretrained=True)[:5]); print(timm.list_models('convnext_base.fb_in22k*', pretrained=True))"
python scripts/verify_data.py --images   # must print 0 failure(s) on the GPU box too
```
Record the GPU model and memory in PLAN §10.2.

### A1. Feature cache + linear-probe bake-off (by G2, 22:30)
- `ml/data.py`: a `Dataset` over a split CSV (refuses `test.csv` unless called from `final_eval.py`). It includes the train and eval transforms from PLAN §3.4.
- `ml/extract_features.py --backbone <timm name>`: runs the backbone frozen on train and val with the **eval** transform, using each model's own normalization (`timm.data.resolve_model_data_config`). Saves `runs/features/<backbone>/{train,val}.npz`. DINOv2: pass `img_size=448`.
- `ml/probe.py`: logistic regression (sklearn, `C` tuned by grid on val, L2, max_iter high enough to converge) per backbone. Writes `reports/probe_bakeoff.json`:
  ```json
  {"<backbone>": {"val_top1": 0.0, "val_top3": 0.0, "val_macro_f1": 0.0, "C": 0.0, "feat_dim": 0, "extract_sec": 0}}
  ```
  It also saves the best probe weights per backbone (used to start the head in LP-FT).
- **Pick the backbone with the highest val macro-F1.** Open a PR with the JSON. That's the G2 decision.
- **Stretch (val-gated):** 5-fold out-of-fold probe predictions on **train**. Flag train images where the given label has probability < 0.05 and another class > 0.8. Drop at most 5% and log the ids to `reports/train_noise_dropped.csv`. Keep it only if LP-FT val macro-F1 improves.

### A2. LP-FT fine-tune (starts right after the bake-off)
`ml/train.py --backbone <name> --seed 13 --epochs 10`
- Head initialized from the probe weights (LP-FT).
- AdamW (wd 0.05), layer-wise learning-rate decay 0.75, top-layer learning rate 5e-5, head 1e-3, cosine schedule with 1 epoch warmup, bf16, gradient clip 1.0, label smoothing 0.1, batch 64 (with gradient accumulation if memory runs out).
- Augmentation exactly as PLAN §3.4. No CutMix/Mixup, no vertical flip.
- After every epoch: val top-1, top-3 and macro-F1 → `runs/<run>/metrics.jsonl`. Keep the **best val macro-F1** checkpoint.
- Run a second seed (`--seed 7`) as soon as the GPU is free. Add a third if time allows.
- **Ship an early checkpoint to B by ~00:30** (even pre-calibration) so integration isn't blocked.

### A3. Calibration + abstention (before G3, 01:30)
`ml/calibrate.py --run <best run>`:
- Fit the temperature `T` on val logits (minimize negative log-likelihood).
- Choose `abstain_threshold` = the smallest max-probability where val accuracy on accepted images is ≥ 0.90.
- Write `artifacts/<model_version>/model_meta.json`, which must validate against `contracts/model_meta.schema.json`, plus `model.pt` (state_dict).
- Also save `reports/val_metrics.json`: top-1, top-3, macro-F1, ECE before and after temperature, and coverage at τ.

### A4. Final evaluation: **once**, after `ml/` code freeze (G3)
`ml/final_eval.py --artifact artifacts/<model_version>`:
1. Appends a line to `reports/TEST_LEDGER.md` *before* reading test: timestamp, git SHA, artifact, reason.
2. On all 4,372 test images:
   - top-1, top-3, macro-F1, per-class precision/recall/F1
   - confusion matrix (`reports/confusion_matrix.png` + JSON)
   - selective accuracy and coverage at τ
3. **95% confidence intervals by cluster bootstrap**: resample `group` ids with replacement, 1,000 resamples.
4. **Prior-weighted top-1**: Σ_class `real_prior` × per-class recall, with `real_prior` from `contracts/categories.json` (real SF photo-report volumes).
5. The same metrics restricted to `reports/claude_baseline_ids.csv` (the 1,020-image subset), so we can compare directly with B's Claude baseline and the cascade.
6. Writes `reports/final_eval.json`. **Commit it untouched.**

If you find a bug after this: fix it, rerun, log the second run in the ledger, and label the new numbers **post-hoc** in every place they appear.

### A5. Model card (by G4)
`reports/MODEL_CARD.md`:
- data source, splits and leakage controls (link PLAN §4)
- backbone and recipe, metrics with confidence intervals, known failure modes (the most confused class pairs from the confusion matrix)
- pretraining-overlap disclosure, and intended use (assistive and human-confirmed; never auto-files)

## What you hand to others
| To | What | When |
|---|---|---|
| B | `model_meta.json` + `model.pt` path, preprocessing confirmed in meta | early checkpoint ~00:30, final by G3 |
| C | `reports/final_eval.json`, `probe_bakeoff.json`, confusion matrix, 3 example wins and 3 honest failures | by G4 |

## Done means (show this evidence in your PRs)
- `reports/probe_bakeoff.json`, `reports/val_metrics.json` and `reports/final_eval.json` are committed, with the commands you ran pasted in the PR.
- B confirms `/classify` returns sensible top-3 for 5 val images you choose.
- TEST_LEDGER has exactly one pre-registered run, or extra runs that are labelled post-hoc.
