"""Tests for tools/backtest/run.py: the statistics and rule sets must be right, or the report is worthless."""
import math, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "backtest"))
import run  # noqa: E402


def coin(peak6, m1h=1.0, **kw):
    r = dict(ca="c", tier="normal", decision="pass", eval_utc="2026-11-23T10:00:00+00:00", flags="", peak6=peak6, m1=m1h, m1h=str(m1h), m3h="", m6h="",
             holders="500", score="5", buys="300", sells="100", m5="3", h1="20", age_m="600", liq="40000", mcap="100000", peak_src="candles")
    r.update({k: str(v) if not isinstance(v, str) else v for k, v in kw.items()}); return r


def test_wilson_interval_basics():
    lo, hi = run.wilson(0, 0); assert (lo, hi) == (0.0, 1.0)
    lo, hi = run.wilson(5, 10); assert lo < 0.5 < hi and 0.23 < lo < 0.24 and 0.76 < hi < 0.77     # known value: 5/10 -> about 0.237-0.763
    lo, hi = run.wilson(0, 20); assert lo == 0.0 and 0.0 < hi < 0.17
    lo, hi = run.wilson(20, 20); assert hi == 1.0 and 0.83 < lo < 1.0

def test_wilson_gets_narrower_with_more_data():
    w_small = run.wilson(5, 10); w_big = run.wilson(50, 100)
    assert (w_big[1] - w_big[0]) < (w_small[1] - w_small[0])

def test_stats_counts_hits_and_medians():
    rows = [coin(3.0, 1.2), coin(2.0, 0.0), coin(1.4, 0.8), coin(0.5, 0.0)]
    s = run.stats(rows)
    assert s["n"] == 4 and s["hit2"] == 2 and s["rate2"] == 0.5 and s["rate15"] == 0.5
    assert s["med_peak"] == pytest.approx(1.7) and s["gone"] == 0.5 and s["up1h"] == 0.25

def test_stats_of_nothing_is_safe():
    assert run.stats([]) == {"n": 0}

def test_rules_select_what_they_say():
    rows = [coin(1, decision="pass", tier="normal"), coin(1, decision="blocked", tier="normal"), coin(1, decision="nearmiss", tier="normal"),
            coin(1, decision="posted", tier="early"), coin(1, decision="blocked", tier="early")]
    sets = run.apply_rules(rows)
    assert len(sets["All logged coins (no filter)"]) == 5
    assert len(sets["Live: coins we actually called (normal + early)"]) == 2
    assert len(sets["Live normal tier only"]) == 1
    assert len(sets["Near-misses (failed exactly one filter)"]) == 1
    assert len(sets["Early tier, called only"]) == 1

def test_rug_checker_rule_rejects_unlocked_liquidity_and_low_holders():
    ok = coin(1); lp = coin(1, flags="Large Amount of LP Unlocked"); few = coin(1, holders="20"); risky = coin(1, score="45")
    sets = run.apply_rules([ok, lp, few, risky]); rule = sets["Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked'"]
    assert rule == [ok]

def test_momentum_rule():
    good = coin(1, m5="4", h1="25", buys="300", sells="100"); falling = coin(1, m5="-5"); pumped = coin(1, h1="200"); weak = coin(1, buys="120", sells="100")
    assert run.apply_rules([good, falling, pumped, weak])["Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5"] == [good]

def test_random_baseline_matches_the_base_rate_in_expectation():
    rows = [coin(3.0)] * 25 + [coin(0.5)] * 75           # base rate 25%
    mean, lo, hi = run.random_baseline(rows, 20)
    assert 0.22 < mean < 0.28 and lo <= mean <= hi
    assert run.random_baseline([], 5) is None

def test_load_uses_candle_peak_or_best_checkpoint(tmp_path, monkeypatch):
    d = tmp_path / "bt"; d.mkdir()
    cols = "ca,symbol,eval_utc,age_m,mcap,liq,holders,score,flags,buys,sells,m5,h1,run_pct,decision,reason,price0,m1h,m3h,m6h,tier,qscore,src"
    (d / "candidates_snapshot.csv").write_text(cols + "\n" +
        "A,A,2026-11-22T10:00:00+00:00,30,1,1,1,1,,1,1,1,1,,pass,,0.1,0.5,3.0,1.0,normal,,\n" +
        "B,B,2026-11-22T11:00:00+00:00,30,1,1,1,1,,1,1,1,1,,blocked,,0.1,0,0,0,,,\n" +
        "C,C,2026-11-22T12:00:00+00:00,30,1,1,1,1,,1,1,1,1,,blocked,,0.1,,,,normal,,\n")      # C has no outcome: ignored
    (d / "peaks.csv").write_text("ca,pool,status,n_candles,peak_close_6h\nA,p,ok,50,2.5\nB,,no_pool,,\n")
    monkeypatch.setattr(run, "D", str(d))
    rows = {r["ca"]: r for r in run.load()}
    assert set(rows) == {"A", "B"}
    assert rows["A"]["peak6"] == 2.5 and rows["A"]["peak_src"] == "candles"
    assert rows["B"]["peak6"] == 0.0 and rows["B"]["peak_src"] == "checkpoints" and rows["B"]["tier"] == "early"     # old rows without a tier were early-tier

def test_report_builds_and_states_its_limits(tmp_path, monkeypatch):
    d = tmp_path / "bt"; d.mkdir()
    cols = "ca,symbol,eval_utc,age_m,mcap,liq,holders,score,flags,buys,sells,m5,h1,run_pct,decision,reason,price0,m1h,m3h,m6h,tier,qscore,src"
    lines = [f"C{i},S{i},2026-11-2{2 + i % 2}T1{i % 10}:00:00+00:00,30,60000,30000,300,5,,300,100,3,20,,{'pass' if i % 3 == 0 else 'blocked'},,0.1,{1.0 + (i % 4)},1,1,normal,,gt_trending" for i in range(40)]
    (d / "candidates_snapshot.csv").write_text(cols + "\n" + "\n".join(lines) + "\n")
    (d / "calls_snapshot.csv").write_text("id,token,chain,contract,called_at_utc,mcap_at_call,tweet_id,status,current_mcap,multiple,notes,peak_mcap\n1,AAA,solana,c,t,100000,1,open,50000,0.5,,450000\n2,BAD,solana,c,t,100000,2,open,1,0,,99999999999\n")
    monkeypatch.setattr(run, "D", str(d))
    md = run.build()
    assert "Peak >= 2x within 6h" in md and "Read this before trusting any number" in md and "Small samples" in md
    assert "1 reached 2x+" in md.replace("**", "") or "1 reached 2x+" in md                 # the absurd 99,999,999,999 peak is not counted as a win
    assert not math.isnan(len(md))


def test_report_with_no_data_does_not_crash(tmp_path, monkeypatch):
    d = tmp_path / "bt"; d.mkdir()
    (d / "candidates_snapshot.csv").write_text("ca,symbol,eval_utc,age_m,mcap,liq,holders,score,flags,buys,sells,m5,h1,run_pct,decision,reason,price0,m1h,m3h,m6h,tier,qscore,src\n")
    monkeypatch.setattr(run, "D", str(d))
    assert "nothing to test" in run.build()
