"""Make a 1200x675 call card. Usage: python3 bot/card.py N SYMBOL "Token Name" MCAP_K LIQ_K BUYS SELLS out.png"""
import sys, os, subprocess, tempfile
n, sym, name, mc, liq, b, s, out = sys.argv[1:9]
tag = os.environ.get("CARD_TAG", "CALL")
html = f"""<html><body style="margin:0;width:1200px;height:675px;background:radial-gradient(circle at 20% 0%,#16352a,#060a08 70%);font-family:Helvetica,Arial,sans-serif;color:#e9fff1;position:relative;overflow:hidden">
<div style="position:absolute;inset:24px;border:2px solid rgba(31,209,107,.35);border-radius:28px"></div>
<div style="position:absolute;left:70px;top:60px;font-size:26px;letter-spacing:8px;color:#1fd16b">CLIPERZ ✂ {tag} #{n}</div>
<div style="position:absolute;right:70px;top:60px;font-size:26px;color:#7fa090">@Cliperzcoins711</div>
<div style="position:absolute;left:70px;top:110px;font-size:110px;font-weight:900;background:linear-gradient(90deg,#1fd16b,#c6ff5e);-webkit-background-clip:text;color:transparent;white-space:nowrap">${sym.upper()}</div>
<div style="position:absolute;left:74px;top:250px;font-size:38px;color:#b9d6c6">{name} · Solana</div>
<div style="position:absolute;left:70px;top:350px;display:flex;gap:30px">
<div style="background:#0d1a14;border:1px solid #1f3a2d;border-radius:20px;padding:24px 34px"><div style="font-size:24px;color:#7fa090">MCAP</div><div style="font-size:60px;font-weight:800">${mc}k</div></div>
<div style="background:#0d1a14;border:1px solid #1f3a2d;border-radius:20px;padding:24px 34px"><div style="font-size:24px;color:#7fa090">LIQUIDITY</div><div style="font-size:60px;font-weight:800">${liq}k</div></div>
<div style="background:#0d1a14;border:1px solid #1f3a2d;border-radius:20px;padding:24px 34px"><div style="font-size:24px;color:#7fa090">1H BUYS / SELLS</div><div style="font-size:60px;font-weight:800">{b} / {s}</div></div></div>
<div style="position:absolute;left:74px;top:570px;font-size:26px;color:#7fa090">Called at ${mc}k mcap · every call tracked, wins + losses · NFA</div></body></html>"""
p = os.path.join(tempfile.mkdtemp(), "c.html"); open(p, "w").write(html)
js = "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1200,height:675}});await pg.goto('file://%s');await pg.screenshot({path:'%s'});await b.close()})()" % (p, os.path.abspath(out))
subprocess.run(["node", "-e", js], check=True)
