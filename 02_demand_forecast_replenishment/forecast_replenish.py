"""
Demand forecasting + replenishment recommendation (quick-commerce planning).

Forecasts near-term demand per darkstore-SKU, then turns the forecast into a
concrete replenishment plan: a demand-and-lead-time-based reorder point and order
quantity, and a recommendation where the current (synthetic) parameters are
mis-set. This is the "translate findings into planning-parameter changes" part of
the APM role.

Method:
    - Aggregate daily demand per store-SKU.
    - Back-test a 14-day horizon: moving-average vs exponentially-weighted MA,
      scored by MAPE/WAPE, so the accuracy claim is honest.
    - Compute recommended reorder point = lead_time * forecast_daily_demand
      + safety stock (z * sigma * sqrt(lead_time)), and compare with the current
      reorder_point to flag SKUs to re-parameterise.

Usage:
    python forecast_replenish.py [--service_level 0.95]
"""
import argparse
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).parent / "outputs"
PLOT_BG = "#FbFaF9"
ACCENT = "#1F6F54"
ACCENT2 = "#6A7B8C"
WARN = "#C0392B"
HORIZON = 14


def load():
    if not (DATA / "demand.csv").exists():
        raise SystemExit("No data — run `python data_pipeline/generate_data.py` first.")
    d = pd.read_csv(DATA / "demand.csv", parse_dates=["date"])
    sk = pd.read_csv(DATA / "skus.csv")
    return d, sk


def wape(actual, pred):
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    denom = actual.sum()
    return np.abs(actual - pred).sum() / denom * 100 if denom else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service_level", type=float, default=0.95)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    d, sk = load()

    # total demand per SKU per day (summed across stores for the forecast demo)
    daily = (d.groupby(["sku_id", "date"])["units_demanded"].sum()
             .reset_index().sort_values(["sku_id", "date"]))

    # ---- back-test two simple, explainable forecasters on a 14-day hold-out ----
    results = []
    for sku, g in daily.groupby("sku_id"):
        s = g.set_index("date")["units_demanded"].asfreq("D").fillna(0)
        if len(s) < HORIZON + 21:
            continue
        train, test = s.iloc[:-HORIZON], s.iloc[-HORIZON:]
        ma = train.rolling(7).mean().iloc[-1]
        ewm = train.ewm(span=7).mean().iloc[-1]
        results.append({
            "sku_id": sku,
            "wape_ma": wape(test, np.repeat(ma, HORIZON)),
            "wape_ewm": wape(test, np.repeat(ewm, HORIZON)),
        })
    bt = pd.DataFrame(results)
    print(f"Back-test on {len(bt)} SKUs (14-day horizon):")
    print(f"  Moving average   median WAPE: {bt['wape_ma'].median():.1f}%")
    print(f"  EWMA (span 7)    median WAPE: {bt['wape_ewm'].median():.1f}%")
    best = "ewm" if bt["wape_ewm"].median() <= bt["wape_ma"].median() else "ma"
    print(f"  -> using {best.upper()} for the live forecast")

    # ---- forecast per store-SKU and build the replenishment recommendation ----
    z = norm.ppf(args.service_level)
    store_sku = (d.groupby(["darkstore_id", "sku_id"])
                 .agg(avg_daily=("units_demanded", "mean"),
                      sigma=("units_demanded", "std"))
                 .reset_index())
    store_sku = store_sku.merge(
        sk[["sku_id", "lead_time_days", "reorder_point", "order_qty",
            "rop_config", "category", "price_inr"]], on="sku_id")

    lt = store_sku["lead_time_days"]
    store_sku["forecast_daily"] = store_sku["avg_daily"].round(1)
    store_sku["safety_stock"] = (z * store_sku["sigma"] * np.sqrt(lt)).round()
    store_sku["recommended_rop"] = (store_sku["forecast_daily"] * lt
                                    + store_sku["safety_stock"]).round()
    store_sku["rop_gap"] = store_sku["recommended_rop"] - store_sku["reorder_point"]
    store_sku["gap_pct"] = (store_sku["rop_gap"] /
                            store_sku["reorder_point"].replace(0, np.nan) * 100).round(0)

    def action(r):
        if r["gap_pct"] >= 25:
            return "Raise ROP (under-stocking risk)"
        if r["gap_pct"] <= -25:
            return "Lower ROP (overstock/expiry risk)"
        return "OK"
    store_sku["recommendation"] = store_sku.apply(action, axis=1)

    flagged = store_sku[store_sku["recommendation"] != "OK"]
    print(f"\nStore-SKU combos needing re-parameterisation: "
          f"{len(flagged):,} of {len(store_sku):,} "
          f"({len(flagged)/len(store_sku):.0%})")
    print(store_sku["recommendation"].value_counts().to_string())

    # how well does the flag line up with the known misconfig? (validation)
    check = (store_sku.assign(flagged=store_sku["recommendation"] != "OK")
             .groupby("rop_config")["flagged"].mean().round(2))
    print("\nShare flagged by true config (validation):")
    print(check.to_string())

    store_sku.sort_values("rop_gap", key=abs, ascending=False)\
        .to_csv(OUT / "replenishment_recommendations.csv", index=False)
    bt.to_csv(OUT / "forecast_backtest.csv", index=False)
    print(f"\nRecommendations -> {OUT/'replenishment_recommendations.csv'}")

    # ---- chart: example forecast for the highest-volume SKU ----
    top_sku = daily.groupby("sku_id")["units_demanded"].sum().idxmax()
    s = daily[daily["sku_id"] == top_sku].set_index("date")["units_demanded"].asfreq("D").fillna(0)
    fc_val = s.iloc[:-HORIZON].ewm(span=7).mean().iloc[-1]
    future = pd.date_range(s.index[-HORIZON], periods=HORIZON, freq="D")
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    s.iloc[-60:].plot(ax=ax, color=ACCENT2, lw=1, label="Actual demand")
    ax.plot(future, np.repeat(fc_val, HORIZON), color=ACCENT, lw=2.5,
            label=f"EWMA forecast ({HORIZON}d)")
    ax.set_title(f"Demand forecast — {top_sku} (all darkstores)", fontweight="bold")
    ax.set_ylabel("Units/day"); ax.legend(frameon=False)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "forecast_example.png", dpi=130); plt.close(fig)

    # ---- chart: ROP gap distribution ----
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=PLOT_BG)
    ax.set_facecolor(PLOT_BG)
    ax.hist(store_sku["gap_pct"].clip(-150, 150).dropna(), bins=40, color=ACCENT)
    ax.axvline(0, color="#333", lw=1)
    ax.axvspan(-25, 25, color=ACCENT2, alpha=0.15, label="Within ±25% (OK)")
    ax.set_xlabel("Recommended ROP vs current (%)")
    ax.set_ylabel("Store-SKU count")
    ax.set_title("How far current reorder points sit from recommended", fontweight="bold")
    ax.legend(frameon=False)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "rop_gap_distribution.png", dpi=130); plt.close(fig)

    print(f"Charts written to {OUT}/")


if __name__ == "__main__":
    main()
