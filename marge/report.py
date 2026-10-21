"""Text, JSON and CSV output for a :class:`marge.engine.Result`."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .engine import Result
from .model import Model


def _n(x: float) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    v = round(float(x))
    return f"{v + 0:,d}" if v else "0"


def _row(label: str, value, note: str = "", indent: int = 0, width: int = 46) -> str:
    text = " " * indent + label
    shown = "" if value is None else _n(value)
    return f"{text:<{width}}{shown:>16}  {note}".rstrip()


def text_report(result: Result, model: Model, top: int = 5) -> str:
    eq, fxr, ex = result.equity, result.fx, result.exposure
    base = model.params["base_currency"]
    out = []
    out.append("marge - risk-based portfolio margin")
    out.append(f"Base currency: {base}   Positions: {len(model.positions)}   Exposure lines: "
               f"{model.n_lines:,}   Assets: {model.n_assets:,}   Issuers: {model.n_issuers:,}")
    out.append("")
    out.append("EXPOSURE")
    out.append(_row("Long market value", ex["long_market_value"], indent=2))
    out.append(_row("Short market value", ex["short_market_value"], indent=2))
    out.append(_row("Gross market value", ex["gross_market_value"], indent=2))
    out.append(_row("Net market value", ex["net_market_value"], indent=2))
    out.append(_row("Gross delta (after leverage)", ex["gross_delta"], indent=2))
    out.append(_row("Net delta (after leverage)", ex["net_delta"], indent=2))
    out.append("")
    out.append("REQUIREMENT")
    pct = ex["requirement_pct_gross"]
    out.append(_row("Total requirement", result.total, f"{pct:.2%} of gross" if pct == pct else "", indent=2))
    out.append(_row("Stress requirement (top 2 + SRSS rest)", result.stress, indent=4))
    labels = {"fx": "FX", "rates": "Interest rates"}
    for cls, val in sorted(result.classes.items(), key=lambda kv: kv[1]):
        out.append(_row(labels.get(cls, cls.capitalize()), val, indent=6))
    out.append(_row("Add-ons (flat rate)", result.addon, indent=4))
    lev = ex["max_gross_leverage"]
    out.append(f"  {'Max gross leverage (gross / requirement)':<44}{lev:>15,.1f}x")
    out.append("")
    out.append("EQUITY")
    out.append(_row("Equity requirement", eq["total"], indent=2))
    out.append(_row("Stress test (worst of five)", eq["stress"], f"driver: {eq['dominant']}", indent=4))
    m, s = eq["macro"], eq["sector"]
    out.append(_row("Macro: global + country + asset", m["total"], m["worst_scenario"], indent=6))
    out.append(_row("global / country / asset", None, f"{_n(m['global_loss'])} / {_n(m['dispersion_loss'])}"
                    f" / {_n(m['asset_loss'])}", indent=8))
    out.append(_row("Sector: global + sector + asset", s["total"], s["worst_scenario"], indent=6))
    out.append(_row("global / sector / asset", None, f"{_n(s['global_loss'])} / {_n(s['dispersion_loss'])}"
                    f" / {_n(s['asset_loss'])}", indent=8))
    rv = eq["relative_value"]
    out.append(_row("Relative value", rv["total"], f"driver: {rv['driver']}", indent=6))
    for k in ("spot_basis", "vol_basis", "vol_surface", "spot_basis_floor"):
        out.append(_row(k.replace("_", " ").capitalize(), rv[k], indent=8))
    c = eq["concentration"]
    out.append(_row("Concentration", c["total"], indent=6))
    sn = c["single"]
    out.append(_row("Single name", sn["total"], f"{sn['name']} {sn['scenario']} ({sn['bucket']})"
                    if sn["name"] else "", indent=8))
    out.append(_row("Seven names", c["seven"]["total"], f"market {c['seven']['direction'].lower()}", indent=8))
    for _, r in c["seven"]["names"].iterrows():
        out.append(_row(str(r["name"])[:34], r["loss"], f"{r['scenario']} ({r['bucket']})", indent=10))
    out.append(_row("Theta (5-day decay)", eq["theta"]["total"], indent=6))
    out.append(_row("Liquidity", eq["liquidity"], indent=4))
    out.append(_row("Delta liquidation", eq["delta_liquidation"]["total"], indent=6))
    for _, r in eq["delta_liquidation"]["issuers"].head(top).iterrows():
        days = "no ADV" if np.isinf(r["days"]) else f"{r['days']:.1f} days"
        out.append(_row(str(r["name"])[:34], r["capped_charge"], f"{r['charge_type']}, {days}", indent=8))
    ol = eq["option_liquidity"]
    out.append(_row("Option liquidity", ol["total"], f"bid/ask {_n(ol['bid_ask'])}, conc {_n(ol['concentration'])},"
                    f" term {_n(ol['term'])}, skew {_n(ol['skew'])}" if ol["total"] else "", indent=6))
    out.append(_row("ETF create/redeem fees", eq["etf_fees"]["total"], indent=6))
    out.append("")
    out.append("MACRO WORST SCENARIO - TOP COUNTRY DISPERSION LOSSES")
    for _, r in m["buckets"].head(top).iterrows():
        out.append(_row(f"{r['country']} (group {r['group']})", r["dispersion_loss"],
                        f"global {_n(r['global_pnl'])}, country {r['direction'].lower()}", indent=2))
    out.append("SECTOR WORST SCENARIO - TOP SECTOR DISPERSION LOSSES")
    for _, r in s["buckets"].head(top).iterrows():
        out.append(_row(str(r["sector"]), r["dispersion_loss"], f"sector {r['direction'].lower()}", indent=2,
                        width=max(46, len(str(r["sector"])) + 4)))
    out.append("")
    out.append("FX")
    out.append(_row("FX requirement (worst of three)", fxr["total"], indent=2))
    if fxr.get("base_shock"):
        d, b = fxr["base_shock"]
        out.append(_row("Base currency move", fxr["base"], f"{base} {d}{b:.0%}", indent=4))
        cur = ", ".join(f"{r['currency']} {_n(r['pnl'])}" for _, r in fxr["portfolio_currencies"].iterrows())
        out.append(_row(f"Two currencies {fxr['portfolio_direction']}", fxr["portfolio"], cur, indent=4))
        peg = fxr.get("pegged_currency")
        out.append(_row("Pegged currency", fxr["pegged"], f"{peg[0]} {peg[1]:+.0%}" if peg else "", indent=4))
    else:
        out.append("    no foreign-currency exposure")
    if result.warnings:
        out.append("")
        out.append("WARNINGS")
        out.extend(f"  - {w}" for w in result.warnings)
    return "\n".join(out)


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _jsonable(obj.to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _jsonable(obj.to_dict())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def to_json(result: Result, path: str | Path | None = None, detail: bool = False) -> str:
    data = result.summary()
    data["warnings"] = result.warnings
    if detail:
        eq = result.equity
        data["detail"] = {
            "macro_scenarios": eq["macro"]["scenarios"], "sector_scenarios": eq["sector"]["scenarios"],
            "macro_countries": eq["macro"]["buckets"], "sector_buckets": eq["sector"]["buckets"],
            "seven_names": eq["concentration"]["seven"]["names"],
            "single_name": eq["concentration"]["single"],
            "delta_liquidation": eq["delta_liquidation"]["issuers"],
            "fx_exposures": result.fx["exposures"],
        }
    text = json.dumps(_jsonable(data), indent=2)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
    return text


def write_details(result: Result, model: Model, directory: str | Path) -> list[Path]:
    """Write the per-component breakdown tables as CSV files."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    eq = result.equity
    tables = {
        "macro_scenarios": pd.DataFrame(eq["macro"]["scenarios"]),
        "macro_countries": eq["macro"]["buckets"],
        "macro_assets": eq["macro"]["assets"],
        "sector_scenarios": pd.DataFrame(eq["sector"]["scenarios"]),
        "sector_buckets": eq["sector"]["buckets"],
        "sector_assets": eq["sector"]["assets"],
        "relative_value_issuers": eq["relative_value"]["issuers"],
        "spot_basis_floor": eq["relative_value"]["floor"],
        "concentration_issuers": eq["concentration"]["issuers"],
        "seven_names": eq["concentration"]["seven"]["names"],
        "delta_liquidation": eq["delta_liquidation"]["issuers"],
        "option_liquidity": eq["option_liquidity"]["underliers"],
        "fx_currencies": result.fx["detail"],
        "addons": result.addons["positions"],
        "positions": model.positions.assign(delta=model.p_delta)[
            ["symbol", "kind", "quantity", "currency", "mv", "leverage", "delta", "reference", "basket"]],
    }
    paths = []
    for name, df in tables.items():
        p = d / f"{name}.csv"
        df.to_csv(p, index=False)
        paths.append(p)
    return paths
