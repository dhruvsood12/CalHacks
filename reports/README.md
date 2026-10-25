# reports/

Every number we show anywhere comes from a file here.

| File | Written by | When |
|---|---|---|
| `claude_prompt_dev_ids.csv` | `scripts/make_baseline_subset.py` | pre-registered, before any model (val, 20/class) |
| `claude_baseline_ids.csv` | `scripts/make_baseline_subset.py` | pre-registered, before any model (test, 60/class) |
| `probe_bakeoff.json` | A: `ml/probe.py` | G2 |
| `val_metrics.json` | A: `ml/calibrate.py` | G3 |
| `final_eval.json`, `confusion_matrix.png` | A: `ml/final_eval.py` (once) | after G3 |
| `claude_baseline.json`, `claude_baseline_predictions.csv` | B: `serve/baseline/claude_zeroshot.py` (once) | before G4 |
| `MODEL_CARD.md` | A | G4 |
| `TEST_LEDGER.md` | whoever touches test, before they touch it | always |
