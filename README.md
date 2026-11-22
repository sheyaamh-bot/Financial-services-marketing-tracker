# PSG Marketing & PR Competitor Tracker

A daily tracker of competitor marketing and PR activity in South African financial services. It tracks two competitor sets:

- **Wealth:** PSG Wealth vs Sanlam (incl. Glacier), Old Mutual, Discovery, Momentum, Liberty, Investec, Allan Gray, Coronation, Ninety One, Alexander Forbes, Citadel, Sygnia and Brenthurst.
- **Insure:** PSG Insure vs Santam, OUTsurance, Hollard, Discovery Insure, Old Mutual Insure, King Price, MiWay, Indwe, Aon SA and Marsh SA.

Share of voice is calculated within each set. Every morning it produces:

- **A dashboard** (`site/index.html`) in PSG brand colours, with a Wealth | Insure switch. Add `#insure` to the link to open the Insure view.
- **An Excel workbook** (`site/PSG_Competitor_Tracker.xlsx`), downloadable from the dashboard.

Built with Claude Code.

## What it tracks

| Area | Source | Updates |
|---|---|---|
| Share of voice (7 and 30 days) | Google News, per brand | Automatic |
| Daily coverage trend | Google News | Automatic |
| Activity by type: campaigns, sponsorships, awards, appointments, launches, results, CSR, thought leadership, digital, deals, reputation | Headline keywords | Automatic |
| Headline tone | Headline keywords | Automatic |
| Top outlets | Google News | Automatic |
| Morning briefing | Claude (or rules if no API key) | Automatic |
| Campaign and activity log | `data/campaigns.csv` | Manual |
| Social followers | `data/social.csv` | Manual |

Edit `config.json` to add or remove brands, change search terms or tune the category keywords. Each brand sits under its segment (`Wealth` or `Insure`).

## How it runs

`.github/workflows/daily-update.yml` runs every day at 05:17 SAST. It:

1. Runs `tracker.py` to collect coverage and rebuild the Excel file and dashboard data.
2. Commits the updated files to the repository.
3. Publishes the dashboard to GitHub Pages.

## Set-up (one-off)

1. Merge this branch into the default branch. Scheduled workflows only run there.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. Optional: in **Settings → Secrets and variables → Actions**, add `ANTHROPIC_API_KEY` so Claude writes the morning briefing.
4. In **Actions → Daily tracker update → Run workflow**, run it once to replace the sample data with live coverage.

## Run it locally

```bash
cd financial-services-marketing-tracker
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
2026-11-01,PSG Wealth,LinkedIn,52000,
```

## Limits to know

- Mentions are news items. They are not reach, impressions or advertising value equivalent (AVE).
- Categories and tone come from headline keywords. Treat them as signals and tune `config.json` over time.
- Google News RSS suits internal monitoring. For commercial redistribution, use a licensed media-monitoring feed.
- Brand colours follow the current PSG brand: cyan #00AEEF, charcoal #353E43, action blue #0054FF, yellow #FFDE21 and magenta #D4055C, with IBM Plex Sans standing in for PSG Plex Sans. Chart marks use a slightly deeper cyan (#0096D6) so they stay legible on white.
