# Role B: Evaluation, calibration and Claude (owner: fill in)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`. Read PLAN §3.5–§4 first.

**Your lane:** `eval/`, `reports/`, and `serve/claude_report.py` (+ `serve/prompts/`).

**You're the half of the model team that judges it.**
- A trains. You decide what the numbers are, whether they're real, and how confident the model is allowed to be.
- You are the **only person who reads test data**. You also own Claude: both the live report writer and the zero-shot baseline the model has to beat.
- You need no GPU until the final eval.

## Inputs
- `runs/<run>/val_logits.npz` from A, one per finished training run. Format: `contracts/predictor.md`.
- `ml/infer.py` (A) → `Predictor.from_artifact(dir).logits(paths)`. You call it in `final_eval.py`.
- `reports/claude_prompt_dev_ids.csv` (340 val images) and `reports/claude_baseline_ids.csv` (1,020 test images): **pre-registered before any model existed.**
- Images:
  ```bash
  python3 scripts/fetch_images.py --ids reports/claude_prompt_dev_ids.csv
  ```
  Do the same for the baseline ids when you're ready to run the baseline. Files are verified by sha1.

## Steps
### B0. Environment (by G0, 19:15)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r eval/requirements.txt   # numpy scipy scikit-learn pandas matplotlib anthropic pydantic pillow
cp .env.example .env                   # your own ANTHROPIC_API_KEY; never paste it anywhere
```

### B1. Metrics library, built on synthetic logits first (by ~21:00)
`eval/metrics.py`, unit-tested in `eval/tests/` with synthetic logits so it's correct before real ones arrive:
- top-1, top-3, macro-F1, per-class precision/recall/F1, confusion matrix
- ECE (15 bins), before and after temperature scaling
- **selective accuracy and coverage** at a threshold, the full risk–coverage curve, and **AURC** (area under it, lower is better)
- a **Clopper–Pearson lower bound** on selective accuracy
- **cluster bootstrap 95% CI**: resample `group` ids (from `data/*.csv`) with replacement, 1,000 resamples
- **prior-weighted top-1**: Σ `real_prior[c]` × recall[c], with `real_prior` from `contracts/categories.json`

### B2. Val dashboard + calibration (as each `val_logits.npz` lands)
- `eval/val_report.py --runs ...` → `reports/val_<run>.json` + confusion matrix PNG.
  - Post the val table (macro-F1, top-1, top-3, AURC, each with a bootstrap CI) in team chat after every run. **It decides:**
    - the crop mode
    - which 2 backbones get the alternative recipe
    - default vs alternative recipe per backbone
    - single model vs ensemble (greedy: add a member only if val macro-F1 improves)
    - whether flip test-time augmentation stays
- `eval/calibrate.py --artifact artifacts/<v>`:
  - fit the temperature on the **final model or ensemble's** val outputs (one scalar, minimize negative log-likelihood)
  - set `abstain_threshold` = the smallest max-probability where the **Clopper–Pearson lower 95% bound** of val selective accuracy is ≥ 0.90. Without the margin, test misses 90% about half the time.
  - write both into the artifact's `model_meta.json`, plus `reports/val_metrics.json`
- **Error analysis (val only):** the top 5 confused class pairs, with 3 example images each. Never use encampment photos in anything shared. This feeds the model card and the pitch's "honest limitations".
- **Optional label audit (~20 min):** hand-check 10 val photos per class (170 total) and record whether the crowd label is right → `reports/label_audit.json`. That gives the realistic accuracy ceiling, and a strong line for Q&A.

### B3. Claude report writer (by G2, 23:00)
`serve/claude_report.py`. A's `serve/app.py` calls `write_report(request_dict) -> dict`:
- **Model:** `claude-opus-5-5` via the official `anthropic` SDK, with `output_config={"effort": "low"}`.
  - Don't send `temperature`/`top_p`/`top_k`, and don't disable thinking. Both return a 400.
- **Image:** a base64 `image` content block before the text.
- **Output:** `client.messages.parse(..., output_format=Report)`, where `Report` is a Pydantic mirror of `contracts/report.response.schema.json`.
- **Refusals:** check `stop_reason == "refusal"`. Enable server-side fallbacks (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"` on the beta client). If your SDK version rejects that, fall back to returning the classification only.
- **Prompt** (`serve/prompts/report_v1.txt`):
  - **Inputs:** the 17 categories with display names and agencies, the classifier's top-3 and its abstain flag, the user's language, location and note.
  - **Claude:**
    - confirms or overrides the category (one of the 17, or `not_a_311_issue`)
    - writes the text in the user's language **and** in English
    - says what happens next
    - sets `emergency=true` for danger such as wires, gas, fire or injury
- **Never** call any SF 311 endpoint. Use a 30 s timeout. On failure, A's API returns 503 and the app shows the classification without a report.

### B4. Claude zero-shot baseline (prompt frozen on val by ~00:00; test run by G4)
`eval/claude_zeroshot.py`:
1. Develop the prompt **on the 340 val images only**: the class list, display names, one-line SF definitions, and **2 example photos per class drawn from train** (never val or test). That makes it a fair comparison, not a straw man.
2. **Commit `eval/prompts/zeroshot_v1.txt` before touching test.** The git history order is the evidence.
3. Run 20 test images first and post the cost estimate. Then run all 1,020 with the Message Batches API (results come back in any order, so key them by `custom_id`; refusals count as wrong).
   - Add a `reports/TEST_LEDGER.md` line **before** the run.
4. Write `reports/claude_baseline.json` and `reports/claude_baseline_predictions.csv`.

### B5. Final evaluation: **once**, after A's `ml/` freeze at G3
`eval/final_eval.py --artifact artifacts/<final>`:
1. Ledger line first.
2. Predict all 4,372 test images with `Predictor`. The GPU box is fastest; CPU takes about 15 min.
3. Compute everything from B1 at the calibrated threshold.
4. Repeat on the 1,020-image subset for:
   - the model vs Claude zero-shot vs **the cascade** (model, with Claude's answer when the model abstains)
   - the best frozen probe (A's probe weights, applied to test features inside this script)
5. Writes `reports/final_eval.json` + `reports/confusion_matrix.png`. **Commit untouched.** Any later run is labelled **post-hoc**.

### B6. Numbers for the story (by G4, 05:00)
- `reports/MODEL_CARD.md`:
  - data, splits and leakage controls (link PLAN §4)
  - the recipe (from A), and metrics with confidence intervals
  - failure modes, pretraining-overlap disclosure, and "Built with DINOv3" if it's in the final model
- Give C the results slide content: every number with its JSON path.

## Done means
- `eval/tests` passes in CI.
- `reports/val_metrics.json`, `claude_baseline.json` and `final_eval.json` are committed, and TEST_LEDGER shows pre-registered runs only.
- The live `/report` round trip is demonstrated from the iPhone (C's screenshot) in your G2/G3 PR.
