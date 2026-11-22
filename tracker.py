#!/usr/bin/env python3
"""Financial Services Marketing Tracker.

An independent, daily view of marketing and PR activity across South African
financial services, in two sectors:
  * Wealth: wealth managers, asset managers and advice firms.
  * Insure: insurers and broker networks.

Runs once a day (see .github/workflows/daily-update.yml). Each run:

1. Pulls the latest news coverage for every brand from Google News RSS.
2. Tags each item with a marketing/PR category and a simple tone score.
3. Adds new items to a rolling history (data/mentions.json).
4. Writes a morning briefing per sector (Claude when ANTHROPIC_API_KEY is set,
   otherwise rule-based).
5. Builds the dashboard data (site/data.json) and the Excel workbook
   (site/Financial_Services_Marketing_Tracker.xlsx).

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
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site"
SAST = timezone(timedelta(hours=2))
WORKBOOK = "Financial_Services_Marketing_Tracker.xlsx"

# Neutral palette (keep in step with site/index.html).
SLATE = "1F2933"
INK = "111418"
MUTED = "5B6570"
ACCENT = "2A78D6"
PALE = "F1F5FA"
WHITE = "FFFFFF"
FONT = "Arial"

TONE = {1: "Positive", 0: "Neutral", -1: "Negative"}


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def item_id(segment: str, link: str, title: str) -> str:
    return hashlib.sha1(f"{segment}|{link}|{title}".encode("utf-8")).hexdigest()[:16]


def fetch_google_news(brand: dict, cfg: dict, lookback_days: int) -> list[dict]:
    region = cfg["region"]
    q = f"({brand['query']}) when:{lookback_days}d"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(q)
        + f"&hl={region['hl']}&gl={region['gl']}&ceid={region['ceid']}"
    )
    resp = requests.get(url, timeout=30, headers={"User-Agent": "fs-marketing-tracker/1.0"})
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
            for day in range(100):
                for _ in range(rnd.randint(0, weight)):
                    cat = rnd.choice(cats)
                    ts = now - timedelta(days=day, hours=rnd.randint(0, 20))
                    title = f"[Sample] {b['name']}: {cat.lower()} story"
                    if rnd.random() < 0.25:
                        topic = rnd.choice([t for t in cfg.get("topics", []) if t["sector"] == seg_name] or [None])
                        if topic:
                            title += f" on {topic['keywords'][0].strip()}"
                    link = f"https://example.com/sample/{seg_name.lower()}/{n}/{day}/{rnd.randint(1, 99999)}"
                    out.append({
                        "id": item_id(seg_name, link, title), "segment": seg_name, "brand": b["name"],
                        "title": title, "link": link, "source": rnd.choice(outlets),
                        "published": ts.isoformat(), "first_seen": ts.isoformat(), "category": cat,
                        "sentiment": rnd.choice([1, 1, 0, 0, 0, -1]),
                    })
    return out


def demo_topic_items(cfg: dict) -> list[dict]:
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    outlets = ["Moneyweb", "BusinessLIVE", "Daily Maverick", "News24", "IOL", "Personal Finance",
               "Citizen", "Fin24", "FA News", "Insurance Times", "Cover", "MyBroadband"]
    out = []
    for t in cfg.get("topics", []):
        brands = [b["name"] for b in cfg["segments"][t["sector"]]["brands"]]
        weight = rnd.randint(1, 6)
        for day in range(100):
            for _ in range(rnd.randint(0, weight)):
                named = rnd.choice(brands) if rnd.random() < 0.35 else None
                title = f"[Sample] {t['name']} story" + (f" quoting {named}" if named else "")
                link = f"https://example.com/sample/topic/{t['name'].lower().replace(' ', '-')}/{day}/{rnd.randint(1, 99999)}"
                ts = now - timedelta(days=day, hours=rnd.randint(0, 20))
                out.append({"id": item_id(t["name"], link, title), "topic": t["name"], "title": title, "link": link,
                            "source": rnd.choice(outlets), "published": ts.isoformat()})
    return out


def brand_aliases(brand: dict) -> list[str]:
    """Names to look for in a headline: the brand name plus every quoted phrase in its search query."""
    names = {brand["name"].lower()} | {q.lower() for q in re.findall(r'"([^"]+)"', brand["query"])}
    for extra in brand.get("aliases", []):
        names.add(extra.lower())
    return sorted(names)


def matches(title: str, keywords: list[str]) -> bool:
    text = f" {title.lower()} "
    return any(k.lower() in text for k in keywords)


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


def build_metrics(items: list[dict], brands: list[str], cfg: dict, now: datetime) -> dict:
    cats = list(cfg["categories"].keys()) + ["Other coverage"]
    last7, last30, last1 = window(items, 7, now), window(items, 30, now), window(items, 1, now)
    cut7 = now - timedelta(days=7)
    prev7 = [i for i in window(items, 14, now) if parse(i["published"]) < cut7]

    sov7, sov30 = share_of_voice(last7, brands), share_of_voice(last30, brands)
    prev_counts = Counter(i["brand"] for i in prev7)
    sov7 = [dict(r, prev_mentions=prev_counts.get(r["brand"], 0)) for r in sov7]

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

    top_cat_7 = Counter(i.get("category", "Other coverage") for i in last7
                        if i.get("category") != "Other coverage").most_common(1)
    riser = max(sov7, key=lambda r: r["mentions"] - r["prev_mentions"])
    leader = sov7[0]
    return {
        "brands": brands,
        "categories": cats,
        "kpis": {
            "mentions_7d": len(last7),
            "mentions_prev_7d": len(prev7),
            "leader": leader["brand"],
            "leader_share_7d": leader["share"],
            "riser": riser["brand"],
            "riser_change": riser["mentions"] - riser["prev_mentions"],
            "top_category_7d": top_cat_7[0][0] if top_cat_7 else None,
            "top_category_count_7d": top_cat_7[0][1] if top_cat_7 else 0,
            "brands_tracked": len(brands),
            "new_items_24h": len(last1),
            "items_30d": len(last30),
        },
        "share_of_voice_7d": sov7,
        "share_of_voice_30d": sov30,
        "daily": {"days": days, "series": {b: [daily[b][d] for d in days] for b in brands}},
        "category_matrix": matrix,
        "sentiment_30d": sent,
        "top_outlets": [{"source": s, "mentions": n, "by_brand": dict(by_outlet[s])} for s, n in outlets],
    }


def build_report_data(items: list[dict], brands: list[str], cats: list[str], now: datetime, days: int = 90) -> dict:
    """Compact, item-level data for the last `days` days, so the page can build a
    report for any brand, competitor set and period without another download."""
    day_list = [(now - timedelta(days=d)).astimezone(SAST).date().isoformat() for d in range(days - 1, -1, -1)]
    day_ix = {d: n for n, d in enumerate(day_list)}
    b_ix = {b: n for n, b in enumerate(brands)}
    c_ix = {c: n for n, c in enumerate(cats)}
    sources: list[str] = []
    s_ix: dict[str, int] = {}
    events = []
    headlines: dict[str, list] = {b: [] for b in brands}
    for i in sorted(items, key=lambda x: x["published"], reverse=True):
        d = parse(i["published"]).astimezone(SAST).date().isoformat()
        if d not in day_ix or i["brand"] not in b_ix:
            continue
        if i["source"] not in s_ix:
            s_ix[i["source"]] = len(sources)
            sources.append(i["source"])
        cat = i.get("category", "Other coverage")
        events.append([day_ix[d], b_ix[i["brand"]], c_ix.get(cat, len(cats) - 1), i.get("sentiment", 0), s_ix[i["source"]]])
        if len(headlines[i["brand"]]) < 20:
            headlines[i["brand"]].append({"d": day_ix[d], "title": i["title"], "link": i["link"],
                                          "source": i["source"], "category": cat})
    return {"days": day_list, "sources": sources, "events": events, "headlines": headlines}


def build_topics_data(items: list[dict], topic_items: list[dict], cfg: dict, now: datetime, days: int = 90) -> dict:
    """Per topic: daily volume, which brands appear in the conversation, outlets and headlines."""
    day_list = [(now - timedelta(days=d)).astimezone(SAST).date().isoformat() for d in range(days - 1, -1, -1)]
    day_ix = {d: n for n, d in enumerate(day_list)}
    all_brands = [{"name": b["name"], "sector": seg} for seg, S in cfg["segments"].items() for b in S["brands"]]
    b_ix = {(b["name"]): n for n, b in enumerate(all_brands)}
    aliases = [(b_ix[b["name"]], brand_aliases(b)) for S in cfg["segments"].values() for b in S["brands"]]
    sources: list[str] = []
    s_ix: dict[str, int] = {}

    def src(name: str) -> int:
        if name not in s_ix:
            s_ix[name] = len(sources)
            sources.append(name)
        return s_ix[name]

    def day_of(i: dict):
        return day_ix.get(parse(i["published"]).astimezone(SAST).date().isoformat())

    out = []
    for t in cfg.get("topics", []):
        news, hits, heads = [], [], []
        seen_links = set()
        for i in sorted((x for x in topic_items if x["topic"] == t["name"]), key=lambda x: x["published"], reverse=True):
            d = day_of(i)
            if d is None:
                continue
            named = [n for n, al in aliases if matches(i["title"], al)]
            news.append([d, src(i["source"])])
            hits += [[d, n] for n in named]
            seen_links.add(i["link"])
            if len(heads) < 40:
                heads.append({"d": d, "title": i["title"], "link": i["link"], "source": i["source"],
                              "brands": [all_brands[n]["name"] for n in named]})
        # Tracked-brand coverage that mentions the topic also counts towards that brand.
        brand_heads = []
        for i in sorted(items, key=lambda x: x["published"], reverse=True):
            d = day_of(i)
            if d is None or i["link"] in seen_links or not matches(i["title"], t["keywords"]):
                continue
            hits.append([d, b_ix[i["brand"]]])
            if len(brand_heads) < 40:
                brand_heads.append({"d": d, "title": i["title"], "link": i["link"], "source": i["source"],
                                    "brands": [i["brand"]]})
        out.append({"name": t["name"], "sector": t["sector"], "keywords": t["keywords"],
                    "news": news, "brand_hits": hits, "headlines": heads, "brand_headlines": brand_heads})
    return {"days": day_list, "brands": all_brands, "sources": sources, "topics": out}


def build_search_index(items: list[dict], topic_items: list[dict], cfg: dict, now: datetime, days: int = 90) -> dict:
    """Everything collected in the last `days` days, for the search box (loaded only when someone searches)."""
    day_list = [(now - timedelta(days=d)).astimezone(SAST).date().isoformat() for d in range(days - 1, -1, -1)]
    day_ix = {d: n for n, d in enumerate(day_list)}
    rows, seen = [], set()
    for i in sorted(items + topic_items, key=lambda x: x["published"], reverse=True):
        d = day_ix.get(parse(i["published"]).astimezone(SAST).date().isoformat())
        if d is None or i["link"] in seen:
            continue
        seen.add(i["link"])
        rows.append([d, i["title"], i["source"], i.get("brand", ""), i.get("segment", ""), i.get("topic", ""), i["link"]])
    return {"days": day_list, "fields": ["d", "title", "source", "brand", "sector", "topic", "link"], "rows": rows}


# --------------------------------------------------------------------------- #
# Morning briefing
# --------------------------------------------------------------------------- #
def pct_change(now_v: int, before: int) -> str:
    if before == 0:
        return "with no coverage the week before"
    p = round(100 * (now_v - before) / before)
    if p == 0:
        return "the same as the week before"
    return f"{'up' if p > 0 else 'down'} {abs(p)}% on the week before"


def rule_based_briefing(segment: str, metrics: dict, items: list[dict], now: datetime) -> dict:
    k = metrics["kpis"]
    sov = metrics["share_of_voice_7d"]
    faller = min(sov, key=lambda r: r["mentions"] - r["prev_mentions"])
    risk = [i for i in window(items, 7, now) if i.get("category") == "Reputation & regulatory"]
    runners = " and ".join(f"{r['brand']} ({r['share']}%)" for r in sov[1:3])
    noun = {"Insure": "insurance"}.get(segment, segment.lower())
    points = [
        f"{k['mentions_7d']} news mentions across {k['brands_tracked']} {noun} brands in the past 7 days, "
        f"{pct_change(k['mentions_7d'], k['mentions_prev_7d'])}.",
        f"{k['leader']} leads share of voice with {k['leader_share_7d']}%, followed by {runners}.",
        f"Biggest riser: {k['riser']}, up {k['riser_change']} mentions week on week. "
        f"Biggest faller: {faller['brand']}, down {abs(faller['mentions'] - faller['prev_mentions'])}.",
    ]
    if k["top_category_7d"]:
        points.append(f"Most common activity this week: {k['top_category_7d']} ({k['top_category_count_7d']} items).")
    if risk:
        points.append(f"{len(risk)} reputation or regulatory items this week, involving "
                      + ", ".join(sorted({i['brand'] for i in risk})) + ".")
    return {"source": "rules", "headline": f"{k['leader']} leads {noun} share of voice this week",
            "points": points, "watch": []}


def claude_briefing(segment: str, metrics: dict, items: list[dict], cfg: dict, now: datetime) -> dict | None:
    if not os.environ.get("ANTHROPIC_API_KEY") or not cfg["claude"].get("enabled_if_key_present", True):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    recent = sorted(window(items, 7, now), key=lambda i: i["published"], reverse=True)[:150]
    payload = {
        "sector": segment,
        "kpis": metrics["kpis"],
        "share_of_voice_7d": metrics["share_of_voice_7d"],
        "headlines_last_7_days": [
            {"brand": i["brand"], "title": i["title"], "source": i["source"],
             "category": i.get("category"), "date": i["published"][:10]} for i in recent
        ],
    }
    system = (
        "You write an independent morning briefing on marketing and PR activity in South African financial "
        "services, for marketers across the industry. Treat every brand even-handedly. Use British English, "
        "plain language and the active voice. No exclamation marks. Keep each point to one idea and at most "
        "two sentences. Focus on campaigns, sponsorships, awards, spokespeople, launches, share of voice "
        "shifts and reputation risks. Only state facts found in the data you are given."
    )
    schema = {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "One-line summary of the day, under 15 words."},
            "points": {"type": "array", "items": {"type": "string"}, "description": "4 to 6 briefing points."},
            "watch": {"type": "array", "items": {"type": "string"}, "description": "1 to 3 things worth watching."},
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
HEAD_FILL = PatternFill("solid", fgColor=SLATE)
HEAD_FONT = Font(bold=True, color=WHITE, name=FONT, size=10)
BODY_FONT = Font(name=FONT, size=10, color=INK)
THIN = Border(bottom=Side(style="thin", color="DDE1E6"))
RULE = Border(bottom=Side(style="medium", color=ACCENT))


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
            if cell.hyperlink is None:
                cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column_letter in wrap_cols)


def title_block(ws, title: str, subtitle: str):
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, bold=True, size=16, color=INK)
    ws["A2"] = subtitle
    ws["A2"].font = Font(name=FONT, italic=True, size=10, color=MUTED)
    ws.sheet_properties.tabColor = ACCENT


def write_segment_sheets(wb, seg: str, S: dict):
    m = S["metrics"]

    ws = wb.create_sheet(f"{seg} share of voice")
    title_block(ws, f"{seg}: share of voice", "Share = brand mentions ÷ all mentions in this sector.")
    ws.append([])
    ws.append(["Brand", "Mentions (7d)", "Previous 7d", "Change", "Share 7d (%)", "Mentions (30d)", "Share 30d (%)"])
    s30 = {r["brand"]: r for r in m["share_of_voice_30d"]}
    for row in m["share_of_voice_7d"]:
        ws.append([row["brand"], row["mentions"], row["prev_mentions"], row["mentions"] - row["prev_mentions"],
                   row["share"], s30[row["brand"]]["mentions"], s30[row["brand"]]["share"]])
    style_table(ws, 4, 7, [20, 14, 13, 10, 13, 15, 13], wrap_cols=())
    chart = BarChart()
    chart.type, chart.title = "bar", "Share of voice, last 30 days (%)"
    chart.add_data(Reference(ws, min_col=7, min_row=4, max_row=ws.max_row), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=5, max_row=ws.max_row))
    chart.legend, chart.height, chart.width = None, 9, 16
    chart.series[0].graphicalProperties.solidFill = ACCENT
    chart.series[0].graphicalProperties.line.solidFill = ACCENT
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

    ws = wb.create_sheet(f"{seg} daily trend")
    title_block(ws, f"{seg}: daily coverage", "Mentions per day, last 30 days.")
    ws.append([])
    ws.append(["Date"] + m["brands"])
    for n, d in enumerate(m["daily"]["days"]):
        ws.append([d] + [m["daily"]["series"][b][n] for b in m["brands"]])
    style_table(ws, 4, len(m["brands"]) + 1, [12] + [13] * len(m["brands"]), wrap_cols=())


def build_excel(data: dict, items: list[dict], cfg: dict, path: Path):
    updated = data["meta"]["updated_local"]
    segs = data["segments"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Briefing"
    title_block(ws, cfg["tracker_name"], f"Updated {updated} SAST" + ("  ·  SAMPLE DATA" if data["meta"]["demo"] else ""))
    r = 4
    for seg, S in segs.items():
        k, b = S["metrics"]["kpis"], S["briefing"]
        c = ws.cell(row=r, column=1, value=f"{seg.upper()}  ·  {b['headline']}")
        c.font, c.border = Font(name=FONT, bold=True, size=13, color=INK), RULE
        r += 2
        for p in b["points"]:
            cell = ws.cell(row=r, column=1, value="•  " + p)
            cell.alignment, cell.font = Alignment(wrap_text=True, vertical="top"), BODY_FONT
            r += 1
        for p in b.get("watch") or []:
            ws.cell(row=r, column=1, value="→  " + p).font = Font(name=FONT, size=10, color=ACCENT)
            r += 1
        r += 1
        for label, val in [("Mentions (7 days)", k["mentions_7d"]),
                           ("Previous 7 days", k["mentions_prev_7d"]),
                           ("Share of voice leader", f"{k['leader']} ({k['leader_share_7d']}%)"),
                           ("Biggest riser", f"{k['riser']} (+{k['riser_change']})"),
                           ("Brands tracked", k["brands_tracked"])]:
            ws.cell(row=r, column=1, value=label).font = Font(name=FONT, size=10, color=MUTED)
            ws.cell(row=r, column=2, value=val).font = Font(name=FONT, bold=True, size=10, color=INK)
            r += 1
        r += 2
    ws.column_dimensions["A"].width = 110
    ws.column_dimensions["B"].width = 28

    for seg, S in segs.items():
        write_segment_sheets(wb, seg, S)

    ws = wb.create_sheet("Coverage log")
    title_block(ws, "Coverage log", f"Every tracked item, newest first. Rolling {cfg['history_days']} days. Filter by sector or brand.")
    ws.append([])
    ws.append(["Date", "Sector", "Brand", "Headline", "Outlet", "Category", "Tone", "Link"])
    for i in sorted(items, key=lambda x: x["published"], reverse=True):
        ws.append([parse(i["published"]).astimezone(SAST).strftime("%Y-%m-%d"), i["segment"], i["brand"], i["title"],
                   i["source"], i.get("category", ""), TONE[i.get("sentiment", 0)], i["link"]])
        link = ws.cell(row=ws.max_row, column=8)
        link.hyperlink = i["link"]
        link.font = Font(name=FONT, size=10, color=ACCENT, underline="single")
    style_table(ws, 4, 8, [12, 10, 18, 70, 22, 28, 10, 40], wrap_cols=("D",))

    ws = wb.create_sheet("Tone")
    title_block(ws, "Headline tone", "Keyword-based tone of headlines, last 30 days. A signal, not a verdict.")
    ws.append([])
    ws.append(["Sector", "Brand", "Positive", "Neutral", "Negative", "Net score"])
    for seg, S in segs.items():
        for b in S["metrics"]["brands"]:
            s = S["metrics"]["sentiment_30d"][b]
            tot = sum(s.values()) or 1
            ws.append([seg, b, s["positive"], s["neutral"], s["negative"], round(100 * (s["positive"] - s["negative"]) / tot)])
    style_table(ws, 4, 6, [10, 20, 11, 11, 11, 11], wrap_cols=())

    ws = wb.create_sheet("Top outlets")
    title_block(ws, "Top outlets", "Publications carrying the most tracked coverage, last 30 days.")
    ws.append([])
    ws.append(["Sector", "Outlet", "Mentions", "Top brand in outlet", "Top brand mentions"])
    for seg, S in segs.items():
        for o in S["metrics"]["top_outlets"]:
            top = max(o["by_brand"].items(), key=lambda kv: kv[1]) if o["by_brand"] else ("", 0)
            ws.append([seg, o["source"], o["mentions"], top[0], top[1]])
    style_table(ws, 4, 5, [10, 28, 11, 22, 18], wrap_cols=())

    ws = wb.create_sheet("Topics")
    title_block(ws, "Tracked topics", "Articles per topic and the brands most linked to each. Edit the topic list in config.json.")
    ws.append([])
    ws.append(["Topic", "Sector", "Articles (7d)", "Articles (30d)", "Articles (90d)", "Top brands (30d)"])
    T = data["topics"]
    n_days = len(T["days"])
    for t in T["topics"]:
        counts = [sum(1 for e in t["news"] if e[0] >= n_days - p) for p in (7, 30, 90)]
        hits = Counter(T["brands"][b]["name"] for d, b in t["brand_hits"] if d >= n_days - 30)
        ws.append([t["name"], "Insurance" if t["sector"] == "Insure" else "Wealth", *counts,
                   ", ".join(f"{b} ({c})" for b, c in hits.most_common(3))])
    style_table(ws, 4, 6, [26, 11, 13, 13, 13, 60], wrap_cols=("F",))

    ws = wb.create_sheet("Social tracker")
    title_block(ws, "Social followers", "Manual input: add rows to data/social.csv (date, brand, platform, followers).")
    ws.append([])
    ws.append(["Brand", "Platform", "Followers", "Change since last entry", "As at"])
    for s in data["social"]:
        ws.append([s["brand"], s["platform"], s["followers"], s["change"], s["date"]])
    style_table(ws, 4, 5, [18, 14, 13, 22, 12], wrap_cols=())

    ws = wb.create_sheet("Campaign log")
    title_block(ws, "Campaign and activity log", "Manual input: add rows to data/campaigns.csv when you spot a campaign, sponsorship or event.")
    ws.append([])
    cols = ["date_spotted", "brand", "campaign_or_activity", "channel", "type", "link", "notes"]
    ws.append(["Date spotted", "Brand", "Campaign or activity", "Channel", "Type", "Link", "Notes"])
    for c in data["campaigns"]:
        ws.append([c.get(k, "") for k in cols])
    style_table(ws, 4, 7, [13, 16, 40, 16, 16, 36, 40])

    ws = wb.create_sheet("How it works")
    title_block(ws, "How this tracker works", "Built with Claude Code.")
    notes = [
        "An independent view of marketing and PR activity in South African financial services. Not affiliated with any brand shown.",
        "Two sectors: Wealth and Insure. Share of voice is calculated within each sector.",
        "Refreshes automatically every morning at about 05:15 SAST.",
        "Coverage comes from Google News for each brand's search terms in config.json.",
        "Categories and tone are keyword-based. Edit the keyword lists in config.json to tune them.",
        "Topics are collected each morning as their own news searches. Brands are linked to a topic when a headline names them.",
        "The online dashboard also builds competitor reports (PDF or Excel) and searches all coverage.",
        "Social followers and campaigns are manual inputs in the data folder.",
        "Mentions are news items, not reach or advertising value equivalent (AVE).",
    ]
    for n, t in enumerate(notes, start=4):
        ws.cell(row=n, column=1, value="•  " + t).font = BODY_FONT
    ws.column_dimensions["A"].width = 120

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
        items, topic_items, demo = demo_items(cfg), demo_topic_items(cfg), True
    else:
        # A live run replaces any sample data.
        known = {} if history.get("demo") else {i["id"]: i for i in history["items"] if "segment" in i}
        # First live run: look further back so the 30- and 90-day views start with data.
        lookback = cfg["lookback_days_per_run"] if known else cfg.get("backfill_days", 30)
        for seg_name, seg in cfg["segments"].items():
            for brand in seg["brands"]:
                try:
                    for it in fetch_google_news(brand, cfg, lookback):
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

        known_t = {} if history.get("demo") else {i["id"]: i for i in history.get("topic_items", [])}
        t_lookback = cfg["lookback_days_per_run"] if known_t else cfg.get("backfill_days", 30)
        for topic in cfg.get("topics", []):
            try:
                for it in fetch_google_news({"name": topic["name"], "query": topic["query"]}, cfg, t_lookback):
                    it["topic"] = it.pop("brand")
                    it["id"] = item_id(topic["name"], it["link"], it["title"])
                    known_t.setdefault(it["id"], it)
            except Exception as exc:
                errors.append(f"Topic {topic['name']}: {exc}")
                print(f"Fetch failed for topic {topic['name']}: {exc}", file=sys.stderr)
        topic_items = [i for i in known_t.values() if parse(i["published"]) >= cutoff]
        demo = False
        if not items and errors:
            print("No data collected; leaving previous outputs untouched.", file=sys.stderr)
            return 1

    store.write_text(json.dumps({"demo": demo, "items": items, "topic_items": topic_items},
                                ensure_ascii=False, indent=1), encoding="utf-8")

    segments = {}
    for seg_name, seg in cfg["segments"].items():
        seg_items = [i for i in items if i["segment"] == seg_name]
        brands = [b["name"] for b in seg["brands"]]
        metrics = build_metrics(seg_items, brands, cfg, now)
        briefing = (None if demo else claude_briefing(seg_name, metrics, seg_items, cfg, now)) \
            or rule_based_briefing(seg_name, metrics, seg_items, now)
        recent = sorted(window(seg_items, 30, now), key=lambda i: i["published"], reverse=True)
        segments[seg_name] = {"briefing": briefing, "metrics": metrics, "coverage": recent[:300],
                              "report": build_report_data(seg_items, brands, metrics["categories"], now)}

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
    data["topics"] = build_topics_data(items, topic_items, cfg, now)
    SITE.mkdir(exist_ok=True)
    (SITE / "search.json").write_text(json.dumps(build_search_index(items, topic_items, cfg, now),
                                                 ensure_ascii=False), encoding="utf-8")
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    build_excel(data, items, cfg, SITE / WORKBOOK)
    print(f"Done: {len(items)} items, {len(errors)} fetch errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
