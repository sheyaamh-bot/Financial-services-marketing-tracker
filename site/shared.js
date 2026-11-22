// Helpers shared by the report and topics views. Loaded after the main page script,
// so it can use $, esc, css, fmt, D and SECTOR from there.

// Validated categorical palette (fixed order, never cycled). Slot 1 is always "you".
const PALETTE = {
  light: ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6"],
  dark:  ["#3987E5", "#D95926", "#199E70", "#C98500", "#D55181", "#0CA30C", "#9085E9"],
};
function isDark(){
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function entityColours(){ return isDark() ? PALETTE.dark : PALETTE.light; }

function shortDate(iso){ return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }); }
function longDate(iso){ return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }); }

// Groups 90 day-indexed values into the points a chart should show for a period:
// daily for 7 and 30 days, weekly for 90 days.
function buckets(daysIso, period){
  const n = daysIso.length, start = n - period, step = period > 31 ? 7 : 1, out = [];
  for (let i = start; i < n; i += step){
    const end = Math.min(i + step, n);
    out.push({ from: i, to: end, label: step === 1 ? shortDate(daysIso[i]) : `w/c ${shortDate(daysIso[i])}` });
  }
  return out;
}

function sparkline(values, colour){
  const w = 200, h = 36, max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * w},${h - 3 - (v / max) * (h - 6)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${colour}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

function pctChange(now, before){
  if (!before) return null;
  return Math.round(100 * (now - before) / before);
}
function changeHtml(p){
  if (p === null || p === undefined) return '<span class="hint">–</span>';
  if (p === 0) return "0%";
  return `<span class="${p > 0 ? "up" : "down"}">${p > 0 ? "▲" : "▼"} ${Math.abs(p)}%</span>`;
}

function loadXLSX(){
  if (window.XLSX) return Promise.resolve(window.XLSX);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
    s.onload = () => resolve(window.XLSX);
    s.onerror = () => reject(new Error("Could not load the Excel library"));
    document.head.appendChild(s);
  });
}
function sheetFromRows(XLSX, rows, widths){
  const ws = XLSX.utils.aoa_to_sheet(rows);
  if (widths) ws["!cols"] = widths.map(w => ({ wch: w }));
  return ws;
}

async function copyLink(btn){
  try { await navigator.clipboard.writeText(location.href); }
  catch(e){ window.prompt("Copy this link:", location.href); return; }
  const old = btn.textContent; btn.textContent = "Link copied"; setTimeout(() => btn.textContent = old, 1600);
}

function chartBase(){
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = css("--muted");
  return { responsive: true, maintainAspectRatio: false, animation: false, devicePixelRatio: Math.max(2, window.devicePixelRatio || 1) };
}
function tooltipBase(){
  return { backgroundColor: "#111418", titleColor: "#fff", bodyColor: "#fff", padding: 10, cornerRadius: 6, boxPadding: 4 };
}
