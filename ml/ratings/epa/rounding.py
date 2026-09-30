"""The reference's three rounding behaviours, reproduced exactly (spec §8).

They are not interchangeable, and the reference uses each at specific sites,
so the engine names the one it means at every output:

* reference_round -- utils/utils.py:33-34, r(x, n) = int(x*10**n + 0.5)/10**n.
  int() truncates toward zero, so for negative x the result is one unit high
  about half the time (r(-1.234, 2) == -1.22, not -1.23), and applying it
  again to an already-rounded negative value moves it up again
  (r(-1.22, 2) == -1.21). This is reproduced, not fixed: Level A parity
  requires the reference's stored values, bugs included.
* numpy_round -- np.round (round half to even on the scaled value), used for
  the recorded team EPA vectors (models/epa/main.py:175, 197), and reached
  implicitly by Python's round() on a numpy.float64.
* python_round -- the builtin round() on a Python float (correctly rounded
  decimal, ties to even), used for the rp fields of the per-match record
  (models/epa/main.py:182-184, 232-234).
"""

from __future__ import annotations

import numpy as np


def reference_round(x: float, n: int = 0) -> float:
    """The reference's r(): int(x * 10**n + 0.5) / 10**n, truncating toward zero."""
    return int(x * (10**n) + 0.5) / (10**n)


def numpy_round(x: float, n: int) -> float:
    """np.round of one float64 value, returned as a Python float."""
    return float(np.round(np.float64(x), n))


def python_round(x: float, n: int) -> float:
    """The builtin round() of the value converted to a Python float."""
    return round(float(x), n)
