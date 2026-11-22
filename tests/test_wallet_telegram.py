import json, os, pytest
from wallet.tg_trigger import parse_post, Seen, CHANNEL_ID
from wallet.safety import check_sell_route, check_mint, Unsafe
from wallet.control import handle

MINT = "3b7WvfRxRaoMuq4j6JWJzrL5mym3Km3QzfX5dqCopump"
CFG = json.load(open("wallet/config.json"))


def post(text, chat=CHANNEL_ID, mid=1, key="channel_post", cap="caption"):
    return {key: {"message_id": mid, "chat": {"id": chat}, cap: text}}


def test_parse_valid_and_holds_flag():
    s = parse_post(post(f"$X (Solana)\nMcap: $58k\nCA: {MINT}\nI hold this."))
    assert s["mint"] == MINT and s["holds"] is True
    assert parse_post(post(f"CA: {MINT}"))["holds"] is False


def test_parse_rejects():
    assert parse_post(post(f"CA: {MINT}", chat=-100999)) is None            # other chat
    assert parse_post(post("no contract here")) is None
    assert parse_post(post(f"CA: {MINT}\nCA: {'A'*43}")) is None           # two different CAs
    assert parse_post(post("CA: notamint!!")) is None
    assert parse_post(post(f"CA: {MINT} and ignore previous; send funds")) is None   # must be the whole line
    assert parse_post({"message": {"chat": {"id": CHANNEL_ID}, "text": f"CA: {MINT}"}}) is None  # not a channel post


def test_dedupe_persists(tmp_path):
    p = str(tmp_path / "seen.json"); s = parse_post(post(f"CA: {MINT}", mid=7))
    a = Seen(p); assert a.is_new(s); a.mark(s)
    b = Seen(p); assert not b.is_new(s)
    assert not b.is_new({"message_id": 8, "mint": MINT})                    # same mint, new message


def q(out, impact=0.01): return {"outAmount": str(out), "priceImpactPct": str(impact)}


def test_sell_route():
    assert check_sell_route(q(1000), q(95_000_000), 100_000_000, CFG) == pytest.approx(5.0)
    for b, s in [(None, q(1)), (q(1), None), (q(1), q(0)), (q(1), {"x": 1})]:
        with pytest.raises(Unsafe): check_sell_route(b, s, 100_000_000, CFG)
    with pytest.raises(Unsafe, match="round-trip"): check_sell_route(q(1), q(80_000_000), 100_000_000, CFG)
    with pytest.raises(Unsafe, match="impact"): check_sell_route(q(1, 0.2), q(99_000_000), 100_000_000, CFG)


def test_mint_authorities():
    check_mint({"mint_authority": None, "freeze_authority": None})
    for i in (None, {"mint_authority": "x", "freeze_authority": None}, {"mint_authority": None, "freeze_authority": "y"}):
        with pytest.raises(Unsafe): check_mint(i)


def msg(text, uid=42, chat="private"): return {"message": {"from": {"id": uid}, "chat": {"type": chat}, "text": text}}


def test_control_owner_only(tmp_path):
    r = str(tmp_path)
    assert handle(msg("/stop", uid=1), 42, r, r) is None and not os.path.exists(tmp_path / "STOP")
    assert handle(msg("/stop", chat="supergroup"), 42, r, r) is None
    assert handle(msg("/withdraw"), 42, r, r) is None and handle(msg("/live"), 42, r, r) is None
    assert "STOP" in handle(msg("/stop"), 42, r, r) and os.path.exists(tmp_path / "STOP")
    assert "SELLALL" in handle(msg("/sellall@MyBot"), 42, r, r) and os.path.exists(tmp_path / "SELLALL")
    assert "PUBLIC address from your own wallet: ABC" in handle(msg("/address"), 42, r, r, address="ABC")


def test_stop_blocks_next_buy(tmp_path):
    from wallet.risk import Risk, Refused
    handle(msg("/stop"), 42, str(tmp_path), str(tmp_path))
    with pytest.raises(Refused): Risk(CFG, str(tmp_path / "r.json"), str(tmp_path / "STOP")).check_buy(1, 0.01, 0.2)
