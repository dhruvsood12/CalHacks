# Devpost draft: Snap311

Paste-ready text for the Devpost form. Fields marked **TODO** must be filled or confirmed before submitting. Every number cites the committed file it comes from.

**Not submitted yet.** Submit only after the TODOs are resolved; the deadline is Sun Oct 25, 9:00 AM PDT (team target 7:45).

---

## Project name
**Snap311** (**TODO:** confirm; PLAN §10 lists the product name as an open decision)

## Tagline (≤ 200 chars)
Photograph a San Francisco street problem: Snap311 finds the location, names the problem and agency, checks for duplicates, and Claude writes the report in your language.

## Inspiration
Reporting a pothole in San Francisco means finding the right category among dozens of 311 types, placing a pin, and guessing whether someone already reported it. In the city's own data for June 15–29, 2025, **44.4% of 28,431 new reports had an earlier same-type report, still open, within 50 m** (`docs/evidence/city_context_stats.json`). SF311's app files in five languages: English, Traditional Chinese, Spanish, Filipino and Vietnamese (`docs/WHY.md` §1). We wanted reporting to be one photo, in the resident's language, with the duplicate check done before filing.

**Who it is for:** San Francisco residents who would rather not navigate 311's category menus in English. This framing comes from SF311's published language coverage and the city's 311 data. We did not run user interviews or partner with community organizations during the hackathon.

## What it does
1. **Photo:** the resident takes a photo or picks one from the library.
2. **Where:** the location fills itself in, and the app says where it came from: the photo's own GPS, the phone's GPS, or an address the resident typed (accepted only inside San Francisco).
3. **What:** a vision model trained on San Francisco's own 311 photos names the problem and the agency that usually handles it, with the top 3 and confidence. Below a calibrated threshold it says **"Not sure"** and the resident picks.
4. **Already reported?** It checks the city's open reports of the same type within 75 m, offers *Add mine as confirmation* or *File anyway*, and shows the typical fix time from city history.
5. **Report:** Claude reads the photo and the classifier's guesses, confirms or corrects the category, and writes the report in the resident's chosen language (English, Español, 中文, Filipino, Tiếng Việt, Русский), with an English copy for city staff. Immediate danger (downed wire, gas, fire, injury) shows **Call 911** instead.
6. **File:** the resident copies the report into sf311.org or the SF311 app. **Snap311 never files for anyone.**
7. **Live map:** each added report appears on a Convex-backed map for everyone, without a refresh. Same-type reports within 75 m group into one pin with a count. Tapping a pin shows the agency and **why**: the city's usual agency for that category, whether the model or the resident chose it, whether Claude agreed, and where the location came from. The photo is never stored.

## How we built it
- **Data (Python):** 29,571 resident photos across 17 categories from DataSF 311 Cases, split train / val / test = 20,947 / 4,252 / 4,372 (`data/SPLIT_MANIFEST.json`, `contracts/categories.json`). To stop the model from memorizing places:
  - the split is spatially grouped (geohash-7 cells), with a 50 m same-class buffer and a near-duplicate purge (dHash ≤ 6 bits) (`data/SPLIT_MANIFEST.json`)
  - the test set is sealed; only the evaluation scripts may read it, and CI enforces that
  - every test run is logged in `reports/TEST_LEDGER.md` beforehand
- **Model (PyTorch, timm), Person A:**
  - frozen-feature probes on three backbones (SigLIP 2, DINOv2, ConvNeXt), each in square and 3:4 crops (`reports/probe_bakeoff.json`, PR #37)
  - then LP-FT fine-tuning (val table in PR #47); the final model or ensemble is chosen on val
  - served by FastAPI (`/classify`, `/context`, `/report`, `/health`) over an HTTPS tunnel
  - **TODO (A):** confirm which runs and ensemble are final
- **Evaluation and Claude (Python, Anthropic SDK), Person B:**
  - metrics with cluster-bootstrap confidence intervals, and calibration (temperature plus an abstain threshold with a Clopper–Pearson safety margin)
  - a Claude zero-shot baseline on the same test subset (PR #41, in review)
  - the live report writer: `claude-opus-5-5` with structured output validated against `contracts/report.response.schema.json`
  - the DataSF city-context lookups
- **App and live map (TypeScript), Person C:**
  - Expo / React Native, so one codebase covers iPhone and Android
  - Expo Router; location provenance from photo EXIF, `expo-location` and SF-bounded geocoding
  - timeouts with Retry on every API call
  - Convex: schema, validated mutation, a duplicate-cluster query and live `useQuery` subscriptions, on a cloud deployment
- **Process:** three lanes with frozen JSON contracts, CI guards (secrets, test-set access, contract validation) and reviewed PRs.

## Why Claude is central
- **Language access:** the report exists in the resident's language and in English because Claude writes both, grounded in the photo, the category, the location and the city context.
- **A second opinion:** Claude sees the photo and the classifier's top 3, and can confirm, correct, or answer `not_a_311_issue`. The map records whether it agreed, so the decision stays auditable.
- **Safety:** Claude flags immediate danger, and the app switches to Call 911 instead of a filing flow.
- **Measured, not assumed:** we evaluate Claude zero-shot against the fine-tuned model on the same sealed test subset (`eval/`), rather than assuming either is better. **TODO:** add results only from `reports/claude_baseline.json` if committed.
- **Live evidence:** a live round trip through the report writer (`claude-opus-5-5`, 11.4 s, schema-valid, Spanish, using the city context) is in PR #40. **TODO:** replace with the in-app result once the full path runs.

## What makes it novel
- **Location provenance as a first-class field:** every report says whether its location came from the photo, the phone or a typed address, and the map shows it.
- **An auditable "why":** the map records the model's top guess, what the resident chose, and whether Claude agreed, not just a final label.
- **Honest uncertainty:** a calibrated "not sure" instead of a confident wrong answer.
- **Evaluation discipline:** a spatially separated, sealed test set with pre-registered runs. We also measured that location alone predicts the category at 16.3% top-1 against 5.9% chance, but does *not* improve agency routing (63.5% for the nearest past report vs 71.5% for the category's usual agency), so we route by category (`docs/evidence/location_signal.json`).

## Challenges we ran into
- **Spatial leakage:** random splits put the same block or object in train and test. We grouped by geohash cells, added a 50 m buffer and purged near-duplicates.
- **The photo upload:** Expo SDK 58's `fetch` rejects React Native's usual `{uri, name, type}` multipart part, so the real `/classify` upload never reached the server; the mock hid it. We send an `expo-file-system` `File` instead.
- **Timeouts that fight each other:** the API time-boxes the city lookup at 6 s and Claude at 30 s, while the app was giving up at 6 s and 30 s. Matching the client to the server's budgets let the server's fallbacks reach the user.
- **Model vs resident:** we first stored the resident's pick where the model's prediction belonged. The map now stores the model's top guess, the resident's choice and Claude's agreement separately.
- **Cross-platform:** we moved from a planned SwiftUI app to Expo mid-hackathon, through a reviewed shared PR, so Android residents aren't left out.

## Accomplishments that we're proud of
- An end-to-end flow from photo to location provenance, classification, duplicate check, report and live map, verified in one uninterrupted simulator run against cloud Convex. **TODO:** upgrade to "on a phone against the real API" once done.
- A live map whose every pin explains its routing.
- A data split and evaluation designed so our numbers can't be inflated by leakage.

## What we learned
- The hard part of civic AI isn't the classifier; it's being honest about uncertainty and showing why.
- Contracts frozen early let three people build in parallel without blocking each other.

## What's next for Snap311
- **TODO:** results slide from `reports/final_eval.json`.
- On-device classification (Core ML), so the photo never leaves the phone for that step.
- Sign-in and rate limits on the map's write endpoint before any public use.
- The same pipeline for any city with open 311 photo data: scrape, spatial split, fine-tune, evaluate.
- Talking with residents and community organizations, which we have not done yet.

## Built with
`expo` · `react-native` · `typescript` · `convex` · `python` · `pytorch` · `timm` · `fastapi` · `anthropic` · `claude` · `datasf` · `cloudflare`

## Links
- GitHub: https://github.com/dhruvsood12/CalHacks
- Video: **TODO** (YouTube, public or unlisted, ≤ 3:00)

## Images (at least one is required)
Use real-API screenshots if available. Otherwise use these and **caption them as "mock API"**, since they show the "Mock data" badge or a mock report. They are on branch `c/pr-evidence`, folder `pr-evidence/`:
1. `c1-capture.png`: capture with location provenance
2. `d-run-picked.png`: "2001 Mission St (±8 m) · from the photo"
3. `c1-context-report.png`: Already reported? card plus report (mock)
4. `d-run-map-4.png`: live map, cluster badge 4
5. `d-run-why-card.png`: the "Why this agency" card

## Prize tracks to select
| Track | Fit | Notes |
|---|---|---|
| [Anthropic] Claude for Public Benefit | Strong on Claude use | Judges ask for a named community and a real problem you've lived or heard from someone who has. We have no interviews; don't claim any |
| Cal Hacks Best People-First Social Impact | Good | Language access; never auto-filing; "not sure" |
| [Convex] Best use of Convex | Good | Live queries, schema, validated mutation and a cluster query. We use no Convex components |
| Cal Hacks Most Technically Complex | Good | Three backbones, LP-FT, calibration, spatial leakage controls |
| Cal Hacks Overall | Yes | |
| [Microsoft] Built for the Real World | Weak | They ask for a "production-minded AI agent"; only select if the team agrees |
| [MLH] Best Use of Vultr | Only if true | **TODO:** select only if the model or API actually runs on Vultr |

## Team
- Dhruv Sood (@dhruvsood12): mobile app, live map (Convex), demo, submission
- Nirvaan (@nirvaansomany): data pipeline, model training, inference API (**TODO:** full name)
- Krishang (@krishang2006): evaluation, calibration, Claude report writer, city data (**TODO:** full name)

All three must be added as teammates on the Devpost submission.
