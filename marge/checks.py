"""Input data-quality report: which missing attributes matter, by exposure."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .model import Model


def data_quality(model: Model, top: int = 10) -> dict:
    """Find gaps in the inputs, ranked by the gross exposure they affect.

    Missing attributes do not stop a run, but each one falls back to a default
    (often a conservative one), so the largest gaps are worth filling first.
    """
    A, I, P = model.assets, model.issuers, model.positions
    gross = np.abs(model.l_delta)
    total_gross = float(gross.sum()) or 1.0
    asset_gross = model.by_asset(gross)
    issuer_gross = model.by_issuer(gross)
    groups = model.params["country_groups"]
    known = {c.lower() for c in groups}

    def gap(kind: str, ids, weights, note: str) -> dict | None:
        ids = list(ids)
        if not ids:
            return None
        w = np.asarray(weights, dtype=float)
        order = np.argsort(-w)
        names = [f"{ids[i]} ({w[i]:,.0f})" for i in order[:top]]
        return dict(issue=kind, count=len(ids), exposure=float(w.sum()),
                    exposure_pct=float(w.sum()) / total_gross, note=note, largest=names)

    issues = []
    line_syms = set(model.lines["symbol"])
    missing_master = sorted(s for s in line_syms if s not in model.securities_given)
    if missing_master:
        w = pd.Series(gross).groupby(model.lines["symbol"].to_numpy()).sum()
        issues.append(gap("not in security master", missing_master, w.reindex(missing_master).fillna(0),
                          "country/sector/market cap unknown: worst-case defaults applied"))

    a_mask = (A["country"].str.lower() == "unknown").to_numpy()
    issues.append(gap("country missing", A.index[a_mask], asset_gross[a_mask],
                      f"treated as country group {model.params['default_country_group']}"))
    unk = A[~A["country"].str.lower().isin(known) & ~a_mask.astype(bool)]
    if len(unk):
        m = A.index.isin(unk.index)
        issues.append(gap("country not in group table", [f"{i} [{c}]" for i, c in zip(unk.index, unk["country"])],
                          asset_gross[m], f"defaulted to group {model.params['default_country_group']}; "
                          "check the spelling or add it under [country_groups]"))
    s_mask = A["sector"].str.lower().isin(["unknown", "", "nan"]).to_numpy()
    issues.append(gap("sector missing", A.index[s_mask], asset_gross[s_mask],
                      "all such names share one 'Unknown' sector bucket"))
    m_mask = (I["market_cap"].isna() & ~I["is_etf"].astype(bool)).to_numpy()
    issues.append(gap("market cap missing", I.index[m_mask], issuer_gross[m_mask],
                      "smallest concentration bucket (+800% / -100% single-name shocks)"))
    adv_value = (I["adv"] * I["price"] * I["fx"]).to_numpy(dtype=float)
    l_mask = np.isnan(adv_value) & ~I["is_etf"].astype(bool).to_numpy()
    issues.append(gap("ADV or price missing", I.index[l_mask], issuer_gross[l_mask],
                      "no delta-liquidation charge (set liquidity.missing_adv = \"max\" to charge the cap)"))
    etf_unexploded = P[(P["kind"] == "etf") & P["basket"].isna()]
    if len(etf_unexploded):
        issues.append(gap("ETF without holdings", etf_unexploded["symbol"], np.abs(model.p_delta[etf_unexploded.index]),
                          "treated as one single-name asset; add its holdings to the basket file"))
    issues = [i for i in issues if i]
    issues.sort(key=lambda i: -i["exposure"])
    return dict(positions=len(P), lines=model.n_lines, assets=model.n_assets, issuers=model.n_issuers,
                gross_delta=total_gross, issues=issues, warnings=list(dict.fromkeys(model.warnings)))


def format_quality(report: dict) -> str:
    out = [f"Positions: {report['positions']}   Exposure lines: {report['lines']:,}   "
           f"Assets: {report['assets']:,}   Issuers: {report['issuers']:,}   "
           f"Gross delta: {report['gross_delta']:,.0f}", ""]
    if not report["issues"]:
        out.append("No data gaps found.")
    for i in report["issues"]:
        out.append(f"- {i['issue']}: {i['count']} name(s), {i['exposure_pct']:.1%} of gross delta "
                   f"({i['exposure']:,.0f})")
        out.append(f"    effect: {i['note']}")
        out.append(f"    largest: {', '.join(i['largest'])}")
    if report["warnings"]:
        out.append("")
        out.append("Warnings:")
        out.extend(f"- {w}" for w in report["warnings"])
    return "\n".join(out)
