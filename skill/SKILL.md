---
name: marge
description: Calculates the risk-based (stress-test) portfolio margin requirement and maximum gross leverage for an equity book - stocks, ETFs (leveraged and inverse ETFs exploded into their holdings), listed options and FX - using a prime-broker portfolio-margin methodology (macro, sector, relative-value, concentration and liquidity stress tests, combined as the two largest asset-class losses plus the square root of the sum of squares of the rest). Use this skill whenever the user asks how much margin, house requirement or leverage a prime broker would give on a portfolio, wants to stress-test or size a long/short or hedged book, compares how hedges, ETF overlays or position changes move the margin, wants the largest gross exposure a given amount of equity supports, or asks what drives a risk-based margin number - even if they only paste or upload holdings and ask "what leverage can I get?"
---

# marge: risk-based portfolio margin

`marge` replicates a prime-brokerage risk-based margin framework. Instead of
charging a fixed percentage per position, it shocks the whole book through a
set of scenarios and charges the worst losses. A hedged book can therefore run
far more gross than a directional one. The calculator is bundled in this skill.
Your job is to turn the user's holdings into its input files, run it, and
explain the result.

The engine was validated against a production broker report for a 150-position
long/short ETF book. The total matched to 0.007%, and every equity scenario
matched to within 0.01%. The answer is only as good as the data you feed it, so
most of the work below is data preparation.

## Setup

* `SKILL_DIR` is the folder that contains this file. In claude.ai it is usually
  `/mnt/skills/user/marge`. It may be read-only.
* Work in a writable folder, for example `mkdir -p /tmp/marge && cd /tmp/marge`.
  Save anything the user should download to `/mnt/user-data/outputs/` if that
  folder exists.
* Run the calculator with
  `python3 $SKILL_DIR/scripts/marge_cli.py <command> ...`. It needs Python 3.9+
  with `numpy` and `pandas`, and needs no install or internet access.
* Example inputs are in `$SKILL_DIR/assets/examples/` and blank templates are in
  `$SKILL_DIR/assets/templates/`. Copy them as a starting point.

## Workflow

### 1. Positions → `positions.csv`

One row per position, with columns `symbol, quantity, price, type`
(`stock` / `etf` / `option`). Shorts have negative quantity.

* ETFs need `basket` (the holdings id, usually the ETF's own symbol) and
  `leverage` (`3`, `-3`, `2`, `-1`, ...; 1 for plain ETFs).
* Options need `underlying, put_call, strike, expiry, implied_vol` and
  optionally `multiplier` (default 100).
* Anything that is not a stock, ETF or option (bonds, futures, swaps, crypto)
  can be given with its real `type`. It is charged a flat rate: 100% of value
  for longs, and 3 × max(price, $2.50) per share for shorts. Tell the user that
  these products are outside the stress model.

Uploaded spreadsheets and broker statements usually just need renaming and
cleaning with pandas. The loader accepts `.csv` or `.xlsx` and common column
aliases.

### 2. Security master and ETF holdings → `securities.csv`, `baskets.csv`

Every single name must have a row in `securities.csv`. That covers names held
directly and every ETF constituent, plus one row per ETF held. The full column
list, the GICS sector names, the country spellings and sourcing tips are in
`references/inputs.md`; read it before building these files. In order of how
much each field moves the answer:

1. **ETF holdings** (`baskets.csv`: `basket, symbol, weight` as a fraction of
   NAV). Holdings drive everything for ETF-heavy or hedged books, because a
   long ETF against short single names only nets out once the ETF is exploded.
   An ETF without holdings is treated as a single stock, which badly overstates
   the requirement of an index-hedged book. Do not renormalise the weights,
   since fund cash is genuinely unexposed. If you only have the top holdings,
   follow the residual approach in `references/inputs.md`.
2. **Market cap.** This sets the concentration shock: names above $150bn take
   ±25%, while small caps take up to +800% or −100%. A missing value is treated
   as the smallest bucket.
3. **Country** (country of risk). This sets the country group (1 = US, 2 = big
   developed markets, 3 = other developed, 4–5 = emerging and offshore) and
   with it every macro shock. Hong Kong-listed Chinese companies are
   `China Offshore`.
4. **Sector**, as a GICS industry group (level 2), for example `Banks` or
   `Software & Services`.
5. **ADV in shares, and price.** These drive the liquidity charge. Only very
   large positions relative to volume are affected.
6. **asset_id / issuer_id.** Map ADRs onto their ordinary share
   (`TSM` → `2330.TW`) and share classes onto one issuer (`GOOG`/`GOOGL`).
   Without this mapping, a hedge across listings looks unhedged.

Fill fields from the user's files first, then from tools you have (web search,
issuer holdings files), then from your own knowledge, clearly labelled as
estimates. Don't stall waiting for perfect data: run with stated assumptions
and let the data-quality check tell you which gaps matter.

### 3. Market state → `config.toml` (or `config.json`)

```toml
base_currency = "USD"
[market]
vix = 18.0       # spot VIX
vix_ema = 17.5   # 5-day exponential average of VIX
[fx_rates]       # 1 unit of local currency in base currency
JPY = 0.0067
```

Every non-base currency held needs an FX rate, or the run stops with a clear
error. The VIX inputs matter: VIX above 15 phases in extra US country shocks,
and a VIX EMA above 30 adds a +12.5% crash-up scenario. If the user doesn't
know them, use recent levels and say which values you used. Losses for asset
classes the engine doesn't model (credit, rates, commodities, convertibles) can
be added under `[external_losses]`.

### 4. Check, then run

```bash
M="python3 $SKILL_DIR/scripts/marge_cli.py"
$M check -p positions.csv -s securities.csv -b baskets.csv -c config.toml
$M run   -p positions.csv -s securities.csv -b baskets.csv -c config.toml \
         --json result.json --detail-dir detail
$M leverage -p positions.csv -s securities.csv -b baskets.csv -c config.toml --equity 25000000
```

* `check` ranks the data gaps by the share of gross exposure they touch. Fill
  anything above a few percent and re-run.
* `run` prints the full breakdown. `--detail-dir` writes CSVs for every
  scenario, country, sector, issuer and currency.
* `leverage` finds the largest scale of the current book that a given amount of
  equity supports. It re-runs the calculation in a search, because liquidity
  charges grow faster than size.
* Add `--as-of YYYY-MM-DD` when the portfolio has options, so their expiries are
  measured from the right date.

For what-if comparisons (add a hedge, cut a name, swap an ETF), use the Python
API rather than editing files repeatedly:

```python
import sys
SKILL_DIR = "/mnt/skills/user/marge"          # this skill's folder
sys.path.insert(0, f"{SKILL_DIR}/scripts")
import pandas as pd
from marge import load_params, run
params = load_params("config.toml")
pos = pd.read_csv("positions.csv")
base = run(pos, "securities.csv", "baskets.csv", params)
alt = run(pd.concat([pos, pd.DataFrame([{"symbol": "SPY", "quantity": -20000, "price": 560,
                                          "type": "etf", "basket": "SPY"}])]),
          "securities.csv", "baskets.csv", params)
print(base.total, alt.total, alt.equity["dominant"])
```

### 5. Report the answer

Lead with the numbers the user asked for, then explain what drives them. Losses
are negative in the engine's output; present the requirement as a positive
dollar amount.

```
## Margin estimate
- Requirement: $X (Y% of gross market value of $G)
- Max gross leverage: Z× gross / requirement; with $E equity: up to $… gross (from `leverage`)
- Binding scenario: <macro / sector / relative value / concentration>, <scenario name>

## What drives it
- 2-4 bullets: the components and names behind the binding scenario
  (e.g. "the +7.5% market-up shock on a net-short book costs $1.0M; pharma
  sector dispersion adds $0.55M")
- The next-largest scenarios, so the user knows what binds after a fix

## How to lower it (if relevant)
- Concrete trades that offset the binding scenario, ideally checked with a what-if run

## Assumptions
- Data you estimated or defaulted, the VIX and FX inputs, unmodelled products
```

How to read the components (see `references/guide.md` for the formulas):

* **Macro and sector.** A net long or short book loses on the market move
  (global). Unhedged country or sector tilts add dispersion losses, and single
  names add asset losses. Hedges that offset at index level but not within
  sectors leave sector dispersion behind.
* **Relative value / spot basis.** About 7.5% of the absolute net exposure of
  every issuer, summed with no offset. It binds for books with many small
  unhedged single-name residuals, for example from ETF-versus-stock hedges.
* **Concentration.** The biggest single-name or seven-name loss, where smaller
  market caps take much larger shocks.
* **Liquidity.** Positions over one day of average volume, OTC names, options
  vega, and non-US ETF create/redeem fees.

### Caveats to state when relevant

* This is an estimate. A broker's own number depends on its data (holdings,
  market caps, its leverage deltas) and on its current parameter tables, which
  it revises.
* Option paths (vol scenarios, vol surface, option liquidity, theta) follow the
  methodology but were not validated against broker output. The cash, ETF and
  FX paths were.
* Credit, rates, commodities, convertibles, crypto and special add-ons (SPACs,
  restricted or non-marginable names) are outside the model unless added as
  external losses or charged at the flat rate.

## Reference files

* `references/inputs.md`: every input column, GICS industry groups, country
  names and groups, sourcing tips, partial-holdings handling. Read it when
  building inputs.
* `references/guide.md`: the full user guide: methodology formulas and tables,
  configuration overrides, outputs, validation and limitations. Read it when
  you need to explain or change a parameter. It writes commands as
  `marge <command>`; in this skill that is
  `python3 $SKILL_DIR/scripts/marge_cli.py <command>`.
