"""
Availability & DOH leakage diagnostic (quick-commerce planning).

Finds where availability is leaking and stock is piling up, attributes each miss
to a likely root cause, and quantifies the impact in rupees — the core "problem
discovery" an APM on a planning team owns.

Metrics:
    - Availability % = fulfilled / demanded (unit fill rate)
    - Stockout rate = share of store-SKU-days with on_hand = 0 and demand > 0
    - DOH (days on hand) = on_hand / trailing avg daily demand
    - Lost sales (Rs) = lost units x price
    - Overstock capital (Rs) = on_hand above a healthy DOH band x cost

Root-cause attribution for availability misses (per SKU):
    - Vendor delay       : its POs arrive late (GRN date > expected)
    - Reorder point too low : SKU flagged rop_config = too_low / low vs lead*demand
    - Demand spike       : lost days coincide with demand >> its mean
    - Other / fulfilment : none of the above dominate

Usage:
    python diagnostic.py
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
ACCENT = "#1F6F54"   # supply-chain green
ACCENT2 = "#6A7B8C"
WARN = "#C0392B"
HEALTHY_DOH = (3, 14)   # target days-on-hand band


def load():
    if not (DATA / "demand.csv").exists():
        raise SystemExit("No data — run `python data_pipeline/generate_data.py` first.")
    d = pd.read_csv(DATA / "demand.csv", parse_dates=["date"])
    inv = pd.read_csv(DATA / "inventory.csv", parse_dates=["date"])
    sk = pd.read_csv(DATA / "skus.csv")
    po = pd.read_csv(DATA / "purchase_orders.csv", parse_dates=["expected_date"])
    grn = pd.read_csv(DATA / "grn.csv", parse_dates=["received_date"])
    return d, inv, sk, po, grn


def main():
    OUT.mkdir(exist_ok=True)
    d, inv, sk, po, grn = load()
    price = sk.set_index("sku_id")["price_inr"]
    cost = sk.set_index("sku_id")["cost_inr"]

    # ---- headline availability ----
    avail = d["units_fulfilled"].sum() / d["units_demanded"].sum()
    panel = inv.merge(d, on=["date", "darkstore_id", "sku_id"])
    stockout_rate = ((panel["on_hand_units"] == 0) & (panel["units_demanded"] > 0)).mean()
    lost_value = (d["units_lost"] * d["sku_id"].map(price)).sum()
    print(f"Overall availability (unit fill): {avail:.1%}")
    print(f"Stock-out rate (store-SKU-days): {stockout_rate:.1%}")
    print(f"Lost-sales value: ₹{lost_value:,.0f}")

    # ---- DOH & overstock ----
    panel = panel.sort_values(["darkstore_id", "sku_id", "date"])
    panel["avg_demand"] = (panel.groupby(["darkstore_id", "sku_id"])["units_demanded"]
                           .transform(lambda s: s.rolling(14, min_periods=3).mean()))
    panel["doh"] = panel["on_hand_units"] / panel["avg_demand"].replace(0, np.nan)
    overstock = panel[panel["doh"] > HEALTHY_DOH[1]].copy()
    excess_units = overstock["on_hand_units"] - HEALTHY_DOH[1] * overstock["avg_demand"]
    overstock_capital = (excess_units.clip(lower=0) * overstock["sku_id"].map(cost)).sum()
    print(f"Median DOH: {panel['doh'].median():.1f} days | "
          f"capital tied in overstock (>{HEALTHY_DOH[1]}d DOH): ₹{overstock_capital:,.0f}")

    # ---- per-SKU lost sales (the leakage ranking) ----
    sku_lost = (d.groupby("sku_id")
                  .apply(lambda g: pd.Series({
                      "lost_units": g["units_lost"].sum(),
                      "demanded": g["units_demanded"].sum(),
                      "availability": g["units_fulfilled"].sum() / g["units_demanded"].sum(),
                  }), include_groups=False)
                  .reset_index())
    sku_lost["lost_value"] = sku_lost["lost_units"] * sku_lost["sku_id"].map(price)
    sku_lost = sku_lost.merge(sk[["sku_id", "category", "vendor", "rop_config"]], on="sku_id")

    # ---- root-cause attribution ----
    # vendor lateness per SKU
    po_grn = po.merge(grn, on=["po_id", "sku_id", "darkstore_id"])
    po_grn["late_days"] = (po_grn["received_date"] - po_grn["expected_date"]).dt.days
    sku_late = po_grn.groupby("sku_id")["late_days"].mean()

    # demand-spike share: lost days where demand > 1.8x the SKU mean
    dmean = d.groupby("sku_id")["units_demanded"].transform("mean")
    d["_spike_lost"] = (d["units_lost"] > 0) & (d["units_demanded"] > 1.8 * dmean)
    spike_share = d.groupby("sku_id").apply(
        lambda g: g["_spike_lost"].sum() / max(1, (g["units_lost"] > 0).sum()),
        include_groups=False)

    def classify(row):
        s = row["sku_id"]
        if sku_late.get(s, 0) >= 0.5:
            return "Vendor delay"
        if row["rop_config"] == "too_low":
            return "Reorder point too low"
        if spike_share.get(s, 0) >= 0.3:
            return "Demand spike"
        return "Thin safety stock / variability"

    sku_lost["root_cause"] = sku_lost.apply(classify, axis=1)

    # ---- impact by root cause ----
    by_cause = (sku_lost.groupby("root_cause")
                .agg(lost_value=("lost_value", "sum"),
                     skus=("sku_id", "count"))
                .sort_values("lost_value", ascending=False))
    by_cause["pct_of_loss"] = (by_cause["lost_value"] / by_cause["lost_value"].sum() * 100).round(1)
    print("\nLost-sales value by root cause:")
    print(by_cause.assign(lost_value=by_cause["lost_value"].map(lambda v: f"₹{v:,.0f}")).to_string())

    # ---- exports ----
    top = sku_lost.sort_values("lost_value", ascending=False).head(20)
    top.to_csv(OUT / "top_leakage_skus.csv", index=False)
    by_cause.to_csv(OUT / "loss_by_root_cause.csv")
    print(f"\nTop 20 leakage SKUs -> {OUT/'top_leakage_skus.csv'}")

    # ---- chart 1: loss by root cause ----
    fig, ax = plt.subplots(figsize=(7.5, 4.2), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    colors = [WARN if i == 0 else ACCENT for i in range(len(by_cause))]
    ax.barh(by_cause.index[::-1], by_cause["lost_value"][::-1] / 1e3, color=colors[::-1])
    ax.set_xlabel("Lost-sales value (₹ thousands)")
    ax.set_title("Where availability is leaking — ₹ impact by root cause", fontweight="bold")
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "loss_by_root_cause.png", dpi=130); plt.close(fig)

    # ---- chart 2: availability vs DOH by category (the two-sided problem) ----
    cat = (panel.groupby("category" if "category" in panel else
                         panel["sku_id"].map(sk.set_index("sku_id")["category"]))
           .agg(doh=("doh", "median")))
    cat_av = d.assign(category=d["sku_id"].map(sk.set_index("sku_id")["category"]))\
              .groupby("category").apply(
                  lambda g: g["units_fulfilled"].sum() / g["units_demanded"].sum(),
                  include_groups=False)
    merged = pd.DataFrame({"availability": cat_av, "doh": cat["doh"]}).dropna()
    fig, ax = plt.subplots(figsize=(7, 5), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    ax.scatter(merged["doh"], merged["availability"] * 100, s=90, color=ACCENT)
    for name, r in merged.iterrows():
        ax.annotate(name, (r["doh"], r["availability"] * 100),
                    textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.axvspan(HEALTHY_DOH[0], HEALTHY_DOH[1], color=ACCENT, alpha=0.08, label="Healthy DOH band")
    ax.axhline(95, ls="--", color=ACCENT2, lw=1, label="95% availability target")
    ax.set_xlabel("Median days on hand (DOH)")
    ax.set_ylabel("Availability %")
    ax.set_title("Availability vs DOH by category", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "availability_vs_doh.png", dpi=130); plt.close(fig)

    print(f"Charts written to {OUT}/")


if __name__ == "__main__":
    main()
