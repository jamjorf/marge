"""Three-level stress tree shared by the macro and sector scenarios.

For a global shock ``g`` every asset is shocked by ``g``, then each bucket
(country or sector) is shocked up and down by its dispersion ``d``, and from
the worse bucket node each asset is shocked up and down by its own
dispersion ``a``::

    Global loss  = min(0, sum of core P&L) + sum over non-core buckets of min(0, bucket P&L)
    Bucket loss  = SRSS over buckets of the worse incremental bucket move
    Asset loss   = SRSS over assets of the worse incremental asset move
    Scenario     = Global + Bucket + Asset

Core buckets (country groups 1-3) are charged for both directions. For
non-core buckets only losses count and the dispersion moves in the direction
of the global shock (both directions when the global shock is zero).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import Model


@dataclass
class TreeResult:
    shock: float
    global_loss: float
    bucket_loss: float
    asset_loss: float
    bucket_global: np.ndarray      # P&L per bucket at the global node
    bucket_disp: np.ndarray        # charged incremental loss per bucket (<= 0)
    bucket_up: np.ndarray          # incremental P&L per bucket, up node
    bucket_down: np.ndarray        # incremental P&L per bucket, down node
    bucket_dir: np.ndarray         # +1 / -1 chosen direction per bucket
    asset_global: np.ndarray       # P&L per asset at the global node
    asset_disp: np.ndarray         # charged incremental loss per asset (<= 0)

    @property
    def total(self) -> float:
        return self.global_loss + self.bucket_loss + self.asset_loss


def _srss_loss(losses: np.ndarray) -> float:
    return -float(np.sqrt(np.sum(np.minimum(losses, 0.0) ** 2)))


def run_tree(model: Model, g: float, dvol, a_bucket: np.ndarray, b_core: np.ndarray,
             b_disp: np.ndarray, a_disp: np.ndarray) -> TreeResult:
    n_b = len(b_core)
    a_core = b_core[a_bucket]
    l_bucket = a_bucket[model.l_asset]

    p0 = model.by_asset(model.line_pnl(g, dvol))
    core_sum = float(p0[a_core].sum())
    b_glob = np.bincount(a_bucket, weights=p0, minlength=n_b)
    global_loss = min(0.0, core_sum) + float(np.minimum(b_glob[~b_core], 0.0).sum())

    d_line = b_disp[l_bucket]
    pu = model.by_asset(model.line_pnl(g + d_line, dvol))
    pd_ = model.by_asset(model.line_pnl(g - d_line, dvol))
    bu = np.bincount(a_bucket, weights=pu - p0, minlength=n_b)
    bd = np.bincount(a_bucket, weights=pd_ - p0, minlength=n_b)
    direction = np.where(bu <= bd, 1, -1)
    if g > 0:
        direction = np.where(b_core, direction, 1)
    elif g < 0:
        direction = np.where(b_core, direction, -1)
    b_loss = np.minimum(np.where(direction == 1, bu, bd), 0.0)

    a_dir = direction[a_bucket]
    node = np.where(a_dir == 1, pu, pd_)
    s0 = g + direction[l_bucket] * d_line
    a_line = a_disp[model.l_asset]
    au = model.by_asset(model.line_pnl(s0 + a_line, dvol)) - node
    ad = model.by_asset(model.line_pnl(s0 - a_line, dvol)) - node
    worst = np.minimum(au, ad)
    if g > 0:
        worst = np.where(a_core, worst, au)
    elif g < 0:
        worst = np.where(a_core, worst, ad)
    a_loss = np.minimum(worst, 0.0)

    return TreeResult(shock=g, global_loss=global_loss, bucket_loss=_srss_loss(b_loss),
                      asset_loss=_srss_loss(a_loss), bucket_global=b_glob, bucket_disp=b_loss,
                      bucket_up=bu, bucket_down=bd, bucket_dir=direction, asset_global=p0,
                      asset_disp=a_loss)


def fade(level: float, lo: float, hi: float) -> float:
    """0 below ``lo``, 1 above ``hi``, linear in between."""
    if hi <= lo:
        return 1.0 if level >= hi else 0.0
    return float(min(max((level - lo) / (hi - lo), 0.0), 1.0))
