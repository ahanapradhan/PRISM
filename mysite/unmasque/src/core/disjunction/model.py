import copy
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence, Tuple


def _norm_op(op: Any) -> str:
    if op is None:
        return ""
    return str(op).lower()


@dataclass
class Atom:
    """Single-column atom (spec B2)."""

    table: str
    col: str
    kind: str = "num"  # 'num' | 'text'
    intervals: List[Tuple[Any, Any]] = field(default_factory=list)  # numeric/date, closed
    text: Optional[Tuple[str, Any]] = None  # ('eq', s) | ('like', pattern)
    id: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def attrs(self):
        return [(self.table, self.col)]

    def pred_sql(self, formatter=None) -> str:
        """Return a boolean SQL expression for this atom.

        `formatter` may be a callable(value)->sql_literal or an object exposing
        formatting compatible with existing callers. If omitted, values are used
        as-is/stringified.
        """
        def fmt(v):
            if formatter is None:
                return v
            try:
                return formatter(v)
            except Exception:
                return v

        if self.kind == "text" and self.text is not None:
            mode, val = self.text
            lit = fmt(val)
            if mode == "like":
                return f"{self.col} LIKE {lit}"
            return f"{self.col} = {lit}"

        parts = []
        for lo, hi in self.intervals or []:
            if lo == hi:
                parts.append(f"{self.col} = {fmt(lo)}")
            else:
                parts.append(f"({self.col} >= {fmt(lo)} and {self.col} <= {fmt(hi)})")
        if not parts:
            return "FALSE"
        if len(parts) == 1:
            return parts[0]
        return "(" + " OR ".join(parts) + ")"

    def to_legacy_pred(self):
        """Best-effort conversion to legacy (tab, attrib, op, lb, ub) tuple."""
        if self.kind == "text" and self.text is not None:
            mode, val = self.text
            if mode == "like":
                return (self.table, self.col, "LIKE", val, val)
            return (self.table, self.col, "equal", val, val)
        if not self.intervals:
            return tuple()
        if len(self.intervals) == 1:
            lo, hi = self.intervals[0]
            if lo == hi:
                return (self.table, self.col, "equal", lo, hi)
            return (self.table, self.col, "range", lo, hi)
        # Multi-interval atoms are not representable as a single legacy arithmetic
        # predicate; callers should use IN/range-group conversion paths.
        return (self.table, self.col, "IN_INTERVALS", list(self.intervals), list(self.intervals))


@dataclass
class Clause:
    """OR of atoms (spec B2)."""

    atoms: List[Atom] = field(default_factory=list)
    id: Optional[str] = None
    status: str = "OK"
    meta: dict = field(default_factory=dict)

    def attrs(self):
        out = []
        seen = set()
        for a in self.atoms:
            for pair in a.attrs():
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)
        return out

    def pred_sql(self, formatter=None) -> str:
        parts = [a.pred_sql(formatter=formatter) for a in self.atoms if a is not None]
        parts = [p for p in parts if p and p != "FALSE"]
        if not parts:
            return "FALSE"
        if len(parts) == 1:
            return parts[0]
        return "(" + " OR ".join(parts) + ")"


@dataclass
class CNF:
    """AND of clauses (spec B2)."""

    clauses: List[Clause] = field(default_factory=list)
    row_of: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def all_atoms(self):
        for c in self.clauses:
            for a in c.atoms:
                yield a


def atom_from_legacy_pred(pred) -> Optional[Atom]:
    """Convert legacy predicate tuple to Atom; returns None for empty/invalid."""
    if not pred:
        return None
    try:
        if not isinstance(pred, (tuple, list)) or len(pred) < 3:
            return None
        tab, col = pred[0], pred[1]
        op = _norm_op(pred[2])
        lb = pred[3] if len(pred) > 3 else None
        ub = pred[4] if len(pred) > 4 else lb
        if op in ("like",):
            return Atom(table=tab, col=col, kind="text", text=("like", lb))
        if op in ("equal", "="):
            return Atom(table=tab, col=col, kind="num", intervals=[(lb, ub if ub is not None else lb)])
        if op in ("in",):
            vals = lb if lb is not None else []
            intervals = []
            points = []
            for v in list(vals):
                if isinstance(v, (tuple, list)) and len(v) == 2:
                    intervals.append((v[0], v[1]))
                else:
                    points.append((v, v))
            return Atom(table=tab, col=col, kind="num", intervals=intervals + points)
        # range / <= / >= and other bounded numeric forms
        return Atom(table=tab, col=col, kind="num", intervals=[(lb, ub)])
    except Exception:
        return None


def atoms_from_or_slot(slot: Sequence) -> List[Atom]:
    """Convert one legacy OR slot (sequence of alternatives, possibly empty tuples)."""
    atoms = []
    for pred in slot or []:
        a = atom_from_legacy_pred(pred)
        if a is not None:
            atoms.append(a)
    return atoms


def legacy_or_predicates_to_cnf(or_predicates) -> CNF:
    """Best-effort mapping of legacy or_predicates slots to CNF clauses.

    Legacy shape is typically a list of slots, each slot being alternatives for
    one (tab,attrib)-predicate position across extraction iterations. This is a
    compatibility scaffold, not a full semantic recovery.
    """
    cnf = CNF()
    for idx, slot in enumerate(or_predicates or []):
        atoms = atoms_from_or_slot(slot)
        if atoms:
            cnf.clauses.append(Clause(atoms=atoms, id=str(idx)))
    return cnf


def cnf_to_legacy_or_predicates(cnf: CNF):
    """Best-effort conversion to legacy slot-wise alternatives.

    Produces one slot per clause containing each atom's legacy predicate form.
    Multi-interval atoms that cannot be represented as single legacy predicates
    are skipped except as empty placeholders only when necessary.
    """
    slots = []
    for clause in (cnf.clauses if cnf else []):
        slot = []
        for atom in clause.atoms:
            pred = atom.to_legacy_pred()
            if pred:
                slot.append(pred)
        if slot:
            slots.append(tuple(slot))
    return slots
