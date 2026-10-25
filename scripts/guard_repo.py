"""Repository guardrails run by CI on every PR. Exit code 1 on any violation.

  1. Test-set access: outside scripts/ (shared data tooling, 2-approval changes),
     only allowlisted code may reference test.csv or the Claude baseline test ids.
  2. Secrets: no API keys, tokens, private keys or connection URLs in tracked files.
  3. Forbidden files: no images under data/images, no model weights, no .env.
  4. Size: no tracked file over MAX_MB.
  5. Contracts: every example in contracts/examples validates against its schema,
     and categories.json has 17 classes indexed 0..16.

Run locally before pushing: python3 scripts/guard_repo.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_MB = 20
CODE_EXT = {".py", ".ipynb", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".sh", ".swift"}
TEST_ACCESS_ALLOWLIST = {
    "eval/final_eval.py",
    "eval/claude_zeroshot.py",
}
TEST_PATTERNS = re.compile(r"test\.csv|claude_baseline_ids")
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"postgres(ql)?(\+[a-z]+)?://[^\s'\"]+:[^\s'\"]+@"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"Bearer [A-Za-z0-9._\-]{24,}"),
    re.compile(r"hf_[A-Za-z0-9]{30,}"),
]
WEIGHT_EXT = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".bin", ".npz", ".pkl"}
failures = []


def fail(msg):
    print("FAIL", msg)
    failures.append(msg)


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [p for p in out.stdout.decode().split("\0") if p]


def check_contracts():
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        fail("jsonschema not installed (pip install -r scripts/requirements.txt)")
        return
    schemas = {p.name: json.loads(p.read_text()) for p in (ROOT / "contracts").glob("*.schema.json")}
    registry = Registry().with_resources((n, Resource.from_contents(s)) for n, s in schemas.items())
    pairs = {
        "classify.response.json": "classify.response.schema.json",
        "classify.response.abstain.json": "classify.response.schema.json",
        "report.response.json": "report.response.schema.json",
        "model_meta.json": "model_meta.schema.json",
        "context.response.json": "context.response.schema.json",
    }
    cats = json.loads((ROOT / "contracts" / "categories.json").read_text())["classes"]
    labels = {c["label"] for c in cats}
    if [c["index"] for c in cats] != list(range(17)):
        fail("contracts/categories.json must list 17 classes indexed 0..16")
    for example, schema in pairs.items():
        path = ROOT / "contracts" / "examples" / example
        if not path.exists():
            fail(f"missing contracts/examples/{example}")
            continue
        doc = json.loads(path.read_text())
        errors = list(Draft202012Validator(schemas[schema], registry=registry).iter_errors(doc))
        for e in errors:
            fail(f"contracts/examples/{example}: {e.message}")
        for item in doc.get("top_k", []):
            if item["label"] not in labels:
                fail(f"contracts/examples/{example}: unknown label {item['label']}")


def main():
    files = tracked()
    for rel in files:
        path = ROOT / rel
        if not path.is_file():
            continue
        if rel.startswith("data/images/"):
            fail(f"{rel}: images must not be committed (gitignored; use scripts/fetch_images.py)")
        if Path(rel).suffix.lower() in WEIGHT_EXT:
            fail(f"{rel}: model weights/arrays must not be committed")
        if Path(rel).name == ".env" or Path(rel).name.startswith(".env.") and rel != ".env.example":
            fail(f"{rel}: env files must not be committed")
        size_mb = path.stat().st_size / 1e6
        if size_mb > MAX_MB:
            fail(f"{rel}: {size_mb:.1f} MB > {MAX_MB} MB")
        if rel == "scripts/guard_repo.py" or size_mb > MAX_MB:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                fail(f"{rel}: looks like a secret ({pat.pattern[:24]}...)")
        if (Path(rel).suffix in CODE_EXT and not rel.startswith("scripts/")
                and rel not in TEST_ACCESS_ALLOWLIST and TEST_PATTERNS.search(text)):
            fail(f"{rel}: references the test set; only {sorted(TEST_ACCESS_ALLOWLIST)} may")
    check_contracts()
    print(f"checked {len(files)} tracked files, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
