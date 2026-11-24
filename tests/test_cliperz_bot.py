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
    monkeypatch.setattr(bot.cliperz_keys, "optional", lambda name: None)      # no real keys: nothing can reach Telegram or X from a test
    monkeypatch.setattr(bot, "tg_api", lambda *a, **k: pytest.fail("tests must not call Telegram"))
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


# ---------- GeckoTerminal trending list is cached for 5 minutes ----------
def test_gt_trending_is_fetched_once_per_ttl(monkeypatch):
    calls = []
    def fake_gt(url):
        calls.append(url)
        return {"data": [{"relationships": {"base_token": {"data": {"id": "solana_TOKEN" + str(len(calls))}}}}]}
    monkeypatch.setattr(bot, "gt_get", fake_gt)
    first = bot.gt_trending(); n = len(calls)
    assert n == 5 and len(first) == 5                       # 5 lists on the first call
    assert bot.gt_trending() == first and len(calls) == n   # served from the cache: no new requests
    assert len(bot.gt_trending(ttl=0)) == 5 and len(calls) == 2 * n    # expired cache fetches again

def test_gt_trending_survives_a_total_gt_failure(monkeypatch):
    def boom(url): raise RuntimeError("down")
    monkeypatch.setattr(bot, "gt_get", boom)
    assert bot.gt_trending() == []                          # never raises, never caches an empty list


# ---------- one-tap approval of marketing drafts ----------
OWNER = "555"

def open_draft(did="abc", **kw):
    d = dict(text="Draft reply text. NFA", reply_to="777", quote_id=None, state="open", t=time.time()); d.update(kw)
    p = bot.mk_pending(); p[did] = d; bot.mk_pending_save(p)

@pytest.fixture
def poster(monkeypatch):
    posted = []
    monkeypatch.setattr(bot, "post", lambda text, **k: posted.append((text, k)) or "999")
    return posted

def test_only_the_owners_tap_can_post(poster):
    open_draft()
    assert bot.mk_handle_tap("mk:post:abc", 12345, OWNER) is None and poster == []        # a stranger is ignored completely
    assert bot.mk_pending()["abc"]["state"] == "open"

def test_owner_tap_posts_the_stored_draft_exactly_once(poster):
    open_draft()
    ans = bot.mk_handle_tap("mk:post:abc", 555, OWNER)
    assert ans.startswith("✅ Posted") and "/status/999" in ans
    assert poster == [("Draft reply text. NFA", {"reply_to": "777", "quote_id": None, "mirror": False})]
    assert "Already handled" in bot.mk_handle_tap("mk:post:abc", 555, OWNER) and len(poster) == 1     # a second tap does nothing

def test_a_tap_cannot_change_what_is_posted(poster):
    open_draft()
    bot.mk_handle_tap("mk:post:abc:EVIL TEXT", 555, OWNER)       # extra data in the tap is not used as text
    assert poster == [] or poster[0][0] == "Draft reply text. NFA"

def test_skip_never_posts(poster):
    open_draft()
    assert bot.mk_handle_tap("mk:skip:abc", 555, OWNER) == "Skipped." and poster == []
    assert "Already handled" in bot.mk_handle_tap("mk:post:abc", 555, OWNER) and poster == []

def test_expired_drafts_do_not_post(poster):
    open_draft(t=time.time() - 90000)
    assert "expired" in bot.mk_handle_tap("mk:post:abc", 555, OWNER) and poster == []

def test_unknown_draft_does_not_post(poster):
    assert "Already handled" in bot.mk_handle_tap("mk:post:nope", 555, OWNER) and poster == []

def test_daily_limit_of_approved_posts(poster):
    os.makedirs(bot.STATE, exist_ok=True)
    open(f"{bot.STATE}/mk_posted-{bot.now.date()}", "w").write("\n".join(f"d{i}" for i in range(bot.MK_MAX_APPROVED_PER_DAY)))
    open_draft()
    assert "Daily limit" in bot.mk_handle_tap("mk:post:abc", 555, OWNER) and poster == []

def test_quote_drafts_post_as_a_quote(poster):
    open_draft(reply_to=None, quote_id="321")
    bot.mk_handle_tap("mk:post:abc", 555, OWNER)
    assert poster[0][1]["quote_id"] == "321" and poster[0][1]["reply_to"] is None

def test_failed_post_can_be_retried(monkeypatch):
    def boom(*a, **k): raise RuntimeError("x down")
    monkeypatch.setattr(bot, "post", boom)
    open_draft()
    assert "Could not post" in bot.mk_handle_tap("mk:post:abc", 555, OWNER)
    assert bot.mk_pending()["abc"]["state"] == "open"

def test_garbage_taps_are_ignored(poster):
    for data in ("", "hello", "mk:", "mk:post"): assert bot.mk_handle_tap(data, 555, OWNER) is None
    assert poster == []

def test_marketing_drafts_with_buttons_post_nothing_and_store_open_drafts(monkeypatch):
    sent = []
    monkeypatch.setattr(bot.cliperz_keys, "optional", lambda n: OWNER if n == "TELEGRAM_OWNER_CHAT_ID" else None)
    monkeypatch.setattr(bot, "tg_api", lambda method, **p: sent.append((method, p)) or {})
    monkeypatch.setattr(bot, "post", lambda *a, **k: pytest.fail("drafts must not post"))
    monkeypatch.setattr(bot, "mk_find_posts", lambda n=3: [(5, {"id": "9", "text": "is this a rug? check holders", "public_metrics": {"like_count": 3}}, {"username": "someone", "public_metrics": {"followers_count": 900}})])
    monkeypatch.setattr(bot, "mk_quote_draft", lambda: None)
    monkeypatch.setattr(bot, "_once_today", lambda t: True); monkeypatch.setattr(bot, "now", bot.now.replace(hour=12))
    bot.marketing_drafts()
    with_kb = [p for m, p in sent if "reply_markup" in p]
    assert len(with_kb) == 1 and with_kb[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("mk:post:")
    assert [v["state"] for v in bot.mk_pending().values()] == ["open"]

def test_telegram_actions_reads_taps_and_posts(monkeypatch, poster):
    open_draft()
    monkeypatch.setattr(bot.cliperz_keys, "optional", lambda n: OWNER if n == "TELEGRAM_OWNER_CHAT_ID" else None)
    calls = []
    def fake(method, **p):
        calls.append(method)
        if method == "getUpdates":
            return {"result": [{"update_id": 41, "callback_query": {"id": "q1", "data": "mk:post:abc", "from": {"id": 555}, "message": {"chat": {"id": 555}, "message_id": 8}}}]}
        return {}
    monkeypatch.setattr(bot, "tg_api", fake)
    bot.telegram_actions()
    assert len(poster) == 1 and "answerCallbackQuery" in calls and open(f"{bot.STATE}/mk_tgoffset").read() == "42"
    assert any("✅ Posted" in m for m in bot.SENT)

def test_telegram_actions_does_not_poll_when_nothing_is_waiting(monkeypatch):
    monkeypatch.setattr(bot.cliperz_keys, "optional", lambda n: OWNER)
    monkeypatch.setattr(bot, "tg_api", lambda *a, **k: pytest.fail("must not poll Telegram without open drafts"))
    bot.telegram_actions()


# ---------- paper-trade outcome summary ----------
def test_outcome_summary_groups_by_tier_and_decision():
    rows = [dict(tier="early", decision="blocked", m1h="0"), dict(tier="early", decision="blocked", m1h="0"), dict(tier="early", decision="blocked", m1h="1.4"),
            dict(tier="normal", decision="posted", m1h="0.8"), dict(tier="normal", decision="pass", m1h="2.0"), dict(tier="normal", decision="pass", m1h="")]
    bot.cand_save([dict(ca="c", symbol="s", **r) for r in rows])
    out = bot.outcome_summary()
    assert "early / blocked: 3 coins, median 0.00x after 1h, 33% above 1.0x, 67% gone" in out
    assert "normal / called: 2 coins" in out                      # the row without an outcome yet is not counted

def test_outcome_summary_with_no_data():
    assert bot.outcome_summary() == "No finished 1-hour outcomes yet."


# ---------- only one copy of the bot may post ----------
def run_main(extra_env):
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "CLIPERZ_DRY", "CLIPERZ_ALLOW_LOCAL")}
    env.update(extra_env)
    return subprocess.run([sys.executable, os.path.join(ROOT, "bot", "bot.py")], capture_output=True, text=True, env=env, timeout=60)

def test_a_non_github_copy_refuses_to_run():
    r = run_main({"CLIPERZ_FAKE": "1"})
    if os.path.exists(os.path.join(ROOT, "STOP")): assert "STOP file" in r.stderr           # the STOP kill switch wins first
    else: assert r.returncode != 0 and "Only the GitHub Actions run may post" in r.stderr


# ---------- shared market filter rules, near-miss log, source attribution ----------
def good_pair(**over):
    q = {"baseToken": {"address": "CAGOOD", "symbol": "GOOD", "name": "Good coin"}, "pairCreatedAt": int((time.time() - 30 * 3600) * 1000),
         "marketCap": 100000, "liquidity": {"usd": 40000}, "volume": {"h24": 200000}, "txns": {"h1": {"buys": 300, "sells": 120}},
         "priceChange": {"h1": 15, "m5": 2}, "priceUsd": "0.001", "pairAddress": "P"}
    q.update(over); return q

def age_h(q): return (time.time() * 1000 - q["pairCreatedAt"]) / 3.6e6

def test_a_good_coin_passes_every_market_filter():
    q = good_pair(); assert bot.market_reasons(q, age_h(q)) == []

@pytest.mark.parametrize("over,reason", [
    ({"marketCap": 5000, "liquidity": {"usd": 40000}}, "mcap out of $20-300k"),
    ({"marketCap": 900000}, "mcap out of $20-300k"),
    ({"liquidity": {"usd": 10000}}, "liq<$25k"),
    ({"txns": {"h1": {"buys": 130, "sells": 120}}}, "weak buy ratio"),
    ({"txns": {"h1": {"buys": 50, "sells": 20}}}, "<200 trades"),
    ({"priceChange": {"h1": 15, "m5": -20}}, "dumping"),
    ({"priceChange": {"h1": 200, "m5": 2}}, "1h move out of range"),
    ({"volume": {"h24": 9000000}}, "wash volume"),
])
def test_each_filter_names_its_reason(over, reason):
    q = good_pair(**over); assert reason in bot.market_reasons(q, age_h(q))

def test_candidates_yields_good_coins_and_logs_single_filter_near_misses(monkeypatch):
    good, near, far = good_pair(), good_pair(baseToken={"address": "CANEAR", "symbol": "NEAR", "name": "n"}, txns={"h1": {"buys": 130, "sells": 120}}), \
        good_pair(baseToken={"address": "CAFAR", "symbol": "FAR", "name": "f"}, marketCap=5000, liquidity={"usd": 900})
    book = {"CAGOOD": good, "CANEAR": near, "CAFAR": far}
    monkeypatch.setattr(bot, "rows", lambda: [])
    monkeypatch.setattr(bot, "candidate_addresses", lambda: list(book))
    monkeypatch.setattr(bot, "prefetch", lambda a: None); monkeypatch.setattr(bot, "pair", lambda a: book[a])
    monkeypatch.setitem(bot.CFG, "min_score", 0)
    got = [c[1]["baseToken"]["address"] for c in bot.candidates()]
    assert got == ["CAGOOD"]
    logged = {r["ca"]: r for r in bot.cand_rows()}
    assert logged["CANEAR"]["decision"] == "nearmiss" and logged["CANEAR"]["reason"] == "weak buy ratio" and logged["CANEAR"]["tier"] == "normal"
    assert "CAFAR" not in logged and "CAGOOD" not in logged        # junk and clean passes are not near-misses

def test_near_miss_log_is_capped_per_day_and_deduplicated():
    for i in range(5):
        bot.log_near_miss(good_pair(baseToken={"address": f"C{i}", "symbol": "X", "name": "x"}), 30, "weak buy ratio", per_day=3)
    bot.log_near_miss(good_pair(baseToken={"address": "C0", "symbol": "X", "name": "x"}), 30, "weak buy ratio", per_day=3)
    assert len([r for r in bot.cand_rows() if r["decision"] == "nearmiss"]) == 3

def test_source_is_logged_with_the_candidate(monkeypatch):
    monkeypatch.setitem(bot._SRC, "CASRC", "dex_boost")
    bot.log_candidate("CASRC", good_pair(baseToken={"address": "CASRC", "symbol": "S", "name": "s"}), 600, None, "blocked", "x", tier="normal")
    bot.log_candidate("CAEARLY", good_pair(baseToken={"address": "CAEARLY", "symbol": "E", "name": "e"}), 10, 0.1, "blocked", "y", tier="early")
    rows_ = {r["ca"]: r for r in bot.cand_rows()}
    assert rows_["CASRC"]["src"] == "dex_boost" and rows_["CAEARLY"]["src"] == "gt_new_pools"

def test_outcome_summary_shows_near_misses_by_filter_and_by_source():
    rows_ = [dict(ca="a", tier="normal", decision="nearmiss", reason="weak buy ratio", m1h="2.0", src="gt_trending"),
             dict(ca="b", tier="normal", decision="nearmiss", reason="weak buy ratio", m1h="0.5", src="gt_trending"),
             dict(ca="c", tier="normal", decision="blocked", reason="x", m1h="0", src="dex_boost")]
    bot.cand_save([dict(symbol="s", **r) for r in rows_])
    out = bot.outcome_summary()
    assert "weak buy ratio: 2 coins" in out and "50% above 1.0x" in out
    assert "By data source:" in out and "gt_trending: 2 coins" in out and "dex_boost: 1 coins" in out


# ---------- extra RugCheck features logged with every candidate ----------
def test_rc_features_exclude_pool_accounts_and_read_creator_and_lp():
    d = {"knownAccounts": {"POOL": {"name": "Raydium", "type": "AMM"}}, "graphInsidersDetected": 2, "creatorTokens": [{}, {}, {}], "totalLPProviders": 0, "deployPlatform": "pump.fun",
         "topHolders": [{"address": "POOL", "pct": 40}, {"address": "A", "pct": 12.5}, {"address": "B", "pct": 7.5}, {"address": "C", "pct": 5}],
         "markets": [{"lp": {"lpLockedPct": 0}}, {"lp": {"lpLockedPct": 99.5}}]}
    f = bot.rc_features(d)
    assert f["top1"] == 12.5 and f["top10"] == 25.0 and f["insiders"] == 2 and f["creator_prior"] == 3
    assert f["lp_locked"] == 99.5 and f["lp_providers"] == 0 and f["launchpad"] == "pump.fun"

def test_rc_features_never_raise_on_odd_reports():
    for d in ({}, {"topHolders": None}, {"topHolders": [{"pct": "x"}]}, {"markets": [{"lp": None}]}, {"creatorTokens": "n/a"}):
        f = bot.rc_features(d); assert set(f) == {"top1", "top10", "insiders", "creator_prior", "lp_locked", "lp_providers", "launchpad"}

def test_candidate_log_stores_the_new_features(monkeypatch):
    monkeypatch.setitem(bot.RC_LAST, "CAF", {"totalHolders": 500, "score_normalised": 5, "risks": [], "topHolders": [{"address": "A", "pct": 9}], "graphInsidersDetected": 1})
    bot.log_candidate("CAF", good_pair(baseToken={"address": "CAF", "symbol": "F", "name": "f"}), 600, None, "blocked", "x", tier="normal")
    r = [x for x in bot.cand_rows() if x["ca"] == "CAF"][0]
    assert r["top1"] == "9.0" and r["insiders"] == "1" and r["holders"] == "500"


# ---------- X API cost: no links in posts, spend tracking, 402 handling ----------
import urllib.error as _ue, json as _json

def http402(): return _ue.HTTPError("https://api.x.com", 402, "Payment Required", {}, None)

def test_no_post_template_contains_a_link_or_website_name():
    """X charges about 13x more for a post with a link, so nothing we post may contain one (the Telegram link lives in the bio)."""
    texts = [bot.CFG["cta_text"].format(link=""), bot.COMMUNITY_LINE] + [c.format(h="x", link="") for c in bot.CTA] + list(bot.MK_TIPS)
    texts += [l["text"] for l in _json.load(open(os.path.join(ROOT, "content", "lessons.json")))]
    texts.append(bot.call_text("COIN", 100000, 40000, 30, {"volume": {"h24": 200000}}, "mint+freeze revoked | 500 holders | RugCheck: no risks", "CA" + "A" * 40))
    for t in texts: assert not bot.URL_RE.search(t), f"link-like text in a post template: {t[:80]!r}"
    assert "t.me" not in _json.dumps(bot.CFG.get("cta_text", ""))

def test_url_detector_sees_links_and_site_names_but_not_normal_text():
    for bad in ("join https://t.me/abc", "see rugcheck.xyz", "pump.fun launch", "x.com/status/1"): assert bot.URL_RE.search(bad), bad
    for ok in ("Mint authority revoked? NFA.", "Mcap: $59k | Liq: $12k", "CA: 5o7AFuoNWsy7gQS85ospXhWFJRnxDwTtwTR3JF2Jpump", "peaked at $403k = 2.2x"): assert not bot.URL_RE.search(ok), ok

def test_posts_record_their_estimated_cost_and_links_cost_more(monkeypatch):
    monkeypatch.setattr(bot, "token", lambda: "t"); monkeypatch.setattr(bot, "tg_send", lambda *a, **k: None)
    monkeypatch.setattr(bot, "http", lambda *a, **k: {"data": {"id": "1"}})
    bot.post("plain text, no link"); a = bot.x_spent_today()
    bot.post("has a link https://t.me/x"); b = bot.x_spent_today()
    assert a == pytest.approx(0.015) and b - a == pytest.approx(0.20)

def test_optional_x_calls_stop_when_the_daily_budget_is_used():
    assert bot.x_budget_ok()
    bot.x_spend("post_url", 3)                       # $0.60 > the $0.50 default budget
    assert not bot.x_budget_ok()

def test_spend_alert_fires_once_past_the_alert_level(monkeypatch):
    monkeypatch.setitem(bot.CFG, "x_spend_alert_usd", 0.1)
    bot.x_spend("post_url", 2); bot.x_spend("post_url", 2)
    assert len([m for m in bot.SENT if "Estimated X API spend" in m]) == 1       # rate limited to once an hour

def test_a_402_marks_credits_depleted_alerts_once_and_pauses_for_30_minutes(monkeypatch):
    monkeypatch.setattr(bot, "token", lambda: "t")
    def boom(*a, **k): raise http402()
    monkeypatch.setattr(bot, "http", boom)
    for _ in range(3):
        with pytest.raises(_ue.HTTPError): bot.post("hello")
    assert bot.x_blocked() and len([m for m in bot.SENT if "credits are depleted" in m]) == 1
    old = time.time() - 31 * 60; os.utime(f"{bot.STATE}/x402", (old, old))
    assert not bot.x_blocked()                         # tries again after 30 minutes

def test_a_blocked_x_means_no_card_is_made_for_a_call(monkeypatch):
    os.makedirs(bot.STATE, exist_ok=True); open(f"{bot.STATE}/x402", "w").close()
    monkeypatch.setattr(bot.subprocess if hasattr(bot, "subprocess") else __import__("subprocess"), "run", lambda *a, **k: pytest.fail("no card must be rendered while X credits are depleted"))
    bot.publish_call(good_pair(), 100000, 40000, "text")

def test_growth_and_marketing_reads_are_skipped_when_over_budget(monkeypatch):
    bot.x_spend("post_url", 3)
    monkeypatch.setattr(bot, "http", lambda *a, **k: pytest.fail("no optional X read may run over budget"))
    monkeypatch.setattr(bot, "_once_today", lambda t: True); monkeypatch.setattr(bot, "now", bot.now.replace(hour=17))
    bot.daily_growth()
    monkeypatch.setattr(bot, "now", bot.now.replace(hour=12)); monkeypatch.setattr(bot, "mk_quote_draft", lambda: None)
    bot.marketing_drafts()
    assert bot.SENT == []
