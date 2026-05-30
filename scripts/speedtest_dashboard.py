#!/usr/bin/env python3
"""Local real-time dashboard server for speed-pro analytics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import speedtest_report  # pylint: disable=wrong-import-position
from scripts.quality_metrics import (  # pylint: disable=wrong-import-position
    average,
    pearson_correlation,
    percentile,
    period_of_day,
    to_float,
)

DASHBOARD_DIR = ROOT_DIR / "dashboard"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Servidor local do dashboard speed-pro."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host bind.")
    parser.add_argument("--port", type=int, default=8787, help="Porta HTTP.")
    parser.add_argument(
        "--history-limit",
        type=int,
        default=300,
        help="Quantidade de pontos na serie temporal da API.",
    )
    return parser.parse_args()


def _safe_records() -> List[Dict[str, Any]]:
    records = speedtest_report.load_records()
    for rec in records:
        speedtest_report.enrich_record(rec)
    return records


def _summary_cards(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {
            "latest": None,
            "total_tests": 0,
            "averages": {},
            "best": {},
            "worst": {},
        }

    latest = records[-1]
    return {
        "latest": {
            "timestamp": latest.get("timestamp"),
            "download_mbps": latest.get("download_mbps"),
            "upload_mbps": latest.get("upload_mbps"),
            "ping_ms": latest.get("ping_ms"),
            "jitter_ms_avg": latest.get("jitter_ms_avg"),
            "packet_loss_pct_avg": latest.get("packet_loss_pct_avg"),
            "quality_score": latest.get("quality_score"),
            "quality_grade": latest.get("quality_grade"),
            "client_isp": latest.get("client_isp"),
            "client_ip": latest.get("client_ip"),
            "plan_name": latest.get("plan_name"),
            "system_cpu_percent": latest.get("system_cpu_percent"),
            "system_ram_percent": latest.get("system_ram_percent"),
        },
        "total_tests": len(records),
        "averages": {
            "download_mbps": average([to_float(r.get("download_mbps")) for r in records]),
            "upload_mbps": average([to_float(r.get("upload_mbps")) for r in records]),
            "ping_ms": average([to_float(r.get("ping_ms")) for r in records]),
            "jitter_ms_avg": average(
                [to_float(r.get("jitter_ms_avg")) for r in records]
            ),
            "packet_loss_pct_avg": average(
                [to_float(r.get("packet_loss_pct_avg")) for r in records]
            ),
            "quality_score": average([to_float(r.get("quality_score")) for r in records]),
        },
        "best": {
            "download_mbps": max(records, key=lambda r: to_float(r.get("download_mbps"))).get(
                "download_mbps"
            ),
            "upload_mbps": max(records, key=lambda r: to_float(r.get("upload_mbps"))).get(
                "upload_mbps"
            ),
            "ping_ms": min(records, key=lambda r: to_float(r.get("ping_ms"))).get(
                "ping_ms"
            ),
            "quality_score": max(records, key=lambda r: to_float(r.get("quality_score"))).get(
                "quality_score"
            ),
        },
        "worst": {
            "download_mbps": min(records, key=lambda r: to_float(r.get("download_mbps"))).get(
                "download_mbps"
            ),
            "upload_mbps": min(records, key=lambda r: to_float(r.get("upload_mbps"))).get(
                "upload_mbps"
            ),
            "ping_ms": max(records, key=lambda r: to_float(r.get("ping_ms"))).get(
                "ping_ms"
            ),
            "quality_score": min(records, key=lambda r: to_float(r.get("quality_score"))).get(
                "quality_score"
            ),
        },
    }


def _percentiles(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {}

    def metric(name: str) -> Dict[str, float]:
        values = [to_float(r.get(name)) for r in records]
        return {
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
            "p99": percentile(values, 99),
        }

    return {
        "download_mbps": metric("download_mbps"),
        "upload_mbps": metric("upload_mbps"),
        "ping_ms": metric("ping_ms"),
        "jitter_ms_avg": metric("jitter_ms_avg"),
        "quality_score": metric("quality_score"),
    }


def _stability_periods(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "madrugada": [],
        "manha": [],
        "tarde": [],
        "noite": [],
    }
    for rec in records:
        buckets[period_of_day(rec["dt"].hour)].append(rec)

    output: List[Dict[str, Any]] = []
    for label in ("madrugada", "manha", "tarde", "noite"):
        data = buckets[label]
        if not data:
            output.append({"period": label, "count": 0, "stability": None})
            continue

        down = [to_float(r.get("download_mbps")) for r in data]
        up = [to_float(r.get("upload_mbps")) for r in data]
        ping = [to_float(r.get("ping_ms")) for r in data]
        loss = [to_float(r.get("packet_loss_pct_avg")) for r in data]

        def _cv(values: List[float]) -> float:
            if len(values) < 2:
                return 0.0
            mean_val = average(values)
            if mean_val == 0:
                return 0.0
            return __import__("statistics").pstdev(values) / mean_val

        stability = 100.0 - (_cv(down) * 35 + _cv(up) * 30 + _cv(ping) * 25 + average(loss) * 4)
        stability = max(0.0, min(100.0, stability))
        output.append(
            {
                "period": label,
                "count": len(data),
                "stability": stability,
                "avg_score": average([to_float(r.get("quality_score")) for r in data]),
            }
        )
    return output


def _weekly_heatmap(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matrix: List[List[List[float]]] = [[[] for _ in range(24)] for _ in range(7)]
    for rec in records:
        matrix[rec["dt"].weekday()][rec["dt"].hour].append(to_float(rec.get("quality_score")))

    output: List[Dict[str, Any]] = []
    for day in range(7):
        for hour in range(24):
            values = matrix[day][hour]
            output.append(
                {
                    "day": day,
                    "hour": hour,
                    "avg_score": average(values) if values else None,
                    "count": len(values),
                }
            )
    return output


def _provider_comparison(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        plan = (rec.get("plan_name") or "sem-plano").strip() or "sem-plano"
        isp = (rec.get("client_isp") or "desconhecido").strip() or "desconhecido"
        ip = (rec.get("client_ip") or "desconhecido").strip() or "desconhecido"
        key = f"{plan} | {isp} | {ip}"
        groups.setdefault(key, []).append(rec)

    ranked = sorted(
        groups.items(),
        key=lambda item: average([to_float(r.get("quality_score")) for r in item[1]]),
        reverse=True,
    )
    out = []
    for key, bucket in ranked[:10]:
        out.append(
            {
                "key": key,
                "count": len(bucket),
                "avg_score": average([to_float(r.get("quality_score")) for r in bucket]),
                "avg_download_mbps": average(
                    [to_float(r.get("download_mbps")) for r in bucket]
                ),
                "avg_upload_mbps": average(
                    [to_float(r.get("upload_mbps")) for r in bucket]
                ),
                "avg_ping_ms": average([to_float(r.get("ping_ms")) for r in bucket]),
                "avg_loss_pct": average(
                    [to_float(r.get("packet_loss_pct_avg")) for r in bucket]
                ),
            }
        )
    return out


def _time_quality(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    hour_scores: Dict[int, List[float]] = {}
    for rec in records:
        hour_scores.setdefault(rec["dt"].hour, []).append(to_float(rec.get("quality_score")))
    if not hour_scores:
        return {"best_hour": None, "worst_hour": None}

    average_scores = {hour: average(scores) for hour, scores in hour_scores.items()}
    best_hour = max(average_scores.items(), key=lambda x: x[1])
    worst_hour = min(average_scores.items(), key=lambda x: x[1])
    return {
        "best_hour": {"hour": best_hour[0], "score": best_hour[1]},
        "worst_hour": {"hour": worst_hour[0], "score": worst_hour[1]},
    }


def _sla_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {
            "below_sla_count": 0,
            "below_sla_ratio": 0.0,
            "below_sla_reasons": {},
        }
    config = {
        "min_download": 100.0,
        "min_upload": 20.0,
        "max_ping": 80.0,
        "max_loss": 2.0,
    }
    reason_counts: Dict[str, int] = {}
    below = 0
    for rec in records:
        reasons = []
        if to_float(rec.get("download_mbps")) < config["min_download"]:
            reasons.append("download")
        if to_float(rec.get("upload_mbps")) < config["min_upload"]:
            reasons.append("upload")
        if to_float(rec.get("ping_ms")) > config["max_ping"]:
            reasons.append("ping")
        if to_float(rec.get("packet_loss_pct_avg")) > config["max_loss"]:
            reasons.append("loss")
        if reasons:
            below += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "below_sla_count": below,
        "below_sla_ratio": (below / len(records)) * 100.0,
        "below_sla_reasons": reason_counts,
    }


def _resource_correlation(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    def corr(resource: str, metric: str) -> Optional[float]:
        xs: List[float] = []
        ys: List[float] = []
        for rec in records:
            rv = rec.get(resource)
            if rv is None:
                continue
            xs.append(to_float(rv))
            ys.append(to_float(rec.get(metric)))
        return pearson_correlation(xs, ys)

    return {
        "cpu_download": corr("system_cpu_percent", "download_mbps"),
        "cpu_upload": corr("system_cpu_percent", "upload_mbps"),
        "cpu_ping": corr("system_cpu_percent", "ping_ms"),
        "cpu_score": corr("system_cpu_percent", "quality_score"),
        "ram_download": corr("system_ram_percent", "download_mbps"),
        "ram_upload": corr("system_ram_percent", "upload_mbps"),
        "ram_ping": corr("system_ram_percent", "ping_ms"),
        "ram_score": corr("system_ram_percent", "quality_score"),
    }


def _series(records: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    sliced = records[-limit:] if limit > 0 else records
    return [
        {
            "timestamp": rec.get("timestamp"),
            "download_mbps": rec.get("download_mbps"),
            "upload_mbps": rec.get("upload_mbps"),
            "ping_ms": rec.get("ping_ms"),
            "jitter_ms_avg": rec.get("jitter_ms_avg"),
            "packet_loss_pct_avg": rec.get("packet_loss_pct_avg"),
            "quality_score": rec.get("quality_score"),
            "system_cpu_percent": rec.get("system_cpu_percent"),
            "system_ram_percent": rec.get("system_ram_percent"),
        }
        for rec in sliced
    ]


def build_dashboard_payload(limit: int) -> Dict[str, Any]:
    records = _safe_records()
    cards = _summary_cards(records)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "total_records": len(records),
        },
        "cards": cards,
        "percentiles": _percentiles(records),
        "stability_periods": _stability_periods(records),
        "weekly_heatmap": _weekly_heatmap(records),
        "providers": _provider_comparison(records),
        "time_quality": _time_quality(records),
        "sla": _sla_summary(records),
        "correlation": _resource_correlation(records),
        "series": _series(records, limit),
    }
    return payload


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serve dashboard static assets and JSON API."""

    def __init__(self, *args, dashboard_limit: int = 300, **kwargs):
        self.dashboard_limit = dashboard_limit
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/summary":
            params = parse_qs(parsed.query)
            limit = self.dashboard_limit
            if "limit" in params:
                try:
                    limit = max(1, int(params["limit"][0]))
                except (TypeError, ValueError):
                    pass
            payload = build_dashboard_payload(limit=limit)
            self._send_json(payload, status=HTTPStatus.OK)
            return

        if parsed.path in ("/", "/dashboard"):
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format_string: str, *args) -> None:
        print(
            f"[dashboard] {self.address_string()} - "
            f"{format_string % args}",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    if not DASHBOARD_DIR.exists():
        print(
            "Diretorio do dashboard nao encontrado. "
            f"Esperado em: {DASHBOARD_DIR}",
            file=sys.stderr,
        )
        return 1

    handler = partial(DashboardHandler, dashboard_limit=args.history_limit)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard Speed Pro ativo em {url}")
    print("Use Ctrl+C para encerrar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Dashboard finalizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
