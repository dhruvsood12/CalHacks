# Why this approach

Two questions every judge, and our own team, will ask:
1. Why is this better than what SF already has?
2. Is the model approach actually the right one?

Sources are linked.
- **[verified]** means we checked the source ourselves on 2026-10-24.
- **[research]** means it came from our research pass and the link should be opened before we quote it on stage.

---

## 1. SF311 today, and what we add

### What SF311 already does (be honest about this in the pitch)
- **The SF311 app already suggests a request type from a photo.** The city's page advertises "Smart photo recognition": the app suggests the request type and identifies objects and licence plates. **[verified]** https://www.sf.gov/sf311-mobile-app
- **Five filing languages:** English, Traditional Chinese, Spanish, Filipino and Vietnamese. The phone line has interpreters for 160+ languages. **[verified]** (same page) · [research] https://www.sf.gov/departments/311-customer-service-center
- **No published accuracy** for the photo suggestion, and no description of the model. **[verified]**
- **It owns everything downstream:** routing into city work queues, duplicates, status tracking, about 870k cases a year. [research, from DataSF]
- **Others ship the same idea:**
  - LA's MyLA311 uses image recognition to pick the request type (2025)
  - NYC lists a "311 Mobile App AI Smart Select"
  - CivicPlus/SeeClickFix announced AI photo categorization (2026)
  - Viladecans (Spain) proposes 3 categories from a photo, and filings rose 40%

  [research] [LA](https://mayor.lacity.gov/news/mayor-bass-announces-launch-new-myla311-system-make-la-cleaner-and-safer-improved-city) · [NYC](https://www.cityandstateny.com/policy/2026/07/how-nyc-government-using-ai/414871/) · [CivicPlus](https://www.civicplus.com/?p=26648) · [Viladecans](https://www.aoc.cat/en/blog/2024/viladecans-gestio-incidencies-ia-digicanvis/)
- **A resident-built competitor, Solve SF,** files photo-first using a general-purpose model (Gemini). City officials told the SF Standard it can get reports wrong, and the developer disputes this. [research] https://sfstandard.com/2025/05/26/san-francisco-311-app-wars-solve/ · https://sf.gazetteer.co/can-an-ai-powered-app-solve-sf-and-its-311-woes

**So "it uses a photo" is not our differentiator.** Cities have shown there's demand. The open question nobody has answered publicly is *how accurate is it, and how do you know?* That's where we are structurally different.

### What we add, structurally
| | SF311 photo suggestion | General-AI filers (e.g. Solve SF) | **Us** |
|---|---|---|---|
| **Measured accuracy** | Not published | Disputed by the city | Measured on a **sealed, spatially separated test set** with 95% CIs. The trainer never sees test. |
| **Knows SF's own taxonomy** | Presumably | No (general model) | Trained on **29,571 of SF's own resident photos**, labelled with SF's own categories. Our 17 classes cover **86.8% of all SF photo reports** in the window (648,419 of 746,859, counted from DataSF). |
| **Says "not sure"** | Unknown | No | **Calibrated abstention**: below a threshold set with a statistical safety margin, it shows its top 3 and asks Claude and the resident instead of guessing. |
| **Agency routing explained** | Inside city systems | Varies | Names the responsible agency (from SF's own routing history) and explains what happens next. |
| **Languages** | 5 in the app | Varies | Claude writes the report in the resident's language (any language Claude handles well), plus an English copy for the city. |
| **Is the general-AI approach good enough?** | n/a | Assumed | **We measure it.** Claude zero-shot on the same test subset, with the same category definitions, against our model and against the cascade. |
| **Portable to other cities** | No | Yes, but unmeasured | The pipeline needs only a city's public 311 data with photos: scrape → spatial split → fine-tune → evaluate. |

**What we can't claim:**
- **That we're more accurate than SF311's own suggestion.** Their accuracy isn't public. We could only claim it by measuring both on the same photos.
  - **Optional:** someone with an iOS 26 iPhone runs about 20 of our **val** photos through the SF311 app's suggestion and records its pick. **Never press submit.** Without that, we say "measured and calibrated", not "more accurate than SF311".
- **That we replace SF311.** We don't: no city work queues, duplicates or status tracking. The honest framing is an **auditable, multilingual front door** that hands the resident a correct, ready-to-file report, plus a **recipe any city can reproduce** to check whether its own photo-categorization actually works.

**Why misrouting matters (precedent):**
- Amsterdam's municipal team reported that residents choosing the wrong category sends issues to the wrong department or delays them. Their production text classifier reached 89%, against 91% for experts. [research] https://arxiv.org/abs/1904.13349
- In SF's own data (2025), free-text status notes mention "duplicate" on about 8% of cases and "transferred" on about 2.7%. These are not official misroute statistics. [research, DataSF query]

---

## 2. Is the model approach right? Precedent check, choice by choice

Verdict key: ✅ supported by precedent, ⚠️ mixed, ❌ contradicted. In each case we adopted what the evidence says.

| # | Design choice | Precedent | Verdict | What we did |
|---|---|---|---|---|
| 2.1 | **Fine-tune pretrained ViT/CNN backbones** rather than train from scratch or zero-shot | Standard for fine-grained classification. In VPT's table (ViT-B), Stanford Cars goes from **51 linear probe → 85 full fine-tuning**. [VPT, ECCV 2022](https://arxiv.org/abs/2203.12119) | ✅ | Core approach |
| 2.2 | **LP-FT** (linear probe, then full fine-tune) | Over 10 shift datasets, LP-FT beat plain fine-tuning by about 1% in distribution and about 10% out of distribution. [Kumar et al., ICLR 2022](https://arxiv.org/abs/2202.10054) | ✅ | Kept. Our live demo photos are a distribution shift. |
| 2.3 | **Layer-wise LR decay**, AdamW, short schedule | Used in the MAE/BEiT fine-tuning recipes. For CLIP-type models, a stronger decay with a higher learning rate did better. [MAE](https://arxiv.org/abs/2111.06377) · [BEiT](https://arxiv.org/abs/2106.08254) · ["CLIP itself is a strong fine-tuner"](https://arxiv.org/abs/2212.06138) | ⚠️ (no recipe published at our 20k scale) | Default recipe **plus** an alternative-recipe run on the top 2 backbones, chosen on val |
| 2.4 | **Choose the backbone by frozen linear probe** | Probe rank doesn't reliably predict fine-tuned rank (MAE's tables: worst probe, best fine-tune). [Kornblith et al., CVPR 2019](https://arxiv.org/abs/1805.08974) | ❌ | **Changed:** fine-tune all three, pick or ensemble on val |
| 2.5 | **Spatially grouped split** | Random hold-outs on spatially autocorrelated data overstate accuracy: up to 28% for CNNs on imagery [Kattenborn et al. 2022](https://doi.org/10.1016/j.ophoto.2022.100018); see also [Ploton et al., Nat. Commun. 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7486894/) and [Roberts et al., Ecography 2017](https://doi.org/10.1111/ecog.02881). Counterpoint: spatial splits can be pessimistic. [Wadoux et al. 2021](https://doi.org/10.1016/j.ecolmodel.2021.109692) | ✅ | Block grouping + 50 m buffer + near-duplicate purge. We accept a possibly pessimistic number over an inflated one. |
| 2.6 | **Is ~1,230 images per class enough?** | Fine-tuned ViT-B reaches **93.4% on Stanford Cars with ~42 images per class**. [DeiT III, ECCV 2022](https://arxiv.org/abs/2204.07118). CLIP's paper: a linear probe matches zero-shot CLIP with a median of **5.4** labelled images per class. [CLIP](https://arxiv.org/abs/2103.00020) | ✅ for quantity | We have ~30× the per-class data of those benchmarks. **Label noise, not quantity, is our ceiling.** Expect fine-tuning to beat frozen features by a few points, not a landslide. We report the gap with a CI. |
| 2.7 | **Label smoothing** for crowd-label noise | Helps under label noise ([Lukasik et al., ICML 2020](https://proceedings.mlr.press/v119/lukasik20a.html)) but **hurts confidence ranking for abstention** ([Xia et al., ICLR 2025](https://arxiv.org/abs/2403.14715)) | ⚠️ | **Changed:** label smoothing 0.1 in the default recipe, 0 in the alternative recipe, chosen on val (AURC + macro-F1). A confident-learning cleanup is the stretch goal. [Northcutt et al., JAIR 2021](https://arxiv.org/abs/1911.00068) |
| 2.8 | **Temperature scaling + abstain threshold** | [Guo et al., ICML 2017](https://arxiv.org/abs/1706.04599) · [Geifman & El-Yaniv, NeurIPS 2017](https://arxiv.org/abs/1705.08500) · temperature scaling also improves selective performance [Galil et al., ICLR 2023](https://arxiv.org/abs/2302.11874) | ✅ with a gap | **Changed:** the threshold uses a **lower 95% bound** on val selective accuracy, so test doesn't miss 90% half the time. Temperature is fitted on the final ensemble. |
| 2.9 | **Claude/VLM zero-shot as the bar to beat** | General VLMs trail CLIP-style classifiers on classification ([Zhang et al., NeurIPS 2024](https://arxiv.org/abs/2405.18415)). CLIP zero-shot is weak on specialised tasks. No published Claude-on-311 benchmark. | ✅ | We give Claude the same category definitions plus a few **train** examples, so the comparison is fair, not a straw man |
| 2.10 | **Square crop** | Center-cropping 576×768 to a square throws away 25% of the frame. Train/test scale mismatch matters. [FixRes](https://arxiv.org/abs/1906.06423) | ⚠️ | **Changed:** a quick val check of square vs fixed 3:4 crop on frozen probes. Both crop to one shape (the aspect-ratio shortcut stays closed). Never pad or squash. |
| 2.11 | **LoRA / PEFT instead of full fine-tuning** | Matches full fine-tuning on few-shot fine-grained sets (VPT). No ViT evidence at our scale that it wins. | — | Not used |
| 2.12 | **Closest street-imagery precedents** | Road-damage *detection* benchmarks: [RDD2020](https://arxiv.org/abs/2011.08740), [RDD2022](https://arxiv.org/abs/2209.08538) (47k images, YOLO ensembles, F1 ≈ 0.67). Japan's My City Report uses road-manager dashcams, not resident photos. **No published work classifies residents' 311 photos into a city taxonomy** that we could find. | — | Our evaluation protocol is the contribution as much as the model. Small published street-photo classifiers report about 95% on *random* splits, which aren't comparable. |

### The three backbones (each the best open option in its family, all one-line `timm` downloads)
All three were checked on Hugging Face on 2026-10-24: **Apache-2.0, not gated**. **[verified]**
- **SigLIP 2 ViT-B/16 @ 384** ([paper](https://arxiv.org/abs/2502.14786)): image–text contrastive. Reads text and knows scene semantics.
- **DINOv2 ViT-B/14** ([paper](https://arxiv.org/abs/2304.07193)): self-supervised. Fine texture and detail.
- **ConvNeXt-B IN-22k @ 384** ([paper](https://arxiv.org/abs/2201.03545)): supervised CNN. A different inductive bias, which helps the ensemble.

Rejected:
- **DINOv3:** custom license with an attribution requirement; its advantage on image-level classification is unverified.
- **ConvNeXt V2:** CC-BY-NC.
- **EVA-02-B @ 448:** about 2.4× the compute.
- **PE-Core-B:** 224 px only.

### Expected gains, ranked (what the GPU time goes to)
1. Fine-tune all three, then ensemble the top 2–3 (plus temperature scaling on the ensemble).
2. Crop-mode check, plus horizontal-flip test-time augmentation if val agrees.
3. Alternative recipe (higher learning rate, stronger layer-wise decay, label smoothing 0) on the top 2.
4. Confident-learning cleanup of train (stretch), and an optional val label audit to estimate the noise ceiling.
5. Abstain threshold with a statistical safety margin.
