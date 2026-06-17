/* Overview — KPI tiles (count-up) + "Traffic over time" area chart. */
(function () {
  "use strict";
  var D = window.Dash;

  var chart = D.makeChart("traffic-chart");
  var overlay = document.getElementById("chart-overlay");
  var seriesData = null;

  function loadKpis() {
    return D.fetchJSON("/api/kpis").then(function (d) {
      if (d.source === "none") return d;
      D.countUp(document.getElementById("kpi-requests"), d.requests, { fmt: function (v) { return "~" + D.fmtNum(v); } });
      D.countUp(document.getElementById("kpi-bytes"), d.bytes, { fmt: function (v) { return "~" + D.fmtBytes(v); } });
      D.countUp(document.getElementById("kpi-errors"), d.error_rate, { fmt: function (v) { return D.fmtPct(v); } });
      D.countUp(document.getElementById("kpi-cache"), d.cache_hit_ratio, { fmt: function (v) { return D.fmtPct(v); } });
      D.setText("kpi-errors-sub", "4xx ~" + D.fmtNum(d.errors_4xx) + " · 5xx ~" + D.fmtNum(d.errors_5xx));
      if (d.source === "mysql" && d.hours_covered < d.hours_expected) {
        D.setText("kpi-requests-sub", "estimated · " + d.hours_covered + "/" + d.hours_expected + " hours collected");
      }
      D.setBadge(d.source);
      D.setUpdated(d.last_collected
        ? "collected " + new Date(d.last_collected).toLocaleTimeString()
        : "as of " + new Date().toLocaleTimeString());
      return d;
    });
  }

  function renderChart() {
    if (!seriesData) return;
    var t = D.tokens();
    var points = seriesData.map(function (p) { return { value: [p.ts, p.requests], bytes: p.bytes }; });
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 56, right: 18, top: 24, bottom: 36 },
      tooltip: Object.assign(D.tooltipBase(), {
        trigger: "axis",
        axisPointer: { type: "cross", label: { show: false },
          lineStyle: { color: t.dim, type: "dashed" },
          crossStyle: { color: t.dim } },
        formatter: function (params) {
          var p = params[0];
          if (!p) return "";
          var when = new Date(p.value[0]).toLocaleString();
          var reqs = p.value[1] === null ? "not collected" : "~" + D.fmtNum(p.value[1]) + " requests (est.)";
          var bw = p.data.bytes == null ? "" : "<br>~" + D.fmtBytes(p.data.bytes) + " bandwidth (est.)";
          return "<div style='font-size:11px;color:" + t.dim + "'>" + when + "</div>" +
            "<strong>" + reqs + "</strong>" + bw;
        }
      }),
      xAxis: { type: "time", axisLine: D.axisLine(), axisLabel: D.axisLabel(),
        axisPointer: { lineStyle: { color: t.dim } }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: Object.assign(D.axisLabel(), { formatter: D.fmtNum }),
        splitLine: D.splitLine() },
      series: [{
        name: "Requests", type: "line", smooth: 0.28, symbol: "none", connectNulls: false,
        data: points,
        sampling: "lttb",
        lineStyle: {
          width: 2.5,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: t.fading }, { offset: 0.5, color: t.rising }, { offset: 1, color: t.live }
          ]),
          shadowColor: "rgba(255,84,54,0.35)", shadowBlur: 12, shadowOffsetY: 4
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(255,122,69,0.34)" },
            { offset: 1, color: "rgba(255,122,69,0.01)" }
          ])
        },
        animationDuration: D.prefersReduced() ? 0 : 1000
      }]
    }, true);
  }

  function loadSeries() {
    return D.fetchJSON("/api/timeseries").then(function (d) {
      var hasData = d.series.some(function (p) { return p.requests !== null; });
      if (!hasData) {
        D.message(overlay, D.noticeText(d.notice) || "No traffic data for this range.");
        return;
      }
      seriesData = d.series;
      D.ready(overlay);
      renderChart();
      var note = D.sourceLabel(d.source);
      if (d.notice === "no_history") note += " · collector not populated yet";
      D.setText("chart-note", note);
    });
  }

  D.onTheme(renderChart);

  function refresh() {
    Promise.all([loadKpis(), loadSeries()]).catch(function (err) {
      D.message(overlay, "Could not load data: " + err.message);
    });
  }
  refresh();
  setInterval(refresh, 5 * 60 * 1000);
})();
