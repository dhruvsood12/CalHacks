"""Offline tests for serve/claude_report.py: the SDK is replaced by a fake client. Checks the
prompt, the Pydantic mirror of the contract, agency overriding, refusal handling, and that the
returned body validates against contracts/report.response.schema.json."""
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from serve import claude_report as R

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "contracts" / "examples"
SCHEMA = json.loads((ROOT / "contracts" / "report.response.schema.json").read_text(encoding="utf-8"))
TINY_JPEG = base64.standard_b64encode(bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffda0008010100003f00d2cf20ffd9")).decode()


def request(lang="es", abstain=False, chosen=None):
    cls = json.loads((EX / ("classify.response.abstain.json" if abstain else "classify.response.json")).read_text(encoding="utf-8"))
    return {"image_b64": TINY_JPEG, "media_type": "image/jpeg", "classification": cls, "language": lang,
            "chosen_label": chosen, "location": {"lat": 37.80124, "lng": -122.4477, "address": "3601 Lyon St"},
            "user_note": "Cars swerve around it"}


class FakeClient:
    """Mimics anthropic.Anthropic().beta.messages.parse / .messages.parse."""

    def __init__(self, parsed, stop_reason="end_turn", model="claude-opus-5-5", reject_beta=False):
        self.calls = []
        self._resp = SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, model=model,
                                     stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None)
        self.reject_beta = reject_beta
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._beta_parse))
        self.messages = SimpleNamespace(parse=self._parse)

    def _beta_parse(self, **kw):
        self.calls.append(("beta", kw))
        if self.reject_beta:
            raise TypeError("unexpected keyword argument 'fallbacks'")
        return self._resp

    def _parse(self, **kw):
        self.calls.append(("plain", kw))
        return self._resp


def good_report(category="pavement_defect"):
    return R.Report(category=category, agrees_with_classifier=True, agency="wrong on purpose",
                    title="Bache grande en la calle", description="Hay un bache profundo frente al 3601 de Lyon St.",
                    title_en="Large pothole", description_en="Deep pothole in front of 3601 Lyon St.",
                    next_steps="Copie este reporte en sf311.org.", emergency=False, language="es")


def test_pydantic_mirror_matches_contract_fields():
    fields = set(R.Report.model_fields)
    assert fields | {"claude_model"} == set(SCHEMA["required"]) == set(SCHEMA["properties"])
    schema = R.Report.model_json_schema()
    cat = schema["$defs"]["Category"]["enum"] if "$defs" in schema else None
    assert cat is not None and len(cat) == 18 and "not_a_311_issue" in cat and "garbage_debris" in cat


def test_prompt_contains_inputs_and_image_first():
    ctx = json.loads((EX / "context.response.json").read_text(encoding="utf-8"))
    msgs = R.build_messages(request(), context=ctx)
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    assert msgs[0]["content"][0]["type"] == "image" and msgs[0]["content"][1]["type"] == "text"
    txt = msgs[0]["content"][1]["text"]
    for needle in ["pavement_defect", "p = 0.81", "Spanish", "3601 Lyon St", "Cars swerve around it",
                   "Already reported", "38 m away", "median 5.6 days", "PW - Street and Sewer Repair",
                   "not_a_311_issue", "Call 911" if False else "911"]:
        assert needle in txt, needle
    assert "$" not in txt.replace("$ ", "")  # every Template placeholder substituted
    # abstain + chosen label change the instructions
    txt2 = R.build_messages(request(abstain=True, chosen="graffiti"))[0]["content"][1]["text"]
    assert "NOT confident" in txt2 and "picked `graffiti`" in txt2
    assert "City context" not in txt2


def test_write_report_happy_path_validates_and_overrides_agency():
    client = FakeClient(good_report())
    body = R.write_report(request(), context=None, client=client)
    errs = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(body)]
    assert not errs, errs
    assert body["agency"] == "PW - Street and Sewer Repair"  # from categories.json, not the model
    assert body["agrees_with_classifier"] is True and body["language"] == "es"
    assert body["claude_model"] == "claude-opus-5-5"
    kind, kw = client.calls[0]
    assert kind == "beta" and kw["model"] == "claude-opus-5-5" and kw["output_format"] is R.Report
    assert kw["output_config"] == {"effort": "low"} and kw["fallbacks"] == "default"
    assert "temperature" not in kw and "top_p" not in kw and "thinking" not in kw


def test_disagreement_and_not_311():
    body = R.write_report(request(), client=FakeClient(good_report("graffiti")))
    assert body["category"] == "graffiti" and body["agrees_with_classifier"] is False
    assert body["agency"] == "PW - Street and Environmental Services"
    body = R.write_report(request(), client=FakeClient(good_report("not_a_311_issue")))
    assert body["category"] == "not_a_311_issue" and body["agency"] == "" and body["agrees_with_classifier"] is False


def test_falls_back_to_plain_parse_when_sdk_lacks_fallbacks():
    client = FakeClient(good_report(), reject_beta=True)
    R.write_report(request(), client=client)
    assert [k for k, _ in client.calls] == ["beta", "plain"]


def test_refusal_raises_report_error():
    with pytest.raises(R.ReportRefused):
        R.write_report(request(), client=FakeClient(good_report(), stop_reason="refusal"))
    with pytest.raises(R.ReportError):
        R.write_report(request(), client=FakeClient(None))


def test_bad_request_rejected_before_any_call():
    client = FakeClient(good_report())
    with pytest.raises(R.ReportError):
        R.write_report({"image_b64": "x", "media_type": "image/gif", "classification": {}, "language": "en"}, client=client)
    assert client.calls == []
    # top_k items without prob (A's stub could regress) -> ReportError, not KeyError
    req = request()
    req["classification"]["top_k"][0] = {"label": "graffiti"}
    with pytest.raises(R.ReportError):
        R.write_report(req, client=client)
    assert client.calls == []


def test_every_unexpected_failure_is_a_report_error():
    """pydantic.ValidationError raised inside messages.parse, or any other exception, must surface
    as ReportError so A's app answers 503, never 500."""
    import pydantic

    class Raising(FakeClient):
        def __init__(self, exc):
            super().__init__(good_report())
            self.exc = exc

        def _beta_parse(self, **kw):
            raise self.exc

    try:
        R.Report(category="pavement_defect")  # missing fields -> a ValidationError instance to replay
    except pydantic.ValidationError as e:
        verr = e
    for exc in (verr, TypeError("boom"), RuntimeError("weird")):
        with pytest.raises(R.ReportError):
            R.write_report(request(), client=Raising(exc))
    # the SDK client is built with no retries so the worst case stays ~timeout
    import anthropic
    c = R._client(30.0)
    assert isinstance(c, anthropic.Anthropic) and c.max_retries == 0
