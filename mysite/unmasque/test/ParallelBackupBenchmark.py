#!/usr/bin/env python3
"""Benchmark serial vs threaded table copies for PRISM backup/restore.

This is an experiment/test harness only. It does not change production code and
it never writes to the source (user) schema: source tables are only read with
SELECT. Every copy is written to a scratch ``bench_*`` schema that is dropped
again before the next run.

The two SQL shapes are the ones PRISM actually uses:

* ``like_insert`` (default): ``CREATE UNLOGGED TABLE dst (LIKE src INCLUDING
  INDEXES); INSERT INTO dst SELECT * FROM src;``
  This mirrors ``SchemaSanitizer.backup_one_table`` / ``restore_one_table``.
* ``ctas``: ``CREATE UNLOGGED TABLE dst AS SELECT * FROM src;``
  This mirrors the restore path in ``test/util/TPCH_backup_restore.py``.

Examples::

    # quick calibration on the small tables only
    python3 mysite/unmasque/test/ParallelBackupBenchmark.py \
        --tables region,nation,supplier,part,customer \
        --threads 1,2,4 --repeat 1

    # full benchmark, production backup SQL
    python3 mysite/unmasque/test/ParallelBackupBenchmark.py \
        --mode like_insert --threads 1,2,4,8 --repeat 2

    # compare both SQL shapes
    python3 mysite/unmasque/test/ParallelBackupBenchmark.py \
        --mode like_insert,ctas --threads 1,2,4,8 --repeat 1
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2

DEFAULT_RELATIONS = [
    "lineitem",
    "orders",
    "partsupp",
    "customer",
    "part",
    "supplier",
    "region",
    "nation",
]


def connection_kwargs(args):
    return {
        "dbname": args.dbname,
        "user": args.user,
        "password": os.environ.get("PGPASSWORD", args.password),
        "host": args.host,
        "port": args.port,
    }


def connect(args):
    conn = psycopg2.connect(**connection_kwargs(args))
    with conn.cursor() as cur:
        cur.execute("SET work_mem = %s;", (args.workmem,))
    return conn


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def qualified(schema, table):
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def reset_schema(args, schema):
    conn = psycopg2.connect(**connection_kwargs(args))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {quote_ident(schema)} CASCADE;")
            cur.execute(f"CREATE SCHEMA {quote_ident(schema)};")
    finally:
        conn.close()


def drop_schema(args, schema):
    conn = psycopg2.connect(**connection_kwargs(args))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {quote_ident(schema)} CASCADE;")
    finally:
        conn.close()


def source_counts(args, tables):
    conn = psycopg2.connect(**connection_kwargs(args))
    try:
        counts = {}
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT count(*) FROM {qualified(args.source, table)};")
                counts[table] = cur.fetchone()[0]
        conn.rollback()
        return counts
    finally:
        conn.close()


def copy_table(conn, mode, dst, src):
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {dst} CASCADE;")
        if mode == "like_insert":
            cur.execute(f"CREATE UNLOGGED TABLE {dst} (LIKE {src} INCLUDING INDEXES);")
            cur.execute(f"ALTER TABLE {dst} SET (autovacuum_enabled = false);")
            cur.execute(f"INSERT INTO {dst} SELECT * FROM {src};")
        elif mode == "ctas":
            cur.execute(f"CREATE UNLOGGED TABLE {dst} AS SELECT * FROM {src};")
            cur.execute(f"ALTER TABLE {dst} SET (autovacuum_enabled = false);")
        else:
            raise ValueError(f"unknown mode {mode!r}")
    conn.commit()


def timed_copy(args, mode, schema, table):
    dst = qualified(schema, table)
    src = qualified(args.source, table)
    conn = connect(args)
    started = time.perf_counter()
    try:
        copy_table(conn, mode, dst, src)
    finally:
        conn.close()
    return time.perf_counter() - started


def run_serial(args, mode, schema, tables):
    reset_schema(args, schema)
    per_table = {}
    started = time.perf_counter()
    conn = connect(args)
    try:
        for table in tables:
            one_start = time.perf_counter()
            copy_table(conn, mode, qualified(schema, table), qualified(args.source, table))
            per_table[table] = time.perf_counter() - one_start
    finally:
        conn.close()
    return time.perf_counter() - started, per_table


def run_threaded(args, mode, schema, tables, workers):
    reset_schema(args, schema)
    per_table = {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(timed_copy, args, mode, schema, table): table
            for table in tables
        }
        for future in as_completed(futures):
            per_table[futures[future]] = future.result()
    return time.perf_counter() - started, per_table


def verify(args, schema, expected):
    conn = psycopg2.connect(**connection_kwargs(args))
    try:
        with conn.cursor() as cur:
            for table, want in expected.items():
                cur.execute(f"SELECT count(*) FROM {qualified(schema, table)};")
                got = cur.fetchone()[0]
                if got != want:
                    return table, want, got
        conn.rollback()
        return None
    finally:
        conn.close()


def run_one(args, mode, workers, run_id):
    schema = f"bench_{mode}_{workers}_{run_id}"
    tables = args.relations
    if workers == 1:
        total, per_table = run_serial(args, mode, schema, tables)
    else:
        total, per_table = run_threaded(args, mode, schema, tables, workers)
    mismatch = verify(args, schema, args.expected)
    drop_schema(args, schema)
    if mismatch is not None:
        table, want, got = mismatch
        raise AssertionError(
            f"{mode} workers={workers}: {table} has {got} rows, expected {want}"
        )
    return total, per_table


def parse_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dbname", default="tpch")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="postgres")
    parser.add_argument("--source", default="fresh", help="read-only source schema")
    parser.add_argument(
        "--tables",
        default=",".join(DEFAULT_RELATIONS),
        help="comma-separated table names (default: all TPCH SF1 tables)",
    )
    parser.add_argument(
        "--mode",
        default="like_insert",
        help="like_insert (production backup/restore) and/or ctas",
    )
    parser.add_argument("--threads", default="1,2,4,8")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workmem", default="32MB")
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args(argv)

    args.relations = parse_csv(args.tables)
    modes = parse_csv(args.mode)
    thread_counts = [int(value) for value in parse_csv(args.threads)]

    unknown = [t for t in args.relations if t not in DEFAULT_RELATIONS]
    if unknown:
        parser.error(f"unknown table(s): {unknown}")

    args.expected = source_counts(args, args.relations)
    print("source counts:", args.expected)
    print(f"threads={thread_counts} modes={modes} repeat={args.repeat}")

    if not args.no_warmup:
        for mode in modes:
            warm_schema = f"bench_warmup_{mode}"
            if 1 in thread_counts:
                run_serial(args, mode, warm_schema, args.relations)
            else:
                run_threaded(args, mode, warm_schema, args.relations, thread_counts[0])
            drop_schema(args, warm_schema)
        print("warmup done")

    summary = {}
    for mode in modes:
        results = {workers: [] for workers in thread_counts}
        for rep in range(args.repeat):
            # Reverse the order on every second repeat to reduce cache-order bias.
            order = thread_counts if rep % 2 == 0 else list(reversed(thread_counts))
            for workers in order:
                run_id = f"r{rep}"
                total, per_table = run_one(args, mode, workers, run_id)
                results[workers].append(total)
                slowest = sorted(per_table.items(), key=lambda kv: kv[1], reverse=True)
                print(
                    f"mode={mode:11s} workers={workers} total={total:8.3f}s "
                    f"per_table={{{', '.join(f'{t}: {d:.3f}s' for t, d in slowest)}}}"
                )
        baseline = min(results[1]) if 1 in results and results[1] else None
        summary[mode] = {}
        for workers in thread_counts:
            best = min(results[workers])
            speedup = baseline / best if baseline else float("nan")
            summary[mode][workers] = (best, speedup)
            print(
                f"SUMMARY mode={mode:11s} workers={workers} "
                f"best={best:8.3f}s speedup={speedup:5.2f}x"
            )

    print("\n=== final ===")
    for mode, by_workers in summary.items():
        for workers, (best, speedup) in by_workers.items():
            print(f"{mode},{workers},{best:.3f},{speedup:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
