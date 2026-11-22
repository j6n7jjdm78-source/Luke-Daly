"""Pre-buy checks. Pure: callers pass already-fetched Jupiter quotes / mint info. Any missing data -> refuse (fail closed)."""


class Unsafe(Exception):
    pass


def check_sell_route(buy_quote, sell_quote, size_lamports, cfg):
    """buy_quote: SOL->token quote. sell_quote: token->SOL quote for the amount the buy would return.
    Requires a sell route to exist, acceptable price impact, and a round trip that loses <= max_roundtrip_loss_pct."""
    e = cfg["execution"]
    if not buy_quote or not sell_quote:
        raise Unsafe("no quote (no route)")
    try:
        out_back = int(sell_quote["outAmount"])
        impact = max(abs(float(buy_quote.get("priceImpactPct") or 0)), abs(float(sell_quote.get("priceImpactPct") or 0))) * 100
    except (KeyError, TypeError, ValueError):
        raise Unsafe("malformed quote")
    if out_back <= 0:
        raise Unsafe("sell route returns nothing")
    if impact > e["max_price_impact_pct"]:
        raise Unsafe(f"price impact {impact:.1f}% over limit")
    loss = (1 - out_back / size_lamports) * 100
    if loss > e["max_roundtrip_loss_pct"]:
        raise Unsafe(f"round-trip loss {loss:.1f}% over limit")
    return loss


def check_mint(info):
    """info: {'mint_authority': str|None, 'freeze_authority': str|None, 'liquidity_usd': float|None}. Authorities must be revoked."""
    if info is None:
        raise Unsafe("mint info unavailable")
    if info.get("mint_authority"):
        raise Unsafe("mint authority not revoked")
    if info.get("freeze_authority"):
        raise Unsafe("freeze authority not revoked")
