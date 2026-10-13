# 04 — Planning Control-Tower Dashboard

An interactive monitoring surface for a planning / ops team: availability and
lost-sales, days-on-hand, vendor reliability and perishable wastage — the
"dashboards and alerts that give planning and ops reliable visibility" part of the
APM role. It ties the three analysis projects into one place a non-analyst can use.

## What it shows

- **KPI tiles** — availability % (vs a 95% target), lost-sales ₹, wastage ₹, and
  average cover (DOH).
- **Availability by category and by darkstore** — where the misses concentrate,
  colour-coded against the target.
- **Lost sales ₹** and **wastage ₹** by category.
- **Vendor lateness** (PO vs GRN) — the reliability leaderboard.

Everything responds to the sidebar filters: **date range, darkstore, category**.

## Two ways to use it

**No install — standalone HTML:** open `planning_dashboard.html` in any browser.
Fully self-contained (data embedded, CSS/SVG charts), works offline, drops
straight into the repo. Rebuild with `python build_html_dashboard.py`.

**View it live (clickable link):**
[open the dashboard](https://htmlpreview.github.io/?https://github.com/Vysh27/supply-chain-planning-portfolio/blob/main/04_planning_dashboard/planning_dashboard.html)
— renders the HTML straight from the repo (works once the file is uploaded). For
a cleaner URL you can enable GitHub Pages (Settings → Pages → Deploy from branch
`main`), which serves it at
`https://vysh27.github.io/supply-chain-planning-portfolio/04_planning_dashboard/planning_dashboard.html`.

**Interactive app — Streamlit:**

```bash
pip install -r ../requirements.txt     # needs streamlit + altair
streamlit run app.py
```

The app auto-generates the dataset on first run, so it also works out of the box
on Streamlit Community Cloud (main file path `04_planning_dashboard/app.py`).

## Headline (synthetic, seed 42)

Availability **87.8%** vs 95% target, **₹16.2M** lost sales and **₹15.6M**
wastage in the window — with V-Gamma the worst vendor for lateness and Fruits &
Veg the worst for wastage, so the filters lead straight to the actions in the
other three projects.

## Note

Synthetic data — no real business. On real data this sits on the warehouse tables
and refreshes on a schedule; the same layout ports to Tableau or Power BI.
