import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import scripts.speedtest_monitor as speedtest_monitor
import scripts.speedtest_record as speedtest_record
import scripts.speedtest_report as speedtest_report


def _sample_payload(timestamp: str) -> dict:
    return {
        "download": 250_000_000.0,
        "upload": 125_000_000.0,
        "ping": 18.25,
        "timestamp": timestamp,
        "bytes_received": 123456,
        "bytes_sent": 654321,
        "server": {
            "id": "1",
            "name": "Manaus",
            "sponsor": "Provider",
            "country": "Brazil",
            "host": "example.test:8080",
            "d": 20.2,
        },
        "client": {
            "ip": "127.0.0.1",
            "isp": "ISP Test",
            "country": "BR",
        },
    }


def test_record_smoke_writes_history_files(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    jsonl_path = data_dir / "history.jsonl"
    csv_path = data_dir / "history.csv"
    timestamp = "2026-05-30T19:00:00Z"

    monkeypatch.setattr(speedtest_record, "DATA_DIR", data_dir)
    monkeypatch.setattr(speedtest_record, "JSONL_PATH", jsonl_path)
    monkeypatch.setattr(speedtest_record, "CSV_PATH", csv_path)
    monkeypatch.setattr(
        speedtest_record,
        "run_speedtest_json",
        lambda: _sample_payload(timestamp),
    )
    monkeypatch.setattr(speedtest_record.sys, "argv", ["speedtest_record.py"])
    monkeypatch.setattr(
        speedtest_record,
        "run_ping_probe",
        lambda **_kwargs: {
            "target": "1.1.1.1",
            "packet_loss_pct": 0.0,
            "avg_latency_ms": 15.0,
            "jitter_ms": 2.0,
            "transmitted": 8,
            "received": 8,
            "error": None,
        },
    )
    monkeypatch.setattr(speedtest_record, "get_cpu_usage_percent", lambda: 35.0)
    monkeypatch.setattr(speedtest_record, "get_ram_usage_percent", lambda: 48.0)

    exit_code = speedtest_record.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Teste registrado com sucesso." in captured.out
    assert jsonl_path.exists()
    assert csv_path.exists()

    record = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert record["timestamp"] == timestamp
    assert record["download_mbps"] == 250.0
    assert record["upload_mbps"] == 125.0
    assert record["quality_score"] > 0
    assert record["packet_loss_pct_avg"] == 0.0

    with csv_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["server_name"] == "Manaus"


def test_report_smoke_renders_summary(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "history.jsonl"
    base = datetime(2026, 5, 30, 19, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "timestamp": (base - timedelta(hours=2)).isoformat().replace(
                "+00:00", "Z"
            ),
            "download_mbps": 200.0,
            "upload_mbps": 100.0,
            "ping_ms": 20.0,
        },
        {
            "timestamp": (base - timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "download_mbps": 300.0,
            "upload_mbps": 150.0,
            "ping_ms": 10.0,
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item) for item in items) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(speedtest_report, "JSONL_PATH", history_path)
    monkeypatch.setattr(speedtest_report.sys, "argv", ["speedtest_report.py"])

    exit_code = speedtest_report.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Relatorio Speed Pro" in captured.out
    assert "- Total de testes: 2" in captured.out
    assert "Tendencia 7 dias" in captured.out
    assert "Medias gerais" in captured.out
    assert "Percentis (p50/p95/p99)" in captured.out
    assert "Heatmap semanal de performance por hora" in captured.out
    assert "Modo SLA domestico (historico)" in captured.out


def test_monitor_smoke_runs_single_cycle(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(
        speedtest_monitor.signal,
        "signal",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        speedtest_monitor.sys,
        "argv",
        [
            "speedtest_monitor.py",
            "--interval-minutes",
            "0.01",
            "--max-runs",
            "1",
        ],
    )

    def _fake_run_record_once(_args):
        calls.append(1)
        return (
            0,
            {
                "timestamp": "2026-05-30T19:10:00Z",
                "download_mbps": 250.0,
                "upload_mbps": 120.0,
                "ping_ms": 20.0,
                "packet_loss_pct_avg": 0.0,
                "system_cpu_percent": 30.0,
                "system_ram_percent": 40.0,
            },
        )

    monkeypatch.setattr(
        speedtest_monitor,
        "run_record_once",
        _fake_run_record_once,
    )

    exit_code = speedtest_monitor.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(calls) == 1
    assert "Monitor iniciado." in captured.out
    assert "Teste #1 concluido com sucesso." in captured.out
