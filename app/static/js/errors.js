/* Panel C — error heatmap (paths/status toggle) + sortable broken-URLs table. */
(function () {
  "use strict";
  var D = window.Dash;

  var chart = D.makeChart("heatmap-chart");
  var hmOverlay = document.getElementById("heatmap-overlay");
  var tblOverlay = document.getElementById("table-overlay");
  var data = null;
  var mode = "paths";

  function colLabel(iso, bh) {
    var d = new Date(iso);
    return bh >= 24 ? (d.getMonth() + 1) + "/" + d.getDate() : d.getHours() + ":00";
  }
  function colTitle(iso, bh) {
    var d = new Date(iso);
    return bh >= 24 ? d.toLocaleDateString() : d.toLocaleString();
  }
  function shorten(s) { return s.length > 46 ? s.slice(0, 22) + "…" + s.slice(-22) : s; }

  function renderHeatmap() {
    if (!data) return;
    var t = D.tokens();
    var rows = mode === "paths" ? data.path_rows : data.status_rows;
    if (!rows.length) { D.message(hmOverlay, "No errors recorded in this window. 🎉"); return; }
    D.ready(hmOverlay);

    var labels = rows.map(function (r) { return r.label; }).reverse();
    var cells = [], maxV = 1;
    rows.forEach(function (r, ri) {
      r.cells.forEach(function (v, ci) {
        if (v > 0) { cells.push([ci, rows.length - 1 - ri, v]); if (v > maxV) maxV = v; }
      });
    });

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 232, right: 72, top: 12, bottom: 38 },
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          var row = rows[rows.length - 1 - p.value[1]];
          var head = mode === "paths" ? row.label : "HTTP " + row.label;
          return "<strong style='font-family:JetBrains Mono,monospace;font-size:11px'>" + head + "</strong><br>" +
            colTitle(data.cols[p.value[0]], data.bucket_hours) + "<br>~" +
            D.fmtNum(p.value[2]) + " est. errors";
        }
      }),
      xAxis: { type: "category", data: data.cols.map(function (c) { return colLabel(c, data.bucket_hours); }),
        axisLine: D.axisLine(), axisLabel: { color: t.dim, fontSize: 10 }, splitArea: { show: false } },
      yAxis: { type: "category", data: labels.map(shorten),
        axisLine: D.axisLine(),
        axisLabel: { color: t.dim, fontSize: 10,
          fontFamily: mode === "paths" ? "JetBrains Mono, monospace" : "Inter" } },
      visualMap: { min: 0, max: maxV, calculable: false, orient: "vertical", right: 2, top: "center",
        itemHeight: 130, textStyle: { color: t.dim, fontSize: 10 }, formatter: D.fmtNum,
        inRange: { color: [t.surface3, t.amber, t.rising, t.live] } },
      series: [{ type: "heatmap", data: cells,
        itemStyle: { borderColor: t.surface, borderWidth: 1, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: t.text, borderWidth: 1.5 } },
        progressive: 2000, animation: !D.prefersReduced() }]
    }, true);
  }

  /* ---- table ---- */
  var sortKey = "errors", sortDir = -1, filterText = "";

  function statusBadge(s) {
    return '<span class="status-badge ' + (s >= 500 ? "status-5xx" : "status-4xx") + '">' + s + "</span>";
  }
  function renderTable() {
    var tbody = document.querySelector("#error-table tbody");
    var rows = data.table.filter(function (r) {
      return !filterText || (r.path + " " + r.status).toLowerCase().indexOf(filterText) !== -1;
    });
    rows.sort(function (a, b) {
      var av = a[sortKey], bv = b[sortKey];
      if (av == null) av = -1; if (bv == null) bv = -1;
      return (av < bv ? -1 : av > bv ? 1 : 0) * sortDir;
    });
    tbody.innerHTML = "";
    rows.slice(0, 100).forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + statusBadge(r.status) + "</td>" +
        '<td class="path-cell">' + r.path + "</td>" +
        '<td class="num">~' + D.fmtNum(r.errors) + "</td>" +
        '<td class="num">' + (r.share == null ? '<span class="muted">—</span>' : D.fmtPct(r.share)) + "</td>" +
        '<td><button class="copy-btn" title="copy URL">copy</button></td>';
      tr.querySelector(".copy-btn").addEventListener("click", function () {
        var btn = this;
        navigator.clipboard.writeText("https://" + D.site + r.path).then(function () {
          btn.textContent = "copied"; btn.classList.add("copied");
          setTimeout(function () { btn.textContent = "copy"; btn.classList.remove("copied"); }, 1200);
        });
      });
      tbody.appendChild(tr);
    });
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted" style="padding:16px">' +
        (filterText ? "Nothing matches the filter." : "No errors recorded in this window.") + "</td></tr>";
    }
  }

  document.querySelectorAll("#error-table th.sortable").forEach(function (th) {
    th.addEventListener("click", function () {
      var key = th.dataset.key;
      if (sortKey === key) sortDir = -sortDir; else { sortKey = key; sortDir = -1; }
      document.querySelectorAll("#error-table th").forEach(function (h) {
        h.classList.remove("sorted-asc", "sorted-desc"); });
      th.classList.add(sortDir === 1 ? "sorted-asc" : "sorted-desc");
      renderTable();
    });
  });
  document.getElementById("table-filter").addEventListener("input", function () {
    filterText = this.value.trim().toLowerCase(); renderTable();
  });
  document.querySelectorAll("#heatmap-mode button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      mode = btn.dataset.mode;
      document.querySelectorAll("#heatmap-mode button").forEach(function (b) {
        b.classList.toggle("active", b === btn); });
      document.getElementById("heatmap-foot").textContent = mode === "paths"
        ? "Rows = top error-producing paths (top 300 error paths per hour are collected) · cell color = est. errors"
        : "Rows = HTTP status codes ≥ 400 across the whole zone · cell color = est. responses";
      renderHeatmap();
    });
  });

  D.onTheme(renderHeatmap);

  D.fetchJSON("/api/panel/errors").then(function (d) {
    if (d.source === "none") {
      D.message(hmOverlay, D.noticeText(d.notice));
      D.message(tblOverlay, D.noticeText(d.notice));
      return;
    }
    data = d;
    D.setBadge(d.source);
    var tt = d.totals;
    D.countUp(document.getElementById("stat-4xx"), tt.e4, { fmt: function (v) { return "~" + D.fmtNum(v); } });
    D.countUp(document.getElementById("stat-5xx"), tt.e5, { fmt: function (v) { return "~" + D.fmtNum(v); } });
    D.setText("stat-4xx-sub", tt.requests ? D.fmtPct(tt.e4 / tt.requests) + " of traffic" : "");
    D.setText("stat-5xx-sub", tt.requests ? D.fmtPct(tt.e5 / tt.requests) + " of traffic" : "");
    D.countUp(document.getElementById("stat-rate"), tt.requests ? (tt.e4 + tt.e5) / tt.requests : 0,
      { fmt: function (v) { return D.fmtPct(v); } });
    D.setText("heatmap-note", d.bucket_hours >= 24 ? "daily buckets (30d view)" : "hourly buckets");
    renderHeatmap();
    renderTable();
    D.ready(tblOverlay);
  }).catch(function (err) {
    D.message(hmOverlay, "Could not load data: " + err.message);
    D.message(tblOverlay, "Could not load data: " + err.message);
  });
})();
