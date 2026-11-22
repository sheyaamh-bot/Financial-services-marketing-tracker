# Financial Services Marketing Tracker

An independent, daily view of marketing and PR activity across South African financial services. Built with Claude Code.

It tracks two sectors:

- **Wealth:** Alexander Forbes, Allan Gray, Brenthurst, Citadel, Coronation, Discovery, Investec, Liberty, Momentum, Ninety One, Old Mutual, PSG Wealth, Sanlam (incl. Glacier) and Sygnia.
- **Insurance:** Aon SA, Discovery Insure, Hollard, Indwe, King Price, Marsh SA, MiWay, Old Mutual Insure, OUTsurance, PSG Insure and Santam.

Share of voice is calculated within each sector. Every morning it produces:

- **A dashboard** (`site/index.html`) with a Wealth | Insurance switch and a picker to compare any two brands. Add `#insurance` to the link to open the Insurance view.
- **An Excel workbook** (`site/Financial_Services_Marketing_Tracker.xlsx`), downloadable from the dashboard.

## What it tracks

| Area | Source | Updates |
|---|---|---|
| Share of voice (7 and 30 days) | Google News, per brand | Automatic |
| Daily coverage trend | Google News | Automatic |
| Activity by type: campaigns, sponsorships, awards, appointments, launches, results, CSR, thought leadership, digital, deals, reputation | Headline keywords | Automatic |
| Headline tone | Headline keywords | Automatic |
| Top outlets | Google News | Automatic |
| Morning briefing | Rules, or Claude if an API key is set | Automatic |
| Campaign and activity log | `data/campaigns.csv` | Manual |
| Social followers | `data/social.csv` | Manual |

Edit `config.json` to add or remove brands, change search terms or tune the category keywords.

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
- Categories and tone come from headline keywords. Treat them as signals and tune `config.json` over time.
- Google News RSS suits monitoring and demonstration. For commercial redistribution, use a licensed media-monitoring feed.
