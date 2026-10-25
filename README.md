# Snap311 · Cal Hacks 13.0

**Photograph a street problem in San Francisco. Snap311 finds where it is, names the problem and the city agency that usually handles it, tells you whether it is already reported nearby and how long it typically takes to fix, and writes the report in your language with an English copy for the city. You file it. We never file for you.**

## Who it is for
San Francisco residents who want to report a street problem but don't want to work through 311's menus in English. SF311's own app files in five languages (English, Traditional Chinese, Spanish, Filipino, Vietnamese; [docs/WHY.md](docs/WHY.md) §1). Snap311 writes the report in the resident's language with Claude, including languages outside that list, and always adds an English copy for city staff.

## The problem
Reporting a pothole, broken streetlight or dumped mattress means picking the right category from dozens of 311 types, placing a pin, and guessing whether someone already reported it. In the city's own data, **44.4% of new reports had an earlier report of the same type, still open, within 50 m** (`docs/evidence/city_context_stats.json` → `overall.already_open_nearby_pct`). SF311 shows no duplicate warning before you file and no typical fix time.

## What it does
| Step | What the resident sees | Where it comes from |
|---|---|---|
| Photo | Camera or library | `mobile/` |
| **Where** | The address, and **where it came from**: "from the photo" (its own GPS), "your location" (phone GPS), or "address you entered" | Photo EXIF, `expo-location`, geocoding inside SF only |
| **What** | Top 3 categories with confidence and the agency that usually handles each. Below a confidence threshold it says **"Not sure"** and the resident picks | Vision model fine-tuned on SF 311 photos (`ml/`, `serve/`) |
| **Already reported?** | "Someone reported this 2 days ago, 38 m away. Still open." → *Add mine as confirmation* or *File anyway*, plus the typical fix time | Live DataSF 311 data (`serve/citydata.py`) |
| **Report** | Title, description and next steps in the resident's language, an English copy, **Copy report**, Open sf311.org. Danger (wires, gas, fire) shows **Call 911** instead | Claude (`claude-opus-5-5`, `serve/claude_report.py`) |
| **Live map** | Every added report as a pin colored by agency; same-type reports within 75 m grouped with a count. Tap a pin for the agency and **why**: usual agency for the category, model pick or resident pick, whether Claude agreed, where the location came from | Convex live queries (`convex/functions/`) |

The map stores the category, agency, location, an English title and how each decision was made. **It never stores the photo.**

## Run it
**Live map backend (Convex)**
```bash
cd convex && npm install
npx convex login
npx convex dev
npm run seed
```
`npx convex dev` prints the deployment URL. `npm run seed` loads 7 demo reports, including a 3-report duplicate cluster on Mission St; it is safe to re-run, and `npm run seed:clear` removes them.

**App (Expo, runs in Expo Go)**
```bash
cd mobile && npm install
npx expo start
```
Put the Convex URL in `mobile/.env` as `EXPO_PUBLIC_CONVEX_URL`. Set `EXPO_PUBLIC_API_BASE_URL` to the API URL to use the real model and Claude; leave it unset to run on the contract examples (the app shows a **Mock data** badge). Scan the QR code with Expo Go, or press `i` for the iOS simulator. On venue Wi-Fi use `npx expo start --tunnel`.

**API (model, city data, Claude):** FastAPI in `serve/`; see [serve/README.md](serve/README.md).

## What is real and what is mocked
| Part | Status |
|---|---|
| App flow, location provenance, timeouts and retries | Real |
| Live map, duplicate clustering, audit fields | Real, on a Convex cloud deployment |
| Map data shown in the demo | **Seeded**: 7 reports marked `model_version: demo-seed`, plus whatever is added live |
| Classifier | Fine-tuned model in progress (`ml/`). Until it is behind the API, the API serves a stub, and the app can run on contract examples |
| Duplicate check and fix times | Real DataSF queries in `serve/citydata.py` |
| Claude report | `serve/claude_report.py`. When the app runs on mock data, the report is a fixed example |
| Filing to SF 311 | Never. The app links to sf311.org; a person decides |

**Accuracy:** read from `reports/final_eval.json` once the sealed test run is committed. No number here is typed by hand.

## Known limits
- Tested on the iOS simulator in Expo Go. **Android and the camera have not been tested.**
- The live map needs internet; the Convex write endpoint has no sign-in (fine for a demo, not for production).
- Duplicate clusters on the map are computed over the latest 500 reports; city duplicates come from DataSF.
- Locations typed by hand are accepted only inside San Francisco.
- Encampment reports are framed as outreach requests. No photos of people appear anywhere in this project.

## Repository
```
mobile/      Expo React Native app (iOS + Android)
convex/      Convex schema, reports functions, duplicate clusters, demo seed
serve/       FastAPI: /classify, /context, /report
ml/          training and inference for the vision model
eval/        metrics, calibration, Claude zero-shot baseline, the one final test eval
contracts/   API schemas and the category ↔ agency map
data/        frozen, leakage-audited splits (images not in git)
reports/     every number we cite, and the test-set ledger
docs/        why this approach, evidence, role briefs
```
Team process: [PLAN.md](PLAN.md), [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md). Demo script: [DEMO.md](DEMO.md).

Data: [DataSF 311 Cases](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6). Not affiliated with the City and County of San Francisco.
