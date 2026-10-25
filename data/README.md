# Dataset: SF 311 street-problem photos

**Source:** [DataSF 311 Cases](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6) (dataset `vw6y-z8j6`), public open data. Check DataSF's terms before any reuse beyond this project. Scraped 2026-10-24.

## What's here
| File | What |
|---|---|
| `scrape_manifest.csv` | Raw scraper output: 30,600 rows (17 classes × 1,800). **Never modified.** |
| `metadata.csv` | 29,571 rows after the leakage purge, with `split`, `geohash` (precision 7), `group`, and `dhash` |
| `train.csv` / `val.csv` / `test.csv` | 20,947 / 4,252 / 4,372 rows (subsets of `metadata.csv`) |
| `SPLIT_MANIFEST.json` | sha256 of every split file, seed, parameters and per-class counts. CI fails if the files drift. |
| `labels.json` | Class list and the SoQL filter that defines each class, plus top agencies at scrape time |
| `scrape_report.json` | Per-class scrape stats (dead links, duplicates, address cap) |
| `images/` | **Not in git** (5.1 GB, gitignored). `images/<label>/<service_request_id>.jpg`, max side 768px. |

## How it was built
1. **Selection** (`scripts/scrape_sf311.py`): requests from 2024-10-01 to 2026-10-01 that have a direct Cloudinary photo (mobile-app reports). Web-form attachment links return HTML, not images, so they're excluded.
   - Candidates are sampled at random offsets across the full date range.
   - At most 3 photos per address per class.
   - sha1 exact-duplicate removal.
   - Images are downscaled to a 768px max side, JPEG q90.
2. **Splits** (`scripts/make_splits.py`, seed 13):
   - Stratified group 7-fold over geohash-7 cells (~150 m blocks); cells that share an address are merged → fold 0 = test, fold 1 = val, folds 2–6 = train.
   - Then **dHash near-duplicate purge** (≤ 6 bits; 137 dropped) and a **50 m same-class buffer** (892 dropped). Both drop only from the train/val side of each pair, so test is untouched.
3. **Audit** (`scripts/verify_data.py`): re-derives every guarantee from the CSVs. Run with `--images` to also decode every file.

## The 17 classes
Index order, display names, primary agencies and real-world volumes: [`contracts/categories.json`](../contracts/categories.json).

## Known limitations
- **Crowd labels.** Residents choose the category, so some labels are wrong or ambiguous, and some photos show more than one problem.
- **Balanced by design.** Real volume is heavily skewed (garbage is 52.5% across these classes). See `real_prior` in `categories.json`.
- **One app.** Mobile-app photos only, so web-form reporters are under-represented.
- **People in photos.** Encampment photos often show people. Never put them in slides, videos or the repo.

## Get images (if you're not the person with the full copy)
```bash
pip install -r scripts/requirements.txt
python3 scripts/fetch_images.py --split val --per-class 20           # quick sample
python3 scripts/fetch_images.py --ids reports/claude_baseline_ids.csv
```
The fetcher verifies the sha1 of each original download against the manifest.
