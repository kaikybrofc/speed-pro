#!/usr/bin/env python3
"""Run speedtest and append enriched results to local history files."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.quality_metrics import (  # pylint: disable=wrong-import-position
    compute_quality_score,
    mean_of_existing,
    quality_grade,
    to_float,
)

DATA_DIR = ROOT_DIR / "data"
JSONL_PATH = DATA_DIR / "history.jsonl"
CSV_PATH = DATA_DIR / "history.csv"
SPEEDTEST_SCRIPT = ROOT_DIR / "speedtest.py"
MAX_ATTEMPTS = 2

CSV_FIELDS = [
    "timestamp",
    "plan_name",
    "ping_ms",
    "jitter_ms_avg",
    "packet_loss_pct_avg",
    "download_mbps",
    "upload_mbps",
    "quality_score",
    "quality_grade",
    "download_bps",
    "upload_bps",
    "bytes_received",
    "bytes_sent",
    "speedtest_duration_seconds",
    "server_id",
    "server_name",
    "server_sponsor",
    "server_country",
    "server_host",
    "distance_km",
    "client_ip",
    "client_isp",
    "client_country",
    "ping_target",
    "ping_pre_packet_loss_pct",
    "ping_pre_avg_latency_ms",
    "ping_pre_jitter_ms",
    "ping_pre_transmitted",
    "ping_pre_received",
    "ping_post_packet_loss_pct",
    "ping_post_avg_latency_ms",
    "ping_post_jitter_ms",
    "ping_post_transmitted",
    "ping_post_received",
    "system_cpu_percent",
    "system_ram_percent",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa speed test e registra historico enriquecido."
    )
    parser.add_argument(
        "--plan",
        default=os.environ.get("SPEED_PRO_PLAN", ""),
        help="Nome do plano/perfil da internet para comparacoes.",
    )
    parser.add_argument(
        "--ping-target",
        default=os.environ.get("SPEED_PRO_PING_TARGET", "1.1.1.1"),
        help="Host alvo para ping continuo pre/pós teste.",
    )
    parser.add_argument(
        "--ping-count",
        type=int,
        default=int(os.environ.get("SPEED_PRO_PING_COUNT", "8")),
        help="Quantidade de pacotes em cada sonda de ping (padrao: 8).",
    )
    parser.add_argument(
        "--ping-timeout",
        type=int,
        default=int(os.environ.get("SPEED_PRO_PING_TIMEOUT", "2")),
        help="Timeout por pacote no ping em segundos (padrao: 2).",
    )
    args = parser.parse_args()

    if args.ping_count <= 0:
        parser.error("--ping-count deve ser maior que zero.")
    if args.ping_timeout <= 0:
        parser.error("--ping-timeout deve ser maior que zero.")
    return args


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def now_utc_isoz() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_json(output: str) -> Dict[str, Any]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise ValueError("No JSON payload found in speedtest output.")


def run_speedtest_json() -> Dict[str, Any]:
    cmd = [sys.executable, str(SPEEDTEST_SCRIPT), "--json"]
    errors: List[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        combined_output = "\n".join(
            part.strip() for part in (proc.stdout, proc.stderr) if part.strip()
        )

        if proc.returncode == 0:
            try:
                return _extract_json(proc.stdout)
            except ValueError as exc:
                errors.append(f"Attempt {attempt}: {exc}")
        else:
            message = combined_output or "Unknown speedtest execution error."
            errors.append(f"Attempt {attempt}: {message}")

    raise RuntimeError("\n".join(errors))


def _read_cpu_times() -> Optional[tuple[int, int]]:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
    except (OSError, FileNotFoundError):
        return None

    if not first_line.startswith("cpu "):
        return None

    parts = first_line.split()[1:]
    if len(parts) < 5:
        return None

    values = [int(part) for part in parts]
    idle = values[3] + values[4]
    total = sum(values)
    return idle, total


def get_cpu_usage_percent(sample_seconds: float = 0.25) -> Optional[float]:
    sample_a = _read_cpu_times()
    if sample_a is None:
        return None

    time.sleep(sample_seconds)
    sample_b = _read_cpu_times()
    if sample_b is None:
        return None

    idle_delta = sample_b[0] - sample_a[0]
    total_delta = sample_b[1] - sample_a[1]
    if total_delta <= 0:
        return None

    usage = (1.0 - (idle_delta / total_delta)) * 100.0
    return round(max(0.0, min(100.0, usage)), 2)


def get_ram_usage_percent() -> Optional[float]:
    mem_total = None
    mem_available = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    mem_total = float(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_available = float(line.split()[1])
    except (OSError, FileNotFoundError):
        return None

    if not mem_total or mem_available is None:
        return None
    if mem_total <= 0:
        return None

    used_pct = ((mem_total - mem_available) / mem_total) * 100.0
    return round(max(0.0, min(100.0, used_pct)), 2)


def _parse_loss_pct(line: str) -> Optional[float]:
    patterns = [
        r"([0-9]+(?:[.][0-9]+)?)%\s*packet loss",
        r"([0-9]+(?:[.][0-9]+)?)%\s*de perda de pacotes",
    ]
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return to_float(match.group(1), 0.0)
    return None


def _parse_transmitted_received(line: str) -> tuple[Optional[int], Optional[int]]:
    patterns = [
        r"([0-9]+)\s+packets transmitted,\s*([0-9]+)\s+(?:packets )?received",
        r"([0-9]+)\s+pacotes transmitidos,\s*([0-9]+)\s+recebidos",
    ]
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return _to_int(match.group(1)), _to_int(match.group(2))
    return None, None


def _parse_avg_jitter(line: str) -> tuple[Optional[float], Optional[float]]:
    match = re.search(
        r"(?:rtt|round-trip)[^=]*=\s*"
        r"([0-9]+(?:[.][0-9]+)?)/"
        r"([0-9]+(?:[.][0-9]+)?)/"
        r"([0-9]+(?:[.][0-9]+)?)/"
        r"([0-9]+(?:[.][0-9]+)?)\s*ms",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    avg_latency = to_float(match.group(2), 0.0)
    jitter = to_float(match.group(4), 0.0)
    return avg_latency, jitter


def run_ping_probe(
    *,
    target: str,
    count: int = 8,
    timeout: int = 2,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "target": target,
        "packet_loss_pct": None,
        "avg_latency_ms": None,
        "jitter_ms": None,
        "transmitted": None,
        "received": None,
        "error": None,
    }

    cmd = ["ping", "-n", "-c", str(count), "-W", str(timeout), target]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        result["error"] = "ping command not found"
        return result

    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    lines = [line.strip() for line in output.splitlines() if line.strip()]

    for line in lines:
        transmitted, received = _parse_transmitted_received(line)
        if transmitted is not None:
            result["transmitted"] = transmitted
            result["received"] = received

        loss_pct = _parse_loss_pct(line)
        if loss_pct is not None:
            result["packet_loss_pct"] = round(loss_pct, 3)

        avg_latency, jitter = _parse_avg_jitter(line)
        if avg_latency is not None:
            result["avg_latency_ms"] = round(avg_latency, 3)
            result["jitter_ms"] = round(jitter or 0.0, 3)

    if proc.returncode != 0 and result["packet_loss_pct"] is None:
        result["error"] = "ping probe failed"

    return result


def build_record(
    payload: Dict[str, Any],
    *,
    plan_name: str,
    ping_target: str,
    ping_pre: Dict[str, Any],
    ping_post: Dict[str, Any],
    system_cpu_percent: Optional[float],
    system_ram_percent: Optional[float],
    speedtest_duration_seconds: float,
) -> Dict[str, Any]:
    server = payload.get("server") or {}
    client = payload.get("client") or {}

    download_bps = to_float(payload.get("download"))
    upload_bps = to_float(payload.get("upload"))
    ping_ms = to_float(payload.get("ping"))

    jitter_avg = mean_of_existing(
        [ping_pre.get("jitter_ms"), ping_post.get("jitter_ms")], fallback=0.0
    )
    packet_loss_avg = mean_of_existing(
        [ping_pre.get("packet_loss_pct"), ping_post.get("packet_loss_pct")],
        fallback=0.0,
    )

    download_mbps = round(download_bps / 1_000_000, 2)
    upload_mbps = round(upload_bps / 1_000_000, 2)

    score = compute_quality_score(
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        ping_ms=ping_ms,
        jitter_ms=jitter_avg,
        packet_loss_pct=packet_loss_avg,
    )

    return {
        "timestamp": payload.get("timestamp") or now_utc_isoz(),
        "plan_name": plan_name or "",
        "ping_ms": round(ping_ms, 3),
        "jitter_ms_avg": round(jitter_avg, 3),
        "packet_loss_pct_avg": round(packet_loss_avg, 3),
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "quality_score": score,
        "quality_grade": quality_grade(score),
        "download_bps": round(download_bps, 3),
        "upload_bps": round(upload_bps, 3),
        "bytes_received": _to_int(payload.get("bytes_received")),
        "bytes_sent": _to_int(payload.get("bytes_sent")),
        "speedtest_duration_seconds": round(speedtest_duration_seconds, 3),
        "server_id": server.get("id"),
        "server_name": server.get("name"),
        "server_sponsor": server.get("sponsor"),
        "server_country": server.get("country"),
        "server_host": server.get("host"),
        "distance_km": round(to_float(server.get("d")), 2),
        "client_ip": client.get("ip"),
        "client_isp": client.get("isp"),
        "client_country": client.get("country"),
        "ping_target": ping_target,
        "ping_pre_packet_loss_pct": ping_pre.get("packet_loss_pct"),
        "ping_pre_avg_latency_ms": ping_pre.get("avg_latency_ms"),
        "ping_pre_jitter_ms": ping_pre.get("jitter_ms"),
        "ping_pre_transmitted": ping_pre.get("transmitted"),
        "ping_pre_received": ping_pre.get("received"),
        "ping_post_packet_loss_pct": ping_post.get("packet_loss_pct"),
        "ping_post_avg_latency_ms": ping_post.get("avg_latency_ms"),
        "ping_post_jitter_ms": ping_post.get("jitter_ms"),
        "ping_post_transmitted": ping_post.get("transmitted"),
        "ping_post_received": ping_post.get("received"),
        "system_cpu_percent": system_cpu_percent,
        "system_ram_percent": system_ram_percent,
    }


def collect_record(
    *,
    plan_name: str = "",
    ping_target: str = "1.1.1.1",
    ping_count: int = 8,
    ping_timeout: int = 2,
) -> Dict[str, Any]:
    system_cpu_percent = get_cpu_usage_percent()
    system_ram_percent = get_ram_usage_percent()

    ping_pre = run_ping_probe(
        target=ping_target, count=ping_count, timeout=ping_timeout
    )

    started_at = time.monotonic()
    payload = run_speedtest_json()
    speedtest_duration = time.monotonic() - started_at

    ping_post = run_ping_probe(
        target=ping_target, count=ping_count, timeout=ping_timeout
    )

    return build_record(
        payload,
        plan_name=plan_name.strip(),
        ping_target=ping_target,
        ping_pre=ping_pre,
        ping_post=ping_post,
        system_cpu_percent=system_cpu_percent,
        system_ram_percent=system_ram_percent,
        speedtest_duration_seconds=speedtest_duration,
    )


def append_jsonl(record: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _csv_header_matches_schema() -> bool:
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        return False
    try:
        with CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
    except OSError:
        return False
    return header == CSV_FIELDS


def rebuild_csv_from_jsonl() -> None:
    records: List[Dict[str, Any]] = []
    if JSONL_PATH.exists():
        with JSONL_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue

    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({field: rec.get(field) for field in CSV_FIELDS})


def append_csv(record: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists() and not _csv_header_matches_schema():
        rebuild_csv_from_jsonl()

    should_write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if should_write_header:
            writer.writeheader()
        writer.writerow(record)


def store_record(record: Dict[str, Any]) -> None:
    append_jsonl(record)
    append_csv(record)


def print_record_summary(record: Dict[str, Any]) -> None:
    print("Teste registrado com sucesso.")
    print(f"Timestamp: {record['timestamp']}")
    print(f"Ping: {record['ping_ms']} ms")
    print(f"Jitter: {record['jitter_ms_avg']} ms")
    print(f"Perda de pacote: {record['packet_loss_pct_avg']}%")
    print(f"Download: {record['download_mbps']} Mbit/s")
    print(f"Upload: {record['upload_mbps']} Mbit/s")
    print(
        f"Score de qualidade: {record['quality_score']}/100 "
        f"({record['quality_grade']})"
    )
    print(f"Servidor: {record['server_sponsor']} ({record['server_name']})")
    if record.get("plan_name"):
        print(f"Plano: {record['plan_name']}")
    print(
        "Uso do sistema: "
        f"CPU={record.get('system_cpu_percent')}% "
        f"RAM={record.get('system_ram_percent')}%"
    )
    print(f"JSONL: {JSONL_PATH}")
    print(f"CSV: {CSV_PATH}")


def main() -> int:
    args = parse_args()
    try:
        record = collect_record(
            plan_name=args.plan,
            ping_target=args.ping_target,
            ping_count=args.ping_count,
            ping_timeout=args.ping_timeout,
        )
        store_record(record)
    except Exception as exc:  # pylint: disable=broad-except
        print("Falha ao registrar o speed test.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    print_record_summary(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
