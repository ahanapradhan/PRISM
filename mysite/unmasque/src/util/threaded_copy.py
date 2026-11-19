"""Python-threaded parallel table copy for the working-schema backup.

Every worker owns its own connection, so this needs no native helper and runs
on Windows.  Rows are copied as disjoint ``ctid`` page ranges; each worker
inserts its range back-to-front (``ORDER BY ctid DESC``) and the workers
interleave.  The physical row order of the copied table in the ``unmasque``
schema therefore differs from the source table.
"""
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .PostgresConnectionHelper import PostgresConnectionHelper

ENV_THREADS = "PRISM_COPY_THREADS"
ENV_LARGE_THREADS = "PRISM_COPY_LARGE_THREADS"
LARGE_TABLES = frozenset({"lineitem", "orders"})
DEFAULT_THREADS = 4
DEFAULT_LARGE_THREADS = 8


@dataclass
class TableCopyResult:
    table: str
    rows: int
    chunks: int
    seconds: float


def _env_int(name, default):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def default_thread_count(table, rows=None, pages=None):
    """Number of worker threads for one table (lineitem/orders get more)."""
    default = DEFAULT_LARGE_THREADS if table in LARGE_TABLES else DEFAULT_THREADS
    env_name = ENV_LARGE_THREADS if table in LARGE_TABLES else ENV_THREADS
    count = _env_int(env_name, default)
    if pages is not None:
        count = min(count, max(1, pages))
    if rows is not None and rows < count:
        count = max(1, rows)
    return count


def _ctid_page(ctid):
    return int(str(ctid).strip()[1:-1].split(",")[0])


def _chunks(min_page, max_page, count):
    """Yield (lower_page, upper_page_exclusive, is_last) ctid page chunks."""
    pages = max_page - min_page + 1
    step = max(1, -(-pages // count))  # ceiling division
    lo = min_page
    while lo <= max_page:
        hi = min(lo + step, max_page + 1)
        yield lo, hi, hi > max_page
        lo = hi


def parallel_copy_table(config, source_schema, dest_schema, table,
                        max_threads=None, logger=None):
    """Copy ``source_schema.table`` into ``dest_schema.table`` with threads.

    The destination is recreated from scratch on every call, so this is safe
    to use both for a fresh backup and to restore a working table afterwards.
    """
    queries = PostgresConnectionHelper(config).queries
    source = f"{source_schema}.{table}"
    destination = f"{dest_schema}.{table}"

    started = time.perf_counter()
    control = PostgresConnectionHelper(config)
    control.connectUsingParams()
    try:
        rows = int(control.execute_sql_fetchone_0(queries.get_row_count(source)) or 0)
        min_ctid = control.execute_sql_fetchone_0(queries.get_ctid_from("min", source))
        max_ctid = control.execute_sql_fetchone_0(queries.get_ctid_from("max", source))
        control.execute_sql([queries.drop_view_or_table_cascade(dest_schema, table),
                             queries.create_unlogged_table_like(destination, source)], logger)
        # Workers use their own connections; commit the DDL first or they will
        # block waiting for a lock held by this transaction.
        control.commit_transaction()

        if rows == 0 or min_ctid is None or max_ctid is None:
            control.commit_transaction()
            return TableCopyResult(table, 0, 0, time.perf_counter() - started)

        min_page, max_page = _ctid_page(min_ctid), _ctid_page(max_ctid)
        count = max_threads or default_thread_count(table, rows, max_page - min_page + 1)
        chunks = list(_chunks(min_page, max_page, count))

        errors = []
        errors_lock = threading.Lock()

        def worker(lo, hi, is_last):
            start_ctid = f"({lo},0)"
            end_ctid = None if is_last else f"({hi},0)"
            helper = None
            try:
                helper = PostgresConnectionHelper(config)
                helper.connectUsingParams()
                helper.execute_sql(
                    [queries.insert_into_tab_select_star_from_ctid_range(
                        destination, source, start_ctid, end_ctid)], logger)
                helper.commit_transaction()
            except Exception as exc:  # keep other workers alive, report at the end
                with errors_lock:
                    errors.append((lo, hi, str(exc)))
                if helper is not None and helper.conn is not None:
                    helper.rollback_transaction()
            finally:
                if helper is not None:
                    helper.closeConnection()

        threads = []
        for lo, hi, is_last in chunks:
            thread = threading.Thread(target=worker, args=(lo, hi, is_last),
                                      name=f"copy-{table}-{lo}-{hi}")
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

        if errors:
            raise RuntimeError(f"parallel copy of {table} failed: {errors}")

        copied = int(control.execute_sql_fetchone_0(queries.get_row_count(destination)) or 0)
        control.commit_transaction()
        if copied != rows:
            raise RuntimeError(f"parallel copy of {table} copied {copied} rows, expected {rows}")

        # Build PK/FK indexes on the working copy (LIKE/CTAS do not copy indexes).
        try:
            from .index_utils import create_pkfk_indexes
            idx_s = create_pkfk_indexes(control, table, schema=dest_schema, logger=logger)
            control.commit_transaction()
            if logger is not None:
                logger.debug(f"Built PK/FK indexes for {destination} in {idx_s:.3f}s")
        except Exception as exc:
            control.conn.rollback()
            raise
    except Exception:
        try:
            control.conn.rollback()
        except Exception:
            pass
        raise
    finally:
        control.closeConnection()

    return TableCopyResult(table, copied, len(chunks), time.perf_counter() - started)


def parallel_backup(config, tables, source_schema=None, dest_schema=None,
                    max_threads=None, logger=None):
    """Back up every table in ``tables`` using one thread pool per table."""
    source_schema = source_schema or config.user_schema
    dest_schema = dest_schema or config.schema
    results = {}
    for table in tables:
        results[table] = parallel_copy_table(
            config, source_schema, dest_schema, table,
            max_threads=max_threads, logger=logger)
        if logger is not None:
            result = results[table]
            logger.debug(f"Parallel copy of {table}: {result.rows} rows in "
                         f"{result.chunks} threads ({result.seconds:.2f}s)")
    return results
