#!/usr/bin/env python3
"""Shared analytics helpers for speed-pro quality metrics."""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def average(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))

    sorted_values = sorted(float(v) for v in values)
    rank = (len(sorted_values) - 1) * (p / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def quality_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def compute_quality_score(
    *,
    download_mbps: float,
    upload_mbps: float,
    ping_ms: float,
    jitter_ms: float,
    packet_loss_pct: float,
    target_download_mbps: float = 300.0,
    target_upload_mbps: float = 100.0,
) -> float:
    """Compute a 0-100 internet quality score.

    Weighting:
    - Throughput (download/upload): 60
    - Latency: 25
    - Jitter: 15
    Packet loss acts as a multiplicative penalty.
    """
    download_norm = clamp(
        to_float(download_mbps) / max(1.0, target_download_mbps), 0.0, 1.0
    )
    upload_norm = clamp(
        to_float(upload_mbps) / max(1.0, target_upload_mbps), 0.0, 1.0
    )

    throughput_score = (download_norm * 0.7 + upload_norm * 0.3) * 60.0

    ping_value = max(0.0, to_float(ping_ms))
    latency_norm = clamp(1.0 - (ping_value / 150.0), 0.0, 1.0)
    latency_score = latency_norm * 25.0

    jitter_value = max(0.0, to_float(jitter_ms))
    jitter_norm = clamp(1.0 - (jitter_value / 35.0), 0.0, 1.0)
    jitter_score = jitter_norm * 15.0

    raw_score = throughput_score + latency_score + jitter_score

    packet_loss = clamp(to_float(packet_loss_pct), 0.0, 100.0)
    loss_penalty = clamp(1.0 - (packet_loss / 100.0) * 2.0, 0.0, 1.0)

    final_score = clamp(raw_score * loss_penalty, 0.0, 100.0)
    return round(final_score, 2)


def pearson_correlation(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None

    x_mean = average(xs)
    y_mean = average(ys)

    num = 0.0
    x_var = 0.0
    y_var = 0.0
    for x_val, y_val in zip(xs, ys):
        dx = x_val - x_mean
        dy = y_val - y_mean
        num += dx * dy
        x_var += dx * dx
        y_var += dy * dy

    if math.isclose(x_var, 0.0) or math.isclose(y_var, 0.0):
        return None

    return num / math.sqrt(x_var * y_var)


def period_of_day(hour_24: int) -> str:
    if 0 <= hour_24 <= 5:
        return "madrugada"
    if 6 <= hour_24 <= 11:
        return "manha"
    if 12 <= hour_24 <= 17:
        return "tarde"
    return "noite"


def format_correlation(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}"


def mean_of_existing(values: Iterable[Optional[float]], fallback: float = 0.0) -> float:
    floats: List[float] = [
        float(v) for v in values if v is not None and not math.isnan(float(v))
    ]
    if not floats:
        return fallback
    return average(floats)
