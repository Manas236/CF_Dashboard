/* Panel D — audience sunburst (click to zoom) + AI-crawler / est.-humans timeline. */
(function () {
  "use strict";
  var D = window.Dash;

  var sunburst = D.makeChart("sunburst-chart");
  var timeline = D.makeChart("timeline-chart");
  var sbOverlay = document.getElementById("sunburst-overlay");
  var tlOverlay = document.getElementById("timeline-overlay");
  var data = null;
  var mode = "all";

  function segColor(name) {
    var t = D.tokens();
    var map = {
      "Human (est.)": t.steady, "Bots": t.amber,
      "Search engines": t.positive, "AI crawlers": t.live, "Other bots": t.dim
    };
    return map[name];
  }

  function recolor(nodes) {
    nodes.forEach(function (n) {
      var c = segColor(n.name);
      if (c) n.itemStyle = { color: c };
      if (n.children) recolor(n.children);
    });
    return nodes;
  }

  function renderStats() {
    var tt = data.totals;
    if (mode === "all") {
      D.setText("stat-a-label", "Total requests");
      D.countUp(document.getElementById("stat-a"), tt.requests, { fmt: function (v) { return "~" + D.fmtNum(v); } });
      D.setText("stat-a-sub", "eyeball traffic, est.");
      D.setText("stat-b-label", "Est. humans");
      D.countUp(document.getElementById("stat-b"), tt.human, { fmt: function (v) { return "~" + D.fmtNum(v); } });
      D.setText("stat-b-sub", D.fmtPct(tt.requests ? tt.human / tt.requests : null) + " of total");
    } else {
      D.setText("stat-a-label", "Est. humans");
      D.countUp(document.getElementById("stat-a"), tt.human, { fmt: function (v) { return "~" + D.fmtNum(v); } });
      D.setText("stat-a-sub", "raw minus UA-identified bots");
      D.setText("stat-b-label", "Removed as bots");
      D.countUp(document.getElementById("stat-b"), tt.bot, { fmt: function (v) { return "~" + D.fmtNum(v); } });
      D.setText("stat-b-sub", D.fmtPct(tt.requests ? tt.bot / tt.requests : null) + " of total");
    }
    D.countUp(document.getElementById("stat-search"), tt.search, { fmt: function (v) { return "~" + D.fmtNum(v); } });
    D.setText("stat-search-sub", D.fmtPct(tt.requests ? tt.search / tt.requests : null) + " of total");
    D.countUp(document.getElementById("stat-ai"), tt.ai, { fmt: function (v) { return "~" + D.fmtNum(v); } });
    D.setText("stat-ai-sub", D.fmtPct(tt.requests ? tt.ai / tt.requests : null) + " of total");
  }

  function renderSunburst() {
    if (!data || !data.totals.requests) return;
    var t = D.tokens();
    sunburst.setOption({
      backgroundColor: "transparent",
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var share = data.totals.requests ? " · " + D.fmtPct(p.value / data.totals.requests) + " of total" : "";
          return "<strong>" + p.name + "</strong><br>~" + D.fmtNum(p.value) + " est. requests" + share;
        }
      }),
      series: [{
        type: "sunburst", data: recolor(JSON.parse(JSON.stringify(data.sunburst))),
        radius: ["16%", "92%"], sort: "desc", nodeClick: "rootToNode",
        emphasis: { focus: "ancestor" },
        itemStyle: { borderColor: t.surface, borderWidth: 2 },
        label: { color: "#fff", fontSize: 11, fontFamily: "Inter", minAngle: 8,
          formatter: function (p) { return p.name.length > 16 ? p.name.slice(0, 15) + "…" : p.name; } },
        levels: [ {},
          { r0: "16%", r: "50%", label: { rotate: 0, fontSize: 12 } },
          { r0: "50%", r: "72%" },
          { r0: "72%", r: "92%", label: { rotate: "tangential", fontSize: 10 } } ],
        animationDuration: D.prefersReduced() ? 0 : 800
      }]
    }, true);
  }

  function renderTimeline() {
    if (!data) return;
    var t = D.tokens();
    var cols = data.timeline.cols;
    var opt = {
      backgroundColor: "transparent",
      grid: { left: 56, right: 18, top: 36, bottom: 36 },
      tooltip: Object.assign(D.tooltipBase(), { trigger: "axis",
        axisPointer: { type: "cross", label: { show: false }, lineStyle: { color: t.dim, type: "dashed" } },
        valueFormatter: function (v) { return v == null ? "n/a" : "~" + D.fmtNum(v) + " est."; } }),
      xAxis: { type: "time", axisLine: D.axisLine(), axisLabel: D.axisLabel(), splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: Object.assign(D.axisLabel(), { formatter: D.fmtNum }), splitLine: D.splitLine() }
    };

    if (mode === "all") {
      opt.legend = { top: 0, textStyle: { color: t.dim, fontSize: 11 }, itemWidth: 11, itemHeight: 8, inactiveColor: t.faint };
      opt.series = data.timeline.ai_series.map(function (s, i) {
        var color = t.catPalette[i % t.catPalette.length];
        return { name: s.name, type: "line", stack: "ai", symbol: "none",
          data: s.data.map(function (v, j) { return [cols[j], v]; }),
          lineStyle: { width: 1, color: color }, itemStyle: { color: color },
          areaStyle: { opacity: 0.4 } };
      });
      D.setText("timeline-title", "AI crawler traffic over time");
      document.getElementById("timeline-foot").textContent =
        "Stacked est. requests per hour from UA-identified AI crawlers — the “who's scraping us, and is it growing” signal · bot list configurable in app/bots.py";
    } else {
      opt.series = [{ name: "Est. humans", type: "line", symbol: "none", connectNulls: false,
        data: data.timeline.human.map(function (v, j) { return [cols[j], v]; }),
        lineStyle: { width: 2.5, color: t.steady, shadowColor: "rgba(108,92,231,0.4)", shadowBlur: 10 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "rgba(108,92,231,0.32)" }, { offset: 1, color: "rgba(108,92,231,0.02)" }]) } }];
      D.setText("timeline-title", "Estimated human traffic over time");
      document.getElementById("timeline-foot").textContent =
        "Est. requests per hour minus UA-identified bots · gaps = hours not collected yet";
    }
    timeline.setOption(opt, true);

    var hasAi = data.timeline.ai_series.length > 0;
    if (mode === "all" && !hasAi) D.message(tlOverlay, "No UA-identified AI crawler traffic stored in this window.");
    else D.ready(tlOverlay);
  }

  document.querySelectorAll("#audience-mode button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      mode = btn.dataset.mode;
      document.querySelectorAll("#audience-mode button").forEach(function (b) {
        b.classList.toggle("active", b === btn); });
      if (data) { renderStats(); renderTimeline(); }
    });
  });

  D.onTheme(function () { renderSunburst(); renderTimeline(); });

  D.fetchJSON("/api/panel/audience").then(function (d) {
    if (d.source === "none") {
      D.message(sbOverlay, D.noticeText(d.notice));
      D.message(tlOverlay, D.noticeText(d.notice));
      return;
    }
    data = d;
    D.setBadge(d.source);
    D.setText("audience-note", d.current_hours + " h of stored data in window");
    renderStats();
    if (!d.totals.requests) {
      D.message(sbOverlay, "No traffic stored for this window.");
      D.message(tlOverlay, "No traffic stored for this window.");
      return;
    }
    renderSunburst();
    D.ready(sbOverlay);
    renderTimeline();
  }).catch(function (err) {
    D.message(sbOverlay, "Could not load data: " + err.message);
    D.message(tlOverlay, "Could not load data: " + err.message);
  });
})();
