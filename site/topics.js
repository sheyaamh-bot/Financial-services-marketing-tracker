// Topics & search: tracked topics (collected daily as their own news searches) and a
// free-text search across everything collected in the last 90 days.
// Links: #topics?topic=Retirement&days=30  or  #topics?q=two-pot&days=90
window.Topics = (() => {
  let st = { topic: "", days: 30, sector: "All", q: "" };
  let charts = [], searchData = null, searchCharts = [], built = false;
  const T = () => D.topics;
  const el = () => $("#topicsView");

  function show(params){
    const t = params.get("topic"), q = params.get("q"), days = +params.get("days");
    if ([7, 30, 90].includes(days)) st.days = days;
    if (t && T().topics.some(x => x.name === t)) st.topic = t;
    if (q !== null) st.q = q;
    if (!st.topic) st.topic = ranked()[0]?.name || "";
    buildShell();
    if (st.q) runSearch(); else renderSearchEmpty();
    renderTopics();
  }

  function syncUrl(){
    const p = new URLSearchParams({ days: st.days });
    if (st.q) p.set("q", st.q); else p.set("topic", st.topic);
    history.replaceState(null, "", "#topics?" + p.toString());
  }

  const n = () => T().days.length;
  const inPeriod = d => d >= n() - st.days;
  const inPrev = d => d >= n() - 2 * st.days && d < n() - st.days;
  const hasPrev = () => 2 * st.days <= n();

  function ranked(){
    return T().topics.map(t => ({ ...t, count: t.news.filter(e => inPeriod(e[0])).length }))
      .sort((a, z) => z.count - a.count);
  }

  function buildShell(){
    el().innerHTML = `
      <section class="card" style="margin-bottom:16px" aria-label="Search coverage">
        <div class="row-head">
          <div><h2>Search all coverage</h2>
          <p class="sub" style="margin:0">Searches every headline collected (South African media, Reuters and the FT) in the last 90 days, for tracked brands and topics. Separate words with commas to find any of them.</p></div>
          <div class="seg" role="group" aria-label="Period">
            ${[7, 30, 90].map(d => `<button type="button" data-tdays="${d}" aria-pressed="${d === st.days}">${d} days</button>`).join("")}
          </div>
        </div>
        <form class="searchbar" id="tSearch" role="search" style="margin-top:12px">
          <input type="search" id="tQ" placeholder="For example: retirement, tax-free savings, fire risk" aria-label="Search headlines" value="${esc(st.q)}">
          <button class="btn2 primary" type="submit">Search</button>
          ${st.q ? '<button class="btn2" type="button" id="tClearQ">Clear</button>' : ""}
        </form>
        <div id="tResults" style="margin-top:14px"></div>
      </section>

      <section class="card" style="margin-bottom:16px">
        <div class="row-head">
          <div><h2>Tracked topics</h2><p class="sub" style="margin:0">Articles per topic in the last <span id="tDaysTxt">${st.days}</span> days. Choose a topic to see who owns the conversation.</p></div>
          <label class="field">Sector
            <select id="tSector"><option value="All">All</option><option value="Wealth">Wealth</option><option value="Insure">Insurance</option></select></label>
        </div>
        <div class="topic-grid" id="tGrid" style="margin-top:14px"></div>
      </section>
      <div id="tDetail"></div>`;
    $("#tSector").value = st.sector;
    $("#tSector").onchange = e => { st.sector = e.target.value; renderTopics(); };
    document.querySelectorAll("[data-tdays]").forEach(b => b.onclick = () => {
      st.days = +b.dataset.tdays;
      document.querySelectorAll("[data-tdays]").forEach(x => x.setAttribute("aria-pressed", x === b));
      $("#tDaysTxt").textContent = st.days;
      syncUrl(); renderTopics(); if (st.q) runSearch();
    });
    $("#tSearch").onsubmit = e => { e.preventDefault(); st.q = $("#tQ").value.trim(); syncUrl(); buildShell(); st.q ? runSearch() : renderSearchEmpty(); renderTopics(); };
    if ($("#tClearQ")) $("#tClearQ").onclick = () => { st.q = ""; syncUrl(); buildShell(); renderSearchEmpty(); renderTopics(); };
    built = true;
  }

  // ---- topics ------------------------------------------------------------
  function renderTopics(){
    const cols = entityColours(), list = ranked().filter(t => st.sector === "All" || t.sector === st.sector);
    if (!list.some(t => t.name === st.topic) && list.length) st.topic = list[0].name;
    const bk = buckets(T().days, 90); // weekly sparkline across the full 90 days
    $("#tGrid").innerHTML = list.map(t => {
      const prev = hasPrev() ? t.news.filter(e => inPrev(e[0])).length : null;
      const weekly = bk.map(b => t.news.filter(e => e[0] >= b.from && e[0] < b.to).length);
      return `<button type="button" class="topic-card" data-topic="${esc(t.name)}" aria-pressed="${t.name === st.topic}">
        <div class="row-head"><span class="t-name">${esc(t.name)}</span><span class="pill">${t.sector === "Insure" ? "Insurance" : "Wealth"}</span></div>
        <div class="t-num">${fmt(t.count)}</div>
        <div class="hint">${prev === null ? "articles" : changeHtml(pctChange(t.count, prev)) + " on previous period"}</div>
        ${sparkline(weekly, cols[0])}
      </button>`;
    }).join("") || '<p class="empty">No topics for this sector. Add some to config.json.</p>';
    $("#tGrid").querySelectorAll("[data-topic]").forEach(b => b.onclick = () => {
      st.topic = b.dataset.topic;
      if (st.q){ st.q = ""; $("#tQ").value = ""; renderSearchEmpty(); }
      syncUrl();
      $("#tGrid").querySelectorAll("[data-topic]").forEach(x => x.setAttribute("aria-pressed", x === b));
      renderDetail(); $("#tDetail").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    renderDetail();
  }

  function renderDetail(){
    charts.forEach(c => c.destroy()); charts = [];
    const t = T().topics.find(x => x.name === st.topic);
    if (!t){ $("#tDetail").innerHTML = ""; return; }
    const brands = T().brands, sources = T().sources;
    const news = t.news.filter(e => inPeriod(e[0]));
    const hits = t.brand_hits.filter(e => inPeriod(e[0]));
    const byBrand = {};
    hits.forEach(([, b]) => byBrand[brands[b].name] = (byBrand[brands[b].name] || 0) + 1);
    const brandRows = Object.entries(byBrand).sort((a, z) => z[1] - a[1]);
    const totalHits = hits.length || 1;
    const byOutlet = {};
    news.forEach(([, s]) => byOutlet[sources[s]] = (byOutlet[sources[s]] || 0) + 1);
    const outletRows = Object.entries(byOutlet).sort((a, z) => z[1] - a[1]).slice(0, 8);
    const heads = [...t.headlines, ...t.brand_headlines].filter(h => inPeriod(h.d)).sort((a, z) => z.d - a.d).slice(0, 30);
    const leader = brandRows[0];

    $("#tDetail").innerHTML = `
      <section class="card" style="margin-bottom:16px">
        <div class="row-head">
          <div><h2 class="rep-title">${esc(t.name)}</h2>
            <div class="rep-meta">${t.sector === "Insure" ? "Insurance" : "Wealth"} · last ${st.days} days · matched on: ${t.keywords.map(k => esc(k.trim())).join(", ")}</div></div>
          <div class="btnrow"><button class="btn2" type="button" id="tLink">Copy link</button></div>
        </div>
        <div class="grid g-kpi" style="margin-top:14px">
          <div class="card kpi"><div class="label">Articles</div><div class="value">${fmt(news.length)}</div><div class="delta">${hasPrev() ? changeHtml(pctChange(news.length, t.news.filter(e => inPrev(e[0])).length)) + " on previous period" : "last " + st.days + " days"}</div></div>
          <div class="card kpi"><div class="label">Brand mentions</div><div class="value">${fmt(hits.length)}</div><div class="delta">tracked brands linked to this topic</div></div>
          <div class="card kpi"><div class="label">Owns the conversation</div><div class="value">${leader ? esc(leader[0]) : "–"}</div><div class="delta">${leader ? Math.round(100 * leader[1] / totalHits) + "% of brand mentions" : "no brand mentions yet"}</div></div>
          <div class="card kpi"><div class="label">Top outlet</div><div class="value">${outletRows[0] ? esc(outletRows[0][0]) : "–"}</div><div class="delta">${outletRows[0] ? outletRows[0][1] + " articles" : ""}</div></div>
        </div>
      </section>
      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Volume over time</h2><p class="sub">${st.days > 31 ? "Articles per week" : "Articles per day"}</p>
          <div class="chart-box"><canvas id="tTrend" role="img" aria-label="Topic volume over time"></canvas></div></div>
        <div class="card"><h2>Brands in the conversation</h2><p class="sub">Share of brand mentions linked to this topic</p>
          ${brandRows.length ? `<div class="chart-box" style="height:${Math.max(160, 30 * Math.min(12, brandRows.length) + 40)}px"><canvas id="tBrands" role="img" aria-label="Brands in this topic"></canvas></div>` : '<p class="empty">No tracked brand has been linked to this topic in this period.</p>'}</div>
      </section>
      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Latest headlines</h2><p class="sub">Topic articles and tracked-brand stories that mention it</p>
          <div class="feed">${heads.length ? heads.map(h => `<div class="item"><a href="${esc(h.link)}" target="_blank" rel="noopener">${esc(h.title)}</a>
            <div class="meta">${esc(h.source)} · ${shortDate(T().days[h.d])}${h.brands.length ? " · " + h.brands.map(b => `<strong>${esc(b)}</strong>`).join(", ") : ""}</div></div>`).join("") : '<p class="empty">No headlines in this period.</p>'}</div></div>
        <div class="card"><h2>Top outlets for this topic</h2><p class="sub">Where the conversation happens</p>
          ${outletRows.length ? `<div class="table-wrap"><table><thead><tr><th>Outlet</th><th class="num">Articles</th></tr></thead><tbody>
            ${outletRows.map(([o, c]) => `<tr><td>${esc(o)}</td><td class="num">${c}</td></tr>`).join("")}</tbody></table></div>` : '<p class="empty">No articles in this period.</p>'}</div>
      </section>`;
    $("#tLink").onclick = e => copyLink(e.currentTarget);

    const base = chartBase(), grid = css("--grid"), accent = entityColours()[0];
    const bk = buckets(T().days, st.days);
    charts.push(new Chart($("#tTrend"), {
      type: "line",
      data: { labels: bk.map(b => b.label), datasets: [{ label: t.name, data: bk.map(b => news.filter(e => e[0] >= b.from && e[0] < b.to).length),
        borderColor: accent, backgroundColor: accent, borderWidth: 2, pointRadius: st.days > 31 ? 3 : 0, pointHoverRadius: 5, cubicInterpolationMode: "monotone" }] },
      options: { ...base, interaction: { mode: "index", intersect: false }, plugins: { legend: { display: false }, tooltip: tooltipBase() },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: { precision: 0 } } } }
    }));
    if (brandRows.length){
      const top = brandRows.slice(0, 12), shares = top.map(([, c]) => Math.round(1000 * c / totalHits) / 10);
      charts.push(new Chart($("#tBrands"), {
        type: "bar",
        data: { labels: top.map(([b]) => b), datasets: [{ data: shares, backgroundColor: accent, borderRadius: 4, borderSkipped: "start", barThickness: 14 }] },
        plugins: [barLabels],
        options: { ...base, indexAxis: "y", layout: { padding: { right: 40 } },
          scales: { x: { max: Math.min(100, Math.ceil((Math.max(...shares) + 5) / 10) * 10), grid: { color: grid }, border: { display: false }, ticks: { callback: v => v + "%" } },
                    y: { grid: { display: false }, border: { display: false }, ticks: { color: css("--ink-2") } } },
          plugins: { legend: { display: false }, tooltip: { ...tooltipBase(), displayColors: false, callbacks: { label: x => `${shares[x.dataIndex]}% · ${top[x.dataIndex][1]} mentions` } } } }
      }));
    }
  }

  // ---- search ------------------------------------------------------------
  function renderSearchEmpty(){
    $("#tResults").innerHTML = `<div class="btnrow">${T().topics.slice(0, 6).map(t => `<button class="btn2" type="button" data-try="${esc(t.keywords[0].trim())}">${esc(t.keywords[0].trim())}</button>`).join("")}</div>`;
    $("#tResults").querySelectorAll("[data-try]").forEach(b => b.onclick = () => { st.q = b.dataset.try; syncUrl(); buildShell(); runSearch(); renderTopics(); });
  }

  async function runSearch(){
    searchCharts.forEach(c => c.destroy()); searchCharts = [];
    $("#tResults").innerHTML = '<p class="hint">Searching…</p>';
    try {
      if (!searchData) searchData = await fetch("search.json", { cache: "no-store" }).then(r => r.json());
    } catch (e) { $("#tResults").innerHTML = '<p class="empty">Search isn\'t available right now.</p>'; return; }
    const terms = st.q.toLowerCase().split(",").map(s => s.trim()).filter(Boolean);
    if (!terms.length){ renderSearchEmpty(); return; }
    const N = searchData.days.length, start = N - st.days;
    const rows = searchData.rows.filter(r => r[0] >= start && terms.some(t => r[1].toLowerCase().includes(t)));
    const byBrand = {};
    rows.forEach(r => { if (r[3]) byBrand[r[3]] = (byBrand[r[3]] || 0) + 1; });
    const brandRows = Object.entries(byBrand).sort((a, z) => z[1] - a[1]).slice(0, 10);
    const re = new RegExp("(" + terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "ig");
    const hl = s => esc(s).replace(re, "<mark>$1</mark>");

    $("#tResults").innerHTML = `
      <p style="margin:0 0 12px"><strong>${fmt(rows.length)}</strong> headline${rows.length === 1 ? "" : "s"} matching “${esc(st.q)}” in the last ${st.days} days.</p>
      ${rows.length ? `<div class="grid g-2">
        <div><h3 style="margin:0 0 6px;font-size:14px">Which tracked brands are linked to it</h3>
          ${brandRows.length ? `<div class="chart-box" style="height:${Math.max(140, 28 * brandRows.length + 40)}px"><canvas id="sBrands" role="img" aria-label="Brands in search results"></canvas></div>` : '<p class="hint">None of the matching headlines name a tracked brand.</p>'}</div>
        <div><h3 style="margin:0 0 6px;font-size:14px">Matching headlines</h3>
          <div class="feed" style="max-height:380px">${rows.slice(0, 100).map(r => `<div class="item"><a href="${esc(r[6])}" target="_blank" rel="noopener">${hl(r[1])}</a>
            <div class="meta">${esc(r[2])} · ${shortDate(searchData.days[r[0]])}${r[3] ? " · <strong>" + esc(r[3]) + "</strong>" : ""}${r[5] ? " · topic: " + esc(r[5]) : ""}</div></div>`).join("")}</div>
          ${rows.length > 100 ? `<p class="hint">Showing the newest 100.</p>` : ""}</div>
      </div>` : '<p class="empty">Nothing matched. Try a shorter word, or add it as a tracked topic in config.json so it is collected every morning.</p>'}`;
    if (brandRows.length){
      const accent = entityColours()[0];
      searchCharts.push(new Chart($("#sBrands"), {
        type: "bar",
        data: { labels: brandRows.map(([b]) => b), datasets: [{ data: brandRows.map(([, c]) => c), backgroundColor: accent, borderRadius: 4, borderSkipped: "start", barThickness: 14 }] },
        options: { ...chartBase(), indexAxis: "y",
          scales: { x: { beginAtZero: true, grid: { color: css("--grid") }, border: { display: false }, ticks: { precision: 0 } }, y: { grid: { display: false }, border: { display: false }, ticks: { color: css("--ink-2") } } },
          plugins: { legend: { display: false }, tooltip: { ...tooltipBase(), displayColors: false, callbacks: { label: x => `${brandRows[x.dataIndex][1]} headlines` } } } }
      }));
    }
  }

  function redraw(){ if (!built) return; renderTopics(); if (st.q) runSearch(); }
  return { show, redraw };
})();
