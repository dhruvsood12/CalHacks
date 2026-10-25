"""B2c: label audit, the realistic accuracy ceiling. 10 val photos per class are checked by eye
against the crowd label; the verdicts go to reports/label_audit.json.

  python eval/label_audit.py sheets  [--per-class 10] [--out <dir>]
        tiles the first N photos per class of the pre-registered val prompt-dev subset
        (reports/claude_prompt_dev_ids.csv, already fetched) into one contact sheet per class
        in a scratch directory (never committed: encampment photos show people).
  python eval/label_audit.py record <label> <verdicts>
        verdicts = 10 comma-separated tokens in sheet order: `ok`, `wrong:<label>`, `ambiguous:<label>`
        or `unclear` (photo too poor to tell). Appends/updates reports/label_audit.json.
  python eval/label_audit.py summary
        per-class and overall agreement, the ceiling estimate, and a 95% Clopper-Pearson interval.

Val only. Never the test split.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import metrics as M  # noqa: E402

DATA = ROOT / "data"
IDS = ROOT / "reports" / "claude_prompt_dev_ids.csv"
OUT = ROOT / "reports" / "label_audit.json"
LABELS = M.class_labels()


def subset(per_class: int) -> pd.DataFrame:
    ids = pd.read_csv(IDS, dtype={"service_request_id": str})
    if (ids["split"] != "val").any():
        raise SystemExit("audit ids must be val")
    return ids.groupby("label", sort=True).head(per_class).reset_index(drop=True)


def cmd_sheets(args) -> int:
    from PIL import Image, ImageDraw

    df = subset(args.per_class)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tile, cols = 384, 5
    for label, g in df.groupby("label", sort=True):
        rows = (len(g) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tile, rows * (tile + 18)), "white")
        d = ImageDraw.Draw(sheet)
        for i, (_, r) in enumerate(g.iterrows()):
            img = Image.open(DATA / r["path"]).convert("RGB")
            img.thumbnail((tile, tile))
            x, y = (i % cols) * tile, (i // cols) * (tile + 18)
            sheet.paste(img, (x + (tile - img.width) // 2, y + 18 + (tile - img.height) // 2))
            d.text((x + 4, y + 2), f"{i + 1}  {r['service_request_id']}", fill="black")
        sheet.save(out / f"{label}.jpg", quality=85)
    (out / "order.json").write_text(json.dumps(
        {l: g["service_request_id"].tolist() for l, g in df.groupby("label", sort=True)}, indent=1), encoding="utf-8")
    print(f"{len(df)} photos -> {out} ({df['label'].nunique()} sheets, order.json)")
    return 0


def cmd_record(args) -> int:
    if args.label not in LABELS:
        raise SystemExit(f"unknown label {args.label}")
    tokens = [t.strip() for t in args.verdicts.split(",")]
    ids = subset(args.per_class).query("label == @args.label")["service_request_id"].tolist()
    if len(tokens) != len(ids):
        raise SystemExit(f"{len(tokens)} verdicts for {len(ids)} photos")
    items = []
    for sid, t in zip(ids, tokens):
        kind, _, alt = t.partition(":")
        if kind not in ("ok", "wrong", "ambiguous", "unclear"):
            raise SystemExit(f"bad verdict {t!r}")
        if kind in ("wrong", "ambiguous") and alt not in LABELS + ["not_a_311_issue"]:
            raise SystemExit(f"bad alternative label in {t!r}")
        items.append({"service_request_id": sid, "verdict": kind, "alt_label": alt or None})
    rep = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {
        "split": "val (first 10/class of reports/claude_prompt_dev_ids.csv)", "auditor": args.auditor,
        "protocol": "one look per photo; ok = the crowd label is the right SF311 category; wrong = clearly another category; "
                    "ambiguous = two categories fit, crowd label defensible; unclear = photo too poor to judge",
        "per_class": {}}
    rep["per_class"][args.label] = {"n": len(items), "ok": sum(i["verdict"] == "ok" for i in items),
                                    "wrong": sum(i["verdict"] == "wrong" for i in items),
                                    "ambiguous": sum(i["verdict"] == "ambiguous" for i in items),
                                    "unclear": sum(i["verdict"] == "unclear" for i in items), "items": items}
    rep["updated"] = datetime.now().isoformat(timespec="seconds")
    _summarise(rep)
    OUT.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    c = rep["per_class"][args.label]
    print(f"{args.label}: ok {c['ok']}  wrong {c['wrong']}  ambiguous {c['ambiguous']}  unclear {c['unclear']}  "
          f"({len(rep['per_class'])}/{len(LABELS)} classes recorded)")
    return 0


def _summarise(rep: dict) -> None:
    pc = rep["per_class"]
    n = sum(c["n"] for c in pc.values())
    ok = sum(c["ok"] for c in pc.values())
    wrong = sum(c["wrong"] for c in pc.values())
    amb = sum(c["ambiguous"] for c in pc.values())
    unclear = sum(c["unclear"] for c in pc.values())
    rep["overall"] = {
        "n": n, "ok": ok, "wrong": wrong, "ambiguous": amb, "unclear": unclear,
        "label_correct_rate": ok / n if n else None,
        "label_defensible_rate": (ok + amb) / n if n else None,
        "clearly_wrong_rate": wrong / n if n else None,
        "ceiling_note": "A classifier scored against crowd labels cannot beat ~label_defensible_rate top-1 "
                        "(and will lose about clearly_wrong_rate outright).",
        "clearly_wrong_lower95": M.clopper_pearson_lower(wrong, n) if n else None,
        "ok_lower95": M.clopper_pearson_lower(ok, n) if n else None,
    }


def cmd_summary(args) -> int:
    rep = json.loads(OUT.read_text(encoding="utf-8"))
    _summarise(rep)
    OUT.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    o = rep["overall"]
    print(f"{len(rep['per_class'])}/{len(LABELS)} classes, n={o['n']}: label correct {o['label_correct_rate']:.1%}, "
          f"defensible (ok+ambiguous) {o['label_defensible_rate']:.1%}, clearly wrong {o['clearly_wrong_rate']:.1%}, "
          f"unclear {o['unclear']}")
    for l, c in sorted(rep["per_class"].items(), key=lambda x: x[1]["ok"]):
        print(f"  {l:20s} ok {c['ok']:2d} wrong {c['wrong']:2d} ambiguous {c['ambiguous']:2d} unclear {c['unclear']:2d}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-class", type=int, default=10)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheets")
    s.add_argument("--out", required=True)
    r = sub.add_parser("record")
    r.add_argument("label")
    r.add_argument("verdicts")
    r.add_argument("--auditor", default="B (Krishang) with Claude viewing the contact sheets")
    sub.add_parser("summary")
    args = ap.parse_args()
    return {"sheets": cmd_sheets, "record": cmd_record, "summary": cmd_summary}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
