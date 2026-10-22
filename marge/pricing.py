"""Vectorised Black-Scholes pricing used to revalue options under shocks."""

from __future__ import annotations

import math

import numpy as np

_erf = np.vectorize(math.erf, otypes=[float])
MIN_VOL = 0.01
MIN_T = 1e-6


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))


def norm_pdf(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(spot, strike, t, vol, rate, div):
    t = np.maximum(t, MIN_T)
    vol = np.maximum(vol, MIN_VOL)
    spot = np.maximum(spot, 1e-12)
    sqrt_t = np.sqrt(t)
    d1 = (np.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / (vol * sqrt_t)
    return d1, d1 - vol * sqrt_t


def bs_price(spot, strike, t, vol, rate, div, is_call) -> np.ndarray:
    """Black-Scholes price; expired options (t <= 0) are worth intrinsic."""
    spot, strike, t, vol = (np.asarray(a, dtype=float) for a in (spot, strike, t, vol))
    is_call = np.asarray(is_call, dtype=bool)
    d1, d2 = _d1_d2(spot, strike, t, vol, rate, div)
    tt = np.maximum(t, 0.0)
    df_r, df_q = np.exp(-rate * tt), np.exp(-div * tt)
    call = spot * df_q * norm_cdf(d1) - strike * df_r * norm_cdf(d2)
    put = strike * df_r * norm_cdf(-d2) - spot * df_q * norm_cdf(-d1)
    price = np.where(is_call, call, put)
    intrinsic = np.where(is_call, np.maximum(spot - strike, 0.0), np.maximum(strike - spot, 0.0))
    return np.where(t <= 0, intrinsic, price)


def bs_delta(spot, strike, t, vol, rate, div, is_call) -> np.ndarray:
    spot, strike, t, vol = (np.asarray(a, dtype=float) for a in (spot, strike, t, vol))
    is_call = np.asarray(is_call, dtype=bool)
    d1, _ = _d1_d2(spot, strike, t, vol, rate, div)
    df_q = np.exp(-div * np.maximum(t, 0.0))
    delta = np.where(is_call, df_q * norm_cdf(d1), df_q * (norm_cdf(d1) - 1.0))
    expired = np.where(is_call, (spot > strike).astype(float), -(spot < strike).astype(float))
    return np.where(t <= 0, expired, delta)


def bs_vega(spot, strike, t, vol, rate, div) -> np.ndarray:
    """Vega per 1.00 change in vol (divide by 100 for per vol point)."""
    spot, strike, t, vol = (np.asarray(a, dtype=float) for a in (spot, strike, t, vol))
    d1, _ = _d1_d2(spot, strike, t, vol, rate, div)
    return np.where(t <= 0, 0.0, spot * np.exp(-div * np.maximum(t, 0)) * norm_pdf(d1) * np.sqrt(np.maximum(t, 0)))
