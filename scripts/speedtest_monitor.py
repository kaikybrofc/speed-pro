#!/usr/bin/env python3
"""Run speed tests continuously at a fixed interval."""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
RECORD_SCRIPT = ROOT_DIR / "scripts" / "speedtest_record.py"


def now_utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message: str) -> None:
    print(f"[{now_utc_text()}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Executa testes periodicos de velocidade e registra no historico "
            "local."
        )
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=30.0,
        help="Intervalo entre testes em minutos (padrao: 30).",
    )
    parser.add_argument(
        "--initial-delay-seconds",
        type=float,
        default=0.0,
        help="Aguarda antes do primeiro teste (padrao: 0).",
    )
    parser.add_argument(
        "--no-immediate",
        action="store_true",
        help="Nao executa o primeiro teste imediatamente.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=0,
        help="Quantidade maxima de execucoes (0 = infinito).",
    )
    args = parser.parse_args()

    if args.interval_minutes <= 0:
        parser.error("--interval-minutes deve ser maior que zero.")
    if args.initial_delay_seconds < 0:
        parser.error("--initial-delay-seconds nao pode ser negativo.")
    if args.max_runs < 0:
        parser.error("--max-runs nao pode ser negativo.")

    return args


def run_record_once() -> int:
    cmd = [sys.executable, str(RECORD_SCRIPT)]
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), check=False)
    return proc.returncode


def wait_or_stop(stop_event: threading.Event, seconds: float) -> bool:
    end_at = time.monotonic() + seconds
    while not stop_event.is_set():
        remaining = end_at - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(1.0, remaining))
    return False


def main() -> int:
    args = parse_args()
    interval_seconds = args.interval_minutes * 60.0
    stop_event = threading.Event()

    def _handle_signal(signum: int, _frame) -> None:
        signal_name = signal.Signals(signum).name
        log(f"Sinal {signal_name} recebido. Encerrando monitor...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log(
        "Monitor iniciado. "
        f"Intervalo: {args.interval_minutes:.2f} minuto(s)."
    )

    first_wait = args.initial_delay_seconds
    if args.no_immediate:
        first_wait += interval_seconds
    if first_wait > 0:
        log(
            "Aguardando "
            f"{first_wait:.0f} segundo(s) antes da primeira execucao..."
        )
        if not wait_or_stop(stop_event, first_wait):
            return 0

    run_count = 0
    while not stop_event.is_set():
        run_count += 1
        log(f"Iniciando teste #{run_count}...")
        code = run_record_once()
        if code == 0:
            log(f"Teste #{run_count} concluido com sucesso.")
        else:
            log(
                f"Teste #{run_count} finalizado com erro (codigo {code}). "
                "Nova tentativa sera feita no proximo ciclo."
            )

        if args.max_runs and run_count >= args.max_runs:
            log(f"Limite de execucoes atingido ({args.max_runs}). Encerrando.")
            break

        if not wait_or_stop(stop_event, interval_seconds):
            break

    log("Monitor finalizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
