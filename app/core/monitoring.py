"""Numbers for the admin page and the weekly drift check (framework-free).

Everything here takes plain lists and returns plain dicts, so it can be tested
without a database and reused by scripts.
"""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta

import numpy as np
from scipy.stats import ks_2samp

from app.core.params import MonitoringParams

BANDS = ("strong", "partial", "weak")


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile, or None for no data."""
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), p))


def latency_summary(latencies_by_path: dict[str, list[float]]) -> dict[str, dict]:
    """{path: {"n", "p50_ms", "p95_ms"}} for each path with data."""
    out = {}
    for path, values in sorted(latencies_by_path.items()):
        if values:
            out[path] = {
                "n": len(values),
                "p50_ms": round(percentile(values, 50)),
                "p95_ms": round(percentile(values, 95)),
            }
    return out


def error_rates(statuses: Sequence[int]) -> dict:
    """Shares of server errors (5xx) and client errors (4xx) among requests."""
    total = len(statuses)
    if not total:
        return {"requests": 0, "server_error_rate": None, "client_error_rate": None}
    server = sum(1 for s in statuses if s >= 500)
    client = sum(1 for s in statuses if 400 <= s < 500)
    return {
        "requests": total,
        "server_error_rate": round(server / total, 4),
        "client_error_rate": round(client / total, 4),
    }


def score_histogram(scores: Sequence[int], bucket: int = 10) -> list[dict]:
    """Counts per score bucket: 0-9, 10-19, ..., 90-100 (100 joins the last bucket)."""
    counts = Counter(min(int(s) // bucket, (100 // bucket) - 1) for s in scores)
    return [
        {
            "bucket": f"{i * bucket}-{i * bucket + bucket - 1 if i < 100 // bucket - 1 else 100}",
            "count": counts.get(i, 0),
        }
        for i in range(100 // bucket)
    ]


def score_summary(scores: Sequence[int], bands: Sequence[str], missing: Sequence[int]) -> dict:
    """Score distribution for a window. `missing` is the count of missing sections per resume."""
    n = len(scores)
    band_counts = Counter(bands)
    return {
        "count": n,
        "mean": round(float(np.mean(scores)), 1) if n else None,
        "bands": {band: band_counts.get(band, 0) for band in BANDS},
        "histogram": score_histogram(scores),
        "missing_sections_share": round(sum(1 for m in missing if m) / n, 3) if n else None,
    }


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def daily_counts(timestamps: Iterable[datetime], days: list[date]) -> list[dict]:
    counts = Counter(t.date() for t in timestamps)
    return [{"day": d.isoformat(), "count": counts.get(d, 0)} for d in days]


def rating_summary(
    ratings: Sequence[tuple[datetime, int, str]], days: list[date], params: MonitoringParams
) -> dict:
    """Ratings as (created_at, rating, target_type): overall, per day and per target type."""
    values = [r for _, r, _ in ratings]
    by_day: dict[date, list[int]] = {}
    by_target: dict[str, list[int]] = {}
    for created_at, rating, target in ratings:
        by_day.setdefault(created_at.date(), []).append(rating)
        by_target.setdefault(target, []).append(rating)

    def mean(xs: list[int]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    overall = mean(values)
    return {
        "count": len(values),
        "mean": overall,
        "by_day": [
            {"day": d.isoformat(), "count": len(by_day.get(d, [])), "mean": mean(by_day.get(d, []))}
            for d in days
        ],
        "by_target": {t: {"count": len(v), "mean": mean(v)} for t, v in sorted(by_target.items())},
        "flag": (
            overall is not None
            and len(values) >= params.rating_min_count
            and overall < params.rating_flag_below
        ),
    }


def drift_check(
    baseline: Sequence[float], current: Sequence[float], params: MonitoringParams
) -> dict:
    """Compare this week's scores with the baseline week's.

    Flags a drift when the mean moves by more than `drift_mean_shift` points or a
    two-sample Kolmogorov-Smirnov test gives p < `drift_ks_alpha`. With too few
    scores in either week it returns status "insufficient_data" and no verdict.
    """
    result: dict = {
        "baseline_n": len(baseline),
        "current_n": len(current),
        "baseline_mean": round(float(np.mean(baseline)), 1) if baseline else None,
        "current_mean": round(float(np.mean(current)), 1) if current else None,
        "mean_shift": None,
        "ks_statistic": None,
        "ks_pvalue": None,
        "reasons": [],
    }
    if min(len(baseline), len(current)) < params.drift_min_samples:
        result["status"] = "insufficient_data"
        result["reasons"].append(f"needs at least {params.drift_min_samples} scores in each week")
        return result

    shift = float(np.mean(current) - np.mean(baseline))
    ks = ks_2samp(baseline, current)
    pvalue = float(ks.pvalue)
    result.update(
        mean_shift=round(shift, 1),
        ks_statistic=round(float(ks.statistic), 3),
        ks_pvalue=pvalue if math.isfinite(pvalue) else None,
    )
    if abs(shift) > params.drift_mean_shift:
        result["reasons"].append(
            f"mean score moved {shift:+.1f} points (limit {params.drift_mean_shift:g})"
        )
    if pvalue < params.drift_ks_alpha:
        result["reasons"].append(
            f"score distribution changed (KS p = {pvalue:.2g}, limit {params.drift_ks_alpha:g})"
        )
    result["status"] = "drift" if result["reasons"] else "ok"
    return result
