"""Unit tests. Run with ``python -m unittest`` (or pytest)."""

from __future__ import annotations

import datetime as dt
import io
import math
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

from marge import build_model, compute, load_params
from marge.cli import main
from marge.engine import aggregate, srss
from marge.equity import concentration_buckets, macro, relative_value, sector
from marge.fx import fx_stress
from marge.liquidity import delta_liquidation
from marge.pricing import bs_delta, bs_price

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
AS_OF = dt.date(2026, 10, 21)


def make(positions, securities, baskets=None, overrides=None):
    params = load_params(overrides=overrides or {})
    return build_model(pd.DataFrame(positions), pd.DataFrame(securities),
                       pd.DataFrame(baskets) if baskets else None, params, as_of=AS_OF)


def sec(symbol, country="United States", sector_="Software & Services", mcap=50e9, adv=1e9, price=100.0,
        currency="USD", **kw):
    return dict(symbol=symbol, country=country, sector=sector_, market_cap=mcap, adv=adv, price=price,
                currency=currency, **kw)


class AggregationTests(unittest.TestCase):
    def test_srss_footnote_example(self):
        # 1,000 equally weighted securities contributing $100 each -> $3,162.
        self.assertAlmostEqual(srss([100.0] * 1000), 3162.28, places=2)

    def test_top_two_plus_srss(self):
        losses = {"equity": -100.0, "fx": -50.0, "rates": -30.0, "credit": -40.0, "commodities": 0.0}
        self.assertAlmostEqual(aggregate(losses), -150.0 - 50.0)


class MacroTests(unittest.TestCase):
    def test_methodology_worked_example(self):
        # $100,000 US stock and -$50,000 UK stock under a -15% global shock with
        # 2.5% country and 7.5% asset dispersion: -7,500 - 2,795 - 8,385 = -18,680.
        overrides = {"macro": {"global_shocks": [-0.15], "country_dispersion": {1: 0.025, 2: 0.025},
                               "asset_dispersion": {1: 0.075, 2: 0.075}, "large_cap_threshold": 1e15}}
        m = make([dict(symbol="US1", quantity=1000, price=100.0), dict(symbol="UK1", quantity=-500, price=100.0)],
                 [sec("US1"), sec("UK1", country="United Kingdom")], overrides=overrides)
        r = macro(m)
        self.assertAlmostEqual(r["global_loss"], -7500.0, places=6)
        self.assertAlmostEqual(r["dispersion_loss"], -math.hypot(2500, 1250), places=6)
        self.assertAlmostEqual(r["asset_loss"], -math.hypot(7500, 3750), places=6)
        self.assertEqual(round(r["total"]), -18680)

    def test_core_global_nets_and_is_floored(self):
        m = make([dict(symbol="A", quantity=1000, price=100.0), dict(symbol="B", quantity=-1000, price=100.0)],
                 [sec("A"), sec("B", country="Canada")])
        rows = {round(s["shock"], 4): s for s in macro(m)["scenarios"]}
        self.assertEqual(rows[-0.15]["global_loss"], 0.0)
        self.assertEqual(rows[0.10]["global_loss"], 0.0)

    def test_non_core_moves_with_the_global_shock(self):
        # A long group-5 position only loses when the global shock is down.
        m = make([dict(symbol="EM", quantity=1000, price=100.0)], [sec("EM", country="Argentina")])
        rows = {round(s["shock"], 4): s for s in macro(m)["scenarios"]}
        self.assertEqual(rows[0.10]["total"], 0.0)
        down = rows[-0.10]
        self.assertAlmostEqual(down["global_loss"], -10_000.0)
        self.assertAlmostEqual(down["dispersion_loss"], -15_000.0)   # group 5 country 15%
        self.assertAlmostEqual(down["asset_loss"], -15_000.0)        # group 5 asset 15%

    def test_group1_top_country_dispersion_fades_with_vix(self):
        pos, s = [dict(symbol="A", quantity=-1000, price=100.0)], [sec("A")]
        for vix, expected in ((14.0, 0.0), (22.5, -0.01 * 100_000), (35.0, -0.02 * 100_000)):
            r = macro(make(pos, s, overrides={"market": {"vix": vix, "vix_ema": 14.0}}))
            top = next(x for x in r["scenarios"] if abs(x["shock"] - 0.10) < 1e-9)
            self.assertAlmostEqual(top["dispersion_loss"], expected, places=6)

    def test_large_caps_get_reduced_asset_shock(self):
        m = make([dict(symbol="BIG", quantity=1000, price=100.0)], [sec("BIG", mcap=500e9)])
        top = next(x for x in macro(m)["scenarios"] if abs(x["shock"] + 0.15) < 1e-9)
        self.assertAlmostEqual(top["asset_loss"], -5_000.0)


class SectorTests(unittest.TestCase):
    def test_top_shock_interpolates_with_vix_ema(self):
        m = make([dict(symbol="A", quantity=-1000, price=100.0)], [sec("A")],
                 overrides={"market": {"vix_ema": 22.5}})
        shocks = [round(s["shock"], 6) for s in sector(m)["scenarios"]]
        self.assertIn(0.0875, shocks)

    def test_sector_dispersion_and_large_cap_exemption(self):
        m = make([dict(symbol="A", quantity=1000, price=100.0), dict(symbol="B", quantity=1000, price=100.0)],
                 [sec("A", mcap=10e9), sec("B", mcap=200e9, sector_="Energy")])
        worst = sector(m)
        self.assertEqual(worst["worst_scenario"], "-15% Vol Md")
        self.assertAlmostEqual(worst["global_loss"], -30_000.0)
        self.assertAlmostEqual(worst["dispersion_loss"], -math.hypot(5_000, 5_000))
        self.assertAlmostEqual(worst["asset_loss"], -10_000.0)   # only the sub-$150bn name


class EtfTests(unittest.TestCase):
    def test_explosion_and_leverage_floor(self):
        baskets = [dict(basket="IDX", symbol="A", weight=0.6), dict(basket="IDX", symbol="B", weight=0.39)]
        m = make([dict(symbol="LEV3", quantity=1000, price=50.0, type="etf", basket="IDX", leverage=3)],
                 [sec("A"), sec("B", sector_="Energy")], baskets)
        self.assertAlmostEqual(m.l_delta.sum(), 3 * 50_000 * 0.99)
        # A 3x ETF cannot lose more than its value.
        self.assertAlmostEqual(m.position_pnl(-0.40)[0], -50_000.0)
        self.assertAlmostEqual(m.position_pnl(-0.10)[0], -15_000.0)
        # A single constituent move only moves the ETF by its weight.
        self.assertAlmostEqual(m.line_pnl(-0.50, mode="idiosyncratic")[0], 50_000 * 3 * 0.6 * -0.50)


class RelativeValueTests(unittest.TestCase):
    def test_listing_gains_only_partly_offset(self):
        # Two lines of one issuer: gains on one listing offset losses at 40%.
        pos = [dict(symbol="ORD", quantity=30, price=100.0), dict(symbol="ADR", quantity=-991.2, price=100.0)]
        secs = [sec("ORD", issuer_id="CO", asset_id="ORD"), sec("ADR", issuer_id="CO", asset_id="ADR")]
        r = relative_value(make(pos, secs))
        self.assertAlmostEqual(r["spot_basis"], -99_120 * 0.075 + 0.4 * 3_000 * 0.075)

    def test_spot_basis_floor(self):
        pos = [dict(symbol="US", quantity=10_000, price=100.0), dict(symbol="UK", quantity=-10_000, price=100.0),
               dict(symbol="BR", quantity=10_000, price=100.0)]
        secs = [sec("US"), sec("UK", country="United Kingdom"), sec("BR", country="Brazil")]
        r = relative_value(make(pos, secs))
        self.assertAlmostEqual(r["spot_basis_floor"], -(1_500 + 5_000 + 12_500))


class ConcentrationTests(unittest.TestCase):
    def test_buckets(self):
        secs = [sec("MEGA", mcap=500e9), sec("BANK", mcap=600e9, sector_="Banks"),
                sec("EU", mcap=60e9, country="Germany"), sec("SMALL", mcap=300e6),
                sec("EMBIG", mcap=400e9, country="Brazil")]
        pos = [dict(symbol=s["symbol"], quantity=100, price=10.0) for s in secs]
        m = make(pos, secs)
        _, labels = concentration_buckets(m)
        self.assertEqual(dict(zip(m.issuers.index, labels)),
                         {"MEGA": ">150b", "BANK": "5b-150b", "EU": ">50b", "SMALL": "200m-500m",
                          "EMBIG": "5b-150b"})

    def test_single_and_seven(self):
        pos = [dict(symbol=f"S{i}", quantity=-1000 * (i + 1), price=100.0) for i in range(8)]
        secs = [sec(f"S{i}", mcap=500e9) for i in range(8)]
        r = compute(make(pos, secs)).equity["concentration"]
        self.assertAlmostEqual(r["single"]["total"], -800_000 * 0.25)
        self.assertAlmostEqual(r["seven"]["total"], -sum(1000 * (i + 1) * 100 for i in range(1, 8)) * 0.15)


class LiquidityTests(unittest.TestCase):
    def test_adv_charge_and_caps(self):
        secs = [sec("L", adv=1000, price=10.0), sec("S", adv=0, price=10.0),
                sec("OTC", adv=1e9, price=0.5, otc=True)]
        pos = [dict(symbol="L", quantity=10_000, price=10.0), dict(symbol="S", quantity=-100, price=10.0),
               dict(symbol="OTC", quantity=-1000, price=0.5)]
        r = delta_liquidation(make(pos, secs)).get("issuers").set_index("issuer")["charge"]
        self.assertAlmostEqual(r["L"], -0.05 * 9 * 100_000)        # 10 days of volume
        self.assertAlmostEqual(r["S"], -3.0 * 1_000)                # no volume: 300% for shorts
        self.assertAlmostEqual(r["OTC"], -2.5 * 1000)               # max(price, $2.50) per share


class FxTests(unittest.TestCase):
    def test_adr_carries_currency_of_its_ordinary(self):
        secs = [sec("ADR", asset_id="ORD.KS", country="Korea, Republic of"),
                sec("ORD.KS", country="Korea, Republic of", currency="KRW", price=100_000)]
        m = make([dict(symbol="ADR", quantity=-1000, price=100.0)], secs)
        r = fx_stress(m)
        self.assertAlmostEqual(r["exposures"]["KRW"], -100_000)
        self.assertAlmostEqual(r["portfolio"], -12_000)            # KRW +12% vs USD
        self.assertAlmostEqual(r["base"], -5_000)                  # all currencies +5% vs USD
        self.assertAlmostEqual(r["total"], -12_000)

    def test_pegged(self):
        secs = [sec("HK", country="Hong Kong", currency="HKD", price=50.0)]
        m = make([dict(symbol="HK", quantity=-10_000, price=50.0)], secs,
                 overrides={"fx_rates": {"HKD": 0.128}})
        self.assertAlmostEqual(fx_stress(m)["pegged"], -64_000 * 0.15)


class OptionTests(unittest.TestCase):
    def test_put_call_parity_and_delta(self):
        c = float(bs_price(100, 95, 0.5, 0.3, 0.04, 0.0, True))
        p = float(bs_price(100, 95, 0.5, 0.3, 0.04, 0.0, False))
        self.assertAlmostEqual(c - p, 100 - 95 * math.exp(-0.04 * 0.5), places=8)
        d = float(bs_delta(100, 100, 1.0, 0.2, 0.0, 0.0, True))
        self.assertTrue(0.5 < d < 0.6)

    def test_option_portfolio_runs(self):
        secs = [sec("A", mcap=500e9)]
        pos = [dict(symbol="A C110", quantity=-100, price=3.0, type="option", underlying="A", put_call="C",
                    strike=110, expiry="2027-01-15", implied_vol=0.3),
               dict(symbol="A", quantity=5000, price=100.0)]
        r = compute(make(pos, secs))
        self.assertLess(r.total, 0)
        self.assertLess(r.equity["option_liquidity"]["total"], 0)
        self.assertLessEqual(r.equity["theta"]["total"], 0)


class InputTests(unittest.TestCase):
    def test_json_config_matches_toml(self):
        import json
        import tempfile
        toml_params = load_params(EXAMPLES / "config.toml")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"market": {"vix": 18.0, "vix_ema": 17.5, "rate": 0.04},
                                        "fx_rates": {"JPY": 0.0067, "HKD": 0.128, "TWD": 0.031}}))
            json_params = load_params(path)
        self.assertEqual(json_params["market"], toml_params["market"])
        self.assertEqual(json_params["fx_rates"], toml_params["fx_rates"])

    def test_missing_position_fx_rate_is_an_error(self):
        from marge import InputError
        with self.assertRaises(InputError):
            make([dict(symbol="JP", quantity=100, price=1000.0, currency="JPY")], [sec("JP", currency="JPY")])

    def test_check_ranks_gaps_by_exposure(self):
        from marge.checks import data_quality
        m = make([dict(symbol="A", quantity=1000, price=100.0), dict(symbol="B", quantity=10, price=100.0),
                  dict(symbol="Z", quantity=500, price=100.0)],
                 [sec("A", mcap=float("nan")), sec("B", mcap=float("nan"), country="Atlantis")])
        issues = {i["issue"]: i for i in data_quality(m)["issues"]}
        self.assertEqual(issues["market cap missing"]["count"], 3)
        self.assertTrue(issues["market cap missing"]["largest"][0].startswith("A "))
        self.assertEqual(issues["not in security master"]["count"], 1)
        self.assertEqual(issues["country not in group table"]["count"], 1)


class ExampleTests(unittest.TestCase):
    def test_example_portfolio_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["run", "-p", str(EXAMPLES / "positions.csv"), "-s", str(EXAMPLES / "securities.csv"),
                         "-b", str(EXAMPLES / "baskets.csv"), "-c", str(EXAMPLES / "config.toml"),
                         "--as-of", "2026-10-21"])
        self.assertEqual(code, 0)
        self.assertIn("Total requirement", out.getvalue())

    def test_requirement_scales_linearly_without_liquidity(self):
        from marge.engine import max_scale
        m = make([dict(symbol="A", quantity=1000, price=100.0)], [sec("A")])
        req = -compute(m).total
        k, _ = max_scale(m, 10 * req)
        self.assertAlmostEqual(k, 10.0, places=2)


if __name__ == "__main__":
    unittest.main()
