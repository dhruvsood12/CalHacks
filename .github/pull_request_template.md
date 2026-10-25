## What and why
<!-- 2 lines. Which gate (G1–G5) does this serve? -->

## Lane
- [ ] A: `ml/`, `serve/app.py`, `serve/classifier.py`, `serve/tests/`
- [ ] B: `eval/`, `reports/`, `serve/claude_report.py`, `serve/prompts/`
- [ ] C: `mobile/`, `convex/`
- [ ] **Touches shared files** (`contracts/`, `data/`, `scripts/`, `PLAN.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.github/`), so it's labelled `shared` and needs 2 approvals

## Evidence it works
<!-- Exact commands + trimmed output. Screenshot / curl transcript for anything user-facing.
     "Tests pass" is necessary, not sufficient. -->

## Numbers
<!-- Every metric cites its reports/*.json file. None typed from memory. -->

## Test-set statement
- [ ] This PR does not read test data
- [ ] This PR reads test data. The TEST_LEDGER line is included, and the run was pre-registered.

## Checklist
- [ ] `python3 scripts/guard_repo.py` passes locally
- [ ] `python3 scripts/verify_data.py` passes locally
- [ ] No secrets, images, weights or `.env` files in the diff
- [ ] Contract changes (if any) updated `contracts/examples/` and have all three 👍
