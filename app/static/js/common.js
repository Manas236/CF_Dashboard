/* Shared helpers + theming for every dashboard page.
   Charts are driven from the same tokens as the CSS; on a theme switch we
   re-run each page's registered render fn so axes, grid, labels, tooltip and
   series colors all swap. */
window.Dash = (function () {
  "use strict";

  var SITE = window.DASH.site;
  var RANGE = window.DASH.range;

  /* ---- palette ----------------------------------------------------- */
  var PALETTES = {
    dark: {
      text: "#eef1f8", dim: "#8a93a8", faint: "#626b80",
      bg: "#0e1118", surface: "#161b27", surface2: "#1d2434", surface3: "#232c40",
      border: "#2a3243", grid: "rgba(255,255,255,0.05)",
      tooltipBg: "#1d2434", tooltipBorder: "#3a4459"
    },
    light: {
      text: "#121725", dim: "#5d6679", faint: "#8b93a5",
      bg: "#f4f6fb", surface: "#ffffff", surface2: "#eef1f8", surface3: "#e7ecf5",
      border: "#e3e8f1", grid: "rgba(18,23,37,0.07)",
      tooltipBg: "#ffffff", tooltipBorder: "#d2dae8"
    }
  };
  /* accents are identical in both themes so meaning stays stable */
  var ACCENT = {
    live: "#ff5436", rising: "#ff7a45", amber: "#ffb020",
    fading: "#19c8d8", steady: "#6c5ce7",
    positive: "#1fce82", negative: "#ff4d6a", accent: "#ff7a45"
  };
  /* momentum is encoded by hue: rising = warm, fading = cool, steady = indigo */
  var MOMENTUM = { rising: "#ff7a45", new: "#ffb020", steady: "#6c5ce7", fading: "#19c8d8" };
  /* a categorical palette built from the accent family */
  var CAT_PALETTE = ["#ff7a45", "#6c5ce7", "#19c8d8", "#ffb020", "#1fce82",
                     "#ff4d6a", "#4f8ff7", "#b58cf5", "#ff5436", "#46c2cb",
                     "#9a8cff", "#8a93a8"];

  function current() { return document.documentElement.getAttribute("data-theme") || "dark"; }
  function tokens() {
    var t = {};
    var pal = PALETTES[current()] || PALETTES.dark;
    Object.keys(pal).forEach(function (k) { t[k] = pal[k]; });
    Object.keys(ACCENT).forEach(function (k) { t[k] = ACCENT[k]; });
    t.momentum = MOMENTUM;
    t.catPalette = CAT_PALETTE;
    return t;
  }
  function momentumColor(cls) { return MOMENTUM[cls] || ACCENT.steady; }

  function prefersReduced() {
    return window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /* ---- ECharts shared option fragments (read live tokens) ---------- */
  function tooltipBase() {
    var t = tokens();
    return {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: t.text, fontSize: 12, fontFamily: "Inter, sans-serif" },
      extraCssText: "border-radius:10px;box-shadow:0 10px 28px -10px rgba(0,0,0,0.45);"
    };
  }
  function axisLabel() { return { color: tokens().dim, fontSize: 11 }; }
  function axisLine() { return { lineStyle: { color: tokens().border } }; }
  function splitLine() { return { lineStyle: { color: tokens().grid } }; }

  /* ---- chart registry + theme switching ---------------------------- */
  var charts = [];
  var themeCbs = [];

  function makeChart(elId) {
    var chart = echarts.init(document.getElementById(elId), null, { renderer: "canvas" });
    charts.push(chart);
    return chart;
  }
  function onTheme(fn) { themeCbs.push(fn); }

  var rt;
  window.addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(function () { charts.forEach(function (c) { c.resize(); }); }, 120);
  });

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("dash-theme", theme); } catch (e) {}
    themeCbs.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
  }
  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      setTheme(current() === "dark" ? "light" : "dark");
    });
  }

  /* ---- formatting -------------------------------------------------- */
  function fmtNum(n) {
    if (n === null || n === undefined) return "—";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e4) return (n / 1e3).toFixed(1) + "K";
    return Math.round(n).toLocaleString();
  }
  function fmtBytes(b) {
    if (b === null || b === undefined) return "—";
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(b >= 100 || i === 0 ? 0 : 1) + " " + u[i];
  }
  function fmtPct(x) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    var p = x * 100;
    return (p >= 10 ? p.toFixed(1) : p.toFixed(2)) + "%";
  }
  function fmtGrowth(g) {
    if (g === null || g === undefined) return "NEW";
    var v = Math.round(g);
    return (v > 0 ? "+" : "") + v + "%";
  }

  /* count-up tween for KPI numbers */
  function countUp(el, to, opts) {
    opts = opts || {};
    var fmt = opts.fmt || function (v) { return Math.round(v).toLocaleString(); };
    if (prefersReduced() || to == null) { el.textContent = fmt(to); return; }
    var dur = opts.dur || 850, from = opts.from || 0, t0 = performance.now();
    (function step(now) {
      var p = Math.min((now - t0) / dur, 1);
      var e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(from + (to - from) * e);
      if (p < 1) requestAnimationFrame(step);
    })(performance.now());
  }

  /* ---- source badge / meta ---------------------------------------- */
  function sourceLabel(s) {
    if (s === "mysql") return "stored rollups";
    if (s === "cloudflare-live") return "live from Cloudflare";
    return "";
  }
  function noticeText(n) {
    if (n === "no_history")
      return "No stored data for this range yet.\nRun collector.py (see README) to build history.";
    if (n === "db_unavailable")
      return "MySQL is unreachable — check the database settings in .env.";
    return "";
  }
  function setBadge(source) {
    var b = document.getElementById("source-badge");
    if (!b) return;
    b.textContent = sourceLabel(source);
    b.hidden = !b.textContent;
    b.classList.toggle("live", source === "cloudflare-live");
  }
  function setUpdated(text) {
    var el = document.getElementById("updated-at");
    if (el) el.textContent = text;
  }
  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  /* ---- overlay states --------------------------------------------- */
  function loading(el) { if (el) { el.classList.add("skeleton"); el.textContent = ""; el.hidden = false; } }
  function message(el, msg) { if (el) { el.classList.remove("skeleton"); el.textContent = msg; el.hidden = false; } }
  function ready(el) { if (el) { el.classList.remove("skeleton"); el.hidden = true; } }

  /* ---- data ------------------------------------------------------- */
  function fetchJSON(url) {
    var sep = url.indexOf("?") === -1 ? "?" : "&";
    return fetch(url + sep + "site=" + encodeURIComponent(SITE) +
                 "&range=" + encodeURIComponent(RANGE))
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.error) throw new Error(d.error); return d; });
  }

  /* ---- site selector ---------------------------------------------- */
  var select = document.getElementById("site-select");
  if (select) {
    select.addEventListener("change", function () {
      location.href = location.pathname +
        "?site=" + encodeURIComponent(this.value) +
        "&range=" + encodeURIComponent(RANGE);
    });
  }

  return {
    site: SITE, range: RANGE,
    tokens: tokens, current: current, momentumColor: momentumColor,
    prefersReduced: prefersReduced,
    tooltipBase: tooltipBase, axisLabel: axisLabel, axisLine: axisLine, splitLine: splitLine,
    makeChart: makeChart, onTheme: onTheme,
    fmtNum: fmtNum, fmtBytes: fmtBytes, fmtPct: fmtPct, fmtGrowth: fmtGrowth, countUp: countUp,
    sourceLabel: sourceLabel, noticeText: noticeText,
    setBadge: setBadge, setUpdated: setUpdated, setText: setText,
    loading: loading, message: message, ready: ready,
    fetchJSON: fetchJSON
  };
})();
