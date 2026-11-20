"""Scoped preparation/snapshot/restore utilities for disjunction extraction.

Step 2 scaffolding: provides reusable helpers for in-memory snapshots and
optional DB-level restore points on disposable/working contexts. This module is
not wired into legacy pipelines by default and performs no actions unless its
helpers are explicitly called.
"""

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence


def deep_snapshot(obj: Any) -> Any:
    """Deep-copy a Python object representing extraction state."""
    return copy.deepcopy(obj)


def restore_snapshot(snapshot: Any) -> Any:
    """Return a deep copy of a snapshot to avoid aliasing restored state."""
    return copy.deepcopy(snapshot)


@dataclass
class StateSnapshot:
    """In-memory snapshot of disjunction-relevant mutable state."""

    global_min_instance_dict: Any = None
    global_d_plus_value: Any = None
    filter_attrib_dict: Any = None
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(
        cls,
        global_min_instance_dict=None,
        global_d_plus_value=None,
        filter_attrib_dict=None,
        **extras,
    ):
        return cls(
            global_min_instance_dict=deep_snapshot(global_min_instance_dict),
            global_d_plus_value=deep_snapshot(global_d_plus_value),
            filter_attrib_dict=deep_snapshot(filter_attrib_dict),
            extras=deep_snapshot(extras),
        )

    def restore(self):
        return {
            "global_min_instance_dict": restore_snapshot(self.global_min_instance_dict),
            "global_d_plus_value": restore_snapshot(self.global_d_plus_value),
            "filter_attrib_dict": restore_snapshot(self.filter_attrib_dict),
            **restore_snapshot(self.extras),
        }


def _qualified(connectionHelper, table: str) -> str:
    if "." in str(table):
        return str(table)
    schema = getattr(connectionHelper.config, "schema", None)
    return f"{schema}.{table}" if schema else str(table)


def _exec(connectionHelper, sqls: Sequence[str], logger=None):
    if not sqls:
        return None
    try:
        return connectionHelper.execute_sql(list(sqls), logger)
    except TypeError:
        return connectionHelper.execute_sql(list(sqls))


class DbRestorePoint:
    """DB-level snapshot/restore point for working tables (scoped utility).

    Creates backup copies of specified tables in the working schema and can
    restore or drop them later. Intended for disposable/disjunction contexts.
    """

    def __init__(self, connectionHelper, tables: Iterable[str], tag: Optional[str] = None, logger=None):
        self.connectionHelper = connectionHelper
        self.tables = list(tables or [])
        self.tag = tag or str(int(time.time() * 1000))
        self.logger = logger
        self.created = []

    def _backup_name(self, table: str) -> str:
        safe_table = str(table).replace(".", "_")
        # Keep names reasonably short/simple for postgres identifiers.
        name = f"_cnf_snap_{safe_table}_{self.tag}"
        return name[-60:]

    def create(self):
        q = self.connectionHelper.queries
        for tab in self.tables:
            src = _qualified(self.connectionHelper, tab)
            bname = self._backup_name(tab)
            bq = _qualified(self.connectionHelper, bname)
            sqls = []
            if hasattr(q, "drop_table_cascade"):
                sqls.append(q.drop_table_cascade(bq))
            elif hasattr(q, "drop_table"):
                sqls.append(q.drop_table(bq))
            # Copy current working-table contents/structure for later restore.
            sqls.append(q.create_table_as_select_star_from(bq, src))
            _exec(self.connectionHelper, sqls, self.logger)
            self.created.append((tab, bname))
        return self

    def restore(self):
        q = self.connectionHelper.queries
        for tab, bname in reversed(self.created):
            dst = _qualified(self.connectionHelper, tab)
            bq = _qualified(self.connectionHelper, bname)
            sqls = []
            # Replace current working table with snapshot contents.
            if hasattr(q, "drop_table_cascade"):
                sqls.append(q.drop_table_cascade(dst))
            elif hasattr(q, "drop_table"):
                sqls.append(q.drop_table(dst))
            sqls.append(q.create_table_as_select_star_from(dst, bq))
            _exec(self.connectionHelper, sqls, self.logger)
        return self

    def drop(self):
        q = self.connectionHelper.queries
        for _, bname in self.created:
            bq = _qualified(self.connectionHelper, bname)
            if hasattr(q, "drop_table_cascade"):
                _exec(self.connectionHelper, [q.drop_table_cascade(bq)], self.logger)
            elif hasattr(q, "drop_table"):
                _exec(self.connectionHelper, [q.drop_table(bq)], self.logger)
        self.created = []
        return self


def drop_not_null_sql(qualified_table: str, column: str) -> str:
    """SQL to drop NOT NULL on a column (scoped utility; caller executes)."""
    return f"ALTER TABLE {qualified_table} ALTER COLUMN {column} DROP NOT NULL;"


def drop_not_null_constraints(connectionHelper, table: str, columns: Iterable[str], logger=None):
    """Drop NOT NULL constraints for columns on a working table (best effort).

    Scoped utility for future disjunction prep; not used by legacy pipelines.
    """
    qtab = _qualified(connectionHelper, table)
    sqls = [drop_not_null_sql(qtab, col) for col in (columns or [])]
    if not sqls:
        return []
    _exec(self.connectionHelper, sqls, logger)
    return sqls
