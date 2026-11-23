"""Trade service used by the app: preview (safety + fee + quote), execute via the signer, positions and honest PnL.
The market object is injected (real HTTP in production, a fake in tests). Nothing here can sign anything."""
import html, re
from . import fees, swap_guard, solana
from wallet.safety import check_sell_route, check_mint, Unsafe

LAMPORTS = 10 ** 9
WSOL = swap_guard.WSOL


class TradeError(Exception):
    """Message is safe to show to the user."""


def clean(s, n=32):
    return html.escape(re.sub(r"[^\w .$\-]", "", str(s or ""))[:n]) or "?"


def parse_mint(text):
    t = (text or "").strip()
    if not (32 <= len(t) <= 44) or not t.isalnum():
        return None
    try: solana.pubkey_bytes(t)
    except Exception: return None
    return None if t == WSOL else t


class LiveMarket:
    """Production market data. Mainnet only (Jupiter has no devnet)."""
    def __init__(self, rpc, jup, dex_get):
        self.rpc, self.jup, self.dex_get = rpc, jup, dex_get

    def token_info(self, mint):
        ps = [p for p in (self.dex_get(f"https://api.dexscreener.com/tokens/v1/solana/{mint}") or []) if p.get("chainId") == "solana"]
        if not ps: return None
        p = max(ps, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        age = (__import__("time").time() * 1000 - (p.get("pairCreatedAt") or 0)) / 3.6e6 if p.get("pairCreatedAt") else None
        return {"name": p["baseToken"].get("name"), "symbol": p["baseToken"].get("symbol"), "price_usd": float(p.get("priceUsd") or 0),
                "mcap": p.get("marketCap") or p.get("fdv"), "liq_usd": (p.get("liquidity") or {}).get("usd") or 0, "age_h": age}

    def quote(self, i, o, amt, slip): return self.jup.quote(i, o, amt, slip)
    def swap_instructions(self, q, user): return self.jup.swap_instructions(q, user)
    def mint_info(self, mint): return self.rpc.mint_info(mint)
    def token_balance(self, user, mint):
        r = self.rpc.get_accounts([str(swap_guard.ata(user, mint))])[0]
        return int(r["data"]["parsed"]["info"]["tokenAmount"]["amount"]) if r else 0


class Trade:
    def __init__(self, signer, db, market, cfg, clock):
        self.signer, self.db, self.market, self.cfg, self.clock = signer, db, market, cfg, clock

    def _slip(self): return int(self.cfg.get("slippage_bps", 500))
    def _bps(self): return int(self.cfg.get("fee_bps", 100))

    def card(self, mint):
        info = self.market.token_info(mint)
        if not info: raise TradeError("No market found for this token.")
        if (info.get("liq_usd") or 0) < self.cfg.get("min_liquidity_usd", 10_000):
            raise TradeError(f"Liquidity too low (${info.get('liq_usd') or 0:,.0f}); not tradable here.")
        return info

    def preview_buy(self, mint, gross):
        """Everything shown on the confirm screen. Raises TradeError with a user-safe reason."""
        if not isinstance(gross, int) or gross <= 0: raise TradeError("Invalid amount.")
        info = self.card(mint)
        try: check_mint(self.market.mint_info(mint))
        except Unsafe as e: raise TradeError(f"Not safe to buy: {e}.")
        except Exception: raise TradeError("Could not verify the token's authorities; not buying.")
        fee = fees.fee(gross, self._bps()); net = gross - fee
        try:
            q = self.market.quote(WSOL, mint, net, self._slip()); out, min_out = int(q["outAmount"]), int(q["otherAmountThreshold"])
            sq = self.market.quote(mint, WSOL, out, self._slip())
            loss = check_sell_route(q, sq, net, {"execution": self.cfg.get("execution", {"max_price_impact_pct": 8, "max_roundtrip_loss_pct": 15})})
        except Unsafe as e: raise TradeError(f"Not safe to buy: {e}.")
        except Exception: raise TradeError("Could not get a price right now; try again.")
        return {"info": info, "gross": gross, "fee": fee, "net": net, "out": out, "min_out": min_out, "quote": q, "roundtrip_loss": loss,
                "impact": abs(float(q.get("priceImpactPct") or 0)) * 100}

    def buy(self, uid, wallet, mint, gross, pin=None):
        pv = self.preview_buy(mint, gross)
        jup = self.market.swap_instructions(pv["quote"], wallet)
        r = self.signer({"op": "swap", "tg_id": uid, "side": "buy", "mint": mint, "amount": gross, "min_out": pv["min_out"], "quote_out": pv["out"],
                         "slippage_bps": self._slip(), "jup": jup, **({"pin": pin} if pin is not None else {})})
        if not r.get("ok"): raise TradeError(r.get("error", "failed"))
        sym = clean(pv["info"].get("symbol"))
        self.db.record_trade(uid, self.clock(), "buy", mint, sym, gross, r.get("est_tokens", 0), r.get("fee_lamports", 0), r["sig"], True)
        if r.get("confirmed"): self.db.add_cost(uid, mint, sym, gross)
        return {"sig": r["sig"], "confirmed": r.get("confirmed"), "fee": r.get("fee_lamports", 0), "est_tokens": r.get("est_tokens", 0), "symbol": sym}

    def sell(self, uid, wallet, mint, pct):
        if pct not in (25, 50, 100): raise TradeError("Invalid amount.")
        bal = self.market.token_balance(wallet, mint)
        amount = bal * pct // 100
        if amount <= 0: raise TradeError("You don't hold this token.")
        try:
            q = self.market.quote(mint, WSOL, amount, self._slip()); out, min_out = int(q["outAmount"]), int(q["otherAmountThreshold"])
            jup = self.market.swap_instructions(q, wallet)
        except Exception: raise TradeError("No sell route right now; try again.")
        r = self.signer({"op": "swap", "tg_id": uid, "side": "sell", "mint": mint, "amount": amount, "min_out": min_out, "quote_out": out,
                         "slippage_bps": self._slip(), "jup": jup})
        if not r.get("ok"): raise TradeError(r.get("error", "failed"))
        row = next((p for p in self.db.positions(uid) if p["mint"] == mint), None); sym = row["symbol"] if row else "?"
        self.db.record_trade(uid, self.clock(), "sell", mint, sym, r.get("est_sol", 0), amount, r.get("fee_lamports", 0), r["sig"], True)
        if r.get("confirmed"): self.db.reduce_cost(uid, mint, amount, bal)
        return {"sig": r["sig"], "confirmed": r.get("confirmed"), "fee": r.get("fee_lamports", 0), "est_sol": r.get("est_sol", 0), "symbol": sym}

    def positions(self, uid, wallet):
        """Mark-to-market from real sell quotes. 'value' is what a sell would return now (before the sell fee); never presented as realized."""
        out = []
        for p in self.db.positions(uid):
            bal = self.market.token_balance(wallet, p["mint"])
            if bal <= 0: continue
            try: value = int(self.market.quote(p["mint"], WSOL, bal, self._slip())["outAmount"])
            except Exception: value = None
            out.append({"mint": p["mint"], "symbol": p["symbol"], "tokens": bal, "cost": p["cost_lamports"], "value": value,
                        "pnl_pct": None if value is None or not p["cost_lamports"] else (value - p["cost_lamports"]) * 100 / p["cost_lamports"]})
        return out
