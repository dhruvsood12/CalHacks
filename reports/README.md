# reports/

Every number we show anywhere comes from a file here.

| File | Written by | When |
|---|---|---|
| `claude_prompt_dev_ids.csv` | `scripts/make_baseline_subset.py` | pre-registered, before any model (val, 20/class) |
| `claude_baseline_ids.csv` | `scripts/make_baseline_subset.py` | pre-registered, before any model (test, 60/class) |
| `probe_bakeoff.json` | A: `ml/probe.py` | ~19:45 |
| `val_<run>.json` | B: `eval/val_report.py` | as each run lands |
| `val_metrics.json` | B: `eval/calibrate.py` | G3 |
| `final_eval.json`, `confusion_matrix.png` | B: `eval/final_eval.py` (once) | after G3 |
| `claude_baseline.json`, `claude_baseline_predictions.csv` | B: `eval/claude_zeroshot.py` (once) | before G4 |
| `MODEL_CARD.md` | B (recipe details from A) | G4 |
| `TEST_LEDGER.md` | whoever touches test, before they touch it | always |
