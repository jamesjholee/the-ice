"""Score a slate and write the board.

python -m nhl.board                        # today -> board.html, board.csv
python -m nhl.board --out docs             # GitHub Pages layout: docs/index.html, docs/boards/<date>.html
python -m nhl.board --goalie LAK=Kuemper   # override projected starter (only affects the opp-goalie column)
"""
import argparse, csv, json, os, sys
from datetime import date, datetime, timezone, timedelta

from .data import games_on, roster
from .features import load_model, p_goal, p_sog_at_least, american
from .history import build_history
from .store import record, graded_rows

MARKETS = [("goal", "Anytime goal", "p_goal"), ("sog2", "2+ shots", "p_sog2"),
           ("sog3", "3+ shots", "p_sog3"), ("sog4", "4+ shots", "p_sog4")]


def score_slate(d, overrides, min_games):
    model = load_model()
    hist = build_history(d)
    games = games_on(d, final_only=False)
    rows = []
    for g in games:
        for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
            gpid = overrides.get(opp) or hist.likely_starter(opp)
            gname = hist.names.get(gpid, "?") if gpid else "?"
            gsv = hist.goalie_sv(gpid) if gpid else 0.905
            try:
                ros = roster(team)
            except Exception as e:
                print("[roster]", team, e, file=sys.stderr); continue
            for p in ros:
                f = hist.skater_feats(p["pid"], opp_goalie_pid=gpid, min_games=min_games)
                if not f:
                    continue
                pg = p_goal(f, model)
                rows.append(dict(
                    pid=p["pid"], name=hist.names.get(p["pid"], p["name"]), team=team, opp=opp,
                    pos=p["pos"], game=f"{g['away']}@{g['home']}", start=g.get("start") or "",
                    opp_goalie=gname, opp_gsv=round(gsv, 3),
                    sog_pg=round(f["sog_pg"], 2), sh_pct=round(f["sh_pct"], 3), pp_share=round(f["pp_share"], 2),
                    goals_l5=int(f["goals_l5"]), toi=round(f["toi_pg"], 1),
                    p_goal=round(pg, 3), fair_goal=american(pg),
                    p_sog2=round(p_sog_at_least(f, 2, model), 3), p_sog3=round(p_sog_at_least(f, 3, model), 3),
                    p_sog4=round(p_sog_at_least(f, 4, model), 3),
                ))
    rows.sort(key=lambda r: -r["p_goal"])
    return rows, games, hist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--out", default=".", help="output dir ('docs' for GitHub Pages)")
    ap.add_argument("--goalie", action="append", default=[], help="TEAM=LastName override")
    ap.add_argument("--min-games", type=int, default=8)
    a = ap.parse_args()
    # default date = today in US/Eastern (the Action runs in UTC)
    d = date.fromisoformat(a.date) if a.date else (datetime.now(timezone.utc) - timedelta(hours=4)).date()
    os.makedirs(os.path.join(a.out, "boards"), exist_ok=True)

    hist_for_overrides = None
    overrides = {}
    rows, games, hist = score_slate(d, {}, a.min_games)
    if a.goalie:
        for o in a.goalie:
            t, nm = o.split("=", 1)
            pid = next((p for p, n in hist.names.items() if nm.lower() in n.lower() and p in hist.gl), None)
            if pid:
                overrides[t.upper()] = pid
        if overrides:
            rows, games, hist = score_slate(d, overrides, a.min_games)

    with open(os.path.join(a.out, "board.csv"), "w", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    page = render(rows, games, d)
    open(os.path.join(a.out, "index.html"), "w").write(page)
    open(os.path.join(a.out, "boards", f"{d.isoformat()}.html"), "w").write(page)
    if not rows:
        print("no regular-season games on", d); return
    print(f"{'#':<3}{'player':<24}{'tm':<5}{'opp':<5}{'G':<3}{'SOG/g':>6}{'sh%':>7}{'toi':>6}{'P(G)':>7}{'fair':>7}{'P2+':>6}{'P3+':>6}")
    for i, r in enumerate(rows[:30], 1):
        print(f"{i:<3}{r['name'][:23]:<24}{r['team']:<5}{r['opp']:<5}{r['pos']:<3}{r['sog_pg']:>6}{r['sh_pct']:>7}"
              f"{r['toi']:>6}{r['p_goal']:>7}{r['fair_goal']:>7}{r['p_sog2']:>6}{r['p_sog3']:>6}")
    print(f"\n{len(rows)} players, {len(games)} games -> {a.out}/index.html")


def render(rows, games, d):
    rec_rows, tot = record()
    recent = graded_rows()[-15:][::-1]
    rec_html = ""
    if tot:
        rec_html = "<table class='rec'><tr><th class='l'>Market</th><th>Record</th><th>Hit</th><th>P&amp;L</th><th>ROI</th><th>Model avg</th><th>Book avg</th></tr>"
        for m, n, h, pnl, st, mp, bp in rec_rows:
            rec_html += f"<tr><td class='l'>{m}</td><td>{h}-{n-h}</td><td>{h/n:.0%}</td><td>{pnl:+.2f}u</td><td>{pnl/st:+.1%}</td><td>{mp:.1%}</td><td>{bp:.1%}</td></tr>"
        rec_html += f"<tr><td class='l'><b>Total</b></td><td><b>{tot[1]}-{tot[0]-tot[1]}</b></td><td>{tot[1]/tot[0]:.0%}</td><td><b>{tot[2]:+.2f}u</b></td><td>{tot[2]/tot[3]:+.1%}</td><td></td><td></td></tr></table>"
        rec_html += "<details><summary>Last graded picks</summary><table class='rec'><tr><th class='l'>Date</th><th class='l'>Player</th><th class='l'>Mkt</th><th>Odds</th><th>Model</th><th>Book</th><th>Res</th><th>P&amp;L</th></tr>"
        for r in recent:
            res = "HIT" if r["result"] == "1" else "miss"
            rec_html += f"<tr><td class='l'>{r['date']}</td><td class='l'>{r['name']}</td><td class='l'>{r['market']}</td><td>{int(r['odds']):+d}</td><td>{float(r['model_p']):.0%}</td><td>{float(r['book_p']):.0%}</td><td class='{'hit' if res=='HIT' else 'miss'}'>{res}</td><td>{float(r['pnl']):+.2f}</td></tr>"
        rec_html += "</table></details>"
    else:
        rec_html = "<p class='sub'>No graded picks yet. Add rows to <code>picks.csv</code>; the Action grades them the next morning.</p>"

    games_html = " · ".join(f"{g['away']}@{g['home']}" for g in games) or "no games"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = json.dumps(rows)
    tabs = "".join(f"<button {'class=on' if i==0 else ''} data-m='{m}'>{lbl}</button>" for i, (m, lbl, _) in enumerate(MARKETS))
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>the-ice — {d}</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--line:#262a33;--fg:#e8eaf0;--mut:#8b91a1;--acc:#3ddc97;--bad:#ff6b6b}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 Inter,system-ui,-apple-system,sans-serif;padding:16px;max-width:1200px;margin:0 auto}}
h1{{font-size:20px;margin:0}} h2{{font-size:15px;color:var(--mut);margin:22px 0 8px;text-transform:uppercase;letter-spacing:.04em}} .sub{{color:var(--mut);margin:4px 0 12px}}
table{{width:100%;border-collapse:collapse;background:var(--card)}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th{{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}} td.l,th.l{{text-align:left}} table.rec{{width:auto;min-width:420px;margin-bottom:8px}}
input{{width:64px;background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:3px 5px;text-align:right}}
.edge-pos{{color:var(--acc);font-weight:600}} .edge-neg{{color:var(--bad)}} .hit{{color:var(--acc)}} .miss{{color:var(--bad)}}
.tabs{{margin:10px 0}} .tabs button{{background:var(--card);color:var(--fg);border:1px solid var(--line);padding:6px 10px;border-radius:6px;margin:0 6px 6px 0;cursor:pointer}} .tabs button.on{{border-color:var(--acc)}}
.wrap{{overflow:auto;max-height:75vh;border:1px solid var(--line);border-radius:6px}} .note{{color:var(--mut);font-size:12px;margin-top:8px}} code{{background:#0f1115;padding:1px 4px;border-radius:3px}}
button.cp{{background:none;border:1px solid var(--line);color:var(--mut);border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px}} details summary{{cursor:pointer;color:var(--mut)}}
</style></head><body>
<h1>the-ice <span style="color:var(--mut);font-weight:400">· NHL props board · {d}</span></h1>
<div class="sub">{games_html} &nbsp;·&nbsp; built {stamp}</div>
<h2>Record</h2>{rec_html}
<h2>Board</h2>
<div class="sub">Model = rolling shots/game, finishing %, ice time, position, PP share (last 20 games). Type the book's price to see edge in points (model − implied). Bar: ≥ +4 on shot lines, ≥ +6 on goals. Opp goalie shown for lineup context only — backtest found no effect on scoring.</div>
<div class="tabs">{tabs}</div>
<div class="wrap"><table id="t"><thead></thead><tbody></tbody></table></div>
<div class="note">To log a pick, click <b>copy</b> on a row after entering the price, then paste the line into <code>picks.csv</code> and push — or run <code>python -m nhl.pick --date {d} --player "Name" --market sog3 --odds -120</code>. Rows: {len(rows)}.</div>
<script>
const rows={data};const MK={{goal:'p_goal',sog2:'p_sog2',sog3:'p_sog3',sog4:'p_sog4'}};const LINE={{goal:0.5,sog2:1.5,sog3:2.5,sog4:3.5}};
let market='goal';const odds=JSON.parse(localStorage.getItem('odds_{d}')||'{{}}');
function implied(o){{o=parseInt(String(o).replace('+',''));if(isNaN(o))return null;return o>0?100/(o+100):(-o)/(-o+100)}}
function fair(p){{return p<0.5?'+'+Math.round(100*(1-p)/p):'-'+Math.round(100*p/(1-p))}}
function render(){{
 const k=MK[market];rows.sort((a,b)=>b[k]-a[k]);
 document.querySelector('#t thead').innerHTML='<tr><th class="l">#</th><th class="l">Player</th><th class="l">Game</th><th>Pos</th><th>SOG/g</th><th>sh%</th><th>TOI</th><th>PP</th><th>G L5</th><th>Opp G</th><th>Model</th><th>Fair</th><th>Book</th><th>Edge</th><th></th></tr>';
 document.querySelector('#t tbody').innerHTML=rows.map((r,i)=>{{const p=r[k];const key=r.pid+market;const o=odds[key];const ip=o?implied(o):null;const e=ip!=null?((p-ip)*100):null;
  return `<tr><td class="l">${{i+1}}</td><td class="l">${{r.name}} <span style="color:var(--mut)">${{r.team}}</span></td><td class="l">${{r.game}}</td><td>${{r.pos}}</td><td>${{r.sog_pg}}</td><td>${{(r.sh_pct*100).toFixed(1)}}</td><td>${{r.toi}}</td><td>${{(r.pp_share*100).toFixed(0)}}%</td><td>${{r.goals_l5}}</td><td>${{r.opp_goalie.split(' ').slice(-1)[0]}} ${{r.opp_gsv}}</td><td><b>${{(p*100).toFixed(1)}}%</b></td><td>${{fair(p)}}</td><td><input value="${{o||''}}" data-k="${{key}}" placeholder="+150"></td><td class="${{e==null?'':e>=0?'edge-pos':'edge-neg'}}">${{e==null?'':(e>0?'+':'')+e.toFixed(1)}}</td><td><button class="cp" data-i="${{i}}">copy</button></td></tr>`}}).join('');
 document.querySelectorAll('#t input').forEach(el=>el.addEventListener('change',ev=>{{odds[ev.target.dataset.k]=ev.target.value;localStorage.setItem('odds_{d}',JSON.stringify(odds));render()}}));
 document.querySelectorAll('button.cp').forEach(b=>b.onclick=()=>{{const r=rows[+b.dataset.i];const o=odds[r.pid+market]||'';const ip=o?implied(o):'';
  const line=`,{d},${{r.pid}},${{r.name}},${{r.team}},${{r.opp}},${{market}},${{LINE[market]}},${{String(o).replace('+','')}},1,${{r[k]}},${{ip===''?'':ip.toFixed(4)}},,,,`;
  navigator.clipboard.writeText(line);b.textContent='copied';setTimeout(()=>b.textContent='copy',1200)}});
}}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');market=b.dataset.m;render()}});
render();
</script></body></html>"""


if __name__ == "__main__":
    main()
