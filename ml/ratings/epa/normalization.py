"""Year-normalized EPA (spec §7.3; reference models/epa/unitless.py:15-61).

Kept apart from the core on purpose. The raw EPA and every per-match value
are exact functions of the inputs; norm_epa is not, in three ways:

1. It is fitted with scipy maximum-likelihood fits (exponnorm.fit, expon.fit),
   an iterative optimizer whose result can move between scipy versions. The
   reference pins scipy ^1.11.1 with numpy 1.26.4; the version used here is
   recorded in every manifest, and exact norm parity needs the pinned
   version. That is a validation environment requirement, not a property of
   the rating math.
2. It is a year-end, look-ahead quantity: the fit uses every team's final
   EPA of the season. It must never be used as a point-in-time feature.
3. It depends on the TeamYear universe the fit sees. The reference fits over
   every registered team of the season; STRATAI sees only teams that appear
   in a match (data contract §8.2).

Unitless EPA (a fixed affine map of the week-1 statistics) has none of these
problems and lives in ml.ratings.epa.aggregate.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Sequence

from ml.ratings.epa.constants import NORM_MEAN, NORM_SD

NormFunction = Callable[[float], float]


def scipy_version() -> str | None:
    try:
        import scipy
    except ImportError:
        return None
    return str(scipy.__version__)


def epa_to_norm_epa_func(year_epas: Sequence[float]) -> NormFunction | None:
    """get_epa_to_norm_epa_func, line for line. None when there is nothing to fit."""
    from scipy.stats import expon, exponnorm

    distrib = exponnorm(1.6, -0.3, 0.2)
    desc_sorted_epas = sorted(year_epas, reverse=True)
    total_n, cutoff_n = len(desc_sorted_epas), int(len(desc_sorted_epas) / 10)
    if total_n == 0:
        return None
    exponnorm_distrib = exponnorm(*exponnorm.fit(desc_sorted_epas))
    expon_distrib = expon(*expon.fit(desc_sorted_epas[:cutoff_n])) if cutoff_n > 0 else None
    sorted_epas = desc_sorted_epas[::-1]

    def _get_norm_epa(epa: float) -> float:
        i = total_n - bisect_left(sorted_epas, epa)
        exponnorm_value: float = exponnorm_distrib.cdf(epa)
        percentile = exponnorm_value
        if i < cutoff_n:
            expon_value: float = expon_distrib.cdf(epa)  # type: ignore[union-attr]
            expon_value = 1 - cutoff_n / total_n * (1 - expon_value)
            # linearly interpolate between the two distributions from 10% to 5%
            expon_frac = min(1, 2 * (cutoff_n - i) / cutoff_n)
            percentile = expon_frac * expon_value + (1 - expon_frac) * exponnorm_value
        out: float = distrib.ppf(percentile)
        return NORM_MEAN + NORM_SD * out

    quantiles = [sorted_epas[((total_n - 1) * i) // 100] for i in range(101)]
    quantile_norm_epas = [_get_norm_epa(epa) for epa in quantiles]

    def get_norm_epa(epa: float) -> float:
        i = bisect_left(quantiles, epa)
        if i == 0:
            return quantile_norm_epas[0]
        if i == 101:
            return quantile_norm_epas[100]
        x0, x1 = quantiles[i - 1], quantiles[i]
        y0, y1 = quantile_norm_epas[i - 1], quantile_norm_epas[i]
        return y0 + (y1 - y0) * (epa - x0) / (x1 - x0)

    return get_norm_epa
