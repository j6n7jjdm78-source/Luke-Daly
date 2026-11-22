"""Weekly leaderboard picture. Usage: python3 bot/leaderboard.py rows.json total_calls out.png
rows.json: [["SYM", 12.3, false], ...] (symbol, multiple, is_early)"""
import sys, os, json, subprocess, tempfile, html
rows, total, out = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bg = os.path.join(ROOT, "assets", "pfp_anime.jpg")
items = ""
for i, (sym, mult, early) in enumerate(rows[:10], 1):
    tag = '<span class="e">EARLY</span>' if early else ""
    items += f'<div class="r"><span class="n">{i}</span><span class="s">${html.escape(sym.upper())}</span>{tag}<span class="m">{mult:.1f}x</span></div>'
page = f"""<html><body style="margin:0;width:1080px;height:1080px;position:relative;overflow:hidden;font-family:'Arial Black',Arial,sans-serif">
<div style="position:absolute;inset:0;background:url('file://{bg}') center/cover;filter:blur(3px) brightness(.42) saturate(1.2);transform:scale(1.06)"></div>
<div style="position:absolute;inset:0;background:radial-gradient(circle at 50% 30%,rgba(0,255,140,.12),rgba(0,0,0,.55) 75%)"></div>
<div style="position:absolute;inset:26px;border:3px solid #39ff88;border-radius:30px;box-shadow:0 0 28px #39ff88,inset 0 0 28px rgba(57,255,136,.4)"></div>
<div style="position:absolute;top:58px;width:100%;text-align:center;font-size:30px;letter-spacing:12px;color:#baffd6;text-shadow:0 0 12px #39ff88">CLIPERZ ✂</div>
<div style="position:absolute;top:104px;width:100%;text-align:center;font-size:92px;color:#eafff3;text-shadow:0 0 10px #39ff88,0 0 26px #39ff88,0 0 60px #12e06c">{html.escape(os.environ.get("LB_TITLE","TOP CALLS"))}</div>
<div style="position:absolute;top:206px;width:100%;text-align:center;font-size:34px;letter-spacing:6px;color:#baffd6;text-shadow:0 0 12px #39ff88">{html.escape(os.environ.get("LB_SUB","THIS WEEK"))}</div>
<div style="position:absolute;top:276px;left:110px;right:110px">{items}</div>
<div style="position:absolute;bottom:52px;width:100%;text-align:center;font-size:25px;color:#baffd6;text-shadow:0 0 10px #39ff88">{html.escape(os.environ.get("LB_FOOT") or f"Top {min(len(rows),10)} of {total} calls this week · NFA · @Cliperzcoins711")}</div>
<style>.r{{display:flex;align-items:center;height:66px;font-size:46px;color:#f2fff7;text-shadow:0 0 8px #39ff88,0 0 22px #12e06c}}
.n{{width:90px;color:#39ff88}}.s{{flex:1}}.m{{color:#c6ff5e;text-shadow:0 0 10px #c6ff5e,0 0 26px #7dff3a}}
.e{{font-size:22px;margin-right:26px;border:2px solid #39ff88;border-radius:10px;padding:2px 10px;color:#baffd6}}</style></body></html>"""
p = os.path.join(tempfile.mkdtemp(), "lb.html"); open(p, "w").write(page)
js = "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1080,height:1080}});await pg.goto('file://%s');await pg.screenshot({path:'%s'});await b.close()})()" % (p, os.path.abspath(out))
subprocess.run(["node", "-e", js], check=True)
