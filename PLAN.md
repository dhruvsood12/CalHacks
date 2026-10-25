# Snap311: master plan

*Working name. Cal Hacks 13.0, submissions due **Sun Oct 25, 9:00 AM PT** (hard). All three of us must be checked in at the venue by 8:00 AM.*

This is the source of truth. If something here is wrong, fix it with a PR. Don't work around it.

---

## 1. The goal (what exists at 9 AM)

**One sentence:** A resident snaps a photo of a street problem. Our fine-tuned vision model, trained on about 30k real SF 311 reports, names the problem and the city agency that handles it. Claude then writes a ready-to-file 311 report in the resident's own language.

**The demo (3-minute pitch, about 60 s of it live):**
1. Open the app on a phone and take or upload a photo (a pothole, a dumped mattress, a broken streetlight).
2. In under a second: "Pothole or street pavement damage → Public Works, Street and Sewer Repair, 91% confident", plus the top 3 alternatives.
3. Pick a language (e.g. Español). Claude writes the report: title, description, what happens next. A copy in English goes to the city.
4. Low-confidence or unclear photo: the model **abstains** and Claude gives a second opinion. Nobody gets a confident wrong answer.
5. The live map (Convex) shows the report appear in real time.
6. One slide of numbers, every one read from a committed JSON report on a test set we never trained or tuned on:
   - our model against a frozen-feature baseline and against Claude zero-shot, with 95% confidence intervals
   - per-class F1
   - accuracy at the abstention threshold

**What "the model performs well" means. These are the success criteria, and they're measured, not assumed:**
- **Top-1 and macro-F1** on the locked test set clearly beat the frozen linear probe. Report the confidence intervals, and no claims without them.
- **Top-3 accuracy** is high enough that the right category is almost always on screen.
- **Selective accuracy:** a confidence threshold chosen on val yields ≥ 90% accuracy on the test images the model accepts, and we report what fraction it accepts.
- **Against Claude zero-shot** on the same frozen test subset: either we win (domain-specific SF taxonomy beats general knowledge) or the cascade (model, plus Claude when it abstains) wins. Both are honest, interesting results. We report whichever is true.
- **Latency:** model under 200 ms per photo. Claude report streams in a few seconds.

---

## 2. Where we are now (done, verified)

| Asset | State |
|---|---|
| Dataset | **29,571 photos, 17 classes**, from DataSF 311 Cases ([dataset](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6)). Requests from Oct 2024 to Sep 2026, mobile-app photos only. |
| Splits | **train 20,947 / val 4,252 / test 4,372**, about 1,190–1,255 / 240–257 / 257–258 per class. Frozen: sha256 values are in `data/SPLIT_MANIFEST.json`. |
| Leakage audit | `python3 scripts/verify_data.py --images`: **15/15 checks pass** (see §4) |
| Images | ~5.1 GB, **not in git**. Nirvaan has them. Others pull subsets with `scripts/fetch_images.py`. |
| Category contract | `contracts/categories.json`: label ↔ index ↔ display name ↔ city agency |

Known data facts that shape the architecture:
- **Label noise is real.** Residents pick the category themselves. Some photos are taken after the problem was gone (encampments), and some show two problems at once. Expect a top-1 ceiling well below 100%.
- **Fine-grained, overlapping classes.** Three car classes (parked on sidewalk, blocking driveway, abandoned) and four ground-surface classes (sidewalk, pavement, curb ramp, vent cover). The difference is context and texture, not object identity.
- **Phone photos:** mostly 576×768 portrait, outdoors, varied light.
- **Aspect-ratio shortcut found:** 20% of `illegal_posting` photos are square, against 2–4% in other classes. That's why we **crop to a square and never pad** (§3.4).
- **Not a deployment prior:** the classes are balanced, but in the real stream of photo reports across our 17 classes, garbage is **52.5%** and sewer vent covers 0.4% (counts are in `contracts/categories.json` → `real_prior`). Real-world accuracy will differ, so we report a prior-weighted number too (§3.6).

---

## 3. Model architecture (decision and reasons)

### 3.1 Task framing
- **Input:** RGB pixels only. **No metadata** (agency, neighborhood, time, address). `agency_responsible` is derived from the label, so feeding it in would leak the answer.
- **Output:** a softmax over 17 classes, calibrated, plus an **abstain** decision.
- **Single-label training, top-3 at inference.** The UI shows the top 3 and the user confirms. That's how a single-label model handles multi-issue photos honestly.

### 3.2 Why fine-tune a pretrained vision backbone (and not the alternatives)
| Option | Verdict |
|---|---|
| Train a CNN from scratch | No. About 1.2k images per class is far too few, and it won't converge in our time window. |
| **Fine-tune a pretrained foundation backbone (chosen)** | Best accuracy per GPU-hour. Strong priors for street scenes, text in images (postings, signs) and textures (cracks). It trains in about 15–40 minutes. |
| Fine-tune a vision-language model (LoRA) to generate text | Slower, harder to evaluate, and more ways to fail overnight. Claude already covers the language side. |
| Claude zero-shot only | No trained model, and it doesn't know SF's own category conventions. We keep it as **a baseline and as the fallback when the model abstains**, not as the classifier. |

### 3.3 Backbone selection: decided by measurement, not opinion
A frozen-feature **linear-probe bake-off** with logistic regression on cached embeddings. Fit on train, **score on val only**. Takes about 10 minutes per backbone.

| Candidate (timm name, verify with `timm.list_models(pretrained=True)`) | Why it's in the running |
|---|---|
| `vit_base_patch16_siglip_384.v2_webli` (SigLIP 2, ViT-B/16 @ 384) | Image-text pretraining. Strong at reading text in photos (postings, signs) and at semantic scene categories. **Prior favorite.** |
| `vit_base_patch14_dinov2.lvd142m` (DINOv2, ViT-B/14, run at 448) | Self-supervised local features. Strong on texture and fine detail (cracks vs potholes vs curb ramps). |
| `convnext_base.fb_in22k_ft_in1k_384` (ConvNeXt-B @ 384) | Robust convolutional network (CNN), cheap to fine-tune and serve. A safety net. |
| *Optional, only on a ≥ 40 GB GPU:* `vit_so400m_patch14_siglip_384.v2_webli` | Bigger SigLIP 2. Use it only if the B/16 probe leaves a clear gap. |

**Pick the winner by val macro-F1.** Probe results go into `reports/probe_bakeoff.json`. That's the decision gate at G2.

### 3.4 Fine-tuning recipe (LP-FT)
Linear probe → full fine-tune: initialize the classifier head from the trained linear probe, then unfreeze everything. LP-FT keeps more of the pretrained features than plain fine-tuning, which helps on **out-of-distribution photos (the live demo)**.

- **Optimizer:** AdamW, weight decay 0.05. **Layer-wise learning-rate decay 0.75**. Backbone top-layer learning rate 5e-5, head 1e-3. Cosine schedule with 1 epoch of warmup. 10 epochs (early-stop on val macro-F1). Batch 64 (gradient accumulation if memory is tight). bf16, gradient clip 1.0.
- **Loss:** cross-entropy with **label smoothing 0.1**, which absorbs some of the crowd-label noise.
- **Train augmentation:** RandomResizedCrop to a square (scale 0.5–1.0, ratio 3/4–4/3), horizontal flip, mild ColorJitter (0.2), rotation ±10°.
  - **No vertical flips.**
  - **No CutMix/Mixup.** Pasting a pothole into a graffiti photo manufactures label noise.
  - **No aggressive crops.** A small graffiti tag disappears.
- **Eval transform:** resize the short side, then **center-crop a square**. **Never letterbox or pad.** Padding would keep the aspect-ratio shortcut visible to the model.
- **Seeds:** at least 2, 3 if time allows. Report mean ± std so one lucky seed can't fool us.
- **Stretch (val-gated, optional):** clean the training set using out-of-fold linear-probe predictions (cleanlab-style). Drop at most the 5% most-likely-mislabeled **train** images, retrain, keep only if val improves. **Never clean val or test.** That inflates the metrics.

### 3.5 Calibration and abstention
- **Temperature scaling** fitted on val (one scalar).
- **Abstain threshold τ** = the smallest max-probability such that val accuracy on accepted images is ≥ 90%. Both values ship in `model_meta.json`.
- **Abstain path in the product:** show the top 3, ask Claude for a second opinion, and the user confirms. This is also our **false-positive control** for photos that aren't street problems at all.

### 3.6 Evaluation protocol (the anti-self-deception rules)
- **The test set is touched exactly once,** by `ml/final_eval.py`, after `ml/` is code-frozen at G3. CI blocks any other code from referencing `test.csv`, except `serve/baseline/claude_zeroshot.py`. Every test run is logged in `reports/TEST_LEDGER.md` with its reason. If we change the model after seeing test numbers, the new number is labelled **post-hoc** everywhere.
- **Metrics:**
  - top-1, top-3, macro-F1, per-class F1, confusion matrix
  - selective accuracy and coverage at τ
  - **95% confidence intervals from a cluster bootstrap that resamples map cells** (photos from one block aren't independent)
  - prior-weighted top-1 using real SF photo-report volumes
- **Baselines on the same frozen subset:**
  - chance (5.9%)
  - the best frozen linear probe
  - Claude zero-shot: a stratified 60-per-class subset of test, 1,020 images, selected by a fixed seed and committed as `reports/claude_baseline_ids.csv`
  - the cascade (model, with Claude on abstentions)

  Claude's prompt is tuned **on val only**, then frozen before it ever sees test.
- **Every number on a slide, in the README or on Devpost** must come from a committed JSON file in `reports/`.

---

## 4. Data leakage controls (what's enforced, and where)

| Leakage path | Control | Enforced by |
|---|---|---|
| Same photo in two splits | sha1 dedupe at scrape time | `verify_data.py` (sha1 check) |
| Same object or spot (repeat reporters, a tagged wall photographed again) | **Spatial grouping:** split by geohash-7 cell (~150 m block). Cells sharing an address are merged, which fixed 87 GPS-jitter cases. | `verify_data.py` (geohash, group and address checks) |
| Same object straddling two neighbouring blocks | **50 m same-class buffer:** dropped 892 train/val photos near a held-out photo | `verify_data.py` (0 pairs within 50 m) |
| Near-identical re-uploads | **dHash ≤ 6 bits** across splits; 137 dropped | `verify_data.py` (0 near-dup pairs) |
| Over-represented single reporters | At most 3 photos per address per class at scrape time | `scrape_sf311.py` |
| Metadata shortcut (agency, location, time) | Classifier input is pixels only | Code review. The `ml/` dataloader returns `(image, label)` only. |
| Aspect-ratio shortcut | Square crop, no padding | Code review of `ml/` transforms |
| Tuning on test (hyperparameters, threshold, prompt) | Val for every decision; test once | `scripts/guard_repo.py` in CI; TEST_LEDGER |
| Split files edited by hand | sha256 values frozen in `SPLIT_MANIFEST.json` | `verify_data.py` in CI |
| Pretraining overlap (backbone saw these images) | Can't be ruled out. The photos sit behind an SF-only Cloudinary account, so overlap is unlikely. **Disclosed** in the model card. | n/a |

---

## 5. System architecture

```
 Phone browser (app/, React + Vite PWA)
   │ 1. photo (resized to JPEG ≤1280px) + GPS + language
   ▼
 Inference API (serve/, FastAPI on the GPU box, public via cloudflared tunnel)
   ├── POST /classify ── fine-tuned model (ml/ artifact) ── top-3 + calibrated probs + abstain
   ├── POST /report ──── Claude (claude-opus-5-5, vision + structured output)
   │                     ── report JSON in user's language + English copy
   └── GET  /health
   │
   ▼
 Convex (app/convex/): reports table, live query → live map (Leaflet)
```

**Contracts are frozen at G1** (`contracts/`). Everyone builds against them from minute one using the stub classifier (`serve/`), so nobody waits on anybody.

---

## 6. Team split: three people, three lanes, one integration

| | Owner | Directory | Builds | Ships to the others |
|---|---|---|---|---|
| **A: Model** | Nirvaan (has the GPU and the images) | `ml/`, `reports/` | bake-off, LP-FT, calibration, final eval, model card | `model_meta.json` + weights (shared out of band), `reports/*.json` |
| **B: Inference + Claude** | *(fill in)* | `serve/` | FastAPI, model loading, Claude report endpoint, Claude zero-shot baseline, public tunnel | live API URL, `reports/claude_baseline.json` |
| **C: Product + Pitch** | *(fill in)* | `app/` | phone app, Convex live map, languages, demo script, Devpost, video | the demo |

Full self-contained briefs, ready to paste into each person's Claude session:
- [docs/roles/A-model.md](docs/roles/A-model.md)
- [docs/roles/B-serve-claude.md](docs/roles/B-serve-claude.md)
- [docs/roles/C-app-pitch.md](docs/roles/C-app-pitch.md)

**Shared files** (`contracts/`, `data/`, `scripts/`, `PLAN.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.github/`) are owned by all three. Changes need a PR labelled `shared` and a 👍 from both other people.

---

## 7. Timeline and gates (PT, Sat → Sun)

| Gate | Time | Exit criteria (all must be true) |
|---|---|---|
| **G0 Setup** | 18:45 | Everyone has cloned the repo, read this plan, and confirmed their role. Python/Node environments installed. Each person's own `ANTHROPIC_API_KEY` in a local `.env`. Images on the GPU box. **Team decides the open questions in §10.** |
| **G1 Contracts frozen** | 19:30 | B's stub API is running and reachable by URL. C's app calls the stub from a phone. Contract changes after this need all three. |
| **G2 Backbone locked** | 22:30 | A's PR with `reports/probe_bakeoff.json` and a first LP-FT val score. B's `/report` is real (Claude) and returns schema-valid JSON. C's capture → result screen works on a phone. |
| **G3 Integration** | 01:30 | The real model is behind `/classify` on the public URL. The app works end to end on a phone. The Convex map is live. **`ml/` code freeze**, then A runs `final_eval.py` **once**. |
| **G4 Feature freeze** | 04:30 | `reports/final_eval.json` and `reports/claude_baseline.json` committed. README numbers filled from them. Bug fixes only from here. |
| **G5 Story done** | 06:30 | Demo video recorded (works when sponsors judge without us). Devpost text, screenshots and GitHub link complete. |
| **Submit** | **07:45** | Submitted on Devpost with everyone listed as a teammate. Buffer before the 9:00 hard deadline. |

Sleep in shifts after G3. A's GPU jobs run unattended. Never leave the merge queue without an owner.

---

## 8. Prize targeting (only claim what we really use)

| Prize | Why we qualify | Owner of the evidence |
|---|---|---|
| **[Anthropic] Claude for Public Benefit** (primary) | Claude drives the report: vision, structured output, multilingual access, a second opinion when the model is unsure, plus a measured zero-shot baseline | B (code), C (story) |
| **Cal Hacks Best People-First Social Impact** | Language access to city services. Fewer misrouted reports. | C |
| **Cal Hacks Most Technically Complex** | A trained and calibrated model with selective prediction and leakage-proof evaluation | A |
| **Cal Hacks overall (1st–3rd)** | Mapped to the judging criteria below | all |
| **[Convex] Best use of Convex** | **Only if** reports and the live map really run on Convex live queries | C |
| **[MLH] Best Use of Vultr** | **Only if** the GPU or API actually runs on Vultr | A/B |
| **[Microsoft] Built for the Real World** | Real city data, real routing, honest evaluation | C |

**C confirms the Anthropic prize's eligibility rules** (Hive/Slack #ask-directors) by G0+30 min.

**How the plan maps to the Cal Hacks judging criteria:**
- **Application:** real SF data, real agencies, and a person-in-the-loop (nothing auto-files).
- **Intentionality:** language access, abstention instead of confident wrong answers, and confirmation before filing.
- **Functionality:** an end-to-end phone demo plus a recorded video.
- **Creativity:** a crowd-sourced city dataset turned into a routing model, with Claude as a multilingual civic assistant.
- **Technical complexity:** a backbone bake-off, LP-FT, calibration, selective prediction, a spatial-leakage-proof split, and a cluster bootstrap.

---

## 9. Product guardrails (the ethics we'll get asked about)

- **We never file to the real SF 311** in the demo. We produce a ready-to-file report with a link to sf311.org. Fake reports waste city crews' time.
- **Danger:** if Claude flags an emergency (live wire, gas, fire, someone hurt), the app tells the user to call 911 instead of filing.
- **Encampment photos show people.** No encampment photos in slides, the video, screenshots or the repo. The product frames this class as "request outreach services", not enforcement. (See the §10 decision.)
- No user photos are stored beyond the demo session. The Convex map stores the category, coordinates and text only, **no image**.

---

## 10. Open decisions (team settles at G0, then the answers get recorded here)

1. **Keep the `encampment` class?** Recommendation: keep it in the model (it's real 311 volume, and dropping it would misroute those photos) but follow the product guardrail in §9. The alternative is to drop the class and retrain, which costs about 0 extra time if decided before G2.
2. **GPU:** what card and how much memory? This sets batch size and whether the So400m backbone is in the bake-off.
3. **Names for B and C,** plus GitHub handles for CODEOWNERS.
4. **Product name.**
