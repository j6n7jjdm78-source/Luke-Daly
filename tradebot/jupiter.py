"""Jupiter v6 client used by the APP (the signer never trusts its output; it re-validates everything).
Mainnet only: Jupiter has no devnet."""
import requests

BASE = "https://quote-api.jup.ag/v6"
S = requests.Session()


def quote(input_mint, output_mint, amount, slippage_bps, base=BASE):
    r = S.get(f"{base}/quote", timeout=10, params={"inputMint": input_mint, "outputMint": output_mint, "amount": int(amount),
                                                    "slippageBps": int(slippage_bps), "onlyDirectRoutes": "false", "asLegacyTransaction": "false"})
    r.raise_for_status()
    return r.json()


def swap_instructions(quote_response, user, base=BASE, priority_lamports=100_000):
    r = S.post(f"{base}/swap-instructions", timeout=10, json={
        "quoteResponse": quote_response, "userPublicKey": user, "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": int(priority_lamports), "priorityLevel": "high"}}})
    r.raise_for_status()
    return r.json()


def intent_numbers(q):
    """(quote_out, min_out) as ints from a quote response; raises on anything malformed."""
    return int(q["outAmount"]), int(q["otherAmountThreshold"])
