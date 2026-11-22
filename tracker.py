#!/usr/bin/env python3
"""PSG Marketing & PR Competitor Tracker.

Tracks two competitor sets, each against its own PSG business:
  * Wealth: PSG Wealth vs wealth managers, asset managers and advice firms.
  * Insure: PSG Insure vs insurers and broker networks.

Runs once a day (see .github/workflows/daily-update.yml). Each run:

1. Pulls the latest news coverage for every brand from Google News RSS.
2. Tags each item with a marketing/PR category and a simple tone score.
3. Adds new items to a rolling history (data/mentions.json).
4. Writes a morning briefing per segment (Claude when ANTHROPIC_API_KEY is set,
   otherwise rule-based).
5. Builds the dashboard data (site/data.json) and the Excel workbook
   (site/PSG_Competitor_Tracker.xlsx).

Usage:
    python tracker.py            # live run
    python tracker.py --demo     # build with clearly labelled sample data (no network)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import random
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site"
SAST = timezone(timedelta(hours=2))

# PSG brand colours (from the current PSG brand). Keep in step with site/index.html.
CHARCOAL = "353E43"
INK = "241F21"
CYAN = "00AEEF"       # PSG cyan
CHART_CYAN = "0096D6"  # deeper cyan for chart marks on white (passes 3:1 contrast)
ACTION = "0054FF"      # links and buttons
PALE = "F2F9FD"
WHITE = "FFFFFF"
FONT = "Arial"         # PSG Plex Sans is not installed on most PCs; Arial is the brand fallback

TONE = {1: "Positive", 0: "Neutral", -1: "Negative"}


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def item_id(segment: str, link: str, title: str) -> str:
    return hashlib.sha1(f"{segment}|{link}|{title}".encode("utf-8")).hexdigest()[:16]


def fetch_google_news(brand: dict, cfg: dict) -> list[dict]:
    region = cfg["region"]
    q = f"({brand['query']}) when:{cfg['lookback_days_per_run']}d"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(q)
        + f"&hl={region['hl']}&gl={region['gl']}&ceid={region['ceid']}"
    )
    resp = requests.get(url, timeout=30, headers={"User-Agent": "competitor-tracker/1.0"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for node in root.iter("item"):
        title = html.unescape(node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        source_el = node.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        if source and title.endswith(f" - {source}"):  # Google appends " - Source"
            title = title[: -len(source) - 3].strip()
        try:
            published = parsedate_to_datetime(node.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        items.append({"brand": brand["name"], "title": title, "link": link,
                      "source": source or "Unknown", "published": published.isoformat()})
    return items


def classify(title: str, cfg: dict) -> str:
    text = f" {title.lower()} "
    best, best_hits = "Other coverage", 0
    for category, words in cfg["categories"].items():
        hits = sum(1 for w in words if w in text)
        if hits > best_hits:
            best, best_hits = category, hits
    return best


def tone(title: str, cfg: dict) -> int:
    text = f" {title.lower()} "
    pos = sum(1 for w in cfg["sentiment"]["positive"] if w in text)
    neg = sum(1 for w in cfg["sentiment"]["negative"] if w in text)
    return (pos > neg) - (neg > pos)


def demo_items(cfg: dict) -> list[dict]:
    """Clearly labelled sample data so the dashboard can be previewed offline."""
    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    outlets = ["Moneyweb", "BusinessLIVE", "Daily Maverick", "News24", "IOL", "Bizcommunity",
               "MyBroadband", "Citizen", "Personal Finance", "Fin24", "Cover", "FA News", "Insurance Times"]
    cats = list(cfg["categories"].keys()) + ["Other coverage"]
    out = []
    for seg_name, seg in cfg["segments"].items():
        for n, b in enumerate(seg["brands"]):
            weight = rnd.randint(2, 9)
            for day in range(60):
                for _ in range(rnd.randint(0, weight)):
                    cat = rnd.choice(cats)
                    ts = now - timedelta(days=day, hours=rnd.randint(0, 20))
                    title = f"[Sample] {b['name']}: {cat.lower()} story"
                    link = f"https://example.com/sample/{seg_name.lower()}/{n}/{day}/{rnd.randint(1, 99999)}"
                    out.append({
                        "id": item_id(seg_name, link, title), "segment": seg_name, "brand": b["name"],
                        "title": title, "link": link, "source": rnd.choice(outlets),
                        "published": ts.isoformat(), "first_seen": ts.isoformat(), "category": cat,
                        "sentiment": rnd.choice([1, 1, 0, 0, 0, -1]),
                    })
    return out


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def window(items: list[dict], days: int, now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=days)
    return [i for i in items if parse(i["published"]) >= cutoff]


def share_of_voice(items: list[dict], brands: list[str]) -> list[dict]:
    counts = Counter(i["brand"] for i in items)
    total = sum(counts.values()) or 1
    rows = [{"brand": b, "mentions": counts.get(b, 0), "share": round(100 * counts.get(b, 0) / total, 1)}
            for b in brands]
    return sorted(rows, key=lambda r: r["mentions"], reverse=True)


def build_metrics(items: list[dict], brands: list[str], home: str, cfg: dict, now: datetime) -> dict:
    cats = list(cfg["categories"].keys()) + ["Other coverage"]
    last7, last30, last1 = window(items, 7, now), window(items, 30, now), window(items, 1, now)
    cut7 = now - timedelta(days=7)
    prev7 = [i for i in window(items, 14, now) if parse(i["published"]) < cut7]

    sov7, sov30 = share_of_voice(last7, brands), share_of_voice(last30, brands)
    prev_counts = Counter(i["brand"] for i in prev7)

    days = [(now - timedelta(days=d)).astimezone(SAST).date().isoformat() for d in range(29, -1, -1)]
    daily = {b: {d: 0 for d in days} for b in brands}
    for i in last30:
        d = parse(i["published"]).astimezone(SAST).date().isoformat()
        if d in daily.get(i["brand"], {}):
            daily[i["brand"]][d] += 1

    matrix = {b: {c: 0 for c in cats} for b in brands}
    sent = {b: {"positive": 0, "neutral": 0, "negative": 0} for b in brands}
    for i in last30:
        if i["brand"] not in matrix:
            continue
        matrix[i["brand"]][i.get("category", "Other coverage")] += 1
        sent[i["brand"]][TONE[i.get("sentiment", 0)].lower()] += 1

    outlets = Counter(i["source"] for i in last30).most_common(15)
    by_outlet = defaultdict(Counter)
    for i in last30:
        by_outlet[i["source"]][i["brand"]] += 1

    home_rank = next((n + 1 for n, r in enumerate(sov7) if r["brand"] == home), None)
    home_7 = next((r for r in sov7 if r["brand"] == home), {"mentions": 0, "share": 0})
    return {
        "brands": brands,
        "categories": cats,
        "kpis": {
            "home_mentions_7d": home_7["mentions"],
            "home_mentions_prev_7d": prev_counts.get(home, 0),
            "home_share_7d": home_7["share"],
            "home_rank_7d": home_rank,
            "brands_tracked": len(brands),
            "new_items_24h": len(last1),
            "items_30d": len(last30),
        },
        "share_of_voice_7d": [dict(r, prev_mentions=prev_counts.get(r["brand"], 0)) for r in sov7],
        "share_of_voice_30d": sov30,
        "daily": {"days": days, "series": {b: [daily[b][d] for d in days] for b in brands}},
        "category_matrix": matrix,
        "sentiment_30d": sent,
        "top_outlets": [{"source": s, "mentions": n, "by_brand": dict(by_outlet[s])} for s, n in outlets],
    }


# --------------------------------------------------------------------------- #
# Morning briefing
# --------------------------------------------------------------------------- #
def rule_based_briefing(metrics: dict, items: list[dict], home: str, now: datetime) -> dict:
    k = metrics["kpis"]
    sov = metrics["share_of_voice_7d"]
    leader = next((r for r in sov if r["brand"] != home), sov[0])
    delta = k["home_mentions_7d"] - k["home_mentions_prev_7d"]
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    riser = max(sov, key=lambda r: r["mentions"] - r["prev_mentions"])
    risk = [i for i in window(items, 7, now) if i.get("category") == "Reputation & regulatory"]
    points = [
        f"{home} earned {k['home_mentions_7d']} mentions in the past 7 days "
        + (f"({direction} {abs(delta)} on the week before). " if delta else "(the same as the week before). ")
        + f"That is a {k['home_share_7d']}% share of voice, ranking #{k['home_rank_7d']} of {k['brands_tracked']}.",
        f"{leader['brand']} leads the competitor set with {leader['share']}% share of voice.",
        f"Biggest riser: {riser['brand']}, up {riser['mentions'] - riser['prev_mentions']} mentions week on week.",
        f"{k['new_items_24h']} new items in the last 24 hours.",
    ]
    if risk:
        points.append(f"{len(risk)} reputation or regulatory items this week, involving "
                      + ", ".join(sorted({i['brand'] for i in risk})) + ".")
    return {"source": "rules", "headline": f"{home} ranks #{k['home_rank_7d']} for share of voice this week",
            "points": points, "watch": []}


def claude_briefing(segment: str, metrics: dict, items: list[dict], home: str, cfg: dict, now: datetime) -> dict | None:
    if not os.environ.get("ANTHROPIC_API_KEY") or not cfg["claude"].get("enabled_if_key_present", True):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    recent = sorted(window(items, 7, now), key=lambda i: i["published"], reverse=True)[:150]
    payload = {
        "segment": segment,
        "home_brand": home,
        "kpis": metrics["kpis"],
        "share_of_voice_7d": metrics["share_of_voice_7d"],
        "headlines_last_7_days": [
            {"brand": i["brand"], "title": i["title"], "source": i["source"],
             "category": i.get("category"), "date": i["published"][:10]} for i in recent
        ],
    }
    system = (
        "You write the morning competitor briefing for the marketing and PR team at PSG Financial Services, "
        "a South African wealth, asset management and insurance group. Use British English, plain language "
        "and the active voice. No exclamation marks. Keep each point to one idea and at most two sentences. "
        "Focus on what matters for marketing and PR: campaigns, sponsorships, awards, spokespeople, launches, "
        "share of voice shifts and reputation risks. Only state facts found in the data you are given."
    )
    schema = {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "One-line summary of the day, under 15 words."},
            "points": {"type": "array", "items": {"type": "string"}, "description": "4 to 6 briefing points."},
            "watch": {"type": "array", "items": {"type": "string"}, "description": "1 to 3 suggested actions for the PSG team."},
        },
        "required": ["headline", "points", "watch"],
        "additionalProperties": False,
    }
    try:
        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=cfg["claude"].get("model", "claude-opus-5-5"),
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": cfg["claude"].get("effort", "low"),
                           "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": "Today's data:\n" + json.dumps(payload, ensure_ascii=False)}],
        )
        if response.stop_reason == "refusal":
            return None
        out = json.loads("".join(b.text for b in response.content if b.type == "text"))
        out["source"] = "claude"
        return out
    except Exception as exc:  # never let the briefing break the daily run
        print(f"Claude briefing skipped for {segment}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Manual inputs
# --------------------------------------------------------------------------- #
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def social_summary(rows: list[dict]) -> list[dict]:
    by_key = defaultdict(list)
    for r in rows:
        try:
            by_key[(r["brand"], r["platform"])].append((r["date"], int(float(r["followers"]))))
        except (KeyError, ValueError):
            continue
    out = []
    for (brand, platform), vals in by_key.items():
        vals.sort()
        latest, prev = vals[-1], (vals[-2] if len(vals) > 1 else None)
        out.append({"brand": brand, "platform": platform, "date": latest[0], "followers": latest[1],
                    "change": latest[1] - prev[1] if prev else None})
    return sorted(out, key=lambda r: (r["platform"], -r["followers"]))


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
HEAD_FILL = PatternFill("solid", fgColor=CHARCOAL)
HEAD_FONT = Font(bold=True, color=WHITE, name=FONT, size=10)
BODY_FONT = Font(name=FONT, size=10, color=CHARCOAL)
HOME_FILL = PatternFill("solid", fgColor=PALE)
THIN = Border(bottom=Side(style="thin", color="D9DEE1"))
CYAN_RULE = Border(bottom=Side(style="thick", color=CYAN))


def style_table(ws, header_row: int, ncols: int, widths: list[int], wrap_cols=("C",)):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[header_row].height = 30
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if ws.max_row > header_row:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(ncols)}{ws.max_row}"
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row, max_col=ncols):
        for cell in row:
            cell.border = THIN
            if cell.font.color is None or cell.font.color.rgb in (None, "FF000000"):
                cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column_letter in wrap_cols)


def title_block(ws, title: str, subtitle: str):
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, bold=True, size=16, color=INK)
    ws["A2"] = subtitle
    ws["A2"].font = Font(name=FONT, italic=True, size=10, color="5F6B72")
    ws.sheet_properties.tabColor = CYAN


def highlight_home(ws, header_row: int, ncols: int, home: str, col: int = 1):
    for r in range(header_row + 1, ws.max_row + 1):
        if ws.cell(row=r, column=col).value == home:
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).fill = HOME_FILL
                ws.cell(row=r, column=c).font = Font(name=FONT, bold=True, size=10, color=INK)


def write_segment_sheets(wb, seg: str, S: dict, cfg: dict):
    home, m = S["home"], S["metrics"]

    ws = wb.create_sheet(f"{seg} share of voice")
    title_block(ws, f"{seg}: share of voice", f"{home} vs competitors. Share = brand mentions ÷ all mentions in this set.")
    ws.append([])
    ws.append(["Brand", "Mentions (7d)", "Previous 7d", "Change", "Share 7d (%)", "Mentions (30d)", "Share 30d (%)"])
    s30 = {r["brand"]: r for r in m["share_of_voice_30d"]}
    for row in m["share_of_voice_7d"]:
        ws.append([row["brand"], row["mentions"], row["prev_mentions"], row["mentions"] - row["prev_mentions"],
                   row["share"], s30[row["brand"]]["mentions"], s30[row["brand"]]["share"]])
    style_table(ws, 4, 7, [20, 14, 13, 10, 13, 15, 13])
    highlight_home(ws, 4, 7, home)
    chart = BarChart()
    chart.type, chart.title = "bar", "Share of voice, last 30 days (%)"
    chart.add_data(Reference(ws, min_col=7, min_row=4, max_row=ws.max_row), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=5, max_row=ws.max_row))
    chart.legend, chart.height, chart.width = None, 9, 16
    chart.series[0].graphicalProperties.solidFill = CHART_CYAN
    chart.series[0].graphicalProperties.line.solidFill = CHART_CYAN
    chart.y_axis.majorGridlines = None
    ws.add_chart(chart, "I4")

    ws = wb.create_sheet(f"{seg} activity")
    cats = m["categories"]
    title_block(ws, f"{seg}: marketing and PR activity", "Items per brand per activity type, last 30 days.")
    ws.append([])
    ws.append(["Brand"] + cats + ["Total"])
    for b in m["brands"]:
        vals = [m["category_matrix"][b][c] for c in cats]
        ws.append([b] + vals + [sum(vals)])
    style_table(ws, 4, len(cats) + 2, [18] + [14] * (len(cats) + 1), wrap_cols=())
    highlight_home(ws, 4, len(cats) + 2, home)

    ws = wb.create_sheet(f"{seg} daily trend")
    title_block(ws, f"{seg}: daily coverage", "Mentions per day, last 30 days.")
    ws.append([])
    ws.append(["Date"] + m["brands"])
    for n, d in enumerate(m["daily"]["days"]):
        ws.append([d] + [m["daily"]["series"][b][n] for b in m["brands"]])
    style_table(ws, 4, len(m["brands"]) + 1, [12] + [13] * len(m["brands"]), wrap_cols=())
    line = LineChart()
    line.title, line.height, line.width, line.legend = f"{home} daily mentions", 8, 18, None
    home_col = m["brands"].index(home) + 2
    line.add_data(Reference(ws, min_col=home_col, min_row=4, max_row=ws.max_row), titles_from_data=True)
    line.set_categories(Reference(ws, min_col=1, min_row=5, max_row=ws.max_row))
    line.series[0].graphicalProperties.line.solidFill = CHART_CYAN
    line.series[0].graphicalProperties.line.width = 22000
    ws.add_chart(line, f"{get_column_letter(len(m['brands']) + 3)}4")


def build_excel(data: dict, items: list[dict], cfg: dict, path: Path):
    updated = data["meta"]["updated_local"]
    segs = data["segments"]
    wb = Workbook()

    # Briefing (both segments)
    ws = wb.active
    ws.title = "Briefing"
    title_block(ws, cfg["tracker_name"], f"Updated {updated} SAST" + ("  ·  SAMPLE DATA" if data["meta"]["demo"] else ""))
    r = 4
    for seg, S in segs.items():
        k, b = S["metrics"]["kpis"], S["briefing"]
        c = ws.cell(row=r, column=1, value=f"{seg.upper()}  ·  {b['headline']}")
        c.font, c.border = Font(name=FONT, bold=True, size=13, color=INK), CYAN_RULE
        r += 2
        for p in b["points"]:
            ws.cell(row=r, column=1, value="•  " + p).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=r, column=1).font = BODY_FONT
            r += 1
        for p in b.get("watch") or []:
            ws.cell(row=r, column=1, value="→  " + p).font = Font(name=FONT, size=10, color=ACTION)
            r += 1
        r += 1
        for label, val in [(f"{S['home']} mentions (7 days)", k["home_mentions_7d"]),
                           ("Previous 7 days", k["home_mentions_prev_7d"]),
                           ("Share of voice (7 days)", f"{k['home_share_7d']}%"),
                           ("Rank (7 days)", f"#{k['home_rank_7d']} of {k['brands_tracked']}")]:
            ws.cell(row=r, column=1, value=label).font = Font(name=FONT, size=10, color="5F6B72")
            ws.cell(row=r, column=2, value=val).font = Font(name=FONT, bold=True, size=10, color=INK)
            r += 1
        r += 2
    ws.column_dimensions["A"].width = 110
    ws.column_dimensions["B"].width = 16

    for seg, S in segs.items():
        write_segment_sheets(wb, seg, S, cfg)

    # Coverage log (all)
    ws = wb.create_sheet("Coverage log")
    title_block(ws, "Coverage log", f"Every tracked item, newest first. Rolling {cfg['history_days']} days. Filter by segment or brand.")
    ws.append([])
    ws.append(["Date", "Segment", "Brand", "Headline", "Outlet", "Category", "Tone", "Link"])
    for i in sorted(items, key=lambda x: x["published"], reverse=True):
        ws.append([parse(i["published"]).astimezone(SAST).strftime("%Y-%m-%d"), i["segment"], i["brand"], i["title"],
                   i["source"], i.get("category", ""), TONE[i.get("sentiment", 0)], i["link"]])
        ws.cell(row=ws.max_row, column=8).hyperlink = i["link"]
        ws.cell(row=ws.max_row, column=8).font = Font(name=FONT, size=10, color=ACTION, underline="single")
    style_table(ws, 4, 8, [12, 10, 18, 70, 22, 28, 10, 40], wrap_cols=("D",))

    # Tone (all)
    ws = wb.create_sheet("Tone")
    title_block(ws, "Headline tone", "Keyword-based tone of headlines, last 30 days. A signal, not a verdict.")
    ws.append([])
    ws.append(["Segment", "Brand", "Positive", "Neutral", "Negative", "Net score"])
    for seg, S in segs.items():
        for b in S["metrics"]["brands"]:
            s = S["metrics"]["sentiment_30d"][b]
            tot = sum(s.values()) or 1
            ws.append([seg, b, s["positive"], s["neutral"], s["negative"], round(100 * (s["positive"] - s["negative"]) / tot)])
    style_table(ws, 4, 6, [10, 20, 11, 11, 11, 11], wrap_cols=())
    for seg, S in segs.items():
        highlight_home(ws, 4, 6, S["home"], col=2)

    # Top outlets (all)
    ws = wb.create_sheet("Top outlets")
    title_block(ws, "Top outlets", "Publications carrying the most tracked coverage, last 30 days.")
    ws.append([])
    ws.append(["Segment", "Outlet", "Mentions", "PSG mentions", "Top brand in outlet"])
    for seg, S in segs.items():
        for o in S["metrics"]["top_outlets"]:
            top = max(o["by_brand"].items(), key=lambda kv: kv[1])[0] if o["by_brand"] else ""
            ws.append([seg, o["source"], o["mentions"], o["by_brand"].get(S["home"], 0), top])
    style_table(ws, 4, 5, [10, 28, 11, 14, 22], wrap_cols=())

    # Manual inputs
    ws = wb.create_sheet("Social tracker")
    title_block(ws, "Social followers", "Manual input: add rows to data/social.csv (date, brand, platform, followers).")
    ws.append([])
    ws.append(["Brand", "Platform", "Followers", "Change since last entry", "As at"])
    for s in data["social"]:
        ws.append([s["brand"], s["platform"], s["followers"], s["change"], s["date"]])
    style_table(ws, 4, 5, [18, 14, 13, 22, 12], wrap_cols=())

    ws = wb.create_sheet("Campaign log")
    title_block(ws, "Campaign and activity log", "Manual input: add rows to data/campaigns.csv when the team spots a campaign, sponsorship or event.")
    ws.append([])
    cols = ["date_spotted", "brand", "campaign_or_activity", "channel", "type", "link", "notes"]
    ws.append(["Date spotted", "Brand", "Campaign or activity", "Channel", "Type", "Link", "Notes"])
    for c in data["campaigns"]:
        ws.append([c.get(k, "") for k in cols])
    style_table(ws, 4, 7, [13, 16, 40, 16, 16, 36, 40])

    ws = wb.create_sheet("How it works")
    title_block(ws, "How this tracker works", "Built with Claude Code.")
    notes = [
        "Two competitor sets: Wealth (PSG Wealth) and Insure (PSG Insure). Share of voice is calculated within each set.",
        "Refreshes automatically every morning at about 05:15 SAST.",
        "Coverage comes from Google News for each brand's search terms in config.json.",
        "Categories and tone are keyword-based. Edit the keyword lists in config.json to tune them.",
        "The briefing is rule-based. Add an Anthropic API key to have Claude write it.",
        "Social followers and campaigns are manual inputs in the data folder.",
        "Mentions are news items, not reach or advertising value equivalent (AVE).",
    ]
    for n, t in enumerate(notes, start=4):
        ws.cell(row=n, column=1, value="•  " + t).font = BODY_FONT
    ws.column_dimensions["A"].width = 110

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="build with sample data, no network")
    args = ap.parse_args()

    cfg = load_config()
    now = datetime.now(timezone.utc)
    store = DATA / "mentions.json"
    history = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {"items": [], "demo": False}

    errors: list[str] = []
    if args.demo:
        items, demo = demo_items(cfg), True
    else:
        # A live run replaces any sample data.
        known = {} if history.get("demo") else {i["id"]: i for i in history["items"] if "segment" in i}
        for seg_name, seg in cfg["segments"].items():
            for brand in seg["brands"]:
                try:
                    for it in fetch_google_news(brand, cfg):
                        it["segment"] = seg_name
                        it["id"] = item_id(seg_name, it["link"], it["title"])
                        if it["id"] not in known:
                            it["first_seen"] = now.isoformat()
                            it["category"] = classify(it["title"], cfg)
                            it["sentiment"] = tone(it["title"], cfg)
                            known[it["id"]] = it
                except Exception as exc:
                    errors.append(f"{brand['name']}: {exc}")
                    print(f"Fetch failed for {brand['name']}: {exc}", file=sys.stderr)
        cutoff = now - timedelta(days=cfg["history_days"])
        items = [i for i in known.values() if parse(i["published"]) >= cutoff]
        demo = False
        if not items and errors:
            print("No data collected; leaving previous outputs untouched.", file=sys.stderr)
            return 1

    store.write_text(json.dumps({"demo": demo, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")

    segments = {}
    for seg_name, seg in cfg["segments"].items():
        seg_items = [i for i in items if i["segment"] == seg_name]
        brands = [b["name"] for b in seg["brands"]]
        metrics = build_metrics(seg_items, brands, seg["home"], cfg, now)
        briefing = (None if demo else claude_briefing(seg_name, metrics, seg_items, seg["home"], cfg, now)) \
            or rule_based_briefing(metrics, seg_items, seg["home"], now)
        recent = sorted(window(seg_items, 30, now), key=lambda i: i["published"], reverse=True)
        segments[seg_name] = {"home": seg["home"], "briefing": briefing, "metrics": metrics, "coverage": recent[:300]}

    data = {
        "meta": {
            "tracker_name": cfg["tracker_name"],
            "updated_utc": now.isoformat(),
            "updated_local": now.astimezone(SAST).strftime("%d %b %Y, %H:%M"),
            "demo": demo,
            "fetch_errors": errors,
        },
        "segments": segments,
        "social": social_summary(read_csv(DATA / "social.csv")),
        "campaigns": sorted(read_csv(DATA / "campaigns.csv"), key=lambda r: r.get("date_spotted", ""), reverse=True),
    }
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    build_excel(data, items, cfg, SITE / "PSG_Competitor_Tracker.xlsx")
    print(f"Done: {len(items)} items, {len(errors)} fetch errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
