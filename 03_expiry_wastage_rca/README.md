# 03 — Expiry & Wastage Root-Cause Analysis

Quantify perishable wastage in rupees, find where it concentrates, and test the
planning hypothesis that expiry is driven by overstocking relative to shelf life
— the "why does stock expire" discovery an APM owns for perishables.

## What it does

- **Wastage in ₹** by category and the worst SKUs.
- **Expiry rate** = expired units ÷ units received, per SKU.
- **Hypothesis test:** correlate each SKU's *DOH ÷ shelf-life* ratio with its
  expiry rate. A ratio above 1 means the store routinely holds more than it can
  sell before the stock expires.

## Results (synthetic, seed 42)

- Total wastage **₹15.6M** (364k units).
- **91%** of wastage value is in **Fruits & Veg**, 8.5% in Bakery — wastage is
  highly concentrated, so a fix there moves the whole number.
- **Overstock ↔ expiry correlation r = 0.72** — strong support for the overstock
  hypothesis.
- Short-shelf-life SKUs (≤9 days) expire at **26%** of received units; long-life
  SKUs essentially never expire — so the lever is *how much* perishables are
  stocked, not which.

## Run it

```bash
python ../data_pipeline/generate_data.py   # if data/ not built yet
python expiry_rca.py
```

## Outputs

| File | What it is |
|------|------------|
| `outputs/wastage_by_category.csv` / `.png` | ₹ wastage concentration by category |
| `outputs/top_wastage_skus.csv` | The 15 SKUs wasting the most value |
| `outputs/overstock_vs_expiry.png` | DOH-to-shelf-life vs expiry rate (the hypothesis) |

## So what

This points straight at the fix in `SAMPLE_PRD.md`: a shelf-life-aware cap on
stock for perishables, so reorder points raise availability without pushing more
Fruits & Veg into the bin.
