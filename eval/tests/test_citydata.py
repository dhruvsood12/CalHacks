"""Offline tests for serve/citydata.py: DataSF is monkeypatched; the output is validated
against contracts/context.response.schema.json."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from serve import citydata as C

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "context.response.schema.json").read_text(encoding="utf-8"))
LAT, LNG = 37.80124, -122.44770


def _validate(body):
    errs = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(body)]
    assert not errs, errs


def _rows(now):
    def ts(days_ago):
        return (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000")

    near = [  # ~38 m east, 2.4 days ago
        {"service_request_id": "1", "requested_datetime": ts(2.4), "status_description": "Open",
         "address": "3599 LYON ST", "lat": str(LAT), "long": str(LNG + 0.00043), "supervisor_district": "2",
         "data_as_of": "2026-10-24T01:01:00.000"},
        {"service_request_id": "2", "requested_datetime": ts(9.0), "status_description": "Open",
         "address": C.NO_ADDRESS, "lat": str(LAT + 0.0003), "long": str(LNG), "supervisor_district": "2",
         "data_as_of": "2026-10-23T01:01:00.000"},
        {"service_request_id": "far", "requested_datetime": ts(1.0), "status_description": "Open",  # 300 m: dropped
         "address": "x", "lat": str(LAT + 0.0027), "long": str(LNG), "supervisor_district": "2"},
        {"service_request_id": "bad", "requested_datetime": ts(1.0), "status_description": "Open", "address": "x"},
    ]
    return near


def test_get_context_happy_path(monkeypatch, tmp_path):
    now = datetime.now()
    monkeypatch.setattr(C, "CACHE_PATH", tmp_path / "fix_times.json")

    def fake_soql(params, timeout):
        sel = params["$select"]
        if sel.startswith("service_request_id"):
            assert "within_circle(point" in params["$where"] and "status_description='Open'" in params["$where"]
            assert C.FILTER["pavement_defect"] in params["$where"]
            return _rows(now)
        if sel.startswith("address"):
            return [{"address": "3601 LYON ST, SAN FRANCISCO, CA 94123", "lat": str(LAT), "long": str(LNG),
                     "supervisor_district": "2.0", "data_as_of": "2026-10-24T01:01:00.000"}]
        if sel.startswith("requested_datetime"):
            assert "closed_date IS NOT NULL" in params["$where"]
            rows = []
            for i in range(100):
                a = now - timedelta(days=100 + i)
                rows.append({"requested_datetime": a.strftime("%Y-%m-%dT%H:%M:%S.000"),
                             "closed_date": (a + timedelta(days=2 + (i % 10))).strftime("%Y-%m-%dT%H:%M:%S.000"),
                             "supervisor_district": "2" if i < 40 else "6"})
            return rows
        raise AssertionError(params)

    monkeypatch.setattr(C, "_soql", fake_soql)
    body = C.get_context("pavement_defect", LAT, LNG)
    _validate(body)
    assert body["label"] == "pavement_defect"
    assert body["address"].startswith("3601 LYON")
    ids = [n["service_request_id"] for n in body["nearby_open"]]
    assert ids == ["1", "2"]  # newest first; 'far' and 'bad' dropped
    assert 30 < body["nearby_open"][0]["distance_m"] < 45
    assert body["nearby_open"][0]["address"] == "3599 LYON ST" and body["nearby_open"][1]["address"] is None
    assert 2.3 < body["nearby_open"][0]["days_open"] < 2.6
    # district 2 has n=40 >= 30, so the district scope wins
    assert body["fix_time"]["scope"].startswith("District 2") and body["fix_time"]["n"] == 40
    assert 2 <= body["fix_time"]["median_days"] <= body["fix_time"]["p75_days"] <= 12
    assert body["data_as_of"] == "2026-10-24T01:01:00"
    # cache written and reused without the network
    assert (tmp_path / "fix_times.json").exists()
    monkeypatch.setattr(C, "_soql", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    ft = C.fix_time("pavement_defect", district="6")
    assert ft["scope"].startswith("District 6") and ft["n"] == 60


def test_network_failure_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "CACHE_PATH", tmp_path / "none.json")

    def boom(params, timeout):
        raise OSError("DataSF down")

    monkeypatch.setattr(C, "_soql", boom)
    body = C.get_context("graffiti", LAT, LNG)
    _validate(body)
    assert body["nearby_open"] == [] and body["address"] is None
    # evidence fallback from docs/evidence/city_context_stats.json
    assert body["fix_time"] is not None and "cached evidence" in body["fix_time"]["scope"]
    assert body["fix_time"]["median_days"] == pytest.approx(6.79)


def test_unknown_label_rejected():
    with pytest.raises(ValueError):
        C.get_context("potholes", LAT, LNG)


def test_haversine_and_percentiles():
    assert C.haversine_m(LAT, LNG, LAT, LNG) == 0.0
    assert 105 < C.haversine_m(LAT, LNG, LAT + 0.001, LNG) < 112  # ~111 m per 0.001 deg lat
    assert C._percentiles([1, 2, 3, 4, 5]) == (3.0, 4.0)
    assert C._percentiles([7.0]) == (7.0, 7.0)
