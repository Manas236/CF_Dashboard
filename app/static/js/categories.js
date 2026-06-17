/* Panel B — category treemap (click to drill) + category radar. */
(function () {
  "use strict";
  var D = window.Dash;

  var treemap = D.makeChart("treemap-chart");
  var radar = D.makeChart("radar-chart");
  var tmOverlay = document.getElementById("treemap-overlay");
  var rdOverlay = document.getElementById("radar-overlay");
  var data = null;

  function renderTreemap() {
    if (!data || !data.treemap.length) return;
    var t = D.tokens();
    treemap.setOption({
      backgroundColor: "transparent",
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var share = (p.value / data.total * 100).toFixed(1);
          var head = p.data.path
            ? "<strong>" + p.name + "</strong><br><span style='font-family:JetBrains Mono,monospace;font-size:11px;color:" + t.dim + "'>" + p.data.path + "</span>"
            : "<strong>" + p.name + "</strong>";
          return head + "<br>~" + D.fmtNum(p.value) + " est. requests · " + share + "% of content";
        }
      }),
      series: [{
        type: "treemap", data: data.treemap, leafDepth: 1, roam: false,
        width: "100%", height: "86%", top: 26,
        colorMappingBy: "index", color: t.catPalette,
        breadcrumb: { show: true, top: 0, left: 0, height: 22,
          itemStyle: { color: t.surface2, borderColor: t.border,
            textStyle: { color: t.dim, fontSize: 11 } },
          emphasis: { itemStyle: { color: t.surface3, textStyle: { color: t.text } } } },
        label: { show: true, color: "#fff", fontSize: 12, fontFamily: "Inter",
          formatter: function (p) { return p.name + "  " + (p.value / data.total * 100).toFixed(1) + "%"; } },
        upperLabel: { show: true, height: 24, color: t.text, fontSize: 12, fontFamily: "Space Grotesk" },
        itemStyle: { borderColor: t.surface, borderWidth: 2, gapWidth: 2 },
        emphasis: { itemStyle: { borderColor: t.text } },
        levels: [
          { itemStyle: { borderWidth: 0, gapWidth: 3 } },
          { colorSaturation: [0.4, 0.7],
            itemStyle: { borderColorSaturation: 0.6, gapWidth: 1, borderWidth: 1 } }
        ],
        animationDuration: D.prefersReduced() ? 0 : 700
      }]
    }, true);
  }

  function renderRadar() {
    if (!data || !data.radar || data.radar.series.length < 2) return;
    var t = D.tokens();
    var r = data.radar;
    radar.setOption({
      backgroundColor: "transparent",
      legend: { top: 0, right: 0, orient: "vertical",
        textStyle: { color: t.dim, fontSize: 11 }, itemWidth: 11, itemHeight: 8, inactiveColor: t.faint },
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var raw = p.data.raw;
          return "<strong>" + p.name + "</strong><br>" +
            "view share: " + raw["View share"] + "%<br>" +
            "growth: " + (r.growth_available ? D.fmtGrowth(raw["Growth"]) : "n/a") + "<br>" +
            "active articles: " + D.fmtNum(raw["Active articles"]) + "<br>" +
            "error rate: " + raw["Error rate"] + "%<br>" +
            "bandwidth share: " + raw["Bandwidth share"] + "%";
        }
      }),
      radar: { indicator: r.axes.map(function (a) { return { name: a, max: 100 }; }),
        radius: "66%", center: ["48%", "56%"],
        axisName: { color: t.dim, fontSize: 11 },
        splitArea: { areaStyle: { color: ["transparent", t.grid] } },
        axisLine: { lineStyle: { color: t.border } },
        splitLine: { lineStyle: { color: t.grid } } },
      series: [{ type: "radar",
        data: r.series.map(function (s, i) {
          var color = t.catPalette[i % t.catPalette.length];
          return { name: s.name, value: s.norm, raw: s.raw,
            itemStyle: { color: color }, lineStyle: { color: color, width: 2 },
            areaStyle: { color: color, opacity: 0.1 }, symbolSize: 4 };
        }),
        emphasis: { lineStyle: { width: 3 }, areaStyle: { opacity: 0.22 } },
        animationDuration: D.prefersReduced() ? 0 : 700 }]
    }, true);
  }

  D.onTheme(function () { renderTreemap(); renderRadar(); });

  D.fetchJSON("/api/panel/categories").then(function (d) {
    if (d.source === "none") {
      D.message(tmOverlay, D.noticeText(d.notice));
      D.message(rdOverlay, D.noticeText(d.notice));
      return;
    }
    D.setBadge(d.source);
    if (d.notice === "no_articles" || !d.treemap.length) {
      D.message(tmOverlay, "No article traffic stored for this window.");
      D.message(rdOverlay, "No article traffic stored for this window.");
      return;
    }
    data = d;
    renderTreemap();
    D.ready(tmOverlay);
    D.setText("treemap-note", d.treemap.length + " categories · ~" + D.fmtNum(d.total) +
      " est. content requests · click a tile to drill in");

    if (d.radar && d.radar.series.length >= 2) {
      renderRadar();
      D.ready(rdOverlay);
      if (!d.radar.growth_available)
        D.setText("radar-note", "growth axis flat — no stored data for the prior window yet");
    } else {
      D.message(rdOverlay, "Need at least two active categories for a profile comparison.");
    }
  }).catch(function (err) {
    D.message(tmOverlay, "Could not load data: " + err.message);
    D.message(rdOverlay, "Could not load data: " + err.message);
  });
})();
