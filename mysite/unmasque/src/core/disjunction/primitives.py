"""SAT/selection primitives and helpers (spec B3 scaffolding).

These utilities are introduced in step 1 without changing legacy pipeline
behavior. They provide SQL predicate builders and result-level SAT checks that
can be used by the CNF-based disjunction path in later steps.
"""

from typing import Any, Iterable, Optional


def is_true(pred_sql: str) -> str:
    """Wrap a boolean SQL predicate with IS TRUE (B3.2)."""
    if pred_sql is None:
        return "TRUE IS TRUE"
    p = str(pred_sql).strip()
    if not p:
        return "TRUE IS TRUE"
    return f"({p}) IS TRUE"


def is_not_true(pred_sql: str) -> str:
    """Wrap a boolean SQL predicate with IS NOT TRUE (B3.2/T6)."""
    if pred_sql is None:
        return "TRUE IS NOT TRUE"
    p = str(pred_sql).strip()
    if not p:
        return "TRUE IS NOT TRUE"
    return f"({p}) IS NOT TRUE"


def keep_predicate_sql(pred_sql: str) -> str:
    return is_true(pred_sql)


def remove_predicate_sql(pred_sql: str) -> str:
    return is_not_true(pred_sql)


def sat_result(res, mode: str = "legacy_nonempty", r_void: Any = None, app=None) -> bool:
    """Classify whether a query result is satisfying (scaffold).

    - legacy_nonempty: non-empty by app's emptiness notion if app provided,
      else header+rows heuristic.
    - non_prism_void: compare to r_void (B3.1, non-PRISM).
    - fit: require at least one row with no NULL cell (B3.1, PRISM/FIT).

    This is intentionally conservative and side-effect free; later steps can
    specialize it per executable/minimizer behavior.
    """
    mode = (mode or "legacy_nonempty").lower()

    if mode == "non_prism_void":
        if r_void is None:
            # Fall back to non-empty heuristic if baseline unavailable.
            return sat_result(res, mode="legacy_nonempty", app=app)
        return res != r_void

    if mode == "fit":
        rows = _data_rows(res)
        for row in rows:
            if all(v not in (None, "None") for v in row):
                return True
        return False

    # legacy_nonempty
    if app is not None:
        try:
            # Prefer the app's "has some/full data" notion when available.
            if hasattr(app, "isQ_result_nonEmpty_nullfree"):
                return bool(app.isQ_result_nonEmpty_nullfree(res))
            if hasattr(app, "isQ_result_has_some_data"):
                return bool(app.isQ_result_has_some_data(res))
            if hasattr(app, "isQ_result_empty"):
                return not bool(app.isQ_result_empty(res))
        except Exception:
            pass
    return len(_data_rows(res)) > 0


def _data_rows(res) -> list:
    if res is None:
        return []
    if isinstance(res, list):
        # Executables typically return [header, ...rows]
        if len(res) <= 1:
            return []
        return list(res[1:])
    if isinstance(res, tuple):
        return list(res)
    return []
