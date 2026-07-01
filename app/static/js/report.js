/* Report — board-meeting summary: KPI strip with WoW deltas, day-by-day
   table, "story of the week", visits-per-day bars, audience + sections. */
(function () {
  "use strict";
  var D = window.Dash;

  var visits = D.makeChart("visits-chart");
  var sunburst = D.makeChart("report-sunburst");
  var visitsOverlay = document.getElementById("visits-overlay");
  var storyOverlay = document.getElementById("story-overlay");
  var dailyOverlay = document.getElementById("daily-overlay");
  var audienceOverlay = document.getElementById("audience-overlay");
  var categoriesOverlay = document.getElementById("categories-overlay");
  var data = null;
  var printing = false, prevTheme = null;

  /* ---- formatting helpers ---------------------------------------------- */
  function dayLabel(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric", timeZone: "UTC"
    });
  }
  function siteUrl(path) { return "https://" + D.site + path; }

  /* a ▲/▼ delta chip; goodWhenUp flips the color meaning (errors: up = bad) */
  function deltaChip(value, opts) {
    opts = opts || {};
    if (value === null || value === undefined) return "";
    var up = value > 0, flat = Math.abs(value) < 0.05;
    var good = opts.goodWhenUp === false ? !up : up;
    var cls = flat ? "growth-flat" : (good ? "growth-up" : "growth-down");
    var arrow = flat ? "→" : (up ? "▲" : "▼");
    var num = opts.pp
      ? (up ? "+" : "") + value.toFixed(2) + " pp"
      : (up ? "+" : "") + Math.round(value) + "%";
    return ' <span class="growth-badge ' + cls + '">' + arrow + " " + num + "</span>";
  }

  function setStat(id, valueText, sub, deltaHtml) {
    var el = document.getElementById(id);
    if (!el) return;
    el.querySelector(".stat-value").innerHTML = valueText + (deltaHtml || "");
    if (sub) el.querySelector(".stat-sub").textContent = sub;
  }

  /* ---- executive summary ----------------------------------------------- */
  function renderSummary() {
    var s = data.summary, wow = data.prior_available;
    var sub = wow ? "vs. prior " + data.days + "d" : "no prior window to compare";

    setStat("stat-requests", "~" + D.fmtNum(s.requests.value), sub,
      wow ? deltaChip(s.requests.delta) : "");
    setStat("stat-visits", "~" + D.fmtNum(s.visits.value), sub,
      wow ? deltaChip(s.visits.delta) : "");
    setStat("stat-bytes", "~" + D.fmtBytes(s.bytes.value), sub,
      wow ? deltaChip(s.bytes.delta) : "");

    if (s.uniques.value == null) {
      setStat("stat-uniques", "n/a", "live count unavailable", "");
    } else {
      setStat("stat-uniques", "~" + D.fmtNum(s.uniques.value), sub,
        wow ? deltaChip(s.uniques.delta) : "");
    }

    setStat("stat-errors", D.fmtPct(s.error_rate.value), sub,
      wow ? deltaChip(s.error_rate.delta_pp, { pp: true, goodWhenUp: false }) : "");
    setStat("stat-cache", D.fmtPct(s.cache_hit_ratio.value), "served from edge cache", "");
  }

  /* ---- story of the week ----------------------------------------------- */
  function renderStory() {
    var host = document.getElementById("story-card");
    var st = data.story;
    if (!st || st.gain <= 0) {
      D.message(storyOverlay, "No standout day-over-day surge in this window yet.");
      return;
    }
    host.innerHTML =
      '<div class="story">' +
        '<div class="story-gain">+' + D.fmtNum(st.gain) + '</div>' +
        '<div class="story-body">' +
          '<a class="story-title" href="' + siteUrl(st.path) + '" target="_blank" rel="noopener">' +
            esc(st.title) + "</a>" +
          '<div class="story-meta">' +
            "climbed from ~" + D.fmtNum(st.from) + " to ~" + D.fmtNum(st.to) +
            " reads on " + dayLabel(st.date) +
            ' · <span class="story-path">' + esc(st.path) + "</span>" +
          "</div>" +
        "</div>" +
      "</div>";
    D.ready(storyOverlay);
  }

  /* ---- day-by-day table ------------------------------------------------ */
  function articleCell(item) {
    if (!item) return '<span class="muted">—</span>';
    var gain = item.gain != null ? ' <span class="muted">(+' + D.fmtNum(item.gain) + ")</span>" : "";
    var hits = item.hits != null ? ' <span class="muted">~' + D.fmtNum(item.hits) + "</span>" : "";
    return '<a href="' + siteUrl(item.path) + '" target="_blank" rel="noopener" title="' +
      esc(item.path) + '">' + esc(item.title) + "</a>" + hits + gain;
  }

  function renderDaily() {
    var body = document.querySelector("#daily-table tbody");
    body.innerHTML = "";
    data.daily.forEach(function (row) {
      var partial = row.hours_covered > 0 && row.hours_covered < 24;
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + dayLabel(row.date) +
          (partial ? ' <span class="growth-badge growth-flat">partial</span>' : "") + "</td>" +
        '<td class="num">~' + D.fmtNum(row.visits) + "</td>" +
        '<td class="num">' + (row.uniques == null ? "—" : "~" + D.fmtNum(row.uniques)) + "</td>" +
        '<td class="num">~' + D.fmtNum(row.requests) + "</td>" +
        '<td class="num">' + D.fmtPct(row.error_rate) + "</td>" +
        "<td>" + articleCell(row.top) + "</td>" +
        "<td>" + articleCell(row.riser) + "</td>";
      body.appendChild(tr);
    });
    D.ready(dailyOverlay);
  }

  /* ---- visits-per-day bars --------------------------------------------- */
  function renderVisits() {
    if (!data) return;
    var t = D.tokens();
    var rows = data.daily;
    visits.setOption({
      backgroundColor: "transparent",
      grid: { left: 56, right: 18, top: 16, bottom: 28 },
      tooltip: Object.assign(D.tooltipBase(), {
        trigger: "axis",
        formatter: function (params) {
          var p = params[0]; if (!p) return "";
          var row = rows[p.dataIndex];
          var uniq = row.uniques == null ? "" : "<br>~" + D.fmtNum(row.uniques) + " unique viewers";
          return "<strong>" + dayLabel(row.date) + "</strong><br>~" +
            D.fmtNum(row.visits) + " visits" + uniq +
            "<br>~" + D.fmtNum(row.requests) + " requests";
        }
      }),
      xAxis: { type: "category", data: rows.map(function (r) { return dayLabel(r.date); }),
        axisLine: D.axisLine(),
        // ECharts auto-hides labels it thinks would overlap; at the narrow print
        // width that dropped every other day. Force all labels when there are few
        // enough to fit (7d board view); keep auto-decimation for longer ranges.
        axisLabel: Object.assign(D.axisLabel(), { interval: rows.length <= 10 ? 0 : "auto" }),
        axisTick: { show: false } },
      yAxis: { type: "value", axisLabel: Object.assign(D.axisLabel(), { formatter: D.fmtNum }),
        splitLine: D.splitLine() },
      series: [{
        type: "bar", data: rows.map(function (r) { return r.visits; }),
        barMaxWidth: 46, barMinHeight: 1,
        // values are written onto the bars when printing, so a PDF/print needs
        // no hovering to be readable.
        label: { show: printing, position: "top", color: t.dim, fontSize: 10,
          formatter: function (p) { return "~" + D.fmtNum(p.value); } },
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: t.rising }, { offset: 1, color: "rgba(255,122,69,0.25)" }
          ])
        },
        emphasis: { itemStyle: { color: t.live } },
        // no animation while printing, so the bars are fully drawn on paper
        animationDuration: (printing || D.prefersReduced()) ? 0 : 700
      }]
    }, true);
  }

  /* ---- audience split -------------------------------------------------- */
  function renderAudience() {
    var a = data.audience, host = document.getElementById("audience-card");
    var total = a.total || 1;
    var segs = [
      { label: "Human (est.)", value: a.human, color: "#4f8ff7" },
      { label: "Search engines", value: a.search, color: "#3fb96f" },
      { label: "AI crawlers", value: a.ai, color: "#f6821f" },
      { label: "Other bots", value: a.other_bots, color: "#8a93a6" }
    ].filter(function (s) { return s.value > 0; });

    var bar = '<div class="split-bar">' + segs.map(function (s) {
      return '<span class="split-seg" style="width:' + (s.value / total * 100) +
        "%;background:" + s.color + '" title="' + s.label + '"></span>';
    }).join("") + "</div>";

    var legend = '<div class="split-legend">' + segs.map(function (s) {
      return '<div class="split-row"><span class="split-key" style="background:' + s.color + '"></span>' +
        '<span class="split-name">' + s.label + "</span>" +
        '<span class="split-val">~' + D.fmtNum(s.value) + " · " +
        (s.value / total * 100).toFixed(1) + "%</span></div>";
    }).join("") + "</div>";

    host.innerHTML = bar + legend;
    D.ready(audienceOverlay);
  }

  /* The same humans-vs-bots sunburst as the Bots & AI page, sized here to match
     the split legend below it (colors come straight from the backend nodes, so
     the rings and the legend stay in sync). Click a segment to zoom. */
  function renderSunburst() {
    var a = data && data.audience;
    if (!a || !a.sunburst || !a.total) return;
    var t = D.tokens();
    sunburst.setOption({
      backgroundColor: "transparent",
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var share = a.total ? " · " + D.fmtPct(p.value / a.total) + " of total" : "";
          return "<strong>" + p.name + "</strong><br>~" + D.fmtNum(p.value) + " est. requests" + share;
        }
      }),
      series: [{
        type: "sunburst", data: JSON.parse(JSON.stringify(a.sunburst)),
        radius: ["16%", "92%"], sort: "desc", nodeClick: "rootToNode",
        emphasis: { focus: "ancestor" },
        itemStyle: { borderColor: t.surface, borderWidth: 2 },
        label: { color: "#fff", fontSize: 11, fontFamily: "Inter", minAngle: 8,
          formatter: function (p) { return p.name.length > 16 ? p.name.slice(0, 15) + "…" : p.name; } },
        levels: [ {},
          { r0: "16%", r: "50%", label: { rotate: 0, fontSize: 12 } },
          { r0: "50%", r: "72%" },
          { r0: "72%", r: "92%", label: { rotate: "tangential", fontSize: 10 } } ],
        animationDuration: (printing || D.prefersReduced()) ? 0 : 800
      }]
    }, true);
  }

  /* ---- top sections ---------------------------------------------------- */
  function renderCategories() {
    var host = document.getElementById("categories-card");
    if (!data.categories.length) {
      D.message(categoriesOverlay, "No article traffic stored for this window.");
      return;
    }
    var max = data.categories[0].share || 1;
    host.innerHTML = '<div class="cat-list">' + data.categories.map(function (c) {
      return '<div class="cat-row">' +
        '<span class="cat-name" title="' + esc(c.name) + '">' + esc(c.name) + "</span>" +
        '<span class="cat-track"><span class="cat-fill" style="width:' +
          (c.share / max * 100) + '%"></span></span>' +
        '<span class="cat-share">' + c.share + "%</span></div>";
    }).join("") + "</div>";
    D.ready(categoriesOverlay);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ---- story timelines: per-day card ----------------------------------
     Built for a meeting: each day leads with one plain-English takeaway, then
     the top 3 stories as labelled hour-strips (darker hour = more reads, ringed
     cell = peak). Ranks 4+ stay behind "show more" on screen, but expand in
     print so the PDF is complete. */
  function hourFmt(d) { return d.toLocaleTimeString([], { hour: "numeric" }); }

  // The contiguous-ish window where reads sat at/above `frac` of the peak.
  // Returns {start, end (Date, exclusive), single} or null.
  function busyWindow(points, frac) {
    var max = points.reduce(function (m, p) { return Math.max(m, p.hits); }, 0) || 1;
    var thr = frac * max;
    var hot = points.filter(function (p) { return p.hits >= thr; });
    if (!hot.length) return null;
    var s = new Date(hot[0].ts), e = new Date(hot[hot.length - 1].ts);
    e.setHours(e.getHours() + 1);
    return { start: s, end: e, single: hot.length === 1 };
  }
  function rangeText(w) {
    if (!w) return "";
    return w.single ? "around " + hourFmt(w.start) : hourFmt(w.start) + "–" + hourFmt(w.end);
  }
  function partOfDay(h) {
    return h < 5 ? "overnight" : h < 8 ? "in the early morning" : h < 12 ? "in the morning"
      : h < 14 ? "around midday" : h < 17 ? "in the afternoon" : h < 21 ? "in the evening"
      : "in the late evening";
  }

  // Plain-English summary of the whole day, from the combined hourly curve,
  // plus the headline stats the insight card surfaces.
  function daySummary(day) {
    var n = day.articles[0].hourly.length, tot = [];
    for (var i = 0; i < n; i++) {
      var s = 0;
      day.articles.forEach(function (a) { s += a.hourly[i].hits; });
      tot.push({ ts: day.articles[0].hourly[i].ts, hits: s });
    }
    var w = busyWindow(tot, 0.6), lead = day.articles[0];
    var main = !w ? "Not enough traffic to summarise this day."
      : w.single ? "Reading activity peaked " + partOfDay(w.start.getHours()) + ", around " + hourFmt(w.start) + "."
      : "Reading activity peaked " + partOfDay(w.start.getHours()) + ", between " +
          hourFmt(w.start) + " and " + hourFmt(w.end) + ".";
    return { main: main, peak: w ? rangeText(w) : "—", lead: lead };
  }

  // discrete 5-step heat scale — reads more clearly at a glance than a
  // continuous wash; faint hours stay neutral.
  function heatClass(frac) {
    if (frac < 0.05) return "low";
    var i = Math.sqrt(frac);
    return i < 0.2 ? "m1" : i < 0.4 ? "m2" : i < 0.6 ? "m3" : i < 0.8 ? "m4" : "m5";
  }

  var CLOCK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>';

  /* The SINGLE story component used for every visible traction story — top-3
     AND the expanded ones. They must never diverge: the only thing `idx`
     controls is the `extra` visibility class. DOM is always headline + full
     heatmap + metadata. (Named distinctly from the "Story of the week" panel's
     renderStory() above.) */
  function renderStoryRow(a, idx, cols) {
    var max = a.hourly.reduce(function (m, p) { return Math.max(m, p.hits); }, 0) || 1;
    // outline exactly ONE cell — the single busiest hour
    var peakIdx = 0;
    a.hourly.forEach(function (p, i) { if (p.hits > a.hourly[peakIdx].hits) peakIdx = i; });
    var line = a.hourly.map(function (p, i) {
      var peak = (i === peakIdx && p.hits > 0) ? " peak" : "";
      var tip = new Date(p.ts).toLocaleString() + " · ~" + D.fmtNum(p.hits) + " reads";
      return '<span class="slot ' + heatClass(p.hits / max) + peak + '" title="' + tip + '"></span>';
    }).join("");
    var w = busyWindow(a.hourly, 0.5);
    var meta = "~" + D.fmtNum(a.total) + " reads" +
      (w ? ' · <span class="peak">Peak ' + rangeText(w) + "</span>" : "");
    return '<div class="story' + (idx >= 3 ? " extra" : "") + '">' +
      '<a class="story-title" href="' + siteUrl(a.path) + '" target="_blank" rel="noopener" title="' +
        esc(a.path) + '">' + esc(a.title) + "</a>" +
      '<div class="heatline" style="grid-template-columns:' + cols + '">' + line + "</div>" +
      '<div class="story-meta">' + meta + "</div>" +
    "</div>";
  }

  function buildTraction() {
    var host = document.getElementById("traction-section");
    var head = document.getElementById("traction-head");
    host.innerHTML = "";
    if (!data.traction || !data.traction.length) { if (head) head.hidden = true; return; }
    if (head) head.hidden = false;

    var dailyByDate = {};
    (data.daily || []).forEach(function (d) { dailyByDate[d.date] = d; });

    data.traction.forEach(function (day) {
      var cols = "repeat(" + day.articles[0].hourly.length + ", 1fr)";

      // Every story — top-3 and the rest — goes through the same renderStoryRow().
      var stories = day.articles.map(function (a, i) {
        return renderStoryRow(a, i, cols);
      }).join("");

      var axis = day.articles[0].hourly.map(function (p, i) {
        return "<span>" + (i % 4 === 0 ? hourFmt(new Date(p.ts)) : "") + "</span>";
      }).join("");

      var sum = daySummary(day);
      var dRow = dailyByDate[day.date];
      var totalReads = dRow && dRow.visits != null
        ? dRow.visits : day.articles.reduce(function (s, a) { return s + a.total; }, 0);
      var extra = day.articles.length - 3;

      var stats =
        '<div class="istat"><div class="istat-label">Peak period</div>' +
          '<div class="istat-value">' + esc(sum.peak) + "</div></div>" +
        '<div class="istat"><div class="istat-label">Total reads</div>' +
          '<div class="istat-value">~' + D.fmtNum(totalReads) + "</div></div>" +
        '<div class="istat istat-wide"><div class="istat-label">Top story</div>' +
          '<div class="istat-value" title="' + esc(sum.lead.title) + '">' + esc(sum.lead.title) + "</div></div>";

      var panel = document.createElement("div");
      panel.className = "panel span-12 traction-day";
      panel.innerHTML =
        '<div class="day-top"><span class="day-label">' + dayLabel(day.date) + "</span>" +
          '<span class="day-meta">' + day.articles.length + " stories tracked</span></div>" +
        '<div class="insight">' +
          '<div class="insight-head"><span class="insight-badge">' + CLOCK_SVG + "</span>" +
            '<div><div class="insight-eyebrow">Daily insight</div>' +
            '<h3 class="insight-main">' + esc(sum.main) + "</h3></div></div>" +
          '<div class="insight-stats">' + stats + "</div></div>" +
        '<div class="story-list">' + stories + "</div>" +
        '<div class="heat-axis" style="grid-template-columns:' + cols + '">' + axis + "</div>" +
        (extra > 0 ? '<button type="button" class="show-more">Show ' + extra + " more ▾</button>" : "");
      host.appendChild(panel);

      var btn = panel.querySelector(".show-more");
      if (btn) btn.addEventListener("click", function () {
        var open = panel.classList.toggle("open");
        btn.innerHTML = open ? "Show less ▴" : "Show " + extra + " more ▾";
      });
    });
  }

  D.onTheme(function () { renderVisits(); renderSunburst(); });

  /* ---- print / PDF ----------------------------------------------------
     The on-screen view is dark and interactive; for a printout we flip to the
     light palette (legible on white), turn on chart value labels, then open
     the browser's print dialog where "Save as PDF" produces the download. */
  function stampGenerated() {
    var gen = document.getElementById("print-generated");
    if (gen) gen.textContent = new Date().toLocaleString();
  }
  function beginPrint() {
    if (printing) return;
    printing = true;
    prevTheme = D.current();
    stampGenerated();
    D.setTheme("light");   // re-renders charts via onTheme: light palette + labels
    // A <canvas> won't shrink to the page on its own, so pin it to a fixed size
    // that fits the printable width of both Letter and A4 (~672px), otherwise the
    // last days spill off the right margin. 660x234px ≈ the print CSS's 62mm tall.
    visits.resize({ width: 660, height: 234 });
    // sunburst is square-ish; pin it to fit the print column (74mm tall in CSS)
    sunburst.resize({ width: 660, height: 280 });
  }
  function endPrint() {
    if (!printing) return;
    printing = false;
    if (prevTheme) D.setTheme(prevTheme);
    // beginPrint pinned the canvas to 660x234; ECharts remembers explicit sizes,
    // so a plain resize() would keep reusing them and leave the chart stuck at
    // print width. "auto" discards the pin and re-measures the live container.
    visits.resize({ width: "auto", height: "auto" });
    sunburst.resize({ width: "auto", height: "auto" });
  }
  var pdfBtn = document.getElementById("download-pdf");
  if (pdfBtn) pdfBtn.addEventListener("click", function () {
    beginPrint();
    // give the light re-render a beat to paint before the dialog opens
    setTimeout(function () { window.print(); }, 350);
  });
  window.addEventListener("beforeprint", beginPrint);  // covers Ctrl/Cmd+P
  window.addEventListener("afterprint", endPrint);

  function fail(msg) {
    [storyOverlay, dailyOverlay, visitsOverlay, audienceOverlay, categoriesOverlay]
      .forEach(function (o) { D.message(o, msg); });
  }

  D.fetchJSON("/api/report").then(function (d) {
    if (d.source === "none") { fail(D.noticeText(d.notice)); return; }
    D.setBadge(d.source);
    data = d;

    var label = d.days === 1 ? "1 day" : d.days + " days";
    D.setText("report-window", label);
    if (d.days < 7) {
      D.setText("report-subtitle",
        "Showing " + label + ". For the full board view, pick the 7d range above.");
    }

    renderSummary();
    renderStory();
    renderDaily();
    renderVisits();
    D.ready(visitsOverlay);
    renderSunburst();
    renderAudience();
    renderCategories();
    buildTraction();
  }).catch(function (err) {
    fail("Could not load data: " + err.message);
  });
})();
