# 01 — Availability & DOH Leakage Diagnostic

Find where availability is leaking and stock is piling up, attribute each miss to
a likely root cause, and size it in rupees — the core "problem discovery" an APM
on a planning team owns.

## What it does

- **Availability** (unit fill = fulfilled ÷ demanded) and **stock-out rate**
  (store-SKU-days with zero on-hand but live demand).
- **DOH** (days on hand = on-hand ÷ trailing-14-day demand) to catch overstock.
- **Lost-sales value** in ₹, ranked per SKU — the leakage list.
- **Root-cause attribution** per SKU: vendor delay (POs arriving late vs
  expected), reorder point too low, demand spike, or thin safety stock / demand
  variability — each sized in ₹.

## Results (synthetic, seed 42)

- Availability **87.8%** vs a 95% target; stock-out rate **18%**.
- Lost-sales value **₹16.2M** over the window, split:
  - Thin safety stock / variability — **37.6%**
  - Vendor delay — **37.6%**
  - Reorder point too low — **24.8%**

That split is the actionable part: roughly a quarter of the loss is a parameter
fix, over a third is a vendor problem, and the rest is safety-stock tuning.

## Run it

```bash
python ../data_pipeline/generate_data.py   # if data/ not built yet
python diagnostic.py
```

## Outputs

| File | What it is |
|------|------------|
| `outputs/loss_by_root_cause.csv` / `.png` | ₹ lost sales attributed to each root cause |
| `outputs/top_leakage_skus.csv` | The 20 SKUs bleeding the most revenue |
| `outputs/availability_vs_doh.png` | Availability vs DOH by category (the two-sided problem) |
