# Snap311 · Cal Hacks 13.0

**Photograph a street problem in San Francisco. Snap311 finds where it is, names the problem and the city agency that usually handles it, checks whether it is already reported nearby and how long it typically takes to fix, and writes the report in your language with an English copy for the city. You file it. We never file for you.**

## Who it is for
San Francisco residents who want to report a street problem but would rather not work through 311's category menus in English. SF311's own app files in five languages: English, Traditional Chinese, Spanish, Filipino and Vietnamese ([docs/WHY.md](docs/WHY.md) §1). Snap311 lets the resident pick the report language (English, Español, 中文, Filipino, Tiếng Việt, Русский). Claude writes the report in that language and always adds an English copy for city staff.

This framing comes from SF311's published language coverage and the city's own 311 data. We have not run user interviews or partnered with community organizations.

## The problem
Reporting a pothole, a broken streetlight or a dumped mattress means picking the right type from dozens of 311 categories, placing a pin, and guessing whether someone already reported it. In the city's own data for June 15–29, 2025, **44.4% of 28,431 new reports had an earlier same-type report, still open, within 50 m, filed in the previous 14 days** (`docs/evidence/city_context_stats.json` → `overall`). SF311 shows a recent-requests list, but no duplicate warning before you file and no typical fix time ([docs/WHY.md](docs/WHY.md)).

## What it does
| Step | What the resident sees | Where it comes from |
|---|---|---|
| Photo | Camera or library | `mobile/` |
| **Where** | The address and **where it came from**: "from the photo" (its own GPS), "your location" (phone GPS) or "address you entered" | Photo EXIF, `expo-location`, and geocoding accepted only inside SF |
| **What** | The top 3 categories with confidence and the agency that usually handles each. Below the confidence threshold it says **"Not sure"** and the resident picks | Vision model trained on SF 311 photos (`ml/`), served by `serve/` |
| **Already reported?** | Open same-type reports within 75 m (*Add mine as confirmation* or *File anyway*), plus the typical fix time | DataSF 311 data (`serve/citydata.py`) |
| **Report** | Title, description and next steps in the chosen language, an English copy, **Copy report** and Open sf311.org. Immediate danger shows **Call 911** instead | Claude (`claude-opus-5-5`) with structured output (`serve/claude_report.py`) |
| **Live map** | Each added report as a pin colored by agency; same-type reports within 75 m grouped with a count. Tap a pin for the agency and **why**: usual agency for the category, model pick or resident pick, whether Claude agreed, and where the location came from | Convex live queries (`convex/functions/`) |

### Why Claude is central
- **Language access:** Claude writes the report in the resident's language and in English from the photo, the category, the location and the note. Without it the report is English-only.
- **A second opinion:** Claude sees the photo and the classifier's top 3. It confirms or changes the category, can answer `not_a_311_issue`, and the map records whether it agreed.
- **Safety:** Claude flags immediate danger (downed wire, gas, fire, injury), and the app then shows Call 911 instead of a filing flow.
- **Measured, not assumed:** the team evaluates Claude zero-shot on the same sealed test subset as the fine-tuned model (`eval/`).

The map stores the category, agency, location, an English title and how each decision was made. **It never stores the photo.**

## Run it
**Live map backend (Convex)**
```bash
cd convex && npm install
npx convex login
npx convex dev
```
`npx convex dev` creates or selects a deployment, pushes the functions and prints the URL. Leave it running.
```bash
cd convex && npm run seed
```
This loads 7 demo reports, including a 3-report duplicate cluster on Mission St. Pass `-- '{"lat":..,"lng":..,"address":"..","category":"pavement_defect"}'` to move the cluster and set its category. It is safe to re-run and replaces only seed and rehearsal rows; `npm run seed:clear` removes them.

**App (Expo, runs in Expo Go)**
```bash
cd mobile && npm install
npx expo start
```
Put the Convex URL in `mobile/.env` as `EXPO_PUBLIC_CONVEX_URL`, and the API URL as `EXPO_PUBLIC_API_BASE_URL`. Without an API URL the app runs on the contract examples and shows a **Mock data** badge; it never switches to mock data on its own. Scan the QR code with Expo Go, or press `i` for the iOS simulator. On venue Wi-Fi use `npx expo start --tunnel`.

**API (model, city data, Claude):** FastAPI in `serve/` ([serve/README.md](serve/README.md)). `GET /health` reports `model_version` (`stub` until a trained model is loaded) and `report_ready` (whether Claude is configured).

## What is real and what is mocked
| Part | Status |
|---|---|
| App flow, location provenance, timeouts and retries | Real; tested on the iOS simulator |
| Live map, duplicate clustering, audit fields | Real, on a Convex cloud deployment |
| Map data in the demo | **Seeded**: 7 reports marked `model_version: demo-seed`, shown as "Seeded demo report" on the pin card |
| Classifier | Trained in `ml/`. Until the trained model is loaded, the API serves a **stub** classifier (`model_version: stub`) |
| Duplicate check and fix times | DataSF queries in `serve/citydata.py`. Fix times may come from a cached evidence file |
| Claude report | `serve/claude_report.py`. In mock mode the report is a labelled placeholder ("Mock data: no Claude call was made"), and map rows are marked `mock` |
| Filing to SF 311 | Never. The app links to sf311.org; a person decides |

**Accuracy:** read from `reports/final_eval.json` once the sealed test run is committed. No number in this README is typed by hand.

## Known limits
- Tested in Expo Go on the iOS simulator only. **Android, the camera and a physical iPhone have not been tested.**
- Add to map appears only after a report is written. If the report writer is down, the resident can retry, or file using the category and agency shown.
- The live map needs internet, and the Convex save endpoint has no sign-in. That is fine for a demo, not for production.
- Map clusters cover the latest 500 reports and only group the same category.
- Typed addresses are accepted only inside San Francisco.
- Encampment reports are framed as outreach requests. No photos of people appear anywhere in this project.

## Repository
```
mobile/      Expo React Native app (iOS + Android)
convex/      Convex schema, reports functions, duplicate clusters, demo seed
serve/       FastAPI: /classify, /context, /report, /health
ml/          training and inference for the vision model
eval/        metrics, calibration, Claude zero-shot baseline, the one final test eval
contracts/   API schemas and the category ↔ agency map
data/        frozen, leakage-audited splits (images not in git)
reports/     every number we cite, and the test-set ledger
docs/        why this approach, evidence, role briefs
```
Team process: [PLAN.md](PLAN.md), [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md). Demo script: [DEMO.md](DEMO.md).

Data: [DataSF 311 Cases](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6). Not affiliated with the City and County of San Francisco.
