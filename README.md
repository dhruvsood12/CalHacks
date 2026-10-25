# Snap311 *(working name)*. Cal Hacks 13.0

Snap a photo of a street problem. A vision model fine-tuned on about 30k real San Francisco 311 reports names the problem and the city agency that handles it. Claude writes a ready-to-file report in your language.

**Start here:**
- [PLAN.md](PLAN.md): goal, architecture, leakage protocol, timeline, prizes
- [CLAUDE.md](CLAUDE.md): hard rules for every session
- [CONTRIBUTING.md](CONTRIBUTING.md): the PR workflow and merge guardrails
- Role briefs: [A: model](docs/roles/A-model.md) · [B: serve + Claude](docs/roles/B-serve-claude.md) · [C: app + pitch](docs/roles/C-app-pitch.md)

**Layout**
```
data/        frozen splits + manifests (images not in git; see data/README.md)
contracts/   API + model-artifact schemas, category ↔ agency map (frozen at G1)
scripts/     scrape, split, leakage audit, image fetch, repo guardrails
ml/          A: bake-off, LP-FT training, calibration, final eval
serve/       B: FastAPI /classify + /report (Claude), Claude baseline
app/         C: phone web app + Convex live map
reports/     every number we cite, plus the test-set ledger
```

**Results:** *filled from `reports/final_eval.json` after G4. Nothing is typed by hand.*

Data: [DataSF 311 Cases](https://data.sf.gov/City-Infrastructure/311-Cases/vw6y-z8j6).
