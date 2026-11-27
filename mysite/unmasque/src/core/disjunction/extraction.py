"""Extraction core primitives/scaffolding (spec B3.4-B3.5, B5, B7 foundations).

Step 3: pure/testable helpers for gap/probe/refine/search logic plus
dependency-injected scaffolds for necessity, try_null, EXTRACT_ATOMS, and
PATTERN_KILL. Not wired into legacy pipelines by default.
"""

import copy
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from .model import Atom


def _intervals_of(atom: Atom):
    if atom is None:
        return []
    if atom.kind == "text":
        # Text atoms represented as equality/like; callers should avoid numeric gaps over them.
        return []
    return list(atom.intervals or [])


def _normalize_intervals(intervals: Sequence[Tuple[Any, Any]]):
    ints = sorted([(lo, hi) for lo, hi in intervals], key=lambda x: x[0])
    merged = []
    for lo, hi in ints:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        elif hi > merged[-1][1]:
            merged[-1][1] = hi
    return [(lo, hi) for lo, hi in merged]


def gap(x: str, v: Any, own_atoms: Sequence[Atom], domain_lo: Any, domain_hi: Any):
    """Return (g_lo, g_hi): maximal interval around v in domain not covered by known atoms on x.

    `own_atoms` are known atoms of the current clause (B3.4). Overlap is treated
    conservatively by considering touching/covering known intervals as excluded.
    """
    covered = []
    for atom in own_atoms or []:
        if getattr(atom, "col", None) != x:
            continue
        covered.extend(_intervals_of(atom))
    covered = _normalize_intervals(covered)

    g_lo, g_hi = domain_lo, domain_hi
    for lo, hi in covered:
        # value inside a known interval -> no gap around it for adding a new atom
        if lo <= v <= hi:
            return (v, v)
        if hi < v and hi >= g_lo:
            g_lo = hi
        if lo > v and lo <= g_hi:
            g_hi = lo
    # If bounds collapsed onto a covered edge marker, keep valid ordering.
    if g_lo > g_hi:
        return (v, v)
    # If v fell exactly on an excluded boundary marker, treat as no usable gap.
    if g_lo == v and any(hi == v for _, hi in covered):
        return (v, v)
    if g_hi == v and any(lo == v for lo, _ in covered):
        return (v, v)
    return (g_lo, g_hi)


def quantize(value: Any, step: Any):
    """Best-effort quantization of numeric-like values to step multiples."""
    if step in (None, 0):
        return value
    try:
        # integers / floats / decimals
        q = round(value / step) * step
        # preserve int type when exact
        if isinstance(value, int) and float(q).is_integer():
            return int(q)
        return q
    except Exception:
        return value


def probes(
    x: str,
    lo: Any,
    hi: Any,
    step: Any = 1,
    k_interior: int = 8,
    distinct_values: Optional[Sequence[Any]] = None,
    max_distinct: int = 32,
    include_bounds: bool = True,
):
    """Generate probe values in [lo, hi] (B3.5 scaffold).

    Deterministic, deduplicated, quantized to step when possible.
    """
    if lo > hi:
        lo, hi = hi, lo
    vals: List[Any] = []
    if include_bounds:
        vals.extend([lo, hi])

    # Interior evenly spaced points
    try:
        if k_interior > 0 and hi != lo:
            span = hi - lo
            for i in range(1, k_interior + 1):
                vals.append(lo + (span * i) / (k_interior + 1))
    except Exception:
        pass

    # Distinct values from data (sampled evenly)
    if distinct_values:
        dvals = [v for v in distinct_values if v is not None and lo <= v <= hi]
        # deterministic subsample
        if len(dvals) > max_distinct:
            idxs = [int(i * (len(dvals) - 1) / (max_distinct - 1)) for i in range(max_distinct)]
            dvals = [dvals[i] for i in sorted(set(idxs))]
        vals.extend(dvals)

    out = []
    seen = set()
    for v in vals:
        qv = quantize(v, step)
        # clamp
        if qv < lo:
            qv = lo
        if qv > hi:
            qv = hi
        key = qv
        if key in seen:
            continue
        seen.add(key)
        out.append(qv)
    return out


@dataclass
class NecessityResult:
    necessary: bool
    witness: Any = None  # value where SAT_at is UNSAT, if any
    inconclusive: bool = False


def is_necessary(
    x: str,
    lo: Any,
    hi: Any,
    sat_at: Callable[[str, Any], Any],
    probe_values: Sequence[Any],
):
    """Necessity test (B5.1): True if any probe is UNSAT."""
    inconclusive = False
    for v in probe_values:
        r = sat_at(x, v)
        # Accept bool or tri-state strings/objects
        if r is False or r == "UNSAT":
            return NecessityResult(True, witness=v, inconclusive=inconclusive)
        if r is None or r == "INCONCLUSIVE":
            inconclusive = True
            continue
        # True/SAT -> continue
    return NecessityResult(False, witness=None, inconclusive=inconclusive)


def _plus(v: Any, step: Any, k: int = 1):
    try:
        return v + (step * k)
    except Exception:
        return v


def _sat_bool(res: Any) -> Optional[bool]:
    if res is True or res == "SAT":
        return True
    if res is False or res == "UNSAT":
        return False
    return None


def _bsearch_smallest_sat(x, lo, hi, sat_at, step):
    """Smallest SAT in [lo, hi] assuming sat_at(hi) SAT; fallback to hi."""
    left, right = lo, hi
    ans = hi
    # numeric discrete/continuous-ish search via midpoint quantization
    for _ in range(64):
        if left > right:
            break
        mid = quantize(left + (right - left) / 2, step) if not isinstance(left, int) else (left + right) // 2
        if mid < left:
            mid = left
        if mid > right:
            mid = right
        r = _sat_bool(sat_at(x, mid))
        if r is True:
            ans = mid
            if mid == left:
                break
            prev = _plus(mid, step, -1)
            if prev < left:
                prev = left
            right = prev
        elif r is False:
            nxt = _plus(mid, step, 1)
            if nxt > right:
                nxt = right
            if nxt == mid:
                break
            left = nxt
        else:
            # inconclusive: try to move inward conservatively
            nxt = _plus(mid, step, 1)
            if nxt <= right:
                left = nxt
            else:
                break
    return ans


def _bsearch_largest_sat(x, lo, hi, sat_at, step):
    """Largest SAT in [lo, hi] assuming sat_at(lo) SAT; fallback to lo."""
    left, right = lo, hi
    ans = lo
    for _ in range(64):
        if left > right:
            break
        mid = quantize(left + (right - left) / 2, step) if not isinstance(left, int) else (left + right) // 2
        if mid < left:
            mid = left
        if mid > right:
            mid = right
        r = _sat_bool(sat_at(x, mid))
        if r is True:
            ans = mid
            if mid == right:
                break
            nxt = _plus(mid, step, 1)
            if nxt > right:
                nxt = right
            left = nxt
        elif r is False:
            prev = _plus(mid, step, -1)
            if prev < left:
                prev = left
            if prev == mid:
                break
            right = prev
        else:
            prev = _plus(mid, step, -1)
            if prev >= left:
                right = prev
            else:
                break
    return ans


def _bsearch_leftmost_unsat(x, lo, hi, sat_at, step):
    left, right = lo, hi
    ans = hi
    for _ in range(64):
        if left > right:
            break
        mid = quantize(left + (right - left) / 2, step) if not isinstance(left, int) else (left + right) // 2
        if mid < left:
            mid = left
        if mid > right:
            mid = right
        r = _sat_bool(sat_at(x, mid))
        if r is False:
            ans = mid
            prev = _plus(mid, step, -1)
            if prev < left:
                break
            right = prev
        else:
            nxt = _plus(mid, step, 1)
            if nxt > right:
                break
            left = nxt
    return ans


def _bsearch_rightmost_unsat(x, lo, hi, sat_at, step):
    left, right = lo, hi
    ans = lo
    for _ in range(64):
        if left > right:
            break
        mid = quantize(left + (right - left) / 2, step) if not isinstance(left, int) else (left + right) // 2
        if mid < left:
            mid = left
        if mid > right:
            mid = right
        r = _sat_bool(sat_at(x, mid))
        if r is False:
            ans = mid
            nxt = _plus(mid, step, 1)
            if nxt > right:
                break
            left = nxt
        else:
            prev = _plus(mid, step, -1)
            if prev < left:
                break
            right = prev
    return ans


def refine(x: str, lo: Any, hi: Any, sat_at: Callable[[str, Any], Any], probe_values: Sequence[Any], step: Any = 1):
    """Verify contiguity on probes and split on UNSAT holes (B7 scaffold)."""
    if lo > hi:
        return []
    for u in probe_values:
        if u < lo or u > hi:
            continue
        if _sat_bool(sat_at(x, u)) is False:
            # find contiguous UNSAT run around u within (lo,hi)
            left_bound = _plus(lo, step, 1) if lo != hi else lo
            right_bound = _plus(hi, step, -1) if lo != hi else hi
            if left_bound > right_bound:
                left_bound, right_bound = lo, hi
            fl = _bsearch_leftmost_unsat(x, max(lo, left_bound), min(hi, u), sat_at, step)
            fr = _bsearch_rightmost_unsat(x, max(lo, u), min(hi, right_bound), sat_at, step)
            left_part = refine(x, lo, _plus(fl, step, -1), sat_at, probe_values, step)
            right_part = refine(x, _plus(fr, step, 1), hi, sat_at, probe_values, step)
            return _normalize_intervals(left_part + right_part)
    return [(lo, hi)]


def search_atom_numeric(
    table: str,
    col: str,
    lo: Any,
    hi: Any,
    v: Any,
    sat_at: Callable[[str, Any], Any],
    step: Any = 1,
    probe_values: Optional[Sequence[Any]] = None,
    domain_lo: Any = None,
    domain_hi: Any = None,
):
    """SEARCH_ATOM for numeric/date-like domains (B7 scaffold)."""
    if probe_values is None:
        probe_values = probes(col, lo, hi, step=step)

    # Equality: neighbors around v UNSAT (or outside gap/domain)
    def unsat_or_out(val):
        if val < lo or val > hi:
            return True
        return _sat_bool(sat_at(col, val)) is False

    v_minus = _plus(v, step, -1)
    v_plus = _plus(v, step, 1)
    if unsat_or_out(v_minus) and unsat_or_out(v_plus):
        return Atom(table=table, col=col, kind="num", intervals=[(v, v)])

    # Bounds search inside [lo, hi]
    l = lo if _sat_bool(sat_at(col, lo)) is True else _bsearch_smallest_sat(col, lo, v, sat_at, step)
    r = hi if _sat_bool(sat_at(col, hi)) is True else _bsearch_largest_sat(col, v, hi, sat_at, step)
    if l < lo:
        l = lo
    if r > hi:
        r = hi
    if l > r:
        l, r = v, v

    intervals = refine(col, l, r, sat_at, probe_values, step)
    intervals = _normalize_intervals(intervals)
    if not intervals:
        intervals = [(v, v)]
    return Atom(table=table, col=col, kind="num", intervals=intervals)


@dataclass
class TryNullResult:
    sat: Any
    null_sensitive: bool = False


def try_null_scaffold(x: str, set_null, run_sat, restore_original) -> TryNullResult:
    """B5.2 scaffold: set x NULL, run SAT, restore if UNSAT.

    Callers provide side-effecting callbacks. Returns SAT classification and
    whether x is NullSensitive (caller decides based on probe behavior).
    """
    set_null(x)
    sat = run_sat()
    if sat is False or sat == "UNSAT":
        restore_original(x)
        return TryNullResult(sat=sat, null_sensitive=False)
    # keep NULL in place when SAT (or inconclusive treated as non-UNSAT by caller policy)
    return TryNullResult(sat=sat, null_sensitive=False)


class PatternKillScaffold:
    """B5.3 scaffold: search/minimize UNSAT patterns over deferred columns.

    This is a structural foundation for unit testing; full integration requires
    row mutation and SAT execution callbacks.
    """

    def __init__(self, max_columns: int = 6):
        self.max_columns = max_columns

    def should_skip(self, deferred_columns: Sequence[str]):
        return len(deferred_columns) > self.max_columns

    def patterns(self, columns: Sequence[str], choices=("orig", "min", "max")):
        """Generate all assignment patterns (cartesian product) deterministically."""
        if not columns:
            return []
        out = [()]
        for _ in columns:
            nxt = []
            for prefix in out:
                for ch in choices:
                    nxt.append(prefix + (ch,))
            out = nxt
        # return list of dicts
        return [dict(zip(columns, p)) for p in out]
