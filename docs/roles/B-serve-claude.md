# Role B: Inference API + Claude (owner: fill in)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`. You own `serve/`. You sit in the middle: A's model plugs into your API, and C's app calls your API. **Your stub must be up by G1 so nobody waits on anyone.**

**Your deliverables:**
1. a public HTTPS API implementing `contracts/`
2. the Claude report endpoint
3. the Claude zero-shot baseline numbers

## Contracts you implement (frozen at G1; see `contracts/README.md`)
- `POST /classify` (multipart `image`) → `contracts/classify.response.schema.json`
- `POST /report` (JSON) → `contracts/report.request.schema.json` → `contracts/report.response.schema.json`
- `GET /health` → `{"status": "ok", "model_version": "...", "num_classes": 17}`

Class order, display names and agencies come **only** from `contracts/categories.json`.

## Steps

### B0. Environment (before G0, 18:45)
```bash
python -m venv .venv && source .venv/bin/activate
# put these in serve/requirements.txt (CI installs it to run serve/tests):
# fastapi uvicorn[standard] python-multipart pillow numpy anthropic pydantic jsonschema torch timm
pip install -r serve/requirements.txt
cp .env.example .env   # put YOUR key in .env; it is gitignored. Never paste keys in chat, PRs or docs.
```

### B1. Stub API (by G1, 19:30), the most important hour
- `serve/app.py` (FastAPI) with all three routes. CORS open to the app origin.
- `serve/classifier.py` defines a `Classifier` interface with two implementations:
  - `StubClassifier`: deterministic fake. Hash the image bytes → pick 3 classes and probabilities. Respects the schema, including `abstain`.
  - `ModelClassifier`: loads A's `model_meta.json` + `model.pt` with timm. Uses the exact preprocessing in the meta: resize the short side, center-crop a square, **no padding**, normalize with the meta's mean/std. Applies the temperature, softmax, top-3, and abstain if max prob < `abstain_threshold`.
  - Chosen by the env var `CLASSIFIER=stub|model`.
- `serve/tests/test_contracts.py` validates every response against the JSON schemas (jsonschema). CI runs pytest if `serve/tests` exists.
- **Public URL:** `cloudflared tunnel --url http://localhost:8000` (no account needed). Post the URL in the team chat and keep it stable. Restarting the tunnel changes the URL, so tell C if that happens.

### B2. Claude report endpoint (by G2, 22:30)
`serve/claude_report.py`, using the official `anthropic` Python SDK:
- **Model:** `claude-opus-5-5`, `output_config={"effort": "low"}` for latency.
  - Don't send `temperature`/`top_p`/`top_k`. They return a 400 on current models.
  - Don't disable thinking. That's also a 400 on Opus 5.5; use effort instead.
- **Vision input:** image as a base64 `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": ...}}` block before the text.
- **Structured output:** `client.messages.parse(..., output_format=ReportModel)` with a Pydantic model that mirrors `contracts/report.response.schema.json`. `response.parsed_output` is validated.
- **Refusals:** check `stop_reason == "refusal"` before reading content. Enable server-side fallbacks by default (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"` on the beta client). If your SDK version rejects this, drop it and handle refusals by returning the classifier-only result.
- **The prompt gives Claude:**
  - the image
  - our top-3 with probabilities and the `abstain` flag
  - the user's language
  - location and the user's note
  - the 17 categories with display names and agencies

  **Claude's job:**
  - confirm or override the category (it must be one of the 17, or `not_a_311_issue`)
  - write a short title and description in the user's language **and** in English
  - name the agency from `categories.json`
  - say what happens next
  - set `emergency=true` (→ the app tells the user to call 911) for danger such as downed wires, gas, fire or injury
- **Never file to the real SF 311.** No calls to any SF endpoint.
- **Timeouts:** 30 s. On failure, return `503` with a JSON error. C shows the classifier result without the report.

### B3. Claude zero-shot baseline (prompt tuned on val, then frozen; run before G4)
`serve/baseline/claude_zeroshot.py` is one of only two files allowed to read test ids.
1. **Prompt development on val only:** `reports/claude_prompt_dev_ids.csv` (340 val images, 20 per class). Iterate the prompt here: class list, display names, one-line definitions of SF conventions.
2. **Freeze the prompt:** commit it as `serve/baseline/prompt_v1.txt` *before* touching test.
3. **Run once** on `reports/claude_baseline_ids.csv` (1,020 test images, 60 per class, pre-selected and committed). Use the Message Batches API (`client.messages.batches.create`, 50% cheaper; results come back in any order, so key them by `custom_id`). Fallbacks aren't supported on batches, so count refusals as wrong.
   - **Cost check:** run 20 images first, multiply out, and post the estimate before running all 1,020.
4. Write `reports/claude_baseline.json`: top-1, macro-F1, per-class F1, refusals and cost. Write `reports/claude_baseline_predictions.csv` (id, predicted label), so A's `final_eval.py` can compute the cascade: model, with Claude when the model abstains.

Get the images with:
```bash
python scripts/fetch_images.py --ids reports/claude_prompt_dev_ids.csv
python scripts/fetch_images.py --ids reports/claude_baseline_ids.csv
```
The script downloads, verifies sha1 against the manifest, and rebuilds the exact files under `data/images/`.

### B4. Integration (G3, 01:30)
- Switch to `CLASSIFIER=model` with A's artifact. Ideally run on A's GPU box; on CPU a ViT-B takes ~0.3 s per photo, which is fine.
- Smoke test: 5 val images A picks give the expected top-3. Measure p50 latency for `/classify` and `/report`, and put both in your PR.

## What you hand to others
| To | What | When |
|---|---|---|
| C | stub URL + example responses | G1 |
| C | real `/report` | G2 |
| everyone | real `/classify` on the public URL | G3 |
| A | `reports/claude_baseline_predictions.csv` for the cascade numbers | by G4 |

## Done means
- Contract tests pass in CI.
- A screen recording or curl transcript of the phone → API → Claude round trip is attached to your G3 PR.
- `reports/claude_baseline.json` is committed, with the frozen prompt committed *before* the test run (check the git history order).
