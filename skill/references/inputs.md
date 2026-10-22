# marge input reference

## Contents

1. [positions.csv](#positionscsv)
2. [securities.csv](#securitiescsv)
3. [baskets.csv](#basketscsv)
4. [config.toml / config.json](#config)
5. [GICS industry groups](#gics-industry-groups)
6. [Country names and groups](#country-names-and-groups)
7. [Sourcing data](#sourcing-data)
8. [Partial ETF holdings](#partial-etf-holdings)

Column names are not case sensitive. `.xlsx` files and pandas DataFrames are
accepted wherever a CSV is.

## positions.csv

| column | needed | notes |
|---|---|---|
| `symbol` | always | Matches `securities.csv`. Options can use any descriptive symbol. |
| `quantity` | always | Signed shares or contracts. Negative means short. |
| `price` | usually | Local price. Falls back to `securities.csv`. For options, the option premium; the theoretical value is used if it is blank. |
| `type` | recommended | `stock`, `etf` or `option`. Other values (`bond`, `future`, `swap`, `crypto`, ...) get the flat-rate add-on. |
| `basket` | ETFs | Holdings id in `baskets.csv`. Defaults to the ETF symbol. Leveraged and inverse ETFs on an index can share the plain ETF's basket. |
| `leverage` | levered ETFs | Daily leverage factor: `3`, `-3`, `2`, `-1`, ... Default 1. For an option on a levered ETF, the ETF's leverage. |
| `currency` | non-base | Trading currency. Falls back to `securities.csv`, then the base currency. |
| `multiplier` | options | Default 100 for options, 1 otherwise. |
| `underlying` | options | Underlying symbol. If it is an ETF with holdings, the option is exploded too. |
| `put_call`, `strike`, `expiry`, `implied_vol` | options | `C`/`P`; `YYYY-MM-DD` or a number of days; vol as a decimal (`0.25`) or percent (`25`). |
| `underlying_price`, `dividend_yield` | optional | Option overrides. |

## securities.csv

One row per single name: names held directly, every ETF constituent, and each
held ETF.

| column | notes |
|---|---|
| `symbol` | Identifier used in positions and baskets. |
| `name` | Display name. |
| `asset_id` | Economic security: map an ADR or secondary listing to its ordinary share (`TSM` → `2330.TW`). Defaults to `symbol`. Macro, sector and FX net at this level. |
| `issuer_id` | Company: all share classes and listings of one issuer (`GOOG` and `GOOGL` → `GOOGL`). Defaults to `asset_id`. Concentration, relative value and liquidity net at this level. |
| `country` | Country of risk. See the names below. |
| `sector` | GICS industry group (level 2). Use `ETF` for ETF rows. |
| `market_cap` | In base currency. Blank for ETFs. A blank on a stock means the smallest concentration bucket. |
| `adv` | 21-day average daily volume in **shares**. |
| `price` | Local price (used for ADV value and options). |
| `currency` | Trading currency of this listing. FX risk is taken from the `asset_id` row's currency, so give the ordinary share row its local currency. |
| `is_etf` | `true` for ETFs. |
| `etf_liquid` | `false` raises the non-home-market ETF fee from 20 bp to 60 bp. |
| `otc` | `true` for pink-sheet / OTC names. Under $5 they get the OTC minimum charge. |
| `liq_class` | Option liquidity class `I1 I2 I3 S0 S1 S2 S3 S4`. Inferred if blank. |
| `country_group` | 1-5 override. |
| `financial` | Override; defaults to true for Banks, Financial Services and Insurance. |
| `leverage` | Default leverage for an ETF symbol. |

The roll-up attributes of an `asset_id` or `issuer_id` (country, market cap,
ADV, currency) come from the row whose `symbol` equals that id. Include that row
even when only the ADR is held. For example, add a `2330.TW` row with
`currency = TWD` and Taiwan ADV.

## baskets.csv

`basket, symbol, weight`. Weight is the fraction of NAV (percentages above 1.5
are divided by 100 automatically). Keep the issuer's weights as published and do
not rescale them to 100%. A warning appears if a basket sums outside 90-110%.

## Config

TOML (`config.toml`) or JSON (`config.json`, the same structure as nested
objects). Common keys:

```toml
base_currency = "USD"
default_country_group = 5
[market]
vix = 18.0        # group-1 country shock at the +10% macro scenario fades in between VIX 15 and 30
vix_ema = 17.5    # sector top shock (7.5% -> 10% between 15 and 30); >30 adds +12.5% scenarios
rate = 0.04       # option pricing
[fx_rates]
EUR = 1.08
[country_groups]
"Puerto Rico" = 1
[external_losses] # positive amounts for asset classes not modelled
credit = 250000
[liquidity]
missing_adv = "max"   # charge names without ADV at the full cap (default: no charge)
```

Every parameter table in the methodology can be overridden; the full tree is
in `scripts/marge/params.py`.

## GICS industry groups

Energy · Materials · Capital Goods · Commercial & Professional Services ·
Transportation · Automobiles & Components · Consumer Durables & Apparel ·
Consumer Services · Consumer Discretionary Distribution & Retail · Consumer
Staples Distribution & Retail · Food, Beverage & Tobacco · Household & Personal
Products · Health Care Equipment & Services · Pharmaceuticals, Biotechnology &
Life Sciences · Banks · Financial Services · Insurance · Software & Services ·
Technology Hardware & Equipment · Semiconductors & Semiconductor Equipment ·
Telecommunication Services · Media & Entertainment · Utilities · Equity Real
Estate Investment Trusts (REITs) · Real Estate Management & Development

Spelling only matters for consistency. Names in the same sector must share the
same string, because the sector scenario nets within each sector.

## Country names and groups

Use these spellings (aliases such as `US`, `UK`, `South Korea`, `Taiwan`,
`Russia` and `UAE` are accepted). Anything unrecognised falls into group 5 and is
flagged by `check`.

| group | countries |
|---|---|
| 1 | United States |
| 2 | United Kingdom; France; Germany; Netherlands; Switzerland; Japan |
| 3 | Canada; Austria; Belgium; Denmark; Finland; Ireland; Italy; Luxembourg; Norway; Spain; Sweden; Australia; New Zealand; Hong Kong; China Offshore; Singapore; `Korea, Republic of`; `Taiwan, Province of China` |
| 4 | Mexico; Brazil; Portugal; Iceland; Croatia; Czech Republic; Poland; Slovenia; China; India; Malaysia; Thailand; Israel; South Africa; Bahrain; Oman |
| 5 | everything else, e.g. Argentina; Chile; Colombia; Peru; Greece; Hungary; Turkey; Indonesia; Philippines; Saudi Arabia; United Arab Emirates; Qatar; Kuwait; Egypt; Bermuda; Cayman Islands; Jersey; Guernsey; Puerto Rico |

Use **country of risk**, not of incorporation. For example, a Bermuda-domiciled
US business is `United States`. Hong Kong-listed mainland companies are
`China Offshore`; A-shares are `China`.

## Sourcing data

* **ETF holdings.** Issuers publish daily holdings files (CSV/XLSX) on each
  fund's web page. Leveraged and inverse ETFs track an index; give them the
  holdings of the matching plain ETF (an S&P 500 basket for a 3x S&P 500 fund,
  and so on).
* **Market cap, sector, country.** Use data the user supplies, then any
  connected data source or web search. Your own knowledge is acceptable for
  large well-known names when nothing else is available; label it as an
  estimate. Precision matters little for mega-caps (everything above $150bn is
  one bucket) but a lot near bucket edges ($5m, $200m, $500m, $1bn, $5bn,
  $150bn).
* **ADV.** Only matters when a net position is large relative to volume (over
  one day of volume). For liquid large caps a rough figure is fine. For small
  caps and OTC names it is worth getting right.
* **Prices and FX.** Use the portfolio's own pricing date. FX rates are quoted
  as one unit of local currency in base currency (for example `JPY = 0.0067`
  for a USD base).

## Partial ETF holdings

If only the top N holdings of a fund are available, the remaining weight would
otherwise vanish as if it were cash, understating exposure. Instead, add the
residual weight `1 - sum(top N)` as about 20 synthetic names in `baskets.csv`
(`<ETF>_R01` ... `<ETF>_R20`, equal weights). Give each a `securities.csv` row
with the fund's country and a sector chosen to roughly match the fund's sector
mix, plus a mid/large market cap such as `50e9`. This keeps the fund's market
exposure and approximates its diversification. Tell the user you did it.

For a quick first pass with no holdings at all, leave the ETF unexploded. It is
then treated as one large-cap name: this is directionally right for an unhedged
long, but overstates relative-value and concentration losses for a book hedged
with single names.
