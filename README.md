# marge

`marge` is a risk-based (stress-test) portfolio margin calculator. You give it a
portfolio and it computes the house margin requirement under a prime-brokerage
style stress framework. It also reports the gross leverage that requirement
implies.

Rather than charging a fixed percentage per position, the framework shocks the
whole book through a set of scenarios. It takes the worst loss in each asset
class and aggregates those losses with partial diversification:

```
Total requirement = sum of the 2 largest asset-class losses
                    + SRSS (square root of sum of squares) of the other asset-class losses
                    + add-ons (flat-rate charges)
```

Asset classes are equity, credit, convertibles, interest rates, FX and
commodities. `marge` fully implements **equity** (stocks, ETFs including
leveraged and inverse ETFs, and listed options) and **FX**. Losses for the other
classes can be supplied as inputs so the aggregation stays complete.

---

## Contents

1. [Install](#install)
2. [Quick start](#quick-start)
3. [Inputs](#inputs)
4. [Command line](#command-line)
5. [Python API](#python-api)
6. [Outputs](#outputs)
7. [How the requirement is calculated](#how-the-requirement-is-calculated)
8. [Configuration reference](#configuration-reference)
9. [Validation](#validation)
10. [Assumptions and limitations](#assumptions-and-limitations)

---

## Install

You need Python 3.11+ with `numpy` and `pandas`.

```bash
pip install -e .            # installs the `marge` command
# or run it without installing:
python -m marge --help
```

## Quick start

The `examples/` folder has a small portfolio: long/short single stocks, two
share classes of one issuer, an ADR, foreign listings, a custom ETF and a 3x
leveraged ETF on the same basket, listed options, an illiquid small cap and an
OTC name.

```bash
marge run -p examples/positions.csv -s examples/securities.csv \
          -b examples/baskets.csv -c examples/config.toml --as-of 2026-10-21
```

```
REQUIREMENT
  Total requirement                                 -1,721,127  7.20% of gross
    Stress requirement (top 2 + SRSS rest)          -1,721,127
      Equity                                        -1,628,967
      FX                                               -92,160
      ...
  Max gross leverage (gross / requirement)               13.9x

EQUITY
  Equity requirement                                -1,628,967
    Stress test (worst of five)                     -1,329,094  driver: concentration
      Macro: global + country + asset                 -511,118  -5% Vol Low
      Sector: global + sector + asset                 -403,310  -15% Vol Unch
      Relative value                                -1,152,211  driver: spot_basis
      Concentration                                 -1,329,094
        Single name                                 -1,124,553  JPMorgan Chase & Co Spot +50% (5b-150b)
        Seven names                                 -1,329,094  market down
      Theta (5-day decay)                               -8,248
    Liquidity                                         -299,872
  ...
```

Losses are shown as negative numbers, in base currency.

To find the largest book a given amount of equity supports:

```bash
marge leverage -p examples/positions.csv -s examples/securities.csv \
               -b examples/baskets.csv -c examples/config.toml --equity 5000000
```

```
Current requirement                   1,721,127
Max scale of current book                2.430x
Max gross market value               58,117,952
Max gross leverage                       11.62x
```

The stress components scale linearly with position size, but liquidity charges
grow faster than linearly. `leverage` therefore re-runs the full calculation in
a bisection search rather than dividing equity by the requirement.

---

## Inputs

There are three CSV files and one optional TOML file. Column names are not case
sensitive, and common aliases are accepted (for example `qty` for `quantity`
and `ticker` for `symbol`).

### 1. `positions.csv` (required)

One row per position.

| column | required | description |
|---|---|---|
| `symbol` | yes | Instrument identifier. Stocks and ETFs should match the security master. |
| `quantity` | yes | Signed quantity (shares or contracts). Negative means short. |
| `price` | yes* | Price in the instrument's currency. *Taken from the security master if omitted.* |
| `type` | no | `stock`, `etf` or `option`. Any other value (`bond`, `future`, `unknown`, ...) is charged a flat rate (see add-ons). Defaults to `etf` when the symbol has holdings in the basket file, otherwise `stock`. |
| `basket` | no | For ETFs: the basket in `baskets.csv` used to explode the ETF into constituents. Defaults to the ETF's own symbol. Leveraged and inverse ETFs on an index point at the same basket as the plain ETF. |
| `leverage` | no | ETF leverage factor (`3`, `-3`, `2`, `-1`, ...). Default 1. For options, the leverage of the underlying ETF. On a stock it acts as a delta multiplier. |
| `currency` | no | Trading currency. Defaults to the security master, then to the base currency. |
| `multiplier` | no | Contract multiplier. Default 1 for stocks and ETFs, 100 for options. |
| `underlying` | options | Underlying symbol. If the underlying is an ETF with holdings, the option is exploded the same way. |
| `put_call`, `strike`, `expiry`, `implied_vol` | options | `C`/`P`, strike, expiry date (`YYYY-MM-DD`, or a number of days), and implied vol (decimal, or percent when above 3). |
| `underlying_price`, `dividend_yield` | no | Override the underlying price, and set a continuous dividend yield (default 0). |

### 2. `securities.csv` (security master)

One row per single name that is held directly or through an ETF. Add one row
per ETF that you hold.

| column | description |
|---|---|
| `symbol` | Identifier used in positions and baskets. |
| `name` | Display name. |
| `asset_id` | The economic security the line belongs to. Map an ADR or a secondary listing onto its ordinary share (for example `TSM` → `2330.TW`). Defaults to `symbol`. Macro, sector and FX work at this level. |
| `issuer_id` | The company. Every share class and listing of one issuer shares it (for example `GOOG`/`GOOGL`). Defaults to `asset_id`. Concentration, relative value and liquidity work at this level. |
| `country` | Country of risk, which sets the country group (see below). Common aliases are accepted: `US`, `UK`, `South Korea`, `Taiwan`, `China Offshore` for Hong Kong-listed Chinese companies, and others. |
| `sector` | GICS industry group (level 2), for example `Banks` or `Software & Services`. |
| `market_cap` | Market cap in base currency. A missing value puts the issuer in the smallest, most punitive concentration bucket, and a warning is printed. |
| `adv` | Average daily volume in shares (21-day). Used for delta liquidation. |
| `price` | Local price. Used with `adv` and for options. |
| `currency` | Trading currency of the listing. The FX stress uses the currency of the **asset's primary row**, so an ADR carries the currency of its ordinary share. |
| `is_etf`, `etf_liquid` | ETF flags. Non-home-market ETFs pay a create/redeem fee: 20 bp if liquid, 60 bp if not. |
| `otc` | Pink-sheet / OTC flag. Names under $5 are held to the OTC per-share minimum. |
| `liq_class` | Option liquidity class `I1`–`I3` / `S0`–`S4`. Inferred when blank. |
| `country_group` | Override the country group (1–5) for this name. |
| `financial` | Override the financial flag. It defaults to true for Banks, Financial Services and Insurance. |
| `leverage` | Default leverage for an ETF symbol. |

The roll-up attributes of an `asset_id` or `issuer_id` (country, market cap,
ADV, currency) come from the row whose `symbol` equals that id. If that row is
missing, they come from the first line found.

### 3. `baskets.csv` (ETF holdings)

| column | description |
|---|---|
| `basket` | Basket id (usually the ETF symbol). |
| `symbol` | Constituent symbol. It must be in the security master. |
| `weight` | Fraction of NAV. Percentages are accepted when the weights look like percent. **Do not renormalise.** Cash held by the fund is simply not exposed to equity shocks. |

ETF issuers publish daily holdings files that can be converted to this format.

### 4. `config.toml` (optional)

This file sets the market state, FX rates and any parameter overrides. See
[Configuration reference](#configuration-reference).

```toml
base_currency = "USD"

[market]
vix = 18.0        # spot VIX
vix_ema = 17.5    # 5-day exponential average of VIX ("EAV")
rate = 0.04       # flat rate for option pricing

[fx_rates]        # 1 unit of local currency in base currency
JPY = 0.0067
HKD = 0.128
```

---

## Command line

```
marge run      -p POSITIONS [-s SECURITIES] [-b BASKETS] [-c CONFIG]
               [--as-of YYYY-MM-DD] [--vix X] [--vix-ema X] [--base-currency CCY]
               [--json FILE|-] [--detail-dir DIR] [--top N] [--quiet]

marge leverage -p POSITIONS ... --equity AMOUNT
```

* `--json`: writes a machine-readable summary (all components, worst scenarios
  and key breakdowns). Pass `-` to print it to stdout.
* `--detail-dir`: writes one CSV per breakdown: every macro and sector scenario,
  per-country, per-sector and per-asset losses, relative-value losses by issuer,
  the spot basis floor by underlier, concentration by issuer, the seven-name
  list, delta liquidation, option liquidity, FX by currency, add-ons, and the
  positions with their deltas.

## Python API

```python
from marge import load_params, build_model, compute
from marge.report import text_report

params = load_params("examples/config.toml", overrides={"market": {"vix": 22}})
model = build_model("examples/positions.csv", "examples/securities.csv",
                    "examples/baskets.csv", params)
result = compute(model)

result.total                       # total requirement (negative)
result.summary()                   # nested dict of every component
result.equity["macro"]["scenarios"]  # every macro scenario
print(text_report(result, model))
```

`build_model` also accepts pandas DataFrames in place of file paths, which is
convenient for what-if analysis. `marge.engine.max_scale(model, equity)` returns
the largest uniform scale of the book whose requirement fits the equity.

---

## Outputs

| field | meaning |
|---|---|
| `total_requirement` | Stress requirement plus add-ons. This is the margin the account must hold. |
| `stress_requirement` | Sum of the two largest asset-class losses plus SRSS of the rest. |
| `equity.*` | Equity requirement = worst of {macro, sector, relative value, concentration, theta} + liquidity. |
| `fx.*` | Worst of {base-currency move, two-currency move, pegged currency}. |
| `exposure.max_gross_leverage` | Gross market value ÷ requirement: the gross leverage the account could run if its equity just covered the requirement. |
| `exposure.requirement_pct_gross` | Requirement as a percentage of gross market value. |

---

## How the requirement is calculated

### Exposure lines: ETF explosion

Each position becomes one or more **exposure lines**. A stock is one line. An
ETF with holdings is exploded into constituents by NAV weight. A leveraged or
inverse ETF uses the same basket scaled by its leverage, and its value is
floored at zero: a 3x ETF loses at most 100% of its value. An option is a line
on its underlying and is revalued with Black-Scholes.

Shocks are applied in one of two ways:

* **Systematic** (index-wide moves in the macro and sector trees): the whole
  basket moves, and the position's P&L is allocated to constituents by weight.
* **Idiosyncratic** (single-name moves in concentration and relative value):
  only the constituent moves, so the fund moves by `weight × shock`.

### Country groups

Countries fall into groups 1–5. Groups 1–3 are **core** markets and groups 4–5
are **non-core**.

| group | countries (defaults; override in config) |
|---|---|
| 1 | United States |
| 2 | United Kingdom, France, Germany, Netherlands, Switzerland, Japan |
| 3 | Canada, Austria, Belgium, Denmark, Finland, Ireland, Italy, Luxembourg, Norway, Spain, Sweden, Australia, New Zealand, Hong Kong, China Offshore, Singapore, Korea, Taiwan |
| 4 | Mexico, Brazil, Portugal, Iceland, Croatia, Czech Republic, Poland, Slovenia, China (onshore), India, Malaysia, Thailand, Israel, South Africa, Bahrain, Oman |
| 5 | all others, including Argentina, Chile, Colombia, Peru, Greece, Hungary, Turkey, Indonesia, the Philippines, Gulf states, and offshore domiciles (Bermuda, Jersey, Cayman, ...) |

### Equity stress test: worst of five

**1. Macro (global + country + asset).** Every name is shocked by a global move
*g* ∈ {−15, −10, −5, 0, +5, +10%}. A +12.5% shock is added when the VIX EMA is
above 30. From each global node, every country is shocked up and down by its
dispersion, and from the worse country node every asset is shocked up and down
by its own dispersion.

| group | country dispersion | asset dispersion |
|---|---|---|
| 1 | 2% (at the +10% shock: 0% for VIX ≤ 15, rising linearly to 2% at VIX 30) | 10% |
| 2 | 5% | 12.5% |
| 3 | 7.5% | 12.5% |
| 4 | 10% | 12.5% |
| 5 | 15% | 15% |

Core names with a market cap above $150bn get a 5% asset shock.

```
Global  = min(0, Σ core P&L) + Σ over non-core countries of min(0, country P&L)
Country = −SRSS over countries of the worse incremental country move
Asset   = −SRSS over assets of the worse incremental asset move
Macro   = worst over global shocks (and vol variants) of Global + Country + Asset
```

Core countries are charged for both directions. In non-core countries only
losses count, and the dispersion moves in the direction of the global shock.

**2. Sector (global + sector + asset).** This is the same tree, with GICS
industry groups (split core / non-core) in place of countries. The sector
dispersion is 5% and the asset dispersion is 10%, or 0% for core names above
$150bn. The global shocks are {−15, −10, −5, 0, +5%} plus a top shock that
interpolates from 7.5% (VIX EMA ≤ 15) to 10% (VIX EMA 30), and a +12.5% shock
when the VIX EMA is above 30.

For options, each spot level is also run with the relative vol shocks of the
methodology tables (low / mid / high, plus unchanged). Each vol shock is capped
at its absolute-point equivalent and scaled to the option's tenor by
`(30/days)^0.4`.

**3. Relative value.** This is the worst of four tests:

* **Spot basis.** Each issuer is shocked alone by ±2.5 / 5 / 7.5%, and the worst
  loss per issuer is summed. When an issuer has several listings (ADR/ORD,
  share classes), a gain on one listing offsets losses on another at only 40%.
  In other words, 60% of the offset is charged.
* **Vol basis.** Implied vols move ±10% (capped at 7.5 vol points) with spot
  unchanged. The worst loss per underlier is summed.
* **Vol surface.** The option-liquidation parallel / term / skew shocks are
  applied, taking the worst of 8 combinations per underlier.
* **Spot basis floor.** Each underlier, before ETF explosion, is shocked up and
  down by 0.15% (group 1), 0.5% (groups 2–3) or 1.25% (groups 4–5). The losses
  are summed with no offset for gains.

**4. Concentration.** Each issuer is shocked alone by its market-cap bucket.
*Single name* is the largest issuer loss. *Seven names* is the sum of the seven
largest losses in the same direction.

| bucket | single core (down / up) | single non-core | seven core | seven non-core |
|---|---|---|---|---|
| < $5m | −100% / +800% | −100% / +800% | −70% / +400% | −100% / +400% |
| $5m–200m | −100% / +400% | −100% / +400% | −55% / +150% | −80% / +150% |
| $200m–500m | −100% / +150% | −100% / +250% | −45% / +60% | −70% / +100% |
| $500m–1bn | −80% / +100% | −100% / +150% | −35% / +45% | −55% / +70% |
| $1bn–5bn | −45% / +60% | −70% / +90% | −30% / +35% | −45% / +55% |
| $5bn–150bn | −40% / +50% | −60% / +75% | −25% / +20% | −40% / +45% |
| > $150bn | −25% / +25% | −25% / +25% | −15% / +15% | −15% / +15% |

Down shocks also raise implied vols for options held directly on the name.
Group-2 countries use $50bn in place of $150bn. Financials above $150bn (above
$50bn in group 2), and non-core names above $150bn, use the $5bn–150bn bucket.

**5. Theta.** The 5-day time decay of the option book (losses only).

### Equity liquidity add-ons

* **Delta liquidation.** For each issuer, *days* = |net exposure| ÷ (ADV ×
  price). The charge is `min(cap, 5% × (days − 1)) × |exposure|` when days > 1,
  with a cap of 100% for longs and 300% for shorts; zero ADV means the full cap.
  For a long, the charge plus the name's loss in the dominant scenario cannot
  exceed its value. OTC names under $5 are held to the greater of that charge
  and `max(price, $2.50) × shares` (shorts) or `50% × value` (longs).
* **Option liquidity.**
  * Bid/ask: the net 90-day-equivalent vega times the class factor, aggregated
    with partial offset.
  * Concentration: the days needed to trade the vega, mapped to a dispersion
    shock on ATM vol.
  * Term structure and skew: aggregated by SRSS across underliers.
* **ETF create/redeem fees.** ETFs listed outside the home market (the United
  States by default) pay 20 bp if liquid and 60 bp if not.

### FX

Each line's delta is attributed to the currency of its asset's primary listing.
The FX requirement is the worst of three tests:

* **Base-currency move.** All foreign currencies move ±*b* together, where *b*
  is 5% for a USD base (10% AUD, 4% EUR, 6% GBP, 5% HKD, 11% JPY, 5% SEK,
  3% SGD).
* **Two-currency move.** Each currency gets its own up/down shock against the
  base (the full table is in `marge/params.py`; currencies not in the table get
  ±25%). Take the sum of the two worst currencies when they appreciate and when
  they depreciate, and keep the worse of the two.
* **Pegged currency.** One peg breaks: ±15% for HKD, DKK, SGD and CNY/CNH, and
  ±30% for AED, BGN, MYR, QAR and SAR. Take the largest single loss.

### Aggregation and add-ons

The asset-class losses (equity and FX computed, others from
`[external_losses]`) are combined as the two largest plus SRSS of the rest.
Positions of an unsupported `type` are charged a flat rate: 100% of value for
longs, and `3 × max(price, $2.50)` per share for shorts.

---

## Configuration reference

Every number lives in `marge/params.py`, and any of them can be overridden in
the TOML config. Use the same table names, and quote keys that are numbers.

```toml
base_currency = "USD"
default_country_group = 5

[market]
vix = 15.0
vix_ema = 15.0
rate = 0.04

[fx_rates]
EUR = 1.08

[country_groups]          # add or override countries
"Puerto Rico" = 1

[external_losses]         # asset classes marge does not model (enter positive amounts)
credit = 250000
rates = 40000

[macro.country_dispersion]
"3" = 0.08

[concentration]
non_core_large_cap_relief = true

[liquidity]
missing_adv = "max"       # charge names without ADV at the full cap (default: ignore, with a warning)
etf_home_country = "United States"

[aggregation]
top_n = 2
```

## Validation

The engine was checked against a full risk report from a production
implementation of this framework, for a long/short portfolio of single stocks,
ETFs and leveraged/inverse ETFs. All inputs were reconstructed from the report.

| component | difference |
|---|---|
| Total requirement | 0.007% |
| Macro: every global scenario, each of global / country / asset | ≤ 0.01% (country 0.2%) |
| Sector: every global scenario | ≤ 0.01% |
| Relative value (spot basis, spot basis floor) | ≤ 0.005% |
| Concentration (single name and seven names) | exact to the dollar |
| Delta liquidation (ADV, zero-ADV and OTC rules) | per-name formulas exact |
| FX (base / two-currency / pegged) | 0.9% / 0.5% / 3.7% |

The FX and macro country differences come from reconstructing a nearly
delta-neutral ETF hedge from rounded report data, not from the method. The
option paths (vol scenarios, theta, vol basis, vol surface, option liquidity)
follow the methodology but could not be checked against the reference, because
it held no options.

Unit tests cover the methodology's worked examples, for instance the two-stock
macro example (−18,680) and the SRSS illustration (1,000 × $100 → $3,162). Run
them with:

```bash
python -m unittest discover -s tests
```

## Assumptions and limitations

* **Data drives the answer.** Accurate ETF holdings, market caps, ADVs, countries
  and sectors matter. A missing market cap is treated conservatively (smallest
  bucket), and a missing ADV is not charged unless `missing_adv = "max"`.
* **Effective deltas.** Production systems derive leveraged-ETF exposure from the
  fund's actual index exposure, which can differ from `leverage × price ×
  quantity` by about 0.1%. For a heavily hedged book (long ETF against inverse
  ETFs) that small difference can move the net exposure. Supply a precise
  `leverage` per position if you have it.
* **VIX inputs.** The group-1 country dispersion at the +10% macro shock uses
  `market.vix`. The sector top shock and the high-volatility scenarios use
  `market.vix_ema`.
* **Options** are priced with Black-Scholes, using a flat rate and the supplied
  implied vol (no surface). The option liquidity, vol-surface and vega
  aggregation formulas follow the methodology text. Where that text is
  ambiguous, `marge` makes a reasonable choice: for example, the option class is
  inferred from market cap when `liq_class` is not given.
* **Not modelled.** Credit, interest rates, commodities, convertibles, crypto,
  VIX products and special add-ons (SPACs, high-risk names, non-marginable
  products) are not modelled. Supply their losses through `[external_losses]`,
  or mark positions with an unsupported `type` to apply the flat rate.
* **Parameters can change.** The defaults reflect the methodology tables plus
  the country-group assignments observed in recent production output. Brokers
  revise these tables, and every one of them can be overridden in the config.
