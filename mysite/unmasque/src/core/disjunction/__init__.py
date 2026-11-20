"""Disjunction/CNF extraction scaffolding (spec B2/B3/B4+).

Step 1-2 scaffolding: data model, converters, SAT/selection helpers, and
scoped snapshot/restore/prep utilities. Not wired into legacy pipelines by
default.
"""

from .extraction import (
    NecessityResult,
    PatternKillScaffold,
    TryNullResult,
    gap,
    is_necessary,
    probes,
    refine,
    search_atom_numeric,
    try_null_scaffold,
)
from .model import Atom, Clause, CNF, atom_from_legacy_pred, atoms_from_or_slot, cnf_to_legacy_or_predicates, legacy_or_predicates_to_cnf
from .prep import DbRestorePoint, StateSnapshot, deep_snapshot, drop_not_null_constraints, drop_not_null_sql, restore_snapshot
from .primitives import is_not_true, is_true, keep_predicate_sql, remove_predicate_sql, sat_result

__all__ = [
    "Atom",
    "Clause",
    "CNF",
    "NecessityResult",
    "PatternKillScaffold",
    "TryNullResult",
    "atom_from_legacy_pred",
    "atoms_from_or_slot",
    "cnf_to_legacy_or_predicates",
    "gap",
    "is_necessary",
    "legacy_or_predicates_to_cnf",
    "probes",
    "refine",
    "search_atom_numeric",
    "try_null_scaffold",
    "DbRestorePoint",
    "StateSnapshot",
    "deep_snapshot",
    "drop_not_null_constraints",
    "drop_not_null_sql",
    "restore_snapshot",
    "is_not_true",
    "is_true",
    "keep_predicate_sql",
    "remove_predicate_sql",
    "sat_result",
]
