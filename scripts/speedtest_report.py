#!/usr/bin/env python3
"""Generate report from recorded speedtest history."""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
JSONL_PATH = ROOT_DIR / "data" / "history.jsonl"


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_records() -> List[Dict[str, Any]]:
    if not JSONL_PATH.exists():
        return []

    records: List[Dict[str, Any]] = []
    with JSONL_PATH.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                record["dt"] = parse_iso_datetime(str(record.get("timestamp", "")))
                records.append(record)
            except Exception as exc:  # pylint: disable=broad-except
                print(
                    f"Aviso: linha {line_number} ignorada no histórico ({exc}).",
                    file=sys.stderr,
                )

    records.sort(key=lambda item: item["dt"])
    return records


def average(values: List[float]) -> float:
    if not values:
        return 0.0
    return statistics.fmean(values)


def format_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def trend_state(delta_percent: float, improve_when_positive: bool) -> str:
    if math.isclose(delta_percent, 0.0, abs_tol=3.0):
        return "estavel"
    if improve_when_positive:
        return "melhorando" if delta_percent > 0 else "piorando"
    return "melhorando" if delta_percent < 0 else "piorando"


def compute_window_trend(records: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    current = [r for r in records if r["dt"] >= current_start]
    previous = [r for r in records if previous_start <= r["dt"] < current_start]

    def metric_stats(metric: str, improve_when_positive: bool) -> Dict[str, Any]:
        current_values = [_to_float(r.get(metric)) for r in current]
        previous_values = [_to_float(r.get(metric)) for r in previous]
        current_avg = average(current_values)
        previous_avg = average(previous_values)

        if previous_values and not math.isclose(previous_avg, 0.0):
            delta_percent = ((current_avg - previous_avg) / previous_avg) * 100
            state = trend_state(delta_percent, improve_when_positive)
        else:
            delta_percent = None
            state = "dados insuficientes"

        return {
            "current_avg": current_avg,
            "previous_avg": previous_avg,
            "delta_percent": delta_percent,
            "state": state,
            "current_count": len(current_values),
            "previous_count": len(previous_values),
        }

    return {
        "days": days,
        "current_count": len(current),
        "previous_count": len(previous),
        "download": metric_stats("download_mbps", improve_when_positive=True),
        "upload": metric_stats("upload_mbps", improve_when_positive=True),
        "ping": metric_stats("ping_ms", improve_when_positive=False),
    }


def print_trend_block(label: str, stats: Dict[str, Any]) -> None:
    def line(metric_name: str, metric: Dict[str, Any], unit: str) -> None:
        delta = metric["delta_percent"]
        if delta is None:
            delta_text = "n/a"
        else:
            delta_text = f"{delta:+.2f}%"
        print(
            f"- {metric_name}: atual {metric['current_avg']:.2f}{unit} | "
            f"anterior {metric['previous_avg']:.2f}{unit} | "
            f"delta {delta_text} | {metric['state']}"
        )

    print(label)
    print(
        f"- Amostras: atual {stats['current_count']} | "
        f"anterior {stats['previous_count']}"
    )
    line("Download", stats["download"], " Mbps")
    line("Upload", stats["upload"], " Mbps")
    line("Ping", stats["ping"], " ms")


def main() -> int:
    records = load_records()
    if not records:
        print("Nenhum histórico encontrado.")
        print("Execute `npm run record` para gerar o primeiro registro.")
        return 1

    first = records[0]
    last = records[-1]

    downloads = [_to_float(r.get("download_mbps")) for r in records]
    uploads = [_to_float(r.get("upload_mbps")) for r in records]
    pings = [_to_float(r.get("ping_ms")) for r in records]

    best_download = max(records, key=lambda item: _to_float(item.get("download_mbps")))
    worst_download = min(records, key=lambda item: _to_float(item.get("download_mbps")))
    best_upload = max(records, key=lambda item: _to_float(item.get("upload_mbps")))
    worst_upload = min(records, key=lambda item: _to_float(item.get("upload_mbps")))
    best_ping = min(records, key=lambda item: _to_float(item.get("ping_ms")))
    worst_ping = max(records, key=lambda item: _to_float(item.get("ping_ms")))

    print("Relatorio Speed Pro")
    print(f"- Total de testes: {len(records)}")
    print(f"- Inicio: {format_dt(first['dt'])}")
    print(f"- Ultimo: {format_dt(last['dt'])}")
    print("")
    print("Medias gerais")
    print(f"- Ping: {average(pings):.2f} ms")
    print(f"- Download: {average(downloads):.2f} Mbps")
    print(f"- Upload: {average(uploads):.2f} Mbps")
    print("")
    print("Melhores e piores")
    print(
        f"- Melhor download: {_to_float(best_download.get('download_mbps')):.2f} Mbps "
        f"({format_dt(best_download['dt'])})"
    )
    print(
        f"- Pior download: {_to_float(worst_download.get('download_mbps')):.2f} Mbps "
        f"({format_dt(worst_download['dt'])})"
    )
    print(
        f"- Melhor upload: {_to_float(best_upload.get('upload_mbps')):.2f} Mbps "
        f"({format_dt(best_upload['dt'])})"
    )
    print(
        f"- Pior upload: {_to_float(worst_upload.get('upload_mbps')):.2f} Mbps "
        f"({format_dt(worst_upload['dt'])})"
    )
    print(
        f"- Melhor ping: {_to_float(best_ping.get('ping_ms')):.2f} ms "
        f"({format_dt(best_ping['dt'])})"
    )
    print(
        f"- Pior ping: {_to_float(worst_ping.get('ping_ms')):.2f} ms "
        f"({format_dt(worst_ping['dt'])})"
    )
    print("")

    trend_7 = compute_window_trend(records, days=7)
    trend_30 = compute_window_trend(records, days=30)
    print_trend_block("Tendencia 7 dias (vs 7 dias anteriores)", trend_7)
    print("")
    print_trend_block("Tendencia 30 dias (vs 30 dias anteriores)", trend_30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
