"""Score today's slate and write board.html + board.csv.

python -m nhl.board                       # today
python -m nhl.board --date 2026-10-08
python -m nhl.board --goalie LAK=Kuemper --goalie TOR=Stolarz   # override projected starters
"""
import argparse, csv, html, json, sys
from datetime import date

from .data import games_on, roster
from .features import load_model, p_goal, p_sog_at_least, american
from .history import build_history


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--goalie", action="append", default=[], help="TEAM=LastName override")
    ap.add_argument("--min-games", type=int, default=8)
    a = ap.parse_args()
    d = date.fromisoformat(a.date)
    model = load_model()
    hist = build_history(d)
    games = games_on(d, final_only=False)
    if not games:
        print("no regular-season games on", d); return
    overrides = {}
    for o in a.goalie:
        t, nm = o.split("=", 1)
        pid = next((p for p, n in hist.names.items() if nm.lower() in n.lower() and p in hist.gl), None)
        if pid is None:
            print(f"[goalie] no history for '{nm}' on {t}; using projection", file=sys.stderr)
        else:
            overrides[t.upper()] = pid

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
                f = hist.skater_feats(p["pid"], opp_goalie_pid=gpid, min_games=a.min_games)
                if not f:
                    continue
                pg = p_goal(f, model)
                rows.append(dict(
                    pid=p["pid"], name=hist.names.get(p["pid"], p["name"]), team=team, opp=opp,
                    pos=p["pos"], game=f"{g['away']}@{g['home']}", opp_goalie=gname, opp_gsv=round(gsv, 3),
                    sog_pg=round(f["sog_pg"], 2), sh_pct=round(f["sh_pct"], 3), pp_share=round(f["pp_share"], 2),
                    goals_l5=int(f["goals_l5"]), toi=round(f["toi_pg"], 1),
                    p_goal=round(pg, 3), fair_goal=american(pg),
                    p_sog2=round(p_sog_at_least(f, 2, model), 3), p_sog3=round(p_sog_at_least(f, 3, model), 3),
                    p_sog4=round(p_sog_at_least(f, 4, model), 3),
                ))
    rows.sort(key=lambda r: -r["p_goal"])
    with open("board.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    write_html(rows, d)
    print(f"{'#':<3}{'player':<24}{'tm':<5}{'opp':<5}{'G':<4}{'SOG/g':>6}{'sh%':>7}{'pp':>5}{'gsv':>7}{'P(G)':>7}{'fair':>7}{'P3+':>6}")
    for i, r in enumerate(rows[:40], 1):
        print(f"{i:<3}{r['name'][:23]:<24}{r['team']:<5}{r['opp']:<5}{r['pos']:<4}{r['sog_pg']:>6}{r['sh_pct']:>7}"
              f"{r['pp_share']:>5}{r['opp_gsv']:>7}{r['p_goal']:>7}{r['fair_goal']:>7}{r['p_sog3']:>6}")
    print(f"\n{len(rows)} players scored; board.html + board.csv written. Projected opposing goalies: "
          + ", ".join(sorted({f'{r["opp"]}:{r["opp_goalie"]}' for r in rows})))


def write_html(rows, d):
    data = json.dumps(rows)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NHL board {d}</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--line:#262a33;--fg:#e8eaf0;--mut:#8b91a1;--acc:#3ddc97;--bad:#ff6b6b}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 Inter,system-ui,-apple-system,sans-serif;padding:16px}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:var(--mut);margin-bottom:12px}}
table{{width:100%;border-collapse:collapse;background:var(--card)}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th{{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card);cursor:pointer}} td.l,th.l{{text-align:left}}
input{{width:62px;background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:3px 5px;text-align:right}}
.edge-pos{{color:var(--acc);font-weight:600}} .edge-neg{{color:var(--bad)}} .tabs{{margin:10px 0}} .tabs button{{background:var(--card);color:var(--fg);border:1px solid var(--line);padding:6px 10px;border-radius:6px;margin-right:6px;cursor:pointer}}
.tabs button.on{{border-color:var(--acc)}} .wrap{{overflow:auto;max-height:80vh}} .note{{color:var(--mut);font-size:12px;margin-top:8px}}
</style></head><body>
<h1>NHL props board — {d}</h1>
<div class="sub">Model probability from rolling shots/game, finishing %, PP share, opponent goalie. Type the book's price to see edge. Edge = model prob − implied prob (after no-vig is NOT applied; use ≥ +4 pts as your bar).</div>
<div class="tabs"><button class="on" data-m="goal">Anytime goal</button><button data-m="sog2">2+ shots</button><button data-m="sog3">3+ shots</button><button data-m="sog4">4+ shots</button></div>
<div class="wrap"><table id="t"><thead></thead><tbody></tbody></table></div>
<div class="note">Log a pick from Terminal: <code>python -m nhl.pick --date {d} --player "Name" --market goal --odds +150</code> (markets: goal, sog2, sog3, sog4). Rows: {len(rows)}.</div>
<script>
const rows={data};let market='goal';const odds={{}};
const pkey=m=>m==='goal'?'p_goal':'p_'+m;
function implied(o){{o=parseInt(String(o).replace('+',''));if(isNaN(o))return null;return o>0?100/(o+100):(-o)/(-o+100)}}
function fair(p){{return p<0.5?'+'+Math.round(100*(1-p)/p):'-'+Math.round(100*p/(1-p))}}
function render(){{
 const k=pkey(market);rows.sort((a,b)=>b[k]-a[k]);
 document.querySelector('thead').innerHTML='<tr><th class="l">#</th><th class="l">Player</th><th class="l">Tm</th><th class="l">Opp</th><th>Pos</th><th>SOG/g</th><th>sh%</th><th>PP</th><th>G L5</th><th>Opp G (sv%)</th><th>Model</th><th>Fair</th><th>Book</th><th>Edge</th></tr>';
 document.querySelector('tbody').innerHTML=rows.map((r,i)=>{{const p=r[k];const o=odds[r.pid+market];const ip=o?implied(o):null;const e=ip!=null?((p-ip)*100):null;
  return `<tr><td class="l">${{i+1}}</td><td class="l">${{r.name}}</td><td class="l">${{r.team}}</td><td class="l">${{r.opp}}</td><td>${{r.pos}}</td><td>${{r.sog_pg}}</td><td>${{(r.sh_pct*100).toFixed(1)}}</td><td>${{(r.pp_share*100).toFixed(0)}}%</td><td>${{r.goals_l5}}</td><td>${{r.opp_goalie}} (${{r.opp_gsv}})</td><td>${{(p*100).toFixed(1)}}%</td><td>${{fair(p)}}</td><td><input value="${{o||''}}" data-id="${{r.pid}}" placeholder="+150"></td><td class="${{e==null?'':e>=0?'edge-pos':'edge-neg'}}">${{e==null?'':(e>0?'+':'')+e.toFixed(1)}}</td></tr>`}}).join('');
 document.querySelectorAll('input').forEach(el=>el.addEventListener('change',ev=>{{odds[ev.target.dataset.id+market]=ev.target.value;render()}}));
}}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');market=b.dataset.m;render()}});
render();
</script></body></html>"""
    open("board.html", "w").write(page)


if __name__ == "__main__":
    main()
