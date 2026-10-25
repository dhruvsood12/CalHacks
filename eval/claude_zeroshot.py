"""B4: the Claude zero-shot baseline the fine-tuned model has to beat (PLAN 3.6).

This file is one of the two allow-listed test readers (scripts/guard_repo.py). The order of
operations is the evidence that the prompt was frozen before any test image was seen:

  1. python eval/claude_zeroshot.py examples
        picks 2 TRAIN photos per class (seed 13) -> eval/prompts/zeroshot_examples.json, fetches them.
  2. python eval/claude_zeroshot.py dev [--limit N] [--workers 8]
        the 340 pre-registered VAL images (reports/claude_prompt_dev_ids.csv), synchronous calls.
        -> reports/claude_zeroshot_dev.json. Iterate on eval/prompts/zeroshot_v1.txt here only.
  3. commit the prompt + examples. Add the TEST_LEDGER line (the script prints it).
  4. python eval/claude_zeroshot.py test --limit 20      # cost check, Message Batches API
     python eval/claude_zeroshot.py test                 # all 1,020 pre-registered test ids
        -> reports/claude_baseline.json + reports/claude_baseline_predictions.csv

Model: claude-opus-5-5, official SDK, structured output (json_schema with the 17-label enum),
effort low, prompt caching on the shared prefix (system + 34 example images). Refusals and
errors count as wrong. Results come back in any order: everything is keyed by custom_id.
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
# prompt pieces
# ----------------------------------------------------------------------------
def system_prompt() -> str:
    cats = "\n".join(f"- `{c['label']}`: {c['display_name']}; {SF_MEANING.get(c['label'], '')}" for c in CATS)
    return Template(PROMPT.read_text(encoding="utf-8")).substitute(categories=cats)


def prompt_sha() -> str:
    h = hashlib.sha256(system_prompt().encode("utf-8"))
    if EXAMPLES.exists():
        h.update(EXAMPLES.read_bytes())
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


def _image_block(b64: str, cache: bool = False) -> dict:
    blk = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    if cache:
        blk["cache_control"] = {"type": "ephemeral"}
    return blk


def example_blocks() -> list[dict]:
    """Labelled train examples, in class order; the last block carries the cache breakpoint."""
    ex = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    meta = pd.read_csv(DATA / "metadata.csv", dtype={"service_request_id": str}).set_index("service_request_id")
    blocks: list[dict] = [{"type": "text", "text": "Labelled examples from the training data, two per category:"}]
    for c in CATS:
        for sid in ex[c["label"]]:
            path = DATA / meta.loc[sid, "path"]
            if meta.loc[sid, "split"] != "train":
                raise SystemExit(f"example {sid} is not a train image")
            blocks.append({"type": "text", "text": f"Example: `{c['label']}` ({c['display_name']})"})
            blocks.append(_image_block(_b64_jpeg(path, EXAMPLE_SIDE)))
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
    """(label or None, stop_reason). Refusals / bad JSON -> None (counted wrong)."""
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
# data
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


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def ledger_ok(sha8: str) -> bool:
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    return any("claude_zeroshot.py" in line and sha8 in line and line.startswith("|") for line in text.splitlines())


def score(ids: list[str], labels: np.ndarray, preds: list[str | None], groups: np.ndarray | None, n_boot: int) -> dict:
    pred_idx = np.array([LABEL_IDX.get(p, -1) for p in preds])
    valid = pred_idx >= 0
    # an unparseable / refused answer is wrong: map it to a never-correct dummy by using (label+1) % C
    safe = np.where(valid, pred_idx, (labels + 1) % len(LABELS))
    out = {
        "n": int(len(ids)), "n_answered": int(valid.sum()),
        "top1": float((safe == labels).mean()),
        "macro_f1": M.macro_f1(safe, labels),
        "per_class": {LABELS[c]: {"recall": float(v)} for c, v in enumerate(M.per_class_prf(safe, labels)["recall"])},
        "confusion_matrix": M.confusion_matrix(safe, labels).tolist(),
        "prior_weighted_top1": M.prior_weighted_top1(safe, labels, M.real_prior()),
    }
    if groups is not None and n_boot:
        out["ci95"] = {
            "top1": list(M.cluster_bootstrap_ci(lambda i: float((safe[i] == labels[i]).mean()), groups, n_boot)),
            "macro_f1": list(M.cluster_bootstrap_ci(lambda i: M.macro_f1(safe[i], labels[i]), groups, n_boot)),
        }
    return out


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
    EXAMPLES.write_text(json.dumps({"seed": 13, "split": "train", "per_class": 2, "examples": chosen}, indent=2) + "\n", encoding="utf-8")
    # keep file format simple for example_blocks(): label -> ids
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
    rep = score(ids, labels, preds, val.loc[ids, "group"].to_numpy(), args.n_boot)
    rep.update({"split": "val (pre-registered prompt-dev subset)", "ids_file": str(DEV_IDS.relative_to(ROOT)),
                "model": MODEL, "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha(),
                "examples_file": str(EXAMPLES.relative_to(ROOT)), "git_sha": git_sha(), "when": datetime.now().isoformat(timespec="seconds"),
                "seconds": round(time.time() - t0, 1), "cost_usd": round(cost, 4), "cost_per_image_usd": round(cost / len(ids), 5),
                "stop_reasons": pd.Series([r[2] for r in results]).value_counts().to_dict(),
                "first_usage": results[0][3], "last_usage": results[-1][3]})
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "claude_zeroshot_dev.json"
    out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame({"service_request_id": ids, "label": [LABELS[l] for l in labels], "pred": preds,
                  "stop_reason": [r[2] for r in results]}).to_csv(REPORTS / "claude_zeroshot_dev_predictions.csv", index=False)
    print(f"val dev n={rep['n']}: top-1 {rep['top1']:.3f}  macro-F1 {rep['macro_f1']:.3f}  "
          f"cost ${rep['cost_usd']:.2f} (${rep['cost_per_image_usd']:.4f}/img, sync prices)  -> {out}")
    print("cache check (last request):", rep["last_usage"])
    return 0


def cmd_test(args) -> int:
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    sha8 = prompt_sha()[:8]
    if not ledger_ok(sha8) and not args.skip_ledger_check:
        print("Add this line to reports/TEST_LEDGER.md and commit it BEFORE running:\n", file=sys.stderr)
        print(f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | B | eval/claude_zeroshot.py | {git_sha()} | "
              f"zeroshot_v1.txt sha {sha8} | Claude zero-shot baseline on the 1,020 pre-registered test ids"
              f"{' (first 20, cost check)' if args.limit else ''} | yes |", file=sys.stderr)
        return 2
    ids_df = pd.read_csv(TEST_IDS, dtype={"service_request_id": str})
    test = pd.read_csv(TEST_CSV, dtype={"service_request_id": str}).set_index("service_request_id")
    ids = ids_df["service_request_id"].tolist()[: args.limit or None]
    ensure_images(ids)
    shared = example_blocks()
    labels = np.array([LABEL_IDX[test.loc[i, "label"]] for i in ids])
    client = anthropic.Anthropic()

    if args.batch_id:
        batch = client.messages.batches.retrieve(args.batch_id)
    else:
        reqs = [Request(custom_id=f"sr-{sid}", params=MessageCreateParamsNonStreaming(**request_params(DATA / test.loc[sid, "path"], shared)))
                for sid in ids]
        batch = client.messages.batches.create(requests=reqs)
        print(f"batch {batch.id} created with {len(reqs)} requests; polling ...", file=sys.stderr)
    while batch.processing_status != "ended":
        time.sleep(30)
        batch = client.messages.batches.retrieve(batch.id)
        c = batch.request_counts
        print(f"  {batch.processing_status}: processing={c.processing} succeeded={c.succeeded} errored={c.errored}", file=sys.stderr)

    preds: dict[str, str | None] = {}
    stops: dict[str, str] = {}
    cost = 0.0
    for r in client.messages.batches.results(batch.id):
        sid = r.custom_id.removeprefix("sr-")
        if r.result.type == "succeeded":
            lab, stop = parse_label(r.result.message)
            cost += usage_cost(r.result.message.usage)["usd"] * 0.5  # batch = 50%
        else:
            lab, stop = None, r.result.type
        preds[sid], stops[sid] = lab, stop
    pred_list = [preds.get(i) for i in ids]
    rep = score(ids, labels, pred_list, test.loc[ids, "group"].to_numpy(), args.n_boot)
    rep.update({"split": "test (pre-registered 1,020-id subset)" + (f" first {args.limit}" if args.limit else ""),
                "ids_file": str(TEST_IDS.relative_to(ROOT)), "model": MODEL, "batch_id": batch.id,
                "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha(),
                "examples_file": str(EXAMPLES.relative_to(ROOT)), "git_sha": git_sha(),
                "when": datetime.now().isoformat(timespec="seconds"), "cost_usd_batch": round(cost, 4),
                "stop_reasons": pd.Series(list(stops.values())).value_counts().to_dict(),
                "post_hoc": bool(args.post_hoc)})
    suffix = f"_first{args.limit}" if args.limit else ""
    (REPORTS / f"claude_baseline{suffix}.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    with open(REPORTS / f"claude_baseline_predictions{suffix}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["service_request_id", "label", "pred", "correct", "stop_reason"])
        for sid, lab, p in zip(ids, labels, pred_list):
            w.writerow([sid, LABELS[lab], p or "", int(p == LABELS[lab]), stops.get(sid, "")])
    print(f"test n={rep['n']}: top-1 {rep['top1']:.3f} {rep.get('ci95', {}).get('top1', '')}  macro-F1 {rep['macro_f1']:.3f}  "
          f"batch cost ${rep['cost_usd_batch']:.2f}  -> reports/claude_baseline{suffix}.json")
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
    t.add_argument("--batch-id", help="resume: collect results of an existing batch")
    t.add_argument("--n-boot", type=int, default=1000)
    t.add_argument("--post-hoc", action="store_true", help="label a re-run as post-hoc")
    t.add_argument("--skip-ledger-check", action="store_true")
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
