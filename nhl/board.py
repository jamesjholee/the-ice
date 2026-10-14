"""Score a slate, join book prices, auto-log model picks, write the board.

python -m nhl.board --out docs                 # today
python -m nhl.board --out docs --auto-pick     # also append model picks to picks.csv (the 6pm Action run)
python -m nhl.board --goalie LAK=Kuemper       # override projected starter (lineup-context column only)

Book prices come from <out>/odds.json if present (written by `python -m nhl.odds`).
"""
import argparse, csv, json, os, sys
from datetime import date, datetime, timezone, timedelta

from .data import games_on, roster
from .features import load_model, p_goal, p_sog_at_least, american, implied
from .history import build_history
from .odds import norm, best
from .store import record, graded_rows, add_pick, _read as read_picks

MARKETS = [("goal", "Anytime goal", "p_goal"), ("sog2", "2+ shots", "p_sog2"),
           ("sog3", "3+ shots", "p_sog3"), ("sog4", "4+ shots", "p_sog4")]
# auto-pick thresholds: model minus book implied, in probability points
EDGE_BAR = {"goal": 0.06, "sog2": 0.05, "sog3": 0.04, "sog4": 0.04}
MAX_AUTO_PICKS = 8


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
                f = hist.skater_feats(p["pid"], opp_goalie_pid=gpid, min_games=min_games, opp_team=opp)
                if not f:
                    continue
                pg = p_goal(f, model)
                rows.append(dict(
                    pid=p["pid"], name=hist.names.get(p["pid"], p["name"]), full_name=p["name"],
                    team=team, opp=opp, pos=p["pos"], game=f"{g['away']}@{g['home']}", start=g.get("start") or "",
                    opp_goalie=gname, opp_gsv=round(gsv, 3),
                    opp_sa=round(f["opp_sa"], 1), team_sf=round(hist.team_shots_for(team), 1),
                    sog_pg=round(f["sog_pg"], 2), sog_l5=round(f["sog_l5"], 2), sog_l10=round(f["sog_l10"], 2),
                    hit2_l10=round(f["hit2_l10"], 2), hit3_l10=round(f["hit3_l10"], 2), goal_l10=round(f["goal_l10"], 2),
                    toi_l5=round(f["toi_l5"], 1),
                    sh_pct=round(f["sh_pct"], 3), pp_share=round(f["pp_share"], 2),
                    goals_l5=int(f["goals_l5"]), toi=round(f["toi_pg"], 1), n_games=f.get("n_games", 0),
                    p_goal=round(pg, 3), fair_goal=american(pg),
                    p_sog2=round(p_sog_at_least(f, 2, model), 3), p_sog3=round(p_sog_at_least(f, 3, model), 3),
                    p_sog4=round(p_sog_at_least(f, 4, model), 3),
                ))
    rows.sort(key=lambda r: -r["p_goal"])
    return rows, games, hist


def join_odds(rows, odds_path):
    """Attach book_goal / book_sogN (best American price) + book name to each row."""
    if not os.path.exists(odds_path):
        return None
    js = json.load(open(odds_path))
    players = js.get("players", {})
    hit = 0
    for r in rows:
        o = players.get(norm(r["full_name"])) or players.get(norm(r["name"]))
        r["book_goal"] = r["book_goal_bk"] = ""
        for k in ("sog2", "sog3", "sog4"):
            r[f"book_{k}"] = r[f"book_{k}_bk"] = ""
        if not o:
            continue
        hit += 1
        bk, px = best(o.get("goal", {}))
        if bk:
            r["book_goal"], r["book_goal_bk"] = px, bk
        # shots: books post ONE line per player (e.g. 2.5). Map it to the matching k.
        for bk, v in o.get("sog", {}).items():
            k = f"sog{int(v['line'] + 0.5)}"
            if k in ("sog2", "sog3", "sog4"):
                cur = r.get(f"book_{k}")
                if cur == "" or v["over"] > cur:
                    r[f"book_{k}"], r[f"book_{k}_bk"] = v["over"], bk
    print(f"[odds] matched {hit}/{len(rows)} board rows to book prices", file=sys.stderr)
    return js.get("meta", {})


def auto_picks(rows, d):
    """Rows where model beats the best book price by the market's bar. Returns picks list."""
    existing = {(r["date"], str(r["pid"]), r["market"]) for r in read_picks()}
    cands = []
    for r in rows:
        for m, _, pk in MARKETS:
            px = r.get(f"book_{m}")
            if px == "" or px is None:
                continue
            edge = r[pk] - implied(px)
            if edge >= EDGE_BAR[m] and (d.isoformat(), str(r["pid"]), m) not in existing:
                cands.append((edge, m, r, px))
    cands.sort(key=lambda t: -t[0])
    picked = []
    for edge, m, r, px in cands[:MAX_AUTO_PICKS]:
        line = {"goal": 0.5, "sog2": 1.5, "sog3": 2.5, "sog4": 3.5}[m]
        add_pick(d.isoformat(), r["pid"], r["name"], r["team"], r["opp"], m, line, int(px), 1.0,
                 r[{"goal": "p_goal", "sog2": "p_sog2", "sog3": "p_sog3", "sog4": "p_sog4"}[m]],
                 implied(px), note=f"auto {r.get(f'book_{m}_bk','')}")
        picked.append((r["name"], m, px, edge))
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--out", default=".", help="output dir ('docs' for GitHub Pages)")
    ap.add_argument("--goalie", action="append", default=[], help="TEAM=LastName override")
    ap.add_argument("--min-games", type=int, default=8)
    ap.add_argument("--auto-pick", action="store_true", help="append model picks to picks.csv")
    a = ap.parse_args()
    d = date.fromisoformat(a.date) if a.date else (datetime.now(timezone.utc) - timedelta(hours=4)).date()
    os.makedirs(os.path.join(a.out, "boards"), exist_ok=True)

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

    odds_meta = join_odds(rows, os.path.join(a.out, "odds.json"))
    picked = auto_picks(rows, d) if (a.auto_pick and odds_meta) else []
    todays_picks = [r for r in read_picks() if r["date"] == d.isoformat()]

    with open(os.path.join(a.out, "board.csv"), "w", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    page = render(rows, games, d, odds_meta, todays_picks)
    open(os.path.join(a.out, "index.html"), "w").write(page)
    open(os.path.join(a.out, "boards", f"{d.isoformat()}.html"), "w").write(page)
    if not rows:
        print("no regular-season games on", d); return
    print(f"{'#':<3}{'player':<24}{'tm':<5}{'opp':<5}{'G':<3}{'SOG/g':>6}{'toi':>6}{'P(G)':>7}{'fair':>7}{'book':>7}{'P3+':>6}{'book3':>7}")
    for i, r in enumerate(rows[:25], 1):
        print(f"{i:<3}{r['name'][:23]:<24}{r['team']:<5}{r['opp']:<5}{r['pos']:<3}{r['sog_pg']:>6}{r['toi']:>6}"
              f"{r['p_goal']:>7}{r['fair_goal']:>7}{str(r.get('book_goal','')):>7}{r['p_sog3']:>6}{str(r.get('book_sog3','')):>7}")
    if picked:
        print("\nauto-picks:", "; ".join(f"{n} {m} @{px:+d} (+{e*100:.1f})" for n, m, px, e in picked))
    print(f"\n{len(rows)} players, {len(games)} games -> {a.out}/index.html")


def render(rows, games, d, odds_meta, todays_picks):
    rec_rows, tot = record()
    recent = graded_rows()[-15:][::-1]
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
        rec_html = "<p class='sub'>No graded picks yet. Picks are auto-logged from the 6pm run when the model beats the best book price; graded the next morning.</p>"

    if todays_picks:
        picks_html = "<table class='rec'><tr><th class='l'>Player</th><th class='l'>Market</th><th>Book</th><th>Model</th><th>Implied</th><th>Edge</th><th class='l'>Src</th></tr>"
        for r in todays_picks:
            mp, bp = float(r["model_p"]), float(r["book_p"])
            picks_html += f"<tr><td class='l'>{r['name']} <span style='color:var(--mut)'>{r['team']}</span></td><td class='l'>{r['market']} o{r['line']}</td><td>{int(float(r['odds'])):+d}</td><td>{mp:.0%}</td><td>{bp:.0%}</td><td class='edge-pos'>+{(mp-bp)*100:.1f}</td><td class='l'>{r.get('note','')}</td></tr>"
        picks_html += "</table>"
    elif odds_meta:
        picks_html = "<p class='sub'>No rows cleared the edge bar today.</p>"
    else:
        picks_html = "<p class='sub'>No book prices this run (odds are fetched on the 6pm run).</p>"

    def et(iso):
        try:
            t = datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(hours=4)
            return t.strftime("%-I:%M %p")
        except Exception:
            return ""
    games_sorted = sorted(games, key=lambda g: g.get("start") or "")
    games_html = " · ".join(f"{g['away']}@{g['home']} {et(g.get('start') or '')}" for g in games_sorted) or "no games"
    gmeta = {f"{g['away']}@{g['home']}": dict(start=g.get("start") or "", et=et(g.get("start") or "")) for g in games}
    for r in rows:
        r["et"] = gmeta.get(r["game"], {}).get("et", "")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    odds_note = (f"book prices: best of {odds_meta.get('events', 0)} games fetched {odds_meta.get('fetched', '')[:16]}Z · "
                 f"{odds_meta.get('credits_remaining', '?')} API credits left") if odds_meta else "no book prices this run"
    data = json.dumps(rows)
    gdata = json.dumps(gmeta)
    tabs = "".join(f"<button {'class=on' if i==0 else ''} data-m='{m}'>{lbl}</button>" for i, (m, lbl, _) in enumerate(MARKETS))
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>the-ice — {d}</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--line:#262a33;--fg:#e8eaf0;--mut:#8b91a1;--acc:#3ddc97;--bad:#ff6b6b}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 Inter,system-ui,-apple-system,sans-serif;padding:16px;max-width:1240px;margin:0 auto}}
h1{{font-size:20px;margin:0}} h2{{font-size:15px;color:var(--mut);margin:22px 0 8px;text-transform:uppercase;letter-spacing:.04em}} .sub{{color:var(--mut);margin:4px 0 12px}}
table{{width:100%;border-collapse:collapse;background:var(--card)}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th{{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}} td.l,th.l{{text-align:left}} table.rec{{width:auto;min-width:420px;margin-bottom:8px}}
input{{width:64px;background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:3px 5px;text-align:right}}
.edge-pos{{color:var(--acc);font-weight:600}} .edge-neg{{color:var(--bad)}} .hit{{color:var(--acc)}} .miss{{color:var(--bad)}} .bk{{color:var(--mut);font-size:11px}}
.tabs{{margin:10px 0}} .tabs button{{background:var(--card);color:var(--fg);border:1px solid var(--line);padding:6px 10px;border-radius:6px;margin:0 6px 6px 0;cursor:pointer}} .tabs button.on{{border-color:var(--acc)}}
.wrap{{overflow:auto;max-height:75vh;border:1px solid var(--line);border-radius:6px}} .note{{color:var(--mut);font-size:12px;margin-top:8px}} code{{background:#0f1115;padding:1px 4px;border-radius:3px}}
details summary{{cursor:pointer;color:var(--mut)}}
.lbl{{color:var(--mut);font-size:12px;margin:0 8px 0 4px}} .mut{{color:var(--mut)}} .good{{color:var(--acc)}} .bad{{color:var(--bad)}} .up{{color:var(--acc)}} .dn{{color:var(--bad)}} .fl{{color:var(--mut)}}
.game{{margin:14px 0 22px}} .gh{{font-size:16px;font-weight:600;margin-bottom:8px}} .sides{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media(max-width:1000px){{.sides{{grid-template-columns:1fr}}}}
.side{{border:1px solid var(--line);border-radius:6px;overflow:auto}} .side .th{{padding:6px 8px;background:#1c2029;border-bottom:1px solid var(--line)}} .side table{{font-size:13px}} .side th,.side td{{padding:4px 6px}}
</style></head><body>
<h1>the-ice <span style="color:var(--mut);font-weight:400">· NHL props board · {d}</span></h1>
<div class="sub">{games_html} &nbsp;·&nbsp; built {stamp} &nbsp;·&nbsp; {odds_note}</div>
<h2>Record</h2>{rec_html}
<h2>Model picks today</h2>{picks_html}
<h2>Board</h2>
<div class="sub">Model = rolling shots/game, finishing %, ice time, position, PP share, <b>opponent shots allowed</b> (last 20 games). Form = last 5 / last 10. Matchup = opponent's shots allowed per game (league ~28; higher = softer). Book = best US price; type your own to override. Edge = model − implied, in points.</div>
<div class="tabs"><span class="lbl">Market</span>{tabs}<span class="lbl">View</span><button class="on" data-v="games">By game</button><button data-v="edge">By edge</button><button data-v="model">By model</button></div>
<div id="board"></div>
<div class="note">Rows: {len(rows)}. Shots prices are shown for the line the book posted (a 2.5 line fills the 3+ tab). Form hit-rates are the player's last-10 rate for that line.</div>
<script>
const rows={data};const G={gdata};const MK={{goal:'p_goal',sog2:'p_sog2',sog3:'p_sog3',sog4:'p_sog4'}};const FORM={{goal:'goal_l10',sog2:'hit2_l10',sog3:'hit3_l10',sog4:null}};
let market='goal',view='games';const manual=JSON.parse(localStorage.getItem('odds_{d}')||'{{}}');
function implied(o){{o=parseInt(String(o).replace('+',''));if(isNaN(o))return null;return o>0?100/(o+100):(-o)/(-o+100)}}
function fair(p){{return p<0.5?'+'+Math.round(100*(1-p)/p):'-'+Math.round(100*p/(1-p))}}
function am(o){{return o===''||o==null?'':(o>0?'+'+o:String(o))}}
function saCls(v){{return v>=30?'good':v<=26.5?'bad':''}}
function trend(r){{const d=r.sog_l5-r.sog_pg;return d>=0.6?'<span class="up">▲</span>':d<=-0.6?'<span class="dn">▼</span>':'<span class="fl">–</span>'}}
function prep(){{const k=MK[market];rows.forEach(r=>{{const key=r.pid+market;const o=manual[key]!==undefined&&manual[key]!==''?manual[key]:r['book_'+market];const ip=(o!==''&&o!=null)?implied(o):null;r._o=o;r._e=ip==null?null:(r[k]-ip)*100;r._p=r[k]}})}}
function head(){{return '<tr><th class="l">Player</th><th>Pos</th><th>TOI</th><th>SOG/g</th><th>L5</th><th></th><th>Form</th><th>sh%</th><th>PP</th><th>Opp SA</th><th>Model</th><th>Fair</th><th>Book</th><th>Edge</th></tr>'}}
function row(r){{const e=r._e;const bk=(manual[r.pid+market]?'you':(r['book_'+market+'_bk']||''));const f=FORM[market];const form=f?Math.round(r[f]*100)+'%':'';
 return `<tr><td class="l">${{r.name}} <span class="mut">${{r.team}}</span></td><td>${{r.pos}}</td><td>${{r.toi}}</td><td>${{r.sog_pg}}</td><td>${{r.sog_l5}}</td><td>${{trend(r)}}</td><td>${{form}}</td><td>${{(r.sh_pct*100).toFixed(1)}}</td><td>${{(r.pp_share*100).toFixed(0)}}%</td><td class="${{saCls(r.opp_sa)}}">${{r.opp_sa}}</td><td><b>${{(r._p*100).toFixed(1)}}%</b></td><td>${{fair(r._p)}}</td><td><input value="${{am(r._o)}}" data-k="${{r.pid+market}}" placeholder="—"> <span class="bk">${{bk}}</span></td><td class="${{e==null?'':e>=0?'edge-pos':'edge-neg'}}">${{e==null?'':(e>0?'+':'')+e.toFixed(1)}}</td></tr>`}}
function render(){{
 prep();const el=document.getElementById('board');
 if(view==='games'){{
  const games=Object.keys(G).sort((a,b)=>(G[a].start||'').localeCompare(G[b].start||''));
  el.innerHTML=games.map(g=>{{const [away,home]=g.split('@');const gr=rows.filter(r=>r.game===g);
   const side=t=>{{const rs=gr.filter(r=>r.team===t).sort((a,b)=>b._p-a._p).slice(0,9);const opp=t===home?away:home;const sa=rs[0]?rs[0].opp_sa:'';const sf=rs[0]?rs[0].team_sf:'';
     return `<div class="side"><div class="th"><b>${{t}}</b> <span class="mut">shots for ${{sf}}/g · vs ${{opp}} allows <span class="${{saCls(sa)}}">${{sa}}</span>/g</span></div><table><thead>${{head()}}</thead><tbody>${{rs.map(row).join('')}}</tbody></table></div>`}};
   return `<div class="game"><div class="gh">${{away}} @ ${{home}} <span class="mut">${{G[g].et}} ET</span></div><div class="sides">${{side(away)}}${{side(home)}}</div></div>`}}).join('');
 }} else {{
  const sorted=rows.slice().sort(view==='edge'?((a,b)=>(b._e==null?-999:b._e)-(a._e==null?-999:a._e)||b._p-a._p):((a,b)=>b._p-a._p));
  el.innerHTML=`<div class="wrap"><table id="t"><thead>${{head().replace('<th class="l">Player','<th class="l">#</th><th class="l">Player').replace('<th>Pos>','<th class="l">Game</th><th>Pos>')}}</thead><tbody>${{sorted.map((r,i)=>row(r).replace('<tr><td class="l">',`<tr><td class="l">${{i+1}}</td><td class="l">`).replace('</td><td>'+r.pos+'</td>',`</td><td class="l">${{r.game}} ${{r.et}}</td><td>${{r.pos}}</td>`)).join('')}}</tbody></table></div>`;
 }}
 document.querySelectorAll('#board input').forEach(x=>x.addEventListener('change',ev=>{{manual[ev.target.dataset.k]=ev.target.value;localStorage.setItem('odds_{d}',JSON.stringify(manual));render()}}));
}}
document.querySelectorAll('.tabs button[data-m]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button[data-m]').forEach(x=>x.classList.remove('on'));b.classList.add('on');market=b.dataset.m;render()}});
document.querySelectorAll('.tabs button[data-v]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button[data-v]').forEach(x=>x.classList.remove('on'));b.classList.add('on');view=b.dataset.v;render()}});
render();
</script></body></html>"""


if __name__ == "__main__":
    main()
