"""Command line interface: ``marge run``, ``marge check`` and ``marge leverage``."""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import __version__
from .checks import data_quality, format_quality
from .config import load_params
from .engine import compute, max_scale
from .model import InputError, build_model
from .report import text_report, to_json, write_details


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--positions", required=True, help="positions CSV")
    p.add_argument("-s", "--securities", help="security master CSV (constituents and held names)")
    p.add_argument("-b", "--baskets", help="ETF holdings CSV (basket, symbol, weight)")
    p.add_argument("-c", "--config", help="TOML or JSON config overriding default parameters")
    p.add_argument("--as-of", help="valuation date YYYY-MM-DD (option expiries), default today")
    p.add_argument("--vix", type=float, help="spot VIX level (overrides config)")
    p.add_argument("--vix-ema", type=float, help="5-day EMA of VIX (overrides config)")
    p.add_argument("--base-currency", help="base currency (overrides config)")


def _load(args):
    overrides: dict = {}
    if args.vix is not None:
        overrides.setdefault("market", {})["vix"] = args.vix
    if args.vix_ema is not None:
        overrides.setdefault("market", {})["vix_ema"] = args.vix_ema
    if args.base_currency:
        overrides["base_currency"] = args.base_currency
    params = load_params(args.config, overrides)
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else None
    return build_model(args.positions, args.securities, args.baskets, params, as_of)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marge", description="Risk-based portfolio margin calculator.")
    parser.add_argument("--version", action="version", version=f"marge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="compute the margin requirement of a portfolio")
    _common(run)
    run.add_argument("--json", help="write a JSON summary to this file ('-' for stdout)")
    run.add_argument("--detail-dir", help="write per-component breakdown CSVs to this directory")
    run.add_argument("--top", type=int, default=5, help="rows shown per breakdown in the text report")
    run.add_argument("--quiet", action="store_true", help="do not print the text report")

    chk = sub.add_parser("check", help="report data gaps in the inputs, ranked by exposure")
    _common(chk)
    chk.add_argument("--top", type=int, default=10, help="names listed per issue")

    lev = sub.add_parser("leverage", help="largest scale of the book that a given equity supports")
    _common(lev)
    lev.add_argument("--equity", type=float, required=True, help="account equity in base currency")

    args = parser.parse_args(argv)
    try:
        model = _load(args)
    except (InputError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        print(format_quality(data_quality(model, top=args.top)))
        return 0

    if args.command == "run":
        result = compute(model)
        if not args.quiet:
            print(text_report(result, model, top=args.top))
        if args.json:
            text = to_json(result, None if args.json == "-" else args.json, detail=True)
            if args.json == "-":
                print(text)
        if args.detail_dir:
            paths = write_details(result, model, args.detail_dir)
            print(f"\nwrote {len(paths)} breakdown files to {args.detail_dir}", file=sys.stderr)
        return 0

    base = compute(model)
    k, res = max_scale(model, args.equity)
    gmv = base.exposure["gross_market_value"]
    req = -base.total
    print(f"Current gross market value   {gmv:>18,.0f}")
    print(f"Current requirement          {req:>18,.0f}")
    print(f"Account equity               {args.equity:>18,.0f}")
    print(f"Excess / (deficit)           {args.equity - req:>18,.0f}")
    print(f"Leverage now (gross/equity)  {gmv / args.equity:>17,.2f}x")
    print(f"Max scale of current book    {k:>17,.3f}x")
    print(f"Max gross market value       {gmv * k:>18,.0f}")
    print(f"Max gross leverage           {gmv * k / args.equity:>17,.2f}x")
    if res is not None:
        print(f"Requirement at max scale     {-res.total:>18,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
