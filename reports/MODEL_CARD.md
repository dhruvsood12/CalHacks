# Model card: Snap311 street-problem classifier

*Owner: B. Every number below is copied from a committed `reports/*.json` and cites its path. Fields marked `TBD` are filled at G4 from the named file; nothing is typed from memory.*

## 1. What it is
A 17-way image classifier that maps a resident's photo of a street problem to the SF 311 category (and so the agency) it is usually filed under, with a calibrated probability and an explicit **abstain** decision. Location enters only through a transparent geo-prior table (PLAN §3.7), never through the network. Claude writes the report text and gives a second opinion when the model abstains.

- **Model version:** `TBD` ← `reports/final_eval.json: model_version`
- **Members / backbones:** `TBD` ← `reports/val_metrics.json: members[].timm_name` (recipe from A: `runs/<run>/config`)
- **Inputs:** RGB pixels, short side resized then centre-cropped (never padded or squashed); crop mode chosen on val per backbone ← `reports/probe_bakeoff.json: chosen_crop_mode`
- **Outputs:** 17 calibrated probabilities (temperature `TBD` ← `reports/val_metrics.json: temperature`), top-3, `abstain = max_prob < TBD` ← `reports/val_metrics.json: abstain_threshold`

## 2. Data
- **Source:** DataSF 311 Cases (`vw6y-z8j6`), mobile-app reports with a direct photo, filed 2024-10-01 → 2026-10-01, 17 classes × 1,800 scraped → 29,571 after the leakage purge (`data/SPLIT_MANIFEST.json: input_rows, dropped`).
- **Splits:** train / val / test = 20,947 / 4,252 / 4,372 (`data/SPLIT_MANIFEST.json: counts`). Stratified group 7-fold over geohash-7 cells (~150 m blocks), cells sharing an address merged; fold 0 = test, fold 1 = val.
- **Leakage controls (PLAN §4):** sha1 exact dedupe; dHash ≤ 6-bit near-duplicate purge across splits (137 dropped); 50 m same-class buffer (892 dropped); ≤ 3 photos per address per class; split files frozen by sha256 and audited in CI by `scripts/verify_data.py`. Trainer (A) never reads test; evaluator (B) ran test **once**: `reports/TEST_LEDGER.md`.
- **Labels are crowd labels.** Residents chose the category, so some are wrong or ambiguous. **Label audit** (`reports/label_audit.json`, 10 val photos per class, 170 total, one look each): the crowd label is clearly right for **68.8%** (`overall.label_correct_rate`), right or defensible for **83.5%** (`overall.label_defensible_rate`), clearly another category for **2.9%** (`overall.clearly_wrong_rate`), and **13.5%** of photos do not show the problem at all (`overall.unclear`, 23/170). So a classifier scored against these labels tops out around 80–85% top-1, and the hardest classes are the ones where residents disagree with SF's own definitions: curb ramp vs sidewalk vs vent cover (`per_class.curb_ramp_defect`: 1/10 clearly right), residential bins filed as "public trash can" (`per_class.litter_receptacle`: 3/10).
- **Class balance:** balanced by construction; real volume is heavily skewed (garbage 52.5%: `contracts/categories.json: real_prior`). We therefore also report **prior-weighted top-1**.

## 3. Training recipe (from A)
`TBD` ← A's G3 PR: LP-FT (head initialised from the frozen linear probe, then all layers unfrozen), AdamW wd 0.05, layer-wise LR decay, cosine schedule, 10 epochs, bf16, batch 64; default vs alternative recipe chosen on val (`reports/val_<run>.json`). GPU and wall-clock per run: `TBD` (A).

## 4. Evaluation protocol
All model decisions (crop mode, recipe, ensemble members, TTA, temperature, abstain threshold, geo-prior β, Claude prompt) were made on **val**. Test was evaluated once by `eval/final_eval.py` after the `ml/` freeze; 95% CIs are a **cluster bootstrap over map-block groups** (1,000 resamples), which is what makes them honest for spatially clustered photos.

### 4.1 Headline (test, n = 4,372) ← `reports/final_eval.json`
| Metric | Value [95% CI] | JSON path |
|---|---|---|
| Top-1 | `TBD` | `with_geo_prior.top1`, `with_geo_prior.ci95.top1` |
| Top-3 | `TBD` | `with_geo_prior.top3` |
| Macro-F1 | `TBD` | `with_geo_prior.macro_f1`, `.ci95.macro_f1` |
| Prior-weighted top-1 | `TBD` | `with_geo_prior.prior_weighted_top1` |
| ECE (15 bins, after temperature) | `TBD` | `with_geo_prior.ece` (uncalibrated: `.ece_uncalibrated`) |
| AURC (lower is better) | `TBD` | `with_geo_prior.aurc` |
| Coverage at the abstain threshold | `TBD` | `with_geo_prior.selective.coverage`, `.ci95.coverage` |
| Selective accuracy when it answers | `TBD` (lower-95% bound `TBD`) | `with_geo_prior.selective.selective_accuracy`, `.selective_accuracy_lower95` |
| **Without** the geo-prior (image only) | top-1 `TBD`, macro-F1 `TBD` | `without_geo_prior.top1`, `.macro_f1` |

Confusion matrix: `reports/confusion_matrix.png`. Most confused pairs: `TBD` ← `final_eval.json: top_confusions`.

### 4.2 Baselines on the same pre-registered 1,020-image test subset ← `final_eval.json: subset_1020`
| System | Top-1 [95% CI] | Macro-F1 | JSON path |
|---|---|---|---|
| Chance | 5.9% | – | `subset_1020.chance_top1` |
| Best frozen linear probe | `TBD` | `TBD` | `subset_1020.best_frozen_probe` |
| Claude zero-shot (definitions + 2 train examples/class, prompt frozen on val) | `TBD` | `TBD` | `subset_1020.claude_zeroshot`, `reports/claude_baseline.json` |
| **Fine-tuned model** | `TBD` | `TBD` | `subset_1020.model` |
| Cascade (model; Claude when it abstains) | `TBD` | `TBD` | `subset_1020.cascade_model_then_claude_on_abstain` |

### 4.3 Calibration and abstention (val) ← `reports/val_metrics.json`
Temperature `TBD`, abstain threshold `TBD` = smallest max-probability whose Clopper-Pearson lower-95% bound on val selective accuracy is ≥ 0.90 (`abstain_rule`). Val coverage at that threshold `TBD` (`selective.coverage`). Geo-prior β `TBD` chosen by val macro-F1 with AURC as tie-break (`geo_prior.sweep`).

## 5. Known failure modes and limitations
- `TBD` from the val error analysis (`reports/val_<final>.json: top_confusions`), typically: sidewalk vs curb-ramp vs pavement damage; garbage next to a trash can vs the can itself; posters vs graffiti; the three car categories when the camera angle hides the driveway or curb.
- Photos that are not street problems: handled by abstention + Claude's `not_a_311_issue`, not by a trained "other" class.
- Only mobile-app photos were scraped, so web-form reporters are under-represented; photos are ≤ 768 px.
- **Pretraining overlap** with the backbones' web-scale data cannot be ruled out. The photos sit behind SF's own Cloudinary account, so overlap is unlikely, but it is undisclosed by the backbone providers.
- Encampment photos show people. The class is kept so those photos route to outreach rather than being misfiled; no encampment image appears in any shared material (PLAN §9).
- SF311's own photo suggestion has no published accuracy; we never claim to beat it unless `reports/sf311_app_check.csv` exists.

## 6. City-context features (not model outputs, measured on city data)
- 44.4% of new reports had a same-type report still open within 50 m (window 2025-06-15..29): `docs/evidence/city_context_stats.json: overall`. Second window 2025-11-01..15: **36.8%** (`reports/city_context_stats_2025-11-01.json: overall.already_open_nearby_pct`), with the same ordering by class (graffiti 69.6%, garbage 42.0%, blocking driveway 6.0%: `per_class.*.already_open_nearby_pct`). The headline is "about 4 in 10", stable across seasons.
- Live "already reported?" and fix-time lookups: `serve/citydata.py` (open same-type reports within 75 m in the last 30 days; median / p75 days-to-close over the last 12 months, per supervisor district where n ≥ 30).

## 7. Licences and credits
Backbones (timm): SigLIP 2 ViT-B/16 384 (Apache-2.0), DINOv2 ViT-B/14 (Apache-2.0), ConvNeXt-B IN-22k (Apache-2.0). Data: DataSF 311 Cases, open data. Report text: `claude-opus-5-5`. *No DINOv3 was used.*
