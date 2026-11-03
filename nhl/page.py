"""HTML for the board — same design system as sixpts (tokens, type, pills, tiers, cards)."""
import json
from datetime import datetime, timezone, timedelta

from .store import record, graded_rows

MARKETS = [("sog3", "3+ shots", "p_sog3"), ("sog2", "2+ shots", "p_sog2"),
           ("sog4", "4+ shots", "p_sog4"), ("goal", "Anytime goal", "p_goal")]

CSS = """
:root{--ink:#070A0F;--surface:#0D131C;--raise:#131C28;--raise-2:#1A2431;--line:#1E2836;--line-strong:#2B3949;
--paint:#EEF2F6;--dim:#8794A5;--faint:#7A8799;--bulb:#FFB020;--bulb-hi:#FFC247;--bulb-dim:rgba(255,176,32,.14);--on-bulb:#0A0D12;
--gain:#35C77F;--gain-dim:rgba(53,199,127,.14);--loss:#F2555A;--loss-dim:rgba(242,85,90,.13);--warn:#FFB020;--warn-dim:rgba(255,176,32,.14);
--display:Archivo,Inter,-apple-system,sans-serif;--text:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;--wide:"wdth" 118;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--r-sm:3px;--r:6px;--quick:120ms;--settle:260ms;--ease:cubic-bezier(.2,.8,.25,1)}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){:root{--quick:0ms;--settle:0ms}}
*{box-sizing:border-box;scrollbar-color:var(--line-strong) transparent;scrollbar-width:thin}
html,body{margin:0;background:var(--ink);color:var(--paint);font:14px/1.45 var(--text);-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
button,input{font:inherit;color:inherit} a{color:inherit}
h1,h2,.wordmark,.p,.tier,.big{font-family:var(--display);font-variation-settings:var(--wide)}
.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:var(--s4);padding:0 var(--s4);height:54px}
.wordmark{font-weight:700;letter-spacing:-.02em;font-size:18px;display:flex;align-items:center;gap:9px;text-decoration:none}
.wordmark i{width:8px;height:16px;border-radius:1px;background:var(--bulb);display:inline-block}
.top .date{color:var(--dim)} .top .right{margin-left:auto;color:var(--faint);font-size:12px}
.wrap{max-width:1240px;margin:0 auto;padding:var(--s4) var(--s4) 80px}
h1{font-size:21px;font-weight:700;letter-spacing:-.01em;margin:0} h2{font-size:16px;font-weight:700;margin:0}
h3{font-size:12px;font-weight:600;color:var(--faint);letter-spacing:.04em;margin:0 0 7px;text-transform:uppercase}
.muted{color:var(--faint)} .dim{color:var(--dim)} .pos{color:var(--gain)} .neg{color:var(--loss)}
.bar{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;margin:var(--s3) 0}
.seg{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:2px}
.seg button{border:0;background:transparent;color:var(--dim);padding:6px 11px;border-radius:var(--r-sm);cursor:pointer;font-weight:500;transition:background var(--quick) var(--ease),color var(--quick) var(--ease)}
.seg button:hover{color:var(--paint)} .seg button.on{background:var(--raise-2);color:var(--paint)}
input[type=search]{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:7px 9px;color:var(--paint);min-width:180px} input[type=search]:focus{border-color:var(--bulb);outline:none}
.games{display:flex;gap:var(--s2);overflow-x:auto;padding-bottom:var(--s2)}
.game{flex:0 0 auto;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:9px 11px;cursor:pointer;min-width:122px;text-align:left;color:inherit;transition:border-color var(--quick) var(--ease)}
.game:hover{border-color:var(--line-strong)} .game.on{border-color:var(--bulb)}
.game b{display:block;font-size:13px;font-family:var(--display);font-variation-settings:var(--wide)} .game small{color:var(--faint)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);margin-bottom:var(--s3);overflow:hidden}
.panel>.head{display:flex;align-items:center;gap:var(--s2);padding:11px 15px} .panel>.body{padding:0 15px 13px;border-top:1px solid var(--line)}
.pick-row{display:grid;grid-template-columns:66px 1fr auto;gap:var(--s3);align-items:start;padding:11px 0;border-bottom:1px solid var(--line)} .pick-row:last-child{border-bottom:0}
.tier{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:4px 0;text-align:center;border-radius:var(--r-sm);min-width:54px;display:inline-block}
.tier.bet{background:var(--bulb);color:var(--on-bulb)} .tier.lean{background:var(--bulb-dim);color:var(--bulb)} .tier.pass{background:var(--raise-2);color:var(--faint)} .tier.out{background:var(--loss-dim);color:var(--loss)}
.pick-row .who{font-weight:600} .pick-row .why{color:var(--dim);margin-top:3px}
.sig{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px} .sig span{font-size:11px;padding:2px 7px;border-radius:var(--r-sm);background:var(--raise);color:var(--faint)}
.sig span.ok{color:var(--gain);background:var(--gain-dim)} .sig span.no{color:var(--loss);background:var(--loss-dim)}
.pick-row .price{text-align:right} .pick-row .price b{font-size:17px;font-family:var(--display)}
.tablewrap{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);overflow:auto}
table{border-collapse:collapse;width:100%}
th{position:sticky;top:0;z-index:3;background:var(--surface);font-size:11px;font-weight:600;letter-spacing:.04em;color:var(--faint);text-align:right;padding:10px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none;text-transform:uppercase}
th.l,td.l{text-align:left} th.sorted{color:var(--paint)} th.sorted::after{content:" ↓";color:var(--bulb)}
td{padding:10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr.row{cursor:pointer;transition:background var(--quick) var(--ease)} tr.row:hover td,tr.row.open td{background:var(--raise)}
tbody tr.row:nth-child(-n+14){animation:rise var(--settle) var(--ease) backwards}
.player{font-weight:600} .player small{color:var(--faint);font-weight:400;margin-left:6px}
.tag{font-size:10px;padding:1px 5px;border-radius:var(--r-sm);background:var(--raise-2);color:var(--faint);margin-left:6px;vertical-align:middle;text-transform:uppercase;letter-spacing:.04em}
.tag.out{background:var(--loss-dim);color:var(--loss)} .tag.q{background:var(--warn-dim);color:var(--warn)} .tag.in{background:var(--gain-dim);color:var(--gain)}
tr.dim td{opacity:.4}
.p{display:inline-block;min-width:54px;text-align:center;padding:3px 8px;border-radius:var(--r-sm);font-weight:700;font-size:15px}
.h1{background:var(--raise-2);color:var(--dim)} .h2{background:var(--raise-2);color:var(--paint)} .h3{background:var(--bulb-dim);color:var(--bulb)} .h4{background:var(--bulb-dim);color:var(--bulb)} .h5{background:var(--bulb);color:var(--on-bulb)}
.edge{font-weight:600} .edge.pos{color:var(--gain)} .edge.neg{color:var(--loss)}
.match{font-size:11px;padding:2px 7px;border-radius:var(--r-sm);background:var(--raise-2);color:var(--faint);font-weight:700}
.match.fav{color:var(--gain);background:var(--gain-dim)} .match.unfav{color:var(--loss);background:var(--loss-dim)}
.odds{width:70px;text-align:right;background:var(--raise);border:1px solid var(--line);border-radius:var(--r-sm);padding:4px 6px;color:var(--paint)} .odds:focus{border-color:var(--bulb);outline:none}
.book{font-size:10px;color:var(--faint);margin-left:4px;letter-spacing:.03em}
.up{color:var(--gain)} .dn{color:var(--loss)} .fl{color:var(--faint)}
.detail td{background:var(--raise);white-space:normal;text-align:left;padding:14px 15px}
.verdict{font-weight:600;font-size:15px;margin-bottom:9px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(224px,1fr));gap:var(--s3)}
.block{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:11px 13px}
.stat{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px;flex-wrap:wrap} .stat:last-child{border-bottom:0}
.stat-l{color:var(--faint)} .stat-v{font-weight:600;font-variant-numeric:tabular-nums}
.two{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3)}
.team-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:13px 15px;animation:rise var(--settle) var(--ease)}
.team-card h2{display:flex;align-items:baseline;gap:8px;margin-bottom:6px} .team-card table{min-width:0} .team-card td,.team-card th{padding:7px 4px;font-size:13px}
.gh{display:flex;align-items:baseline;gap:10px;margin:18px 0 8px}
.rec{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--s3)}
.rec .block .big{font-size:24px;font-weight:700} .rec .block .lbl{color:var(--faint);font-size:12px}
.howto p{margin:9px 0;color:var(--dim);max-width:78ch}
.cards{display:none;flex-direction:column;gap:var(--s2)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:13px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.card-num{text-align:right} .card-num .p{font-size:20px}
.card-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:11px;color:var(--dim);font-size:13px}
.sources{font-size:12px;color:var(--faint);padding:14px 0 0}
@media(max-width:860px){.two{grid-template-columns:1fr}.tablewrap{display:none}.cards{display:flex}.top .right{display:none}}
:focus-visible{outline:2px solid var(--bulb);outline-offset:2px} ::selection{background:var(--bulb);color:var(--on-bulb)} input{caret-color:var(--bulb)}
"""


def _et(iso):
    try:
        return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(hours=5)).strftime("%-I:%M %p")
    except Exception:
        return ""


def _record_html():
    rec_rows, tot = record()
    if not tot:
        return ("<div class='panel'><div class='head'><h2>Record</h2></div><div class='body'><p class='dim' style='margin:10px 0 0'>"
                "No graded picks yet. Picks are logged automatically on the evening run when the model beats the best book price, "
                "and graded the next morning. Every pick stays — wins, losses and voids.</p></div></div>")
    n, h, pnl, st = tot
    blocks = f"""<div class='rec'>
<div class='block'><div class='big'>{h}-{n-h}</div><div class='lbl'>record · {h/n:.0%}</div></div>
<div class='block'><div class='big {'pos' if pnl>=0 else 'neg'}'>{pnl:+.1f}u</div><div class='lbl'>P&amp;L · ROI {pnl/st:+.0%}</div></div>"""
    for m, mn, mh, mp, ms, amp, abp in rec_rows:
        blocks += f"<div class='block'><div class='big'>{mh}-{mn-mh}</div><div class='lbl'>{m} · model {amp:.0%} vs book {abp:.0%}</div></div>"
    blocks += "</div>"
    recent = graded_rows()[-12:][::-1]
    tbl = "<table style='margin-top:12px'><thead><tr><th class='l'>Date</th><th class='l'>Pick</th><th>Price</th><th>Model</th><th>Book</th><th>Result</th></tr></thead><tbody>"
    for r in recent:
        res = "void" if (r["result"] == "0" and float(r["pnl"]) == 0) else ("hit" if r["result"] == "1" else "miss")
        tbl += (f"<tr><td class='l muted'>{r['date'][5:]}</td><td class='l'><span class='player'>{r['name']}</span> <small>{r['market']} o{r['line']}</small></td>"
                f"<td>{int(float(r['odds'])):+d}</td><td>{float(r['model_p']):.0%}</td><td>{float(r['book_p']):.0%}</td>"
                f"<td class='{'pos' if res=='hit' else 'neg' if res=='miss' else 'muted'}'>{res} {float(r['pnl']):+.2f}</td></tr>")
    tbl += "</tbody></table>"
    return f"<div class='panel'><div class='head'><h2>Record</h2><span class='muted'>every pick, including losses</span></div><div class='body'>{blocks}{tbl}</div></div>"


def _picks_html(todays_picks, odds_meta, rows_by_pid):
    if todays_picks:
        body = ""
        for r in todays_picks:
            mp, bp = float(r["model_p"]), float(r["book_p"]); e = (mp - bp) * 100
            tier = "bet" if e >= 8 else "lean"
            b = rows_by_pid.get(int(r["pid"]), {})
            sig = []
            if b:
                sig.append(f"<span class='{'ok' if b.get('status')=='IN' else 'no' if b.get('status') in ('OUT','?') else ''}'>{b.get('status') or 'played last'}</span>")
                sig.append(f"<span>{b['sog_pg']} SOG/g</span><span>L5 {b['sog_l5']}</span><span>{b['toi']} min</span>")
                g = "A" if b["opp_sa"] >= 29 else "B" if b["opp_sa"] >= 27 else "C"
                sig.append(f"<span class='{'ok' if g=='A' else 'no' if g=='C' else ''}'>matchup {g}</span>")
            body += (f"<div class='pick-row'><span class='tier {tier}'>{tier}</span><div><div class='who'>{r['name']} <span class='muted'>{r['team']} vs {r['opp']}</span> · {r['market']} over {r['line']}</div>"
                     f"<div class='why'>model {mp:.0%} vs book {bp:.0%} · edge <b class='pos'>+{e:.1f}</b> · {r.get('note','')}</div><div class='sig'>{''.join(sig)}</div></div>"
                     f"<div class='price'><b>{int(float(r['odds'])):+d}</b></div></div>")
        return f"<div class='panel'><div class='head'><h2>Model picks</h2><span class='muted'>edge ≥ +4 shots / +6 goals, best book price</span></div><div class='body'>{body}</div></div>"
    msg = "No row cleared the edge bar today." if odds_meta else "Book prices come on the afternoon run; model picks appear here once they do."
    return f"<div class='panel'><div class='head'><h2>Model picks</h2></div><div class='body'><p class='dim' style='margin:10px 0 0'>{msg}</p></div></div>"


def _parlays_html(out_dir, rows_by_pid):
    import os
    from .parlays import why, record as parlay_record
    path = os.path.join(out_dir, "parlays.json")
    if not os.path.exists(path):
        return ""
    try:
        tickets = json.load(open(path))
    except Exception:
        return ""
    if not tickets:
        return ""
    NAMES = {"core": "Core · 3 shots legs", "stack": "Team stack · 2+ shots", "mix": "Pace mix · one game",
             "goals4": "Longshot · 4 goal scorers", "goals6": "Longshot · 6 goal scorers", "ladder4": "Longshot · 4+ shots ladder", "pace6": "Longshot · pace stack"}
    MK = {"goal": "ATG", "sog2": "2+ SOG", "sog3": "3+ SOG", "sog4": "4+ SOG"}
    body = ""
    for t in tickets:
        fp = float(t["fair_p"]); bo = t.get("book_odds"); bp = t.get("book_p")
        long = fp < 0.05
        tier = "lean" if long else "bet"
        price = f"<b>{bo:+d}</b><div class='muted'>fair {t['fair_odds']}</div>" if bo is not None else f"<b>{t['fair_odds']}</b><div class='muted'>fair · no book</div>"
        overlay = f" · book pays <span class='pos'>{fp/float(bp):.1f}×</span> fair" if bo is not None and bp else ""
        legs = "".join(f"<div class='stat'><span class='stat-l'><b style='color:var(--paint)'>{l['name']}</b> <span class='muted'>{l['team']}</span> {MK[l['market']]}"
                       f"{(' @ %+d' % l['book']) if l.get('book') is not None else ''}</span><span class='stat-v'>{float(l['p']):.0%} <span class='muted' style='font-weight:400'>{why(l, rows_by_pid)}</span></span></div>" for l in t["legs"])
        body += (f"<div class='pick-row'><span class='tier {tier}'>{'long' if long else 'play'}</span><div><div class='who'>{NAMES.get(t['kind'], t['kind'])}</div>"
                 f"<div class='why'>{len(t['legs'])} legs · model {fp:.2%} to hit{overlay}</div><div style='margin-top:8px'>{legs}</div></div><div class='price'>{price}</div></div>")
    pr = parlay_record()
    rec = f"<span class='muted'>{pr['total'][1]}/{pr['total'][0]} hit · {pr['total'][2]:+.1f}u</span>" if pr else "<span class='muted'>built from the board each evening, graded next morning</span>"
    return f"<div class='panel'><div class='head'><h2>Parlays</h2>{rec}</div><div class='body'>{body}</div></div>"


def render(rows, games, d, odds_meta, todays_picks, out_dir="docs"):
    games_sorted = sorted(games, key=lambda g: g.get("start") or "")
    gmeta = {f"{g['away']}@{g['home']}": dict(start=g.get("start") or "", et=_et(g.get("start") or "")) for g in games}
    for r in rows:
        r["et"] = gmeta.get(r["game"], {}).get("et", "")
    n_in = sum(1 for r in rows if r.get("status") == "IN"); n_out = sum(1 for r in rows if r.get("status") == "OUT"); n_q = sum(1 for r in rows if r.get("status") == "?")
    lineup = f"lineups posted: {n_in} in, {n_out} out" if n_in else f"lineups not posted · {n_q} flagged"
    stamp = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%b %-d, %-I:%M %p ET")
    credits = f" · {odds_meta.get('credits_remaining')} API credits" if odds_meta and odds_meta.get("credits_remaining") else ""
    strip = "".join(f"<button class='game' data-g='{g['away']}@{g['home']}'><b>{g['away']} @ {g['home']}</b><small>{_et(g.get('start') or '')} ET</small></button>" for g in games_sorted)
    seg_m = "".join(f"<button {'class=on' if i==0 else ''} data-m='{m}'>{lbl}</button>" for i, (m, lbl, _) in enumerate(MARKETS))
    by_pid = {r["pid"]: r for r in rows}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>the-ice · NHL props · {d}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<div class="top"><a class="wordmark" href="./"><i></i>the-ice</a><span class="date">{d.strftime('%a %b %-d')}</span><span class="right">{lineup} · built {stamp}{credits}</span></div>
<div class="wrap">
{_record_html()}
{_picks_html(todays_picks, odds_meta, by_pid)}
{_parlays_html(out_dir, by_pid)}
<div class="gh"><h2>Board</h2><span class="muted">{len(games)} games · {len(rows)} players</span></div>
<div class="games" id="strip"><button class="game on" data-g=""><b>All games</b><small>{len(games)} tonight</small></button>{strip}</div>
<div class="bar"><div class="seg" id="mseg">{seg_m}</div><div class="seg" id="vseg"><button class="on" data-v="edge">By edge</button><button data-v="model">By model</button><button data-v="games">By game</button></div><input type="search" id="q" placeholder="Search player"></div>
<div id="board"></div>
<div class="panel howto" style="margin-top:18px"><div class="head"><h2>How to read it</h2></div><div class="body">
<p><b>Edge</b> is the only column that says bet or don't: model probability minus what the book's price implies. Bar is +4 on shot lines, +6 on anytime goal. Negative edge means the book likes him more than the model does — pass, however good the player.</p>
<p><b>3+ shots</b> is the main market: calibrated within 2 points in every bucket over 5,000+ graded rows. 2+ is a coin flip books price well. Anytime goal only pays in the +250 to +450 range.</p>
<p><b>Matchup</b> grades the opponent's shots allowed: A = 29+ (3+ SOG/g forwards hit 3+ shots 70% in October), B = 27–29 (54%), C = under 27 (52%). The model already includes it.</p>
<p><b>Status</b>: <span class="tag in">in</span> confirmed in the posted lineup · <span class="tag out">out</span> not in it · <span class="tag q">?</span> didn't dress the team's last game and lineups aren't up yet. Neither out nor ? is ever auto-picked.</p>
<p>Type a book price into any row to see your own edge. Prices you type stay in this browser.</p></div></div>
<div class="sources">Data: NHL API (boxscores, rosters, lineups) · The Odds API (prices) · model fit on 2024-25, tested on 2025-26 · <a href="https://github.com/jamesjholee/the-ice">source</a></div>
</div>
<script>
const rows={json.dumps(rows)};const G={json.dumps(gmeta)};const MK={{goal:'p_goal',sog2:'p_sog2',sog3:'p_sog3',sog4:'p_sog4'}};const FORM={{goal:'goal_l10',sog2:'hit2_l10',sog3:'hit3_l10',sog4:null}};const BAR={{goal:6,sog2:5,sog3:4,sog4:4}};
let market='sog3',view='edge',game='',q='',open=null;const manual=JSON.parse(localStorage.getItem('odds_{d}')||'{{}}');
const implied=o=>{{o=parseInt(String(o).replace('+',''));if(isNaN(o))return null;return o>0?100/(o+100):(-o)/(-o+100)}};
const fair=p=>p<0.5?'+'+Math.round(100*(1-p)/p):'-'+Math.round(100*p/(1-p));
const am=o=>(o===''||o==null)?'':(o>0?'+'+o:String(o));
const tierCls=p=>p>=.6?'h5':p>=.45?'h4':p>=.33?'h3':p>=.2?'h2':'h1';
const grade=v=>v>=29?'A':v>=27?'B':'C';
const trend=r=>{{const dd=r.sog_l5-r.sog_pg;return dd>=0.6?'<span class="up">▲</span>':dd<=-0.6?'<span class="dn">▼</span>':'<span class="fl">–</span>'}};
const statusTag=r=>r.status==='OUT'?'<span class="tag out">out</span>':r.status==='?'?'<span class="tag q">?</span>':r.status==='IN'?'<span class="tag in">in</span>':'';
const verdict=r=>{{if(r.status==='OUT')return['out','Not in the lineup'];if(r.status==='?')return['out','Didn\\'t dress last game — wait for the lineup'];if(r._e==null)return['pass','No price yet'];if(r._e>=BAR[market]+4)return['bet',`Model beats the book by ${{r._e.toFixed(1)}} pts`];if(r._e>=BAR[market])return['lean',`Edge +${{r._e.toFixed(1)}}, just over the bar`];if(r._e>=0)return['pass','Fairly priced — no edge'];return['pass','Book likes him more than the model does']}};
function prep(){{const k=MK[market];rows.forEach(r=>{{const key=r.pid+market;const o=manual[key]!==undefined&&manual[key]!==''?manual[key]:r['book_'+market];const ip=(o!==''&&o!=null)?implied(o):null;r._o=o;r._p=r[k];r._e=ip==null?null:(r._p-ip)*100;r._bk=manual[key]?'you':(r['book_'+market+'_bk']||'')}})}}
function filt(){{return rows.filter(r=>(!game||r.game===game)&&(!q||r.name.toLowerCase().includes(q)))}}
function sorter(a,b){{if(view==='edge')return((b._e==null?-999:b._e)-(a._e==null?-999:a._e))||(b._p-a._p);return b._p-a._p}}
const head=()=>`<thead><tr><th class="l">Player</th><th class="l">Game</th><th>TOI</th><th>SOG/G</th><th>L5</th><th>Form</th><th>Matchup</th><th>Model</th><th>Fair</th><th>Book</th><th>Edge</th></tr></thead>`;
function row(r,i){{const f=FORM[market];const form=f?Math.round(r[f]*100)+'%':'—';const g=grade(r.opp_sa);const e=r._e;
 return `<tr class="row ${{open===r.pid?'open':''}} ${{r.status==='OUT'?'dim':''}}" data-pid="${{r.pid}}"><td class="l"><span class="player">${{r.name}}<small>${{r.team}} ${{r.pos}}</small></span>${{statusTag(r)}}</td><td class="l muted">${{r.game}} ${{r.et}}</td><td>${{r.toi}}</td><td>${{r.sog_pg}}</td><td>${{r.sog_l5}} ${{trend(r)}}</td><td>${{form}}</td><td><span class="match ${{g==='A'?'fav':g==='C'?'unfav':''}}">${{g}} ${{r.opp_sa}}</span></td><td><span class="p ${{tierCls(r._p)}}">${{Math.round(r._p*100)}}%</span></td><td class="muted">${{fair(r._p)}}</td><td><input class="odds" value="${{am(r._o)}}" data-k="${{r.pid+market}}" placeholder="—"><span class="book">${{r._bk}}</span></td><td class="edge ${{e==null?'':e>=0?'pos':'neg'}}">${{e==null?'—':(e>0?'+':'')+e.toFixed(1)}}</td></tr>`+(open===r.pid?detail(r):'')}}
function detail(r){{const [t,why]=verdict(r);const g=grade(r.opp_sa);
 return `<tr class="detail"><td colspan="11"><div class="verdict"><span class="tier ${{t}}">${{t}}</span> &nbsp;${{why}}</div><div class="grid">
 <div class="block"><h3>Volume</h3><div class="stat"><span class="stat-l">Shots/game, last 20</span><span class="stat-v">${{r.sog_pg}}</span></div><div class="stat"><span class="stat-l">Last 5</span><span class="stat-v">${{r.sog_l5}} ${{trend(r)}}</span></div><div class="stat"><span class="stat-l">Last 10</span><span class="stat-v">${{r.sog_l10}}</span></div><div class="stat"><span class="stat-l">Ice time</span><span class="stat-v">${{r.toi}} min (L5 ${{r.toi_l5}})</span></div><div class="stat"><span class="stat-l">PP share</span><span class="stat-v">${{Math.round(r.pp_share*100)}}%</span></div></div>
 <div class="block"><h3>Form, last 10</h3><div class="stat"><span class="stat-l">2+ shots</span><span class="stat-v">${{Math.round(r.hit2_l10*100)}}%</span></div><div class="stat"><span class="stat-l">3+ shots</span><span class="stat-v">${{Math.round(r.hit3_l10*100)}}%</span></div><div class="stat"><span class="stat-l">Scored</span><span class="stat-v">${{Math.round(r.goal_l10*100)}}%</span></div><div class="stat"><span class="stat-l">Goals, last 5</span><span class="stat-v">${{r.goals_l5}}</span></div><div class="stat"><span class="stat-l">Shooting %</span><span class="stat-v">${{(r.sh_pct*100).toFixed(1)}}</span></div></div>
 <div class="block"><h3>Matchup</h3><div class="stat"><span class="stat-l">${{r.opp}} shots allowed/g</span><span class="stat-v"><span class="match ${{g==='A'?'fav':g==='C'?'unfav':''}}">${{g}}</span> ${{r.opp_sa}}</span></div><div class="stat"><span class="stat-l">${{r.team}} shots for/g</span><span class="stat-v">${{r.team_sf}}</span></div><div class="stat"><span class="stat-l">Projected goalie</span><span class="stat-v">${{r.opp_goalie}} ${{r.opp_gsv}}</span></div><div class="stat"><span class="stat-l">Lineup</span><span class="stat-v">${{r.status||'played last game'}}</span></div></div>
 <div class="block"><h3>All markets</h3>${{['sog2','sog3','sog4','goal'].map(m=>{{const p=r[MK[m]];const o=manual[r.pid+m]||r['book_'+m];const ip=o?implied(o):null;return `<div class="stat"><span class="stat-l">${{ {{sog2:'2+ shots',sog3:'3+ shots',sog4:'4+ shots',goal:'Anytime goal'}}[m] }}</span><span class="stat-v">${{Math.round(p*100)}}% <span class="muted">${{fair(p)}}</span>${{ip!=null?` <span class="edge ${{p-ip>=0?'pos':'neg'}}">${{((p-ip)*100>0?'+':'')+((p-ip)*100).toFixed(1)}}</span>`:''}}</span></div>`}}).join('')}}</div></div></td></tr>`}}
function card(r){{const [t,why]=verdict(r);const g=grade(r.opp_sa);const e=r._e;return `<div class="card"><div class="card-head"><div><div class="player">${{r.name}}<small>${{r.team}} ${{r.pos}} · ${{r.game}} ${{r.et}}</small></div><div class="muted" style="margin-top:3px">${{statusTag(r)}} <span class="tier ${{t}}">${{t}}</span> ${{why}}</div></div><div class="card-num"><span class="p ${{tierCls(r._p)}}">${{Math.round(r._p*100)}}%</span><div class="muted">${{fair(r._p)}}</div></div></div><div class="card-row"><span>${{r.sog_pg}} SOG/g</span><span>L5 ${{r.sog_l5}} ${{trend(r)}}</span><span>${{r.toi}} min</span><span class="match ${{g==='A'?'fav':g==='C'?'unfav':''}}">${{g}} ${{r.opp_sa}}</span><span style="margin-left:auto"><input class="odds" value="${{am(r._o)}}" data-k="${{r.pid+market}}" placeholder="price"> <b class="edge ${{e==null?'':e>=0?'pos':'neg'}}">${{e==null?'':(e>0?'+':'')+e.toFixed(1)}}</b></span></div></div>`}}
function render(){{prep();const el=document.getElementById('board');const rs=filt().sort(sorter);
 if(view==='games'){{const gs=Object.keys(G).filter(g=>!game||g===game).sort((a,b)=>(G[a].start||'').localeCompare(G[b].start||''));
  el.innerHTML=gs.map(g=>{{const [away,home]=g.split('@');const side=t=>{{const x=rs.filter(r=>r.team===t).slice(0,9);const o=t===home?away:home;const sa=x[0]?x[0].opp_sa:'';const gg=sa?grade(sa):'';return `<div class="team-card"><h2>${{t}}<span class="muted" style="font-size:12px;font-weight:400">vs ${{o}} · allows <span class="match ${{gg==='A'?'fav':gg==='C'?'unfav':''}}">${{gg}} ${{sa}}</span>/g</span></h2><table>${{head()}}<tbody>${{x.map(row).join('')}}</tbody></table></div>`}};
   return `<div class="gh"><h2>${{away}} @ ${{home}}</h2><span class="muted">${{G[g].et}} ET</span></div><div class="two">${{side(away)}}${{side(home)}}</div>`}}).join('');
 }}else{{el.innerHTML=`<div class="tablewrap"><table>${{head()}}<tbody>${{rs.map(row).join('')}}</tbody></table></div><div class="cards">${{rs.slice(0,60).map(card).join('')}}</div>`}}
 el.querySelectorAll('tr.row').forEach(tr=>tr.addEventListener('click',ev=>{{if(ev.target.tagName==='INPUT')return;const p=+tr.dataset.pid;open=open===p?null:p;render()}}));
 el.querySelectorAll('input.odds').forEach(x=>x.addEventListener('change',ev=>{{manual[ev.target.dataset.k]=ev.target.value;localStorage.setItem('odds_{d}',JSON.stringify(manual));render()}}));
}}
document.querySelectorAll('#mseg button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('#mseg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');market=b.dataset.m;render()}});
document.querySelectorAll('#vseg button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('#vseg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');view=b.dataset.v;render()}});
document.querySelectorAll('#strip .game').forEach(b=>b.onclick=()=>{{document.querySelectorAll('#strip .game').forEach(x=>x.classList.remove('on'));b.classList.add('on');game=b.dataset.g;render()}});
document.getElementById('q').addEventListener('input',e=>{{q=e.target.value.toLowerCase();render()}});
render();
</script></body></html>"""
