"""One command that checks everything before anything is sent back or merged.
  python3 deploy/selfcheck.py          offline checks (no network, posts nothing)
  python3 deploy/selfcheck.py --live   also read-only reachability checks of the free data sources
Exit code 0 = all green, 1 = at least one check failed."""
import ast, json, os, re, subprocess, sys, tempfile, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
RESULTS = []

def check(name):
    def deco(fn):
        try: msg = fn() or "ok"; RESULTS.append((name, True, msg))
        except Exception as e: RESULTS.append((name, False, f"{type(e).__name__}: {str(e)[:300]}"))
        return fn
    return deco

def tracked(*exts):
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f.endswith(exts) and os.path.exists(f)]

@check("python files compile")
def _():
    fs = tracked(".py")
    for f in fs: ast.parse(open(f).read(), f)
    return f"{len(fs)} files"

@check("workflow YAML parses and has jobs")
def _():
    import yaml
    fs = [f for f in tracked(".yml", ".yaml") if f.startswith(".github/workflows/")]
    for f in fs:
        d = yaml.safe_load(open(f)); assert isinstance(d, dict) and d.get("jobs"), f"{f}: no jobs"
    return f"{len(fs)} workflows"

@check("shell scripts parse")
def _():
    fs = tracked(".sh")
    for f in fs: subprocess.run(["bash", "-n", f], check=True)
    return f"{len(fs)} scripts"

@check("config is sane")
def _():
    c = json.load(open("bot/config.json"))
    for k in ("chain", "handle", "max_calls_per_day", "x_daily_budget_usd", "x_spend_alert_usd", "x_cost_usd", "watch_instant"): assert k in c, f"missing {k}"
    assert 0 < c["x_daily_budget_usd"] <= c["x_spend_alert_usd"], "budget must be positive and not above the alert level"
    assert all(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a) for a in c["watch_instant"]), "watch_instant entries must be Solana addresses"
    assert not c.get("dry_run"), "dry_run is on in config.json"
    return f"{len(c)} keys"

@check("no post template contains a link or site name")
def _():
    os.environ["CLIPERZ_DRY"] = "1"; sys.path.insert(0, os.path.join(ROOT, "bot")); import bot
    texts = [bot.CFG["cta_text"].format(link=""), bot.COMMUNITY_LINE] + [c.format(h="x", link="") for c in bot.CTA] + list(bot.MK_TIPS)
    texts += [l["text"] for l in json.load(open("content/lessons.json"))]
    bad = [t[:60] for t in texts if bot.URL_RE.search(t)]
    assert not bad, f"link-like text: {bad}"
    return f"{len(texts)} templates"

@check("main stage list matches the stage functions")
def _():
    src = open("bot/bot.py").read(); tree = ast.parse(src)
    defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    m = re.search(r"for stage in \(([^)]*)\)", src); stages = [s.strip() for s in m.group(1).split(",")]
    missing = [s for s in stages if s not in defs]; assert not missing, f"stages not defined: {missing}"
    return f"{len(stages)} stages"

@check("no secrets in tracked files")
def _():
    pats = [r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\bghp_[A-Za-z0-9]{30,}\b", r"\bgithub_pat_[A-Za-z0-9_]{30,}\b", r"CLIPERZ_TOKEN_KEY\s*=\s*\S{16,}"]
    hits = []
    for f in tracked(".py", ".json", ".md", ".yml", ".sh", ".txt", ".csv"):
        if f.endswith((".enc",)) or f.startswith("data/"): continue
        try: t = open(f, errors="ignore").read()
        except Exception: continue
        for p in pats:
            if re.search(p, t): hits.append(f"{f}: {p[:20]}")
    assert not hits, hits
    return "clean"

@check("full test suite")
def _():
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider"], capture_output=True, text=True, timeout=600)
    last = (r.stdout.strip().splitlines() or ["no output"])[-1]
    assert r.returncode == 0, "\n".join(r.stdout.strip().splitlines()[-15:])
    return last

@check("every stage runs in a dry run with no network")
def _():
    code = ("import os,sys,tempfile;os.environ['CLIPERZ_DRY']='1';sys.path.insert(0,'bot');import bot,urllib.request\n"
            "def nope(*a,**k): raise OSError('network disabled in selfcheck')\n"
            "bot.http=nope;bot.http_text=nope;urllib.request.urlopen=nope\n"
            "bot.STATE=tempfile.mkdtemp();bad=[]\n"
            "src=open('bot/bot.py').read();import re\n"
            "names=[s.strip() for s in re.search(r'for stage in \\(([^)]*)\\)',src).group(1).split(',')]\n"
            "for n in names:\n"
            "    try: getattr(bot,n)()\n"
            "    except SystemExit: pass\n"
            "    except Exception as e: bad.append(n+': '+type(e).__name__+' '+str(e)[:80])\n"
            "print('BAD',bad) if bad else print('OK',len(names))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, env={**os.environ, "CLIPERZ_DRY": "1"})
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
    assert out.startswith("OK"), out
    return out

if "--live" in sys.argv:
    def reach(name, url):
        @check(f"reachable: {name}")
        def _():
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cliperz-selfcheck"}), timeout=20) as r: return f"HTTP {r.status}"
    reach("DexScreener", "https://api.dexscreener.com/latest/dex/search?q=SOL")
    reach("GeckoTerminal", "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1")
    reach("RugCheck", "https://api.rugcheck.xyz/v1/stats/new_tokens")
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if tok: reach("Telegram", f"https://api.telegram.org/bot{tok}/getMe")

width = max(len(n) for n, _, _ in RESULTS)
for n, ok, msg in RESULTS: print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(width)}  {msg}")
failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
