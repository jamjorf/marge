"""Portfolio model: input loading, ETF explosion and vectorised P&L.

The engine works on *exposure lines*. Every position is turned into one or
more lines ``(position, constituent symbol, weight)``:

* a stock is a single line on itself (weight 1);
* an ETF with holdings in the basket file is exploded into one line per
  constituent, weighted by the constituent's share of NAV (leveraged and
  inverse ETFs use the same basket, scaled by their leverage factor);
* an option is a line on its underlying (and is exploded the same way when the
  underlying is an ETF with holdings).

Lines are rolled up to *assets* (``asset_id``: one economic security, e.g. an
ADR and its ordinary share) and *issuers* (``issuer_id``: every security of
one company, e.g. both share classes). Constituent attributes come from the
security master.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .params import COUNTRY_ALIASES, FINANCIAL_SECTORS
from .pricing import bs_delta, bs_price, bs_vega

# Column aliases accepted in the input files (lower-case).
POSITION_COLUMNS = {
    "symbol": ["symbol", "ticker", "ric", "id", "asset symbol"],
    "quantity": ["quantity", "qty", "shares", "position", "contracts"],
    "price": ["price", "closing price", "last", "close"],
    "type": ["type", "security type", "kind", "instrument"],
    "underlying": ["underlying", "underlyer", "underlying symbol", "underlyer symbol"],
    "basket": ["basket", "index", "reference", "holdings"],
    "leverage": ["leverage", "leverage factor", "lev"],
    "currency": ["currency", "ccy", "denominated"],
    "multiplier": ["multiplier", "contract size", "mult"],
    "put_call": ["put_call", "put/call", "pc", "option type", "right"],
    "strike": ["strike", "strike price"],
    "expiry": ["expiry", "expiration", "expiration date", "maturity"],
    "implied_vol": ["implied_vol", "implied vol", "vol", "iv", "volatility"],
    "dividend_yield": ["dividend_yield", "div_yield", "dividend yield"],
    "underlying_price": ["underlying_price", "underlying spot", "spot"],
    "name": ["name", "description"],
}

SECURITY_COLUMNS = {
    "symbol": ["symbol", "ticker", "ric", "id"],
    "name": ["name", "description"],
    "asset_id": ["asset_id", "asset", "primary", "adr_parent", "adr parent", "parent"],
    "issuer_id": ["issuer_id", "issuer", "company", "entity"],
    "country": ["country", "country of risk", "risk country"],
    "country_group": ["country_group", "group"],
    "sector": ["sector", "gics", "industry group", "gics industry group"],
    "market_cap": ["market_cap", "mktcap", "market cap", "mcap"],
    "adv": ["adv", "avg daily volume", "average daily volume", "adv_shares"],
    "price": ["price", "last", "close", "local price"],
    "currency": ["currency", "ccy", "denominated"],
    "is_etf": ["is_etf", "etf"],
    "etf_liquid": ["etf_liquid", "liquid"],
    "otc": ["otc", "pink_sheet", "pinksheet"],
    "liq_class": ["liq_class", "liquidity_class", "option_class"],
    "leverage": ["leverage", "leverage factor"],
    "financial": ["financial", "is_financial"],
}

BASKET_COLUMNS = {
    "basket": ["basket", "etf", "fund", "index"],
    "symbol": ["symbol", "constituent", "ticker", "holding"],
    "weight": ["weight", "pct", "weight_pct", "percent"],
}

LINEAR_TYPES = {"stock", "etf", "equity", "adr", "fund", "etp", "etn"}
OPTION_TYPES = {"option", "call", "put", "opt"}


class InputError(ValueError):
    """Raised for malformed or inconsistent input files."""


def _standardise(df: pd.DataFrame, spec: dict, required: list, what: str) -> pd.DataFrame:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    for target, aliases in spec.items():
        for alias in aliases:
            if alias in lookup:
                out[target] = df[lookup[alias]]
                break
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise InputError(f"{what}: missing required column(s) {missing}; got {list(df.columns)}")
    return out


def _to_bool(value, default: bool) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "t"}
    return bool(value)


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or (
        isinstance(value, str) and value.strip() == "")


def _read_table(source) -> pd.DataFrame:
    if source is None:
        return pd.DataFrame()
    if isinstance(source, pd.DataFrame):
        return source.copy()
    return pd.read_csv(source, keep_default_na=True)


def normalize_country(name) -> str:
    if name is None or (isinstance(name, float) and math.isnan(name)):
        return "Unknown"
    text = str(name).strip()
    return COUNTRY_ALIASES.get(text.lower(), text) if text else "Unknown"


def _parse_expiry(value, as_of: dt.date) -> float:
    """Years to expiry from a date string, or a number of days."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise InputError("option without expiry")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return max(float(value), 0.0) / 365.0
    date = pd.Timestamp(str(value)).date()
    return max((date - as_of).days, 0) / 365.0


@dataclass
class Model:
    params: dict
    positions: pd.DataFrame
    lines: pd.DataFrame
    securities: pd.DataFrame
    assets: pd.DataFrame
    issuers: pd.DataFrame
    warnings: list = field(default_factory=list)

    # ---------------------------------------------------------------- arrays
    def __post_init__(self):
        p, ln = self.positions, self.lines
        self.n_lines = len(ln)
        self.l_pos = ln["pos"].to_numpy(dtype=int)
        self.l_w = ln["weight"].to_numpy(dtype=float)
        self.l_asset = ln["asset_code"].to_numpy(dtype=int)
        self.l_issuer = ln["issuer_code"].to_numpy(dtype=int)
        self.l_symbol = ln["symbol_code"].to_numpy(dtype=int)
        self.p_kind = p["kind"].to_numpy()
        self.p_mv = p["mv"].to_numpy(dtype=float)
        self.p_lev = p["leverage"].to_numpy(dtype=float)
        self.p_units = p["units"].to_numpy(dtype=float)
        self.p_spot = p["spot"].to_numpy(dtype=float)
        self.p_strike = p["strike"].to_numpy(dtype=float)
        self.p_t = p["t"].to_numpy(dtype=float)
        self.p_vol = p["vol"].to_numpy(dtype=float)
        self.p_call = p["is_call"].to_numpy(dtype=bool)
        self.p_div = p["div"].to_numpy(dtype=float)
        self.rate = float(self.params["market"]["rate"])
        self.p_is_opt = self.p_kind == "option"
        self.l_is_opt = self.p_is_opt[self.l_pos]
        self.has_options = bool(self.p_is_opt.any())
        self.p_value0 = np.zeros(len(p))
        if self.has_options:
            o = self.p_is_opt
            self.p_value0[o] = bs_price(self.p_spot[o], self.p_strike[o], self.p_t[o], self.p_vol[o],
                                        self.rate, self.p_div[o], self.p_call[o])
        self.p_delta = self._position_delta()
        self.l_delta = self.l_w * self.p_delta[self.l_pos]
        self.n_assets = len(self.assets)
        self.n_issuers = len(self.issuers)

    def _position_delta(self) -> np.ndarray:
        delta = self.p_mv * self.p_lev
        if self.has_options:
            o = self.p_is_opt
            d = bs_delta(self.p_spot[o], self.p_strike[o], self.p_t[o], self.p_vol[o], self.rate,
                         self.p_div[o], self.p_call[o])
            delta[o] = self.p_units[o] * d * self.p_spot[o] * self.p_lev[o]
        return delta

    def position_vega(self) -> np.ndarray:
        """Position vega in base currency per 1 vol point."""
        vega = np.zeros(len(self.positions))
        if self.has_options:
            o = self.p_is_opt
            vega[o] = self.p_units[o] * bs_vega(self.p_spot[o], self.p_strike[o], self.p_t[o],
                                                self.p_vol[o], self.rate, self.p_div[o]) / 100.0
        return vega

    # ------------------------------------------------------------------ P&L
    def position_pnl(self, shock, dvol=None, pos_index=None, dt_years: float = 0.0) -> np.ndarray:
        """P&L of positions for a reference-price return ``shock``.

        ``shock`` and ``dvol`` (absolute change in vol, decimals) broadcast
        against the selected positions. Leveraged products are floored at a
        total loss of their market value.
        """
        idx = np.arange(len(self.positions)) if pos_index is None else np.asarray(pos_index)
        shock = np.broadcast_to(np.asarray(shock, dtype=float), idx.shape)
        ret = np.maximum(self.p_lev[idx] * shock, -1.0)
        pnl = self.p_mv[idx] * ret
        opt = self.p_is_opt[idx]
        if opt.any():
            j = idx[opt]
            vol = self.p_vol[j]
            if dvol is not None:
                dv = np.broadcast_to(np.asarray(dvol, dtype=float), idx.shape)[opt]
                vol = np.maximum(vol + dv, 0.01)
            new = bs_price(self.p_spot[j] * (1.0 + ret[opt]), self.p_strike[j],
                           np.maximum(self.p_t[j] - dt_years, 0.0), vol, self.rate, self.p_div[j],
                           self.p_call[j])
            pnl[opt] = self.p_units[j] * (new - self.p_value0[j])
        return pnl

    def line_pnl(self, shock, dvol_pos=None, mode: str = "systematic") -> np.ndarray:
        """P&L per exposure line.

        ``systematic``: the whole reference basket moves by ``shock`` and the
        position P&L is allocated by weight (index-wide moves, macro/sector).
        ``idiosyncratic``: only the constituent moves, so the reference moves
        by ``weight * shock`` (single-name moves: concentration, RV).
        """
        shock = np.broadcast_to(np.asarray(shock, dtype=float), (self.n_lines,))
        dv = None if dvol_pos is None else np.asarray(dvol_pos, dtype=float)[self.l_pos]
        if mode == "systematic":
            if not self.has_options:
                return self.l_w * self.p_mv[self.l_pos] * np.maximum(self.p_lev[self.l_pos] * shock, -1.0)
            return self.l_w * self.position_pnl(shock, dv, self.l_pos)
        if not self.has_options:
            return self.p_mv[self.l_pos] * np.maximum(self.p_lev[self.l_pos] * self.l_w * shock, -1.0)
        return self.position_pnl(self.l_w * shock, dv, self.l_pos)

    def by_asset(self, values) -> np.ndarray:
        return np.bincount(self.l_asset, weights=values, minlength=self.n_assets)

    def by_issuer(self, values) -> np.ndarray:
        return np.bincount(self.l_issuer, weights=values, minlength=self.n_issuers)

    # ------------------------------------------------------------ vol shocks
    def vol_shift(self, rel_shock, up_factor: float, down_factor: float) -> np.ndarray | None:
        """Per-position absolute vol change for a relative vol shock.

        The smaller of the relative shock (``rel * vol``) and the absolute
        equivalent (``factor * rel`` vol points) is used, scaled to the
        option's tenor by ``(30 / days) ** 0.4``.
        """
        if not self.has_options:
            return None
        rel = np.broadcast_to(np.asarray(rel_shock, dtype=float), self.p_vol.shape)
        factor = np.where(rel >= 0, up_factor, down_factor)
        mag = np.minimum(np.abs(rel) * self.p_vol, np.abs(rel) * factor)
        days = np.maximum(self.p_t * 365.0, 1.0)
        out = np.sign(rel) * mag * (30.0 / days) ** 0.4
        return np.where(self.p_is_opt, out, 0.0)


# ---------------------------------------------------------------------------
# Building the model from input tables
# ---------------------------------------------------------------------------

def _country_group(country: str, groups: dict, default: int) -> int:
    if country in groups:
        return groups[country]
    lower = {k.lower(): v for k, v in groups.items()}
    return lower.get(country.lower(), default)


def build_model(positions, securities=None, baskets=None, params: dict | None = None,
                as_of: dt.date | None = None) -> Model:
    """Create a :class:`Model` from position, security-master and basket tables."""
    from .config import load_params

    params = params or load_params()
    as_of = as_of or dt.date.today()
    base = params["base_currency"]
    warnings: list[str] = []
    fx_missing: set[str] = set()

    def fx_rate(ccy, strict: bool = False) -> float:
        ccy = base if ccy is None or (isinstance(ccy, float) and math.isnan(ccy)) else str(ccy).upper()
        if ccy == base:
            return 1.0
        if ccy in params["fx_rates"]:
            return float(params["fx_rates"][ccy])
        if strict:
            raise InputError(f"no fx rate for {ccy}: add it under [fx_rates] in the config "
                             f"(1 {ccy} in {base})")
        fx_missing.add(ccy)
        return float("nan")

    # ------------------------------------------------------------ securities
    sec_raw = _read_table(securities)
    if len(sec_raw):
        sec = _standardise(sec_raw, SECURITY_COLUMNS, ["symbol"], "securities")
    else:
        sec = pd.DataFrame(columns=["symbol"])
    sec["symbol"] = sec["symbol"].astype(str).str.strip()
    sec = sec.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)

    # --------------------------------------------------------------- baskets
    bk_raw = _read_table(baskets)
    if len(bk_raw):
        bk = _standardise(bk_raw, BASKET_COLUMNS, ["basket", "symbol", "weight"], "baskets")
        bk["basket"] = bk["basket"].astype(str).str.strip()
        bk["symbol"] = bk["symbol"].astype(str).str.strip()
        bk["weight"] = pd.to_numeric(bk["weight"], errors="coerce").fillna(0.0)
        if bk["weight"].abs().max() > 1.5:  # given in percent
            bk["weight"] = bk["weight"] / 100.0
        bk = bk.groupby(["basket", "symbol"], as_index=False, sort=False)["weight"].sum()
        for name, total in bk.groupby("basket")["weight"].sum().items():
            if not 0.9 <= total <= 1.1:
                warnings.append(f"basket {name}: weights sum to {total:.3f}")
    else:
        bk = pd.DataFrame(columns=["basket", "symbol", "weight"])
    basket_map = {b: g[["symbol", "weight"]].to_numpy() for b, g in bk.groupby("basket", sort=False)}

    sec_records = sec.to_dict("index")

    def sec_value(symbol, column, default=None):
        rec = sec_records.get(symbol)
        if rec is not None:
            value = rec.get(column)
            if not _missing(value):
                return value
        return default

    # -------------------------------------------------------------- positions
    pos_raw = _read_table(positions)
    pos = _standardise(pos_raw, POSITION_COLUMNS, ["symbol", "quantity"], "positions").reset_index(drop=True)
    pos["symbol"] = pos["symbol"].astype(str).str.strip()
    pos["quantity"] = pd.to_numeric(pos["quantity"], errors="coerce").fillna(0.0)

    rows = []
    for i, r in pos.iterrows():
        sym = r["symbol"]
        raw_type = str(r.get("type", "") or "").strip().lower()
        if raw_type in ("", "nan"):
            if not pd.isna(r.get("put_call", np.nan)) and not pd.isna(r.get("strike", np.nan)):
                raw_type = "option"
            elif sym in basket_map or _to_bool(sec_value(sym, "is_etf"), False):
                raw_type = "etf"
            else:
                raw_type = "stock"
        if raw_type in OPTION_TYPES:
            kind = "option"
        elif raw_type in LINEAR_TYPES:
            kind = "etf" if raw_type in {"etf", "fund", "etp", "etn"} else "stock"
        else:
            kind = "flat"
        ccy = r.get("currency")
        if ccy is None or pd.isna(ccy):
            ccy = sec_value(sym if kind != "option" else str(r.get("underlying", sym)), "currency", base)
        ccy = str(ccy).upper()
        fx = fx_rate(ccy, strict=True)
        qty = float(r["quantity"])
        price = r.get("price")
        price = float(price) if price is not None and not pd.isna(price) else None
        rec = dict(pos=i, symbol=sym, kind=kind, quantity=qty, currency=ccy, fx=fx, name=r.get("name"),
                   leverage=1.0, units=0.0, spot=np.nan, strike=np.nan, t=0.0, vol=np.nan,
                   is_call=False, div=0.0, mv=0.0, reference=sym, basket=None)
        lev = r.get("leverage")
        if kind == "option":
            und = r.get("underlying")
            if und is None or pd.isna(und):
                raise InputError(f"option {sym}: missing underlying")
            und = str(und).strip()
            rec["reference"] = und
            mult = r.get("multiplier")
            mult = float(mult) if mult is not None and not pd.isna(mult) else 100.0
            spot = r.get("underlying_price")
            spot = float(spot) if spot is not None and not pd.isna(spot) else sec_value(und, "price")
            if spot is None:
                raise InputError(f"option {sym}: no underlying price (positions.underlying_price or securities.price)")
            vol = r.get("implied_vol")
            if vol is None or pd.isna(vol):
                raise InputError(f"option {sym}: missing implied_vol")
            vol = float(vol)
            vol = vol / 100.0 if vol > 3.0 else vol
            pc = str(r.get("put_call", "")).strip().upper()[:1]
            if pc not in ("C", "P"):
                raise InputError(f"option {sym}: put_call must be C or P")
            div = r.get("dividend_yield")
            und_lev = lev if lev is not None and not pd.isna(lev) else sec_value(und, "leverage", 1.0)
            rec.update(units=qty * mult * fx, spot=float(spot), strike=float(r["strike"]),
                       t=_parse_expiry(r.get("expiry"), as_of), vol=vol, is_call=pc == "C",
                       div=float(div) if div is not None and not pd.isna(div) else 0.0,
                       leverage=float(und_lev))
            theo = float(bs_price(rec["spot"], rec["strike"], rec["t"], vol, params["market"]["rate"],
                                  rec["div"], rec["is_call"]))
            rec["mv"] = qty * mult * fx * (price if price is not None else theo)
            rec["basket"] = und if und in basket_map else None
        else:
            if price is None:
                price = sec_value(sym, "price")
                if price is None:
                    raise InputError(f"position {sym}: no price (positions.price or securities.price)")
                price = float(price)
            mult = r.get("multiplier")
            mult = float(mult) if mult is not None and not pd.isna(mult) else 1.0
            rec["mv"] = qty * price * mult * fx
            rec["spot"] = price
            lev = lev if lev is not None and not pd.isna(lev) else sec_value(sym, "leverage", 1.0)
            rec["leverage"] = float(lev)
            if kind == "etf":
                b = r.get("basket")
                b = str(b).strip() if b is not None and not pd.isna(b) else sym
                if b in basket_map:
                    rec["basket"] = b
                else:
                    warnings.append(f"ETF {sym}: no holdings for basket '{b}', treated as a single asset")
        rows.append(rec)
    P = pd.DataFrame(rows)
    if P.empty:
        raise InputError("positions: no rows")

    # ------------------------------------------------------------------ lines
    line_rows = []
    for rec in rows:
        if rec["kind"] == "flat":
            continue
        if rec["basket"] is not None:
            for sym, w in basket_map[rec["basket"]]:
                line_rows.append((rec["pos"], sym, float(w)))
        else:
            line_rows.append((rec["pos"], rec["reference"], 1.0))
    L = pd.DataFrame(line_rows, columns=["pos", "symbol", "weight"])
    if L.empty:
        L = pd.DataFrame({"pos": pd.Series(dtype=int), "symbol": pd.Series(dtype=str),
                          "weight": pd.Series(dtype=float)})

    # Security attributes for every symbol that appears in lines or positions.
    groups = params["country_groups"]
    default_group = int(params["default_country_group"])
    default_etf_country = params.get("default_etf_country", "United States")
    symbols = list(dict.fromkeys(list(L["symbol"]) + list(P["symbol"]) + list(P["reference"])))
    missing_sec = [s for s in L["symbol"].unique() if s not in sec.index]
    if missing_sec:
        warnings.append(f"{len(missing_sec)} symbol(s) missing from the security master "
                        f"(defaults applied): {', '.join(missing_sec[:10])}{' ...' if len(missing_sec) > 10 else ''}")
    # Primary lines of assets/issuers carry the attributes of the roll-up even
    # when they are not held themselves (e.g. the ordinary share of an ADR).
    for s in list(symbols):
        for key in ("asset_id", "issuer_id"):
            primary = sec_value(s, key)
            if primary is not None and str(primary) in sec.index and str(primary) not in symbols:
                symbols.append(str(primary))
    srows = []
    etf_syms = set(P.loc[P["kind"] == "etf", "symbol"]) | set(basket_map)
    for s in symbols:
        is_etf = _to_bool(sec_value(s, "is_etf"), s in etf_syms)
        country = normalize_country(sec_value(s, "country", default_etf_country if is_etf else None))
        grp = sec_value(s, "country_group")
        grp = int(grp) if grp is not None else _country_group(country, groups, default_group)
        sector = str(sec_value(s, "sector", "ETF" if is_etf else "Unknown")).strip()
        fin = sec_value(s, "financial")
        fin = _to_bool(fin, sector in FINANCIAL_SECTORS)
        mcap = sec_value(s, "market_cap")
        ccy = str(sec_value(s, "currency", base)).upper()
        asset_id = str(sec_value(s, "asset_id", s))
        srows.append(dict(
            symbol=s, name=sec_value(s, "name", s), asset_id=asset_id,
            issuer_id=str(sec_value(s, "issuer_id", asset_id)), country=country, group=grp,
            core=grp <= 3, sector=sector, financial=fin,
            market_cap=float(mcap) if mcap is not None else np.nan,
            adv=float(sec_value(s, "adv")) if sec_value(s, "adv") is not None else np.nan,
            price=float(sec_value(s, "price")) if sec_value(s, "price") is not None else np.nan,
            currency=ccy, fx=fx_rate(ccy), is_etf=is_etf,
            etf_liquid=_to_bool(sec_value(s, "etf_liquid"), True),
            otc=_to_bool(sec_value(s, "otc"), False),
            liq_class=sec_value(s, "liq_class"),
        ))
    S = pd.DataFrame(srows).set_index("symbol", drop=False)

    # Asset / issuer tables use the attributes of their primary line when it
    # exists in the security master, else of their first constituent line.
    s_records = {r["symbol"]: r for r in srows}

    def rollup(key: str) -> pd.DataFrame:
        first: dict = {}
        for sym in L["symbol"]:
            first.setdefault(s_records[sym][key], sym)
        recs = [dict(s_records[k] if k in s_records else s_records[sym], id=k) for k, sym in first.items()]
        return pd.DataFrame(recs).set_index("id", drop=False) if recs else pd.DataFrame(columns=["id"])

    A = rollup("asset_id")
    I = rollup("issuer_id")
    if len(L):
        L["asset_id"] = L["symbol"].map(S["asset_id"]).to_numpy()
        L["issuer_id"] = L["symbol"].map(S["issuer_id"]).to_numpy()
        L["asset_code"] = pd.Index(A.index).get_indexer(L["asset_id"])
        L["issuer_code"] = pd.Index(I.index).get_indexer(L["issuer_id"])
        L["symbol_code"] = pd.factorize(L["symbol"])[0]
    else:
        for c in ("asset_id", "issuer_id"):
            L[c] = pd.Series(dtype=str)
        for c in ("asset_code", "issuer_code", "symbol_code"):
            L[c] = pd.Series(dtype=int)

    if fx_missing:
        warnings.append(f"no fx rate for {sorted(fx_missing)}: local prices in those currencies are "
                        f"ignored (no liquidity charge); set [fx_rates] in the config")
    # Reference (pre-explosion) attributes for each position.
    P["ref_group"] = [int(S.at[r, "group"]) for r in P["reference"]]
    P["ref_country"] = [S.at[r, "country"] for r in P["reference"]]
    return Model(params=params, positions=P, lines=L, securities=S, assets=A, issuers=I,
                 warnings=warnings)
