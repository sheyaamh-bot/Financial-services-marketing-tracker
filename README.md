# Financial Services Marketing Tracker

An independent, daily view of marketing and PR activity across South African financial services. Built with Claude Code.

It tracks two sectors:

- **Wealth:** Alexander Forbes, Allan Gray, Brenthurst, Citadel, Coronation, Discovery, Investec, Liberty, Momentum, Ninety One, Old Mutual, PSG Wealth, Sanlam (incl. Glacier) and Sygnia.
- **Insurance:** Aon SA, Discovery Insure, Hollard, Indwe, King Price, Marsh SA, MiWay, Old Mutual Insure, OUTsurance, PSG Insure and Santam.

Share of voice is calculated within each sector. Every morning it produces:

- **A dashboard** (`site/index.html`) with a Wealth | Insurance switch and a picker to compare any two brands. Add `#insurance` to the link to open the Insurance view.
- **An Excel workbook** (`site/Financial_Services_Marketing_Tracker.xlsx`), downloadable from the dashboard.

## What people can do with it

- **Daily dashboard (Wealth and Insurance tabs).** Share of voice, coverage trends, activity mix, tone, top outlets and a morning briefing.
- **Competitor report.** Pick your brand, up to six competitors and a period (7, 30 or 90 days). The report shows how you're tracking: a summary, head-to-head table, share of voice in the group, coverage over time, activity mix, tone, outlet gaps (publications covering competitors but not you) and the latest competitor headlines. Download it as a PDF or Excel file, or copy a link that reopens the same report.
- **Topics and search.** Tracked topics (for example retirement, tax-free savings, fire risk, commercial insurance) are collected every morning as their own news searches. Each shows its volume over time, which brands own the conversation, top outlets and headlines. A search box finds any word across everything collected in the last 90 days.

Every view has its own link, for example `#report?sector=wealth&you=Allan Gray&vs=Coronation|Ninety One&days=30` or `#topics?topic=Fire risk`.

## What it tracks

| Area | Source | Updates |
|---|---|---|
| Share of voice (7 and 30 days) | Google News, per brand | Automatic |
| Daily coverage trend | Google News | Automatic |
| Activity by type: campaigns, sponsorships, awards, appointments, launches, results, CSR, thought leadership, digital, deals, reputation | Headline keywords | Automatic |
| Headline tone | Headline keywords | Automatic |
| Top outlets | Google News | Automatic |
| Morning briefing | Rules, or Claude if an API key is set | Automatic |
| Tracked topics | Google News, per topic | Automatic |
| Campaign and activity log | `data/campaigns.csv` | Manual |
| Social followers | `data/social.csv` | Manual |

Edit `config.json` to add or remove brands, change search terms or tune the category keywords.

To add a topic, add an entry under `topics` in `config.json`:

```json
{"name": "Medical aid", "sector": "Insure",
 "query": "\"medical aid\" OR \"medical scheme\" South Africa",
 "keywords": ["medical aid", "medical scheme"]}
```

`query` is the daily news search. `keywords` link tracked brands' own headlines to the topic.

## How it runs

`.github/workflows/daily-update.yml` runs every day at 05:17 SAST. It:

1. Runs `tracker.py` to collect coverage and rebuild the Excel file and dashboard data.
2. Commits the updated files to the repository.
3. Publishes the dashboard to GitHub Pages.

## Set-up (one-off)

1. In **Settings → Pages**, set **Source** to **GitHub Actions**.
2. In **Actions → Daily tracker update → Run workflow**, run it once to replace the sample data with live coverage.
3. Optional: in **Settings → Secrets and variables → Actions**, add `ANTHROPIC_API_KEY` so Claude writes the morning briefing.

## Run it locally

```bash
pip install -r requirements.txt
python tracker.py          # live run
python tracker.py --demo   # sample data, no network
python -m http.server -d site 8000   # open http://localhost:8000
```

## Logging campaigns and social numbers

Add rows to the CSV files in `data/`, either in GitHub's web editor or in Excel (save as CSV). They appear on the dashboard and in the workbook after the next run.

```csv
date_spotted,brand,campaign_or_activity,channel,type,link,notes
2026-11-20,Sanlam,Summer savings campaign,TV and digital,Campaign,https://...,Fronted by brand ambassador
```

```csv
date,brand,platform,followers,notes
2026-11-01,Allan Gray,LinkedIn,52000,
```

## Limits to know

- Not affiliated with any brand shown.
- Mentions are news items. They are not reach, impressions or advertising value equivalent (AVE).
- The first live run looks back 30 days. After that, history builds daily, so 90-day views fill up over three months.
- Brands are linked to a topic only when a headline names them.
- Categories and tone come from headline keywords. Treat them as signals and tune `config.json` over time.
- Google News RSS suits monitoring and demonstration. For commercial redistribution, use a licensed media-monitoring feed.
