"""B3: the Claude report writer behind POST /report (A's serve/app.py calls `write_report`).

    from serve.claude_report import write_report, ReportError
    try:
        body = write_report(request_dict, context=context_dict_or_None)
    except ReportError:
        -> HTTP 503; the app shows the classification without a report

- Input: contracts/report.request.schema.json (image_b64, media_type, classification, language,
  chosen_label?, location?, user_note?) plus the optional /context response (nearby_open, fix_time),
  so Claude can say "already reported 2 days ago, add yours as confirmation" and "typically fixed in ~6 days".
- Output: contracts/report.response.schema.json. `agency` is copied from categories.json for the
  chosen category (never trusted from the model), `claude_model` is response.model.
- Model: claude-opus-5-5, official SDK, output_config effort=low, structured output via
  client.messages.parse(output_format=Report). No temperature/top_p/top_k, thinking left on.
  Refusals: stop_reason == "refusal" -> ReportRefused. Server-side fallbacks are enabled when the SDK
  accepts them (betas=["server-side-fallback-2026-07-01"], fallbacks="default"), else plain parse.
- Never calls any SF 311 endpoint. 30 s timeout, 1 retry.
"""
from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from string import Template
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "report_v1.txt"
CATEGORIES_PATH = ROOT / "contracts" / "categories.json"
RESPONSE_SCHEMA_PATH = ROOT / "contracts" / "report.response.schema.json"

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-5-5")
TIMEOUT_S = 30.0
MAX_TOKENS = 4096
NOT_311 = "not_a_311_issue"

LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish (Español)", "zh": "Chinese", "zh-Hans": "Simplified Chinese (简体中文)",
    "zh-Hant": "Traditional Chinese (繁體中文)", "fil": "Filipino", "tl": "Tagalog", "vi": "Vietnamese (Tiếng Việt)",
    "ru": "Russian (Русский)", "ko": "Korean", "ja": "Japanese", "ar": "Arabic", "fr": "French", "pt": "Portuguese",
}


class ReportError(RuntimeError):
    """Any failure that should make /report return 503 (the app then shows the classification only)."""


class ReportRefused(ReportError):
    """Claude declined (stop_reason == 'refusal')."""


# ----------------------------------------------------------------------------
# categories + structured-output model
# ----------------------------------------------------------------------------
def _categories() -> list[dict]:
    return json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))["classes"]


CATEGORIES = _categories()
LABELS = [c["label"] for c in CATEGORIES]
AGENCY = {c["label"]: c["primary_agency"] for c in CATEGORIES}
DISPLAY = {c["label"]: c["display_name"] for c in CATEGORIES}

Category = Enum("Category", {l: l for l in LABELS + [NOT_311]}, type=str)  # type: ignore[misc]


class Report(BaseModel):
    """Pydantic mirror of contracts/report.response.schema.json minus `claude_model` (filled by us)."""
    category: Category = Field(description="One of the 17 labels, or not_a_311_issue")  # type: ignore[valid-type]
    agrees_with_classifier: bool
    agency: str = Field(description="primary agency for category, exactly as listed; empty for not_a_311_issue")
    title: str = Field(description="In the resident's language, <= 80 characters")
    description: str = Field(description="In the resident's language, 1-3 sentences, what and where")
    title_en: str
    description_en: str = Field(description="English copy for the city")
    next_steps: str = Field(description="In the resident's language")
    emergency: bool = Field(description="Immediate danger: downed wire, gas, fire, injury")
    language: str


# ----------------------------------------------------------------------------
# prompt
# ----------------------------------------------------------------------------
def _fmt_classification(cls: dict[str, Any]) -> str:
    rows = [f"- {i + 1}. `{t['label']}` ({t.get('display_name', DISPLAY.get(t['label'], ''))}): p = {t['prob']:.2f}"
            for i, t in enumerate(cls.get("top_k", []))]
    rows.append(f"- abstain: {cls.get('abstain')} (threshold {cls.get('abstain_threshold')})"
                + ("; the classifier is NOT confident: judge the photo yourself." if cls.get("abstain") else ""))
    if cls.get("used_location"):
        rows.append("- the resident's location was used as a second signal")
    return "\n".join(rows)


def _fmt_context(ctx: dict[str, Any] | None) -> tuple[str, str]:
    """(block for the prompt, one-sentence instruction for next_steps)."""
    if not ctx:
        return "", ""
    lines = []
    sent = []
    nearby = ctx.get("nearby_open") or []
    if nearby:
        n0 = nearby[0]
        lines.append(f"- Already reported: {len(nearby)} open same-type report(s) within 75 m in the last 30 days. "
                     f"Newest: case {n0.get('service_request_id')}, {n0.get('distance_m', 0):.0f} m away, "
                     f"open for {n0.get('days_open', 0):.1f} days, status {n0.get('status')}.")
        sent.append("Mention that a similar report is already open nearby and that this report adds confirmation.")
    ft = ctx.get("fix_time")
    if ft:
        lines.append(f"- Typical fix time for this category: median {ft['median_days']:.1f} days, "
                     f"75% within {ft['p75_days']:.1f} days ({ft.get('scope', '')}, n={ft.get('n')}).")
        sent.append("Give the typical fix time in plain words (e.g. 'usually within about 6 days').")
    if ctx.get("address"):
        lines.append(f"- Nearest city-record address: {ctx['address']}")
    block = ("\n## City context at this location (from SF open data)\n" + "\n".join(lines) + "\n") if lines else ""
    return block, " ".join(sent)


def build_prompt(request: dict[str, Any], context: dict[str, Any] | None = None) -> str:
    cls = request["classification"]
    top1 = cls["top_k"][0]["label"] if cls.get("top_k") else "(none)"
    chosen = request.get("chosen_label")
    loc = request.get("location") or {}
    loc_txt = ", ".join(x for x in [loc.get("address"),
                                     f"({loc['lat']:.5f}, {loc['lng']:.5f})" if "lat" in loc and "lng" in loc else None] if x) or "not provided"
    lang = request.get("language", "en")
    ctx_block, ctx_sentence = _fmt_context(context)
    cats = "\n".join(f"- `{c['label']}`: {c['display_name']}; {c['primary_agency']}" for c in CATEGORIES)
    return Template(PROMPT_PATH.read_text(encoding="utf-8")).substitute(
        categories=cats,
        top1_label=top1,
        chosen_sentence=(f"The resident picked `{chosen}` from the suggestions; use it unless the photo clearly contradicts it."
                         if chosen else ""),
        language=lang,
        language_name=LANGUAGE_NAMES.get(lang, LANGUAGE_NAMES.get(lang.split("-")[0], lang)),
        classification=_fmt_classification(cls),
        location=loc_txt,
        note=(request.get("user_note") or "none").strip(),
        context_block=ctx_block,
        context_sentence=ctx_sentence,
    )


def build_messages(request: dict[str, Any], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One user turn: the image block first, then the instructions (role brief B3)."""
    return [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": request["media_type"], "data": request["image_b64"]}},
            {"type": "text", "text": build_prompt(request, context)},
        ],
    }]


# ----------------------------------------------------------------------------
# the call
# ----------------------------------------------------------------------------
def _validate_request(request: dict[str, Any]) -> None:
    for k in ("image_b64", "media_type", "classification", "language"):
        if k not in request:
            raise ReportError(f"request missing `{k}`")
    if request["media_type"] not in ("image/jpeg", "image/png", "image/webp"):
        raise ReportError(f"unsupported media_type {request['media_type']}")
    if not request["classification"].get("top_k"):
        raise ReportError("classification.top_k is empty")


def _client(timeout: float):
    import anthropic
    return anthropic.Anthropic(timeout=timeout, max_retries=1)


def _call(client, messages: list[dict[str, Any]]):
    """messages.parse with server-side fallbacks when the SDK supports them, else plain parse."""
    import anthropic
    common = dict(model=MODEL, max_tokens=MAX_TOKENS, messages=messages, output_format=Report,
                  output_config={"effort": "low"})
    try:
        return client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **common)
    except TypeError:  # older SDK: no `fallbacks` kwarg
        return client.messages.parse(**common)
    except anthropic.BadRequestError as e:  # API rejected the beta: retry without it
        if "fallback" in str(e).lower() or "beta" in str(e).lower():
            return client.messages.parse(**common)
        raise


def write_report(request: dict[str, Any], context: dict[str, Any] | None = None, client=None,
                 timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """Return a dict matching contracts/report.response.schema.json, or raise ReportError."""
    import anthropic

    _validate_request(request)
    client = client or _client(timeout)
    messages = build_messages(request, context)
    try:
        resp = _call(client, messages)
    except anthropic.APITimeoutError as e:
        raise ReportError(f"claude timeout after {timeout}s") from e
    except anthropic.APIStatusError as e:
        raise ReportError(f"claude api error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ReportError(f"claude connection error: {e}") from e

    if getattr(resp, "stop_reason", None) == "refusal":
        det = getattr(resp, "stop_details", None)
        raise ReportRefused(f"claude refused ({getattr(det, 'category', None)})")
    parsed = getattr(resp, "parsed_output", None)
    if parsed is None:
        raise ReportError(f"no structured output (stop_reason={getattr(resp, 'stop_reason', None)})")

    category = parsed.category.value if isinstance(parsed.category, Enum) else str(parsed.category)
    top1 = request["classification"]["top_k"][0]["label"]
    out = {
        "category": category,
        "agrees_with_classifier": category == top1,
        "agency": AGENCY.get(category, "") if category != NOT_311 else "",
        "title": parsed.title[:80],
        "description": parsed.description,
        "title_en": parsed.title_en,
        "description_en": parsed.description_en,
        "next_steps": parsed.next_steps,
        "emergency": bool(parsed.emergency),
        "language": request.get("language", "en"),
        "claude_model": getattr(resp, "model", MODEL),
    }
    errors = validate_response(out)
    if errors:
        raise ReportError("report does not match contract: " + "; ".join(errors))
    return out


def validate_response(body: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return []
    schema = json.loads(RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(body)]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=value lines) so local smoke tests pick up ANTHROPIC_API_KEY."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


if __name__ == "__main__":  # smoke test: python -m serve.claude_report <image.jpg> [language]
    import base64
    import sys

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("set ANTHROPIC_API_KEY in .env (copy .env.example) before the smoke test")
    img = Path(sys.argv[1])
    lang = sys.argv[2] if len(sys.argv) > 2 else "es"
    cls = json.loads((ROOT / "contracts" / "examples" / "classify.response.json").read_text(encoding="utf-8"))
    ctx = json.loads((ROOT / "contracts" / "examples" / "context.response.json").read_text(encoding="utf-8"))
    req = {"image_b64": base64.standard_b64encode(img.read_bytes()).decode(), "media_type": "image/jpeg",
           "classification": cls, "language": lang, "location": {"lat": 37.80, "lng": -122.45, "address": "3601 Lyon St"},
           "user_note": None}
    print(json.dumps(write_report(req, context=ctx), indent=2, ensure_ascii=False))
