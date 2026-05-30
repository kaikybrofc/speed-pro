#!/usr/bin/env bash
set -euo pipefail

INTERVAL_MINUTES="${1:-30}"
SERVICE_NAME="speed-pro-monitor.service"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"
LINK_PATH="$HOME/.local/share/speed-pro"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(command -v python3)"

if ! [[ "$INTERVAL_MINUTES" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Erro: intervalo invalido '$INTERVAL_MINUTES'." >&2
  echo "Use um numero positivo. Exemplo: 15 ou 30.5" >&2
  exit 1
fi

if ! awk "BEGIN {exit !($INTERVAL_MINUTES > 0)}"; then
  echo "Erro: intervalo deve ser maior que zero." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "Erro: systemctl nao encontrado no sistema." >&2
  exit 1
fi

mkdir -p "$SYSTEMD_USER_DIR"
mkdir -p "$(dirname "$LINK_PATH")"
ln -sfn "$PROJECT_DIR" "$LINK_PATH"

SERVICE_WAS_ACTIVE="false"
if systemctl --user is-active --quiet "$SERVICE_NAME"; then
  SERVICE_WAS_ACTIVE="true"
fi

cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=Speed Pro Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$LINK_PATH
ExecStart=$PYTHON_BIN scripts/speedtest_monitor.py --interval-minutes $INTERVAL_MINUTES
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME" >/dev/null

if [ "$SERVICE_WAS_ACTIVE" = "true" ]; then
  systemctl --user restart "$SERVICE_NAME"
  SERVICE_ACTION="reiniciado"
else
  systemctl --user start "$SERVICE_NAME"
  SERVICE_ACTION="iniciado"
fi

echo "Servico instalado e $SERVICE_ACTION: $SERVICE_NAME"
echo "Intervalo configurado: $INTERVAL_MINUTES minuto(s)"
echo "Status: systemctl --user status $SERVICE_NAME"
echo "Logs:   journalctl --user -u $SERVICE_NAME -f"
echo ""
echo "Se quiser iniciar no boot sem depender de login, rode:"
echo "sudo loginctl enable-linger $USER"
