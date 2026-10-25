"""Every API response validates against contracts/*.schema.json. Runs on the stub classifier;
B's modules are replaced by fakes here so this file tests A's server, not Claude or DataSF."""
import io
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SCHEMAS = {p.name: json.loads(p.read_text()) for p in (ROOT / "contracts").glob("*.schema.json")}
REGISTRY = Registry().with_resources((n, Resource.from_contents(s)) for n, s in SCHEMAS.items())
EXAMPLES = ROOT / "contracts" / "examples"


def validate(doc, schema):
    errors = [e.message for e in Draft202012Validator(SCHEMAS[schema], registry=REGISTRY).iter_errors(doc)]
    assert not errors, errors


def jpeg(color=(120, 90, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (576, 768), color).save(buf, "JPEG")
    return buf.getvalue()


class ReportError(RuntimeError):
    pass


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CLASSIFIER", "stub")
    fake_city = types.ModuleType("serve.citydata")
    fake_city.get_context = lambda label, lat, lng: {**json.loads((EXAMPLES / "context.response.json").read_text()),
                                                       "label": label}
    fake_report = types.ModuleType("serve.claude_report")
    fake_report.ReportError = ReportError
    fake_report.write_report = lambda body, context=None: json.loads((EXAMPLES / "report.response.json").read_text())
    monkeypatch.setitem(sys.modules, "serve.citydata", fake_city)
    monkeypatch.setitem(sys.modules, "serve.claude_report", fake_report)
    from serve.app import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["num_classes"] == 17


@pytest.mark.parametrize("form", [{}, {"lat": "37.8023", "lng": "-122.4486"}])
def test_classify(client, form):
    r = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}, data=form)
    assert r.status_code == 200, r.text
    validate(r.json(), "classify.response.schema.json")
    probs = [k["prob"] for k in r.json()["top_k"]]
    assert probs == sorted(probs, reverse=True)


def test_classify_is_deterministic(client):
    a = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}).json()
    b = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}).json()
    assert a["top_k"] == b["top_k"]


def test_classify_rejects_non_image(client):
    r = client.post("/classify", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_context(client):
    r = client.get("/context", params={"label": "pavement_defect", "lat": 37.8023, "lng": -122.4486})
    assert r.status_code == 200
    validate(r.json(), "context.response.schema.json")
    assert client.get("/context", params={"label": "nope", "lat": 1, "lng": 1}).status_code == 400


def test_report(client):
    cls = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}).json()
    body = {"image_b64": "AAAA", "media_type": "image/jpeg", "classification": cls, "language": "es",
            "location": {"lat": 37.8023, "lng": -122.4486, "address": None}}
    r = client.post("/report", json=body)
    assert r.status_code == 200
    validate(r.json(), "report.response.schema.json")


def test_report_failure_is_503(client, monkeypatch):
    def boom(body, context=None):
        raise ReportError("upstream down")
    monkeypatch.setattr(sys.modules["serve.claude_report"], "write_report", boom)
    cls = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}).json()
    r = client.post("/report", json={"image_b64": "AAAA", "media_type": "image/jpeg", "classification": cls,
                                     "language": "en"})
    assert r.status_code == 503 and r.json()["error"] == "report_unavailable"


def test_context_times_out_to_valid_empty(client, monkeypatch):
    import time
    import serve.app as appmod
    monkeypatch.setattr(appmod, "CONTEXT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(sys.modules["serve.citydata"], "get_context", lambda label, lat, lng: time.sleep(2))
    t0 = time.time()
    r = client.get("/context", params={"label": "graffiti", "lat": 37.8, "lng": -122.4})
    assert r.status_code == 200 and time.time() - t0 < 1.5
    validate(r.json(), "context.response.schema.json")
    assert r.json()["nearby_open"] == []


def test_report_unexpected_error_is_503(client, monkeypatch):
    def boom(body, context=None):
        raise KeyError("prob")
    monkeypatch.setattr(sys.modules["serve.claude_report"], "write_report", boom)
    cls = client.post("/classify", files={"image": ("p.jpg", jpeg(), "image/jpeg")}).json()
    r = client.post("/report", json={"image_b64": "AAAA", "media_type": "image/jpeg", "classification": cls,
                                     "language": "en"})
    assert r.status_code == 503
