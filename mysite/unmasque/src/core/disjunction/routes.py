"""B13 downstream route-awareness helpers (CNF-guarded scaffolding).

These helpers provide route selection, pinning, and free-value utilities for
downstream modules when a CNF disjunction model is available. They are designed
to be non-breaking: callers should only use CNF-aware behavior when
`has_cnf_routes(...)` is true.
"""

import copy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .model import Atom, CNF


def has_cnf_routes(cnf: Optional[CNF]) -> bool:
    return bool(cnf is not None and getattr(cnf, "clauses", None) and len(cnf.clauses) > 0)


def iter_routes(cnf: CNF):
    """Yield deterministic routes as tuples of one Atom per clause.

    Cartesian product in clause order, atom order within clause. Intended for
    small CNFs/tests; callers should cap consumption.
    """
    if not has_cnf_routes(cnf):
        return
    clauses = [list(c.atoms or []) for c in cnf.clauses]
    if any(len(c) == 0 for c in clauses):
        return

    idxs = [0] * len(clauses)

    def build():
        return tuple(copy.deepcopy(clauses[i][idxs[i]]) for i in range(len(clauses)))

    while True:
        yield build()
        # increment like odometer from rightmost
        for i in range(len(idxs) - 1, -1, -1):
            idxs[i] += 1
            if idxs[i] < len(clauses[i]):
                break
            idxs[i] = 0
        else:
            return


def select_route(cnf: Optional[CNF], route_index: int = 0) -> Optional[Tuple[Atom, ...]]:
    """Select a deterministic route by index (default first atom of each clause)."""
    if not has_cnf_routes(cnf):
        return None
    if route_index <= 0:
        route = []
        for clause in cnf.clauses:
            if not clause.atoms:
                return None
            route.append(copy.deepcopy(clause.atoms[0]))
        return tuple(route)
    for i, route in enumerate(iter_routes(cnf)):
        if i == route_index:
            return route
    return None


def pinned_attrs(route: Optional[Sequence[Atom]]) -> List[Tuple[str, str]]:
    out = []
    seen = set()
    for atom in route or []:
        for pair in atom.attrs():
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out


def is_attr_free(attr: Tuple[str, str], route: Optional[Sequence[Atom]], cnf: Optional[CNF] = None) -> bool:
    """True if attr is not pinned by the selected route.

    If a CNF is provided, callers may also treat attrs absent from all CNF atoms
    as globally free; this helper focuses on route-level freedom.
    """
    if not route:
        return True
    return attr not in set(pinned_attrs(route))


def atom_for_attr(route: Optional[Sequence[Atom]], table: str, col: str) -> Optional[Atom]:
    for atom in route or []:
        if atom.table == table and atom.col == col:
            return atom
    return None


def representative_value(atom: Atom) -> Any:
    """Pick a representative concrete value satisfying the atom (best-effort)."""
    if atom is None:
        return None
    if atom.kind == "text" and atom.text is not None:
        mode, val = atom.text
        if mode == "like":
            # Replace simple wildcards with a concrete char for pinning
            s = str(val)
            s = s.replace("%", "a").replace("_", "a")
            return s
        return val
    intervals = list(atom.intervals or [])
    if not intervals:
        return None
    lo, hi = intervals[0]
    if lo == hi:
        return lo
    # prefer an interior-ish value when possible
    try:
        if isinstance(lo, int) and isinstance(hi, int):
            if hi - lo >= 2:
                return lo + 1
            return lo
        mid = lo + (hi - lo) / 2
        # keep int domain stable
        if isinstance(lo, int) and isinstance(hi, int):
            mid = int(mid)
        return mid
    except Exception:
        return lo


def route_pin_values(route: Optional[Sequence[Atom]]) -> Dict[Tuple[str, str], Any]:
    out = {}
    for atom in route or []:
        key = (atom.table, atom.col)
        if key in out:
            continue
        out[key] = representative_value(atom)
    return out


def route_row_snapshots(cnf: Optional[CNF], route: Optional[Sequence[Atom]]) -> List[Any]:
    """Return row_of snapshots for atoms in route when available."""
    if not has_cnf_routes(cnf) or not route:
        return []
    row_of = getattr(cnf, "row_of", {}) or {}
    snaps = []
    for atom in route:
        aid = getattr(atom, "id", None)
        if aid is not None and aid in row_of:
            snaps.append(copy.deepcopy(row_of[aid]))
    return snaps


def cnf_attrs(cnf: Optional[CNF]) -> List[Tuple[str, str]]:
    if not has_cnf_routes(cnf):
        return []
    out = []
    seen = set()
    for clause in cnf.clauses:
        for atom in clause.atoms:
            for pair in atom.attrs():
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)
    return out
