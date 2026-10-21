"""Equity stress components: macro, sector, relative value, concentration, theta."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .model import Model
from .tree import TreeResult, fade, run_tree

def _fmt_shock(g: float) -> str:
    return f"{g * 100:+.1f}%".replace(".0%", "%")


def _scenario_rows(results: list[tuple[str, TreeResult]]) -> list[dict]:
    return [dict(scenario=name, shock=r.shock, global_loss=r.global_loss, dispersion_loss=r.bucket_loss,
                 asset_loss=r.asset_loss, total=r.total) for name, r in results]


def _variant_dvols(model: Model, rel_by_variant: dict, up: float, down: float) -> list[tuple[str, object]]:
    """Vol variants to evaluate for one spot shock (just one if no options)."""
    if not model.has_options:
        return [("Md", None)]
    out, seen = [("Unch", None)], set()
    for name in ("Low", "Md", "High"):
        rel = rel_by_variant[name]
        key = tuple(np.round(rel, 12))
        if not np.any(rel) or key in seen:
            continue
        seen.add(key)
        out.append((name, model.vol_shift(rel, up, down)))
    return out


# ---------------------------------------------------------------------------
# Macro: global + country + asset
# ---------------------------------------------------------------------------

def macro(model: Model) -> dict:
    p = model.params["macro"]
    mkt = model.params["market"]
    A = model.assets
    countries, a_bucket = np.unique(A["country"].to_numpy(dtype=str), return_inverse=True)
    grp_of = A.groupby("country")["group"].first()
    b_group = np.array([int(grp_of[c]) for c in countries])
    b_core = b_group <= 3
    mcap = A["market_cap"].to_numpy(dtype=float)
    a_group = A["group"].to_numpy(dtype=int)
    a_disp = np.array([p["asset_dispersion"][g] for g in a_group], dtype=float)
    large = (a_group <= 3) & (np.nan_to_num(mcap) > p["large_cap_threshold"])
    a_disp[large] = p["large_cap_asset_dispersion"]

    shocks = list(p["global_shocks"])
    if mkt["vix_ema"] > p["extra_top_vix"]:
        shocks.append(p["extra_top_shock"])
    g1_fade = fade(mkt["vix"], *p["group1_top_country_vix"])
    pos_group = model.positions["ref_group"].to_numpy(dtype=int)

    results = []
    for g in shocks:
        b_disp = np.array([p["country_dispersion"][x] for x in b_group], dtype=float)
        if g >= 0.10 - 1e-12:
            b_disp[b_group == 1] *= g1_fade
        key = min(p["vol_shocks"][1], key=lambda k: abs(k - g))
        rel = {}
        for i, name in enumerate(("Low", "Md", "High")):
            rel[name] = np.array([p["vol_shocks"][grp][key][i] for grp in pos_group], dtype=float)
        if abs(g + 0.15) < 1e-9 and mkt["vix_ema"] <= p["low_vol_at_crash_vix"]:
            rel["Low"] = np.zeros(len(pos_group))
        for vname, dvol in _variant_dvols(model, rel, p["vol_map_up_factor"], p["vol_map_down_factor"]):
            r = run_tree(model, g, dvol, a_bucket, b_core, b_disp, a_disp)
            results.append((f"{_fmt_shock(g)} Vol {vname}", r))
    return _tree_summary(model, results, countries, a_bucket, b_group, "country")


# ---------------------------------------------------------------------------
# Sector: global + sector + asset
# ---------------------------------------------------------------------------

def sector(model: Model) -> dict:
    p = model.params["sector"]
    mkt = model.params["market"]
    A = model.assets
    core = A["core"].to_numpy(dtype=bool)
    keys = np.array([f"{s} {'Core' if c else 'Non Core'}" for s, c in zip(A["sector"], core)])
    sectors, a_bucket = np.unique(keys, return_inverse=True)
    b_core = np.array([not k.endswith(" Non Core") for k in sectors])
    b_disp = np.full(len(sectors), p["sector_dispersion"], dtype=float)
    mcap = A["market_cap"].to_numpy(dtype=float)
    a_disp = np.full(len(A), p["asset_dispersion"], dtype=float)
    a_disp[core & (np.nan_to_num(mcap) > p["large_cap_threshold"])] = p["large_cap_asset_dispersion"]

    lo, hi = p["top_shock"]
    top = lo + (hi - lo) * fade(mkt["vix_ema"], *p["top_shock_vix"])
    shocks = [(g, g) for g in p["global_shocks"]] + [(top, "top")]
    if mkt["vix_ema"] > p["extra_top_vix"]:
        shocks.append((p["extra_top_shock"], "top"))
    n_pos = len(model.positions)
    results = []
    for g, key in shocks:
        table = p["vol_shocks"][key] if key == "top" else p["vol_shocks"][min(
            (k for k in p["vol_shocks"] if k != "top"), key=lambda k: abs(k - g))]
        if g <= -0.10 + 1e-12 and mkt["vix_ema"] > p["extra_top_vix"]:
            table = p["crash_vol_shocks_high_vix"]
        rel = {name: np.full(n_pos, table[i]) for i, name in enumerate(("Low", "Md", "High"))}
        for vname, dvol in _variant_dvols(model, rel, p["vol_map_up_factor"], p["vol_map_down_factor"]):
            r = run_tree(model, g, dvol, a_bucket, b_core, b_disp, a_disp)
            results.append((f"{_fmt_shock(g)} Vol {vname}", r))
    return _tree_summary(model, results, sectors, a_bucket, None, "sector")


def _tree_summary(model: Model, results, buckets, a_bucket, b_group, label: str) -> dict:
    name, worst = min(results, key=lambda x: x[1].total)
    A = model.assets
    bdf = pd.DataFrame({
        label: buckets,
        "global_pnl": worst.bucket_global,
        "up_pnl": worst.bucket_up,
        "down_pnl": worst.bucket_down,
        "direction": np.where(worst.bucket_dir == 1, "Up", "Down"),
        "dispersion_loss": worst.bucket_disp,
    })
    if b_group is not None:
        bdf.insert(1, "group", b_group)
    adf = pd.DataFrame({"asset": A.index, "name": A["name"].to_numpy(), label: buckets[a_bucket],
                        "global_pnl": worst.asset_global, "asset_loss": worst.asset_disp})
    return dict(
        total=worst.total, worst_scenario=name, global_loss=worst.global_loss,
        dispersion_loss=worst.bucket_loss, asset_loss=worst.asset_loss,
        scenarios=_scenario_rows(results),
        buckets=bdf.sort_values("dispersion_loss").reset_index(drop=True),
        assets=adf.sort_values("asset_loss").reset_index(drop=True),
    )


# ---------------------------------------------------------------------------
# Relative value
# ---------------------------------------------------------------------------

def _listing_adjusted(values: np.ndarray, issuer_of_pair: np.ndarray, multi: np.ndarray,
                      n_issuers: int, credit: float) -> np.ndarray:
    """Issuer P&L where gains on one listing only partly offset another's losses."""
    loss = np.bincount(issuer_of_pair, weights=np.minimum(values, 0.0), minlength=n_issuers)
    gain = np.bincount(issuer_of_pair, weights=np.maximum(values, 0.0), minlength=n_issuers)
    net = loss + gain
    return np.where(multi, loss + credit * gain, net)


def relative_value(model: Model) -> dict:
    p = model.params["relative_value"]
    P = model.positions
    credit = p["listing_gain_credit"]

    # (A) Spot basis: each issuer shocked on its own, listings charged separately.
    pair_codes, pair_index = np.unique(np.stack([model.l_issuer, model.l_symbol], axis=1), axis=0,
                                       return_inverse=True)
    pair_index = np.asarray(pair_index).ravel()
    pair_issuer = pair_codes[:, 0]
    multi = np.bincount(pair_issuer, minlength=model.n_issuers) > 1
    per_shock = []
    for s in p["spot_shocks"]:
        lp = model.line_pnl(s, None, mode="idiosyncratic")
        pair_pnl = np.bincount(pair_index, weights=lp, minlength=len(pair_codes))
        per_shock.append(_listing_adjusted(pair_pnl, pair_issuer, multi, model.n_issuers, credit))
    grid = np.vstack(per_shock) if per_shock else np.zeros((1, model.n_issuers))
    spot_issuer = np.minimum(grid.min(axis=0), 0.0)
    spot_driver = np.array(p["spot_shocks"])[grid.argmin(axis=0)] if per_shock else np.zeros(model.n_issuers)
    spot_total = float(spot_issuer.sum())

    # References (pre-explosion underliers) for the option and floor tests.
    refs, ref_index = np.unique(P["reference"].to_numpy(dtype=str), return_inverse=True)
    linear = P["kind"].isin(["stock", "etf"]).to_numpy()
    tradable = linear | model.p_is_opt

    # (B) Vol basis: implied vols up/down with spot unchanged, per underlier.
    vol_total = 0.0
    if model.has_options:
        o = model.p_is_opt
        mag = np.minimum(model.p_vol * p["vol_shock_rel"], p["vol_shock_cap_pts"] / 100.0)
        up = np.where(o, model.position_pnl(0.0, mag), 0.0)
        dn = np.where(o, model.position_pnl(0.0, -mag), 0.0)
        ref_issuer = model.securities.loc[refs, "issuer_id"].to_numpy(dtype=str)
        iss, iss_index = np.unique(ref_issuer, return_inverse=True)
        ref_multi = np.bincount(iss_index, minlength=len(iss)) > 1
        res = []
        for v in (up, dn):
            per_ref = np.bincount(ref_index, weights=v, minlength=len(refs))
            res.append(_listing_adjusted(per_ref, iss_index, ref_multi, len(iss), credit))
        vol_total = float(np.minimum(np.minimum(res[0], res[1]), 0.0).sum())

    # (C) Vol surface: parallel / term / skew liquidation shocks, worst of 8.
    surface_total = vol_surface(model, refs, ref_index) if model.has_options else 0.0

    # (D) Spot basis floor: small up/down move per underlier before explosion.
    floor_pct = np.array([p["spot_basis_floor"][g] for g in P["ref_group"]], dtype=float)
    up = np.where(tradable, model.position_pnl(floor_pct), 0.0)
    dn = np.where(tradable, model.position_pnl(-floor_pct), 0.0)
    ru = np.bincount(ref_index, weights=up, minlength=len(refs))
    rd = np.bincount(ref_index, weights=dn, minlength=len(refs))
    floor_ref = np.minimum(np.minimum(ru, rd), 0.0)
    floor_total = float(floor_ref.sum())

    parts = {"spot_basis": spot_total, "vol_basis": vol_total, "vol_surface": surface_total,
             "spot_basis_floor": floor_total}
    driver = min(parts, key=parts.get)
    I = model.issuers
    issuers = pd.DataFrame({"issuer": I.index, "name": I["name"].to_numpy(), "spot_rv": spot_issuer,
                            "driver_shock": spot_driver}).sort_values("spot_rv").reset_index(drop=True)
    floor = pd.DataFrame({"reference": refs, "loss": floor_ref}).sort_values("loss").reset_index(drop=True)
    return dict(total=parts[driver], driver=driver, **parts, issuers=issuers, floor=floor)


def _interp(x: float, xs, ys) -> float:
    return float(np.interp(x, xs, ys))


def option_class(model: Model, symbol: str) -> str:
    """Liquidity class (I1-I3, S0-S4) of an option underlier."""
    S = model.securities
    cls = S.at[symbol, "liq_class"] if symbol in S.index else None
    if isinstance(cls, str) and cls.strip():
        return cls.strip().upper()
    root = symbol.split(".")[0].lstrip(".").upper()
    p = model.params["option_liquidity"]
    if root in p["index_i1"]:
        return "I1"
    if root in p["index_i2"]:
        return "I2"
    if symbol in S.index and bool(S.at[symbol, "is_etf"]):
        return "I3"
    mcap = float(S.at[symbol, "market_cap"]) if symbol in S.index else float("nan")
    if np.isnan(mcap):
        return "S4"
    for bound, cls in ((1e12, "S0"), (100e9, "S1"), (15e9, "S2"), (2e9, "S3")):
        if mcap >= bound:
            return cls
    return "S4"


def vol_surface(model: Model, refs: np.ndarray, ref_index: np.ndarray) -> float:
    p = model.params["vol_surface"]
    o = model.p_is_opt
    days = np.maximum(model.p_t * 365.0, 1.0)
    vol = model.p_vol
    classes = np.array([option_class(model, r) for r in refs])[ref_index]
    par = np.zeros(len(vol))
    term = np.zeros(len(vol))
    skew = np.zeros(len(vol))
    delta = model.p_delta / np.where(model.p_units * model.p_spot * model.p_lev == 0, 1.0,
                                     model.p_units * model.p_spot * model.p_lev)
    call_delta = np.where(model.p_call, delta, delta + 1.0)
    for i in np.where(o)[0]:
        c = classes[i]
        rel, ab = p["atm_3m"][c]
        par[i] = min(rel * vol[i], ab / 100.0) * (90.0 / days[i]) ** 0.4
        t_rel = _interp(model.p_t[i], p["term_tenors"], p["term_rel"][c])
        t_abs = _interp(model.p_t[i], p["term_tenors"], p["term_abs"][c]) / 100.0
        term[i] = t_rel * vol[i] if abs(t_rel * vol[i]) < abs(t_abs) else t_abs
        s_rel, s_abs = p["skew"][c]
        skew[i] = min(s_rel * vol[i], s_abs / 100.0) * 2.0 * (call_delta[i] - 0.5)
    worst = np.zeros(len(refs))
    for a in (1, -1):
        for b in (1, -1):
            for c in (1, -1):
                pnl = np.where(o, model.position_pnl(0.0, a * par + b * term + c * skew), 0.0)
                worst = np.minimum(worst, np.bincount(ref_index, weights=pnl, minlength=len(refs)))
    return float(worst.sum())


# ---------------------------------------------------------------------------
# Concentration: single name and seven names
# ---------------------------------------------------------------------------

BUCKET_LABELS = ["<5m", "5m-200m", "200m-500m", "500m-1b", "1b-5b", "5b-150b", ">150b"]
BUCKET_LABELS_G2 = ["<5m", "5m-200m", "200m-500m", "500m-1b", "1b-5b", "5b-50b", ">50b"]


def concentration_buckets(model: Model) -> tuple[np.ndarray, list[str]]:
    p = model.params["concentration"]
    I = model.issuers
    mcap = I["market_cap"].to_numpy(dtype=float)
    grp = I["group"].to_numpy(dtype=int)
    fin = I["financial"].to_numpy(dtype=bool)
    core = I["core"].to_numpy(dtype=bool)
    etf = I["is_etf"].to_numpy(dtype=bool)
    buckets = np.zeros(len(I), dtype=int)
    missing = []
    for i in range(len(I)):
        bounds = p["group2_bucket_bounds"] if grp[i] == 2 else p["bucket_bounds"]
        if np.isnan(mcap[i]):
            buckets[i] = len(bounds) if etf[i] else 0
            if not etf[i]:
                missing.append(I.index[i])
            continue
        b = int(np.searchsorted(bounds, mcap[i], side="right"))
        if b == len(bounds):
            fin_cut = p["financial_cap_threshold_group2"] if grp[i] == 2 else p["financial_cap_threshold"]
            if fin[i] and mcap[i] > fin_cut:
                b -= 1
            elif not core[i] and not p["non_core_large_cap_relief"]:
                b -= 1
        buckets[i] = b
    if missing:
        model.warnings.append(f"{len(missing)} issuer(s) without market cap use the smallest "
                              f"concentration bucket: {', '.join(missing[:10])}"
                              f"{' ...' if len(missing) > 10 else ''}")
    labels = [(BUCKET_LABELS_G2 if g == 2 else BUCKET_LABELS)[b] for g, b in zip(grp, buckets)]
    return buckets, labels


def concentration(model: Model) -> dict:
    p = model.params["concentration"]
    I = model.issuers
    buckets, labels = concentration_buckets(model)
    core = I["core"].to_numpy(dtype=bool)
    exploded = model.positions["basket"].notna().to_numpy()

    def shocks(table: dict):
        arr = np.array([table["core" if c else "non_core"][b] for c, b in zip(core, buckets)], dtype=float)
        return arr[:, 0], arr[:, 1], arr[:, 2]

    def issuer_pnl(spot_by_issuer, vol_by_issuer=None):
        dvol = None
        if model.has_options and vol_by_issuer is not None:
            # Vol shocks apply to options held directly on the shocked name.
            ref_issuer = model.issuers.index.get_indexer(
                model.securities.loc[model.positions["reference"], "issuer_id"])
            rel = np.where(model.p_is_opt & ~exploded & (ref_issuer >= 0),
                           vol_by_issuer[np.maximum(ref_issuer, 0)], 0.0)
            dvol = rel * model.p_vol
        return model.by_issuer(model.line_pnl(spot_by_issuer[model.l_issuer], dvol, mode="idiosyncratic"))

    out = {}
    for kind in ("single", "seven"):
        down, vol, up = shocks(p[kind])
        pu = issuer_pnl(up)
        pdn = issuer_pnl(down, vol)
        out[kind] = (pu, pdn, up, down, vol)

    pu, pdn, up, down, vol = out["single"]
    single_loss = np.minimum(np.minimum(pu, pdn), 0.0)
    i_single = int(np.argmin(single_loss)) if len(single_loss) else 0
    single_total = float(single_loss.min()) if len(single_loss) else 0.0

    pu7, pd7, up7, down7, vol7 = out["seven"]
    n = int(p["seven_name_count"])
    lu, ld = np.minimum(pu7, 0.0), np.minimum(pd7, 0.0)
    top_up, top_dn = np.argsort(lu)[:n], np.argsort(ld)[:n]
    seven_up, seven_dn = float(lu[top_up].sum()), float(ld[top_dn].sum())
    if seven_up <= seven_dn:
        seven_total, top, direction, sh, pnl7 = seven_up, top_up, "Up", up7, lu
    else:
        seven_total, top, direction, sh, pnl7 = seven_dn, top_dn, "Down", down7, ld

    def describe(shock, vol_shock=None):
        text = f"Spot {shock * 100:+.0f}%"
        if vol_shock is not None:
            text += f" Vol {vol_shock * 100:+.0f}%"
        return text

    single_up = pu[i_single] <= pdn[i_single] if len(pu) else True
    single = dict(total=single_total, issuer=I.index[i_single] if len(I) else None,
                  name=I["name"].iloc[i_single] if len(I) else None,
                  scenario=describe(up[i_single]) if single_up else describe(down[i_single], vol[i_single]),
                  bucket=labels[i_single] if len(I) else None)
    seven_rows = pd.DataFrame({
        "issuer": I.index[top], "name": I["name"].to_numpy()[top],
        "scenario": [describe(sh[i], None if direction == "Up" else vol7[i]) for i in top],
        "bucket": [labels[i] for i in top], "loss": pnl7[top]})
    seven_rows = seven_rows[seven_rows["loss"] < 0].reset_index(drop=True)
    issuers = pd.DataFrame({"issuer": I.index, "name": I["name"].to_numpy(), "bucket": labels,
                            "single_up": pu, "single_down": pdn, "seven_up": pu7, "seven_down": pd7})
    total = min(single_total, seven_total)
    return dict(total=total, single=single, seven=dict(total=seven_total, direction=direction,
                                                     names=seven_rows),
                issuers=issuers.sort_values("single_up").reset_index(drop=True))


# ---------------------------------------------------------------------------
# Theta
# ---------------------------------------------------------------------------

def theta(model: Model) -> dict:
    days = model.params["theta"]["days"]
    if not model.has_options:
        return dict(total=0.0, by_expiry=pd.DataFrame(columns=["expiry_days", "theta"]))
    o = model.p_is_opt
    decay = np.where(o, model.position_pnl(0.0, None, dt_years=days / 365.0), 0.0)
    exp_days = np.round(model.p_t * 365.0).astype(int)
    df = pd.DataFrame({"expiry_days": exp_days[o], "theta": decay[o]}).groupby("expiry_days",
                                                                              as_index=False).sum()
    return dict(total=min(0.0, float(decay.sum())), by_expiry=df.head(10))
