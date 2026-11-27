"""CNF filter-structure/domain/route helpers for downstream modules (B13+).

Provides structured, non-lossy reasoning over CNF clauses/routes:
- attribute domain under a route (free / union / pinned/singleton)
- selection of routes that free a target attribute when possible
- sampling of distinct values from domains for probing (projection/GB/agg)
- carrier planning for cross-table clause satisfaction

Legacy-safe: callers should only use when a valid CNF with routes is present.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .model import Atom, Clause, CNF
from .routes import has_cnf_routes, iter_routes, select_route

Attr = Tuple[str, str]


@dataclass
class Domain:
    kind: str  # 'free' | 'union' | 'pinned' | 'empty'
    intervals: List[Tuple[Any, Any]] = field(default_factory=list)  # numeric/date, closed
    values: List[Any] = field(default_factory=list)  # explicit points/text values
    text_mode: Optional[str] = None  # 'eq' | 'like' for text domains
    source: str = ""


def _singleton_domain_from_atom(atom: Atom) -> Domain:
    if atom is None:
        return Domain(kind='empty', source='missing-atom')
    if atom.kind == 'text' and atom.text is not None:
        mode, val = atom.text
        return Domain(kind='pinned' if mode == 'eq' else 'union', values=[val], text_mode=mode, source='atom')
    intervals = list(atom.intervals or [])
    if not intervals:
        return Domain(kind='empty', source='atom-empty')
    if len(intervals) == 1 and intervals[0][0] == intervals[0][1]:
        return Domain(kind='pinned', intervals=[tuple(intervals[0])], values=[intervals[0][0]], source='atom')
    vals = [lo for (lo, hi) in intervals if lo == hi]
    return Domain(kind='union', intervals=[tuple(iv) for iv in intervals], values=vals, source='atom')


def _union_domain_from_atoms(atoms: Sequence[Atom]) -> Domain:
    intervals: List[Tuple[Any, Any]] = []
    values: List[Any] = []
    text_mode = None
    saw_text = False
    for atom in atoms or []:
        if atom.kind == 'text' and atom.text is not None:
            saw_text = True
            mode, val = atom.text
            text_mode = mode
            values.append(val)
        else:
            for iv in (atom.intervals or []):
                intervals.append(tuple(iv))
                if iv[0] == iv[1]:
                    values.append(iv[0])
    if saw_text:
        uniq = []
        for v in values:
            if v not in uniq:
                uniq.append(v)
        kind = 'pinned' if len(uniq) == 1 and text_mode == 'eq' else 'union'
        return Domain(kind=kind, values=uniq, text_mode=text_mode or 'eq', source='union-atoms')
    if not intervals and not values:
        return Domain(kind='empty', source='union-atoms')
    # merge numeric/date intervals (best-effort ordering)
    try:
        merged = []
        for lo, hi in sorted(intervals, key=lambda x: (x[0], x[1])):
            if not merged:
                merged.append([lo, hi])
                continue
            if lo <= merged[-1][1]:
                if hi > merged[-1][1]:
                    merged[-1][1] = hi
            else:
                merged.append([lo, hi])
        intervals = [tuple(x) for x in merged]
    except Exception:
        intervals = [tuple(iv) for iv in intervals]
    uniq_vals = []
    for v in values:
        if v not in uniq_vals:
            uniq_vals.append(v)
    if len(intervals) == 1 and intervals[0][0] == intervals[0][1]:
        return Domain(kind='pinned', intervals=intervals, values=[intervals[0][0]], source='union-atoms')
    return Domain(kind='union', intervals=intervals, values=uniq_vals, source='union-atoms')


def _intersect_domains(domains: List[Domain], fallback_free: Optional[Domain] = None) -> Domain:
    # Keep only constraining domains
    constraining = [d for d in domains if d is not None and d.kind not in ('free',)]
    if not constraining:
        return fallback_free or Domain(kind='free', source='unconstrained')
    if any(d.kind == 'empty' for d in constraining):
        return Domain(kind='empty', source='intersect')
    # If all pinned to same value, pinned.
    pinned_vals = [d.values[0] for d in constraining if d.kind == 'pinned' and d.values]
    if pinned_vals and all(v == pinned_vals[0] for v in pinned_vals) and all(d.kind == 'pinned' for d in constraining):
        d0 = constraining[0]
        return Domain(kind='pinned', intervals=list(d0.intervals), values=[pinned_vals[0]], text_mode=d0.text_mode, source='intersect')
    # Conservative: if mixed/complex, prefer the most specific non-free domain (first pinned/union)
    # Full interval intersection can be added as needed; callers mainly need "not singleton"/sampling.
    for d in constraining:
        if d.kind == 'pinned':
            return copy.deepcopy(d)
    return copy.deepcopy(constraining[0])


def clauses_for_attr(cnf: Optional[CNF], attr: Attr) -> List[Clause]:
    if not has_cnf_routes(cnf):
        return []
    out = []
    for clause in cnf.clauses:
        for atom in clause.atoms:
            if (atom.table, atom.col) == attr:
                out.append(clause)
                break
    return out


def attr_atoms_in_clause(clause: Clause, attr: Attr) -> List[Atom]:
    return [a for a in (clause.atoms or []) if (a.table, a.col) == attr]


def clause_has_other_column_disjunct(clause: Clause, attr: Attr) -> bool:
    return any((a.table, a.col) != attr for a in (clause.atoms or []))


def attr_domain_under_route(cnf: Optional[CNF], route: Optional[Sequence[Atom]], attr: Attr,
                            global_domain: Optional[Domain] = None) -> Domain:
    """Compute attribute domain under a selected route.

    - Clause satisfied by an atom on another column => no constraint on attr from that clause.
    - Clause satisfied by an atom on attr => constrained to that atom's domain.
    - Clauses not mentioning attr => no constraint.
    - If unconstrained by all clauses on this route => free (global_domain).
    """
    if not has_cnf_routes(cnf) or route is None:
        return global_domain or Domain(kind='free', source='no-cnf-route')
    route_by_clause = {}
    # route is one atom per clause in order
    for i, clause in enumerate(cnf.clauses):
        if i < len(route):
            route_by_clause[id(clause)] = route[i]
    constraints = []
    for clause in cnf.clauses:
        chosen = route_by_clause.get(id(clause))
        if chosen is None:
            continue
        if (chosen.table, chosen.col) == attr:
            constraints.append(_singleton_domain_from_atom(chosen))
        else:
            # route satisfies this clause via another column/attr => frees target attr for this clause
            continue
    if not constraints:
        # Even if clause atoms are all on attr, route must pick one of them (handled above).
        return global_domain or Domain(kind='free', source='route-free')
    return _intersect_domains(constraints, fallback_free=global_domain or Domain(kind='free'))


def clause_union_domain_for_attr(clause: Clause, attr: Attr) -> Domain:
    atoms = attr_atoms_in_clause(clause, attr)
    if not atoms:
        return Domain(kind='free', source='attr-not-in-clause')
    return _union_domain_from_atoms(atoms)


def attr_global_union_domain(cnf: Optional[CNF], attr: Attr) -> Optional[Domain]:
    """Union/pinned domain implied by clauses whose every disjunct is on attr.
    Returns None if attr is not solely-constrained by any such clause.
    """
    if not has_cnf_routes(cnf):
        return None
    domains = []
    for clause in clauses_for_attr(cnf, attr):
        if not clause_has_other_column_disjunct(clause, attr):
            domains.append(clause_union_domain_for_attr(clause, attr))
    if not domains:
        return None
    return _intersect_domains(domains)


def is_attr_free_under_route(cnf: Optional[CNF], route: Optional[Sequence[Atom]], attr: Attr) -> bool:
    d = attr_domain_under_route(cnf, route, attr, global_domain=Domain(kind='free'))
    return d.kind == 'free'


def select_freeing_route_for_attr(cnf: Optional[CNF], attr: Attr,
                                  max_routes: Optional[int] = 64) -> Optional[Tuple[Atom, ...]]:
    """Select a route that frees attr when possible.

    Preference: for clauses mentioning attr and another column, choose a disjunct
    on another column; otherwise choose first viable atom. Falls back to first route.
    """
    if not has_cnf_routes(cnf):
        return None
    # Greedy per-clause choice (independent clauses) gives a freeing route when feasible.
    chosen = []
    possible = True
    for clause in cnf.clauses:
        atoms = list(clause.atoms or [])
        if not atoms:
            return None
        on_attr = [a for a in atoms if (a.table, a.col) == attr]
        others = [a for a in atoms if (a.table, a.col) != attr]
        if on_attr and others:
            chosen.append(copy.deepcopy(others[0]))
        elif on_attr and not others:
            # cannot be freed by this clause; pick first atom on attr (union applies across routes)
            chosen.append(copy.deepcopy(on_attr[0]))
            possible = False
        else:
            chosen.append(copy.deepcopy(atoms[0]))
    # Greedy choice is a valid route in standard independent-clause CNF enumeration.
    route = tuple(chosen)
    if possible or is_attr_free_under_route(cnf, route, attr):
        return route
    # Try to find any route that frees attr (bounded)
    count = 0
    for r in iter_routes(cnf):
        if max_routes is not None and count >= max_routes:
            break
        count += 1
        if is_attr_free_under_route(cnf, r, attr):
            return r
    return route


def _mid_value(lo: Any, hi: Any) -> Any:
    if lo == hi:
        return lo
    try:
        if isinstance(lo, int) and isinstance(hi, int):
            if hi - lo >= 2:
                return lo + 1
            return lo
        mid = lo + (hi - lo) / 2
        if isinstance(lo, int) and isinstance(hi, int):
            return int(mid)
        return mid
    except Exception:
        return lo


def sample_values_from_domain(domain: Domain, count: int = 2,
                              fallback: Optional[List[Any]] = None) -> List[Any]:
    """Return up to `count` distinct sample values from a domain (best-effort)."""
    if domain is None or domain.kind == 'empty':
        return list((fallback or [])[:count])
    if domain.kind == 'pinned':
        base = domain.values[0] if domain.values else (domain.intervals[0][0] if domain.intervals else None)
        return [base] if base is not None else list((fallback or [])[:count])
    out = []
    # explicit values first
    for v in (domain.values or []):
        if v not in out:
            out.append(v)
        if len(out) >= count:
            return out[:count]
    # interval endpoints/midpoints
    for lo, hi in (domain.intervals or []):
        for cand in (lo, hi, _mid_value(lo, hi)):
            if cand not in out:
                out.append(cand)
            if len(out) >= count:
                return out[:count]
    # text fallback: cannot invent reliably except given values
    if fallback:
        for v in fallback:
            if v not in out:
                out.append(v)
            if len(out) >= count:
                break
    return out[:count]


def carrier_plan_for_clause(clause: Clause, route_atom: Atom) -> Dict[str, Any]:
    """Plan carrier satisfaction for a clause under chosen route atom.

    For cross-table clauses, satisfying the chosen atom on its table for relevant
    rows acts as a carrier so joins satisfy the clause. Actual DB application is
    performed by mutation/base helpers; this returns structured intent.
    """
    if clause is None or route_atom is None:
        return {"ok": False}
    atoms = list(clause.atoms or [])
    cross_table = len({(a.table, a.col) for a in atoms}.union({(route_atom.table, route_atom.col)})) > 0 and \
        len({a.table for a in atoms}) > 1
    return {
        "ok": True,
        "clause_id": getattr(clause, 'id', None),
        "carrier_table": route_atom.table,
        "carrier_attr": (route_atom.table, route_atom.col),
        "carrier_atom": copy.deepcopy(route_atom),
        "cross_table": cross_table,
        "needs_all_rows": cross_table,
    }


def route_probe_plan(cnf: Optional[CNF], route: Optional[Sequence[Atom]]) -> List[Dict[str, Any]]:
    if not has_cnf_routes(cnf) or route is None:
        return []
    plans = []
    for i, clause in enumerate(cnf.clauses):
        if i < len(route):
            plans.append(carrier_plan_for_clause(clause, route[i]))
    return plans


def route_pins_and_domains(cnf: Optional[CNF], route: Optional[Sequence[Atom]],
                           attrs: Optional[Sequence[Attr]] = None) -> Dict[Attr, Domain]:
    """Return per-attr domain under route for requested attrs (or all CNF attrs)."""
    if attrs is None:
        seen = set()
        attrs_list = []
        if has_cnf_routes(cnf):
            for clause in cnf.clauses:
                for atom in clause.atoms:
                    k = (atom.table, atom.col)
                    if k not in seen:
                        seen.add(k)
                        attrs_list.append(k)
        attrs = attrs_list
    return {a: attr_domain_under_route(cnf, route, a) for a in attrs}
