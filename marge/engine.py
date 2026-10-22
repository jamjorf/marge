"""Run every component and aggregate them into the total requirement.

Total requirement = sum of the two largest asset-class losses
                    + SRSS of the remaining asset-class losses
                    + add-ons (flat-rate charges)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import equity, fx, liquidity
from .model import Model, build_model

ASSET_CLASSES = ("equity", "credit", "convertibles", "rates", "fx", "commodities")


@dataclass
class Result:
    total: float
    stress: float
    addon: float
    classes: dict
    equity: dict
    fx: dict
    addons: dict
    exposure: dict
    warnings: list = field(default_factory=list)

    def summary(self) -> dict:
        eq = self.equity
        return {
            "total_requirement": self.total,
            "stress_requirement": self.stress,
            "addon_requirement": self.addon,
            "asset_classes": dict(self.classes),
            "equity": {
                "total": eq["total"],
                "stress_test": eq["stress"],
                "dominant_scenario": eq["dominant"],
                "macro": eq["macro"]["total"],
                "macro_scenario": eq["macro"]["worst_scenario"],
                "sector": eq["sector"]["total"],
                "sector_scenario": eq["sector"]["worst_scenario"],
                "relative_value": eq["relative_value"]["total"],
                "relative_value_driver": eq["relative_value"]["driver"],
                "concentration": eq["concentration"]["total"],
                "single_name": eq["concentration"]["single"]["total"],
                "seven_name": eq["concentration"]["seven"]["total"],
                "theta": eq["theta"]["total"],
                "liquidity": eq["liquidity"],
                "delta_liquidation": eq["delta_liquidation"]["total"],
                "option_liquidity": eq["option_liquidity"]["total"],
                "etf_fees": eq["etf_fees"]["total"],
            },
            "fx": {k: self.fx[k] for k in ("total", "base", "portfolio", "pegged")},
            "exposure": self.exposure,
        }


def srss(values) -> float:
    return math.sqrt(sum(v * v for v in values))


def aggregate(losses: dict, top_n: int = 2) -> float:
    """Sum of the ``top_n`` largest losses plus SRSS of the rest (losses <= 0)."""
    ordered = sorted((min(v, 0.0) for v in losses.values()))
    return float(sum(ordered[:top_n]) - srss(ordered[top_n:]))


def flat_rate_addons(model: Model) -> dict:
    """Flat charges for positions the stress test does not cover."""
    p = model.params["flat_rate"]
    P = model.positions
    rows = []
    for _, r in P[P["kind"] == "flat"].iterrows():
        price = abs(r["spot"]) if not np.isnan(r["spot"]) else abs(r["mv"] / r["quantity"]) if r["quantity"] else 0.0
        if r["quantity"] >= 0:
            charge = -p["long"] * abs(r["mv"])
        else:
            charge = -p["short_multiple"] * max(price * r["fx"], p["short_min_price"]) * abs(r["quantity"])
        rows.append(dict(symbol=r["symbol"], market_value=r["mv"], charge=charge))
    df = pd.DataFrame(rows, columns=["symbol", "market_value", "charge"])
    return dict(total=float(df["charge"].sum()) if len(df) else 0.0, positions=df)


def exposure_summary(model: Model, requirement: float) -> dict:
    mv = model.p_mv
    delta = model.p_delta
    lmv, smv = float(mv[mv > 0].sum()), float(mv[mv < 0].sum())
    gmv = lmv - smv
    req = -requirement
    return {
        "long_market_value": lmv, "short_market_value": smv, "gross_market_value": gmv,
        "net_market_value": lmv + smv,
        "gross_delta": float(np.abs(delta).sum()), "net_delta": float(delta.sum()),
        "requirement_pct_gross": req / gmv if gmv else float("nan"),
        "max_gross_leverage": gmv / req if req > 0 else float("inf"),
    }


def compute(model: Model) -> Result:
    params = model.params
    macro = equity.macro(model)
    sector = equity.sector(model)
    rv = equity.relative_value(model)
    conc = equity.concentration(model)
    theta = equity.theta(model)
    scen = {"macro": macro["total"], "sector": sector["total"], "relative_value": rv["total"],
            "concentration": conc["total"], "theta": theta["total"]}
    dominant = min(scen, key=scen.get)
    stress = scen[dominant]

    # Issuer P&L in the dominant scenario's global move, for the liquidity cap.
    scenario_pnl = None
    if dominant in ("macro", "sector"):
        tree = macro if dominant == "macro" else sector
        g = next(s["shock"] for s in tree["scenarios"] if s["scenario"] == tree["worst_scenario"])
        scenario_pnl = model.by_issuer(model.line_pnl(g))
    dl = liquidity.delta_liquidation(model, scenario_pnl)
    ol = liquidity.option_liquidity(model)
    fees = liquidity.etf_fees(model)
    liq = dl["total"] + ol["total"] + fees["total"]
    eq = dict(total=stress + liq, stress=stress, dominant=dominant, scenarios=scen, liquidity=liq,
              macro=macro, sector=sector, relative_value=rv, concentration=conc, theta=theta,
              delta_liquidation=dl, option_liquidity=ol, etf_fees=fees)

    fxr = fx.fx_stress(model)
    external = params.get("external_losses", {}) or {}
    classes = {c: min(0.0, -abs(float(external.get(c, 0.0)))) + 0.0 for c in ASSET_CLASSES}
    classes["equity"] = eq["total"]
    classes["fx"] = fxr["total"] + classes["fx"]
    stress_req = aggregate(classes, int(params["aggregation"]["top_n"]))
    addons = flat_rate_addons(model)
    total = stress_req + addons["total"]
    return Result(total=total, stress=stress_req, addon=addons["total"], classes=classes, equity=eq,
                  fx=fxr, addons=addons, exposure=exposure_summary(model, total),
                  warnings=list(dict.fromkeys(model.warnings)))


def run(positions, securities=None, baskets=None, params=None, as_of=None) -> Result:
    """Convenience wrapper: build the model and compute the requirement."""
    return compute(build_model(positions, securities, baskets, params, as_of))


def scale_model(model: Model, k: float) -> Model:
    """A copy of the model with every position scaled by ``k``."""
    P = model.positions.copy()
    for c in ("quantity", "mv", "units"):
        P[c] = P[c] * k
    return Model(params=model.params, positions=P, lines=model.lines, securities=model.securities,
                 assets=model.assets, issuers=model.issuers, warnings=[],
                 securities_given=model.securities_given)


def max_scale(model: Model, equity_value: float, tol: float = 1e-4) -> tuple[float, Result]:
    """Largest uniform scale of the book whose requirement fits ``equity_value``."""
    def req(k):
        res = compute(scale_model(model, k))
        return -res.total, res

    r1, res1 = req(1.0)
    if r1 <= 0:
        return float("inf"), res1
    lo, hi = 0.0, equity_value / r1 * 2.0 + 1e-9
    while req(hi)[0] <= equity_value:
        lo, hi = hi, hi * 2.0
    best = None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        r, res = req(mid)
        if r <= equity_value:
            lo, best = mid, res
        else:
            hi = mid
        if hi - lo <= tol * max(hi, 1e-9):
            break
    return lo, best if best is not None else req(lo)[1]
