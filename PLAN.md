# Snap311: master plan

*Working name. Cal Hacks 13.0, submissions due **Sun Oct 25, 9:00 AM PT** (hard). All three of us must be checked in at the venue by 8:00 AM.*

This is the source of truth. If something here is wrong, fix it with a PR. Don't work around it.

**Tasks live in GitHub Issues** (labels `role:A` / `role:B` / `role:C`, milestones G0–G5). Start with the 📌 START HERE issue.

---

## 1. The goal (what exists at 9 AM)

**One sentence:** On a phone (iPhone or Android), a resident photographs a street problem. In one step, with no menus and no pin-dropping:
- **where:** exact GPS location and the nearest address
- **what:** our vision model, fine-tuned on about 30k real SF 311 photo reports (with location as a second signal), names the problem and the agency that usually handles it, or says it isn't sure
- **already reported?** a live check of the city's open reports within 75 m
- **how long:** the typical fix time from the city's own history
- **report:** Claude writes a ready-to-file report in the resident's own language

**Why this beats SF311's app** (full sources in [docs/WHY.md](docs/WHY.md)):
- **SF311 already suggests a category from a photo, so that alone isn't our edge.**
- **Our edge is everything around the photo, each measured on the city's own data** (`docs/evidence/`):
  - **44.4% of new reports** had an earlier same-type report, still open, within 50 m (graffiti 74%, garbage 51%). SF311 shows a "recent requests" list but no duplicate warning before filing. Our check runs automatically at the photo's GPS.
  - **Fix times** vary from hours (garbage, median 0.4 days) to weeks (sidewalks 13 days, trees 51 days). SF311 shows none.
  - **Location is filled in automatically** from GPS or the photo's EXIF. SF311 asks the resident to place a pin.
  - **Location improves the prediction:** location *alone* predicts the category at 16.3% top-1 on held-out blocks, against 5.9% chance. That's a second signal to fuse with the image (§3.7).
  - **Accuracy is measured and calibrated, with "not sure".** SF311 publishes no accuracy.
  - **Any language** through Claude. SF311 offers 5 in the app.
  - **iPhone (iOS 16.4+) and Android, from one codebase.** SF311 v7 needs iOS 26.
  - **Head-to-head accuracy against SF311's own suggestion:** measured on the same val photos (team task). We claim "more accurate" only if that measurement says so.
- **Measured and ruled out:** location does *not* improve agency routing. The nearest past report's agency scored 63.5% against 71.5% for the category's usual agency, so we don't claim it. `docs/evidence/location_signal.json`

**The demo (3-minute pitch, about 60 s of it live):**
1. Open the app on a phone and take or choose a photo (a pothole, a dumped mattress, a broken streetlight). The location pins itself: "📍 3601 Lyon St".
2. In about a second: "Pothole or street pavement damage → usually Public Works, 91%", plus two alternatives.
   - **"Already reported 2 days ago, 38 m away, still open."** Options: add yours as confirmation, or file anyway.
   - **"Similar issues are typically fixed in about 6 days."**
3. Pick Español. Claude writes the report: title, description, what happens next. An English copy goes to the city.
4. An ambiguous photo: the model says **"not sure"**, shows its best guesses, and Claude gives a second opinion. No confident wrong answers.
5. The live map (Convex) shows the new pin appear in real time.
6. One results slide, every number read from a committed `reports/*.json`, on a test set nobody trained or tuned on:
   - our model against the frozen-feature baseline and Claude zero-shot, with 95% confidence intervals
   - accuracy when the model is confident, and how often it is confident

**Success criteria (measured, not assumed):**
- **Fine-tuned vs frozen features:** the fine-tuned model beats the best frozen-feature probe on test macro-F1. **Report the gap with a CI**; published precedent says to expect a few points, not a landslide (WHY §2.6).
- **Top-3 accuracy** high enough that the right category is almost always on screen.
- **Selective accuracy:** at the abstain threshold, accepted test predictions are ≈ 90% correct (the threshold is set with a statistical safety margin on val, §3.5). Coverage is reported.
- **Against Claude zero-shot** (given the same category definitions and a few training examples, so the comparison is fair): either the model wins or the cascade (model, plus Claude when it abstains) wins. We report whichever is true.
- **Geo-prior:** fusing location with the image improves val macro-F1. It's kept only if it does, and test is reported with and without it.
- **Head-to-head with SF311's suggestion** on the same val photos (never submitted): reported whatever the result.
- **Latency:** `/classify` under 300 ms on the server, `/context` under 2 s (live city data). The Claude report arrives in a few seconds.

---

## 2. Where we are now (done, verified)

| Asset | State |
|---|---|
| Dataset | **29,571 photos, 17 classes**, from DataSF 311 Cases ([dataset](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6)). Oct 2024 to Sep 2026, mobile-app photos. |
| Splits | **train 20,947 / val 4,252 / test 4,372**, about 1,190–1,255 / 240–257 / 257–258 per class. sha256 frozen in `data/SPLIT_MANIFEST.json`. |
| Leakage audit | `python3 scripts/verify_data.py --images`: **15/15 checks pass** (§4) |
| Pre-registered evaluation subsets | `reports/claude_baseline_ids.csv` (1,020 test) and `reports/claude_prompt_dev_ids.csv` (340 val), committed before any model existed |
| Images | 5.1 GB, **not in git**. Nirvaan has them. Others pull subsets with `scripts/fetch_images.py` (sha1-verified). |
| Contracts | `contracts/`: categories ↔ agencies ↔ real-world priors, API schemas, the A→B predictor interface |

**Is there enough data?** Yes, by a wide margin for fine-tuning: about **1,230 training images per class**. Published fine-grained benchmarks fine-tune ViT-B to strong accuracy with **~40 images per class** (Stanford Cars: 196 classes, ~8k images). The limiting factor here is **label noise, not quantity**. See WHY §2.6.

**Known data facts that shape the architecture:**
- **Crowd label noise.** Residents pick the category, some photos are taken after the problem was gone, and some show two problems.
- **Fine-grained, overlapping classes:**
  - three car classes: parked on sidewalk, blocking driveway, abandoned
  - four ground-surface classes: sidewalk, pavement, curb ramp, sewer vent cover
- **Phone photos.** 576×768 portrait for about 70% of images, with some landscape and some square.
- **Aspect-ratio shortcut.** 20% of `illegal_posting` photos are square, against 2–4% in other classes. So every image is **cropped** to one fixed shape: never padded, never squashed.
- **Balanced on purpose.** The real world is not: garbage is **52.5%** of real photo reports across these classes (`contracts/categories.json` → `real_prior`). We also report a prior-weighted number.

---

## 3. Model architecture

### 3.1 Task framing
- **Input:** RGB pixels only. **No metadata.** `agency_responsible` is derived from the label, so feeding it in would leak the answer.
- **Output:** 17-way softmax, calibrated, plus an **abstain** decision. Single-label training, top-3 at inference: the user confirms, which handles photos showing more than one problem.

### 3.2 Why fine-tune pretrained backbones (and not the alternatives)
| Option | Verdict |
|---|---|
| Train from scratch | No. Too little data per class, and no time. |
| **Fine-tune pretrained vision backbones (chosen)** | Standard practice for fine-grained classification. 1,230 images per class is far above what published fine-grained benchmarks need. |
| Frozen features + linear probe only | It's our **baseline**. Fine-tuning reliably beats it on fine-grained tasks (VPT table: Stanford Cars 51 → 85). |
| LoRA / prompt-tuning (PEFT) | Matches full fine-tuning in low-data settings; no evidence it beats full fine-tuning at our scale. Skip it. |
| Fine-tune a VLM to generate text | Slower, harder to evaluate, more ways to fail. Claude covers the language side. |
| Claude zero-shot only | Doesn't know SF's category conventions. General VLMs trail specialised classifiers on classification. Kept as **a baseline and the fallback when the model abstains**. |

### 3.3 The three backbones (best open option in each family, all one-line downloads)
Verified on Hugging Face: all three are **Apache-2.0, ungated, available in `timm`**.

| Family | Model (timm name) | Why it's here |
|---|---|---|
| Image–text contrastive | **SigLIP 2 ViT-B/16 @ 384** (`vit_base_patch16_siglip_384.v2_webli`) | Strongest open image–text encoder at this size. Reads text in photos (postings, signs) and knows scene semantics. |
| Self-supervised | **DINOv2 ViT-B/14 @ 378** (`vit_base_patch14_dinov2.lvd142m`) | The standard frozen-feature backbone. Strong on texture and fine detail (cracks vs potholes vs curb ramps). |
| Supervised CNN | **ConvNeXt-B IN-22k @ 384** (`convnext_base.fb_in22k_ft_in1k_384`) | A different architecture, so its mistakes differ (good for ensembling). Cheap to train and serve. |

Considered and rejected:
- **DINOv3:** custom non-OSI license with attribution and use restrictions; no verified advantage on image-level classification at this size.
- **ConvNeXt V2:** CC-BY-NC, non-commercial.
- **EVA-02-B @ 448:** MIT and strong, but about 2.4× the compute of ConvNeXt-B.
- **Meta PE-Core-B:** 224 px only, and small details matter here.

**We fine-tune all three. Selecting by a frozen probe isn't safe:** probe rank doesn't reliably predict fine-tuned rank (the MAE paper's tables; Kornblith 2019). The frozen probes still run first: they are the baseline, they initialize the heads (LP-FT), and they choose the crop mode quickly.

### 3.4 Training recipe (LP-FT), and what's decided on val
1. **Crop-mode check (minutes, on frozen probes):** square center-crop vs a fixed **3:4** crop (which keeps the whole frame of the ~70% portrait photos). Both crop to one shape, so the aspect-ratio shortcut can't leak. Pick by val macro-F1 per backbone. Never pad or squash.
2. **LP-FT:** the head is initialized from the frozen linear probe, then all layers are unfrozen. LP-FT matched or beat plain fine-tuning in distribution and helped most on shifted data (Kumar et al. 2022), which matches our live-demo photos.
3. **Default recipe (run 1 for each backbone):**
   - AdamW, wd 0.05, **layer-wise LR decay 0.75**
   - learning rate 5e-5 for the top block, 1e-3 for the head
   - cosine schedule, 1 warmup epoch, 10 epochs, keep the best epoch by val macro-F1
   - bf16, gradient clip 1.0, batch 64
   - **label smoothing 0.1**
   - Augmentation: RandomResizedCrop (scale 0.5–1) at the chosen aspect, horizontal flip, mild ColorJitter, rotation ±10°. **No CutMix/Mixup** (it pastes a pothole into a graffiti photo). **No vertical flips.**
4. **Alternative recipe (run 2, on the top-2 backbones):**
   - learning rate 1e-4, LLRD 0.65 (the "CLIP is a strong fine-tuner" setting)
   - **label smoothing 0**: label smoothing can hurt confidence ranking for abstention (Xia et al. 2025)
   - The better run per backbone is chosen on val.
5. **Ensemble:** average the softmax probabilities of the best run of each top-2/top-3 backbone, if val macro-F1 improves. Ensembles also improve calibration.
6. **Test-time augmentation:** horizontal flip, averaged. Kept only if val improves.
7. **Stretch (val-gated):** confident-learning cleanup. Out-of-fold frozen-probe predictions flag likely-mislabeled **train** images; drop at most 5% and retrain. **Never clean val or test.**

### 3.5 Calibration and abstention (B)
- **Temperature scaling** on val, fitted to the **final** model or ensemble.
- **Abstain threshold:** the smallest max-probability where the **lower 95% bound** (Clopper–Pearson) of val selective accuracy is ≥ 0.90. A threshold tuned to exactly 90% on val misses on test about half the time; the margin fixes that.
- Report the risk–coverage curve and AURC on val. Coverage on test is reported with a CI.
- **In the product:** when the model abstains, show the top 3, ask Claude for a second opinion, and the user picks. This is also how non-street photos are handled.

### 3.6 Evaluation protocol (the anti-self-deception rules)
- **The trainer never touches test.** A trains; B evaluates. Only B's `eval/final_eval.py` and `eval/claude_zeroshot.py` may read test (CI-enforced).
- **Test is run once**, after the `ml/` code freeze at G3, logged in `reports/TEST_LEDGER.md` beforehand. Any re-run is labelled **post-hoc**.
- **Metrics:**
  - top-1, top-3, macro-F1, per-class F1, confusion matrix, ECE
  - selective accuracy and coverage at τ, and AURC
  - **95% CIs from a cluster bootstrap over map-block groups**
  - prior-weighted top-1
- **Baselines on the same frozen subset:**
  - chance (5.9%)
  - the best frozen probe
  - Claude zero-shot: same category definitions plus a few **train** examples; prompt tuned on val, frozen before test
  - the cascade (model, with Claude when it abstains)
- **Optional label audit (B):** hand-check about 170 val photos (10 per class) to estimate how often the crowd label is wrong. That's the realistic accuracy ceiling, and a good line for the pitch.
- **Every number on a slide, in the README or on Devpost** comes from a committed JSON in `reports/`.

### 3.7 Geo-prior: location as a second signal (A builds, B tunes and evaluates)
**Precedent:** location priors improve fine-grained image classification. On iNaturalist, combining an image model with p(class | location) raised accuracy (Mac Aodha et al., "Presence-Only Geographical Priors for Fine-Grained Image Classification", ICCV 2019). Our own measurement: location alone gets 16.3% top-1 on held-out blocks against 5.9% chance.

**Design (no leakage):**
- **Source:** DataSF cases of the same 17 class definitions, all sources, **filed 2022-10-01 → 2024-09-30, strictly before our dataset window**. No case overlaps train, val or test, and nothing comes from the future.
- **Table:** counts per (geohash-6 cell, class), smoothed toward the citywide class distribution: p(c|cell) = (n_cell,c + α·p(c)) / (n_cell + α).
- **Feature:** the **lift** L(c|cell) = p(c|cell) / p(c), meaning "how much more common this class is *here* than citywide". Using the lift instead of raw frequency stops the prior pushing everything toward garbage, the most common class citywide.
- **Fusion at inference:** log p(c|img, loc) ∝ log p(c|img) + β · log L(c|cell). **β is tuned on val by B**, and β = 0 means off. Temperature and the abstain threshold are fitted after fusion.
- The network still sees **pixels only**. Location enters only through this transparent, inspectable table, and only when the phone sends `lat`/`lng`.
- **Reported on test both with and without the prior,** so the image model's own accuracy is never hidden.

---

## 4. Data leakage controls (what's enforced, and where)

| Leakage path | Control | Enforced by |
|---|---|---|
| Same photo in two splits | sha1 dedupe at scrape time | `verify_data.py` |
| Same object or spot (repeat reporters) | **Spatial grouping** by geohash-7 cell (~150 m). Cells that share an address are merged (fixed 87 GPS-jitter cases). | `verify_data.py` |
| Same object straddling neighbouring blocks | **50 m same-class buffer** (dropped 892 train/val photos) | `verify_data.py` (0 pairs) |
| Near-identical re-uploads | **dHash ≤ 6 bits** across splits (137 dropped) | `verify_data.py` (0 pairs) |
| One reporter dominating a class | At most 3 photos per address per class at scrape time | `scrape_sf311.py` |
| Metadata shortcut | The network sees pixels only. Location enters only through the geo-prior (§3.7). | Code review of `ml/data.py` |
| Geo-prior leaking held-out cases | The prior is built only from cases filed **before** 2024-10-01 (the dataset starts then); β is tuned on val | `ml/geoprior.py` asserts the date bound |
| Aspect-ratio shortcut | Fixed-shape crop, no pad, no squash | Code review of `ml/data.py` |
| Tuning on test (hyperparameters, crop, ensemble, threshold, prompt) | Val for every decision; test once; trainer ≠ evaluator | `guard_repo.py` in CI + TEST_LEDGER |
| Split files edited | sha256 frozen in `SPLIT_MANIFEST.json` | `verify_data.py` in CI |
| Backbone pretraining overlap | Can't be ruled out. The photos sit behind SF's own Cloudinary account, so overlap is unlikely. **Disclosed** in the model card. | n/a |

Precedent for why this matters: random hold-outs on spatially autocorrelated imagery overstated CNN accuracy by up to 28% (Kattenborn et al. 2022). See WHY §2.5.

---

## 5. System architecture

```
 Mobile app (mobile/, Expo React Native, iOS + Android)       Convex (convex/)
   │ photo → JPEG ≤1280px, GPS, language                      ▲ reports table (no photos)
   ▼                                                           │ live subscription → react-native-maps pins
 Inference API (serve/, FastAPI on the GPU box, HTTPS via cloudflared)
   ├── POST /classify ── ml/infer.py Predictor (A) + geo-prior (A, β from B) + calibration (B) → top-3, abstain
   ├── GET  /context ─── serve/citydata.py (B) → live DataSF: open same-type reports ≤75 m, typical fix time
   ├── POST /report ──── serve/claude_report.py (B) → claude-opus-5-5 vision + structured output
   └── GET  /health
```
**Nobody waits on anybody:**
- C builds against `contracts/examples` through an in-app `MockAPI`.
- A's API serves a stub classifier until the model exists.
- B builds the metrics on synthetic logits, then real `val_logits.npz` files as A's runs finish.

---

## 6. Team split: two people on the model, one on the app

The model is most of the work, so two people work on it, split the way serious ML teams split it: **one person trains, a different person judges.** That separation is itself a guard against inflated results.

| | Owner | Lane | Builds | Hands off |
|---|---|---|---|---|
| **A: Training + API host** | Nirvaan (GPU + images) | `ml/`, `serve/app.py`, `serve/classifier.py`, `serve/tests/` | data pipeline, frozen probes, LP-FT on 3 backbones, recipe variants, ensemble, `ml/infer.py`, the **geo-prior table**, the API on the GPU box | `val_logits.npz` per run → B; the artifact → B; the API URL → C |
| **B: Evaluation + Claude + city data** | *(fill in)* | `eval/`, `reports/`, `serve/claude_report.py`, `serve/citydata.py`, `serve/prompts/` | metrics with bootstrap CIs, the val decision tables, geo-prior β, calibration and abstain threshold, the `/context` city-data lookups, the Claude report writer, Claude zero-shot baseline, **the one test run**, model card | decision tables → A; calibrated artifact → A; numbers → C |
| **C: mobile app + submission** | *(fill in)* | `mobile/`, `convex/` | Expo React Native app (iOS + Android), **automatic geotagging** (GPS / photo EXIF + address), the "already reported?" and fix-time cards, react-native-maps + Convex live map, languages, emergency and abstain UX, demo video, Devpost | the demo and the submission |

**Why not split the GPU work across three people?** With one GPU, training runs back to back no matter who launches them, and splitting the launches only adds coordination. What *can* run in parallel is everything around the GPU: evaluation, calibration, Claude, and the app. That's how the work is cut.
- If B or C can get a **second GPU** (e.g. the Vultr credits from the MLH prize), the obvious use is running backbone 3 and the recipe variants in parallel on it. Same code, same configs.

**Briefs** (paste into each person's Claude session):
- [A: training](docs/roles/A-training.md)
- [B: evaluation + Claude](docs/roles/B-eval-claude.md)
- [C: mobile app](docs/roles/C-ios-app.md)

**Shared files:** `contracts/`, `data/`, `scripts/`, `PLAN.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `docs/`, `.github/`. These change only in a `shared`-labelled PR with both other approvals.

---

## 7. Timeline and gates (PT, Sat → Sun)

| Gate | Time | Exit criteria |
|---|---|---|
| **G0 Setup** | 19:15 | Everyone has read PLAN + their brief. Roles decided (§10). Environments installed. Own API keys in `.env`. Images on the GPU box. PR #1 merged. |
| **G1 Contracts frozen** | 20:00 | A's stub API answers over HTTPS. C's app runs on `MockAPI`. B's metrics tests run on synthetic logits. Frozen probes done (`probe_bakeoff.json`). |
| **G2 Backbones compared** | 23:00 | All three LP-FT runs are done or nearly done. B's val table posted. Claude `/report` is real. C's app calls the real API from a physical phone. |
| **G3 Integration** | 02:00 | Variants done, ensemble chosen on val, calibrated by B. The real model is behind `/classify`. Full flow on a phone, including the live map. **`ml/` code freeze**, then B's final eval (once). |
| **G4 Feature freeze** | 05:00 | `final_eval.json`, `claude_baseline.json` and `MODEL_CARD.md` committed. Bug fixes only. |
| **G5 Story done** | 07:00 | Demo video recorded. Devpost complete. |
| **Submit** | **07:45** | Submitted, all teammates listed. Buffer before 9:00. |

GPU queue (A):
1. probes and the crop check: 19:15–20:00
2. LP-FT × 3: 20:00–~22:45
3. variants on the top 2: ~22:45–01:00
4. ensemble and export: by 01:30

Sleep in shifts after G3. Never leave the merge queue without an owner.

---

## 8. Prize targeting (only claim what we really use)

| Prize | Why we qualify | Evidence owner |
|---|---|---|
| **[Anthropic] Claude for Public Benefit** (primary) | Claude drives the report: vision, structured output, multilingual access, the second opinion when the model is unsure, plus a measured zero-shot baseline | B (code), C (story) |
| **Cal Hacks Best People-First Social Impact** | Language access to city services. Fewer misrouted reports. | C |
| **Cal Hacks Most Technically Complex** | Three fine-tuned backbones, an ensemble, calibrated selective prediction, a spatial-leakage-proof evaluation | A + B |
| **Cal Hacks overall (1st–3rd)** | Mapped to the judging criteria below | all |
| **[Convex] Best use of Convex** | **Only if** the live map really runs on Convex live subscriptions (`useQuery` from the `convex` React client) | C |
| **[MLH] Best Use of Vultr** | **Only if** a GPU or the API actually runs on Vultr | A |
| **[Microsoft] Built for the Real World** | Real city data, real routing, honest evaluation | C |

C confirms the Anthropic prize's eligibility rules (Hive / Slack #ask-directors) at G0.

**How the plan maps to the Cal Hacks judging criteria:**
- **Application:** real SF data and agencies, person-in-the-loop.
- **Intentionality:** language access, "not sure" instead of confident wrong answers, confirmation before filing.
- **Functionality:** a native mobile demo (iOS and Android) plus a recorded video.
- **Creativity:** a city's own crowd reports turned into a routing model, with Claude as a multilingual civic assistant.
- **Technical complexity:**
  - 3 backbones, LP-FT, an ensemble, plus an image × location geo-prior
  - live duplicate detection against city data
  - calibrated abstention with a statistical safety margin
  - a spatially grouped, leakage-audited split
  - cluster-bootstrap CIs and a trainer/evaluator separation

---

## 9. Product guardrails (the ethics we'll get asked about)

- **We never file to the real SF 311** in the demo. We produce a ready-to-file report and link to sf311.org.
- **Danger** (downed wire, gas, fire, injury): the app shows "Call 911", not a filing flow.
- **Encampment photos show people.** None in slides, video, screenshots or the repo. The product frames this class as "request outreach services", not enforcement.
- No user photos are stored. Convex stores the category, coordinates and text only.
- If DINOv3 is ever used, add a "Built with DINOv3" credit (license term). The current plan uses DINOv2 (Apache-2.0).

---

## 10. Open decisions (settle at G0 in the "G0: team decisions" issue)

1. **Who is B and who is C?** Plus GitHub handles for `.github/CODEOWNERS`.
2. **GPU model and memory.** This sets batch size and whether all three backbones plus variants fit before G3.
3. **Who has an iOS 26 iPhone** for the SF311 head-to-head (about 20–40 val photos through SF311's photo suggestion; **never press submit**)?
4. **Keep the `encampment` class?** Recommendation: keep it in the model (it's real 311 volume, and dropping it would misroute those photos) and apply the §9 guardrails. Dropping it costs nothing if decided before G2.
5. **Product name.**
