# CLAUDE.md: rules for every Claude session in this repo

Three people work in parallel, each with their own Claude session, on one shared repo. These rules keep us from breaking each other's work or fooling ourselves. They override convenience. If a rule blocks you, say so in the team chat and don't work around it.

**Read first:** `PLAN.md` (goal, architecture, timeline), then your role brief in `docs/roles/` (A = training + API host, B = evaluation + Claude, C = iOS app + submission), then `CONTRIBUTING.md`.

## Hard rules
1. **Never push to `main`.**
   - Work on a branch named `<role>/<topic>` (e.g. `a/probe-bakeoff`, `b/metrics-lib`, `c/capture-screen`) and open a PR using the template.
   - Never merge your own PR. Never enable auto-merge. Never force-push a shared branch.
2. **Stay in your lane.**
   - **A** edits `ml/`, `serve/app.py`, `serve/classifier.py`, `serve/tests/` and `serve/requirements.txt`.
   - **B** edits `eval/`, `reports/`, `serve/claude_report.py`, `serve/citydata.py` and `serve/prompts/`.
   - **C** edits `ios/` and `convex/`.
   - Shared files (`contracts/`, `data/`, `scripts/`, `docs/`, `PLAN.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.github/`) change only in a PR labelled `shared`, approved by **both** other people.
3. **The test set is sealed.**
   - Only B's `eval/final_eval.py` and `eval/claude_zeroshot.py` may read `data/test.csv` or `reports/claude_baseline_ids.csv`. A trains; B judges. The shared data tooling in `scripts/` is the one exception: it builds, audits and fetches the split, and changes to it need two approvals. CI enforces this.
   - Every model and prompt decision is made on **val**.
   - Every test run gets a line in `reports/TEST_LEDGER.md` *before* it runs.
4. **The split files are frozen.** Never edit `data/*.csv` or `data/SPLIT_MANIFEST.json` by hand. `scripts/verify_data.py` must pass.
   - The network sees pixels only, never metadata.
   - Location enters only through the geo-prior (PLAN §3.7), built from cases filed **before 2024-10-01**.
5. **No secrets, data or weights in git.**
   - Keys live in `.env` (gitignored), with names only in `.env.example`. Never paste a key into a doc, PR, commit or chat.
   - Images (`data/images/`) and weights (`*.pt`, `*.onnx`, ...) are shared out of band.
   - Before committing, run: `python3 scripts/guard_repo.py`
6. **Numbers come from files.** Any metric in the README, slides, Devpost or a PR description must be copied from a committed `reports/*.json` and cite it. Counts are measured by command, never remembered.
7. **"Done" needs evidence.**
   - A PR claiming something works includes how you verified it: the command and its output, a screenshot, or a curl transcript.
   - Tests passing or a build going green is necessary, but **not sufficient** for anything user-facing.
8. **Never file to the real SF 311** and never call SF write endpoints. The app produces a report and a link; a human decides.
9. **Contracts are frozen after G1** (20:00 PT). Changing a schema in `contracts/` needs a `shared` PR, a 👍 from all three, and updated `contracts/examples/`.

## Claude API conventions (B: `serve/claude_report.py`, `eval/claude_zeroshot.py`)
- **Model:** `claude-opus-5-5`, through the official `anthropic` Python SDK.
- **Latency:** set `output_config={"effort": "low"}` for the live report path.
- **Don't send** `temperature`/`top_p`/`top_k`, and don't disable thinking. Both return a 400.
- **Structured output:** `client.messages.parse(..., output_format=<Pydantic model>)`.
- **Refusals:** check `stop_reason == "refusal"` before reading content.

## Working style
- Small PRs, merged at the gates in PLAN §7. Pull `main` before starting new work: `git pull --rebase origin main`.
- If `main` breaks, **revert the PR** (`git revert`, via a PR). Don't patch forward under pressure, and never rewrite history.
- Unsure whether something crosses a lane or touches the test set? Stop and ask in the team chat.
