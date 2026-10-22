"""Liquidity add-ons: delta liquidation, ETF create/redeem fees and options."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .equity import option_class
from .model import Model


def delta_liquidation(model: Model, scenario_pnl: np.ndarray | None = None) -> dict:
    """Charge for net issuer exposure exceeding one day of average volume.

    ``charge = min(cap, rate * (days - 1)) * |exposure|`` for ``days > 1``
    (cap 100% for longs, 300% for shorts). Low-priced OTC names are held to
    the greater of that and a per-share charge. When ``scenario_pnl`` (issuer
    P&L in the dominant stress scenario) is given, the charge plus the stress
    loss of a name may not exceed its capped exposure.
    """
    p = model.params["liquidity"]
    I = model.issuers
    exposure = model.by_issuer(model.l_delta)
    price = I["price"].to_numpy(dtype=float) * I["fx"].to_numpy(dtype=float)
    adv = I["adv"].to_numpy(dtype=float)
    adv_value = adv * price
    with np.errstate(divide="ignore", invalid="ignore"):
        days = np.where(adv_value > 0, np.abs(exposure) / adv_value, np.inf)
    missing = np.isnan(adv_value)
    if missing.any():
        held = missing & (np.abs(exposure) > 0.5)
        if held.any():
            model.warnings.append(f"{int(held.sum())} issuer(s) without ADV/price: liquidity "
                                  f"{'charged at the cap' if p['missing_adv'] == 'max' else 'not charged'}")
        days = np.where(missing, np.inf if p["missing_adv"] == "max" else 0.0, days)
    cap = np.where(exposure >= 0, p["long_cap"], p["short_cap"])
    rate = np.where(days > p["free_days"], np.minimum(cap, p["rate_per_day"] * (days - p["free_days"])), 0.0)
    charge = -rate * np.abs(exposure)
    kind = np.where(rate > 0, "ADV based", "")

    otc = I["otc"].to_numpy(dtype=bool) & (price < p["otc_price_threshold"])
    if otc.any():
        shares = np.abs(exposure) / np.where(price > 0, price, np.nan)
        alt = np.where(exposure < 0, np.maximum(price, p["otc_short_min_price"]) * shares,
                       price * shares * p["otc_long_rate"])
        alt = np.nan_to_num(alt)
        use = otc & (alt > -charge)
        charge = np.where(use, -alt, charge)
        kind = np.where(use, "OTC", kind)

    capped = charge.copy()
    if scenario_pnl is not None:
        # A long cannot lose more than its value: liquidation charge plus the
        # name's loss in the dominant scenario is capped at the exposure.
        allowance = np.maximum(p["long_cap"] * np.abs(exposure) + np.minimum(scenario_pnl, 0.0), 0.0)
        capped = np.where(exposure > 0, -np.minimum(-charge, allowance), charge)
    df = pd.DataFrame({"issuer": I.index, "name": I["name"].to_numpy(), "exposure": exposure,
                       "adv_value": adv_value, "days": days, "charge_type": kind, "charge": charge,
                       "capped_charge": capped})
    df = df[df["capped_charge"] < 0].sort_values("capped_charge").reset_index(drop=True)
    return dict(total=float(capped.sum()), issuers=df)


def etf_fees(model: Model) -> dict:
    """Create/redeem add-on for ETFs listed outside the home market."""
    p = model.params["liquidity"]
    P = model.positions
    S = model.securities
    home = p["etf_home_country"]
    fees = np.zeros(len(P))
    for i, r in P.iterrows():
        if r["kind"] != "etf":
            continue
        if S.at[r["symbol"], "country"] != home:
            liquid = bool(S.at[r["symbol"], "etf_liquid"])
            fees[i] = -abs(r["mv"]) * (p["etf_redemption_liquid"] if liquid else p["etf_redemption_illiquid"])
    df = pd.DataFrame({"symbol": P["symbol"], "fee": fees})
    return dict(total=float(fees.sum()), positions=df[df["fee"] < 0].reset_index(drop=True))


# ---------------------------------------------------------------------------
# Option liquidity: bid/ask + concentration + term structure + skew
# ---------------------------------------------------------------------------

def _omega(x, alpha, beta, cap):
    x = np.asarray(x, dtype=float)
    return np.where(x <= 1.0, alpha * x, alpha * np.minimum(x, cap) ** beta)


def option_liquidity(model: Model) -> dict:
    empty = dict(total=0.0, bid_ask=0.0, concentration=0.0, term=0.0, skew=0.0,
                 underliers=pd.DataFrame())
    if not model.has_options:
        return empty
    p = model.params["option_liquidity"]
    P = model.positions
    o = model.p_is_opt
    idx = np.where(o)[0]
    refs, ref_of = np.unique(P["reference"].to_numpy(dtype=str)[idx], return_inverse=True)
    classes = [option_class(model, r) for r in refs]
    days = np.maximum(model.p_t[idx] * 365.0, 1.0)
    vega = model.position_vega()[idx]                       # $ per vol point
    vega90 = vega * (90.0 / days) ** p["vega_tenor_exponent"]
    vol_pts = model.p_vol[idx] * 100.0
    unit_delta = model.p_delta[idx] / np.where(model.p_units[idx] * model.p_spot[idx] * model.p_lev[idx] == 0,
                                              1.0, model.p_units[idx] * model.p_spot[idx] * model.p_lev[idx])
    call_delta = np.where(model.p_call[idx], unit_delta, unit_delta + 1.0)
    n = len(refs)
    net90 = np.bincount(ref_of, weights=vega90, minlength=n)
    abs_vega = np.bincount(ref_of, weights=np.abs(vega), minlength=n)
    atm = np.bincount(ref_of, weights=np.abs(vega) * vol_pts, minlength=n) / np.where(abs_vega > 0, abs_vega, 1)
    cap = p["days_to_trade_cap"]

    # Bid/ask to neutralise the 90-day vega with ATM options, partial offset.
    factor = np.array([p["bid_ask_factor"][c] for c in classes])
    signed = net90 * factor
    if np.sum(net90 ** 2) > 0:
        eff_n = np.sum(np.abs(net90)) ** 2 / np.sum(net90 ** 2)
        g = 2.0 / np.log(min(eff_n + 6.4, 20.0))
    else:
        g = 1.0
    bid_ask = -(g * np.sum(np.abs(signed)) + (1 - g) * abs(np.sum(signed)))

    # Concentration: days to trade the 90-day vega, dispersion shock to ATM vol.
    # Days to trade: 90-day net vega over the 3-month daily vega threshold.
    thr = np.array([np.interp(0.25, p["vega_threshold_tenors"], p["vega_threshold"][c]) for c in classes])
    x = np.abs(net90) / thr
    conc = np.zeros(n)
    for k, c in enumerate(classes):
        w_rel = _omega(x[k], *p["concentration_rel"][c], cap) * atm[k]
        w_abs = _omega(x[k], *p["concentration_abs"][c], cap)
        shock = min(w_rel, w_abs)
        lo, hi = p["vol_bounds"][c]
        room = (atm[k] - lo) if net90[k] > 0 else (hi - atm[k])
        shock = min(shock, max(room, 0.0))
        conc[k] = -abs(net90[k]) * shock / 2.0
    conc_total = -float(np.sqrt(np.sum(conc ** 2)))

    # Term structure and skew: per expiry days-to-trade.
    exp_key = np.round(days).astype(int)
    term = np.zeros(n)
    skew = np.zeros(n)
    up_t, dn_t, up_s, dn_s = (np.zeros(n) for _ in range(4))
    for k, c in enumerate(classes):
        sel = ref_of == k
        for e in np.unique(exp_key[sel]):
            m = sel & (exp_key == e)
            t_e = e / 365.0
            thr_e = np.interp(t_e, p["vega_threshold_tenors"], p["vega_threshold"][c])
            x_e = abs(vega[m].sum()) / thr_e
            a_r = np.interp(t_e, p["term_tenors"], [a for a, _ in p["term_rel"][c]])
            b_r = np.interp(t_e, p["term_tenors"], [b for _, b in p["term_rel"][c]])
            a_a = np.interp(t_e, p["term_tenors"], [a for a, _ in p["term_abs"][c]])
            b_a = np.interp(t_e, p["term_tenors"], [b for _, b in p["term_abs"][c]])
            rel = float(_omega(x_e, a_r, b_r, cap)) * vol_pts[m]
            ab = float(_omega(x_e, a_a, b_a, cap)) * np.ones(m.sum())
            shock = np.where(np.abs(rel) < np.abs(ab), rel, ab)
            for sign, acc in ((1, up_t), (-1, dn_t)):
                s = sign * shock
                s = np.where(s > 0, np.minimum(s, vol_pts[m]),
                             -np.minimum(-s, np.maximum(vol_pts[m] - p["term_down_floor_pts"], 0.0)))
                acc[k] += float(np.sum(vega[m] * s))
            sa, sb = p["skew"][c]
            w = float(_omega(x_e, sa, sb, cap))
            sk = atm[k] * (w / 2.0) * np.abs(call_delta[m] - 0.5) * np.sign(call_delta[m] - 0.5)
            up_s[k] += float(np.sum(vega[m] * sk))
            dn_s[k] += float(np.sum(-vega[m] * sk))
        term[k] = min(0.0, up_t[k], dn_t[k])
        skew[k] = min(0.0, up_s[k], dn_s[k])
    term_total = -float(np.sqrt(np.sum(term ** 2)))
    skew_total = -float(np.sqrt(np.sum(skew ** 2)))

    df = pd.DataFrame({"underlier": refs, "class": classes, "net_vega_90d": net90, "atm_vol": atm,
                       "bid_ask": -np.abs(signed), "concentration": conc, "term": term, "skew": skew})
    total = float(bid_ask) + conc_total + term_total + skew_total
    return dict(total=total, bid_ask=float(bid_ask), concentration=conc_total, term=term_total,
                skew=skew_total, underliers=df)
