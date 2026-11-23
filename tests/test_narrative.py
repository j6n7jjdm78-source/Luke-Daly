"""Tests for the narrative radar (bot/narrative.py and bot.narrative_radar). No network; everything external is stubbed."""
import datetime as dt, email.utils, json, os, sys, time
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))
os.environ["CLIPERZ_DRY"] = "1"
import bot, narrative  # noqa: E402

NOW = dt.datetime(2026, 11, 23, 20, 0, tzinfo=dt.timezone.utc)


def rss(entries):
    """entries: [(title, source, minutes_ago)] -> Google-News-style RSS text."""
    items = "".join(f"<item><title>{t} - {s}</title><link>https://x/{i}</link><pubDate>{email.utils.format_datetime(NOW - dt.timedelta(minutes=m))}</pubDate><source url='https://{s}'>{s}</source></item>"
                    for i, (t, s, m) in enumerate(entries))
    return f"<?xml version='1.0'?><rss><channel>{items}</channel></rss>"


HOT = [("Nvidia board reinstates Jensen Huang", "NVIDIA Newsroom", 30), ("Trump claims credit as Jensen Huang returns", "NPR", 60),
       ("Trump tells CNBC he made the deal", "CNBC", 90), ("Jensen Huang back as CEO", "Reuters", 45)]


def pair(sym, name, liq, mc, age_h, h24=100, ca=None, chain="solana"):
    return {"chainId": chain, "baseToken": {"address": ca or f"CA{sym}{name}".replace(" ", ""), "symbol": sym, "name": name}, "liquidity": {"usd": liq}, "marketCap": mc,
            "pairCreatedAt": int((NOW.timestamp() - age_h * 3600) * 1000), "priceChange": {"h24": h24, "h1": 5}}


# ---------- pure helpers ----------
def test_parse_rss_reads_titles_sources_and_times():
    items = narrative.parse_rss(rss(HOT))
    assert len(items) == 4 and items[0]["source"] == "NVIDIA Newsroom" and items[0]["ts"] == (NOW - dt.timedelta(minutes=30))

def test_parse_rss_survives_garbage():
    assert narrative.parse_rss("not xml at all <<<") == []
    assert narrative.parse_rss("<rss><channel><item><title>x</title><pubDate>garbage</pubDate></item></channel></rss>") == []

def test_a_story_is_hot_only_when_broad_and_fresh():
    assert narrative.is_hot(narrative.parse_rss(rss(HOT)), NOW)
    assert not narrative.is_hot(narrative.parse_rss(rss(HOT[:2])), NOW)                                           # only 2 publishers
    assert not narrative.is_hot(narrative.parse_rss(rss([(t, s, m + 600) for t, s, m in HOT])), NOW)             # all stale
    one_outlet = [("A", "Same Paper", 10), ("B", "Same Paper", 20), ("C", "Same Paper", 30), ("D", "Same Paper", 40)]
    assert not narrative.is_hot(narrative.parse_rss(rss(one_outlet)), NOW)                                       # one publisher repeating itself is noise

def test_clones_are_grouped_and_the_most_liquid_one_wins():
    pairs = [pair("JENSEN", "Jensen Is Back", 77992, 1069938, 2.7, 1131), pair("JENSEN", "Jensen Is Back", 161, 998652, 0.3, -1, ca="FAKE1"),
             pair("JENSEN", "Jensen the White", 54348, 266033, 5.6, 100, ca="WHITE"), pair("JENSEN", "Official Jensen Huang", 0, 5894, 3.6, 92, ca="OFF"),
             pair("NVDA", "Unrelated", 90000, 90000, 1, 10, ca="NOPE"), pair("JENSEN", "Jensen Is Back", 50000, 400000, 2, 5, ca="ETH", chain="ethereum")]
    best = narrative.best_coins(pairs, ["jensen"], NOW.timestamp() * 1000)
    assert [c["name"] for c, _ in best] == ["Jensen Is Back", "Jensen the White"]
    assert best[0][0]["liq"] == 77992 and best[0][1] == 2          # the $161 clone is in the same family and loses
    assert all(c["ca"] != "ETH" for c, _ in best)                  # other chains are ignored

def test_old_or_illiquid_coins_are_not_suggested():
    pairs = [pair("JEN", "Jensen Old", 90000, 500000, 400), pair("JEN", "Jensen Tiny", 2000, 30000, 3)]
    assert narrative.best_coins(pairs, ["jensen"], NOW.timestamp() * 1000) == []

def test_red_flags_name_the_dangers():
    c = narrative.coin_view(pair("JENSEN", "Official Jensen Huang", 161, 998652, 80, 900), NOW.timestamp() * 1000)
    flags = " | ".join(narrative.red_flags(c, 3))
    assert "3 coins with this same name" in flags and "liquidity only $161" in flags and "faked" in flags
    assert "official" in flags and "late" in flags and "older coin" in flags
    clean = narrative.coin_view(pair("OK", "Jensen Fan", 60000, 120000, 5, 40), NOW.timestamp() * 1000)
    assert narrative.red_flags(clean, 1) == []

def test_alert_text_is_private_and_never_implies_endorsement():
    items = narrative.parse_rss(rss(HOT)); coins = narrative.best_coins([pair("JENSEN", "Jensen Is Back", 77992, 1069938, 2.7, 1131, ca="CAJ")], ["jensen"], NOW.timestamp() * 1000)
    text = narrative.format_alert("Jensen Huang", items, coins, NOW, {"CAJ": "passes the RugCheck gate"})
    assert "Narrative alert: Jensen Huang" in text and "CA: CAJ" in text and "nothing was posted" in text and "endorses" in text and "up 1131%" in text


# ---------- the radar stage ----------
@pytest.fixture
def radar(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE", str(tmp_path / "state")); monkeypatch.setattr(bot, "DRY", False); monkeypatch.setattr(bot, "now", NOW)
    monkeypatch.setattr(bot.cliperz_keys, "optional", lambda n: None)
    monkeypatch.setattr(bot, "post", lambda *a, **k: pytest.fail("a news alert must never post publicly"))
    monkeypatch.setitem(bot.CFG, "narrative_entities", {"Jensen Huang": ["jensen"]}); monkeypatch.setitem(bot.CFG, "narrative_enabled", True)
    sent = []; monkeypatch.setattr(bot, "owner_msg", lambda t: sent.append(t))
    monkeypatch.setattr(bot, "http_text", lambda url, headers=None: rss(HOT))
    pairs = [pair("JENSEN", "Jensen Is Back", 77992, 1069938, 2.7, 1131, ca="CAJ"), pair("JENSEN", "Jensen Is Back", 161, 998652, 0.3, -1, ca="FAKE")]
    monkeypatch.setattr(bot, "http", lambda url, *a, **k: {"pairs": pairs})
    monkeypatch.setattr(bot, "safety_rc", lambda ca, **k: (True, "ok", "mint+freeze revoked | 600 holders"))
    monkeypatch.setattr(bot, "off_high", lambda q: 0.8)
    return sent

def test_radar_alerts_once_logs_a_shadow_candidate_and_never_posts(radar):
    bot.narrative_radar(every=0)
    assert len(radar) == 1 and "Jensen Is Back" in radar[0] and "1 coins" not in radar[0] and "2 coins with this same name" in radar[0]
    assert "mint+freeze revoked" in radar[0] and "80% of its 1-hour high" in radar[0]
    logged = [r for r in bot.cand_rows() if r["ca"] == "CAJ"]
    assert logged and logged[0]["tier"] == "narrative" and logged[0]["src"] == "news:Jensen Huang" and logged[0]["decision"] == "alert"
    bot.narrative_radar(every=0)
    assert len(radar) == 1                                         # same story, same coin: not repeated

def test_radar_is_throttled_between_runs(radar):
    bot.narrative_radar(every=600); bot.narrative_radar(every=600)
    assert len(radar) == 1

def test_radar_stays_quiet_when_the_story_is_not_hot(radar, monkeypatch):
    monkeypatch.setattr(bot, "http_text", lambda url, headers=None: rss(HOT[:1]))
    bot.narrative_radar(every=0); assert radar == []

def test_radar_survives_a_failing_news_feed(radar, monkeypatch):
    def boom(url, headers=None): raise OSError("network down")
    monkeypatch.setattr(bot, "http_text", boom)
    bot.narrative_radar(every=0); assert radar == []               # no crash, no alert

def test_radar_shows_a_blocked_safety_verdict(radar, monkeypatch):
    monkeypatch.setattr(bot, "safety_rc", lambda ca, **k: (False, "RugCheck danger: Large Amount of LP Unlocked", ""))
    bot.narrative_radar(every=0); assert "BLOCKED: RugCheck danger: Large Amount of LP Unlocked" in radar[0]

def test_radar_does_nothing_in_dry_mode_or_when_disabled(radar, monkeypatch):
    monkeypatch.setattr(bot, "DRY", True); bot.narrative_radar(every=0); assert radar == []
    monkeypatch.setattr(bot, "DRY", False); monkeypatch.setitem(bot.CFG, "narrative_enabled", False); bot.narrative_radar(every=0); assert radar == []


def test_alias_matching_uses_whole_words_not_substrings():
    c = lambda name, sym="X": narrative.coin_view(pair(sym, name, 50000, 90000, 2), NOW.timestamp() * 1000)
    assert narrative.matches(c("Elon Musk Coin"), ["elon", "musk"]) and narrative.matches(c("ELONMUSK"), ["elon"]) and narrative.matches(c("x", "ELON"), ["elon"])
    assert not narrative.matches(c("Melon Cat"), ["elon"]) and not narrative.matches(c("Trumpet Dog"), ["trump"]) and not narrative.matches(c("Muskrat"), ["musk"])
    assert narrative.matches(c("Trump Pepe"), ["trump"])

def test_missing_24h_change_does_not_print_none():
    coins = narrative.best_coins([pair("JEN", "Jensen Fan", 60000, 120000, 5, h24=None)], ["jensen"], NOW.timestamp() * 1000)
    assert "None" not in narrative.format_alert("Jensen Huang", narrative.parse_rss(rss(HOT)), coins, NOW)

def test_a_coin_logged_earlier_still_records_the_narrative_alert(radar):
    bot.log_candidate("CAJ", pair("JENSEN", "Jensen Is Back", 77992, 1069938, 2.7, ca="CAJ"), 160, None, "blocked", "x", tier="early")
    bot.narrative_radar(every=0)
    row = [r for r in bot.cand_rows() if r["ca"] == "CAJ"][0]
    assert row["tier"] == "early" and row["reason"].startswith("also narrative: narrative:Jensen Huang")
