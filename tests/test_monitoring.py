from datetime import date, datetime

import numpy as np
import pytest

from app.core.monitoring import (
    daily_counts,
    days_between,
    drift_check,
    error_rates,
    latency_summary,
    percentile,
    rating_summary,
    score_histogram,
    score_summary,
)
from app.core.params import MonitoringParams

PARAMS = MonitoringParams()


def test_percentile_and_latency_summary():
    assert percentile([], 95) is None
    assert percentile([100], 95) == 100
    assert percentile(list(range(1, 101)), 50) == pytest.approx(50.5)
    summary = latency_summary({"/analyze": [100, 200, 300, 400, 1000], "/coach": []})
    assert list(summary) == ["/analyze"]
    assert summary["/analyze"]["n"] == 5 and summary["/analyze"]["p50_ms"] == 300
    assert 800 <= summary["/analyze"]["p95_ms"] <= 1000


def test_error_rates():
    assert error_rates([]) == {"requests": 0, "server_error_rate": None, "client_error_rate": None}
    rates = error_rates([200, 201, 404, 429, 500, 503, 200, 200, 200, 200])
    assert rates == {"requests": 10, "server_error_rate": 0.2, "client_error_rate": 0.2}


def test_score_histogram_buckets():
    hist = score_histogram([0, 9, 10, 55, 99, 100])
    assert [h["bucket"] for h in hist][:2] == ["0-9", "10-19"] and hist[-1]["bucket"] == "90-100"
    assert [h["count"] for h in hist] == [2, 1, 0, 0, 0, 1, 0, 0, 0, 2]
    assert sum(h["count"] for h in score_histogram([])) == 0


def test_score_summary():
    s = score_summary([80, 50, 20, 30], ["strong", "partial", "weak", "weak"], [0, 1, 0, 2])
    assert s["count"] == 4 and s["mean"] == 45.0
    assert s["bands"] == {"strong": 1, "partial": 1, "weak": 2}
    assert s["missing_sections_share"] == 0.5
    empty = score_summary([], [], [])
    assert empty["mean"] is None and empty["missing_sections_share"] is None


def test_daily_counts_fill_empty_days():
    days = days_between(date(2026, 11, 10), date(2026, 11, 12))
    counts = daily_counts([datetime(2026, 11, 10, 9), datetime(2026, 11, 12, 1)] * 2, days)
    assert counts == [
        {"day": "2026-11-10", "count": 2},
        {"day": "2026-11-11", "count": 0},
        {"day": "2026-11-12", "count": 2},
    ]


def test_rating_summary_and_flag():
    days = days_between(date(2026, 11, 10), date(2026, 11, 11))
    ratings = [
        (datetime(2026, 11, 10, 9), 2, "analysis"),
        (datetime(2026, 11, 10, 10), 3, "coach_message"),
        (datetime(2026, 11, 11, 9), 4, "analysis"),
    ]
    s = rating_summary(ratings, days, PARAMS)
    assert s["count"] == 3 and s["mean"] == 3.0
    assert s["by_day"][0] == {"day": "2026-11-10", "count": 2, "mean": 2.5}
    assert s["by_target"]["analysis"] == {"count": 2, "mean": 3.0}
    assert s["flag"] is False  # below 3.5 but fewer than 5 ratings

    low = [(datetime(2026, 11, 10, 9), 2, "analysis")] * 5
    assert rating_summary(low, days, PARAMS)["flag"] is True
    high = [(datetime(2026, 11, 10, 9), 5, "analysis")] * 5
    assert rating_summary(high, days, PARAMS)["flag"] is False
    assert rating_summary([], days, PARAMS)["mean"] is None


def test_drift_needs_enough_data():
    result = drift_check([50] * 5, [60] * 30, PARAMS)
    assert result["status"] == "insufficient_data"
    assert result["mean_shift"] is None and result["reasons"]


def test_no_drift_on_the_same_distribution():
    rng = np.random.default_rng(0)
    base = rng.normal(55, 12, 200).clip(0, 100)
    same = rng.normal(55, 12, 200).clip(0, 100)
    result = drift_check(base.tolist(), same.tolist(), PARAMS)
    assert result["status"] == "ok" and result["reasons"] == []
    assert abs(result["mean_shift"]) < 3 and result["ks_pvalue"] > 0.01


def test_mean_shift_is_flagged():
    rng = np.random.default_rng(1)
    base = rng.normal(50, 10, 100).clip(0, 100)
    shifted = rng.normal(65, 10, 100).clip(0, 100)
    result = drift_check(base.tolist(), shifted.tolist(), PARAMS)
    assert result["status"] == "drift"
    assert result["mean_shift"] > 10
    assert any("mean score moved" in r for r in result["reasons"])


def test_shape_change_without_mean_shift_is_flagged_by_ks():
    rng = np.random.default_rng(2)
    base = rng.normal(50, 3, 200)
    wide = rng.normal(50, 25, 200).clip(0, 100)
    result = drift_check(base.tolist(), wide.tolist(), PARAMS)
    assert abs(result["mean_shift"]) < 10
    assert result["status"] == "drift"
    assert any("KS" in r for r in result["reasons"])
