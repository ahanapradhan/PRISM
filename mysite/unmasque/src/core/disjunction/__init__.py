"""Disjunction/CNF extraction scaffolding (spec B2/B3/B4+).

Step 1-2 scaffolding: data model, converters, SAT/selection helpers, and
scoped snapshot/restore/prep utilities. Not wired into legacy pipelines by
default.
"""

from .cnf_extractor import CNFDisjunctionExtractor, ClauseStatus, ExtractionResult
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
from .filter_structure import (
    Domain,
    attr_domain_under_route,
    attr_global_union_domain,
    carrier_plan_for_clause,
    clause_union_domain_for_attr,
    is_attr_free_under_route,
    route_pins_and_domains,
    route_probe_plan,
    sample_values_from_domain,
    select_freeing_route_for_attr,
)
from .model import Atom, Clause, CNF, atom_from_legacy_pred, atoms_from_or_slot, cnf_to_legacy_or_predicates, legacy_or_predicates_to_cnf
from .prep import DbRestorePoint, StateSnapshot, deep_snapshot, drop_not_null_constraints, drop_not_null_sql, restore_snapshot
from .primitives import is_not_true, is_true, keep_predicate_sql, remove_predicate_sql, sat_result
from .routes import (
    atom_for_attr,
    cnf_attrs,
    has_cnf_routes,
    is_attr_free,
    iter_routes,
    pinned_attrs,
    representative_value,
    route_pin_values,
    route_row_snapshots,
    select_route,
    verify_cnf_structure,
)

__all__ = [
    "Atom",
    "Clause",
    "CNF",
    "CNFDisjunctionExtractor",
    "ClauseStatus",
    "Domain",
    "ExtractionResult",
    "NecessityResult",
    "PatternKillScaffold",
    "TryNullResult",
    "atom_from_legacy_pred",
    "atoms_from_or_slot",
    "attr_domain_under_route",
    "attr_global_union_domain",
    "carrier_plan_for_clause",
    "clause_union_domain_for_attr",
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
    "atom_for_attr",
    "cnf_attrs",
    "has_cnf_routes",
    "is_attr_free",
    "is_attr_free_under_route",
    "iter_routes",
    "pinned_attrs",
    "representative_value",
    "route_pin_values",
    "route_pins_and_domains",
    "route_probe_plan",
    "route_row_snapshots",
    "sample_values_from_domain",
    "select_freeing_route_for_attr",
    "select_route",
    "verify_cnf_structure",
]

