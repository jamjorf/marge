"""Configuration loading.

A run is configured by an optional TOML file whose tables mirror the tree in
``marge.params.DEFAULTS``. Only the keys you set are overridden; everything
else keeps its default. Example::

    base_currency = "USD"

    [market]
    vix = 16.2
    vix_ema = 15.8

    [fx_rates]
    EUR = 1.08
    JPY = 0.0067

    [country_groups]
    "Puerto Rico" = 1
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .params import COUNTRY_GROUPS, default_params


def _coerce_key(key, template: dict):
    """Map a TOML string key onto the key type used by the default table."""
    if key in template or not isinstance(key, str):
        return key
    for existing in template:
        if isinstance(existing, int) and not isinstance(existing, bool):
            try:
                if int(key) == existing:
                    return existing
            except ValueError:
                pass
        elif isinstance(existing, float):
            try:
                if abs(float(key) - existing) < 1e-12:
                    return existing
            except ValueError:
                pass
    # New numeric keys in a numeric-keyed table keep the numeric type.
    if template and all(isinstance(k, (int, float)) and not isinstance(k, bool) for k in template):
        try:
            value = float(key)
            return int(value) if value.is_integer() and all(isinstance(k, int) for k in template) else value
        except ValueError:
            pass
    return key


def merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (in place) and return it."""
    for key, value in override.items():
        key = _coerce_key(key, base)
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def load_params(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Build the parameter tree from defaults, an optional TOML file and a dict."""
    params = default_params()
    params["country_groups"] = dict(COUNTRY_GROUPS)
    if path:
        with open(path, "rb") as fh:
            merge(params, tomllib.load(fh))
    if overrides:
        merge(params, overrides)
    params["base_currency"] = str(params["base_currency"]).upper()
    params["fx_rates"] = {str(k).upper(): float(v) for k, v in params.get("fx_rates", {}).items()}
    params["country_groups"] = {str(k): int(v) for k, v in params["country_groups"].items()}
    return params
