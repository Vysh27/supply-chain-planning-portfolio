"""
Expiry & wastage root-cause analysis (perishables planning).

Quantifies wastage in rupees, finds where it concentrates (category, SKU, store),
and tests the planning hypothesis that expiry is driven by overstocking relative
to shelf life — the "why does stock expire" discovery an APM owns for perishables.

Outputs:
    - Wastage ₹ by category and the worst SKUs.
    - Expiry rate = expired units / units received, by shelf-life bucket.
    - Correlation between a SKU's days-on-hand vs its shelf life and its expiry rate
      (the overstock-vs-shelf-life hypothesis).

Usage:
    python expiry_rca.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).parent / "outputs"
PLOT_BG = "#FbFaF9"
ACCENT = "#1F6F54"
WARN = "#C0392B"


def load():
    if not (DATA / "wastage.csv").exists():
        raise SystemExit("No data — run `python data_pipeline/generate_data.py` first.")
    w = pd.read_csv(DATA / "wastage.csv", parse_dates=["date"])
    d = pd.read_csv(DATA / "demand.csv", parse_dates=["date"])
    inv = pd.read_csv(DATA / "inventory.csv", parse_dates=["date"])
    grn = pd.read_csv(DATA / "grn.csv")
    sk = pd.read_csv(DATA / "skus.csv")
    return w, d, inv, grn, sk


def main():
    OUT.mkdir(exist_ok=True)
    w, d, inv, grn, sk = load()
    cost = sk.set_index("sku_id")["cost_inr"]

    w = w.merge(sk[["sku_id", "category", "shelf_life_days", "perishable"]], on="sku_id")
    w["waste_value"] = w["units_expired"] * w["sku_id"].map(cost)
    total_waste_units = w["units_expired"].sum()
    total_waste_value = w["waste_value"].sum()
    print(f"Total wastage: {total_waste_units:,} units  ₹{total_waste_value:,.0f}")

    # ---- by category ----
    by_cat = (w.groupby("category")
              .agg(units=("units_expired", "sum"), value=("waste_value", "sum"))
              .sort_values("value", ascending=False))
    by_cat["pct"] = (by_cat["value"] / by_cat["value"].sum() * 100).round(1)
    print("\nWastage by category:")
    print(by_cat.assign(value=by_cat["value"].map(lambda v: f"₹{v:,.0f}")).to_string())

    # ---- expiry rate = expired / received, per SKU ----
    recv = grn.groupby("sku_id")["qty_received"].sum()
    exp = w.groupby("sku_id")["units_expired"].sum()
    rate = (exp / recv).dropna().rename("expiry_rate").reset_index()
    rate = rate.merge(sk[["sku_id", "category", "shelf_life_days"]], on="sku_id")
    rate["waste_value"] = rate["sku_id"].map(w.groupby("sku_id")["waste_value"].sum())
    top = rate.sort_values("waste_value", ascending=False).head(15)
    top.to_csv(OUT / "top_wastage_skus.csv", index=False)
    by_cat.to_csv(OUT / "wastage_by_category.csv")

    # ---- overstock-vs-shelf-life hypothesis ----
    panel = inv.merge(d, on=["date", "darkstore_id", "sku_id"])
    panel = panel.sort_values(["darkstore_id", "sku_id", "date"])
    panel["avg_demand"] = (panel.groupby(["darkstore_id", "sku_id"])["units_demanded"]
                           .transform(lambda s: s.rolling(14, min_periods=3).mean()))
    panel["doh"] = panel["on_hand_units"] / panel["avg_demand"].replace(0, np.nan)
    sku_doh = panel.groupby("sku_id")["doh"].median()
    rate["median_doh"] = rate["sku_id"].map(sku_doh)
    rate["doh_vs_shelf"] = rate["median_doh"] / rate["shelf_life_days"]
    valid = rate.dropna(subset=["doh_vs_shelf", "expiry_rate"])
    corr = valid["doh_vs_shelf"].corr(valid["expiry_rate"])
    print(f"\nHypothesis test — DOH-to-shelf-life ratio vs expiry rate:")
    print(f"  Pearson correlation = {corr:.2f}  "
          f"({'supports' if corr > 0.3 else 'weak support for'} the overstock hypothesis)")
    perish_rate = rate[rate["shelf_life_days"] <= 9]["expiry_rate"].mean()
    long_vals = rate[rate["shelf_life_days"] > 9]["expiry_rate"]
    long_rate = long_vals.mean() if long_vals.notna().any() else 0.0
    print(f"  Mean expiry rate — short shelf-life (<=9d): {perish_rate:.1%} | "
          f"long (>9d): {long_rate:.1%}  (long-life SKUs essentially never expire)")

    # ---- chart 1: wastage value by category ----
    fig, ax = plt.subplots(figsize=(7.5, 4.2), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    ax.barh(by_cat.index[::-1], by_cat["value"][::-1] / 1e3, color=ACCENT)
    ax.set_xlabel("Wastage value (₹ thousands)")
    ax.set_title("Wastage ₹ by category", fontweight="bold")
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "wastage_by_category.png", dpi=130); plt.close(fig)

    # ---- chart 2: DOH/shelf-life vs expiry rate scatter ----
    fig, ax = plt.subplots(figsize=(7.5, 5), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    sc = ax.scatter(valid["doh_vs_shelf"], valid["expiry_rate"] * 100,
                    c=valid["shelf_life_days"], cmap="YlGn_r", s=60, edgecolor="#555", linewidth=0.3)
    ax.set_xlabel("Median DOH ÷ shelf life  (>1 = stocking beyond shelf life)")
    ax.set_ylabel("Expiry rate (% of received)")
    ax.axvline(1.0, ls="--", color=WARN, lw=1)
    ax.set_title(f"Overstock vs expiry  (r = {corr:.2f})", fontweight="bold")
    fig.colorbar(sc, label="Shelf life (days)")
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "overstock_vs_expiry.png", dpi=130); plt.close(fig)

    print(f"\nOutputs written to {OUT}/")


if __name__ == "__main__":
    main()
