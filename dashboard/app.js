const REFRESH_MS = 5000;

const els = {
  cardsGrid: document.getElementById("cardsGrid"),
  lastUpdate: document.getElementById("lastUpdate"),
  sampleCount: document.getElementById("sampleCount"),
  percentilesTable: document.getElementById("percentilesTable"),
  stabilityList: document.getElementById("stabilityList"),
  heatmapWrapper: document.getElementById("heatmapWrapper"),
  providerTable: document.getElementById("providerTable"),
  slaChips: document.getElementById("slaChips"),
  corrChips: document.getElementById("corrChips"),
  timeQuality: document.getElementById("timeQuality"),
  throughputChart: document.getElementById("throughputChart"),
  qualityChart: document.getElementById("qualityChart"),
};

function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatTs(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString("pt-BR");
}

function card(label, value, suffix = "") {
  return `
    <article class="card">
      <div class="label">${label}</div>
      <div class="value">${value}${suffix}</div>
    </article>
  `;
}

function renderCards(payload) {
  const latest = payload.cards.latest || {};
  const averages = payload.cards.averages || {};
  const html = [
    card("Último Score", formatNumber(latest.quality_score, 2)),
    card("Último Download", formatNumber(latest.download_mbps, 2), " Mbps"),
    card("Último Upload", formatNumber(latest.upload_mbps, 2), " Mbps"),
    card("Último Ping", formatNumber(latest.ping_ms, 2), " ms"),
    card("Perda de Pacote", formatNumber(latest.packet_loss_pct_avg, 2), "%"),
    card("Média Download", formatNumber(averages.download_mbps, 2), " Mbps"),
    card("Média Upload", formatNumber(averages.upload_mbps, 2), " Mbps"),
    card("Média Ping", formatNumber(averages.ping_ms, 2), " ms"),
    card("Jitter Médio", formatNumber(averages.jitter_ms_avg, 2), " ms"),
    card("Média Score", formatNumber(averages.quality_score, 2)),
    card("CPU Local", formatNumber(latest.system_cpu_percent, 2), "%"),
    card("RAM Local", formatNumber(latest.system_ram_percent, 2), "%"),
  ].join("");
  els.cardsGrid.innerHTML = html;
}

function renderPercentiles(percentiles) {
  const rows = [
    ["Download (Mbps)", percentiles.download_mbps],
    ["Upload (Mbps)", percentiles.upload_mbps],
    ["Ping (ms)", percentiles.ping_ms],
    ["Jitter (ms)", percentiles.jitter_ms_avg],
    ["Score", percentiles.quality_score],
  ]
    .map(([name, stats]) => {
      if (!stats) {
        return `<tr><td>${name}</td><td>-</td><td>-</td><td>-</td></tr>`;
      }
      return `
      <tr>
        <td>${name}</td>
        <td>${formatNumber(stats.p50, 2)}</td>
        <td>${formatNumber(stats.p95, 2)}</td>
        <td>${formatNumber(stats.p99, 2)}</td>
      </tr>
    `;
    })
    .join("");

  els.percentilesTable.innerHTML = `
    <table>
      <thead>
        <tr><th>Métrica</th><th>p50</th><th>p95</th><th>p99</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderStability(items = []) {
  els.stabilityList.innerHTML = items
    .map((item) => {
      if (item.stability === null) {
        return `<div class="stability-row"><strong>${item.period}</strong><span>Sem dados</span><span>-</span></div>`;
      }
      const pct = Math.max(0, Math.min(100, item.stability));
      return `
        <div class="stability-row">
          <strong>${item.period}</strong>
          <div class="bar"><span style="width:${pct}%;"></span></div>
          <span>${formatNumber(pct, 1)}</span>
        </div>
      `;
    })
    .join("");
}

function heatColor(score) {
  if (score === null || score === undefined) return "rgba(255,255,255,0.04)";
  const clamped = Math.max(0, Math.min(100, Number(score)));
  const hue = clamped * 1.2;
  return `hsl(${hue} 78% 42%)`;
}

function renderHeatmap(cells = []) {
  const byDayHour = new Map();
  cells.forEach((cell) => byDayHour.set(`${cell.day}:${cell.hour}`, cell));

  const dayNames = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"];
  let header = "<tr><th>Dia/Hora</th>";
  for (let h = 0; h < 24; h += 1) {
    header += `<th>${h}</th>`;
  }
  header += "</tr>";

  let body = "";
  for (let d = 0; d < 7; d += 1) {
    body += `<tr><th>${dayNames[d]}</th>`;
    for (let h = 0; h < 24; h += 1) {
      const cell = byDayHour.get(`${d}:${h}`);
      const score = cell?.avg_score;
      body += `<td title="score: ${formatNumber(score, 2)}"
        style="background:${heatColor(score)}">${score == null ? "" : "&nbsp;"}</td>`;
    }
    body += "</tr>";
  }

  els.heatmapWrapper.innerHTML = `
    <div class="heatmap">
      <table>
        <thead>${header}</thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function renderProviders(rows = []) {
  const body = rows
    .map(
      (row) => `
      <tr>
        <td>${row.key}</td>
        <td>${row.count}</td>
        <td>${formatNumber(row.avg_score, 2)}</td>
        <td>${formatNumber(row.avg_download_mbps, 2)}</td>
        <td>${formatNumber(row.avg_upload_mbps, 2)}</td>
        <td>${formatNumber(row.avg_ping_ms, 2)}</td>
      </tr>
    `
    )
    .join("");

  els.providerTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Plano | ISP | IP</th>
          <th>N</th>
          <th>Score</th>
          <th>Down</th>
          <th>Up</th>
          <th>Ping</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function renderSla(sla) {
  const ratio = Number(sla?.below_sla_ratio || 0);
  const levelClass = ratio > 20 ? "danger" : "ok";
  const reasonEntries = Object.entries(sla?.below_sla_reasons || {});
  const reasonText =
    reasonEntries.length > 0
      ? reasonEntries.map(([k, v]) => `${k}: ${v}`).join(" | ")
      : "sem ocorrências";

  els.slaChips.innerHTML = `
    <span class="chip ${levelClass}">Abaixo SLA: ${formatNumber(
    sla?.below_sla_count || 0,
    0
  )} amostras</span>
    <span class="chip ${levelClass}">Taxa: ${formatNumber(ratio, 2)}%</span>
    <span class="chip">Causas: ${reasonText}</span>
  `;
}

function renderCorrelation(correlation = {}) {
  const entries = [
    ["CPU x Download", correlation.cpu_download],
    ["CPU x Upload", correlation.cpu_upload],
    ["CPU x Ping", correlation.cpu_ping],
    ["CPU x Score", correlation.cpu_score],
    ["RAM x Download", correlation.ram_download],
    ["RAM x Upload", correlation.ram_upload],
    ["RAM x Ping", correlation.ram_ping],
    ["RAM x Score", correlation.ram_score],
  ];

  els.corrChips.innerHTML = entries
    .map(([label, value]) => {
      const num = value == null ? null : Number(value);
      const cls = num == null ? "" : Math.abs(num) > 0.6 ? "danger" : "ok";
      const shown = num == null ? "n/a" : formatNumber(num, 3);
      return `<span class="chip ${cls}">${label}: ${shown}</span>`;
    })
    .join("");
}

function renderTimeQuality(info = {}) {
  const best = info.best_hour;
  const worst = info.worst_hour;
  els.timeQuality.innerHTML = `
    <span class="chip ok">Hora ideal: ${
      best ? `${String(best.hour).padStart(2, "0")}h (${formatNumber(best.score, 2)})` : "-"
    }</span>
    <span class="chip danger">Hora ruim: ${
      worst
        ? `${String(worst.hour).padStart(2, "0")}h (${formatNumber(worst.score, 2)})`
        : "-"
    }</span>
  `;
}

function drawChart(canvas, labels, datasets) {
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);

  const padding = { top: 20, right: 16, bottom: 28, left: 42 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const allValues = datasets.flatMap((d) => d.values).filter((v) => v != null);
  const minVal = Math.min(...allValues, 0);
  const maxVal = Math.max(...allValues, 1);
  const span = maxVal - minVal || 1;

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(232, 244, 251, 0.75)";
  ctx.font = "12px Space Grotesk, sans-serif";
  ctx.fillText(formatNumber(maxVal, 1), 6, padding.top + 4);
  ctx.fillText(formatNumber(minVal, 1), 6, padding.top + chartH + 4);

  const xStep = labels.length > 1 ? chartW / (labels.length - 1) : chartW;
  datasets.forEach((dataset) => {
    ctx.beginPath();
    dataset.values.forEach((val, idx) => {
      if (val == null) return;
      const x = padding.left + idx * xStep;
      const y = padding.top + chartH - ((val - minVal) / span) * chartH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = dataset.color;
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  const legendY = height - 8;
  let legendX = padding.left;
  datasets.forEach((dataset) => {
    ctx.fillStyle = dataset.color;
    ctx.fillRect(legendX, legendY - 8, 10, 10);
    ctx.fillStyle = "rgba(232, 244, 251, 0.8)";
    ctx.fillText(dataset.label, legendX + 14, legendY);
    legendX += ctx.measureText(dataset.label).width + 36;
  });
}

function renderCharts(series = []) {
  const labels = series.map((point) => formatTs(point.timestamp));
  drawChart(els.throughputChart, labels, [
    {
      label: "Download",
      color: "#14b8a6",
      values: series.map((p) => Number(p.download_mbps)),
    },
    {
      label: "Upload",
      color: "#f59e0b",
      values: series.map((p) => Number(p.upload_mbps)),
    },
  ]);

  drawChart(els.qualityChart, labels, [
    {
      label: "Ping",
      color: "#ef4444",
      values: series.map((p) => Number(p.ping_ms)),
    },
    {
      label: "Score",
      color: "#22c55e",
      values: series.map((p) => Number(p.quality_score)),
    },
  ]);
}

async function refresh() {
  try {
    const response = await fetch("/api/summary?limit=360", { cache: "no-store" });
    const payload = await response.json();

    els.lastUpdate.textContent = `Atualizado: ${formatTs(payload.meta.generated_at)}`;
    els.sampleCount.textContent = `${payload.meta.total_records} amostras coletadas`;
    renderCards(payload);
    renderPercentiles(payload.percentiles || {});
    renderStability(payload.stability_periods || []);
    renderHeatmap(payload.weekly_heatmap || []);
    renderProviders(payload.providers || []);
    renderSla(payload.sla || {});
    renderCorrelation(payload.correlation || {});
    renderTimeQuality(payload.time_quality || {});
    renderCharts(payload.series || []);
  } catch (error) {
    els.lastUpdate.textContent = `Falha na atualização: ${error}`;
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
