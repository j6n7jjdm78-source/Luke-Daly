"""Milestone result card. Usage: python3 bot/result_card.py SYMBOL MULTIPLE(peak) CALL_K PEAK_K "called date" out.png"""
import sys, os, subprocess, tempfile, html
sym, mult, call_k, now_k, when, out = sys.argv[1:7]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bg = os.path.join(ROOT, "assets", "pfp_anime.jpg")
page = f"""<html><body style="margin:0;width:1200px;height:675px;position:relative;overflow:hidden;font-family:'Arial Black',Arial,sans-serif;color:#eafff3">
<div style="position:absolute;inset:0;background:url('file://{bg}') center 30%/cover;filter:blur(4px) brightness(.35) saturate(1.2);transform:scale(1.08)"></div>
<div style="position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,rgba(0,255,140,.16),rgba(0,0,0,.6) 78%)"></div>
<div style="position:absolute;inset:22px;border:3px solid #39ff88;border-radius:28px;box-shadow:0 0 26px #39ff88,inset 0 0 26px rgba(57,255,136,.35)"></div>
<div style="position:absolute;top:54px;left:70px;font-size:26px;letter-spacing:9px;color:#baffd6;text-shadow:0 0 10px #39ff88">CLIPERZ ✂ PEAK RESULT</div>
<div style="position:absolute;top:54px;right:70px;font-size:24px;color:#baffd6">@Cliperzcoins711</div>
<div style="position:absolute;top:118px;width:100%;text-align:center;font-size:76px;color:#eafff3;text-shadow:0 0 10px #39ff88,0 0 28px #12e06c">${html.escape(sym.upper())}</div>
<div style="position:absolute;top:210px;width:100%;text-align:center;font-size:210px;line-height:210px;color:#c6ff5e;text-shadow:0 0 14px #c6ff5e,0 0 40px #7dff3a,0 0 90px #39ff88">{html.escape(mult)}x</div>
<div style="position:absolute;top:470px;width:100%;text-align:center;font-size:42px;color:#eafff3;text-shadow:0 0 10px #39ff88">Called at ${html.escape(call_k)}k &nbsp;→&nbsp; peak ${html.escape(now_k)}k</div>
<div style="position:absolute;bottom:50px;width:100%;text-align:center;font-size:24px;color:#baffd6;text-shadow:0 0 8px #39ff88">Called {html.escape(when)} · every call tracked, wins + losses · NFA</div></body></html>"""
p = os.path.join(tempfile.mkdtemp(), "r.html"); open(p, "w").write(page)
js = "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1200,height:675}});await pg.goto('file://%s');await pg.screenshot({path:'%s'});await b.close()})()" % (p, os.path.abspath(out))
subprocess.run(["node", "-e", js], check=True)
