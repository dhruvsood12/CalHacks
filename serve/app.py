"""Snap311 API (contracts/README.md). Run: uvicorn serve.app:app --host 0.0.0.0 --port 8000

POST /classify  multipart `image` (+ optional `lat`, `lng`)  -> classify.response.schema.json
GET  /context   ?label=&lat=&lng=                            -> context.response.schema.json  (B: serve/citydata.py)
POST /report    report.request.schema.json                   -> report.response.schema.json   (B: serve/claude_report.py)
GET  /health

B's modules are imported on first use, so the stub API runs before they exist.
Never files anything to SF 311.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from serve.classifier import LABELS, make_classifier

log = logging.getLogger("snap311")
app = FastAPI(title="Snap311 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
CONTEXT_TIMEOUT_S = 6.0  # /context must never stall the app, whatever the city API does
classifier = make_classifier()
_pool = ThreadPoolExecutor(max_workers=8)


def _warm_city_cache():
    try:
        from serve.citydata import warm_cache

        warm_cache()
        log.info("city fix-time cache warmed")
    except Exception as e:  # missing module or network: /context falls back to cache/evidence
        log.warning("city cache warm-up skipped: %s", e)


@app.on_event("startup")
def _startup():
    threading.Thread(target=_warm_city_cache, daemon=True).start()


def _empty_context(label):
    return {"label": label, "address": None, "nearby_open": [], "fix_time": None,
            "data_as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _context_or_fallback(label, lat, lng):
    """B's get_context, time-boxed. On timeout or error the app still gets a valid, empty context."""
    try:
        from serve.citydata import get_context

        return _pool.submit(get_context, label, lat, lng).result(timeout=CONTEXT_TIMEOUT_S)
    except ValueError:
        raise
    except FutureTimeout:
        log.warning("/context timed out after %.0fs for %s", CONTEXT_TIMEOUT_S, label)
    except Exception as e:
        log.warning("/context failed for %s: %s", label, e)
    return _empty_context(label)


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
    try:
        return _context_or_fallback(label, lat, lng)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/report")
def report(body: dict):
    from serve.claude_report import ReportError, write_report  # B

    ctx = None
    loc = body.get("location") or {}
    label = body.get("chosen_label") or ((body.get("classification") or {}).get("top_k") or [{}])[0].get("label")
    if loc.get("lat") is not None and loc.get("lng") is not None and label in LABELS:
        try:
            ctx = _context_or_fallback(label, loc["lat"], loc["lng"])
        except Exception as e:  # context is a nice-to-have for the report text
            log.warning("context for report failed: %s", e)
    try:
        return write_report(body, context=ctx)
    except ReportError as e:
        log.warning("report failed: %s", e)
        return JSONResponse(status_code=503, content={"error": "report_unavailable", "detail": str(e)})
    except Exception as e:  # e.g. a structured-output validation error: still a clean 503, never a 500
        log.exception("report crashed")
        return JSONResponse(status_code=503, content={"error": "report_unavailable", "detail": type(e).__name__})
