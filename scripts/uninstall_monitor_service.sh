#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="speed-pro-monitor.service"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl --user daemon-reload || true
fi

rm -f "$SERVICE_PATH"

echo "Servico removido: $SERVICE_NAME"
echo "A pasta do projeto e os dados de historico foram preservados."
