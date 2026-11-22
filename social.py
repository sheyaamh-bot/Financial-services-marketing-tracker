"""Social media tracking for the Financial Services Marketing Tracker.

What it collects, per brand:
  * Accounts: found automatically on each brand's own website (links to YouTube,
    Instagram, LinkedIn and Facebook), cached in data/social_accounts.json.
    Anything set under a brand's "social" key in config.json wins.
  * YouTube: new videos and views from the channel's public feed (no set-up).
    With a YOUTUBE_API_KEY it also adds subscribers and full video statistics.
  * Instagram: followers, posts and engagement through Meta's Business Discovery
    API. Needs IG_USER_ID and IG_ACCESS_TOKEN (an Instagram business account).
  * LinkedIn: followers logged by hand in data/social.csv (LinkedIn offers no
    public data for other companies' pages).
  * Facebook and Instagram ads: a link to each brand's live ads in Meta's Ad Library.

Every network call is optional: a failure is recorded and the daily run carries on.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REDISCOVER_DAYS = 30

PATTERNS = {
    "youtube": re.compile(r"youtube\.com/(@[\w.\-]+|channel/UC[\w\-]{22}|c/[\w.\-]+|user/[\w.\-]+)", re.I),
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I),
    "linkedin": re.compile(r"linkedin\.com/company/([\w\-%.]+)", re.I),
    "facebook": re.compile(r"facebook\.com/([\w.\-]{2,})", re.I),
}
SKIP = {
    "instagram": {"p", "reel", "reels", "explore", "accounts", "stories", "tv", "share"},
    "facebook": {"sharer", "sharer.php", "share", "share.php", "tr", "plugins", "dialog", "login", "pages", "groups",
                 "profile.php", "watch", "events", "people", "hashtag", "ads", "business", "policies", "privacy"},
}


def _get(url: str, **kw) -> requests.Response:
    time.sleep(1)
    return requests.get(url, timeout=25, headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-ZA,en;q=0.9"}, **kw)


# --------------------------------------------------------------------------- #
# Account discovery
# --------------------------------------------------------------------------- #
EXTRA_PAGES = ["/contact-us", "/contact", "/about-us", "/about"]


def discover_from_website(url: str, extra_urls: list[str] | None = None) -> dict:
    """Reads the brand's homepage (and, if links are missing, its contact and about pages)
    and takes the most-linked account on each platform."""
    hits = {p: [] for p in PATTERNS}
    pages = [url] + list(extra_urls or [])
    base = url.rstrip("/")
    pages += [base + p for p in EXTRA_PAGES]
    first_error = None
    for n, page in enumerate(pages):
        if n > 0 and all(hits[p] for p in ("youtube", "instagram", "linkedin")):
            break
        try:
            html = _get(page).text
        except Exception as exc:
            first_error = first_error or exc
            continue
        for platform, rx in PATTERNS.items():
            hits[platform] += [m.group(1).rstrip("/.") for m in rx.finditer(html)
                               if m.group(1).rstrip("/.").lower() not in SKIP.get(platform, set())]
    found = {p: Counter(h).most_common(1)[0][0] for p, h in hits.items() if h}
    if not found and first_error:
        raise first_error
    return found


ALLOWED_SUFFIX = {"insurance", "insure", "wealth", "management", "group", "sa", "south", "africa", "african",
                  "investments", "investment", "investors", "fund", "funds", "managers", "asset", "limited", "ltd",
                  "official", "tv", "financial", "services", "life", "holdings", "za"}


def channel_matches(brand: str, title: str) -> bool:
    """True only when the channel name is the brand name, optionally followed by generic
    words such as "Insurance" or "Wealth Management" (so "Coronation Avenue Church" fails)."""
    b = re.sub(r"\bsa\b", "", brand.lower()).split()
    t = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return t[:len(b)] == b and all(w in ALLOWED_SUFFIX for w in t[len(b):])


def youtube_search_channel(brand: str) -> str | None:
    """Finds a channel through YouTube's own search, accepted only when the channel's
    name contains the brand name (so a fan or unrelated channel isn't picked up)."""
    q = urllib.parse.urlencode({"search_query": brand + " South Africa", "sp": "EgIQAg%3D%3D"})
    html = _get("https://www.youtube.com/results?" + q.replace("%253D", "%3D")).text
    for cid, title in re.findall(r'"channelId":"(UC[\w\-]{22})","title":\{"simpleText":"([^"]+)"', html)[:5]:
        if channel_matches(brand, title):
            return "channel/" + cid
    return None


def resolve_accounts(cfg: dict, data_dir: Path, now: datetime, errors: list[str]) -> dict:
    path = data_dir / "social_accounts.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = {}
    for seg in cfg["segments"].values():
        for b in seg["brands"]:
            name = b["name"]
            entry = cache.get(name, {})
            stale = not entry.get("discovered_at") or \
                datetime.fromisoformat(entry["discovered_at"]) < now - timedelta(days=REDISCOVER_DAYS) or \
                not all(entry.get(k) for k in ("youtube", "instagram", "linkedin"))  # retry gaps daily
            if stale and b.get("website"):
                try:
                    found = discover_from_website(b["website"], b.get("social_pages"))
                    entry = {**found, "discovered_at": now.isoformat(), "source": b["website"]}
                except Exception as exc:
                    errors.append(f"Social accounts for {name}: {str(exc)[:160]}")
                    entry = {**entry, "discovered_at": now.isoformat(), "source": b.get("website", "")}
                if not entry.get("youtube"):
                    try:
                        ch = youtube_search_channel(name)
                        if ch:
                            entry["youtube"], entry["youtube_source"] = ch, "YouTube search"
                    except Exception as exc:
                        errors.append(f"YouTube search for {name}: {str(exc)[:160]}")
            cache[name] = entry
            # A brand's "social" settings in config.json win. "-" means "don't track this platform".
            overrides = {k: (None if v == "-" else v) for k, v in (b.get("social") or {}).items() if v}
            out[name] = {**{k: entry.get(k) for k in PATTERNS}, **overrides,
                         "manual": sorted(overrides), "source": entry.get("source")}
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def account_urls(acc: dict) -> dict:
    urls = {}
    if acc.get("youtube"):
        urls["youtube"] = "https://www.youtube.com/" + acc["youtube"]
    if acc.get("instagram"):
        urls["instagram"] = "https://www.instagram.com/" + acc["instagram"]
    if acc.get("linkedin"):
        urls["linkedin"] = "https://www.linkedin.com/company/" + acc["linkedin"]
    if acc.get("facebook"):
        urls["facebook"] = "https://www.facebook.com/" + acc["facebook"]
    return urls


def ad_library_url(brand: str) -> str:
    q = urllib.parse.urlencode({"active_status": "active", "ad_type": "all", "country": "ZA", "q": brand,
                                "search_type": "keyword_unordered", "media_type": "all"})
    return "https://www.facebook.com/ads/library/?" + q


# --------------------------------------------------------------------------- #
# YouTube
# --------------------------------------------------------------------------- #
def youtube_channel_id(ref: str, key: str | None) -> str | None:
    if ref.startswith("channel/"):
        return ref.split("/", 1)[1]
    if key:
        params = {"part": "id", "key": key}
        if ref.startswith("@"):
            params["forHandle"] = ref
        elif ref.startswith("user/"):
            params["forUsername"] = ref.split("/", 1)[1]
        else:
            params = None
        if params:
            r = _get("https://www.googleapis.com/youtube/v3/channels", params=params).json()
            if r.get("items"):
                return r["items"][0]["id"]
    # No key (or a /c/ address): read the channel id from the public channel page.
    html = _get("https://www.youtube.com/" + ref).text
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w\-]{22})"', html) or \
        re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w\-]{22})"', html)
    return m.group(1) if m else None


def youtube_stats(ref: str, key: str | None, now: datetime) -> dict:
    cid = youtube_channel_id(ref, key)
    if not cid:
        raise ValueError(f"channel not found for {ref}")
    cutoff = now - timedelta(days=30)
    out = {"channel_id": cid, "url": f"https://www.youtube.com/channel/{cid}"}
    videos = []
    if key:
        ch = _get("https://www.googleapis.com/youtube/v3/channels",
                  params={"part": "statistics,contentDetails,snippet", "id": cid, "key": key}).json()["items"][0]
        st = ch["statistics"]
        out.update(title=ch["snippet"]["title"],
                   subscribers=None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
                   total_videos=int(st.get("videoCount", 0)))
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = _get("https://www.googleapis.com/youtube/v3/playlistItems",
                  params={"part": "contentDetails", "playlistId": uploads, "maxResults": 50, "key": key}).json()
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if ids:
            vs = _get("https://www.googleapis.com/youtube/v3/videos",
                      params={"part": "snippet,statistics", "id": ",".join(ids), "key": key}).json()
            for v in vs.get("items", []):
                videos.append({"title": v["snippet"]["title"], "url": f"https://www.youtube.com/watch?v={v['id']}",
                               "published": v["snippet"]["publishedAt"],
                               "views": int(v["statistics"].get("viewCount", 0)),
                               "likes": int(v["statistics"].get("likeCount", 0) or 0)})
    else:
        feed = _get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        feed.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
              "yt": "http://www.youtube.com/xml/schemas/2015"}
        root = ET.fromstring(feed.content)
        out["title"] = root.findtext("a:title", default="", namespaces=ns)
        for e in root.findall("a:entry", ns):
            stats = e.find("media:group/media:community/media:statistics", ns)
            rating = e.find("media:group/media:community/media:starRating", ns)
            videos.append({"title": e.findtext("a:title", default="", namespaces=ns),
                           "url": e.find("a:link", ns).get("href"),
                           "published": e.findtext("a:published", default="", namespaces=ns),
                           "views": int(stats.get("views", 0)) if stats is not None else 0,
                           "likes": int(rating.get("count", 0)) if rating is not None else 0})
    recent = [v for v in videos if v["published"] and datetime.fromisoformat(v["published"].replace("Z", "+00:00")) >= cutoff]
    recent.sort(key=lambda v: v["published"], reverse=True)
    out.update(videos_30d=len(recent), views_30d=sum(v["views"] for v in recent),
               top_video=max(recent, key=lambda v: v["views"]) if recent else None,
               latest=sorted(videos, key=lambda v: v["published"], reverse=True)[:5])
    return out


# --------------------------------------------------------------------------- #
# Instagram (Business Discovery)
# --------------------------------------------------------------------------- #
def instagram_stats(username: str, ig_user_id: str, token: str, version: str, now: datetime) -> dict:
    fields = (f"business_discovery.username({username})"
              "{username,name,followers_count,media_count,"
              "media.limit(40){timestamp,like_count,comments_count,media_type,permalink,caption}}")
    r = _get(f"https://graph.facebook.com/{version}/{ig_user_id}", params={"fields": fields, "access_token": token})
    body = r.json()
    if "error" in body:
        raise ValueError(body["error"].get("message", "Instagram error"))
    bd = body["business_discovery"]
    cutoff = now - timedelta(days=30)
    posts = []
    for m in bd.get("media", {}).get("data", []):
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        posts.append({"date": ts.isoformat(), "url": m.get("permalink"), "type": m.get("media_type"),
                      "likes": m.get("like_count", 0) or 0, "comments": m.get("comments_count", 0) or 0,
                      "caption": (m.get("caption") or "")[:140]})
    recent = [p for p in posts if datetime.fromisoformat(p["date"]) >= cutoff]
    eng = [p["likes"] + p["comments"] for p in recent]
    return {"username": bd.get("username", username), "followers": bd.get("followers_count"),
            "total_posts": bd.get("media_count"), "posts_30d": len(recent),
            "avg_engagement_30d": round(sum(eng) / len(eng)) if eng else 0,
            "top_post": max(recent, key=lambda p: p["likes"] + p["comments"]) if recent else None,
            "url": f"https://www.instagram.com/{bd.get('username', username)}"}


# --------------------------------------------------------------------------- #
# Collect everything
# --------------------------------------------------------------------------- #
def linkedin_from_log(rows: list[dict]) -> dict:
    by_brand: dict[str, list] = {}
    for r in rows:
        if (r.get("platform") or "").strip().lower() != "linkedin":
            continue
        try:
            by_brand.setdefault(r["brand"].strip(), []).append((r["date"].strip(), int(float(r["followers"]))))
        except (KeyError, ValueError):
            continue
    out = {}
    for b, vals in by_brand.items():
        vals.sort()
        latest, prev = vals[-1], (vals[-2] if len(vals) > 1 else None)
        out[b] = {"followers": latest[1], "date": latest[0], "change": latest[1] - prev[1] if prev else None,
                  "previous_date": prev[0] if prev else None, "history": vals[-12:]}
    return out


def collect(cfg: dict, data_dir: Path, linkedin_rows: list[dict], now: datetime, demo: bool = False) -> dict:
    errors: list[str] = []
    yt_key = os.environ.get("YOUTUBE_API_KEY") or None
    ig_id, ig_token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    version = (cfg.get("social") or {}).get("graph_api_version", "v21.0")
    if demo:
        return demo_social(cfg, now, linkedin_rows)

    accounts = resolve_accounts(cfg, data_dir, now, errors)
    hist_path = data_dir / "social_history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else {}
    today = now.date().isoformat()
    linkedin = linkedin_from_log(linkedin_rows)
    brands = {}
    for seg_name, seg in cfg["segments"].items():
        for b in seg["brands"]:
            name, acc = b["name"], accounts[b["name"]]
            row = {"brand": name, "sector": seg_name, "accounts": {k: acc.get(k) for k in PATTERNS},
                   "account_urls": account_urls(acc), "manual": acc.get("manual", []),
                   "ad_library": ad_library_url(name), "linkedin": linkedin.get(name)}
            if acc.get("youtube"):
                try:
                    row["youtube"] = youtube_stats(acc["youtube"], yt_key, now)
                except Exception as exc:
                    errors.append(f"YouTube {name}: {exc}")
            if acc.get("instagram") and ig_id and ig_token:
                try:
                    row["instagram"] = instagram_stats(acc["instagram"], ig_id, ig_token, version, now)
                except Exception as exc:
                    errors.append(f"Instagram {name}: {exc}")
            snap = history.setdefault(name, {})
            snap[today] = {"yt_subscribers": (row.get("youtube") or {}).get("subscribers"),
                           "ig_followers": (row.get("instagram") or {}).get("followers")}
            # Change over ~30 days from the stored daily snapshots.
            past = [d for d in sorted(snap) if d <= (now - timedelta(days=30)).date().isoformat()]
            ref = snap[past[-1]] if past else (snap[sorted(snap)[0]] if len(snap) > 1 else None)
            for k, field in (("youtube", "yt_subscribers"), ("instagram", "ig_followers")):
                if row.get(k) and ref and ref.get(field) is not None and snap[today].get(field) is not None:
                    row[k]["change_30d"] = snap[today][field] - ref[field]
            brands[name] = row
    # Keep a year of daily snapshots.
    cutoff = (now - timedelta(days=366)).date().isoformat()
    for name in history:
        history[name] = {d: v for d, v in history[name].items() if d >= cutoff}
    hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    return {"updated": now.isoformat(), "youtube_mode": "api" if yt_key else "feed",
            "instagram_enabled": bool(ig_id and ig_token), "errors": errors, "brands": brands}


def demo_social(cfg: dict, now: datetime, linkedin_rows: list[dict]) -> dict:
    rnd = random.Random(11)
    brands = {}
    for seg_name, seg in cfg["segments"].items():
        for b in seg["brands"]:
            n = b["name"]
            slug = re.sub(r"[^a-z0-9]", "", n.lower())
            vids = [{"title": f"[Sample] {n} video {i + 1}", "url": "https://www.youtube.com/",
                     "published": (now - timedelta(days=rnd.randint(0, 40))).isoformat(),
                     "views": rnd.randint(200, 40000), "likes": rnd.randint(5, 900)} for i in range(rnd.randint(0, 8))]
            recent = [v for v in vids if datetime.fromisoformat(v["published"]) >= now - timedelta(days=30)]
            posts = rnd.randint(2, 30)
            brands[n] = {
                "brand": n, "sector": seg_name,
                "accounts": {"youtube": f"@{slug}", "instagram": slug, "linkedin": slug, "facebook": slug},
                "account_urls": account_urls({"youtube": f"@{slug}", "instagram": slug, "linkedin": slug, "facebook": slug}),
                "manual": [], "ad_library": ad_library_url(n),
                "youtube": {"title": n, "url": "https://www.youtube.com/", "subscribers": rnd.randint(500, 90000),
                            "change_30d": rnd.randint(-50, 900), "videos_30d": len(recent),
                            "views_30d": sum(v["views"] for v in recent),
                            "top_video": max(recent, key=lambda v: v["views"]) if recent else None,
                            "latest": sorted(vids, key=lambda v: v["published"], reverse=True)[:5]},
                "instagram": {"username": slug, "url": "https://www.instagram.com/", "followers": rnd.randint(2000, 250000),
                              "change_30d": rnd.randint(-200, 4000), "posts_30d": posts,
                              "avg_engagement_30d": rnd.randint(20, 1500),
                              "top_post": {"url": "https://www.instagram.com/", "likes": rnd.randint(100, 5000),
                                           "comments": rnd.randint(0, 300), "caption": f"[Sample] {n} post",
                                           "date": now.isoformat(), "type": "IMAGE"}},
                "linkedin": {"followers": rnd.randint(5000, 400000), "change": rnd.randint(-100, 6000),
                             "date": now.date().isoformat(), "previous_date": None, "history": []},
            }
    return {"updated": now.isoformat(), "youtube_mode": "sample", "instagram_enabled": True, "errors": [],
            "brands": brands, "demo": True}
