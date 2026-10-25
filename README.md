# Snap311 *(working name)*. Cal Hacks 13.0

Snap a photo of a street problem on your phone (iPhone or Android). A vision model fine-tuned on about 30k real San Francisco 311 reports names the problem and the city agency that handles it. Claude writes a ready-to-file report in your language.

**Start here:**
- [PLAN.md](PLAN.md): goal, architecture, leakage protocol, timeline, prizes
- [CLAUDE.md](CLAUDE.md): hard rules for every session
- [CONTRIBUTING.md](CONTRIBUTING.md): the PR workflow and merge guardrails
- Role briefs: [A: training + API host](docs/roles/A-training.md) · [B: evaluation + Claude](docs/roles/B-eval-claude.md) · [C: mobile app + submission](docs/roles/C-ios-app.md)
- Why this approach: [docs/WHY.md](docs/WHY.md) (vs SF311, and the published precedents)
- **Task board:** GitHub Issues, filtered by `role:A` / `role:B` / `role:C`, with milestones G0–G5

**Layout**
```
data/        frozen splits + manifests (images not in git; see data/README.md)
contracts/   API + model-artifact schemas, category ↔ agency map (frozen at G1)
scripts/     scrape, split, leakage audit, image fetch, repo guardrails
ml/          A: probes, LP-FT training of 3 backbones, inference library
serve/       A hosts FastAPI /classify + /report; B owns the Claude report writer
eval/        B: metrics, calibration, Claude zero-shot baseline, the one final test eval
mobile/      C: Expo React Native app (iOS + Android)
convex/      C: Convex functions behind the live map
reports/     every number we cite, plus the test-set ledger
```

**Results:** *filled from `reports/final_eval.json` after G4. Nothing is typed by hand.*

Data: [DataSF 311 Cases](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6).
