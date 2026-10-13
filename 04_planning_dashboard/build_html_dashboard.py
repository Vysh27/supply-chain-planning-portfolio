"""
Build a single self-contained HTML planning dashboard from the data.

Pre-aggregates the planning data to compact cubes and embeds them in one
standalone HTML file with CSS/SVG charts and vanilla-JS filtering — no server,
no libraries, no internet needed. Open the file in any browser.

Usage:
    python build_html_dashboard.py          # -> planning_dashboard.html
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).parent / "planning_dashboard.html"


def load():
    if not (DATA / "demand.csv").exists():
        import subprocess, sys
        subprocess.run([sys.executable, str(ROOT / "data_pipeline" / "generate_data.py")], check=True)
    sk = pd.read_csv(DATA / "skus.csv")
    d = pd.read_csv(DATA / "demand.csv", parse_dates=["date"]).merge(
        sk[["sku_id", "category", "price_inr"]], on="sku_id")
    inv = pd.read_csv(DATA / "inventory.csv", parse_dates=["date"]).merge(
        sk[["sku_id", "category"]], on="sku_id")
    w = pd.read_csv(DATA / "wastage.csv", parse_dates=["date"]).merge(
        sk[["sku_id", "category", "cost_inr"]], on="sku_id")
    po = pd.read_csv(DATA / "purchase_orders.csv", parse_dates=["expected_date"])  # already has vendor
    grn = pd.read_csv(DATA / "grn.csv", parse_dates=["received_date"])
    return sk, d, inv, w, po, grn


def build_payload(sk, d, inv, w, po, grn):
    base = d["date"].min().normalize()
    stores = sorted(d["darkstore_id"].unique())
    cats = sorted(d["category"].unique())
    vendors = sorted(po["vendor"].unique())
    si = {s: i for i, s in enumerate(stores)}
    ci = {c: i for i, c in enumerate(cats)}
    vi = {v: i for i, v in enumerate(vendors)}

    def di(s):
        return int((pd.Timestamp(s).normalize() - base).days)

    # main cube: [di, store, cat, demanded, fulfilled, lost, lost_value, on_hand, waste_units, waste_value]
    dd = d.copy(); dd["di"] = (dd["date"].dt.normalize() - base).dt.days
    g = dd.groupby(["di", "darkstore_id", "category"]).agg(
        dem=("units_demanded", "sum"), ful=("units_fulfilled", "sum"),
        lost=("units_lost", "sum")).reset_index()
    g["lostv"] = (dd.groupby(["di", "darkstore_id", "category"])
                  .apply(lambda x: (x["units_lost"] * x["price_inr"]).sum(), include_groups=False)
                  .values)
    inv2 = inv.copy(); inv2["di"] = (inv2["date"].dt.normalize() - base).dt.days
    oh = inv2.groupby(["di", "darkstore_id", "category"])["on_hand_units"].sum().reset_index()
    g = g.merge(oh, on=["di", "darkstore_id", "category"], how="left").fillna({"on_hand_units": 0})
    w2 = w.copy(); w2["di"] = (w2["date"].dt.normalize() - base).dt.days
    wv = w2.groupby(["di", "darkstore_id", "category"]).agg(
        wu=("units_expired", "sum")).reset_index()
    wv["wval"] = (w2.groupby(["di", "darkstore_id", "category"])
                  .apply(lambda x: (x["units_expired"] * x["cost_inr"]).sum(), include_groups=False)
                  .values)
    g = g.merge(wv, on=["di", "darkstore_id", "category"], how="left").fillna({"wu": 0, "wval": 0})

    recs = [[int(r.di), si[r.darkstore_id], ci[r.category], int(r.dem), int(r.ful),
             int(r.lost), round(float(r.lostv)), int(r.on_hand_units),
             int(r.wu), round(float(r.wval))] for r in g.itertuples()]

    # vendor cube: [recv_di, store, vendor, late_sum, n]
    pg = po.merge(grn, on=["po_id", "sku_id", "darkstore_id"])
    pg["recv_di"] = (pg["received_date"].dt.normalize() - base).dt.days
    pg["late"] = (pg["received_date"] - pg["expected_date"]).dt.days
    vg = pg.groupby(["recv_di", "darkstore_id", "vendor"]).agg(
        late_sum=("late", "sum"), n=("late", "count")).reset_index()
    vrecs = [[int(r.recv_di), si[r.darkstore_id], vi[r.vendor], int(r.late_sum), int(r.n)]
             for r in vg.itertuples()]

    return {"base": base.date().isoformat(), "span": int(dd["di"].max()) + 1,
            "stores": stores, "cats": cats, "vendors": vendors,
            "recs": recs, "vrecs": vrecs}


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planning Control Tower</title>
<style>
  :root{--accent:#1F6F54;--accent2:#6A7B8C;--warn:#C0392B;--ink:#1b211e;--muted:#6a7470;
    --bg:#f7f9f8;--card:#fff;--line:#e6ece9;--pos:#1f8a5b;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
  header h1{font-size:23px;margin:0 0 4px}
  header p{color:var(--muted);margin:0 0 20px;font-size:13px}
  .layout{display:grid;grid-template-columns:230px 1fr;gap:22px;align-items:start}
  @media (max-width:820px){.layout{grid-template-columns:1fr}}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
  .panel h3{margin:0 0 12px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
  label.small{font-size:11px;color:var(--muted);display:block;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.05em}
  input[type=date]{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:7px;font-size:13px;background:#fff;color:var(--ink)}
  .chk{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;cursor:pointer}
  .chk input{accent-color:var(--accent)}
  button.reset{margin-top:14px;width:100%;padding:8px;border:1px solid var(--accent);background:#fff;color:var(--accent);border-radius:8px;font-size:13px;cursor:pointer;font-weight:600}
  button.reset:hover{background:var(--accent);color:#fff}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
  @media (max-width:640px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .kpi .lab{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
  .kpi .val{font-size:22px;font-weight:700;margin:6px 0 2px}
  .kpi .sub{font-size:12px;font-weight:600}
  .sub.pos{color:var(--pos)} .sub.neg{color:var(--warn)} .sub.flat{color:var(--muted)}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:4px}
  @media (max-width:820px){.grid2{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:18px}
  .card.tight{margin-top:0}
  .card h2{font-size:14px;margin:0 0 14px}
  .barrow{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}
  .barrow .name{width:110px;flex:none}
  .barrow .track{flex:1;background:#eef3f1;border-radius:5px;height:16px;overflow:hidden}
  .barrow .fill{height:100%;border-radius:5px}
  .barrow .amt{width:70px;flex:none;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
  .foot{color:var(--muted);font-size:11px;margin-top:22px;text-align:center}
  .empty{color:var(--muted);font-size:13px;padding:16px 0;text-align:center}
</style></head>
<body><div class="wrap">
<header><h1>📦 Planning Control Tower</h1>
<p>Synthetic quick-commerce planning data, self-contained HTML. Filters apply to every tile.</p></header>
<div class="layout">
  <aside class="panel">
    <h3>Filters</h3>
    <label class="small">From</label><input type="date" id="from">
    <label class="small">To</label><input type="date" id="to">
    <label class="small">Darkstore</label><div id="storeBox"></div>
    <label class="small">Category</label><div id="catBox"></div>
    <button class="reset" id="reset">Reset filters</button>
  </aside>
  <main>
    <div class="kpis" id="kpis"></div>
    <div class="grid2">
      <div class="card tight"><h2>Availability by category</h2><div id="availCat"></div></div>
      <div class="card tight"><h2>Availability by darkstore</h2><div id="availStore"></div></div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Lost sales ₹ by category</h2><div id="lostCat"></div></div>
      <div class="card"><h2>Wastage ₹ by category</h2><div id="wasteCat"></div></div>
    </div>
    <div class="card"><h2>Vendor lateness (PO vs GRN, avg days)</h2><div id="vendor"></div></div>
    <p class="foot" id="foot"></p>
  </main>
</div></div>
<script>
const P=__PAYLOAD__;
const fINR=new Intl.NumberFormat('en-IN');
const money=v=>'₹'+fINR.format(Math.round(v));
const base=new Date(P.base+'T00:00:00');
const addDays=n=>{const d=new Date(base);d.setDate(d.getDate()+n);return d;};
const iso=d=>d.toISOString().slice(0,10);
const diFromISO=s=>Math.round((new Date(s+'T00:00:00')-base)/86400000);
const TARGET=95;
let fStores=new Set(P.stores.map((_,i)=>i));
let fCats=new Set(P.cats.map((_,i)=>i));
let fromDi=0,toDi=P.span-1;

function controls(){
  document.getElementById('from').value=iso(addDays(0));
  document.getElementById('from').min=iso(addDays(0));document.getElementById('from').max=iso(addDays(P.span-1));
  document.getElementById('to').value=iso(addDays(P.span-1));
  document.getElementById('to').min=iso(addDays(0));document.getElementById('to').max=iso(addDays(P.span-1));
  const sb=document.getElementById('storeBox');
  P.stores.forEach((s,i)=>sb.insertAdjacentHTML('beforeend',`<label class="chk"><input type="checkbox" data-s="${i}" checked>${s}</label>`));
  const cb=document.getElementById('catBox');
  P.cats.forEach((c,i)=>cb.insertAdjacentHTML('beforeend',`<label class="chk"><input type="checkbox" data-c="${i}" checked>${c}</label>`));
  document.getElementById('from').addEventListener('change',e=>{fromDi=diFromISO(e.target.value);render();});
  document.getElementById('to').addEventListener('change',e=>{toDi=diFromISO(e.target.value);render();});
  sb.addEventListener('change',e=>{const i=+e.target.dataset.s;e.target.checked?fStores.add(i):fStores.delete(i);render();});
  cb.addEventListener('change',e=>{const i=+e.target.dataset.c;e.target.checked?fCats.add(i):fCats.delete(i);render();});
  document.getElementById('reset').addEventListener('click',()=>{
    fromDi=0;toDi=P.span-1;fStores=new Set(P.stores.map((_,i)=>i));fCats=new Set(P.cats.map((_,i)=>i));
    document.getElementById('from').value=iso(addDays(0));document.getElementById('to').value=iso(addDays(P.span-1));
    document.querySelectorAll('#storeBox input,#catBox input').forEach(x=>x.checked=true);render();});
}
function slice(){const o=[];for(const r of P.recs){if(r[0]<fromDi||r[0]>toDi)continue;if(!fStores.has(r[1]))continue;if(!fCats.has(r[2]))continue;o.push(r);}return o;}
function vslice(){const o=[];for(const r of P.vrecs){if(r[0]<fromDi||r[0]>toDi)continue;if(!fStores.has(r[1]))continue;o.push(r);}return o;}
// indices: di0 s1 c2 dem3 ful4 lost5 lostv6 oh7 wu8 wval9
const col=(rows,k)=>rows.reduce((a,r)=>a+r[k],0);

function kpis(rows){
  const dem=col(rows,3),ful=col(rows,4),lv=col(rows,6),wv=col(rows,9),oh=col(rows,7);
  const avail=dem?ful/dem*100:0;
  const days=toDi-fromDi+1;
  const doh=dem?(oh/days)/(dem/days):0;
  const gap=avail-TARGET;
  document.getElementById('kpis').innerHTML=`
   <div class="kpi"><div class="lab">Availability</div><div class="val">${avail.toFixed(1)}%</div>
     <div class="sub ${gap>=0?'pos':'neg'}">${gap>=0?'+':''}${gap.toFixed(1)} pp vs ${TARGET}% target</div></div>
   <div class="kpi"><div class="lab">Lost sales</div><div class="val">${money(lv)}</div><div class="sub flat">unmet demand × price</div></div>
   <div class="kpi"><div class="lab">Wastage</div><div class="val">${money(wv)}</div><div class="sub flat">expired × cost</div></div>
   <div class="kpi"><div class="lab">Avg cover (DOH)</div><div class="val">${doh.toFixed(1)} d</div><div class="sub flat">on-hand ÷ daily demand</div></div>`;
}

function bars(elId,rows,keyIdx,labels,kind){
  // kind: 'avail' uses ful/dem per label; 'val' sums valueIdx; else sum
  const agg={};labels.forEach((_,i)=>agg[i]={dem:0,ful:0,v:0});
  rows.forEach(r=>{const k=r[keyIdx];agg[k].dem+=r[3];agg[k].ful+=r[4];agg[k].v+=(kind==='lost'?r[6]:kind==='waste'?r[9]:0);});
  let arr;
  if(kind==='avail'){arr=labels.map((n,i)=>[n,agg[i].dem?agg[i].ful/agg[i].dem*100:0]).filter(x=>x[1]>0);}
  else{arr=labels.map((n,i)=>[n,agg[i].v]).filter(x=>x[1]>0);}
  arr.sort((a,b)=>b[1]-a[1]);
  const el=document.getElementById(elId);
  if(!arr.length){el.innerHTML='<div class="empty">No data for this selection.</div>';return;}
  const max=kind==='avail'?100:Math.max(...arr.map(x=>x[1]));
  el.innerHTML=arr.map(([n,v])=>{
    const w=(v/max*100).toFixed(1);
    const color=kind==='avail'?(v>=95?'var(--accent)':v>=85?'#E59866':'var(--warn)'):(kind==='waste'?'var(--accent)':'var(--warn)');
    const amt=kind==='avail'?v.toFixed(1)+'%':money(v);
    return `<div class="barrow"><div class="name">${n}</div><div class="track"><div class="fill" style="width:${w}%;background:${color}"></div></div><div class="amt">${amt}</div></div>`;
  }).join('');
}

function vendorBars(){
  const rows=vslice();const agg={};P.vendors.forEach((_,i)=>agg[i]={s:0,n:0});
  rows.forEach(r=>{agg[r[2]].s+=r[3];agg[r[2]].n+=r[4];});
  const arr=P.vendors.map((n,i)=>[n,agg[i].n?agg[i].s/agg[i].n:0,agg[i].n]).filter(x=>x[2]>0).sort((a,b)=>b[1]-a[1]);
  const el=document.getElementById('vendor');
  if(!arr.length){el.innerHTML='<div class="empty">No receipts in this selection.</div>';return;}
  const max=Math.max(0.1,...arr.map(x=>x[1]));
  el.innerHTML=arr.map(([n,v,c])=>{
    const color=v>=0.75?'var(--warn)':v>=0.4?'#E59866':'var(--accent)';
    return `<div class="barrow"><div class="name">${n}</div><div class="track"><div class="fill" style="width:${(v/max*100).toFixed(1)}%;background:${color}"></div></div><div class="amt">${v.toFixed(2)}d</div></div>`;
  }).join('');
}

function render(){
  if(toDi<fromDi){const t=fromDi;fromDi=toDi;toDi=t;}
  const rows=slice();
  kpis(rows);
  bars('availCat',rows,2,P.cats,'avail');
  bars('availStore',rows,1,P.stores,'avail');
  bars('lostCat',rows,2,P.cats,'lost');
  bars('wasteCat',rows,2,P.cats,'waste');
  vendorBars();
  const from=iso(addDays(fromDi)),to=iso(addDays(toDi));
  document.getElementById('foot').textContent=`${fINR.format(col(rows,3))} units demanded over ${toDi-fromDi+1} days (${from} to ${to}). Synthetic data — portfolio demonstration.`;
}
controls();render();
</script></body></html>
"""


def main():
    sk, d, inv, w, po, grn = load()
    payload = build_payload(sk, d, inv, w, po, grn)
    html = HTML.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    OUT.write_text(html, encoding="utf-8")
    kb = len(html.encode()) / 1024
    print(f"Wrote {OUT} ({kb:.0f} KB, {len(payload['recs']):,} + {len(payload['vrecs']):,} rows embedded)")


if __name__ == "__main__":
    main()
