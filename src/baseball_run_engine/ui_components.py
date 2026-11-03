"""OOTP-inspired presentation helpers. Names are escaped before HTML rendering."""
from html import escape
from .events import Event

def batting_line(h):
    p=h.probabilities
    hits=sum(p[int(e)] for e in (Event.SINGLE,Event.DOUBLE,Event.TRIPLE,Event.HR))
    free=p[Event.BB]+p[Event.HBP]
    ab=max(1e-12,1-free)
    bases=p[Event.SINGLE]+2*p[Event.DOUBLE]+3*p[Event.TRIPLE]+4*p[Event.HR]
    return {"AVG":hits/ab,"OBP":hits+free,"SLG":bases/ab,"HR%":100*p[Event.HR]}

def lineup_card(lineup):
    if len(lineup)!=9: raise ValueError("Nine players required")
    header='<section class="ootp-panel"><div class="panel-heading"><div><span class="kicker">PROJECTED NINE / OFFENSE</span><h2>Batting order</h2></div><span class="stamp">LINEUP CARD<br>01–09</span></div><div class="lineup-head"><span>NO.</span><span>BATTER / POSITION</span><span>AVG*</span><span>OBP*</span><span>SLG*</span><span>HR%</span></div>'
    rows=[]
    for n,h in enumerate(lineup,1):
        stats=batting_line(h)
        initial="".join(x[:1] for x in h.name.split()[:2]).upper()
        positions=", ".join(h.positions[:2]) or "UTIL"
        rows.append(f'<div class="lineup-row"><span class="number">{n:02d}</span><div class="player"><span class="monogram">{escape(initial)}</span><span class="identity"><b>{escape(h.name)}</b><small>{escape(positions)}</small></span></div><span class="stat">{stats["AVG"]:.3f}</span><span class="stat gold">{stats["OBP"]:.3f}</span><span class="stat">{stats["SLG"]:.3f}</span><span class="stat">{stats["HR%"]:.1f}</span></div>')
    return header+"".join(rows)+'<div class="footnote">* Approximate projected batting rates from simplified PA outcome categories. Not official ZiPS/Steamer AVG, OBP, SLG.</div></section>'

def masthead():
    return '<div class="masthead"><div><div class="kicker">BASEBALL OPERATIONS / RESEARCH</div><div class="brand">LINEUP <em>LAB</em></div><div class="subtitle">Run production · batting order · constrained roster construction</div></div><div class="engine">MARKOV ENGINE<strong>216 STATES</strong></div></div>'

def field_diagram():
    return """<div class="field-panel"><span class="kicker">BASE / OUT ENGINE</span>
    <svg viewBox="0 0 310 232" role="img" aria-label="Schematic baseball diamond" style="width:100%;max-height:250px">
    <defs><linearGradient id="turf" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#1a4d45"/><stop offset="1" stop-color="#0d2b34"/></linearGradient></defs>
    <path d="M155 15 L300 164 Q155 239 10 164 Z" fill="url(#turf)" stroke="#47776f" stroke-width="1.5"/>
    <path d="M155 66 L242 151 L155 221 L68 151 Z" fill="none" stroke="#d4bd84" stroke-width="2"/>
    <path d="M155 92 L217 151 L155 212 L93 151 Z" fill="#244437" stroke="#d4bd84" stroke-opacity=".7"/>
    <circle cx="155" cy="155" r="7" fill="#c9af72"/>
    <rect x="149" y="86" width="12" height="12" transform="rotate(45 155 92)" fill="#eadfc5"/>
    <rect x="211" y="145" width="12" height="12" transform="rotate(45 217 151)" fill="#eadfc5"/>
    <rect x="87" y="145" width="12" height="12" transform="rotate(45 93 151)" fill="#eadfc5"/>
    <path d="M148 213 L162 213 L155 223 Z" fill="#eadfc5"/>
    <g font-size="11" fill="#d7e7e3" text-anchor="middle"><text x="155" y="75">2B</text><text x="239" y="132">1B</text><text x="72" y="132">3B</text></g>
    </svg><div class="field-foot"><span>24 BASE-OUT STATES</span><span>9 LINEUP POSITIONS</span></div></div>"""

def run_metric(value,note="Lineup-conditioned, nine offensive innings"):
    return f'<div class="run-metric"><span class="kicker">EXPECTED RUNS / GAME</span><strong>{escape(str(value))}</strong><small>{escape(note)}</small></div>'

THEME = """
<style>
:root {--bg:#091522;--panel:#14283c;--line:#33495d;--gold:#e3c787;--text:#edf1ec;--muted:#a5b4c5;}
html,body,[data-testid="stAppViewContainer"] {background:var(--bg)!important;color:var(--text)}
[data-testid="stHeader"] {background:var(--bg)}
[data-testid="stSidebar"] {background:#102033!important;border-right:1px solid #31475b}
.block-container {max-width:1500px;padding-top:1.2rem}
.kicker {font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.13em;color:#d5bb84;font-weight:750}
.masthead {display:flex;justify-content:space-between;gap:24px;align-items:center;border-bottom:1px solid var(--line);padding:10px 0 22px;margin-bottom:20px}
.brand {font-size:clamp(28px,4.2vw,52px);font-weight:900;letter-spacing:-.05em;line-height:1.15}
.brand em {font-style:normal;color:var(--gold)}
.subtitle {font-size:13px;color:var(--muted)}
.engine {border:1px solid #52657a;padding:12px 18px;letter-spacing:.1em;font-size:10px;text-align:center;white-space:nowrap}
.engine strong {display:block;color:var(--gold);font-size:18px;margin-top:5px}
.ootp-panel {background:linear-gradient(150deg,#1b3045,#111f30);border:1px solid var(--line);border-radius:9px;overflow:hidden}
.panel-heading {display:flex;justify-content:space-between;align-items:center;padding:18px 22px;background:#23374b;border-bottom:2px solid #b69a66}
.panel-heading h2 {font-size:26px;margin:2px 0 0;color:#f3f0e9;font-weight:800}
.stamp {text-align:right;color:#bcaf97;font-size:11px;font-weight:700;letter-spacing:.1em}
.lineup-head,.lineup-row {display:grid;grid-template-columns:40px minmax(150px,1fr) 54px 54px 54px 47px;gap:8px;align-items:center;padding:0 18px}
.lineup-head {height:36px;background:#102032;color:#a2b7c8;font:700 10px ui-monospace,monospace}
.lineup-row {min-height:66px;border-bottom:1px solid #32465b}
.lineup-row:nth-child(even) {background:#1a2d40}
.number {font:800 22px ui-monospace,monospace;color:var(--gold)}
.player {display:flex;align-items:center;gap:11px;min-width:0}
.monogram {display:flex;align-items:center;justify-content:center;flex:0 0 35px;height:35px;background:#2d4559;border:1px solid #587080;border-radius:6px;font-size:12px;font-weight:800;color:#f6e5be}
.identity {display:flex;flex-direction:column;min-width:0}
.identity b {font-size:14px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:#f1f3f1}
.identity small {font:600 10px ui-monospace,monospace;color:#97b0be;margin-top:4px}
.stat {font:700 12px ui-monospace,monospace;text-align:right;color:#e6ecf0}
.gold {color:var(--gold)}
.footnote {font-size:10px;color:#a4b2c0;padding:13px 18px}
.field-panel,.run-metric {background:linear-gradient(135deg,#192f42,#101f30);padding:19px;border:1px solid var(--line);border-radius:8px;margin-bottom:12px}
.field-foot {display:flex;justify-content:space-between;font-size:10px;letter-spacing:.05em;color:#a1b8ba}
.run-metric strong {display:block;font-size:42px;color:var(--gold);line-height:1.15;margin-top:5px}
.run-metric small {display:block;font-size:11px;color:var(--muted);margin-top:5px}
@media(max-width:750px){.masthead{flex-direction:column;align-items:flex-start}.lineup-head,.lineup-row{grid-template-columns:30px minmax(102px,1fr) 43px 43px 43px;padding:0 9px;gap:4px}.lineup-head span:last-child,.lineup-row .stat:last-child{display:none}.monogram{display:none}.identity b{font-size:12px}.stat{font-size:11px}}
</style>
"""
