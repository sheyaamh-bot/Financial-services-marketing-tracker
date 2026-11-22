// Competitor report: pick your brand, up to six competitors and a period, then read,
// print (PDF) or download (Excel) a head-to-head analysis. The selection lives in the
// URL (#report?sector=wealth&you=...&vs=...&days=30), so a report can be shared as a link.
window.Report = (() => {
  const MAX_VS = 6;
  const el = () => $("#reportView");
  let st = { sector: "Wealth", you: "", vs: [], days: 30 };
  let charts = [];
  let built = false, last = null;

  const seg = () => D.segments[st.sector];
  const brands = () => seg().metrics.brands;

  function show(params){
    const sector = (params.get("sector") || "").toLowerCase() === "insurance" ? "Insure"
                 : (params.get("sector") || "").toLowerCase() === "wealth" ? "Wealth" : st.sector;
    st.sector = sector;
    const all = brands();
    const you = params.get("you");
    st.you = all.includes(you) ? you : (all.includes(st.you) ? st.you : "");
    const vs = (params.get("vs") || "").split("|").filter(b => all.includes(b) && b !== st.you);
    if (vs.length) st.vs = vs.slice(0, MAX_VS);
    else st.vs = st.vs.filter(b => all.includes(b) && b !== st.you);
    const days = +params.get("days");
    if ([7, 30, 90].includes(days)) st.days = days;
    if (!st.you){ // sensible starting point so the page is never empty
      const ranked = seg().metrics.share_of_voice_30d.map(r => r.brand);
      st.you = ranked[0]; st.vs = ranked.slice(1, 4);
    }
    buildShell();
    update(false);
  }

  function syncUrl(){
    const p = new URLSearchParams({ sector: SECTOR[st.sector], you: st.you, vs: st.vs.join("|"), days: st.days });
    history.replaceState(null, "", "#report?" + p.toString());
  }

  function buildShell(){
    el().innerHTML = `
      <section class="card controls no-print" style="margin-bottom:16px" aria-label="Report settings">
        <div class="row-head">
          <div><h2>Build a competitor report</h2>
          <p class="sub" style="margin:0">Choose your brand and up to ${MAX_VS} competitors to see how you're tracking against them.</p></div>
          <div class="btnrow">
            <button class="btn2 primary" type="button" id="rPdf">Download PDF</button>
            <button class="btn2" type="button" id="rXlsx">Download Excel</button>
            <button class="btn2" type="button" id="rLink">Copy link</button>
          </div>
        </div>
        <div class="ctrl-row">
          <label class="field">Sector
            <select id="rSector"><option value="Wealth">Wealth</option><option value="Insure">Insurance</option></select></label>
          <label class="field">Your brand <select id="rYou"></select></label>
          <div class="field">Period
            <div class="seg" role="group" aria-label="Period">
              ${[7, 30, 90].map(d => `<button type="button" data-rdays="${d}" aria-pressed="${d === st.days}">${d} days</button>`).join("")}
            </div></div>
        </div>
        <div class="field">Competitors <span class="hint" id="rCount"></span>
          <div class="chips" id="rChips" role="group" aria-label="Competitors"></div>
          <div class="btnrow" style="margin-top:6px">
            <button class="btn2" type="button" id="rTop">Top 3 by share of voice</button>
            <button class="btn2" type="button" id="rClear">Clear</button>
          </div>
        </div>
      </section>
      <div id="rBody"></div>`;
    $("#rSector").value = st.sector;
    $("#rSector").onchange = e => {
      st.sector = e.target.value;
      const ranked = seg().metrics.share_of_voice_30d.map(r => r.brand);
      st.you = ranked[0]; st.vs = ranked.slice(1, 4);
      buildShell(); update();
    };
    $("#rYou").innerHTML = brands().map(b => `<option ${b === st.you ? "selected" : ""}>${esc(b)}</option>`).join("");
    $("#rYou").onchange = e => { st.you = e.target.value; st.vs = st.vs.filter(b => b !== st.you); renderChips(); update(); };
    document.querySelectorAll("[data-rdays]").forEach(b => b.onclick = () => {
      st.days = +b.dataset.rdays;
      document.querySelectorAll("[data-rdays]").forEach(x => x.setAttribute("aria-pressed", x === b));
      update();
    });
    $("#rTop").onclick = () => {
      st.vs = rankAll().filter(b => b !== st.you).slice(0, 3); renderChips(); update();
    };
    $("#rClear").onclick = () => { st.vs = []; renderChips(); update(); };
    $("#rPdf").onclick = () => window.print();
    $("#rXlsx").onclick = downloadExcel;
    $("#rLink").onclick = e => copyLink(e.currentTarget);
    renderChips();
    built = true;
  }

  function renderChips(){
    const cols = entityColours();
    const opts = brands().filter(b => b !== st.you);
    $("#rChips").innerHTML = opts.map(b => {
      const i = st.vs.indexOf(b), on = i >= 0;
      return `<label class="chip"><input type="checkbox" value="${esc(b)}" ${on ? "checked" : ""} ${!on && st.vs.length >= MAX_VS ? "disabled" : ""}>
        <span><i style="background:${on ? cols[i + 1] : "var(--neu)"}"></i>${esc(b)}</span></label>`;
    }).join("");
    $("#rChips").querySelectorAll("input").forEach(inp => inp.onchange = () => {
      if (inp.checked) st.vs.push(inp.value); else st.vs = st.vs.filter(b => b !== inp.value);
      renderChips(); update();
    });
    $("#rCount").textContent = `(${st.vs.length} of ${MAX_VS} chosen)`;
  }

  function rankAll(){
    const R = seg().report, start = R.days.length - st.days, all = brands(), n = all.map(() => 0);
    R.events.forEach(e => { if (e[0] >= start) n[e[1]]++; });
    return all.map((b, i) => [b, n[i]]).sort((a, z) => z[1] - a[1]).map(x => x[0]);
  }

  // ---- calculations ------------------------------------------------------
  function compute(){
    const R = seg().report, M = seg().metrics, all = M.brands, cats = M.categories;
    const group = [st.you, ...st.vs], gi = group.map(b => all.indexOf(b));
    const n = R.days.length, start = n - st.days, pstart = n - 2 * st.days, hasPrev = pstart >= 0;
    const per = group.map(() => ({ cur: 0, prev: 0, tone: [0, 0, 0], cats: cats.map(() => 0), outlets: {}, daily: new Array(n).fill(0) }));
    const idx = new Map(gi.map((g, k) => [g, k]));
    for (const [d, b, c, t, s] of R.events){
      const k = idx.get(b); if (k === undefined) continue;
      const P = per[k];
      if (d >= start){
        P.cur++; P.daily[d]++; P.cats[c]++;
        P.tone[t === 1 ? 0 : t === -1 ? 2 : 1]++;
        const src = R.sources[s]; P.outlets[src] = (P.outlets[src] || 0) + 1;
      } else if (hasPrev && d >= pstart) P.prev++;
    }
    const total = per.reduce((a, p) => a + p.cur, 0) || 1;
    const rows = group.map((b, k) => {
      const p = per[k], t = p.tone[0] + p.tone[1] + p.tone[2];
      const topCat = p.cur ? cats[p.cats.indexOf(Math.max(...p.cats))] : "–";
      const topOut = Object.entries(p.outlets).sort((a, z) => z[1] - a[1])[0];
      return { brand: b, you: k === 0, colour: k, mentions: p.cur, prev: p.prev,
        share: Math.round(1000 * p.cur / total) / 10, change: hasPrev ? pctChange(p.cur, p.prev) : null,
        tone: p.tone, net: t ? Math.round(100 * (p.tone[0] - p.tone[2]) / t) : 0,
        cats: p.cats, topCat, topOutlet: topOut ? `${topOut[0]} (${topOut[1]})` : "–",
        outlets: p.outlets, daily: p.daily };
    });
    const ranked = [...rows].sort((a, z) => z.mentions - a.mentions);

    // Outlet gaps: outlets covering competitors but not you.
    const you = rows[0], gaps = {}, strong = [];
    rows.slice(1).forEach(r => Object.entries(r.outlets).forEach(([o, c]) => {
      if (!you.outlets[o]){ (gaps[o] = gaps[o] || { outlet: o, total: 0, by: {} }); gaps[o].total += c; gaps[o].by[r.brand] = c; }
    }));
    const gapList = Object.values(gaps).sort((a, z) => z.total - a.total);
    Object.entries(you.outlets).forEach(([o, c]) => {
      const comp = rows.slice(1).reduce((a, r) => a + (r.outlets[o] || 0), 0);
      strong.push({ outlet: o, you: c, compAvg: rows.length > 1 ? Math.round(10 * comp / (rows.length - 1)) / 10 : 0 });
    });
    strong.sort((a, z) => z.you - a.you);

    // Activity mix as % of each brand's coverage.
    const mix = rows.map(r => r.cats.map(c => r.mentions ? Math.round(100 * c / r.mentions) : 0));

    return { R, cats, rows, ranked, gapList, strong, mix, hasPrev, start, n };
  }

  function summary(c){
    const { rows, ranked, cats, mix, gapList, hasPrev } = c;
    const you = rows[0], comps = rows.slice(1), rank = ranked.findIndex(r => r.you) + 1;
    const pts = [];
    pts.push(`${you.brand} had ${fmt(you.mentions)} news mentions in the last ${st.days} days: ${you.share}% of coverage across this group, ranking #${rank} of ${rows.length}.`);
    if (hasPrev){
      const ch = you.change;
      const grow = comps.filter(r => r.change !== null).sort((a, z) => z.change - a.change)[0];
      pts.push(`${ch === null ? "There is no earlier period to compare with yet." : `Your coverage is ${ch >= 0 ? "up" : "down"} ${Math.abs(ch)}% on the previous ${st.days} days.`}`
        + (grow ? ` ${grow.brand} grew fastest among your competitors (${grow.change >= 0 ? "+" : ""}${grow.change}%).` : ""));
    }
    if (ranked[0].you && ranked[1]) pts.push(`You lead this group, ${Math.round(10 * (ranked[0].share - ranked[1].share)) / 10} points ahead of ${ranked[1].brand}.`);
    else pts.push(`${ranked[0].brand} leads this group with ${ranked[0].share}%, ${Math.round(10 * (ranked[0].share - you.share)) / 10} points ahead of you.`);
    if (comps.length){
      const avgNet = Math.round(comps.reduce((a, r) => a + r.net, 0) / comps.length);
      pts.push(`Your net headline tone is ${you.net > 0 ? "+" : ""}${you.net}, against a competitor average of ${avgNet > 0 ? "+" : ""}${avgNet}.`);
      let best = null;
      cats.forEach((cat, i) => {
        if (cat === "Other coverage") return;
        const avg = comps.reduce((a, _, k) => a + mix[k + 1][i], 0) / comps.length;
        const gap = avg - mix[0][i];
        if (!best || gap > best.gap) best = { cat, gap, avg: Math.round(avg), you: mix[0][i] };
      });
      if (best && best.gap >= 3) pts.push(`Biggest activity gap: competitors put ${best.avg}% of their coverage into ${best.cat.toLowerCase()}, against ${best.you}% for you.`);
      if (gapList.length) pts.push(`${gapList.length} outlet${gapList.length > 1 ? "s" : ""} covered your competitors but not you, led by ${gapList[0].outlet} (${gapList[0].total} competitor mention${gapList[0].total > 1 ? "s" : ""}).`);
    }
    return pts;
  }

  // ---- rendering ---------------------------------------------------------
  function update(sync = true){
    if (sync) syncUrl();
    charts.forEach(ch => ch.destroy()); charts = [];
    if (!st.vs.length){
      $("#rBody").innerHTML = `<p class="empty">Choose at least one competitor to build the report.</p>`;
      last = null; return;
    }
    const c = last = compute();
    const cols = entityColours();
    const sw = r => `<span class="sw" style="background:${cols[r.colour]}"></span>`;
    const periodTxt = `Last ${st.days} days to ${longDate(c.R.days[c.n - 1])}`;
    const pts = summary(c);
    const startD = c.start;

    $("#rBody").innerHTML = `
      <section class="card summary" style="margin-bottom:16px">
        <div class="print-only hint" style="margin-bottom:6px">Financial Services Marketing Tracker · Competitor report</div>
        <h2 class="rep-title">${esc(st.you)} vs ${st.vs.length} competitor${st.vs.length > 1 ? "s" : ""}</h2>
        <div class="rep-meta">${st.sector === "Insure" ? "Insurance" : "Wealth"} · ${periodTxt} · Competitors: ${st.vs.map(esc).join(", ")}</div>
        <ul style="margin:12px 0 0;padding-left:20px">${pts.map(p => `<li>${esc(p)}</li>`).join("")}</ul>
        ${D.meta.demo ? '<p class="hint" style="margin:10px 0 0">Sample data. Figures are illustrative until the first live run.</p>' : ""}
      </section>

      <section class="card" style="margin-bottom:16px">
        <h2>Head to head</h2><p class="sub">Share is each brand's part of all coverage in this group</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Brand</th><th class="num">Mentions</th><th class="num">Share</th>${c.hasPrev ? `<th class="num">vs previous ${st.days} days</th>` : ""}<th class="num">Net tone</th><th>Top activity</th><th>Top outlet</th></tr></thead>
          <tbody>${c.ranked.map(r => `<tr class="${r.you ? "you" : ""}"><td>${sw(r)}${esc(r.brand)}${r.you ? ' <span class="pill">You</span>' : ""}</td>
            <td class="num">${fmt(r.mentions)}</td><td class="num">${r.share}%</td>${c.hasPrev ? `<td class="num">${changeHtml(r.change)}</td>` : ""}
            <td class="num">${r.net > 0 ? "+" : ""}${r.net}</td><td>${esc(r.topCat)}</td><td>${esc(r.topOutlet)}</td></tr>`).join("")}</tbody>
        </table></div>
        ${c.hasPrev ? "" : '<p class="hint" style="margin:8px 0 0">Change on the previous period is shown for 7- and 30-day reports.</p>'}
      </section>

      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Share of voice in this group</h2><p class="sub">${periodTxt}</p>
          <div class="chart-box" style="height:${Math.max(180, 44 * c.rows.length + 40)}px"><canvas id="rSov" role="img" aria-label="Share of voice within the chosen group"></canvas></div></div>
        <div class="card"><h2>Coverage over time</h2><p class="sub">${st.days > 31 ? "Mentions per week" : "Mentions per day"}</p>
          <div class="chart-box"><canvas id="rTrend" role="img" aria-label="Coverage over time for each brand"></canvas></div></div>
      </section>

      <section class="card" style="margin-bottom:16px">
        <h2>Activity mix</h2><p class="sub">Share of each brand's coverage by activity type. Darker means a bigger part of that brand's coverage.</p>
        <div class="table-wrap"><table class="heat" id="rMix"></table></div>
      </section>

      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Headline tone</h2><p class="sub">Keyword-based. A signal, not a verdict.</p>
          <div class="legend"><span><i style="background:var(--pos)"></i>Positive</span><span><i style="background:var(--neu)"></i>Neutral</span><span><i style="background:var(--neg)"></i>Negative</span></div>
          <div class="table-wrap"><table><thead><tr><th>Brand</th><th>Tone mix</th><th class="num">Net</th></tr></thead><tbody>
          ${c.rows.map(r => { const t = r.tone[0] + r.tone[1] + r.tone[2] || 1; return `<tr class="${r.you ? "you" : ""}"><td>${sw(r)}${esc(r.brand)}</td>
            <td><div class="stack" title="${r.tone[0]} positive · ${r.tone[1]} neutral · ${r.tone[2]} negative"><span style="width:${100 * r.tone[0] / t}%;background:var(--pos)"></span><span style="width:${100 * r.tone[1] / t}%;background:var(--neu)"></span><span style="width:${100 * r.tone[2] / t}%;background:var(--neg)"></span></div></td>
            <td class="num">${r.net > 0 ? "+" : ""}${r.net}</td></tr>`; }).join("")}
          </tbody></table></div></div>
        <div class="card"><h2>Outlet gaps</h2><p class="sub">Publications that covered your competitors but not ${esc(st.you)}. Useful PR targets.</p>
          ${c.gapList.length ? `<div class="table-wrap"><table><thead><tr><th>Outlet</th><th class="num">Competitor mentions</th><th>Who they covered</th></tr></thead><tbody>
            ${c.gapList.slice(0, 10).map(g => `<tr><td>${esc(g.outlet)}</td><td class="num">${g.total}</td><td>${Object.entries(g.by).sort((a, z) => z[1] - a[1]).map(([b, n]) => `${esc(b)} (${n})`).join(", ")}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="empty">No gaps: every outlet that covered a competitor also covered ${esc(st.you)}.</p>`}
          <h2 style="margin-top:20px">Your strongest outlets</h2><p class="sub">Where ${esc(st.you)} got the most coverage, against the competitor average</p>
          ${c.strong.length ? `<div class="table-wrap"><table><thead><tr><th>Outlet</th><th class="num">You</th><th class="num">Competitor average</th></tr></thead><tbody>
            ${c.strong.slice(0, 6).map(s => `<tr><td>${esc(s.outlet)}</td><td class="num">${s.you}</td><td class="num">${s.compAvg}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="empty">No coverage for ${esc(st.you)} in this period.</p>`}
        </div>
      </section>

      <section class="card" style="margin-bottom:16px">
        <h2>Latest competitor headlines</h2><p class="sub">Up to five recent stories per competitor in this period</p>
        <div class="grid g-2">${st.vs.map(b => {
          const r = c.rows.find(x => x.brand === b);
          const hs = (c.R.headlines[b] || []).filter(h => h.d >= startD).slice(0, 5);
          return `<div><h3 style="margin:4px 0 6px;font-size:14px">${sw(r)}${esc(b)}</h3>
            ${hs.length ? hs.map(h => `<div class="feed"><div class="item" style="padding:6px 0"><a href="${esc(h.link)}" target="_blank" rel="noopener">${esc(h.title)}</a>
              <div class="meta">${esc(h.source)} · ${shortDate(c.R.days[h.d])} · ${esc(h.category)}</div></div></div>`).join("") : '<p class="hint">No headlines in this period.</p>'}</div>`;
        }).join("")}</div>
      </section>
      <p class="hint print-only">Source: South African news coverage collected daily via Google News by the Financial Services Marketing Tracker. Mentions count news items, not reach or advertising value. Built by Sheyaam Hill using Claude Code.</p>`;

    renderMix(c);
    drawCharts(c);
  }

  function renderMix(c){
    const lo = css("--heat-0"), hi = css("--heat-1"), cols = entityColours();
    const max = Math.max(1, ...c.mix.flat());
    let h = `<thead><tr><th>Activity</th>${c.rows.map(r => `<th class="rot"><span class="sw" style="background:${cols[r.colour]}"></span>${esc(r.brand)}</th>`).join("")}</tr></thead><tbody>`;
    c.cats.forEach((cat, i) => {
      h += `<tr><td>${esc(cat)}</td>` + c.rows.map((r, k) => {
        const v = c.mix[k][i], t = v / max;
        return `<td class="cell" style="background:${mix(lo, hi, Math.pow(t, .8))};color:${t > .5 ? "#fff" : css("--ink")}" title="${esc(r.brand)} · ${esc(cat)}: ${r.cats[i]} items (${v}%)">${v ? v + "%" : ""}</td>`;
      }).join("") + "</tr>";
    });
    $("#rMix").innerHTML = h + "</tbody>";
  }

  function drawCharts(c){
    const cols = entityColours(), grid = css("--grid"), base = chartBase();
    const sorted = [...c.rows].sort((a, z) => z.share - a.share);
    charts.push(new Chart($("#rSov"), {
      type: "bar",
      data: { labels: sorted.map(r => r.brand), datasets: [{ data: sorted.map(r => r.share), backgroundColor: sorted.map(r => cols[r.colour]), borderRadius: 4, borderSkipped: "start", barThickness: 18 }] },
      plugins: [barLabels],
      options: { ...base, indexAxis: "y", layout: { padding: { right: 40 } },
        scales: { x: { max: Math.min(100, Math.ceil((Math.max(...sorted.map(r => r.share)) + 5) / 10) * 10), grid: { color: grid }, border: { display: false }, ticks: { callback: v => v + "%" } },
                  y: { grid: { display: false }, border: { display: false }, ticks: { color: css("--ink-2") } } },
        plugins: { legend: { display: false }, tooltip: { ...tooltipBase(), displayColors: false, callbacks: { label: x => `${sorted[x.dataIndex].share}% · ${fmt(sorted[x.dataIndex].mentions)} mentions` } } } }
    }));
    const bk = buckets(c.R.days, st.days);
    charts.push(new Chart($("#rTrend"), {
      type: "line",
      data: { labels: bk.map(b => b.label), datasets: c.rows.map(r => ({
        label: r.brand, data: bk.map(b => r.daily.slice(b.from, b.to).reduce((a, v) => a + v, 0)),
        borderColor: cols[r.colour], backgroundColor: cols[r.colour], borderWidth: r.you ? 3 : 2,
        pointRadius: st.days > 31 ? 3 : 0, pointHoverRadius: 5, cubicInterpolationMode: "monotone" })) },
      options: { ...base, interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 3, color: css("--ink-2") } }, tooltip: tooltipBase() },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: { precision: 0 } } } }
    }));
  }

  async function downloadExcel(){
    if (!last) return;
    const btn = $("#rXlsx"), label = btn.textContent;
    btn.textContent = "Preparing…";
    try {
      const XLSX = await loadXLSX(), c = last, wb = XLSX.utils.book_new();
      const period = `Last ${st.days} days to ${longDate(c.R.days[c.n - 1])}`;
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        ["Competitor report: " + st.you + " vs " + st.vs.join(", ")],
        ["Sector", st.sector === "Insure" ? "Insurance" : "Wealth"], ["Period", period],
        ["Generated", longDate(new Date().toISOString())], ["Link", location.href], [],
        ["Summary"], ...summary(c).map(p => ["• " + p]), [],
        [D.meta.demo ? "Sample data: figures are illustrative." : "Source: South African news coverage collected daily via Google News. Mentions count news items, not reach or advertising value."],
      ], [110, 40]), "Summary");
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        ["Brand", "You?", "Mentions", "Share of group (%)", `Previous ${st.days} days`, "Change (%)", "Positive", "Neutral", "Negative", "Net tone", "Top activity", "Top outlet"],
        ...c.ranked.map(r => [r.brand, r.you ? "Yes" : "", r.mentions, r.share, c.hasPrev ? r.prev : "", r.change ?? "", r.tone[0], r.tone[1], r.tone[2], r.net, r.topCat, r.topOutlet]),
      ], [20, 6, 10, 16, 16, 11, 9, 9, 9, 9, 28, 28]), "Head to head");
      const bk = buckets(c.R.days, st.days);
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        [st.days > 31 ? "Week" : "Date", ...c.rows.map(r => r.brand)],
        ...bk.map(b => [b.label, ...c.rows.map(r => r.daily.slice(b.from, b.to).reduce((a, v) => a + v, 0))]),
      ], [16, ...c.rows.map(() => 16)]), "Coverage over time");
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        ["Activity", ...c.rows.map(r => r.brand + " (items)"), ...c.rows.map(r => r.brand + " (%)")],
        ...c.cats.map((cat, i) => [cat, ...c.rows.map(r => r.cats[i]), ...c.rows.map((_, k) => c.mix[k][i])]),
      ], [30, ...c.rows.flatMap(() => [16, 16])]), "Activity mix");
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        ["Outlet", "Competitor mentions", "Who they covered"],
        ...c.gapList.map(g => [g.outlet, g.total, Object.entries(g.by).map(([b, n]) => `${b} (${n})`).join(", ")]),
        [], ["Your strongest outlets"], ["Outlet", "You", "Competitor average"],
        ...c.strong.map(s => [s.outlet, s.you, s.compAvg]),
      ], [28, 20, 60]), "Outlet gaps");
      XLSX.utils.book_append_sheet(wb, sheetFromRows(XLSX, [
        ["Brand", "Date", "Headline", "Outlet", "Category", "Link"],
        ...c.rows.flatMap(r => (c.R.headlines[r.brand] || []).filter(h => h.d >= c.start)
          .map(h => [r.brand, c.R.days[h.d], h.title, h.source, h.category, h.link])),
      ], [18, 12, 70, 22, 28, 50]), "Headlines");
      const safe = s => s.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "");
      XLSX.writeFile(wb, `Competitor_report_${safe(st.you)}_${st.days}d_${c.R.days[c.n - 1]}.xlsx`);
    } catch (e) {
      alert("Sorry, the Excel download didn't work. " + e.message);
    } finally { btn.textContent = label; }
  }

  function redraw(){ if (built && last) update(false); }
  window.addEventListener("beforeprint", () => charts.forEach(ch => ch.resize()));
  window.addEventListener("afterprint", () => charts.forEach(ch => ch.resize()));
  return { show, redraw };
})();
