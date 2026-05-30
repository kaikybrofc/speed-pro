# speed-pro

Projeto inicial para executar o `speedtest.py` com scripts via npm.

## Requisitos

- Node.js e npm
- Python 3

## Scripts

- `npm run start`: executa o speed test
- `npm run speedtest`: alias para executar o speed test
- `npm run record`: executa o speed test e salva no histórico (`data/history.jsonl` e `data/history.csv`)
- `npm run report`: gera relatório analítico avançado (score, percentis, estabilidade, heatmap, SLA, correlação)
- `npm run monitor`: inicia monitor contínuo local (teste automático a cada 30 minutos)
- `npm run monitor:install`: instala e inicia serviço automático (`systemd --user`) com intervalo de 30 minutos
- `npm run monitor:uninstall`: remove serviço automático
- `npm run monitor:status`: mostra status do serviço
- `npm run monitor:logs`: acompanha logs em tempo real
- `npm run check`: valida sintaxe do script Python

## Histórico e Relatórios

O histórico é salvo localmente em:

- `data/history.jsonl`
- `data/history.csv`

Fluxo recomendado:

1. Rode `npm run record` sempre que quiser registrar uma medição.
2. Rode `npm run report` para analisar desempenho médio e tendência.

O relatório inclui:

- score de qualidade da internet (0-100) com ping, jitter, throughput e perda
- percentis p50/p95/p99 de latência, jitter e velocidades
- estabilidade por faixa horária (madrugada/manhã/tarde/noite)
- heatmap semanal de performance por hora
- comparação automática entre plano/provedor/IP
- detecção de hora ideal/ruim para reuniões, jogos e upload
- modo SLA doméstico em histórico, com supressão por carga local alta
- correlação entre uso de CPU/RAM e qualidade da rede

## Monitoramento Automático

Para deixar o projeto executando testes periódicos automaticamente:

1. Instale o serviço: `npm run monitor:install`
2. Verifique status: `npm run monitor:status`
3. Veja logs: `npm run monitor:logs`

Por padrão, o intervalo é de 30 minutos.

Para instalar com outro intervalo (exemplo 10 minutos):

```bash
bash scripts/install_monitor_service.sh 10
```

Para remover o serviço automático:

```bash
npm run monitor:uninstall
```

Se quiser que rode mesmo sem login ativo, habilite linger:

```bash
sudo loginctl enable-linger $USER
```

Modo SLA no monitor contínuo:

```bash
python3 scripts/speedtest_monitor.py \
  --interval-minutes 10 \
  --sla-mode \
  --sla-min-download-mbps 100 \
  --sla-min-upload-mbps 20 \
  --sla-max-ping-ms 80 \
  --sla-max-packet-loss-pct 2 \
  --sla-window-minutes 30
```

Registro enriquecido com perda de pacote e plano:

```bash
python3 scripts/speedtest_record.py --plan "fibra-500" --ping-target 1.1.1.1
```

## Direitos e Créditos

Este projeto utiliza o script `speedtest.py` e reconhece os direitos da marca e do serviço Speedtest da Ookla.

Site oficial: https://www.speedtest.net/pt
