#!/usr/bin/env python3
"""Run speedtest and append results to local history files."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
JSONL_PATH = DATA_DIR / "history.jsonl"
CSV_PATH = DATA_DIR / "history.csv"
SPEEDTEST_SCRIPT = ROOT_DIR / "speedtest.py"
MAX_ATTEMPTS = 2

CSV_FIELDS = [
    "timestamp",
    "ping_ms",
    "download_mbps",
    "upload_mbps",
    "download_bps",
    "upload_bps",
    "bytes_received",
    "bytes_sent",
    "server_id",
    "server_name",
    "server_sponsor",
    "server_country",
    "server_host",
    "distance_km",
    "client_ip",
    "client_isp",
    "client_country",
]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_json(output: str) -> Dict[str, Any]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise ValueError("No JSON payload found in speedtest output.")


def now_utc_isoz() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def build_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    server = payload.get("server") or {}
    client = payload.get("client") or {}

    download_bps = _to_float(payload.get("download"))
    upload_bps = _to_float(payload.get("upload"))
    ping_ms = _to_float(payload.get("ping"))

    return {
        "timestamp": payload.get("timestamp") or now_utc_isoz(),
        "ping_ms": round(ping_ms, 3),
        "download_mbps": round(download_bps / 1_000_000, 2),
        "upload_mbps": round(upload_bps / 1_000_000, 2),
        "download_bps": round(download_bps, 3),
        "upload_bps": round(upload_bps, 3),
        "bytes_received": _to_int(payload.get("bytes_received")),
        "bytes_sent": _to_int(payload.get("bytes_sent")),
        "server_id": server.get("id"),
        "server_name": server.get("name"),
        "server_sponsor": server.get("sponsor"),
        "server_country": server.get("country"),
        "server_host": server.get("host"),
        "distance_km": round(_to_float(server.get("d")), 2),
        "client_ip": client.get("ip"),
        "client_isp": client.get("isp"),
        "client_country": client.get("country"),
    }


def append_jsonl(record: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_csv(record: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    should_write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if should_write_header:
            writer.writeheader()
        writer.writerow(record)


def main() -> int:
    try:
        payload = run_speedtest_json()
        record = build_record(payload)
        append_jsonl(record)
        append_csv(record)
    except Exception as exc:  # pylint: disable=broad-except
        print("Falha ao registrar o speed test.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    print("Teste registrado com sucesso.")
    print(f"Timestamp: {record['timestamp']}")
    print(f"Ping: {record['ping_ms']} ms")
    print(f"Download: {record['download_mbps']} Mbit/s")
    print(f"Upload: {record['upload_mbps']} Mbit/s")
    print(f"Servidor: {record['server_sponsor']} ({record['server_name']})")
    print(f"JSONL: {JSONL_PATH}")
    print(f"CSV: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
