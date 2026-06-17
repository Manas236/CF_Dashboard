/* Panel E — world choropleth (focused on traffic beyond India) + ranked list. */
(function () {
  "use strict";
  var D = window.Dash;

  var ISO2 = {
    AD: "Andorra", AE: "United Arab Emirates", AF: "Afghanistan", AG: "Antigua and Barb.",
    AL: "Albania", AM: "Armenia", AO: "Angola", AR: "Argentina", AT: "Austria",
    AU: "Australia", AZ: "Azerbaijan", BA: "Bosnia and Herz.", BB: "Barbados",
    BD: "Bangladesh", BE: "Belgium", BF: "Burkina Faso", BG: "Bulgaria", BH: "Bahrain",
    BI: "Burundi", BJ: "Benin", BN: "Brunei", BO: "Bolivia", BR: "Brazil", BS: "Bahamas",
    BT: "Bhutan", BW: "Botswana", BY: "Belarus", BZ: "Belize", CA: "Canada",
    CD: "Dem. Rep. Congo", CF: "Central African Rep.", CG: "Congo", CH: "Switzerland",
    CI: "Côte d'Ivoire", CL: "Chile", CM: "Cameroon", CN: "China", CO: "Colombia",
    CR: "Costa Rica", CU: "Cuba", CY: "Cyprus", CZ: "Czech Rep.", DE: "Germany",
    DJ: "Djibouti", DK: "Denmark", DO: "Dominican Rep.", DZ: "Algeria", EC: "Ecuador",
    EE: "Estonia", EG: "Egypt", ER: "Eritrea", ES: "Spain", ET: "Ethiopia",
    FI: "Finland", FJ: "Fiji", FK: "Falkland Is.", FR: "France", GA: "Gabon",
    GB: "United Kingdom", GE: "Georgia", GH: "Ghana", GL: "Greenland", GM: "Gambia",
    GN: "Guinea", GQ: "Eq. Guinea", GR: "Greece", GT: "Guatemala", GW: "Guinea-Bissau",
    GY: "Guyana", HN: "Honduras", HR: "Croatia", HT: "Haiti", HU: "Hungary",
    ID: "Indonesia", IE: "Ireland", IL: "Israel", IN: "India", IQ: "Iraq", IR: "Iran",
    IS: "Iceland", IT: "Italy", JM: "Jamaica", JO: "Jordan", JP: "Japan", KE: "Kenya",
    KG: "Kyrgyzstan", KH: "Cambodia", KP: "Dem. Rep. Korea", KR: "Korea",
    KW: "Kuwait", KZ: "Kazakhstan", LA: "Lao PDR", LB: "Lebanon", LK: "Sri Lanka",
    LR: "Liberia", LS: "Lesotho", LT: "Lithuania", LU: "Luxembourg", LV: "Latvia",
    LY: "Libya", MA: "Morocco", MD: "Moldova", ME: "Montenegro", MG: "Madagascar",
    MK: "Macedonia", ML: "Mali", MM: "Myanmar", MN: "Mongolia", MR: "Mauritania",
    MW: "Malawi", MX: "Mexico", MY: "Malaysia", MZ: "Mozambique", NA: "Namibia",
    NC: "New Caledonia", NE: "Niger", NG: "Nigeria", NI: "Nicaragua",
    NL: "Netherlands", NO: "Norway", NP: "Nepal", NZ: "New Zealand", OM: "Oman",
    PA: "Panama", PE: "Peru", PG: "Papua New Guinea", PH: "Philippines",
    PK: "Pakistan", PL: "Poland", PR: "Puerto Rico", PS: "Palestine",
    PT: "Portugal", PY: "Paraguay", QA: "Qatar", RO: "Romania", RS: "Serbia",
    RU: "Russia", RW: "Rwanda", SA: "Saudi Arabia", SB: "Solomon Is.", SD: "Sudan",
    SE: "Sweden", SG: "Singapore", SI: "Slovenia", SK: "Slovakia", SL: "Sierra Leone",
    SN: "Senegal", SO: "Somalia", SR: "Suriname", SS: "S. Sudan", SV: "El Salvador",
    SY: "Syria", SZ: "Swaziland", TD: "Chad", TG: "Togo", TH: "Thailand",
    TJ: "Tajikistan", TL: "Timor-Leste", TM: "Turkmenistan", TN: "Tunisia",
    TR: "Turkey", TT: "Trinidad and Tobago", TW: "Taiwan", TZ: "Tanzania",
    UA: "Ukraine", UG: "Uganda", US: "United States", UY: "Uruguay",
    UZ: "Uzbekistan", VE: "Venezuela", VN: "Vietnam", VU: "Vanuatu",
    YE: "Yemen", ZA: "South Africa", ZM: "Zambia", ZW: "Zimbabwe"
  };
  var FALLBACK = { HK: "Hong Kong", MO: "Macao", SG: "Singapore", MT: "Malta",
    BH: "Bahrain", MV: "Maldives", MU: "Mauritius", KM: "Comoros", CV: "Cabo Verde",
    ST: "São Tomé", WS: "Samoa", TO: "Tonga", SC: "Seychelles" };
  function countryName(c) { return ISO2[c] || FALLBACK[c] || c; }

  var chart = D.makeChart("geo-chart");
  var overlay = document.getElementById("geo-overlay");
  var listOverlay = document.getElementById("geo-list-overlay");
  var data = null;
  var mode = "world";

  function renderMap() {
    if (!data) return;
    if (typeof echarts.getMap === "function" && !echarts.getMap("world")) {
      D.message(overlay, "World map asset failed to load from the CDN — the ranked list still has the data.");
      return;
    }
    var t = D.tokens();
    var rows = data.countries.filter(function (c) { return mode === "all" || c.code !== data.home_country; });
    var mapData = rows.filter(function (c) { return ISO2[c.code]; })
      .map(function (c) { return { name: ISO2[c.code], value: c.requests, code: c.code }; });
    var maxV = mapData.length ? mapData[0].value : 1;

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: Object.assign(D.tooltipBase(), {
        formatter: function (p) {
          if (!p.data || p.data.value === undefined) return p.name + "<br><span style='color:" + t.dim + "'>no sampled traffic</span>";
          var share = data.total ? " · " + D.fmtPct(p.data.value / data.total) + " of all traffic" : "";
          return "<strong>" + p.name + "</strong><br>~" + D.fmtNum(p.data.value) + " est. requests" + share;
        }
      }),
      visualMap: { min: 0, max: maxV, text: ["high", "low"], left: 0, bottom: 0, calculable: false,
        textStyle: { color: t.dim, fontSize: 10 }, formatter: D.fmtNum,
        inRange: { color: [t.surface3, t.steady, t.fading, t.rising] } },
      series: [{ type: "map", map: "world", roam: true, scaleLimit: { min: 1, max: 6 }, zoom: 1.15,
        itemStyle: { areaColor: t.surface2, borderColor: t.border, borderWidth: 0.5 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: t.amber } },
        select: { disabled: true }, data: mapData }]
    }, true);
    D.ready(overlay);
  }

  function renderList() {
    var host = document.getElementById("geo-list");
    var intl = data.countries.filter(function (c) { return c.code !== data.home_country; });
    var intlTotal = intl.reduce(function (s, c) { return s + c.requests; }, 0) || 1;
    host.innerHTML = "";
    intl.slice(0, 12).forEach(function (c) {
      var share = c.requests / intlTotal;
      var li = document.createElement("li");
      li.innerHTML = "<div style='flex:1;min-width:0'>" +
        "<div>" + countryName(c.code) + " <span class='muted' style='font-family:JetBrains Mono,monospace'>" + c.code + "</span></div>" +
        "<div class='geo-bar' style='width:" + Math.max(share * 100, 1.5) + "%'></div></div>" +
        "<div class='num' style='text-align:right'>~" + D.fmtNum(c.requests) +
        "<div class='muted' style='font-size:11px'>" + D.fmtPct(share) + " of intl.</div></div>";
      host.appendChild(li);
    });
    if (!intl.length) host.innerHTML = "<li class='muted'>No international traffic stored in this window.</li>";
  }

  function renderStats() {
    var intlTotal = data.total - data.home;
    D.countUp(document.getElementById("stat-home"), data.total ? data.home / data.total : 0, { fmt: D.fmtPct });
    D.setText("stat-home-sub", "~" + D.fmtNum(data.home) + " est. requests");
    D.countUp(document.getElementById("stat-intl"), data.total ? intlTotal / data.total : 0, { fmt: D.fmtPct });
    D.setText("stat-intl-sub", "~" + D.fmtNum(intlTotal) + " est. requests");
    D.setText("stat-count", data.countries.length);
    var top = data.countries.filter(function (c) { return c.code !== data.home_country; })[0];
    if (top) {
      D.setText("stat-top", countryName(top.code));
      D.setText("stat-top-sub", "~" + D.fmtNum(top.requests) + " est. requests");
    }
  }

  document.querySelectorAll("#geo-mode button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      mode = btn.dataset.mode;
      document.querySelectorAll("#geo-mode button").forEach(function (b) {
        b.classList.toggle("active", b === btn); });
      renderMap();
    });
  });

  D.onTheme(renderMap);

  D.fetchJSON("/api/panel/geo").then(function (d) {
    if (d.source === "none") {
      D.message(overlay, D.noticeText(d.notice));
      D.message(listOverlay, D.noticeText(d.notice));
      return;
    }
    data = d;
    D.setBadge(d.source);
    D.setText("geo-note", d.countries.length + " countries · ~" + D.fmtNum(d.total) + " est. requests");
    renderStats();
    renderList();
    D.ready(listOverlay);
    renderMap();
  }).catch(function (err) {
    D.message(overlay, "Could not load data: " + err.message);
    D.message(listOverlay, "Could not load data: " + err.message);
  });
})();
