"""Tests for the Cliperz bot (bot/bot.py) and its save script. Run: python3 -m pytest tests/test_cliperz_bot.py -q
They never touch the network, X, Telegram or the real state: every external call is stubbed and STATE points at a temp folder."""
import json, os, subprocess, sys, shutil, time
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))
os.environ["CLIPERZ_DRY"] = "1"
import bot  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE", str(tmp_path / "state"))
    monkeypatch.setattr(bot, "DRY", False)
    monkeypatch.setattr(bot, "owner_msg", lambda t: bot.SENT.append(t))
    bot.SENT = []
    yield


def call(**kw):
    base = dict(id="1", token="COIN", mcap_at_call="100000", peak_mcap="0", current_mcap="100000", status="open", tweet_id="123", notes="")
    base.update({k: str(v) for k, v in kw.items()})
    return base


# ---------- peak maths: the hCAT ($85 billion peak) bug must never come back ----------
def test_peak_mult_normal():
    assert bot.peak_mult(call(peak_mcap=300000, current_mcap=150000)) == pytest.approx(3.0)

def test_peak_mult_uses_current_if_higher():
    assert bot.peak_mult(call(peak_mcap=0, current_mcap=250000)) == pytest.approx(2.5)

def test_peak_mult_absurd_peak_is_bad_data():
    x = call(mcap_at_call=128525, peak_mcap=85757259400, current_mcap=76263)
    assert bot.peak_mult(x) == pytest.approx(1.0)      # bad data counts as 'no gain'; a board can never show 667241x

def test_far_below_skips_chart_lookup():
    assert bot._far_below(call(peak_mcap=300000), 100000)        # under 80% of its peak
    assert bot._far_below(call(peak_mcap=0), 50000)               # under 60% of call price
    assert not bot._far_below(call(peak_mcap=300000), 290000)     # near its peak: must be looked up
    assert not bot._far_below(call(peak_mcap=0), 99000)


# ---------- confirmation, names, length, alerts ----------
def test_confirmed_needs_second_cycle(monkeypatch):
    monkeypatch.setitem(bot.CFG, "confirm_seconds", 0)
    assert bot.confirmed("AAA", 100000) is False         # first sight
    assert bot.confirmed("AAA", 100000) is True          # still there on the next cycle
    assert bot.confirmed("AAA", 90000) is False          # fell 10%: clock restarts

def test_confirmed_waits_the_configured_time(monkeypatch):
    monkeypatch.setitem(bot.CFG, "confirm_seconds", 100)
    bot.confirmed("BBB", 100000)
    assert bot.confirmed("BBB", 100000) is False

def test_name_ok_blocks_crude_names_but_not_innocent_words():
    assert bot.name_ok("Milo", "Milo the cat")
    assert bot.name_ok("assume", "assume nothing")
    assert not bot.name_ok("testicles", "testicles")

def test_xlen_counts_urls_as_23():
    assert bot.xlen("hi https://example.com/a/very/long/path/that/is/long/indeed/1234567890") == len("hi ") + 23

def test_owner_alert_is_rate_limited():
    for _ in range(3): bot.owner_alert("card-ZOL", "x")
    assert len(bot.SENT) == 1
    bot.owner_alert("card-OTHER", "y")
    assert len(bot.SENT) == 2


# ---------- quality score and safety gate ----------
def pair_q(buys=300, sells=100, h1=20, m5=2):
    return {"txns": {"h1": {"buys": buys, "sells": sells}}, "priceChange": {"h1": h1, "m5": m5}}

def test_quality_score_rises_with_buy_pressure_and_stays_in_range():
    lo = bot.quality_score(pair_q(buys=100, sells=100), 100000, 30000, 300000)
    hi = bot.quality_score(pair_q(buys=300, sells=100), 100000, 30000, 300000)
    assert 0 <= lo < hi <= 100

def good_report(**kw):
    d = {"rugged": False, "mintAuthority": None, "freezeAuthority": None, "risks": [], "totalHolders": 500, "score_normalised": 5, "transferFee": {}}
    d.update(kw); return d

@pytest.mark.parametrize("patch,expect_ok", [
    ({}, True),
    ({"mintAuthority": "x"}, False),
    ({"freezeAuthority": "x"}, False),
    ({"rugged": True}, False),
    ({"totalHolders": 40}, False),
    ({"score_normalised": 60}, False),
    ({"risks": [{"level": "danger", "name": "Large Amount of LP Unlocked"}]}, False),
    ({"risks": [{"level": "warn", "name": "Low amount of LP Providers"}]}, True),
    ({"transferFee": {"pct": 9}}, False),
])
def test_safety_gate(monkeypatch, patch, expect_ok):
    monkeypatch.setattr(bot, "rugcheck", lambda ca: good_report(**patch))
    ok, why, _ = bot.safety_rc("CA")
    assert ok is expect_ok, why

def test_safety_fails_closed_without_a_report(monkeypatch):
    monkeypatch.setattr(bot, "rugcheck", lambda ca: None)
    assert bot.safety_rc("CA") is None                  # caller must then treat it as not verified


# ---------- dump filter ----------
def cand(ca="CA1"):
    return (50, {"baseToken": {"address": ca, "symbol": "X"}, "priceUsd": "1", "pairAddress": "P"}, 1, 1, 1)

def test_dump_filter_skips_a_coin_far_below_its_hour_high(monkeypatch):
    monkeypatch.setattr(bot, "safety", lambda ca: (True, "ok", "fine"))
    monkeypatch.setattr(bot, "off_high", lambda q: 0.08)          # the Milo case
    ok, why, _ = bot._vet(cand())
    assert not ok and "dumping" in why

def test_dump_filter_passes_a_coin_near_its_high(monkeypatch):
    monkeypatch.setattr(bot, "safety", lambda ca: (True, "ok", "fine"))
    monkeypatch.setattr(bot, "off_high", lambda q: 0.9)
    assert bot._vet(cand())[0]

def test_dump_filter_does_not_block_when_chart_is_unavailable(monkeypatch):
    monkeypatch.setattr(bot, "safety", lambda ca: (True, "ok", "fine"))
    monkeypatch.setattr(bot, "off_high", lambda q: None)
    assert bot._vet(cand())[0]

def test_vet_keeps_the_safety_verdict_when_blocked(monkeypatch):
    monkeypatch.setattr(bot, "safety", lambda ca: (False, "mint authority is ACTIVE", ""))
    monkeypatch.setattr(bot, "off_high", lambda q: pytest.fail("chart must not be fetched for a blocked coin"))
    assert bot._vet(cand())[:2] == (False, "mint authority is ACTIVE")


# ---------- GeckoTerminal rate limiter ----------
class Err429(Exception):
    code = 429

def test_gt_get_retries_on_429_with_a_shared_pause(monkeypatch):
    seq = [Err429(), {"ok": 1}]
    def fake_http(url, *a, **k):
        v = seq.pop(0)
        if isinstance(v, Exception): raise v
        return v
    monkeypatch.setattr(bot, "http", fake_http)
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    before = list(bot.GT_STATS)
    assert bot.gt_get("https://x") == {"ok": 1}
    assert bot.GT_STATS[0] - before[0] == 2 and bot.GT_STATS[1] - before[1] == 1
    assert bot._GT_COOL[0] > time.time() - 1            # all threads pause after a 429


# ---------- marketing agent: drafts only ----------
def test_marketing_filters_scammy_posts():
    for bad in ["Free GIVEAWAY!! send me SOL", "this will 100x guaranteed", "DM me for presale"]:
        assert bot.MK_BAD.search(bad)
    assert not bot.MK_BAD.search("is this coin a rug? how do I check mint authority")

def test_reply_text_is_a_tip_only_when_the_post_is_about_safety():
    assert bot.mk_reply_text({"id": "5", "text": "How do I know if a coin is a rug?"}) in bot.MK_TIPS
    assert bot.mk_reply_text({"id": "6", "text": "gm everyone nice weather"}) is None

def test_reply_text_contract_check_is_not_an_endorsement(monkeypatch):
    ca = "A" * 44
    monkeypatch.setattr(bot, "rugcheck", lambda c: good_report(totalHolders=1475))
    monkeypatch.setattr(bot, "pair", lambda c: {"baseToken": {"symbol": "CIRC"}})
    txt = bot.mk_reply_text({"id": "7", "text": f"CA: {ca} to the moon"})
    assert "CIRC" in txt and "Not an endorsement" in txt and "NFA" in txt and bot.xlen(txt) <= 280

def test_reply_text_skips_a_contract_rugcheck_does_not_know(monkeypatch):
    monkeypatch.setattr(bot, "rugcheck", lambda c: None)
    assert bot.mk_reply_text({"id": "8", "text": f"CA: {'B' * 44}"}) is None

def test_quote_draft_picks_best_sane_result(monkeypatch):
    rows = [call(id=1, token="OK", peak_mcap=430000, tweet_id=111),                       # 4.3x
            call(id=2, token="BAD", mcap_at_call=128525, peak_mcap=85757259400, tweet_id=222),
            call(id=3, token="RUG", peak_mcap=900000, status="rugged", tweet_id=333),
            call(id=4, token="LOW", peak_mcap=120000, tweet_id=444)]                     # under 1.5x
    monkeypatch.setattr(bot, "rows", lambda: rows)
    key, link, text = bot.mk_quote_draft()
    assert key == "q1" and link.endswith("/111") and "4.3x" in text and "Peak, not a promise" in text

def test_marketing_never_posts(monkeypatch):
    """The marketing stage may only send a private DM; it must not call post() or the X write endpoint."""
    monkeypatch.setattr(bot, "post", lambda *a, **k: pytest.fail("marketing must not post"))
    monkeypatch.setattr(bot, "mk_find_posts", lambda n=3: [(5, {"id": "9", "text": "is this a rug? check holders", "public_metrics": {"like_count": 3}}, {"username": "someone", "public_metrics": {"followers_count": 900}})])
    monkeypatch.setattr(bot, "mk_quote_draft", lambda: None)
    monkeypatch.setattr(bot, "_once_today", lambda t: True)
    monkeypatch.setattr(bot, "now", bot.now.replace(hour=12))
    bot.marketing_drafts()
    assert len(bot.SENT) == 1 and "NOTHING was posted" in bot.SENT[0]


# ---------- the save script (the conflict that lost a whole run) ----------
def sh(cmd, cwd, env=None):
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {}))
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=e)

@pytest.mark.skipif(not shutil.which("git") or not shutil.which("openssl"), reason="needs git and openssl")
def test_save_state_wins_over_a_remote_that_moved_ahead(tmp_path):
    remote = tmp_path / "remote.git"; sh(f"git init -q --bare -b main {remote}", tmp_path)
    seed = tmp_path / "seed"; sh(f"git clone -q {remote} {seed}", tmp_path)
    sh("git config user.email a@b; git config user.name s; mkdir -p state bot; echo id > calls.csv; echo v1 > bot/bot.py; echo old > state/tokens.enc; git add -A; git commit -qm init; git push -q origin HEAD:main", seed)
    runner = tmp_path / "runner"; sh(f"git clone -q {remote} {runner}", tmp_path)
    (runner / "deploy").mkdir(); shutil.copy(os.path.join(ROOT, "deploy", "save_state.sh"), runner / "deploy" / "save_state.sh")
    sh("echo 1,A >> calls.csv; echo v2 > bot/bot.py; echo newer > state/tokens.enc; git commit -qam moved; git push -q origin HEAD:main", seed)   # remote moves ahead
    home = runner / "home"; (home / ".config" / "cliperz-bot").mkdir(parents=True)
    (home / ".config" / "cliperz-bot" / "tokens.json").write_text('{"refresh_token":"mine"}')
    with open(runner / "calls.csv", "a") as f: f.write("1,A\n2,B\n")
    r = sh("bash deploy/save_state.sh", runner, {"HOME": str(home), "TOKEN_KEY": "k"})
    assert r.returncode == 0, r.stderr
    check = tmp_path / "check"; sh(f"git clone -q {remote} {check}", tmp_path)
    assert (check / "calls.csv").read_text().splitlines() == ["id", "1,A", "2,B"]   # the runner's rows win
    assert (check / "bot" / "bot.py").read_text().strip() == "v2"                      # newer remote code kept
    dec = sh("openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:TOKEN_KEY -in state/tokens.enc", check, {"TOKEN_KEY": "k"})
    assert json.loads(dec.stdout)["refresh_token"] == "mine"

@pytest.mark.skipif(not shutil.which("git") or not shutil.which("openssl"), reason="needs git and openssl")
def test_save_state_leaves_a_reauthorized_login_alone_when_this_run_never_refreshed(tmp_path):
    remote = tmp_path / "remote.git"; sh(f"git init -q --bare -b main {remote}", tmp_path)
    seed = tmp_path / "seed"; sh(f"git clone -q {remote} {seed}", tmp_path)
    enc = "openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:TOKEN_KEY"
    (seed / "state").mkdir(); (seed / "tok.json").write_text('{"refresh_token":"OLD"}')
    sh(f"git config user.email a@b; git config user.name s; {enc} -in tok.json -out state/tokens.enc; rm tok.json; echo id > calls.csv; git add -A; git commit -qm init; git push -q origin HEAD:main", seed, {"TOKEN_KEY": "k"})
    runner = tmp_path / "runner"; sh(f"git clone -q {remote} {runner}", tmp_path)
    (runner / "deploy").mkdir(); shutil.copy(os.path.join(ROOT, "deploy", "save_state.sh"), runner / "deploy" / "save_state.sh")
    cfg = runner / "home" / ".config" / "cliperz-bot"; cfg.mkdir(parents=True)
    sh(f"openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:TOKEN_KEY -in state/tokens.enc -out {cfg}/tokens.json; sha256sum {cfg}/tokens.json | cut -d' ' -f1 > {cfg}/tokens.start.sha", runner, {"TOKEN_KEY": "k"})
    (seed / "tok.json").write_text('{"refresh_token":"FRESH"}')                            # someone re-authorizes on main meanwhile
    sh(f"{enc} -in tok.json -out state/tokens.enc; rm tok.json; git commit -qam fresh; git push -q origin HEAD:main", seed, {"TOKEN_KEY": "k"})
    with open(runner / "calls.csv", "a") as f: f.write("1\n")
    sh("bash deploy/save_state.sh", runner, {"HOME": str(runner / "home"), "TOKEN_KEY": "k"})
    check = tmp_path / "check"; sh(f"git clone -q {remote} {check}", tmp_path)
    dec = sh("openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:TOKEN_KEY -in state/tokens.enc", check, {"TOKEN_KEY": "k"})
    assert json.loads(dec.stdout)["refresh_token"] == "FRESH"
    assert "1" in (check / "calls.csv").read_text().split()
