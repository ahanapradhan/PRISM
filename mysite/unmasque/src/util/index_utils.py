"""Helpers for building PK/FK indexes on working copies and probe candidates.

Indexes are derived from the pk/fk relations CSV (same source as the PK
minimizer).  They are built explicitly because working tables/candidates are
created via ``LIKE`` (without INCLUDING INDEXES) or CTAS and therefore do not
inherit indexes from the source schema.
"""
from __future__ import annotations

import csv
import pathlib
import re
from collections import OrderedDict
from time import perf_counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_PKFK_CACHE: Dict[Tuple[str, str], Tuple[Dict[str, Tuple[str, ...]], Dict[str, Tuple[Tuple[str, ...], ...]]]] = {}


def _resolve_pkfk_path(config) -> Optional[pathlib.Path]:
    base = pathlib.Path(getattr(config, "base_path", "") or "")
    pkfk = getattr(config, "pkfk", "pkfkrelations.csv")
    candidates = [
        (base / pkfk).resolve() if str(base) else None,
        (pathlib.Path.cwd() / "mysite" / pkfk).resolve(),
        (pathlib.Path.cwd() / pkfk).resolve(),
        (pathlib.Path(__file__).resolve().parents[3] / pkfk).resolve(),
        (pathlib.Path(__file__).resolve().parents[4] / pkfk).resolve(),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


def load_pkfk_index_specs(config):
    """Return (pk_cols_by_table, fk_colgroups_by_table) from pkfkrelations.csv.

    ``pk_cols_by_table[table]`` is an ordered tuple of PK columns.
    ``fk_colgroups_by_table[table]`` is an ordered tuple of column tuples, one
    per FK relationship (composite FKs grouped by referencing table as they
    appear in the CSV).
    """
    path = _resolve_pkfk_path(config)
    cache_key = (str(path) if path else "", getattr(config, "pkfk", "pkfkrelations.csv"))
    if cache_key in _PKFK_CACHE:
        return _PKFK_CACHE[cache_key]

    pk_cols: "OrderedDict[str, OrderedDict[str, None]]" = OrderedDict()
    # fk_groups[table][ref_table] = OrderedDict of columns
    fk_groups: "OrderedDict[str, OrderedDict[str, OrderedDict[str, None]]]" = OrderedDict()

    if path is not None:
        with open(path, "rt", newline="") as f:
            rows = list(csv.reader(f))
        for row in rows[1:]:
            if len(row) < 4:
                continue
            table = (row[0] or "").strip()
            attr = (row[1] or "").strip()
            if not table or not attr:
                continue
            is_pk = (row[2] or "").strip().upper() == "Y"
            is_fk = (row[3] or "").strip().upper() == "Y"
            if is_pk:
                pk_cols.setdefault(table, OrderedDict())[attr] = None
            if is_fk:
                ref_table = (row[4] or "").strip() if len(row) > 4 else ""
                fk_groups.setdefault(table, OrderedDict()).setdefault(ref_table, OrderedDict())[attr] = None

    pk_specs = {t: tuple(cols.keys()) for t, cols in pk_cols.items()}
    fk_specs = {}
    for t, refs in fk_groups.items():
        groups = []
        seen = set()
        for _ref, cols in refs.items():
            col_t = tuple(cols.keys())
            if col_t and col_t not in seen:
                seen.add(col_t)
                groups.append(col_t)
        fk_specs[t] = tuple(groups)

    result = (pk_specs, fk_specs)
    _PKFK_CACHE[cache_key] = result
    return result


def _safe_ident(name: str) -> str:
    # identifiers come from trusted CSV/schema metadata; keep alnum/_ only for index names
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_") or "idx"


def index_specs_for_table(config, table: str):
    """Yield (index_name_suffix, columns_tuple, is_pk) for table's PK/FK indexes."""
    pk_specs, fk_specs = load_pkfk_index_specs(config)
    specs = []
    seen = set()
    pk = pk_specs.get(table)
    if pk:
        seen.add(tuple(c.lower() for c in pk))
        specs.append(("pk", pk, True))
    for i, cols in enumerate(fk_specs.get(table, ())):
        key = tuple(c.lower() for c in cols)
        if key in seen:
            continue
        seen.add(key)
        specs.append((f"fk{i+1}", cols, False))
    return specs


def create_pkfk_indexes(connection_helper, table: str, schema: Optional[str] = None, logger=None) -> float:
    """Create PK/FK indexes for ``schema.table``; return seconds spent."""
    config = connection_helper.config
    schema = schema or config.schema
    fq = f"{schema}.{table}"
    specs = index_specs_for_table(config, table)
    if not specs:
        return 0.0
    t0 = perf_counter()
    for suffix, cols, _is_pk in specs:
        col_list = ", ".join(cols)
        idx_name = _safe_ident(f"{table}_{suffix}_{'_'.join(cols)}_idx")
        # cap overly long names (Postgres limit 63 bytes)
        if len(idx_name.encode("utf-8")) > 60:
            idx_name = _safe_ident(f"{table}_{suffix}_idx")
        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {fq} ({col_list});"
        connection_helper.execute_sql([sql], logger)
    return perf_counter() - t0


def create_pkfk_indexes_on_qualified(connection_helper, fq_table: str, base_table: str, logger=None) -> float:
    """Create PK/FK indexes (derived from base_table metadata) on fq_table."""
    config = connection_helper.config
    specs = index_specs_for_table(config, base_table)
    if not specs:
        return 0.0
    t0 = perf_counter()
    # include fq relation in name hash-ish by replacing dots for uniqueness safety
    fq_tag = _safe_ident(fq_table.replace('.', '_'))
    for suffix, cols, _is_pk in specs:
        col_list = ", ".join(cols)
        idx_name = _safe_ident(f"{fq_tag}_{suffix}_{'_'.join(cols)}_idx")
        if len(idx_name.encode("utf-8")) > 60:
            idx_name = _safe_ident(f"{fq_tag}_{suffix}_idx")
        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {fq_table} ({col_list});"
        connection_helper.execute_sql([sql], logger)
    return perf_counter() - t0
