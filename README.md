# speed-pro

Projeto inicial para executar o `speedtest.py` com scripts via npm.

## Requisitos

- Node.js e npm
- Python 3

## Scripts

- `npm run start`: executa o speed test
- `npm run speedtest`: alias para executar o speed test
- `npm run record`: executa o speed test e salva no histórico (`data/history.jsonl` e `data/history.csv`)
- `npm run report`: gera relatório com médias, melhor/pior e tendência de 7/30 dias
- `npm run check`: valida sintaxe do script Python

## Histórico e Relatórios

O histórico é salvo localmente em:

- `data/history.jsonl`
- `data/history.csv`

Fluxo recomendado:

1. Rode `npm run record` sempre que quiser registrar uma medição.
2. Rode `npm run report` para analisar desempenho médio e tendência.

## Direitos e Créditos

Este projeto utiliza o script `speedtest.py` e reconhece os direitos da marca e do serviço Speedtest da Ookla.

Site oficial: https://www.speedtest.net/pt
