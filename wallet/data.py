"""Market data (public, read-only). Reimplemented small so the wallet has no dependency on X credentials."""
import time, requests

S = requests.Session()
S.headers["User-Agent"] = "wallet-bot/0.1"


def _get(url, tries=4, **kw):
    for i in range(tries):
        r = S.get(url, timeout=15, **kw)
        if r.status_code == 429:
            time.sleep(2 + 3 * i); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"rate limited: {url}")


def best_pool(mint):
    """Highest-liquidity Solana pair for a mint (DexScreener)."""
    ps = [p for p in (_get(f"https://api.dexscreener.com/tokens/v1/solana/{mint}") or []) if p.get("chainId") == "solana"]
    if not ps:
        return None
    return max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


def candles(pool, since_ts, until_ts, agg=1):
    """1m (agg=1) or 5m OHLCV from GeckoTerminal, ascending, [(ts,o,h,l,c)] in USD, covering since..until.
    Pages backwards from `until_ts` (API returns newest-first, max 1000 per page)."""
    out, before = {}, int(until_ts)
    for _ in range(6):
        j = _get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/minute",
                 params={"aggregate": agg, "limit": 1000, "before_timestamp": before, "currency": "usd"})
        rows = j["data"]["attributes"]["ohlcv_list"]
        if not rows:
            break
        for t, o, h, l, c, _v in rows:
            out[int(t)] = (int(t), float(o), float(h), float(l), float(c))
        before = min(out) - 1
        if min(out) <= since_ts:
            break
        time.sleep(1)
    return sorted(v for v in out.values() if since_ts - 60 * agg <= v[0] <= until_ts)


def jupiter_quote(input_mint, output_mint, amount, slippage_bps=300):
    return _get("https://quote-api.jup.ag/v6/quote", params={
        "inputMint": input_mint, "outputMint": output_mint, "amount": int(amount), "slippageBps": slippage_bps})
