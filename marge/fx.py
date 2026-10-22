"""FX stress: base-currency move, two-currency moves and pegged currencies.

FX exposure of a line is its delta in base currency, attributed to the
currency of its asset (an ADR carries the currency of its ordinary share).
"""

from __future__ import annotations

import pandas as pd

from .model import Model


def fx_exposures(model: Model) -> pd.Series:
    base = model.params["base_currency"]
    ccy = model.assets["currency"].to_numpy(dtype=str)[model.l_asset]
    s = pd.Series(model.l_delta).groupby(ccy).sum()
    return s.drop(base, errors="ignore")


def fx_stress(model: Model) -> dict:
    p = model.params["fx"]
    base = model.params["base_currency"]
    exp = fx_exposures(model)
    exp = exp[exp.abs() > 0]
    empty = dict(total=0.0, base=0.0, portfolio=0.0, pegged=0.0, exposures=exp.rename("exposure"),
                 detail=pd.DataFrame())
    if exp.empty:
        return empty

    # Base currency: every foreign currency moves together, up and down.
    b = p["base_shock"].get(base, p["default_base_shock"])
    net = float(exp.sum())
    base_up, base_dn = net * b, -net * b
    base_loss = min(0.0, base_up, base_dn)
    base_dir = "+" if base_up <= base_dn else "-"

    # Portfolio currencies: sum of the two worst currencies, per direction.
    table = p["pair_shocks"].get(base, {})
    other = p["other_currency_shock"]
    rows = []
    for c, e in exp.items():
        dn, up = table.get(c, [-other, other])
        rows.append(dict(currency=c, exposure=e, up_shock=up, down_shock=dn, up_pnl=e * up, down_pnl=e * dn))
    df = pd.DataFrame(rows)
    k = int(p["currencies_per_side"])
    up_losses = df["up_pnl"].clip(upper=0).nsmallest(k)
    dn_losses = df["down_pnl"].clip(upper=0).nsmallest(k)
    port_up, port_dn = float(up_losses.sum()), float(dn_losses.sum())
    portfolio = min(port_up, port_dn)
    port_side = df.loc[(up_losses if port_up <= port_dn else dn_losses).index]

    # Pegged currencies: one currency breaks its peg.
    peg = 0.0
    peg_ccy = None
    for c, e in exp.items():
        shock = p["stable_peg_shock"] if c in p["stable_pegs"] else (
            p["risky_peg_shock"] if c in p["risky_pegs"] else None)
        if shock is None or c == base:
            continue
        loss = -abs(e) * shock
        if loss < peg:
            peg, peg_ccy = loss, (c, shock if e < 0 else -shock)

    total = min(base_loss, portfolio, peg)
    return dict(
        total=total, base=base_loss, base_shock=(base_dir, b), portfolio=portfolio,
        portfolio_direction="appreciate" if port_up <= port_dn else "depreciate",
        portfolio_currencies=port_side[["currency", "exposure", "up_pnl" if port_up <= port_dn else "down_pnl"]]
        .rename(columns={"up_pnl": "pnl", "down_pnl": "pnl"}).reset_index(drop=True),
        pegged=peg, pegged_currency=peg_ccy, exposures=exp.rename("exposure"), detail=df,
    )
