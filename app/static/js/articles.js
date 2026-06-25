/* Panel A — article momentum scatter + top-articles leaderboard.
   Color encodes momentum: rising = warm, fading = cool, steady = indigo. */
(function () {
  "use strict";
  var D = window.Dash;

  var GROWTH_CAP = 500;
  var CLASSES = {
    rising: "Rising", new: "NEW", steady: "Evergreen", fading: "Fading"
  };

  var chart = D.makeChart("momentum-chart");
  var momentumOverlay = document.getElementById("momentum-overlay");
  var lbOverlay = document.getElementById("leaderboard-overlay");
  var data = null;

  function bubbleSize(change) {
    return Math.min(8 + Math.sqrt(Math.abs(change)) * 0.95, 46);
  }

  // x positions on est. visits when available, else raw hits (uniform factor,
  // so the log-scale shape is identical either way).
  function xOf(hits) { return D.hasViews() ? Math.max(D.estViews(hits), 1) : hits; }

  function renderScatter() {
    if (!data) return;
    var t = D.tokens();
    var useViews = D.hasViews();
    var series = Object.keys(CLASSES).map(function (cls) {
      var pts = data.scatter.filter(function (p) { return p.cls === cls; }).map(function (p) {
        var y = p.growth === null ? GROWTH_CAP : Math.max(-100, Math.min(p.growth, GROWTH_CAP));
        return { value: [xOf(p.cur), y], item: p, symbolSize: bubbleSize(p.change) };
      });
      var color = D.momentumColor(cls);
      return {
        name: CLASSES[cls], type: "scatter", data: pts,
        itemStyle: { color: color, opacity: 0.82,
          shadowBlur: 8, shadowColor: color + "66" },
        emphasis: { scale: 1.4, focus: "series",
          itemStyle: { opacity: 1, borderColor: t.text, borderWidth: 1.5 } }
      };
    });

    chart.setOption({
      backgroundColor: "transparent",
      legend: { top: 0, right: 0, textStyle: { color: t.dim, fontSize: 11 },
        itemWidth: 11, itemHeight: 8, inactiveColor: t.faint },
      grid: { left: 64, right: 24, top: 34, bottom: 46 },
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var it = p.data.item;
          var g = it.growth === null ? "NEW (no prior hits)" : D.fmtGrowth(it.growth);
          return "<strong style='font-family:JetBrains Mono,monospace;font-size:11px'>" + it.path + "</strong>" +
            "<div style='margin-top:4px'>" + D.viewsTip(it.cur) + "</div>" +
            "<div style='margin-top:3px'>growth: <b style='color:" + D.momentumColor(it.cls) + "'>" + g + "</b></div>" +
            "<div>change: " + (it.change > 0 ? "+" : "") + D.fmtNum(it.change) + " hits</div>";
        }
      }),
      xAxis: { type: "log", logBase: 10,
        name: (useViews ? "est. visits (log)" : "est. hits (log)"),
        nameLocation: "middle", nameGap: 30,
        nameTextStyle: { color: t.faint, fontSize: 11 },
        axisLine: D.axisLine(), axisLabel: Object.assign(D.axisLabel(), { formatter: D.fmtNum }),
        splitLine: D.splitLine() },
      yAxis: { type: "value", name: "growth %", max: GROWTH_CAP, min: -100,
        nameTextStyle: { color: t.faint, fontSize: 11 },
        axisLine: D.axisLine(),
        axisLabel: Object.assign(D.axisLabel(), { formatter: function (v) { return v + "%"; } }),
        splitLine: D.splitLine() },
      series: series.concat([{
        type: "line", markLine: { silent: true, symbol: "none",
          lineStyle: { color: t.dim, type: "dashed", opacity: 0.5 },
          label: { show: true, formatter: "flat", color: t.faint, fontSize: 10, position: "insideEndTop" },
          data: [{ yAxis: 0 }] }, data: [] }]),
      animationDuration: D.prefersReduced() ? 0 : 700
    }, true);
  }

  function sparkline(el, dataArr, color) {
    var c = echarts.init(el, null, { renderer: "canvas" });
    c.setOption({
      backgroundColor: "transparent",
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "category", show: false, data: dataArr.map(function (_, i) { return i; }) },
      yAxis: { type: "value", show: false },
      series: [{ type: "line", data: dataArr, symbol: "none", smooth: 0.3, silent: true,
        lineStyle: { width: 1.6, color: color },
        areaStyle: { color: color + "22" } }],
      animation: false
    });
    return c;
  }

  function growthBadge(item) {
    if (item.growth === null && item.cls === "new") return '<span class="growth-badge growth-new">NEW</span>';
    if (item.growth === null) return '<span class="growth-badge growth-flat">—</span>';
    var cls = item.growth >= 25 ? "growth-up" : item.growth <= -25 ? "growth-down" : "growth-flat";
    return '<span class="growth-badge ' + cls + '">' + D.fmtGrowth(item.growth) + "</span>";
  }

  // Headline = estimated visits (actual people); raw hits kept as a small
  // secondary line. Falls back to hits alone when no visits factor is available.
  function hitsCell(item) {
    var v = D.estViews(item.cur);
    if (v === null) return "~" + D.fmtNum(item.cur);
    return "~" + D.fmtNum(v) +
      "<div style='font-size:10px;font-weight:400;opacity:0.6;margin-top:1px'>~" +
      D.fmtNum(item.cur) + " hits</div>";
  }

  function renderLeaderboard() {
    var host = document.getElementById("leaderboard");
    host.innerHTML = "";
    data.leaderboard.forEach(function (item, i) {
      var color = D.momentumColor(item.cls);
      var row = document.createElement("div");
      row.className = "lb-row";
      row.innerHTML =
        '<div class="lb-rank">' + (i + 1) + "</div>" +
        '<div><span class="dot dot-' + item.cls + '" title="' + (CLASSES[item.cls] || "") + '"></span></div>' +
        '<div class="lb-path"><a href="https://' + D.site + item.path +
          '" target="_blank" rel="noopener" title="' + item.path + '">' + item.path + "</a></div>" +
        '<div class="lb-spark"></div>' +
        '<div class="lb-hits" title="estimated visits · raw hits this window">' + hitsCell(item) + "</div>" +
        '<div class="lb-growth">' + growthBadge(item) + "</div>";
      host.appendChild(row);
      sparkline(row.querySelector(".lb-spark"), item.spark, color);
    });
  }

  D.onTheme(renderScatter);

  D.fetchJSON("/api/panel/articles").then(function (d) {
    if (d.source === "none") {
      D.message(momentumOverlay, D.noticeText(d.notice));
      D.message(lbOverlay, D.noticeText(d.notice));
      return;
    }
    D.setBadge(d.source);
    D.setText("min-hits", d.min_hits);
    D.setViewsFactor(d.views_factor);
    D.setText("momentum-x-label", D.hasViews() ? "est. visits" : "est. hits");
    data = d;

    if (!d.scatter.length) {
      D.message(momentumOverlay, "No article reached " + d.min_hits + " est. hits in this window.");
    } else if (d.prior_hours === 0) {
      data = Object.assign({}, d, { scatter: d.scatter.map(function (p) {
        return Object.assign({}, p, { growth: 0, cls: "steady" }); }) });
      renderScatter();
      D.ready(momentumOverlay);
      D.setText("momentum-note", "no stored data for the prior window — growth unavailable, showing volume only");
    } else {
      renderScatter();
      D.ready(momentumOverlay);
      D.setText("momentum-note", d.scatter.length + " articles · prior window " +
        d.prior_hours + "/" + d.current_hours + " h covered");
    }

    if (!d.leaderboard.length) {
      D.message(lbOverlay, "No article traffic stored for this window.");
    } else {
      renderLeaderboard();
      D.ready(lbOverlay);
    }
  }).catch(function (err) {
    D.message(momentumOverlay, "Could not load data: " + err.message);
    D.message(lbOverlay, "Could not load data: " + err.message);
  });
})();
