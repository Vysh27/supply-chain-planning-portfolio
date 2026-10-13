"""
Planning control-tower dashboard (Streamlit) — quick-commerce.

A self-serve monitoring surface for a planning / ops team: availability and
lost-sales, days-on-hand, vendor reliability and perishable wastage, all driven
by sidebar filters (date range, darkstore, category). This is the "dashboards and
alerts that give planning and ops reliable visibility" part of the APM role.

Run:
    python ../data_pipeline/generate_data.py   # if data/ not built yet
    streamlit run app.py
"""
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
ACCENT = "#1F6F54"
ACCENT2 = "#6A7B8C"
WARN = "#C0392B"

st.set_page_config(page_title="Planning Control Tower", page_icon="📦", layout="wide")


@st.cache_data
def load():
    # auto-generate on first run so the app works out of the box (e.g. on cloud)
    if not (DATA / "demand.csv").exists():
        import subprocess
        import sys
        subprocess.run([sys.executable, str(ROOT / "data_pipeline" / "generate_data.py")],
                       check=True)
    sk = pd.read_csv(DATA / "skus.csv")
    d = pd.read_csv(DATA / "demand.csv", parse_dates=["date"]).merge(
        sk[["sku_id", "category", "price_inr", "cost_inr", "shelf_life_days"]], on="sku_id")
    inv = pd.read_csv(DATA / "inventory.csv", parse_dates=["date"])
    w = pd.read_csv(DATA / "wastage.csv", parse_dates=["date"]).merge(
        sk[["sku_id", "category", "cost_inr"]], on="sku_id")
    po = pd.read_csv(DATA / "purchase_orders.csv", parse_dates=["expected_date"])  # already has vendor
    grn = pd.read_csv(DATA / "grn.csv", parse_dates=["received_date"])
    return sk, d, inv, w, po, grn


def inr(x):
    return f"₹{x:,.0f}"


def main():
    st.title("📦 Planning Control Tower")
    st.caption("Synthetic quick-commerce planning data. Filters apply to every tile.")

    sk, d, inv, w, po, grn = load()

    # ---- filters ----
    st.sidebar.header("Filters")
    min_d, max_d = d["date"].min().date(), d["date"].max().date()
    dr = st.sidebar.date_input("Date range", (min_d, max_d), min_value=min_d, max_value=max_d)
    start_d, end_d = dr if isinstance(dr, tuple) and len(dr) == 2 else (min_d, max_d)
    stores = sorted(d["darkstore_id"].unique())
    cats = sorted(d["category"].unique())
    pick_stores = st.sidebar.multiselect("Darkstore", stores, default=stores)
    pick_cats = st.sidebar.multiselect("Category", cats, default=cats)

    dm = d[(d["date"].dt.date >= start_d) & (d["date"].dt.date <= end_d)
           & (d["darkstore_id"].isin(pick_stores)) & (d["category"].isin(pick_cats))]
    wm = w[(w["date"].dt.date >= start_d) & (w["date"].dt.date <= end_d)
           & (w["darkstore_id"].isin(pick_stores)) & (w["category"].isin(pick_cats))]
    im = inv[(inv["date"].dt.date >= start_d) & (inv["date"].dt.date <= end_d)
             & (inv["darkstore_id"].isin(pick_stores))]
    if dm.empty:
        st.info("No data matches the current filters.")
        st.stop()

    # ---- KPIs ----
    avail = dm["units_fulfilled"].sum() / dm["units_demanded"].sum()
    lost_val = (dm["units_lost"] * dm["price_inr"]).sum()
    waste_val = (wm["units_expired"] * wm["cost_inr"]).sum()
    panel = im.merge(dm[["date", "darkstore_id", "sku_id", "units_demanded"]],
                     on=["date", "darkstore_id", "sku_id"], how="inner")
    panel = panel.sort_values(["darkstore_id", "sku_id", "date"])
    panel["avg_dem"] = (panel.groupby(["darkstore_id", "sku_id"])["units_demanded"]
                        .transform(lambda s: s.rolling(14, min_periods=3).mean()))
    panel["doh"] = panel["on_hand_units"] / panel["avg_dem"].replace(0, np.nan)
    median_doh = panel["doh"].median()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Availability", f"{avail*100:.1f}%", f"{(avail-0.95)*100:+.1f} pp vs 95% target",
              delta_color="normal")
    c2.metric("Lost sales", inr(lost_val))
    c3.metric("Wastage", inr(waste_val))
    c4.metric("Median DOH", f"{median_doh:.1f} d" if pd.notna(median_doh) else "—")
    st.divider()

    # ---- availability by category ----
    left, right = st.columns(2)
    with left:
        g = dm.groupby("category").apply(
            lambda x: pd.Series({"availability": x["units_fulfilled"].sum() / x["units_demanded"].sum() * 100,
                                 "lost_value": (x["units_lost"] * x["price_inr"]).sum()}),
            include_groups=False).reset_index()
        ch = alt.Chart(g).mark_bar(color=ACCENT).encode(
            x=alt.X("availability:Q", title="Availability %", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("category:N", sort="-x", title=None),
            tooltip=["category", alt.Tooltip("availability:Q", format=".1f"),
                     alt.Tooltip("lost_value:Q", title="Lost ₹", format=",.0f")],
        ).properties(height=260, title="Availability by category")
        rule = alt.Chart(pd.DataFrame({"t": [95]})).mark_rule(color=WARN, strokeDash=[4, 3]).encode(x="t:Q")
        st.altair_chart(ch + rule, use_container_width=True)
    with right:
        g2 = dm.groupby("darkstore_id").apply(
            lambda x: x["units_fulfilled"].sum() / x["units_demanded"].sum() * 100,
            include_groups=False).reset_index(name="availability")
        ch2 = alt.Chart(g2).mark_bar(color=ACCENT2).encode(
            x=alt.X("availability:Q", title="Availability %", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("darkstore_id:N", sort="-x", title=None),
            tooltip=["darkstore_id", alt.Tooltip("availability:Q", format=".1f")],
        ).properties(height=260, title="Availability by darkstore")
        st.altair_chart(ch2 + rule, use_container_width=True)

    # ---- vendor delay + wastage ----
    l2, r2 = st.columns(2)
    with l2:
        pg = po.merge(grn, on=["po_id", "sku_id", "darkstore_id"])
        pg = pg[pg["darkstore_id"].isin(pick_stores)]
        pg["late_days"] = (pg["received_date"] - pg["expected_date"]).dt.days
        vg = pg.groupby("vendor")["late_days"].mean().reset_index()
        chv = alt.Chart(vg).mark_bar(color=WARN).encode(
            x=alt.X("late_days:Q", title="Avg days late"),
            y=alt.Y("vendor:N", sort="-x", title=None),
            tooltip=["vendor", alt.Tooltip("late_days:Q", format=".2f")],
        ).properties(height=240, title="Vendor lateness (PO vs GRN)")
        st.altair_chart(chv, use_container_width=True)
    with r2:
        wc = wm.groupby("category").apply(
            lambda x: (x["units_expired"] * x["cost_inr"]).sum(), include_groups=False
        ).reset_index(name="waste_value")
        chw = alt.Chart(wc).mark_bar(color=ACCENT).encode(
            x=alt.X("waste_value:Q", title="Wastage ₹"),
            y=alt.Y("category:N", sort="-x", title=None),
            tooltip=["category", alt.Tooltip("waste_value:Q", format=",.0f")],
        ).properties(height=240, title="Wastage ₹ by category")
        st.altair_chart(chw, use_container_width=True)

    # ---- DOH distribution ----
    doh_vals = panel["doh"].clip(0, 40).dropna()
    chd = alt.Chart(pd.DataFrame({"doh": doh_vals})).mark_bar(color=ACCENT2).encode(
        x=alt.X("doh:Q", bin=alt.Bin(maxbins=40), title="Days on hand"),
        y=alt.Y("count()", title="Store-SKU-days"),
    ).properties(height=220, title="Days-on-hand distribution (overstock sits to the right)")
    st.altair_chart(chd, use_container_width=True)

    # ---- worst leakage SKUs table ----
    st.subheader("Top lost-sales SKUs")
    top = (dm.groupby(["sku_id", "category"]).apply(
        lambda x: pd.Series({"lost_units": x["units_lost"].sum(),
                             "lost_value": (x["units_lost"] * x["price_inr"]).sum(),
                             "availability": x["units_fulfilled"].sum() / x["units_demanded"].sum()}),
        include_groups=False).reset_index()
        .sort_values("lost_value", ascending=False).head(15).round(2))
    st.dataframe(top, use_container_width=True, hide_index=True)
    st.download_button("Download filtered demand (CSV)", dm.to_csv(index=False).encode(),
                       "filtered_demand.csv", "text/csv")


if __name__ == "__main__":
    main()
