/* ATLAS | Hyperliquid public market-data dashboard. No wallets, keys or order endpoints. */
(() => {
  "use strict";
  const reportPath = "./data/hyperliquid_btc_15m.json";
  const candlesPath = "./data/hyperliquid_btc_candles.json";
  const $ = id => document.getElementById(id);
  const money = value => Number.isFinite(value)
    ? "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";
  const number = (v, decimals = 2) => Number.isFinite(v) ? v.toFixed(decimals) : "—";
  const setText = (id, value) => { const node = $(id); if (node) node.textContent = value; };
  const fmtTime = ms => Number.isFinite(ms) && ms > 0
    ? new Intl.DateTimeFormat("ar-MA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(ms))
    : "—";
  const state = { report: null, candles: [], range: "24h", loading: false };

  function checkReport(r) {
    if (!r || r.exchange !== "Hyperliquid" || r.mode !== "READ_ONLY_ANALYSIS" ||
        r.interval !== "15m" || r.market !== "BTC perpetual") {
      throw new Error("مصدر البيانات غير متوقع.");
    }
    const keys = ["close_usd", "ema9", "ema21", "ema50", "rsi14",
                  "atr14_usd", "support_20_prior_candles", "resistance_20_prior_candles"];
    if (keys.some(k => typeof r[k] !== "number" || !Number.isFinite(r[k]))) {
      throw new Error("البيانات المالية غير صالحة.");
    }
    const when = Date.parse(r.last_closed_candle_utc);
    if (!Number.isFinite(when) || when > Date.now() + 120000) {
      throw new Error("تاريخ التقرير غير صالح.");
    }
    return when;
  }

  function markFreshness() {
    const pill = $("feedStatus");
    pill.classList.remove("fresh", "error");
    if (!state.report) {
      setText("feedText", "بانتظار البيانات");
      return;
    }
    const age = Date.now() - Date.parse(state.report.last_closed_candle_utc);
    if (age >= 0 && age < 45 * 60 * 1000) {
      pill.classList.add("fresh");
      setText("feedText", "بيانات حديثة");
    } else {
      setText("feedText", "بيانات قديمة");
    }
    setText("ageText", age >= 0 ? "آخر شمعة أُغلقت منذ " + Math.max(0, Math.floor(age / 60000)) + " دقيقة" : "وقت آخر شمعة");
  }

  function renderReport(r) {
    state.report = r;
    setText("headlinePrice", money(r.close_usd));
    setText("closeTime", fmtTime(Date.parse(r.last_closed_candle_utc)));
    setText("updatedTime", fmtTime(Date.parse(r.generated_at_utc)));
    setText("rsiValue", number(r.rsi14));
    setText("atrValue", money(r.atr14_usd));
    setText("ema9", money(r.ema9));
    setText("ema9b", money(r.ema9));
    setText("ema21", money(r.ema21));
    setText("ema21b", money(r.ema21));
    setText("ema50", money(r.ema50));
    setText("supportValue", money(r.support_20_prior_candles));
    setText("resistanceValue", money(r.resistance_20_prior_candles));
    $("rsiMeter").style.width = Math.max(0, Math.min(100, r.rsi14)) + "%";
    setText("strategySignal", r.existing_atlas_strategy_signal === "LONG" ? "إشارة صعود للمراقبة"
      : r.existing_atlas_strategy_signal === "SHORT" ? "إشارة هبوط للمراقبة" : "لا توجد إشارة");
    const bullish = r.trend === "BULLISH";
    const bearish = r.trend === "BEARISH";
    setText("marketTrend", bullish ? "اتجاه صاعد" : bearish ? "اتجاه هابط" : "سوق متذبذب");
    setText("trendGlyph", bullish ? "↗" : bearish ? "↘" : "↔");
    $("trendGlyph").className = "trend-glyph" + (bearish ? " down" : !bullish ? " wait" : "");
    setText("trendExplain", "استنتاج آلي من متوسطات EMA9 وEMA21 وEMA50، وليس توقعاً مؤكداً.");
    markFreshness();
  }

  function parseCandles(payload) {
    if (!payload || payload.exchange !== "Hyperliquid" || payload.market !== "BTC perpetual" ||
        payload.interval !== "15m" || !Array.isArray(payload.candles)) return [];
    const rows = payload.candles.map(row => ({
      t: Number(row.t), c: Number(row.c)
    })).filter(row => Number.isFinite(row.t) && row.t > 0 && Number.isFinite(row.c) && row.c > 0);
    rows.sort((a, b) => a.t - b.t);
    return rows.filter((row, idx) => idx === 0 || row.t > rows[idx-1].t);
  }

  function svgNode(name, attrs = {}) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
    return el;
  }

  function renderChart() {
    const svg = $("priceChart");
    const empty = $("chartEmpty");
    const all = state.candles;
    const count = state.range === "1h" ? 5 : state.range === "4h" ? 17 : 97;
    const pts = all.slice(-count);
    if (pts.length < 3) {
      svg.replaceChildren();
      empty.hidden = false;
      setText("percentChange", "—");
      setText("rangeLabel", "بانتظار ملف الشموع من ATLAS");
      return;
    }
    empty.hidden = true;
    const first = pts[0].c;
    const last = pts[pts.length - 1].c;
    const change = (last / first - 1) * 100;
    const changeEl = $("percentChange");
    changeEl.className = "change" + (change < 0 ? " negative" : change === 0 ? " neutral" : "");
    changeEl.textContent = (change > 0 ? "+" : "") + number(change) + "%";
    const caption = state.range === "1h" ? "ساعة" : state.range === "4h" ? "4 ساعات" : "24 ساعة";
    setText("rangeLabel", "تغير السعر خلال " + caption + " من شموع 15 دقيقة");
    setText("axisStart", new Intl.DateTimeFormat("ar-MA", {hour:"2-digit", minute:"2-digit"}).format(new Date(pts[0].t)));
    setText("axisEnd", new Intl.DateTimeFormat("ar-MA", {hour:"2-digit", minute:"2-digit"}).format(new Date(pts[pts.length - 1].t)));
    svg.replaceChildren();
    const W = 800, H = 230, PAD = 23;
    const prices = pts.map(p => p.c);
    const baseMin = Math.min(...prices), baseMax = Math.max(...prices);
    const margin = Math.max((baseMax - baseMin) * .16, baseMax * .0003);
    const min = baseMin - margin, max = baseMax + margin;
    const x = i => (i / (pts.length - 1)) * W;
    const y = val => PAD + (max - val) / (max - min) * (H - PAD * 2);
    const coords = pts.map((p, i) => [x(i), y(p.c)]);
    const line = "M" + coords.map(c => c.map(n => n.toFixed(2)).join(",")).join(" L");
    const isUp = last >= first;
    const stroke = isUp ? "#44e0c1" : "#ff8090";
    const gradName = isUp ? "atlasUp" : "atlasDown";
    const defs = svgNode("defs"), grad = svgNode("linearGradient", {id:gradName, x1:"0", x2:"0", y1:"0", y2:"1"});
    grad.append(svgNode("stop", {offset:"0%", "stop-color":stroke, "stop-opacity":".27"}),
                svgNode("stop", {offset:"100%", "stop-color":stroke, "stop-opacity":"0"}));
    defs.append(grad); svg.append(defs);
    for (let i = 1; i <= 3; i++) {
      svg.append(svgNode("line", {x1:0, x2:W, y1:(H/4)*i, y2:(H/4)*i,
        stroke:"#2a405a", "stroke-width":1, "stroke-dasharray":"5 6"}));
    }
    svg.append(svgNode("path", {d:line + " L" + W + "," + H + " L0," + H + " Z",
      fill:"url(#" + gradName + ")"}));
    svg.append(svgNode("path", {d:line, stroke, fill:"none", "stroke-width":2.9,
      "stroke-linecap":"round", "stroke-linejoin":"round"}));
    svg.append(svgNode("circle", {cx:x(pts.length - 1), cy:y(last), r:5,
      fill:stroke, stroke:"#101d31", "stroke-width":3}));
    const indicator = svgNode("line", {x1:0, x2:0, y1:6, y2:H-6, stroke:"#8dbff4",
      "stroke-width":1.3, "stroke-dasharray":"4 6",visibility:"hidden"});
    svg.append(indicator);
    const tooltip = $("chartTooltip");
    const onPointer = ev => {
      const rect = svg.getBoundingClientRect();
      const px = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      const index = Math.min(pts.length-1, Math.max(0, Math.round(px * (pts.length-1))));
      const p = pts[index];
      indicator.setAttribute("x1", x(index));
      indicator.setAttribute("x2", x(index));
      indicator.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      tooltip.textContent = money(p.c) + " · " + new Intl.DateTimeFormat("ar-MA", {
        hour:"2-digit", minute:"2-digit"
      }).format(new Date(p.t));
    };
    svg.onpointermove = onPointer;
    svg.onpointerdown = onPointer;
    svg.onpointerleave = () => { indicator.setAttribute("visibility","hidden");tooltip.hidden = true; };
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    $("refreshBtn").classList.add("rotate");
    $("refreshBtn").disabled = true;
    $("errorBanner").hidden = true;
    try {
      const cache = "?t=" + Date.now();
      const resp = await fetch(reportPath + cache, {cache:"no-store"});
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const r = await resp.json();
      checkReport(r);
      renderReport(r);
      try {
        const chartResp = await fetch(candlesPath + cache, {cache:"no-store"});
        if (!chartResp.ok) throw new Error("Candles unavailable");
        const chart = parseCandles(await chartResp.json());
        const lastTime = chart.length ? chart[chart.length - 1].t : 0;
        const reportTime = Date.parse(r.last_closed_candle_utc);
        state.candles = Math.abs(lastTime - reportTime) < 50 * 60 * 1000 ? chart : [];
      } catch {
        state.candles = [];
      }
      renderChart();
    } catch (error) {
      $("errorBanner").hidden = false;
      $("errorBanner").textContent = "تعذّر تحميل تقرير Hyperliquid. تأكد أن GitHub Pages منشور وأن ملف البيانات موجود، ثم اضغط تحديث.";
      if (!state.report) {
        $("feedStatus").classList.add("error");
        setText("feedText", "لا توجد بيانات");
      }
      console.error("ATLAS public feed:", error);
    } finally {
      state.loading = false;
      $("refreshBtn").classList.remove("rotate");
      $("refreshBtn").disabled = false;
    }
  }

  document.querySelectorAll(".range-btn").forEach(button => {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      document.querySelectorAll(".range-btn").forEach(b => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-pressed", String(b === button));
      });
      renderChart();
    });
  });
  $("refreshBtn").addEventListener("click", refresh);
  refresh();
  window.setInterval(() => { markFreshness(); if (!document.hidden) refresh(); }, 120000);
})();
