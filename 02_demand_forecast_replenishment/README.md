# 02 — Demand Forecast + Replenishment Recommendation

Forecast near-term demand per darkstore-SKU, then turn the forecast into a
concrete replenishment plan — a recommended reorder point and the SKUs whose
current parameters are mis-set. This is the "translate findings into
planning-parameter changes" part of the APM role.

## What it does

1. **Back-test** two explainable forecasters (7-day moving average vs EWMA) on a
   14-day hold-out, scored by **WAPE**, so the accuracy claim is honest.
2. **Recommend a reorder point** per store-SKU:
   `ROP = forecast_daily_demand × lead_time + safety_stock`, with
   `safety_stock = z(service_level) × σ_demand × √lead_time`.
3. **Flag re-parameterisation**: SKUs whose recommended ROP differs from the
   current one by more than ±25% (raise = under-stocking risk, lower =
   overstock/expiry risk).

## Results (synthetic, seed 42)

- Median **WAPE ≈ 10%** on the 14-day back-test.
- **58%** of store-SKU combos flagged for a reorder-point change.
- **Validation:** the flag catches **100%** of SKUs whose reorder point was truly
  set too low and **95%** of those set too high (only 35% of correctly-configured
  SKUs are flagged) — evidence the method finds the real misconfigurations.

## Run it

```bash
python ../data_pipeline/generate_data.py   # if data/ not built yet
python forecast_replenish.py --service_level 0.95
```

## Outputs

| File | What it is |
|------|------------|
| `outputs/replenishment_recommendations.csv` | Per store-SKU: recommended ROP, gap vs current, action |
| `outputs/forecast_backtest.csv` | WAPE per SKU for both forecasters |
| `outputs/forecast_example.png` | Forecast vs actual for the top-volume SKU |
| `outputs/rop_gap_distribution.png` | How far current reorder points sit from recommended |

## Notes

Simple, explainable forecasters are deliberate — a planning team needs to trust
and reason about the number. On real data this extends to SARIMAX with promo /
holiday regressors (see the time-series project in the beauty portfolio).
