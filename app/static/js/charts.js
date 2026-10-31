// Renders every <canvas data-chart="id"> from its JSON config.
// Palette: validated categorical order (fixed slots, never cycled), reserved status colors,
// thin marks (2px lines, 4px rounded bar ends), recessive grid, legend only for 2+ series.
(function () {
  "use strict";
  if (!window.Chart) return;

  const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
  const STATUS = { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b", neutral: "#c3c2b7" };
  const INK = { primary: "#0b0b0b", secondary: "#52514e", muted: "#898781", grid: "#e1e0d9", axis: "#c3c2b7" };
  const SURFACE = "#ffffff";

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = INK.secondary;
  Chart.defaults.plugins.tooltip.backgroundColor = "#0b0b0b";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  function colorOf(ds, i) {
    if (ds.status) return STATUS[ds.status] || STATUS.neutral;
    return PALETTE[(ds.series !== undefined ? ds.series : i) % PALETTE.length];
  }

  function build(cfg) {
    const o = cfg.opts || {};
    const type = cfg.type;
    const isLine = type === "line";
    const isDonut = type === "doughnut";
    const datasets = cfg.datasets.map(function (ds, i) {
      const c = colorOf(ds, i);
      const out = { label: ds.label, data: ds.data };
      if (isDonut) {
        out.backgroundColor = ds.colors || (ds.statuses ? ds.statuses.map(function (s) { return STATUS[s]; }) : PALETTE);
        out.borderColor = SURFACE;
        out.borderWidth = 2; // surface gap between segments
        out.hoverOffset = 4;
      } else if (isLine) {
        Object.assign(out, {
          borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6,
          pointBorderColor: SURFACE, pointBorderWidth: 2, tension: 0.25, spanGaps: true, fill: false,
        });
      } else {
        Object.assign(out, {
          backgroundColor: ds.colors || c, borderWidth: 0, borderRadius: 4, borderSkipped: "start",
          maxBarThickness: 28, categoryPercentage: 0.7, barPercentage: 0.85,
        });
      }
      return out;
    });

    const scaleBase = {
      grid: { color: INK.grid, drawTicks: false },
      border: { color: INK.axis },
      ticks: { color: INK.muted, padding: 6 },
    };
    const valueAxis = Object.assign({}, scaleBase, { beginAtZero: true });
    if (o.percent) {
      valueAxis.max = 100;
      valueAxis.ticks = Object.assign({}, scaleBase.ticks, { callback: function (v) { return v + "%"; }, stepSize: 25 });
    }
    if (o.integer) valueAxis.ticks = Object.assign({}, valueAxis.ticks, { precision: 0 });
    const catAxis = Object.assign({}, scaleBase, { grid: { display: false }, ticks: { color: INK.muted, autoSkip: true, maxRotation: 0 } });

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: isLine ? { mode: "index", intersect: false } : { mode: "nearest", intersect: true },
      plugins: {
        legend: { display: isDonut || datasets.length >= 2, position: isDonut ? "bottom" : "top", align: "end" },
        tooltip: {
          callbacks: o.percent ? {
            label: function (ctx) {
              const v = ctx.parsed.y !== undefined && !o.horizontal ? ctx.parsed.y : ctx.parsed.x;
              return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + (v === null ? "no data" : v + "%");
            },
          } : {},
        },
      },
    };
    if (isDonut) {
      options.cutout = "70%";
    } else {
      options.indexAxis = o.horizontal ? "y" : "x";
      options.scales = o.horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis };
      if (o.stacked) { options.scales.x.stacked = true; options.scales.y.stacked = true; }
    }
    return { type: type, data: { labels: cfg.labels, datasets: datasets }, options: options };
  }

  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    const cfg = window.SP && window.SP.data(canvas.getAttribute("data-chart"));
    if (!cfg) return;
    try { new Chart(canvas, build(cfg)); } catch (e) { /* leave the table view as fallback */ }
  });
})();
