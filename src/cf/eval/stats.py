"""Small, dependency-free statistics for evaluation reports.

Unit of resampling = the session (turns and trials inside a session are correlated), so every
interval is a session-cluster bootstrap or a Wilson interval on session-level outcomes.
"""

from __future__ import annotations

import math
import random


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap(values: list[float], b: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95% percentile interval, resampling the given (session-level) values."""
    vals = [v for v in values if v is not None]
    if not vals:
        return (float("nan"), float("nan"), float("nan"))
    rnd = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(b))
    return (sum(vals) / n, means[int(0.025 * b)], means[int(0.975 * b) - 1])


def paired(a: dict, b: dict, nboot: int = 2000, seed: int = 0) -> dict:
    """Paired difference a − b over the sessions both have: mean, 95% interval, and the bootstrap
    share of resamples with difference ≤ 0 (a one-sided p-value for 'a is better')."""
    keys = sorted(set(a) & set(b))
    diffs = [a[k] - b[k] for k in keys if a[k] is not None and b[k] is not None]
    if not diffs:
        return {"n": 0}
    rnd = random.Random(seed)
    n = len(diffs)
    boots = sorted(sum(diffs[rnd.randrange(n)] for _ in range(n)) / n for _ in range(nboot))
    return {"n": n, "diff": sum(diffs) / n, "lo": boots[int(0.025 * nboot)], "hi": boots[int(0.975 * nboot) - 1],
            "p_le0": sum(x <= 0 for x in boots) / nboot}
