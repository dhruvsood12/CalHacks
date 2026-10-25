"""Snap311 API (contracts/README.md). Run: uvicorn serve.app:app --host 0.0.0.0 --port 8000

POST /classify  multipart `image` (+ optional `lat`, `lng`)  -> classify.response.schema.json
GET  /context   ?label=&lat=&lng=                            -> context.response.schema.json  (B: serve/citydata.py)
POST /report    report.request.schema.json                   -> report.response.schema.json   (B: serve/claude_report.py)
GET  /health

B's modules are imported on first use, so the stub API runs before they exist.
Never files anything to SF 311.
"""
import logging

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from serve.classifier import LABELS, make_classifier

log = logging.getLogger("snap311")
app = FastAPI(title="Snap311 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
classifier = make_classifier()


@app.get("/health")
def health():
    return {"status": "ok", "model_version": classifier.model_version, "num_classes": len(LABELS)}


@app.post("/classify")
async def classify(image: UploadFile = File(...), lat: float | None = Form(None), lng: float | None = Form(None)):
    data = await image.read()
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413 if data else 400, "image missing or larger than 10 MB")
    latlng = (lat, lng) if lat is not None and lng is not None else None
    try:
        return classifier.classify(data, latlng)
    except Exception as e:  # PIL cannot decode -> client error, not a server crash
        log.warning("classify failed: %s", e)
        raise HTTPException(400, "could not read the image (send JPEG or PNG)")


@app.get("/context")
def context(label: str = Query(...), lat: float = Query(...), lng: float = Query(...)):
    if label not in LABELS:
        raise HTTPException(400, f"unknown label {label!r}")
    from serve.citydata import get_context  # B; never raises for network trouble

    return get_context(label, lat, lng)


@app.post("/report")
def report(body: dict):
    from serve.claude_report import ReportError, write_report  # B

    ctx = None
    loc = body.get("location") or {}
    label = body.get("chosen_label") or ((body.get("classification") or {}).get("top_k") or [{}])[0].get("label")
    if loc.get("lat") is not None and loc.get("lng") is not None and label in LABELS:
        try:
            from serve.citydata import get_context

            ctx = get_context(label, loc["lat"], loc["lng"])
        except Exception as e:  # context is a nice-to-have for the report text
            log.warning("context for report failed: %s", e)
    try:
        return write_report(body, context=ctx)
    except ReportError as e:
        log.warning("report failed: %s", e)
        return JSONResponse(status_code=503, content={"error": "report_unavailable", "detail": str(e)})
