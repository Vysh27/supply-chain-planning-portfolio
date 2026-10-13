# Supply-Chain Planning Analytics Portfolio

Analytics projects in a **quick-commerce (darkstore grocery) planning** context,
built to mirror an Associate Product Manager role on a planning team: dig into
planning data with SQL and Python, find where availability leaks and stock
expires, quantify the impact in rupees, and turn findings into planning-parameter
and product changes.

All data is **synthetic** (one generator, fixed seed) with realistic failure
modes baked in — vendor delays, reorder-point misconfiguration, demand spikes and
short-shelf-life perishables — so the diagnostics have real leakages to recover.

## Projects

| # | Project | What it answers | Headline (synthetic) |
|---|---------|-----------------|----------------------|
| 01 | [Availability & DOH diagnostic](01_availability_doh_diagnostic) | Where is availability leaking, and why? | 87.8% availability; ₹16.2M lost sales split across 3 root causes |
| 02 | [Demand forecast + replenishment](02_demand_forecast_replenishment) | What should reorder points be? | WAPE ≈ 10%; flags 100% of too-low & 95% of too-high reorder points |
| 03 | [Expiry & wastage RCA](03_expiry_wastage_rca) | Why does stock expire? | ₹15.6M wastage, 91% in Fruits & Veg; overstock↔expiry r = 0.72 |
| 04 | [Planning control-tower dashboard](04_planning_dashboard) | One live view for planning & ops | Streamlit + standalone HTML; availability, DOH, vendor, wastage |
| — | [Planning SQL](sql) | The queries behind the above | Availability, stock-out, DOH, vendor-delay, wastage |
| — | [Sample PRD](SAMPLE_PRD.md) | Turning a finding into a product change | Dynamic reorder points for perishables |

## Why these

They map onto the APM responsibilities: **analyse large planning datasets (orders,
inventory, POs, GRNs, wastage) to find leakages across availability, DOH and
expiry**, run **root-cause analysis and quantify impact in ₹**, support
**forecasting and replenishment improvements**, and **write a PRD** for the fix.
Tools — SQL, Python (pandas, numpy, scipy), with clear, explainable methods — are
what the role runs on.

## Quick start

```bash
pip install -r requirements.txt

# 1) build the shared dataset (writes data/)
python data_pipeline/generate_data.py

# 2) run any project
python 01_availability_doh_diagnostic/diagnostic.py
python 02_demand_forecast_replenishment/forecast_replenish.py
python 03_expiry_wastage_rca/expiry_rca.py
```

## Repo layout

```
supply-chain-planning-portfolio/
├── data_pipeline/                  # one synthetic data generator for all projects
├── 01_availability_doh_diagnostic/ # leakage diagnosis + ₹ impact + root cause
├── 02_demand_forecast_replenishment/ # forecasting + reorder-point recommendations
├── 03_expiry_wastage_rca/          # perishables expiry root-cause analysis
├── 04_planning_dashboard/          # interactive control tower (Streamlit + HTML)
├── sql/                            # planning SQL (availability, DOH, vendor delay)
├── SAMPLE_PRD.md                   # a worked PRD built on the findings
└── requirements.txt
```

## A note on the data

Every table is fabricated with documented relationships so the methods have real
signal to find — but the numbers describe no real business. The point is the
*approach*: find the leakage, attribute the cause, size it in money, and propose a
change an ops and product team can act on.
