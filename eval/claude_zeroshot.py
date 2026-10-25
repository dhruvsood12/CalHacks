"""B4: the Claude zero-shot baseline the fine-tuned model has to beat (PLAN 3.6).

This file is one of the two allow-listed test readers (scripts/guard_repo.py). The order of
operations is the evidence that the prompt was frozen before any test image was seen:

  1. python eval/claude_zeroshot.py examples
        picks 2 TRAIN photos per class (seed 13) -> eval/prompts/zeroshot_examples.json, fetches them.
  2. python eval/claude_zeroshot.py dev [--limit N] [--workers 8]
        the 340 pre-registered VAL images (reports/claude_prompt_dev_ids.csv), synchronous calls.
        -> reports/claude_zeroshot_dev.json. Iterate on eval/prompts/zeroshot_v1.txt here only.
  3. commit the prompt + examples (a test run refuses a dirty or uncommitted prompt).
  4. python eval/claude_zeroshot.py test --limit 20      # cost check: its own ledger row (n=20)
     python eval/claude_zeroshot.py test                 # all 1,020 ids: its own ledger row (n=1020)
        -> reports/claude_baseline.json + reports/claude_baseline_predictions.csv

Ledger rules (CLAUDE.md rule 3): every test run needs its own row in reports/TEST_LEDGER.md naming
this script, the committed prompt's sha256 prefix and `n=<ids in this run>` (the script prints the
row). A run whose output file already exists is refused; a re-run must pass --post-hoc, writes
*_posthoc files and needs a row containing "post-hoc". There is no way to skip the check.

Model: claude-opus-5-5, official SDK, structured output (json_schema with the 17-label enum),
effort low, prompt caching on the shared prefix (system + 34 example images). Refusals and
errors count as "no answer" (an 18th column: wrong for their class, credited to nobody).
Test requests go through the Message Batches API in chunks of <= 100 requests (each request
carries the ~2 MB of example images, and a batch is capped at 256 MB); results come back in any
order, so everything is keyed by custom_id.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import metrics as M  # noqa: E402

DATA = ROOT / "data"
PROMPT = ROOT / "eval" / "prompts" / "zeroshot_v1.txt"
EXAMPLES = ROOT / "eval" / "prompts" / "zeroshot_examples.json"
DEV_IDS = ROOT / "reports" / "claude_prompt_dev_ids.csv"
TEST_IDS = ROOT / "reports" / "claude_baseline_ids.csv"
TEST_CSV = DATA / "test.csv"
LEDGER = ROOT / "reports" / "TEST_LEDGER.md"
REPORTS = ROOT / "reports"

MODEL = os.environ.get("ZEROSHOT_MODEL", "claude-opus-5-5")
MAX_TOKENS = 2048
EXAMPLE_SIDE = 448   # example photos are downscaled to keep the cached prefix small
QUERY_SIDE = 768     # dataset images are already <= 768
BATCH_CHUNK = 100    # requests per Message Batch: ~2.1 MB each (34 examples) -> ~210 MB < 256 MB cap
# $/MTok, Claude Opus 5.5 (skill table, 2026-10): input 4, output 20, cache write 5, cache read 0.20
PRICE = {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20}

CATS = M.load_categories()
LABELS = [c["label"] for c in CATS]
LABEL_IDX = {l: i for i, l in enumerate(LABELS)}
SF_MEANING = {
    "abandoned_vehicle": "a vehicle left on the street for days: flat tyres, dust, notices, damage",
    "blocked_sidewalk": "objects (not a parked car) blocking pedestrian passage: construction, merchandise, bikes, scooters, furniture",
    "blocking_driveway": "a vehicle parked across a driveway opening",
    "curb_ramp_defect": "a damaged, missing or non-compliant curb ramp at a corner",
    "encampment": "tents, tarps, bedding or belongings set up on the sidewalk (outreach request)",
    "garbage_debris": "dumped bags, piles, furniture, boxes or debris on the sidewalk or street",
    "graffiti": "paint, marker or stickers on a wall, pole, box, sign or vehicle",
    "illegal_posting": "paper posters, flyers, signs or banners attached to poles, boxes or walls",
    "litter_receptacle": "a public trash can that is overflowing, damaged, missing or needs service",
    "parked_on_sidewalk": "a vehicle with wheels on the sidewalk",
    "pavement_defect": "a pothole or broken, sunken or lifted street pavement",
    "sewer_flooding": "sewage, a clogged catch basin, standing water, a leak or flooding at the curb",
    "sewer_vent_cover": "a missing or damaged small sewer vent plate in the sidewalk near a building",
    "sidewalk_defect": "cracked, lifted, broken or uneven sidewalk slabs",
    "streetlight": "a streetlight that is out, damaged, leaning or has an open base",
    "traffic_sign": "a bent, missing, faded, twisted or vandalised regulatory or street-name sign",
    "tree_issue": "a street tree with broken branches, fallen, dead, or roots lifting the pavement",
}


# ----------------------------------------------------------------------------
# git: the prompt must be committed before a test run; the hash is of the committed bytes
# ----------------------------------------------------------------------------
def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def git_sha() -> str:
    return _git("rev-parse", "--short", "HEAD").strip() or "unknown"


def prompt_files_committed() -> bool:
    rel = [str(p.relative_to(ROOT)).replace("\\", "/") for p in (PROMPT, EXAMPLES)]
    dirty = _git("status", "--porcelain", "--", *rel).strip()
    tracked = all(_git("ls-files", "--error-unmatch", r) for r in rel)
    return tracked and not dirty


def committed_bytes(path: Path) -> bytes:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True)
    return out.stdout if out.returncode == 0 else b""


# ----------------------------------------------------------------------------
# prompt pieces
# ----------------------------------------------------------------------------
def system_prompt(text: str | None = None) -> str:
    cats = "\n".join(f"- `{c['label']}`: {c['display_name']}; {SF_MEANING.get(c['label'], '')}" for c in CATS)
    return Template(text if text is not None else PROMPT.read_text(encoding="utf-8")).substitute(categories=cats)


def prompt_sha(committed: bool = False) -> str:
    """sha256 of the rendered system prompt + the examples file. committed=True hashes HEAD's bytes."""
    if committed:
        text = committed_bytes(PROMPT).decode("utf-8")
        ex = committed_bytes(EXAMPLES)
    else:
        text = PROMPT.read_text(encoding="utf-8")
        ex = EXAMPLES.read_bytes() if EXAMPLES.exists() else b""
    h = hashlib.sha256(system_prompt(text).encode("utf-8"))
    h.update(ex)
    return h.hexdigest()


def output_schema() -> dict:
    return {"type": "object", "properties": {"label": {"type": "string", "enum": LABELS}},
            "required": ["label"], "additionalProperties": False}


def _b64_jpeg(path: Path, max_side: int) -> str:
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _image_block(b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}


def example_blocks() -> list[dict]:
    """Labelled train examples, in class order; the last block carries the cache breakpoint."""
    ex = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    meta = pd.read_csv(DATA / "metadata.csv", dtype={"service_request_id": str}).set_index("service_request_id")
    blocks: list[dict] = [{"type": "text", "text": "Labelled examples from the training data, two per category:"}]
    for c in CATS:
        for sid in ex[c["label"]]:
            if meta.loc[sid, "split"] != "train":
                raise SystemExit(f"example {sid} is not a train image")
            blocks.append({"type": "text", "text": f"Example: `{c['label']}` ({c['display_name']})"})
            blocks.append(_image_block(_b64_jpeg(DATA / meta.loc[sid, "path"], EXAMPLE_SIDE)))
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def request_params(query_path: Path, shared: list[dict]) -> dict:
    content = shared + [{"type": "text", "text": "Now classify this photo:"}, _image_block(_b64_jpeg(query_path, QUERY_SIDE))]
    return {
        "model": MODEL, "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": output_schema()}},
    }


def parse_label(message) -> tuple[str | None, str]:
    """(label or None, stop_reason). Refusals / bad JSON -> None = no answer."""
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        return None, "refusal"
    for b in getattr(message, "content", []) or []:
        if getattr(b, "type", None) == "text":
            try:
                lab = json.loads(b.text).get("label")
                return (lab if lab in LABEL_IDX else None), stop or "end_turn"
            except (ValueError, AttributeError):
                return None, f"{stop}:unparseable"
    return None, stop or "no_text"


def usage_cost(u) -> dict:
    d = {"input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0,
         "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
         "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}
    d["usd"] = sum(d[k] * PRICE[k] / 1e6 for k in PRICE)
    return d


# ----------------------------------------------------------------------------
# data + scoring
# ----------------------------------------------------------------------------
def ensure_images(ids: list[str]) -> None:
    meta = pd.read_csv(DATA / "metadata.csv", dtype={"service_request_id": str}).set_index("service_request_id")
    missing = [i for i in ids if not (DATA / meta.loc[i, "path"]).exists()]
    if missing:
        tmp = REPORTS / ".fetch_ids.csv"
        pd.DataFrame({"service_request_id": missing}).to_csv(tmp, index=False)
        print(f"fetching {len(missing)} images ...", file=sys.stderr)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_images.py"), "--ids", str(tmp)], check=True)
        tmp.unlink(missing_ok=True)


def score(labels: np.ndarray, preds: list[str | None], groups: np.ndarray | None, n_boot: int) -> dict:
    """preds: label string or None (no answer). No answer is wrong for its class and credited to nobody."""
    p = np.array([LABEL_IDX.get(x, M.NO_ANSWER) if x else M.NO_ANSWER for x in preds])
    cm = M.confusion_matrix_na(p, labels)
    recall = {LABELS[c]: float(cm[c, c] / cm[c].sum()) if cm[c].sum() else 0.0 for c in range(len(LABELS))}
    out = {
        "n": int(len(labels)), "n_answered": int((p >= 0).sum()), "n_no_answer": int((p < 0).sum()),
        "top1": M.top1_na(p, labels), "macro_f1": M.macro_f1_na(p, labels),
        "per_class": {k: {"recall": v} for k, v in recall.items()},
        "confusion_matrix_with_no_answer_column": cm.tolist(),
        "prior_weighted_top1": float(np.sum(M.real_prior() * np.array([recall[l] for l in LABELS]))),
    }
    if groups is not None and n_boot:
        out["ci95"] = {
            "top1": list(M.cluster_bootstrap_ci(lambda i: M.top1_na(p[i], labels[i]), groups, n_boot)),
            "macro_f1": list(M.cluster_bootstrap_ci(lambda i: M.macro_f1_na(p[i], labels[i]), groups, n_boot)),
        }
    return out


# ----------------------------------------------------------------------------
# ledger
# ----------------------------------------------------------------------------
def ledger_rows() -> list[str]:
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    return [l for l in text.splitlines() if l.startswith("|") and "claude_zeroshot.py" in l]


def ledger_row_for(sha8: str, n: int, post_hoc: bool) -> str | None:
    """The row that pre-registers THIS run: same script, same committed prompt, same n, and
    'post-hoc' iff this is a re-run."""
    for row in ledger_rows():
        if sha8 in row and f"n={n}" in row and (("post-hoc" in row.lower()) == post_hoc):
            return row
    return None


def suggested_row(sha8: str, n: int, post_hoc: bool) -> str:
    reason = f"Claude zero-shot baseline, {n} pre-registered test ids" + (" (cost check)" if n < 1020 else "")
    if post_hoc:
        reason += " POST-HOC re-run"
    return (f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | B | eval/claude_zeroshot.py | {git_sha()} | "
            f"zeroshot_v1.txt sha {sha8} n={n} | {reason} | {'no (post-hoc)' if post_hoc else 'yes'} |")


# ----------------------------------------------------------------------------
# subcommands
# ----------------------------------------------------------------------------
def cmd_examples(args) -> int:
    train = pd.read_csv(DATA / "train.csv", dtype={"service_request_id": str})
    rng = np.random.default_rng(13)
    chosen = {}
    for lab in LABELS:
        pool = train.loc[train["label"] == lab, "service_request_id"].tolist()
        chosen[lab] = [str(x) for x in rng.choice(pool, size=2, replace=False)]
    EXAMPLES.write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    ensure_images([i for v in chosen.values() for i in v])
    print(f"wrote {EXAMPLES} ({sum(len(v) for v in chosen.values())} train ids) and fetched the images")
    return 0


def cmd_dev(args) -> int:
    import anthropic
    client = anthropic.Anthropic(max_retries=3, timeout=120)
    ids_df = pd.read_csv(DEV_IDS, dtype={"service_request_id": str})
    if (ids_df["split"] != "val").any():
        raise SystemExit("dev ids must all be val")
    val = pd.read_csv(DATA / "val.csv", dtype={"service_request_id": str}).set_index("service_request_id")
    ids = ids_df["service_request_id"].tolist()[: args.limit or None]
    ensure_images(ids)
    shared = example_blocks()
    labels = np.array([LABEL_IDX[val.loc[i, "label"]] for i in ids])

    def one(sid):
        params = request_params(DATA / val.loc[sid, "path"], shared)
        try:
            msg = client.messages.create(**params)
            lab, stop = parse_label(msg)
            return sid, lab, stop, usage_cost(msg.usage)
        except anthropic.APIError as e:
            return sid, None, f"error:{type(e).__name__}", {"usd": 0}

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(one, ids))
    preds = [r[1] for r in results]
    cost = sum(r[3].get("usd", 0) for r in results)
    rep = score(labels, preds, val.loc[ids, "group"].to_numpy(), args.n_boot)
    rep.update({"split": "val (pre-registered prompt-dev subset)", "ids_file": str(DEV_IDS.relative_to(ROOT)),
                "model": MODEL, "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha(),
                "prompt_committed": prompt_files_committed(), "examples_file": str(EXAMPLES.relative_to(ROOT)),
                "git_sha": git_sha(), "when": datetime.now().isoformat(timespec="seconds"),
                "seconds": round(time.time() - t0, 1), "cost_usd": round(cost, 4), "cost_per_image_usd": round(cost / len(ids), 5),
                "stop_reasons": pd.Series([r[2] for r in results]).value_counts().to_dict(),
                "first_usage": results[0][3], "last_usage": results[-1][3]})
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "claude_zeroshot_dev.json"
    out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame({"service_request_id": ids, "label": [LABELS[l] for l in labels], "pred": preds,
                  "stop_reason": [r[2] for r in results]}).to_csv(REPORTS / "claude_zeroshot_dev_predictions.csv", index=False)
    print(f"val dev n={rep['n']}: top-1 {rep['top1']:.3f}  macro-F1 {rep['macro_f1']:.3f}  no-answer {rep['n_no_answer']}  "
          f"cost ${rep['cost_usd']:.2f} (${rep['cost_per_image_usd']:.4f}/img, sync prices)  -> {out}")
    print("cache check (last request):", rep["last_usage"])
    return 0


def cmd_test(args) -> int:
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    # ---- pre-flight, all before any test data is read -------------------------------------
    if not prompt_files_committed():
        raise SystemExit("commit eval/prompts/zeroshot_v1.txt and zeroshot_examples.json first (clean git status); "
                         "the committed prompt is what the ledger row pre-registers")
    sha8 = prompt_sha(committed=True)[:8]
    n_ids = len(pd.read_csv(TEST_IDS, dtype={"service_request_id": str}).index[: args.limit or None])
    suffix = ("_posthoc" if args.post_hoc else "") + (f"_first{args.limit}" if args.limit else "")
    out_json = REPORTS / f"claude_baseline{suffix}.json"
    out_csv = REPORTS / f"claude_baseline_predictions{suffix}.csv"
    if out_json.exists():
        raise SystemExit(f"{out_json.relative_to(ROOT)} already exists: the first run is the result. "
                         "A re-run must pass --post-hoc (its own ledger row, *_posthoc outputs).")
    row = ledger_row_for(sha8, n_ids, args.post_hoc)
    if row is None:
        print("No ledger row pre-registers this run. Add this line to reports/TEST_LEDGER.md, commit it, then run:\n",
              file=sys.stderr)
        print(suggested_row(sha8, n_ids, args.post_hoc), file=sys.stderr)
        return 2
    print(f"ledger row found: {row}", file=sys.stderr)

    # ---- test data is read from here on ------------------------------------------------------
    ids_df = pd.read_csv(TEST_IDS, dtype={"service_request_id": str})
    test = pd.read_csv(TEST_CSV, dtype={"service_request_id": str}).set_index("service_request_id")
    ids = ids_df["service_request_id"].tolist()[: args.limit or None]
    ensure_images(ids)
    shared = example_blocks()
    labels = np.array([LABEL_IDX[test.loc[i, "label"]] for i in ids])
    client = anthropic.Anthropic()

    if args.batch_ids:
        batch_ids = [b.strip() for b in args.batch_ids.split(",") if b.strip()]
    else:
        batch_ids = []
        for start in range(0, len(ids), BATCH_CHUNK):
            chunk = ids[start:start + BATCH_CHUNK]
            reqs = [Request(custom_id=f"sr-{sid}",
                            params=MessageCreateParamsNonStreaming(**request_params(DATA / test.loc[sid, "path"], shared)))
                    for sid in chunk]
            b = client.messages.batches.create(requests=reqs)
            batch_ids.append(b.id)
            print(f"batch {b.id}: {len(reqs)} requests ({start + len(reqs)}/{len(ids)})", file=sys.stderr)
        print(f"resume with: --batch-ids {','.join(batch_ids)}", file=sys.stderr)

    pending = set(batch_ids)
    while pending:
        time.sleep(30)
        for bid in sorted(pending):
            b = client.messages.batches.retrieve(bid)
            c = b.request_counts
            print(f"  {bid} {b.processing_status}: processing={c.processing} succeeded={c.succeeded} errored={c.errored}",
                  file=sys.stderr)
            if b.processing_status == "ended":
                pending.discard(bid)

    preds: dict[str, str | None] = {}
    stops: dict[str, str] = {}
    cost = 0.0
    for bid in batch_ids:
        for r in client.messages.batches.results(bid):
            sid = r.custom_id.removeprefix("sr-")
            if r.result.type == "succeeded":
                lab, stop = parse_label(r.result.message)
                cost += usage_cost(r.result.message.usage)["usd"] * 0.5  # batch = 50%
            else:
                lab, stop = None, r.result.type
            preds[sid], stops[sid] = lab, stop
    pred_list = [preds.get(i) for i in ids]
    rep = score(labels, pred_list, test.loc[ids, "group"].to_numpy(), args.n_boot)
    rep.update({"split": "test (pre-registered 1,020-id subset)" + (f", first {args.limit}" if args.limit else ""),
                "ids_file": str(TEST_IDS.relative_to(ROOT)), "model": MODEL, "batch_ids": batch_ids,
                "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha(committed=True),
                "examples_file": str(EXAMPLES.relative_to(ROOT)), "git_sha": git_sha(), "ledger_row": row,
                "when": datetime.now().isoformat(timespec="seconds"), "cost_usd_batch": round(cost, 4),
                "stop_reasons": pd.Series(list(stops.values())).value_counts().to_dict(),
                "post_hoc": bool(args.post_hoc)})
    out_json.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["service_request_id", "label", "pred", "correct", "stop_reason"])
        for sid, lab, p in zip(ids, labels, pred_list):
            w.writerow([sid, LABELS[lab], p or "", int(p == LABELS[lab]), stops.get(sid, "")])
    print(f"test n={rep['n']}: top-1 {rep['top1']:.3f} {rep.get('ci95', {}).get('top1', '')}  macro-F1 {rep['macro_f1']:.3f}  "
          f"no-answer {rep['n_no_answer']}  batch cost ${rep['cost_usd_batch']:.2f}  -> {out_json.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("examples")
    d = sub.add_parser("dev")
    d.add_argument("--limit", type=int)
    d.add_argument("--workers", type=int, default=8)
    d.add_argument("--n-boot", type=int, default=1000)
    t = sub.add_parser("test")
    t.add_argument("--limit", type=int)
    t.add_argument("--batch-ids", help="resume: comma-separated ids of already-created batches")
    t.add_argument("--n-boot", type=int, default=1000)
    t.add_argument("--post-hoc", action="store_true", help="a re-run: needs its own 'post-hoc' ledger row, writes *_posthoc")
    args = ap.parse_args()
    try:  # local .env (gitignored) -> ANTHROPIC_API_KEY
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass
    return {"examples": cmd_examples, "dev": cmd_dev, "test": cmd_test}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
