"""
Generate a synthetic quick-commerce planning dataset (darkstore grocery).

Produces the core planning tables an APM would actually dig through, with
realistic failure modes baked in so the diagnostics have real leakages to find:

    data/skus.csv          SKU master (category, price, cost, shelf life, lead time)
    data/demand.csv        daily demand & fulfilled units per darkstore x SKU
    data/inventory.csv     daily on-hand units per darkstore x SKU
    data/purchase_orders.csv  POs raised (qty, vendor, expected date)
    data/grn.csv           goods receipts (actual received qty & date vs expected)
    data/wastage.csv       units expired per darkstore x SKU x day

Baked-in failure modes:
    - vendor delays (some vendors chronically late -> availability misses)
    - forecast error / demand spikes the reorder point doesn't cover
    - parameter misconfiguration (reorder points set too low or too high)
    - perishables with short shelf life -> expiry when overstocked

Usage:
    python generate_data.py [--days 180] [--stores 6] [--skus 60] [--seed 42]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIES = {
    #              share, price, cost, shelf_life_days, base_daily_demand, perishable
    "Fruits&Veg":   (0.22, 70,  45,  4,   38, True),
    "Dairy":        (0.18, 55,  38,  9,   30, True),
    "Bakery":       (0.10, 45,  28,  3,   18, True),
    "Packaged":     (0.22, 120, 85,  240, 22, False),
    "Beverages":    (0.14, 90,  60,  180, 20, False),
    "Personal Care":(0.14, 180, 120, 365, 12, False),
}
VENDORS = {   # vendor -> (avg lead time days, on-time reliability 0..1, fill reliability)
    "V-Alpha":   (2, 0.92, 0.98),
    "V-Beta":    (3, 0.75, 0.95),   # somewhat late
    "V-Gamma":   (4, 0.55, 0.90),   # chronically late -> a leakage source
    "V-Delta":   (2, 0.88, 0.97),
}


def build_skus(n_skus, rng):
    cats = list(CATEGORIES)
    probs = [CATEGORIES[c][0] for c in cats]
    rows = []
    vendors = list(VENDORS)
    for i in range(n_skus):
        c = rng.choice(cats, p=probs)
        _, price, cost, shelf, base, perish = CATEGORIES[c]
        vendor = rng.choice(vendors)
        lead = VENDORS[vendor][0]
        # parameter misconfiguration: reorder point should ~ lead_time * demand,
        # but we deliberately mis-set a chunk of SKUs (too low -> stockouts,
        # too high -> overstock/expiry).
        demand_mu = max(3, base * rng.uniform(0.5, 1.6))
        ideal_rop = lead * demand_mu
        misconfig = rng.choice(["ok", "too_low", "too_high"], p=[0.6, 0.25, 0.15])
        factor = {"ok": rng.uniform(0.9, 1.2), "too_low": rng.uniform(0.35, 0.6),
                  "too_high": rng.uniform(1.8, 2.6)}[misconfig]
        rop = round(ideal_rop * factor)
        order_qty = round(demand_mu * rng.uniform(5, 9))  # cover ~ a week+
        rows.append({
            "sku_id": f"SKU{1000 + i}", "category": c, "price_inr": price,
            "cost_inr": cost, "shelf_life_days": shelf, "perishable": perish,
            "vendor": vendor, "lead_time_days": lead,
            "demand_mu": round(demand_mu, 1), "reorder_point": rop,
            "order_qty": order_qty, "rop_config": misconfig,
        })
    return pd.DataFrame(rows)


def simulate(skus, stores, days, rng):
    start = pd.Timestamp("2026-03-01")
    dates = pd.date_range(start, periods=days, freq="D")
    demand_rows, inv_rows, po_rows, grn_rows, waste_rows = [], [], [], [], []
    po_counter = 0

    for store in [f"DS{s:02d}" for s in range(1, stores + 1)]:
        store_mult = rng.uniform(0.8, 1.25)   # some stores busier
        for _, s in skus.iterrows():
            sku = s["sku_id"]
            mu = s["demand_mu"] * store_mult
            rop = s["reorder_point"]
            oq = s["order_qty"]
            lead = s["lead_time_days"]
            vendor = s["vendor"]
            lt_rel, fill_rel = VENDORS[vendor][1], VENDORS[vendor][2]
            shelf = int(s["shelf_life_days"])

            on_hand = float(rop + oq * 0.5)       # start mid-cycle
            # batches as (expiry_date, units) for perishables
            batches = [[dates[0] + pd.Timedelta(days=shelf), on_hand]]
            incoming = []   # (arrival_date, units)
            open_po = False

            for d in dates:
                # receive arrivals due today
                for arr, qty, pid in [x for x in incoming if x[0] == d]:
                    on_hand += qty
                    batches.append([d + pd.Timedelta(days=shelf), qty])
                    grn_rows.append({"po_id": pid, "sku_id": sku,
                                     "darkstore_id": store, "received_date": d.date(),
                                     "qty_received": int(qty)})
                incoming = [x for x in incoming if x[0] != d]
                if not incoming:
                    open_po = False

                # demand (with occasional spike = forecast error)
                spike = 2.4 if rng.random() < 0.03 else 1.0
                dem = max(0, int(rng.poisson(mu * spike)))
                fulfilled = int(min(on_hand, dem))
                lost = dem - fulfilled
                on_hand -= fulfilled

                # consume batches FIFO for fulfilled units
                rem = fulfilled
                for b in batches:
                    if rem <= 0:
                        break
                    take = min(b[1], rem); b[1] -= take; rem -= take
                batches = [b for b in batches if b[1] > 1e-6]

                # expire batches past expiry
                expired = sum(b[1] for b in batches if b[0] <= d)
                if expired > 0:
                    on_hand -= expired
                    batches = [b for b in batches if b[0] > d]
                    waste_rows.append({"date": d.date(), "darkstore_id": store,
                                       "sku_id": sku, "units_expired": int(round(expired))})

                demand_rows.append({"date": d.date(), "darkstore_id": store, "sku_id": sku,
                                    "units_demanded": dem, "units_fulfilled": fulfilled,
                                    "units_lost": lost})
                inv_rows.append({"date": d.date(), "darkstore_id": store, "sku_id": sku,
                                 "on_hand_units": int(round(max(0, on_hand)))})

                # reorder logic: if below ROP and no open PO, raise a PO
                if on_hand <= rop and not open_po:
                    po_counter += 1
                    pid = f"PO{po_counter}"
                    # vendor may be late; fill may be short
                    late = 0 if rng.random() < lt_rel else int(rng.integers(1, 4))
                    fill = 1.0 if rng.random() < fill_rel else rng.uniform(0.6, 0.9)
                    exp_date = d + pd.Timedelta(days=lead)
                    arr_date = exp_date + pd.Timedelta(days=late)
                    recv_qty = round(oq * fill)
                    po_rows.append({"po_id": pid, "sku_id": sku, "darkstore_id": store,
                                    "vendor": vendor, "order_date": d.date(),
                                    "expected_date": exp_date.date(),
                                    "qty_ordered": int(oq)})
                    incoming.append((arr_date, recv_qty, pid))
                    open_po = True

    return (pd.DataFrame(demand_rows), pd.DataFrame(inv_rows),
            pd.DataFrame(po_rows), pd.DataFrame(grn_rows), pd.DataFrame(waste_rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--stores", type=int, default=6)
    ap.add_argument("--skus", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    skus = build_skus(args.skus, rng)
    demand, inv, po, grn, waste = simulate(skus, args.stores, args.days, rng)

    out = Path(__file__).parent.parent / "data"
    out.mkdir(exist_ok=True)
    skus.to_csv(out / "skus.csv", index=False)
    demand.to_csv(out / "demand.csv", index=False)
    inv.to_csv(out / "inventory.csv", index=False)
    po.to_csv(out / "purchase_orders.csv", index=False)
    grn.to_csv(out / "grn.csv", index=False)
    waste.to_csv(out / "wastage.csv", index=False)

    print(f"SKUs: {len(skus)} | darkstores: {args.stores} | days: {args.days}")
    print(f"demand rows: {len(demand):,} | inventory rows: {len(inv):,}")
    print(f"POs: {len(po):,} | GRNs: {len(grn):,} | wastage rows: {len(waste):,}")
    print(f"Written to {out}/")


if __name__ == "__main__":
    main()
