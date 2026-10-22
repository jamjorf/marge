"""Default methodology parameters.

Every number the engine uses lives here so that a single config file can
override any of them (see ``marge.config``). Percentages are expressed as
decimals (0.05 == 5%) unless a name ends in ``_pts`` (volatility points).
"""

from __future__ import annotations

import copy

# ---------------------------------------------------------------------------
# Country classification
# ---------------------------------------------------------------------------

# Country group 1-3 = "core" markets, 4-5 = "non-core" markets. Countries that
# are not listed fall back to ``default_country_group``.
COUNTRY_GROUPS = {
    # Americas
    "United States": 1, "Canada": 3, "Mexico": 4, "Brazil": 4, "Argentina": 5,
    "Chile": 5, "Colombia": 5, "Peru": 5, "Venezuela": 5, "Uruguay": 5,
    "Panama": 5, "Costa Rica": 5, "Puerto Rico": 5, "Bermuda": 5,
    "Cayman Islands": 5, "British Virgin Islands": 5, "Bahamas": 5,
    # Western Europe
    "United Kingdom": 2, "France": 2, "Germany": 2, "Netherlands": 2,
    "Switzerland": 2, "Austria": 3, "Belgium": 3, "Denmark": 3, "Finland": 3,
    "Ireland": 3, "Italy": 3, "Luxembourg": 3, "Norway": 3, "Spain": 3,
    "Sweden": 3, "Portugal": 4, "Iceland": 4, "Jersey": 5, "Guernsey": 5,
    "Isle of Man": 5, "Gibraltar": 5, "Monaco": 5, "Liechtenstein": 5,
    "Malta": 5, "Cyprus": 5,
    # Central / Eastern Europe
    "Croatia": 4, "Czech Republic": 4, "Poland": 4, "Slovenia": 4,
    "Greece": 5, "Estonia": 5, "Hungary": 5, "Romania": 5,
    "Russian Federation": 5, "Slovakia": 5, "Turkey": 5, "Ukraine": 5,
    # Asia / Australia
    "Japan": 2, "Australia": 3, "New Zealand": 3, "Hong Kong": 3,
    "China Offshore": 3, "Singapore": 3, "Korea, Republic of": 3,
    "Taiwan, Province of China": 3, "China": 4, "India": 4, "Malaysia": 4,
    "Thailand": 4, "Indonesia": 5, "Pakistan": 5, "Philippines": 5,
    "Viet Nam": 5,
    # Middle East / Africa
    "Israel": 4, "South Africa": 4, "Bahrain": 4, "Oman": 4, "Kuwait": 5,
    "Qatar": 5, "Saudi Arabia": 5, "United Arab Emirates": 5, "Egypt": 5,
    "Morocco": 5, "Nigeria": 5,
}

# Alternative spellings accepted in input files (case-insensitive).
COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "great britain": "United Kingdom",
    "south korea": "Korea, Republic of", "korea": "Korea, Republic of", "kr": "Korea, Republic of",
    "taiwan": "Taiwan, Province of China", "tw": "Taiwan, Province of China",
    "china onshore": "China", "cn": "China", "china (onshore)": "China",
    "china (offshore)": "China Offshore", "hk": "Hong Kong",
    "russia": "Russian Federation", "vietnam": "Viet Nam", "czechia": "Czech Republic",
    "slovak republic": "Slovakia", "uae": "United Arab Emirates", "jp": "Japan",
    "de": "Germany", "fr": "France", "nl": "Netherlands", "ch": "Switzerland",
    "ca": "Canada", "au": "Australia", "ie": "Ireland", "in": "India", "br": "Brazil",
    "il": "Israel", "sg": "Singapore", "mx": "Mexico", "za": "South Africa",
    "türkiye": "Turkey", "turkiye": "Turkey",
}

# GICS industry groups treated as financials for the concentration rule.
FINANCIAL_SECTORS = {"Banks", "Financial Services", "Insurance", "Diversified Financials"}

DEFAULTS: dict = {
    "base_currency": "USD",
    "default_country_group": 5,
    # Market state used by the VIX-dependent rules.
    "market": {
        "vix": 15.0,       # spot VIX level
        "vix_ema": 15.0,   # 5-day exponential average of VIX (EAV)
        "rate": 0.04,      # flat rate used for option pricing
    },
    "fx_rates": {},        # local currency -> base currency multiplier

    # -----------------------------------------------------------------------
    # Equity: macro (global + country + asset)
    # -----------------------------------------------------------------------
    "macro": {
        "global_shocks": [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10],
        "extra_top_shock": 0.125,         # added when vix_ema > extra_top_vix
        "extra_top_vix": 30.0,
        "country_dispersion": {1: 0.02, 2: 0.05, 3: 0.075, 4: 0.10, 5: 0.15},
        "asset_dispersion": {1: 0.10, 2: 0.125, 3: 0.125, 4: 0.125, 5: 0.15},
        # Core (group 1-3) names above this market cap get the reduced shock.
        "large_cap_threshold": 150e9,
        "large_cap_asset_dispersion": 0.05,
        # Group 1 country dispersion at the top up-shock fades in with VIX:
        # 0% below vix_low, full at vix_high, linear in between.
        "group1_top_country_vix": [15.0, 30.0],
        # Relative vol shocks (low, mid, high) per group per global shock.
        "vol_shocks": {
            1: {-0.15: [-0.10, 0.40, 0.70], -0.10: [-0.30, 0.10, 0.70], -0.05: [-0.30, 0.10, 0.40],
                0.0: [-0.40, 0.0, 0.40], 0.05: [-0.40, 0.0, 0.20], 0.10: [-0.20, 0.0, 0.10],
                0.125: [-0.20, 0.0, 0.10]},
            2: {-0.15: [-0.10, 0.40, 0.70], -0.10: [-0.30, 0.10, 0.70], -0.05: [-0.30, 0.10, 0.60],
                0.0: [-0.40, 0.0, 0.40], 0.05: [-0.40, 0.0, 0.40], 0.10: [-0.20, 0.0, 0.25],
                0.125: [-0.20, 0.0, 0.25]},
            3: {-0.15: [-0.30, 0.40, 0.70], -0.10: [-0.30, 0.10, 0.70], -0.05: [-0.30, 0.10, 0.60],
                0.0: [-0.40, 0.0, 0.40], 0.05: [-0.40, 0.0, 0.40], 0.10: [-0.20, 0.0, 0.25],
                0.125: [-0.20, 0.0, 0.25]},
            4: {-0.15: [-0.10, 0.40, 0.70], -0.10: [-0.30, 0.10, 0.70], -0.05: [-0.30, 0.10, 0.60],
                0.0: [-0.40, 0.0, 0.40], 0.05: [-0.40, 0.0, 0.40], 0.10: [-0.30, 0.0, 0.40],
                0.125: [-0.30, 0.0, 0.40]},
            5: {-0.15: [-0.10, 0.40, 0.70], -0.10: [-0.30, 0.10, 0.70], -0.05: [-0.30, 0.10, 0.60],
                0.0: [-0.40, 0.0, 0.40], 0.05: [-0.40, 0.0, 0.40], 0.10: [-0.30, 0.0, 0.40],
                0.125: [-0.30, 0.0, 0.40]},
        },
        # The -10% "low" vol shock at -15% only applies when vix_ema > 30.
        "low_vol_at_crash_vix": 30.0,
        # Absolute vol-point equivalents of the relative shocks (Vol Map):
        # points = factor * relative shock * 100.
        "vol_map_up_factor": 0.4,
        "vol_map_down_factor": 0.5,
    },

    # -----------------------------------------------------------------------
    # Equity: sector (global + sector + asset)
    # -----------------------------------------------------------------------
    "sector": {
        "global_shocks": [-0.15, -0.10, -0.05, 0.0, 0.05],
        # Top up-shock: interpolated between these with vix_ema in [15, 30].
        "top_shock": [0.075, 0.10],
        "top_shock_vix": [15.0, 30.0],
        "extra_top_shock": 0.125,
        "extra_top_vix": 30.0,
        "sector_dispersion": 0.05,
        "asset_dispersion": 0.10,
        "large_cap_threshold": 150e9,
        "large_cap_asset_dispersion": 0.0,
        "vol_shocks": {-0.15: [0.10, 0.175, 0.375], -0.10: [0.10, 0.175, 0.375],
                       -0.05: [0.0, 0.15, 0.25], 0.0: [-0.20, 0.0, 0.20], 0.05: [-0.20, 0.0, 0.20],
                       "top": [-0.20, 0.0, 0.10]},
        "crash_vol_shocks_high_vix": [0.0, 0.15, 0.25],
        "vol_map_up_factor": 0.4,
        "vol_map_down_factor": 0.4,
    },

    # -----------------------------------------------------------------------
    # Equity: relative value
    # -----------------------------------------------------------------------
    "relative_value": {
        "spot_shocks": [-0.075, -0.05, -0.025, 0.025, 0.05, 0.075],
        "vol_shock_rel": 0.10,
        "vol_shock_cap_pts": 7.5,
        # Multiple listings (ADR/ORD, share classes): gains only offset losses
        # at this rate (i.e. 60% of the offset is charged).
        "listing_gain_credit": 0.40,
        "spot_basis_floor": {1: 0.0015, 2: 0.005, 3: 0.005, 4: 0.0125, 5: 0.0125},
    },

    # -----------------------------------------------------------------------
    # Equity: concentration (single name / seven names)
    # Buckets: market-cap upper bounds in USD.
    # -----------------------------------------------------------------------
    "concentration": {
        "bucket_bounds": [5e6, 200e6, 500e6, 1e9, 5e9, 150e9],
        "group2_bucket_bounds": [5e6, 200e6, 500e6, 1e9, 5e9, 50e9],
        "financial_cap_threshold": 150e9,
        "financial_cap_threshold_group2": 50e9,
        "seven_name_count": 7,
        # [down spot, down vol (relative), up spot] for each of 7 buckets
        "single": {
            "core":     [[-1.00, 0.50, 8.00], [-1.00, 0.50, 4.00], [-1.00, 0.50, 1.50],
                         [-0.80, 0.50, 1.00], [-0.45, 0.50, 0.60], [-0.40, 0.40, 0.50],
                         [-0.25, 0.30, 0.25]],
            "non_core": [[-1.00, 0.75, 8.00], [-1.00, 0.75, 4.00], [-1.00, 0.75, 2.50],
                         [-1.00, 0.75, 1.50], [-0.70, 0.50, 0.90], [-0.60, 0.50, 0.75],
                         [-0.25, 0.30, 0.25]],
        },
        "seven": {
            "core":     [[-0.70, 0.40, 4.00], [-0.55, 0.40, 1.50], [-0.45, 0.40, 0.60],
                         [-0.35, 0.40, 0.45], [-0.30, 0.30, 0.35], [-0.25, 0.30, 0.20],
                         [-0.15, 0.20, 0.15]],
            "non_core": [[-1.00, 0.50, 4.00], [-0.80, 0.50, 1.50], [-0.70, 0.50, 1.00],
                         [-0.55, 0.50, 0.70], [-0.45, 0.50, 0.55], [-0.40, 0.40, 0.45],
                         [-0.15, 0.20, 0.15]],
        },
        # Non-core names above the top threshold use the bucket below unless
        # this is switched on (requires risk approval in the methodology).
        "non_core_large_cap_relief": False,
    },

    # -----------------------------------------------------------------------
    # Equity: theta
    # -----------------------------------------------------------------------
    "theta": {"days": 5},

    # -----------------------------------------------------------------------
    # Equity: liquidity
    # -----------------------------------------------------------------------
    "liquidity": {
        "rate_per_day": 0.05,
        "free_days": 1.0,
        "long_cap": 1.00,
        "short_cap": 3.00,
        # What to do when ADV is missing: "ignore" (no charge) or "max" (full cap).
        "missing_adv": "ignore",
        "otc_price_threshold": 5.0,
        "otc_short_min_price": 2.5,
        "otc_long_rate": 0.5,
        "etf_redemption_liquid": 0.0020,
        "etf_redemption_illiquid": 0.0060,
        "etf_home_country": "United States",
    },

    # -----------------------------------------------------------------------
    # Equity: option liquidity (bid/ask + concentration + term + skew)
    # -----------------------------------------------------------------------
    "option_liquidity": {
        "bid_ask_factor": {"I1": 0.5, "I2": 0.96, "I3": 1.92, "S0": 0.26, "S1": 0.5,
                           "S2": 1.5, "S3": 3.72, "S4": 8.1},
        "vega_tenor_exponent": 0.4,
        # Table 11: (alpha, beta) relative and absolute
        "concentration_rel": {"I1": [0.25, 0.4248], "I2": [0.31, 0.454], "I3": [0.62, 0.454],
                              "S0": [0.30, 0.466], "S1": [0.30, 0.598], "S2": [0.72, 0.353],
                              "S3": [0.91, 0.315], "S4": [1.63, 0.337]},
        "concentration_abs": {"I1": [12.8, 0.28], "I2": [15.42, 0.30], "I3": [31.0, 0.30],
                              "S0": [22.47, 0.24], "S1": [48.12, 0.33], "S2": [54.52, 0.32],
                              "S3": [64.57, 0.36], "S4": [102.76, 0.36]},
        # Table 12: min/max 90-day ATM vol after shock (vol points)
        "vol_bounds": {"I1": [13.07, 70.18], "I2": [13.07, 101.13], "I3": [13.07, 101.13],
                       "S0": [12.42, 146.4], "S1": [12.42, 258.87], "S2": [12.42, 264.68],
                       "S3": [12.42, 287.15], "S4": [12.42, 439.68]},
        # Table 13a (US) daily vega thresholds in USD by tenor bucket (years)
        "vega_threshold_tenors": [1 / 12, 0.25, 0.5, 1.0, 2.0],
        "vega_threshold": {"I1": [10e6, 40e6, 15e6, 10e6, 5e6], "I2": [80e3, 200e3, 180e3, 40e3, 40e3],
                           "I3": [20e3, 30e3, 15e3, 10e3, 10e3], "S0": [2.5e6, 3e6, 1e6, 500e3, 500e3],
                           "S1": [100e3, 100e3, 80e3, 30e3, 30e3], "S2": [100e3, 100e3, 40e3, 20e3, 15e3],
                           "S3": [100e3, 100e3, 40e3, 10e3, 10e3], "S4": [5e3, 10e3, 5e3, 5e3, 5e3]},
        "days_to_trade_cap": 30.0,
        # Table 14/15: term structure (alpha, beta) by tenor 1m, 6m, 1y, 2y
        "term_tenors": [1 / 12, 0.5, 1.0, 2.0],
        "term_rel": {"I1": [[-0.17, 0.28], [0.05, 0.26], [0.06, 0.57], [0.09, 0.40]],
                     "I2": [[-0.18, 0.45], [0.17, 0.16], [0.21, 0.27], [0.376, 0.121]],
                     "I3": [[-0.587, 0.105], [0.239, 0.214], [0.252, 0.273], [0.387, 0.557]],
                     "S0": [[-0.164, 0.411], [0.084, 0.339], [0.099, 0.313], [0.113, 0.462]],
                     "S1": [[-0.312, 0.415], [0.127, 0.399], [0.224, 0.183], [0.189, 0.518]],
                     "S2": [[-0.79, 0.32], [0.39, 0.30], [0.51, 0.22], [0.72, 0.21]],
                     "S3": [[-1.508, 0.166], [0.614, 0.255], [0.77, 0.19], [0.809, 0.20]],
                     "S4": [[-1.982, 0.262], [1.277, 0.213], [1.431, 0.185], [1.504, 0.243]]},
        "term_abs": {"I1": [[-3.75, 0.51], [1.26, 0.62], [1.6, 0.76], [2.78, 0.37]],
                     "I2": [[-7.66, 0.58], [7.35, 0.24], [2.73, 0.91], [4.56, 0.8]],
                     "I3": [[-33.0, 0.06], [11.84, 0.03], [12.26, 0.14], [20.54, 0.01]],
                     "S0": [[-9.11, 0.29], [3.72, 0.29], [4.32, 0.34], [4.95, 0.47]],
                     "S1": [[-51.66, 0.25], [24.89, 0.11], [21.34, 0.22], [29.61, 0.29]],
                     "S2": [[-52.57, 0.29], [23.93, 0.24], [30.31, 0.11], [34.42, 0.16]],
                     "S3": [[-77.68, 0.22], [41.72, 0.11], [47.35, 0.15], [50.15, 0.2]],
                     "S4": [[-140.92, 0.25], [84.99, 0.22], [93.73, 0.24], [96.35, 0.28]]},
        "term_down_floor_pts": 5.0,
        # Table 16: skew (alpha, beta) as multiple of ATM vol
        "skew": {"I1": [0.168, 0.199], "I2": [0.28, 0.07], "I3": [0.618, 0.109], "S0": [0.214, 0.369],
                 "S1": [0.509, 0.653], "S2": [0.884, 0.059], "S3": [0.868, 0.219], "S4": [1.384, 0.169]},
        "index_i1": ["SPY", "SPX", "OEX", "DIA", "DJIA", "MDY", "MID", "IWM", "RUT", "RTY", "IWB",
                     "IWV", "QQQ", "NDX", "RUA", "RAY", "SML"],
        "index_i2": ["XLB", "XLE", "XLF", "XLG", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "EFA",
                     "EEM", "EWJ"],
    },

    # Vol surface relative-value scenario (Tables 4, 6, 7)
    "vol_surface": {
        "atm_3m": {"I1": [0.175, 7.0], "I2": [0.20, 8.0], "I3": [0.40, 16.0], "S0": [0.20, 8.0],
                   "S1": [0.25, 10.0], "S2": [0.40, 16.0], "S3": [0.504, 20.1], "S4": [0.95, 38.0]},
        "term_tenors": [1 / 12, 0.5, 1.0, 2.0],
        "term_rel": {"I1": [-0.0796, 0.0278, 0.0419, 0.049], "I2": [-0.194, 0.0568, 0.0574, 0.0653],
                     "I3": [-0.3492, 0.0758, 0.0718, 0.1415], "S0": [-0.1552, 0.0379, 0.0287, 0.0326],
                     "S1": [-0.3104, 0.0568, 0.0574, 0.0653], "S2": [-0.6983, 0.1516, 0.1436, 0.1415],
                     "S3": [-1.0, 0.2274, 0.201, 0.1632], "S4": [-1.0, 0.4547, 0.3733, 0.3156]},
        "term_abs": {"I1": [-1.94, 0.7, 1.05, 1.23], "I2": [-7.76, 2.27, 2.3, 2.61],
                     "I3": [-13.97, 3.03, 2.87, 5.66], "S0": [-6.21, 1.52, 1.15, 1.31],
                     "S1": [-12.41, 2.27, 2.3, 2.61], "S2": [-27.93, 6.06, 5.74, 5.66],
                     "S3": [-40.35, 9.09, 8.04, 6.53], "S4": [-62.07, 18.19, 14.93, 12.62]},
        "skew": {"I1": [0.075, 3.0], "I2": [0.10, 4.0], "I3": [0.25, 10.0], "S0": [0.125, 5.0],
                 "S1": [0.25, 10.0], "S2": [0.35, 14.0], "S3": [0.40, 16.0], "S4": [0.60, 24.0]},
    },

    # -----------------------------------------------------------------------
    # FX
    # -----------------------------------------------------------------------
    "fx": {
        "base_shock": {"AUD": 0.10, "EUR": 0.04, "GBP": 0.06, "HKD": 0.05, "JPY": 0.11,
                       "SEK": 0.05, "SGD": 0.03, "USD": 0.05},
        "default_base_shock": 0.05,
        "currencies_per_side": 2,
        "other_currency_shock": 0.25,
        "stable_pegs": ["HKD", "DKK", "SGD", "CNY", "CNH"],
        "stable_peg_shock": 0.15,
        "risky_pegs": ["AED", "BGN", "MYR", "QAR", "SAR"],
        "risky_peg_shock": 0.30,
        # (down, up) shock in % for each currency against each base currency.
        "pair_shocks": None,  # filled from FX_PAIR_SHOCKS below
    },

    # -----------------------------------------------------------------------
    # Flat-rate add-ons for products the stress test does not cover
    # -----------------------------------------------------------------------
    "flat_rate": {"long": 1.0, "short_multiple": 3.0, "short_min_price": 2.5},

    # -----------------------------------------------------------------------
    # Top-level aggregation
    # -----------------------------------------------------------------------
    "aggregation": {"top_n": 2},
}

_FX_BASES = ["AUD", "EUR", "GBP", "HKD", "JPY", "SEK", "SGD", "USD"]
_FX_ROWS = """
AUD 0 0 -8 8 -9 7 -14 8 -21 11 -14 8 -12 7 -13 8
BRL -10 13 -11 11 -10 9 -13 9 -18 12 -16 12 -11 10 -12 9
CAD -6 7 -5 7 -5 7 -8 6 -14 9 -6 6 -6 6 -8 6
CHF -4 16 -4 18 -6 17 -5 16 -6 16 -5 19 -4 16 -5 16
CLP -7 9 -7 7 -8 8 -9 7 -15 9 -10 11 -8 6 -9 7
CNH -8 15 -7 6 -5 8 -2 2 -6 5 -8 8 -3 3 -3 2
CNO -8 15 -7 6 -5 8 -2 2 -6 5 -8 8 -3 3 -3 2
CNY -8 15 -7 6 -5 8 -2 2 -6 5 -8 8 -3 3 -3 2
COP -11 11 -11 8 -12 8 -9 8 -13 11 -11 10 -9 7 -9 8
CZK -7 10 -5 5 -6 8 -9 7 -12 10 -5 6 -7 6 -9 7
DKK -9 9 -1 1 -8 6 -7 7 -13 7 -5 6 -5 5 -7 7
EUR -8 8 0 0 -6 6 -7 7 -10 6 -5 6 -4 4 -6 7
GBP -7 9 -6 6 0 0 -8 6 -12 7 -8 7 -7 6 -8 6
HKD -8 15 -7 6 -5 8 0 0 -7 5 -8 9 -3 3 -1 1
HUF -9 11 -7 8 -10 9 -10 9 -15 11 -7 7 -8 7 -10 9
IDR -15 13 -11 6 -10 9 -9 9 -10 9 -13 8 -10 6 -9 9
ILS -9 13 -5 6 -7 7 -6 5 -10 6 -7 7 -5 4 -6 5
INR -4 4 -6 4 -6 4 -5 4 -7 4 -6 5 -4 3 -5 4
JPY -11 21 -6 11 -7 12 -5 7 0 0 -10 14 -6 9 -5 7
KRW -9 10 -10 11 -9 11 -12 12 -18 15 -11 12 -11 12 -12 12
MXN -9 9 -9 7 -11 8 -12 8 -16 10 -13 7 -10 8 -12 8
MYR -4 4 -7 5 -5 5 -4 5 -7 5 -7 4 -4 3 -4 5
NOK -10 10 -6 6 -7 8 -9 7 -13 9 -5 4 -8 6 -9 7
NZD -4 5 -7 7 -8 7 -11 9 -17 10 -9 7 -10 7 -11 9
PEN -9 13 -6 6 -6 8 -5 4 -8 6 -6 8 -4 4 -5 4
PHP -8 12 -5 5 -5 7 -3 3 -8 6 -8 6 -3 4 -3 3
PLN -9 8 -8 8 -8 8 -12 9 -15 13 -9 7 -11 8 -12 9
RUB -10 12 -9 5 -11 7 -9 5 -11 7 -10 7 -9 5 -9 5
SAR -8 14 -7 7 -6 9 -1 1 -7 5 -8 9 -3 3 -1 1
SEK -8 10 -6 5 -7 8 -8 7 -13 8 0 0 -7 7 -8 7
SGD -7 11 -5 4 -6 7 -3 3 -8 5 -7 6 0 0 -3 3
THB -5 5 -7 4 -6 4 -6 6 -9 5 -6 5 -6 5 -6 6
TRY -18 11 -18 9 -18 10 -20 11 -20 11 -19 10 -19 9 -20 11
TWD -8 12 -5 5 -5 7 -3 3 -8 6 -7 7 -2 2 -3 3
USD -8 15 -7 6 -6 8 -1 1 -7 5 -8 9 -3 3 0 0
ZAR -13 9 -10 9 -10 11 -11 10 -16 12 -9 11 -11 8 -11 10
"""


def _parse_fx_rows() -> dict:
    table: dict = {base: {} for base in _FX_BASES}
    for line in _FX_ROWS.strip().splitlines():
        parts = line.split()
        ccy, nums = parts[0], [float(x) / 100.0 for x in parts[1:]]
        for i, base in enumerate(_FX_BASES):
            table[base][ccy] = [nums[2 * i], nums[2 * i + 1]]
    return table


FX_PAIR_SHOCKS = _parse_fx_rows()
DEFAULTS["fx"]["pair_shocks"] = FX_PAIR_SHOCKS


def default_params() -> dict:
    """Return a deep copy of the default parameter tree."""
    return copy.deepcopy(DEFAULTS)
