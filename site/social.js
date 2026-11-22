// Social media view: YouTube and Instagram (collected daily), LinkedIn (monthly log),
// and one-click links to each brand's live Facebook and Instagram ads.
window.Social = (() => {
  let st = { sector: "Wealth", sort: "instagram" };
  let charts = [], built = false;
  const el = () => $("#socialView");
  const SM = () => D.social_media || { brands: {} };
  const rows = () => Object.values(SM().brands).filter(b => b.sector === st.sector);
  const n = v => v === null || v === undefined ? null : v;
  const num = v => v === null || v === undefined ? '<span class="hint">–</span>' : fmt(v);
  const chg = v => v === null || v === undefined ? "" : ` <span class="${v > 0 ? "up" : v < 0 ? "down" : "hint"}">${v > 0 ? "+" : ""}${fmt(v)}</span>`;

  function show(params){
    const s = (params.get("sector") || "").toLowerCase();
    if (s === "insurance") st.sector = "Insure"; else if (s === "wealth") st.sector = "Wealth";
    build();
  }
  function syncUrl(){ history.replaceState(null, "", "#social?sector=" + SECTOR[st.sector]); }

  function statusHtml(){
    const sm = SM(), yt = sm.youtube_mode, ig = sm.instagram_enabled;
    const item = (ok, label, detail) => `<li><strong>${ok ? "✓" : "○"} ${label}:</strong> ${detail}</li>`;
    return `<ul style="margin:0;padding-left:0;list-style:none;display:grid;gap:4px;font-size:13px">
      ${item(!!yt, "YouTube", yt === "api" ? "subscribers, new videos and views, updated daily." : yt === "feed" ? "new videos and views, updated daily. Add a YouTube API key to include subscriber counts." : yt === "sample" ? "sample data." : "not collected yet.")}
      ${item(ig, "Instagram", ig ? "followers, posts and engagement, updated daily." : "waiting for set-up. Add an Instagram business account token to switch it on (see the README).")}
      ${item(true, "LinkedIn", "from the monthly log in <code>data/social.csv</code>. Use the links below to check each page.")}
      ${item(true, "Facebook and Instagram ads", "the Live ads links open each brand in Meta's Ad Library.")}
    </ul>`;
  }

  function build(){
    charts.forEach(c => c.destroy()); charts = [];
    const R = rows();
    const has = k => R.some(r => r[k]);
    const sortKey = { instagram: r => n(r.instagram?.followers) ?? -1, youtube: r => n(r.youtube?.views_30d) ?? -1,
                      linkedin: r => n(r.linkedin?.followers) ?? -1, name: r => r.brand };
    const sorted = [...R].sort((a, z) => st.sort === "name" ? a.brand.localeCompare(z.brand) : sortKey[st.sort](z) - sortKey[st.sort](a));
    const videos = R.flatMap(r => (r.youtube?.latest || []).map(v => ({ ...v, brand: r.brand })))
      .sort((a, z) => (z.published || "").localeCompare(a.published || "")).slice(0, 12);
    const posts = R.filter(r => r.instagram?.top_post).map(r => ({ ...r.instagram.top_post, brand: r.brand }))
      .sort((a, z) => (z.likes + z.comments) - (a.likes + a.comments)).slice(0, 8);
    const errs = (SM().errors || []).filter(e => R.some(r => e.includes(r.brand)));

    el().innerHTML = `
      <section class="card" style="margin-bottom:16px">
        <div class="row-head">
          <div><h2>Social media</h2><p class="sub" style="margin:0">What each brand is doing on YouTube, Instagram and LinkedIn, and the ads it is running.</p></div>
          <div class="btnrow">
            <div class="seg" role="group" aria-label="Sector">
              <button type="button" data-ssec="Wealth" aria-pressed="${st.sector === "Wealth"}">Wealth</button>
              <button type="button" data-ssec="Insure" aria-pressed="${st.sector === "Insure"}">Insurance</button>
            </div>
          </div>
        </div>
        <div style="margin-top:12px">${statusHtml()}</div>
      </section>

      <section class="card" style="margin-bottom:16px">
        <div class="row-head">
          <div><h2>At a glance</h2><p class="sub" style="margin:0">Last 30 days. Changes compare with the previous reading.</p></div>
          <label class="field">Sort by <select id="sSort">
            <option value="instagram">Instagram followers</option><option value="youtube">YouTube views (30 days)</option>
            <option value="linkedin">LinkedIn followers</option><option value="name">Brand name</option></select></label>
        </div>
        <div class="table-wrap" style="margin-top:10px"><table>
          <thead><tr><th>Brand</th>
            <th class="num">Instagram followers</th><th class="num">Posts</th><th class="num">Avg engagement</th>
            <th class="num">YouTube subscribers</th><th class="num">New videos</th><th class="num">Views</th>
            <th class="num">LinkedIn followers</th><th>Live ads</th></tr></thead>
          <tbody>${sorted.map(r => `<tr>
            <td>${esc(r.brand)}</td>
            <td class="num">${num(r.instagram?.followers)}${chg(r.instagram?.change_30d)}</td>
            <td class="num">${num(r.instagram?.posts_30d)}</td>
            <td class="num">${num(r.instagram?.avg_engagement_30d)}</td>
            <td class="num">${num(r.youtube?.subscribers)}${chg(r.youtube?.change_30d)}</td>
            <td class="num">${num(r.youtube?.videos_30d)}</td>
            <td class="num">${num(r.youtube?.views_30d)}</td>
            <td class="num">${num(r.linkedin?.followers)}${chg(r.linkedin?.change)}</td>
            <td><a href="${esc(r.ad_library)}" target="_blank" rel="noopener">View ads</a></td></tr>`).join("")}</tbody>
        </table></div>
        <p class="hint" style="margin:8px 0 0">Engagement is likes plus comments per post. “–” means no account was found or the platform isn't switched on yet.</p>
      </section>

      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Instagram followers</h2><p class="sub">Latest count</p>
          ${has("instagram") ? `<div class="chart-box" style="height:${36 * R.length + 40}px"><canvas id="sIg" role="img" aria-label="Instagram followers by brand"></canvas></div>` : `<p class="empty">Instagram isn't switched on yet.</p>`}</div>
        <div class="card"><h2>YouTube activity</h2><p class="sub">Views on videos published in the last 30 days</p>
          ${has("youtube") ? `<div class="chart-box" style="height:${36 * R.length + 40}px"><canvas id="sYt" role="img" aria-label="YouTube views by brand"></canvas></div>` : `<p class="empty">No YouTube channels found yet.</p>`}</div>
      </section>

      <section class="grid g-2" style="margin-bottom:16px">
        <div class="card"><h2>Latest YouTube videos</h2><p class="sub">Newest first, across this sector</p>
          <div class="feed">${videos.length ? videos.map(v => `<div class="item"><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a>
            <div class="meta"><strong>${esc(v.brand)}</strong> · ${v.published ? shortDate(v.published) : ""} · ${fmt(v.views)} views</div></div>`).join("") : '<p class="empty">No videos yet.</p>'}</div></div>
        <div class="card"><h2>Top Instagram posts</h2><p class="sub">Each brand's best post in the last 30 days, by engagement</p>
          <div class="feed">${posts.length ? posts.map(p => `<div class="item"><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.caption || "View post")}</a>
            <div class="meta"><strong>${esc(p.brand)}</strong> · ${shortDate(p.date)} · ${fmt(p.likes)} likes · ${fmt(p.comments)} comments</div></div>`).join("") : '<p class="empty">Instagram isn\'t switched on yet.</p>'}</div></div>
      </section>

      <section class="card" style="margin-bottom:16px">
        <h2>Accounts we're tracking</h2>
        <p class="sub">Found on each brand's own website. If one is wrong or missing, set it under the brand's <code>social</code> key in <code>config.json</code>. The LinkedIn links help with the monthly follower log.</p>
        <div class="table-wrap"><table><thead><tr><th>Brand</th><th>YouTube</th><th>Instagram</th><th>LinkedIn</th><th>Facebook</th><th>LinkedIn last logged</th></tr></thead><tbody>
          ${[...R].sort((a, z) => a.brand.localeCompare(z.brand)).map(r => `<tr><td>${esc(r.brand)}</td>
            ${["youtube", "instagram", "linkedin", "facebook"].map(k => `<td>${r.account_urls?.[k] ? `<a href="${esc(r.account_urls[k])}" target="_blank" rel="noopener">${esc(r.accounts[k])}</a>${(r.manual || []).includes(k) ? ' <span class="pill">set</span>' : ""}` : '<span class="hint">not found</span>'}</td>`).join("")}
            <td>${r.linkedin ? `${fmt(r.linkedin.followers)} on ${esc(r.linkedin.date)}` : '<span class="hint">not logged</span>'}</td></tr>`).join("")}
        </tbody></table></div>
        ${errs.length ? `<details style="margin-top:10px"><summary class="hint">${errs.length} account${errs.length > 1 ? "s" : ""} couldn't be read on the last run</summary><ul class="hint">${errs.map(e => `<li>${esc(e)}</li>`).join("")}</ul></details>` : ""}
      </section>`;

    $("#sSort").value = st.sort;
    $("#sSort").onchange = e => { st.sort = e.target.value; build(); };
    document.querySelectorAll("[data-ssec]").forEach(b => b.onclick = () => { st.sector = b.dataset.ssec; syncUrl(); build(); });
    drawBars("sIg", R.filter(r => r.instagram?.followers != null).map(r => [r.brand, r.instagram.followers]));
    drawBars("sYt", R.filter(r => r.youtube?.views_30d != null).map(r => [r.brand, r.youtube.views_30d]));
    built = true;
  }

  function drawBars(id, pairs){
    const c = document.getElementById(id); if (!c || !pairs.length) return;
    pairs.sort((a, z) => z[1] - a[1]);
    const colour = entityColours()[0];
    charts.push(new Chart(c, {
      type: "bar",
      data: { labels: pairs.map(p => p[0]), datasets: [{ data: pairs.map(p => p[1]), backgroundColor: colour, borderRadius: 4, borderSkipped: "start", barThickness: 14 }] },
      options: { ...chartBase(), indexAxis: "y",
        scales: { x: { beginAtZero: true, grid: { color: css("--grid") }, border: { display: false }, ticks: { callback: v => fmt(v) } },
                  y: { grid: { display: false }, border: { display: false }, ticks: { color: css("--ink-2") } } },
        plugins: { legend: { display: false }, tooltip: { ...tooltipBase(), displayColors: false, callbacks: { label: x => fmt(pairs[x.dataIndex][1]) } } } }
    }));
  }

  function redraw(){ if (built) build(); }
  return { show, redraw };
})();
