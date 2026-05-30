#!/usr/bin/env python3
"""Run speed tests continuously at a fixed interval."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import speedtest_record  # pylint: disable=wrong-import-position
from scripts.quality_metrics import to_float  # pylint: disable=wrong-import-position


def now_utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message: str) -> None:
    print(f"[{now_utc_text()}] {message}", flush=True)


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    parser.add_argument(
        "--plan",
        default="",
        help="Nome de plano/perfil para comparacao no historico.",
    )
    parser.add_argument(
        "--ping-target",
        default="1.1.1.1",
        help="Host alvo para ping pre/pós teste (padrao: 1.1.1.1).",
    )
    parser.add_argument(
        "--ping-count",
        type=int,
        default=8,
        help="Quantidade de pacotes no ping pre/pós teste.",
    )
    parser.add_argument(
        "--ping-timeout",
        type=int,
        default=2,
        help="Timeout por pacote ping em segundos.",
    )
    parser.add_argument(
        "--sla-mode",
        action="store_true",
        help="Ativa monitoramento SLA com alertas automaticos.",
    )
    parser.add_argument(
        "--sla-min-download-mbps",
        type=float,
        default=100.0,
        help="Minimo de download para SLA.",
    )
    parser.add_argument(
        "--sla-min-upload-mbps",
        type=float,
        default=20.0,
        help="Minimo de upload para SLA.",
    )
    parser.add_argument(
        "--sla-max-ping-ms",
        type=float,
        default=80.0,
        help="Maximo de ping para SLA.",
    )
    parser.add_argument(
        "--sla-max-packet-loss-pct",
        type=float,
        default=2.0,
        help="Maximo de perda de pacote para SLA.",
    )
    parser.add_argument(
        "--sla-window-minutes",
        type=float,
        default=30.0,
        help="Janela minima em minutos para disparar alerta SLA.",
    )
    parser.add_argument(
        "--sla-ignore-high-cpu-percent",
        type=float,
        default=85.0,
        help="Ignora evento SLA ruim se CPU estiver acima deste valor.",
    )
    parser.add_argument(
        "--sla-ignore-high-ram-percent",
        type=float,
        default=90.0,
        help="Ignora evento SLA ruim se RAM estiver acima deste valor.",
    )
    args = parser.parse_args()

    if args.interval_minutes <= 0:
        parser.error("--interval-minutes deve ser maior que zero.")
    if args.initial_delay_seconds < 0:
        parser.error("--initial-delay-seconds nao pode ser negativo.")
    if args.max_runs < 0:
        parser.error("--max-runs nao pode ser negativo.")
    if args.ping_count <= 0:
        parser.error("--ping-count deve ser maior que zero.")
    if args.ping_timeout <= 0:
        parser.error("--ping-timeout deve ser maior que zero.")
    if args.sla_window_minutes <= 0:
        parser.error("--sla-window-minutes deve ser maior que zero.")

    return args


def run_record_once(args: argparse.Namespace) -> Tuple[int, Optional[Dict[str, Any]]]:
    try:
        record = speedtest_record.collect_record(
            plan_name=args.plan,
            ping_target=args.ping_target,
            ping_count=args.ping_count,
            ping_timeout=args.ping_timeout,
        )
        speedtest_record.store_record(record)
        speedtest_record.print_record_summary(record)
        return 0, record
    except Exception as exc:  # pylint: disable=broad-except
        print("Falha ao registrar o speed test.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1, None


def wait_or_stop(stop_event: threading.Event, seconds: float) -> bool:
    end_at = time.monotonic() + seconds
    while not stop_event.is_set():
        remaining = end_at - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(1.0, remaining))
    return False


def evaluate_sla_bad(
    record: Dict[str, Any], args: argparse.Namespace
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if to_float(record.get("download_mbps")) < args.sla_min_download_mbps:
        reasons.append("download baixo")
    if to_float(record.get("upload_mbps")) < args.sla_min_upload_mbps:
        reasons.append("upload baixo")
    if to_float(record.get("ping_ms")) > args.sla_max_ping_ms:
        reasons.append("ping alto")
    if to_float(record.get("packet_loss_pct_avg")) > args.sla_max_packet_loss_pct:
        reasons.append("perda de pacote alta")
    return bool(reasons), reasons


def is_local_load_high(record: Dict[str, Any], args: argparse.Namespace) -> bool:
    cpu = record.get("system_cpu_percent")
    ram = record.get("system_ram_percent")
    cpu_high = cpu is not None and to_float(cpu) >= args.sla_ignore_high_cpu_percent
    ram_high = ram is not None and to_float(ram) >= args.sla_ignore_high_ram_percent
    return cpu_high or ram_high


def run_sla_logic(
    *,
    record: Dict[str, Any],
    args: argparse.Namespace,
    state: Dict[str, Any],
) -> None:
    bad, reasons = evaluate_sla_bad(record, args)
    high_load = is_local_load_high(record, args)
    timestamp = parse_iso_datetime(str(record.get("timestamp", now_utc_text())))

    if not bad:
        if state["bad_started_at"] is not None:
            duration = (
                timestamp - state["bad_started_at"]
            ).total_seconds() / 60.0
            log(
                "SLA recuperado. "
                f"Duracao do periodo ruim: {duration:.1f} min."
            )
        state["bad_started_at"] = None
        state["alerted"] = False
        return

    if high_load:
        log(
            "SLA degradado detectado, mas ignorado por alta carga local "
            f"(CPU={record.get('system_cpu_percent')}% "
            f"RAM={record.get('system_ram_percent')}%)."
        )
        return

    if state["bad_started_at"] is None:
        state["bad_started_at"] = timestamp
        state["alerted"] = False

    elapsed = (timestamp - state["bad_started_at"]).total_seconds() / 60.0
    log(
        "SLA degradado: "
        f"{', '.join(reasons)}. "
        f"Tempo acumulado: {elapsed:.1f} min."
    )

    if elapsed >= args.sla_window_minutes and not state["alerted"]:
        log(
            "ALERTA SLA: "
            f"conexao abaixo do minimo por {elapsed:.1f} min "
            f"(janela configurada: {args.sla_window_minutes:.1f} min)."
        )
        state["alerted"] = True


def main() -> int:
    args = parse_args()
    interval_seconds = args.interval_minutes * 60.0
    stop_event = threading.Event()
    sla_state: Dict[str, Any] = {
        "bad_started_at": None,
        "alerted": False,
    }

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
    if args.sla_mode:
        log(
            "SLA mode ativo: "
            f"min-down={args.sla_min_download_mbps}Mbps "
            f"min-up={args.sla_min_upload_mbps}Mbps "
            f"max-ping={args.sla_max_ping_ms}ms "
            f"max-loss={args.sla_max_packet_loss_pct}% "
            f"window={args.sla_window_minutes}min."
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
        code, record = run_record_once(args)
        if code == 0:
            log(f"Teste #{run_count} concluido com sucesso.")
            if args.sla_mode and record is not None:
                run_sla_logic(record=record, args=args, state=sla_state)
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
