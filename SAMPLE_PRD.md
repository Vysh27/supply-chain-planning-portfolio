# PRD — Dynamic Reorder Points for Perishables

**Author:** Vyshnavi Yerra · **Status:** Draft · **Reviewers:** Planning PM, Data Science, Ops
**Type:** Planning-parameter / algorithm change

> This is a sample PRD written to illustrate how I'd turn a data finding into a
> scoped product change. The numbers come from the analysis in this repo
> (synthetic data), not a real system.

## 1. Problem

Availability sits at **87.8%** against a 95% target, and two root causes together
drive most of the leakage (from `01_availability_doh_diagnostic`):

- **Reorder points mis-set** — ~25% of lost-sales value (₹4.0M in the sample window)
  comes from SKUs whose reorder point (ROP) is too low for their lead time and
  demand variability.
- **Thin safety stock / demand variability** — another ~38% (₹6.1M) comes from
  SKUs whose ROP doesn't absorb normal demand swings.

Separately, perishables waste **₹15.6M**, 91% of it in Fruits & Veg, and expiry
rate correlates with overstock relative to shelf life (**r = 0.72**). So the two
failure modes pull in opposite directions: raise stock and expiry rises; cut it
and availability falls. A single static ROP can't serve both.

## 2. Goal & success metrics

Move availability toward 95% **without** increasing perishable wastage.

| Metric | Baseline | Target (90 days) |
|--------|----------|------------------|
| Unit availability | 87.8% | ≥ 93% |
| Lost-sales value / week | (baseline) | −40% |
| Perishable wastage ₹ / week | (baseline) | No increase (ideally −10%) |
| % store-SKUs within ±25% of recommended ROP | ~42% | ≥ 80% |

## 3. Proposed change

Replace the static reorder point with a **demand- and shelf-life-aware ROP**,
recomputed weekly per darkstore-SKU:

```
ROP = forecast_daily_demand × lead_time
      + safety_stock
safety_stock = z(service_level) × σ_demand × √lead_time
```

with a **shelf-life cap** for perishables so recommended stock never exceeds what
can sell before expiry:

```
max_stock = min( ROP + order_qty,  sellable_before_expiry )
sellable_before_expiry = forecast_daily_demand × shelf_life_days × safety_factor
```

The forecast and the recommended ROP are already implemented in
`02_demand_forecast_replenishment` (back-tested WAPE ≈ 10%); this PRD productises
them into the planning system.

## 4. Scope

**In scope:** weekly ROP recompute job; shelf-life cap for perishables; a review
queue surfacing SKUs whose recommended ROP differs >25% from current; an audit log.

**Out of scope (phase 1):** vendor-delay remediation (tracked separately), fully
automated ordering without human review, promo-demand modelling.

## 5. Rollout & guardrails

1. **Shadow mode (2 weeks):** compute recommended ROPs, don't apply — compare
   against actuals.
2. **Pilot (4 weeks):** apply to 2 darkstores + Fruits & Veg; hold the rest as control.
3. **A/B readout:** availability and wastage, pilot vs control (method in
   `beauty-analytics-portfolio/04_ab_test_analysis` applies here too).
4. **Guardrail:** auto-revert any SKU whose wastage rises >20% week-on-week post-change.

## 6. Risks

| Risk | Mitigation |
|------|------------|
| Forecast misses a demand spike → stockout | Safety-stock term sized to demand σ; monitor WAPE drift |
| Shelf-life cap starves fast movers | Cap uses forecast × shelf life, not a flat number |
| Ops can't action 200+ changes at once | Prioritise by ₹ lost-sales impact; batch the top decile first |

## 7. Open questions

- Is lead time reliable per vendor, or should it use the **p75 observed** lead
  time (vendor delay data suggests some vendors run 1 day late)?
- Service level: uniform 95%, or higher for high-margin / hero SKUs?
