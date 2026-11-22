"""Executors. PaperExecutor simulates fills from REAL quotes (read-only), so paper results reflect real routes and impact.
Quotes/marks are injected so it is testable offline. The live Jupiter executor is added only in phase 3."""
SOL = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000


class PaperExecutor:
    live = False

    def __init__(self, quote_fn, mint_info_fn, slippage_bps=300):
        self.quote_fn, self.mint_info_fn, self.slip = quote_fn, mint_info_fn, slippage_bps

    def wallet_sol(self):
        return 0.0  # paper wallet holds nothing; the cap check is trivially satisfied

    def mint_info(self, mint):
        return self.mint_info_fn(mint)

    def quote_buy(self, mint, size_sol):
        return self.quote_fn(SOL, mint, int(size_sol * LAMPORTS), self.slip)

    def quote_sell(self, mint, tokens):
        return self.quote_fn(mint, SOL, int(tokens), self.slip)

    def buy(self, mint, size_sol, buy_quote):
        return {"tokens": int(buy_quote["outAmount"]), "size_sol": size_sol}

    def mark(self, mint, tokens):
        """SOL value of the position if sold now (real sell quote), or None if no route (treated as zero by the trader)."""
        try:
            return int(self.quote_sell(mint, tokens)["outAmount"]) / LAMPORTS
        except Exception:
            return None

    def sell(self, mint, tokens, fraction):
        return None  # paper: the fill is the mark; nothing to send
