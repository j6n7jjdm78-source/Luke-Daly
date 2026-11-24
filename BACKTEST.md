# Backtest: which rules find the coins that reach bigger peaks?

Metric (chosen by the owner): **peak >= 2x** = the coin's best 5-minute close within 6 hours of our evaluation was at least twice the price at evaluation. Peaks come from 5-minute candles (`data/backtest/peaks.csv`); where a pool no longer exists the best known 1h/3h/6h checkpoint is used as a lower bound. Regenerate with `python3 tools/backtest/run.py`.

Data: 188 logged coins (2026-11-22T12:33 to 2026-11-23T18:37 UTC); 40 have candle peaks.

## Our public calls

- 22 public calls so far: **5 reached 1.5x+ (23%)**, **3 reached 2x+ (14%, 95% CI 5%-33%)**, 1 reached 4x+, 4 rugged. Median peak 1.21x.

## Rule sets on the logged coins

| Rule set | Coins | Peak >= 2x within 6h (95% CI) | Peak >= 1.5x | Median peak | Median after 1h | Above 1.0x after 1h | Gone after 1h |
|---|---|---|---|---|---|---|---|
| All logged coins (no filter) | 188 | 15 (8%, CI 5%-13%) | 10% | 0.00x | 0.00x | 12% | 81% |
| Live: coins we actually called (normal + early) | 16 | 0 (0%, CI 0%-19%) | 6% | 1.14x | 0.61x | 19% | 0% |
| Live normal tier only | 12 | 0 (0%, CI 0%-24%) | 0% | 1.14x | 0.69x | 25% | 0% |
| No safety gate: normal-tier coins that passed market filters | 13 | 0 (0%, CI 0%-23%) | 0% | 1.14x | 0.70x | 31% | 0% |
| Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked' | 17 | 0 (0%, CI 0%-18%) | 6% | 1.15x | 0.67x | 24% | 0% |
| Strict rug-checker: holders>=100, risk score<=20, no 'LP unlocked' | 17 | 0 (0%, CI 0%-18%) | 6% | 1.15x | 0.67x | 24% | 0% |
| Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5 | 106 | 9 (8%, CI 5%-15%) | 11% | 0.00x | 0.00x | 13% | 82% |
| Most active third (by trades) | 62 | 2 (3%, CI 1%-11%) | 3% | 0.00x | 0.00x | 3% | 87% |
| Near-misses (failed exactly one filter) | 0 | - | - | - | - | - | - |
| Early tier, all | 175 | 15 (9%, CI 5%-14%) | 10% | 0.00x | 0.00x | 10% | 87% |
| Early tier, called only | 4 | 0 (0%, CI 0%-49%) | 25% | 1.29x | 0.10x | 0% | 0% |

Random picks of the same size as the live selection (16 coins) reach 2x+ about **8%** of the time (90% range 0%-19%); the base rate over all logged coins is **8%**.

## Stability: first half vs second half of the period

A rule that only works in one half is probably luck.

| Rule set | Coins | Peak >= 2x within 6h (95% CI) | Peak >= 1.5x | Median peak | Median after 1h | Above 1.0x after 1h | Gone after 1h |
|---|---|---|---|---|---|---|---|
| All logged coins (no filter) (first half) | 94 | 11 (12%, CI 7%-20%) | 12% | 0.00x | 0.00x | 10% | 89% |
| All logged coins (no filter) (second half) | 94 | 4 (4%, CI 2%-10%) | 7% | 0.00x | 0.00x | 14% | 73% |
| Live: coins we actually called (normal + early) (first half) | 1 | 0 (0%, CI 0%-79%) | 0% | 1.14x | 0.55x | 0% | 0% |
| Live: coins we actually called (normal + early) (second half) | 15 | 0 (0%, CI 0%-20%) | 7% | 1.15x | 0.67x | 20% | 0% |
| Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked' (first half) | 1 | 0 (0%, CI 0%-79%) | 0% | 1.14x | 0.55x | 0% | 0% |
| Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked' (second half) | 16 | 0 (0%, CI 0%-19%) | 6% | 1.15x | 0.68x | 25% | 0% |
| Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5 (first half) | 57 | 5 (9%, CI 4%-19%) | 9% | 0.00x | 0.00x | 9% | 91% |
| Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5 (second half) | 49 | 4 (8%, CI 3%-19%) | 14% | 0.00x | 0.00x | 18% | 71% |

## The coins that did reach 2x

| Coin | Tier | Our decision | Why blocked / flags | Age at eval | Market cap | Liquidity | Holders | Peak (6h) | After 1h |
|---|---|---|---|---|---|---|---|---|---|
| ZOL | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 5 min | $29,122 | $28,239 | 539 | 13.6x | 13.58x |
| JAGENT | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 7 min | $50,566 | $37,325 | 360 | 6.7x | 5.91x |
| MCAT | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 8 min | $10,384 | $12,718 | 491 | 6.6x | 1.23x |
| OpenIndex | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 8 min | $10,473 | $15,873 | 461 | 6.1x | 1.72x |
| Dandelion | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 8 min | $19,835 | $33,404 | 739 | 5.7x | 4.78x |
| Claude | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 10 min | $23,516 | $36,868 | 934 | 4.4x | 3.44x |
| JENSEN | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 6 min | $21,802 | $36,139 | 744 | 4.2x | 3.07x |
| black | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 17 min | $25,082 | $35,740 | 930 | 3.6x | 0.00x |
| SAKURA | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 6 min | $20,851 | $34,293 | 725 | 3.3x | 3.24x |
| NEX Ai | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 18 min | $24,278 | $36,741 | 902 | 3.1x | 2.39x |
| GORP | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 7 min | $19,329 | $33,695 | 844 | 3.0x | 2.27x |
| CORONA | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 7 min | $18,736 | $32,956 | 687 | 2.8x | 1.52x |
| Green cat | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 32 min | $41,250 | $48,642 | 1718 | 2.6x | 0.00x |
| USOI | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 7 min | $18,679 | $32,423 | 626 | 2.4x | 0.00x |
| JUMP COIN | early | blocked | RugCheck danger: Large Amount of LP Unlocked | 7 min | $19,391 | $33,053 | 660 | 2.4x | 2.35x |

Of the 15 coins that reached 2x, **0 were ones we called and 15 were blocked by our filters** (most by the RugCheck 'LP unlocked' danger flag).


## Could a bot that posts a few minutes later still have caught them? (entry delay)

| Group | Coins with candles | Entry after 0 min: peak >= 2x | Entry after 3 min: peak >= 2x | Entry after 6 min: peak >= 2x | Entry after 10 min: peak >= 2x |
|---|---|---|---|---|---|
| All logged coins | 35 | 14/35 (40%, CI 26%-56%) | 12/35 (34%, CI 21%-51%) | 12/35 (34%, CI 21%-51%) | 11/35 (31%, CI 19%-48%) |
| Early coins blocked by 'LP unlocked' | 19 | 12/19 (63%, CI 41%-81%) | 12/19 (63%, CI 41%-81%) | 12/19 (63%, CI 41%-81%) | 11/19 (58%, CI 36%-77%) |
| Coins we actually called | 15 | 2/15 (13%, CI 4%-38%) | 0/15 (0%, CI 0%-20%) | 0/15 (0%, CI 0%-20%) | 0/15 (0%, CI 0%-20%) |

Of the coins that reached 2x, the first 2x close came a median **49 minutes** after we evaluated them (fastest 13, slowest 75); a call needs the confirmation wait plus posting time before anyone can act on it.


## Can anything tell surviving coins from rugs?

170 early coins carried the LP-unlocked flag. Only **18 (11%, CI 7%-16%) were still trading after 1 hour**; the rest were gone.

Best single-feature cuts for survival (scanned 33 cuts, so the best one is partly luck):

| Cut | Coins | Still trading after 1h (95% CI) |
|---|---|---|
| holders < 600 | 36 | 9 (25%, CI 14%-41%) |
| mcap >= 30000 | 37 | 7 (19%, CI 9%-34%) |
| liq >= 40000 | 34 | 6 (18%, CI 8%-34%) |
| m5 < 10 | 62 | 10 (16%, CI 9%-27%) |
| holders < 800 | 98 | 15 (15%, CI 10%-24%) |

**No cut clearly beats the base rate: with the features logged so far, surviving coins cannot be told apart from rugs before the fact.**


## Which logged features carry signal?

**Holders**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 100 to 300 | 9 | 0 (0%, CI 0%-30%) |
| 300 to 1000 | 143 | 14 (10%, CI 6%-16%) |
| 1000 to + | 36 | 1 (3%, CI 0%-14%) |

**RugCheck risk score (low = safer)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 0 to 5 | 17 | 0 (0%, CI 0%-18%) |
| 40 to 101 | 171 | 15 (9%, CI 5%-14%) |

**Age when evaluated (min)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 0 to 15 | 167 | 12 (7%, CI 4%-12%) |
| 60 to + | 13 | 0 (0%, CI 0%-23%) |

**Liquidity ($)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 15000 to 25000 | 34 | 1 (3%, CI 1%-15%) |
| 25000 to 50000 | 123 | 13 (11%, CI 6%-17%) |
| 50000 to + | 26 | 0 (0%, CI 0%-13%) |

**Market cap ($)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 0 to 30000 | 134 | 13 (10%, CI 6%-16%) |
| 30000 to 60000 | 41 | 2 (5%, CI 1%-16%) |

**1h price change at evaluation (%)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 0 to 20 | 15 | 0 (0%, CI 0%-20%) |
| 20 to 60 | 100 | 9 (9%, CI 5%-16%) |
| 60 to + | 70 | 6 (9%, CI 4%-17%) |

**5m price change at evaluation (%)**

| Bucket | Coins | Peak >= 2x |
|---|---|---|
| 0 to 10 | 68 | 6 (9%, CI 4%-18%) |
| 10 to 40 | 95 | 7 (7%, CI 4%-14%) |
| 40 to + | 20 | 2 (10%, CI 3%-30%) |

## What this means (plain language)

1. Only **15 of 188 logged coins (8%)** reached 2x within 6 hours, and **15 of those 15 were blocked by our safety filters** (the RugCheck 'LP unlocked' flag).
2. Coins with that flag were **gone within an hour 89% of the time** (152 of 170), so letting them through trades a few 2x peaks for many total losses.
3. The coins we actually called reached 2x within 6 hours **0 of 16 times** in this log. Among all rule sets tested, none beat random picking with confidence (all intervals overlap).
4. A few minutes of posting delay hardly changes whether a *surviving* coin reaches 2x (see the entry-delay table; that table only covers coins still trading after 1h, so it is biased and is not a hit rate for new coins). The hard part is knowing in advance which coins survive.
5. The open-source bots reviewed (QuantOrb, Scan-Scam-AI-v1) are rug detectors and publish no peak or profit results, so there is nothing comparable to beat; the fair comparison is the random-pick baseline above.
6. **For the goal of bigger peaks:** do not loosen the safety gate on this evidence. The honest path is to collect more outcomes with the new holder-concentration, insider and creator-history features (now logged for every coin) and the narrative-radar shadow log, then re-run this report. A rule is only promoted after it beats the random baseline on forward data.

## Read this before trusting any number

- **Small samples.** Confidence intervals above are wide; differences between rule sets are only real if their intervals do not overlap, and even then only for this period.
- **Selection bias.** Only coins that reached our safety stage (or narrowly missed one filter) are logged, not every coin on Solana, so these are not general market statistics.
- **Tuned on the same coins.** Rules built from this data are not proven by it; new strategies run in shadow mode and are judged on forward data before they go live.
- **Other bots.** Public rule sets (rug checkers, holder scanners) were re-implemented from their published criteria, not run; their own marketing claims are unverified.
- **Public base rates** (arXiv 2026 study of 832,941 Pump.fun launches; CoinGecko launch-day data) show that only about 0.2-1.4% of new coins last, so a good scanner is judged by enrichment over the base rate, not by winning most calls.
