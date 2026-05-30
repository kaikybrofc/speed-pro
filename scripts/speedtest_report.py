#!/usr/bin/env python3
"""Generate advanced analytics report from recorded speedtest history."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.quality_metrics import (  # pylint: disable=wrong-import-position
    average,
    compute_quality_score,
    format_correlation,
    pearson_correlation,
    percentile,
    period_of_day,
    quality_grade,
    to_float,
)

JSONL_PATH = ROOT_DIR / "data" / "history.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera relatorio analitico avancado do historico speed-pro."
    )
    parser.add_argument("--sla-min-download-mbps", type=float, default=100.0)
    parser.add_argument("--sla-min-upload-mbps", type=float, default=20.0)
    parser.add_argument("--sla-max-ping-ms", type=float, default=80.0)
    parser.add_argument("--sla-max-packet-loss-pct", type=float, default=2.0)
    parser.add_argument("--sla-window-minutes", type=float, default=30.0)
    parser.add_argument("--sla-ignore-high-cpu-percent", type=float, default=85.0)
    parser.add_argument("--sla-ignore-high-ram-percent", type=float, default=90.0)
    return parser.parse_args()


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def enrich_record(record: Dict[str, Any]) -> None:
    record["download_mbps"] = to_float(record.get("download_mbps"))
    record["upload_mbps"] = to_float(record.get("upload_mbps"))
    record["ping_ms"] = to_float(record.get("ping_ms"))
    record["jitter_ms_avg"] = to_float(record.get("jitter_ms_avg"))
    record["packet_loss_pct_avg"] = to_float(record.get("packet_loss_pct_avg"))
    record["system_cpu_percent"] = (
        None
        if record.get("system_cpu_percent") is None
        else to_float(record.get("system_cpu_percent"))
    )
    record["system_ram_percent"] = (
        None
        if record.get("system_ram_percent") is None
        else to_float(record.get("system_ram_percent"))
    )

    if record["jitter_ms_avg"] <= 0:
        record["jitter_ms_avg"] = average(
            [
                to_float(record.get("ping_pre_jitter_ms"), 0.0),
                to_float(record.get("ping_post_jitter_ms"), 0.0),
            ]
        )

    if record["packet_loss_pct_avg"] <= 0:
        record["packet_loss_pct_avg"] = average(
            [
                to_float(record.get("ping_pre_packet_loss_pct"), 0.0),
                to_float(record.get("ping_post_packet_loss_pct"), 0.0),
            ]
        )

    score = record.get("quality_score")
    if score is None:
        score = compute_quality_score(
            download_mbps=record["download_mbps"],
            upload_mbps=record["upload_mbps"],
            ping_ms=record["ping_ms"],
            jitter_ms=record["jitter_ms_avg"],
            packet_loss_pct=record["packet_loss_pct_avg"],
        )
    record["quality_score"] = to_float(score)
    record["quality_grade"] = record.get("quality_grade") or quality_grade(
        record["quality_score"]
    )


def format_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def pstats(values: Sequence[float]) -> Dict[str, float]:
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


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
        current_values = [to_float(r.get(metric)) for r in current]
        previous_values = [to_float(r.get(metric)) for r in previous]
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
        delta_text = "n/a" if delta is None else f"{delta:+.2f}%"
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


def print_percentile_block(records: List[Dict[str, Any]]) -> None:
    print("Percentis (p50/p95/p99)")
    mapping = [
        ("Ping (ms)", [r["ping_ms"] for r in records], "ms"),
        ("Jitter (ms)", [r["jitter_ms_avg"] for r in records], "ms"),
        ("Download (Mbps)", [r["download_mbps"] for r in records], "Mbps"),
        ("Upload (Mbps)", [r["upload_mbps"] for r in records], "Mbps"),
        ("Score qualidade", [r["quality_score"] for r in records], ""),
    ]
    for label, values, unit in mapping:
        ps = pstats(values)
        suffix = f" {unit}" if unit else ""
        print(
            f"- {label}: "
            f"p50={ps['p50']:.2f}{suffix} "
            f"p95={ps['p95']:.2f}{suffix} "
            f"p99={ps['p99']:.2f}{suffix}"
        )


def _coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_val = average(values)
    if math.isclose(mean_val, 0.0):
        return 0.0
    return statistics.pstdev(values) / mean_val


def print_stability_by_period(records: List[Dict[str, Any]]) -> None:
    print("Estabilidade por faixa horaria")
    groups: Dict[str, List[Dict[str, Any]]] = {
        "madrugada": [],
        "manha": [],
        "tarde": [],
        "noite": [],
    }
    for record in records:
        groups[period_of_day(record["dt"].hour)].append(record)

    for period_name in ("madrugada", "manha", "tarde", "noite"):
        bucket = groups[period_name]
        if not bucket:
            print(f"- {period_name}: sem dados")
            continue

        down = [r["download_mbps"] for r in bucket]
        up = [r["upload_mbps"] for r in bucket]
        ping = [r["ping_ms"] for r in bucket]
        loss = [r["packet_loss_pct_avg"] for r in bucket]
        score = [r["quality_score"] for r in bucket]

        cv_down = _coefficient_of_variation(down)
        cv_up = _coefficient_of_variation(up)
        cv_ping = _coefficient_of_variation(ping)
        loss_avg = average(loss)

        stability_index = 100.0 - (
            cv_down * 35.0 + cv_up * 30.0 + cv_ping * 25.0 + loss_avg * 4.0
        )
        stability_index = max(0.0, min(100.0, stability_index))

        print(
            f"- {period_name}: "
            f"amostras={len(bucket)} "
            f"score-medio={average(score):.2f} "
            f"indice-estabilidade={stability_index:.2f}"
        )


def _score_to_symbol(score: float) -> str:
    palette = " .:-=+*#%@"
    normalized = max(0.0, min(100.0, score)) / 100.0
    idx = int(round(normalized * (len(palette) - 1)))
    return palette[idx]


def print_weekly_heatmap(records: List[Dict[str, Any]]) -> None:
    print("Heatmap semanal de performance por hora (score medio)")
    day_labels = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    matrix: List[List[List[float]]] = [[[] for _ in range(24)] for _ in range(7)]

    for record in records:
        day = record["dt"].weekday()
        hour = record["dt"].hour
        matrix[day][hour].append(record["quality_score"])

    for day, label in enumerate(day_labels):
        row_symbols = []
        for hour in range(24):
            cell = matrix[day][hour]
            if not cell:
                row_symbols.append(" ")
            else:
                row_symbols.append(_score_to_symbol(average(cell)))
        day_scores = [
            average(matrix[day][hour]) for hour in range(24) if matrix[day][hour]
        ]
        day_avg = average(day_scores) if day_scores else 0.0
        print(f"- {label}: {''.join(row_symbols)} | media={day_avg:.2f}")
    print("- Legenda: vazio=sem dados,  .=pior ... @=melhor")


def print_provider_comparison(records: List[Dict[str, Any]]) -> None:
    print("Comparacao automatica entre provedores/planos")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        plan = (record.get("plan_name") or "sem-plano").strip() or "sem-plano"
        isp = (record.get("client_isp") or "desconhecido").strip() or "desconhecido"
        ip = (record.get("client_ip") or "desconhecido").strip() or "desconhecido"
        key = f"{plan} | {isp} | {ip}"
        groups.setdefault(key, []).append(record)

    ranked = sorted(
        groups.items(),
        key=lambda item: average([r["quality_score"] for r in item[1]]),
        reverse=True,
    )

    for key, bucket in ranked:
        print(
            f"- {key}: "
            f"n={len(bucket)} "
            f"score={average([r['quality_score'] for r in bucket]):.2f} "
            f"down={average([r['download_mbps'] for r in bucket]):.2f}Mbps "
            f"up={average([r['upload_mbps'] for r in bucket]):.2f}Mbps "
            f"ping={average([r['ping_ms'] for r in bucket]):.2f}ms "
            f"loss={average([r['packet_loss_pct_avg'] for r in bucket]):.2f}%"
        )


def _scenario_score_meeting(record: Dict[str, Any]) -> float:
    low_ping = max(0.0, 100.0 - record["ping_ms"] * 1.2)
    low_jitter = max(0.0, 100.0 - record["jitter_ms_avg"] * 2.0)
    low_loss = max(0.0, 100.0 - record["packet_loss_pct_avg"] * 10.0)
    return (
        record["quality_score"] * 0.5
        + low_ping * 0.25
        + low_jitter * 0.15
        + low_loss * 0.1
    )


def _scenario_score_gaming(record: Dict[str, Any]) -> float:
    low_ping = max(0.0, 100.0 - record["ping_ms"] * 1.4)
    low_jitter = max(0.0, 100.0 - record["jitter_ms_avg"] * 2.5)
    low_loss = max(0.0, 100.0 - record["packet_loss_pct_avg"] * 12.0)
    return (
        record["quality_score"] * 0.35
        + low_ping * 0.35
        + low_jitter * 0.2
        + low_loss * 0.1
    )


def _scenario_score_upload(record: Dict[str, Any]) -> float:
    upload_norm = min(100.0, (record["upload_mbps"] / 100.0) * 100.0)
    low_loss = max(0.0, 100.0 - record["packet_loss_pct_avg"] * 10.0)
    return upload_norm * 0.6 + record["quality_score"] * 0.25 + low_loss * 0.15


def _best_worst_hour(
    records: List[Dict[str, Any]], score_fn
) -> Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
    per_hour: Dict[int, List[float]] = {}
    for record in records:
        per_hour.setdefault(record["dt"].hour, []).append(score_fn(record))
    if not per_hour:
        return None, None

    avg_per_hour = {hour: average(scores) for hour, scores in per_hour.items()}
    best = max(avg_per_hour.items(), key=lambda x: x[1])
    worst = min(avg_per_hour.items(), key=lambda x: x[1])
    return best, worst


def print_best_worst_hours(records: List[Dict[str, Any]]) -> None:
    print("Deteccao de hora ideal e hora ruim")
    configs = [
        ("reunioes", _scenario_score_meeting),
        ("jogos", _scenario_score_gaming),
        ("upload", _scenario_score_upload),
    ]
    for label, scorer in configs:
        best, worst = _best_worst_hour(records, scorer)
        if not best or not worst:
            print(f"- {label}: sem dados")
            continue
        print(
            f"- {label}: ideal={best[0]:02d}h (score {best[1]:.2f}) | "
            f"ruim={worst[0]:02d}h (score {worst[1]:.2f})"
        )


def evaluate_record_sla(
    record: Dict[str, Any], args: argparse.Namespace
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if record["download_mbps"] < args.sla_min_download_mbps:
        reasons.append("download baixo")
    if record["upload_mbps"] < args.sla_min_upload_mbps:
        reasons.append("upload baixo")
    if record["ping_ms"] > args.sla_max_ping_ms:
        reasons.append("ping alto")
    if record["packet_loss_pct_avg"] > args.sla_max_packet_loss_pct:
        reasons.append("perda de pacote alta")
    return bool(reasons), reasons


def is_local_load_high(record: Dict[str, Any], args: argparse.Namespace) -> bool:
    cpu = record.get("system_cpu_percent")
    ram = record.get("system_ram_percent")
    cpu_high = cpu is not None and to_float(cpu) >= args.sla_ignore_high_cpu_percent
    ram_high = ram is not None and to_float(ram) >= args.sla_ignore_high_ram_percent
    return cpu_high or ram_high


def _estimated_interval_minutes(records: List[Dict[str, Any]], index: int) -> float:
    if len(records) <= 1:
        return 30.0

    if index < len(records) - 1:
        delta = (records[index + 1]["dt"] - records[index]["dt"]).total_seconds() / 60.0
        if delta > 0:
            return delta

    deltas = [
        (records[i + 1]["dt"] - records[i]["dt"]).total_seconds() / 60.0
        for i in range(len(records) - 1)
        if (records[i + 1]["dt"] - records[i]["dt"]).total_seconds() > 0
    ]
    if not deltas:
        return 30.0
    return statistics.median(deltas)


def print_sla_block(records: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    print("Modo SLA domestico (historico)")
    total_bad = 0.0
    total_suppressed = 0.0
    max_streak = 0.0
    current_streak = 0.0
    breaches = 0
    reason_counter: Dict[str, int] = {}

    for index, record in enumerate(records):
        interval = _estimated_interval_minutes(records, index)
        bad, reasons = evaluate_record_sla(record, args)
        high_load = is_local_load_high(record, args)

        if bad and high_load:
            total_suppressed += interval
            current_streak = 0.0
            continue

        if bad:
            for reason in reasons:
                reason_counter[reason] = reason_counter.get(reason, 0) + 1
            previous = current_streak
            current_streak += interval
            total_bad += interval
            max_streak = max(max_streak, current_streak)
            if previous < args.sla_window_minutes <= current_streak:
                breaches += 1
        else:
            current_streak = 0.0

    print(
        f"- Janela SLA configurada: {args.sla_window_minutes:.1f} min | "
        f"min-down={args.sla_min_download_mbps}Mbps "
        f"min-up={args.sla_min_upload_mbps}Mbps "
        f"max-ping={args.sla_max_ping_ms}ms "
        f"max-loss={args.sla_max_packet_loss_pct}%"
    )
    print(
        f"- Minutos abaixo do SLA: {total_bad:.1f} | "
        f"max-streak: {max_streak:.1f} | "
        f"breaches: {breaches}"
    )
    print(
        f"- Minutos suprimidos por carga local alta (CPU/RAM): "
        f"{total_suppressed:.1f}"
    )
    if reason_counter:
        ordered = sorted(reason_counter.items(), key=lambda item: item[1], reverse=True)
        print(
            "- Principais causas: "
            + ", ".join(f"{name} ({count})" for name, count in ordered)
        )
    else:
        print("- Principais causas: nenhuma")


def print_resource_correlation(records: List[Dict[str, Any]]) -> None:
    print("Correlacao com uso da maquina (CPU/RAM)")

    def pairs(metric_name: str, resource_name: str) -> Tuple[List[float], List[float]]:
        xs: List[float] = []
        ys: List[float] = []
        for rec in records:
            resource_value = rec.get(resource_name)
            if resource_value is None:
                continue
            xs.append(to_float(resource_value))
            ys.append(to_float(rec.get(metric_name)))
        return xs, ys

    cpu_download = pearson_correlation(*pairs("download_mbps", "system_cpu_percent"))
    cpu_upload = pearson_correlation(*pairs("upload_mbps", "system_cpu_percent"))
    cpu_ping = pearson_correlation(*pairs("ping_ms", "system_cpu_percent"))
    cpu_score = pearson_correlation(*pairs("quality_score", "system_cpu_percent"))

    ram_download = pearson_correlation(*pairs("download_mbps", "system_ram_percent"))
    ram_upload = pearson_correlation(*pairs("upload_mbps", "system_ram_percent"))
    ram_ping = pearson_correlation(*pairs("ping_ms", "system_ram_percent"))
    ram_score = pearson_correlation(*pairs("quality_score", "system_ram_percent"))

    print(
        "- CPU  vs (down/up/ping/score): "
        f"{format_correlation(cpu_download)} / "
        f"{format_correlation(cpu_upload)} / "
        f"{format_correlation(cpu_ping)} / "
        f"{format_correlation(cpu_score)}"
    )
    print(
        "- RAM  vs (down/up/ping/score): "
        f"{format_correlation(ram_download)} / "
        f"{format_correlation(ram_upload)} / "
        f"{format_correlation(ram_ping)} / "
        f"{format_correlation(ram_score)}"
    )


def main() -> int:
    args = parse_args()
    records = load_records()
    if not records:
        print("Nenhum histórico encontrado.")
        print("Execute `npm run record` para gerar o primeiro registro.")
        return 1

    for record in records:
        enrich_record(record)

    first = records[0]
    last = records[-1]

    downloads = [r["download_mbps"] for r in records]
    uploads = [r["upload_mbps"] for r in records]
    pings = [r["ping_ms"] for r in records]
    jitters = [r["jitter_ms_avg"] for r in records]
    losses = [r["packet_loss_pct_avg"] for r in records]
    scores = [r["quality_score"] for r in records]

    best_download = max(records, key=lambda item: item["download_mbps"])
    worst_download = min(records, key=lambda item: item["download_mbps"])
    best_upload = max(records, key=lambda item: item["upload_mbps"])
    worst_upload = min(records, key=lambda item: item["upload_mbps"])
    best_ping = min(records, key=lambda item: item["ping_ms"])
    worst_ping = max(records, key=lambda item: item["ping_ms"])

    print("Relatorio Speed Pro")
    print(f"- Total de testes: {len(records)}")
    print(f"- Inicio: {format_dt(first['dt'])}")
    print(f"- Ultimo: {format_dt(last['dt'])}")
    print("")
    print("Medias gerais")
    print(f"- Ping: {average(pings):.2f} ms")
    print(f"- Jitter: {average(jitters):.2f} ms")
    print(f"- Perda de pacote: {average(losses):.2f}%")
    print(f"- Download: {average(downloads):.2f} Mbps")
    print(f"- Upload: {average(uploads):.2f} Mbps")
    print(
        f"- Score de qualidade: {average(scores):.2f}/100 "
        f"(grade {quality_grade(average(scores))})"
    )
    print("")
    print("Melhores e piores")
    print(
        f"- Melhor download: {best_download['download_mbps']:.2f} Mbps "
        f"({format_dt(best_download['dt'])})"
    )
    print(
        f"- Pior download: {worst_download['download_mbps']:.2f} Mbps "
        f"({format_dt(worst_download['dt'])})"
    )
    print(
        f"- Melhor upload: {best_upload['upload_mbps']:.2f} Mbps "
        f"({format_dt(best_upload['dt'])})"
    )
    print(
        f"- Pior upload: {worst_upload['upload_mbps']:.2f} Mbps "
        f"({format_dt(worst_upload['dt'])})"
    )
    print(
        f"- Melhor ping: {best_ping['ping_ms']:.2f} ms "
        f"({format_dt(best_ping['dt'])})"
    )
    print(
        f"- Pior ping: {worst_ping['ping_ms']:.2f} ms "
        f"({format_dt(worst_ping['dt'])})"
    )
    print("")

    print_percentile_block(records)
    print("")

    trend_7 = compute_window_trend(records, days=7)
    trend_30 = compute_window_trend(records, days=30)
    print_trend_block("Tendencia 7 dias (vs 7 dias anteriores)", trend_7)
    print("")
    print_trend_block("Tendencia 30 dias (vs 30 dias anteriores)", trend_30)
    print("")

    print_stability_by_period(records)
    print("")
    print_weekly_heatmap(records)
    print("")
    print_provider_comparison(records)
    print("")
    print_best_worst_hours(records)
    print("")
    print_sla_block(records, args)
    print("")
    print_resource_correlation(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
