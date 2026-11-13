#!/usr/bin/env python3
"""End-to-end test and benchmark for the native threaded copy helper.

The test is skipped unless ``PRISM_NATIVE_BENCH=1`` is set, because it copies
real tables and therefore needs a populated PostgreSQL database.

What it does:

1. builds ``mysite/unmasque/native/pgcopy``;
2. creates two scratch schemas;
3. copies every requested table once with ``--serial`` and once with the
   threaded configuration (large tables threaded, small tables sequential);
4. verifies row counts, index names and ``UNLOGGED`` persistence;
5. prints the observed serial-vs-threaded speedup.

It also runs the same check with per-table ``--where`` predicates for both
``ctas`` and ``like_insert``, covering partial restores. A separate testcase
times native threaded copies against PRISM's default Python copy SQL on the
same tables. The source schema is only read. Scratch schemas are always dropped
again.

Examples::

    PRISM_NATIVE_BENCH=1 python3 -m pytest \
        mysite/unmasque/test/NativeParallelCopyTest.py -s -q

    # quicker run on a subset
    PRISM_NATIVE_BENCH=1 \
    PRISM_NATIVE_TABLES=region,nation,supplier,part,customer \
    python3 -m pytest mysite/unmasque/test/NativeParallelCopyTest.py -s -q

Environment variables:

    PRISM_NATIVE_BENCH=1          required, enables the test
    PRISM_NATIVE_TABLES           comma-separated tables (default: all TPCH SF1)
    PRISM_NATIVE_THREADS          large-table workers (default: 4)
    PRISM_NATIVE_INDEX_THREADS    concurrent index builders (default: 4)
    PRISM_NATIVE_THRESHOLD        large-table row cutoff (default: 100000)
    PRISM_NATIVE_REPEAT           measured repetitions (default: 1)
    PRISM_NATIVE_SQL              like_insert (default) or ctas
    PRISM_NATIVE_PGCOPY           path to a prebuilt pgcopy binary
    PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD
                                  database connection (defaults: localhost/5432/tpch/postgres/postgres)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extensions import make_dsn

DEFAULT_TABLES = [
    "lineitem",
    "orders",
    "partsupp",
    "customer",
    "part",
    "supplier",
    "region",
    "nation",
]

# Predicates used by the WHERE-restore coverage. They are trusted test SQL,
# just like the predicates PRISM generates internally.
TPCH_WHERES = {
    "lineitem": "l_quantity < 10",
    "orders": "o_totalprice > 100000",
    "partsupp": "ps_supplycost < 500",
    "customer": "c_acctbal > 5000",
    "part": "p_retailprice < 1000",
    "supplier": "s_acctbal > 1000",
    "region": "r_regionkey < 3",
    "nation": "n_nationkey < 10",
}

pytestmark = pytest.mark.skipif(
    os.environ.get("PRISM_NATIVE_BENCH") != "1",
    reason="set PRISM_NATIVE_BENCH=1 to run the native copy benchmark",
)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _connection_kwargs():
    return {
        "host": _env("PGHOST", "localhost"),
        "port": _env("PGPORT", "5432"),
        "dbname": _env("PGDATABASE", "tpch"),
        "user": _env("PGUSER", "postgres"),
        "password": _env("PGPASSWORD", "postgres"),
    }


def _connect():
    return psycopg2.connect(**_connection_kwargs())


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qualified(schema: str, table: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(table)}"


def _reset_schema(schema: str):
    conn = _connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_quote_ident(schema)} CASCADE;")
            cur.execute(f"CREATE SCHEMA {_quote_ident(schema)};")
    finally:
        conn.close()


def _drop_schema(schema: str):
    conn = _connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_quote_ident(schema)} CASCADE;")
    finally:
        conn.close()


def _source_counts(
    source: str, tables: list[str], wheres: dict[str, str] | None = None
) -> dict[str, int]:
    wheres = wheres or {}
    conn = _connect()
    try:
        counts = {}
        with conn.cursor() as cur:
            for table in tables:
                where = wheres.get(table)
                suffix = f" WHERE {where}" if where else ""
                cur.execute(
                    f"SELECT count(*) FROM {_qualified(source, table)}{suffix};"
                )
                counts[table] = cur.fetchone()[0]
        conn.rollback()
        return counts
    finally:
        conn.close()


def _table_persistence(schema: str, table: str) -> str:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.relpersistence FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s",
                (schema, table),
            )
            row = cur.fetchone()
            return row[0] if row else ""
    finally:
        conn.close()


def _index_columns(cur, schema: str, table: str) -> set[tuple[str, ...]]:
    """Return the indexed column tuples of a table, ignoring index names."""
    cur.execute(
        "SELECT i.indexrelid, a.attname, k.ord "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "
        "WHERE n.nspname = %s AND c.relname = %s "
        "ORDER BY i.indexrelid, k.ord",
        (schema, table),
    )
    indexes: dict[int, list[str]] = {}
    for index_oid, column, _ in cur.fetchall():
        indexes.setdefault(index_oid, []).append(column)
    return {tuple(columns) for columns in indexes.values()}


def _verify_destination(
    schema: str,
    expected: dict[str, int],
    source: str,
    *,
    expect_indexes: bool,
    compare_index_names: bool = True,
):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for table, want in expected.items():
                cur.execute(f"SELECT count(*) FROM {_qualified(schema, table)};")
                got = cur.fetchone()[0]
                assert got == want, f"{schema}.{table}: {got} rows, expected {want}"

                cur.execute(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = %s AND tablename = %s",
                    (schema, table),
                )
                dest_indexes = {row[0] for row in cur.fetchall()}
                if expect_indexes:
                    if compare_index_names:
                        cur.execute(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = %s AND tablename = %s",
                            (source, table),
                        )
                        src_indexes = {row[0] for row in cur.fetchall()}
                        assert dest_indexes == src_indexes, (
                            f"{schema}.{table}: indexes {sorted(dest_indexes)}, "
                            f"expected {sorted(src_indexes)}"
                        )
                    else:
                        # LIKE ... INCLUDING INDEXES keeps the same indexed
                        # columns but PostgreSQL generates new index names.
                        assert _index_columns(cur, schema, table) == \
                            _index_columns(cur, source, table), (
                                f"{schema}.{table}: indexed columns differ from "
                                f"{source}.{table}"
                            )
                else:
                    assert not dest_indexes, (
                        f"{schema}.{table}: ctas should not copy indexes, "
                        f"found {sorted(dest_indexes)}"
                    )
        conn.rollback()
    finally:
        conn.close()

    for table in expected:
        assert _table_persistence(schema, table) == "u", (
            f"{schema}.{table} should be UNLOGGED"
        )


def _build_pgcopy(native_dir: Path) -> Path:
    override = os.environ.get("PRISM_NATIVE_PGCOPY")
    if override:
        binary = Path(override).expanduser().resolve()
        assert binary.is_file(), f"PRISM_NATIVE_PGCOPY does not exist: {binary}"
        return binary

    binary = native_dir / "pgcopy"
    result = subprocess.run(
        ["make", "-C", str(native_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "failed to build pgcopy:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert binary.is_file(), f"make did not produce {binary}"
    return binary


def _run_pgcopy(
    binary: Path,
    source: str,
    dest: str,
    tables: list[str],
    counts: dict[str, int],
    *,
    serial: bool,
    max_threads: int,
    index_threads: int,
    threshold: int,
    sql_shape: str,
    wheres: dict[str, str] | None = None,
):
    command = [
        str(binary),
        "--conninfo",
        make_dsn(**_connection_kwargs()),
        "--source",
        source,
        "--dest",
        dest,
        "--tables",
        ",".join(tables),
        "--rows",
        ",".join(f"{table}:{counts[table]}" for table in tables),
        "--threshold",
        str(threshold),
        "--max-threads",
        str(max_threads),
        "--index-threads",
        str(index_threads),
        "--sql",
        sql_shape,
    ]
    for table, where in (wheres or {}).items():
        if table in tables and where:
            command.extend(["--where", f"{table}={where}"])
    if serial:
        command.append("--serial")

    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"pgcopy failed ({result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return _parse_output(result.stdout), result.stdout


def _parse_output(output: str):
    parsed = {
        "plan": {},
        "results": [],
        "index_results": [],
        "seconds": {},
        "failures": None,
    }
    for line in output.splitlines():
        fields = line.split("\t")
        tag = fields[0]
        if tag == "PLAN":
            for field in fields[1:]:
                key, _, value = field.partition("=")
                parsed["plan"][key] = value
        elif tag == "RESULT":
            parsed["results"].append(
                {
                    "worker": int(fields[1]),
                    "kind": fields[2],
                    "table": fields[3],
                    "seconds": float(fields[4]),
                    "copied": int(fields[5]),
                    "ok": fields[6] == "1",
                    "error": fields[7] if len(fields) > 7 else "",
                }
            )
        elif tag == "INDEX_RESULT":
            parsed["index_results"].append(
                {
                    "worker": int(fields[1]),
                    "table": fields[2],
                    "seconds": float(fields[3]),
                    "ok": fields[4] == "1",
                    "error": fields[5] if len(fields) > 5 else "",
                }
            )
        elif tag.endswith("_SECONDS"):
            parsed["seconds"][tag] = float(fields[1])
        elif tag == "FAILURES":
            parsed["failures"] = int(fields[1])
    return parsed


def _assert_clean_run(parsed, label: str):
    assert parsed["failures"] == 0, f"{label}: {parsed['failures']} failed table(s)"
    for item in parsed["results"]:
        assert item["ok"], f"{label}: {item['table']} failed: {item['error']}"
    for item in parsed["index_results"]:
        assert item["ok"], f"{label}: index on {item['table']} failed: {item['error']}"


def _run_benchmark(
    binary: Path,
    source: str,
    tables: list[str],
    *,
    sql_shape: str,
    wheres: dict[str, str] | None,
    max_threads: int,
    index_threads: int,
    threshold: int,
    repeat: int,
    label: str,
) -> float:
    expect_indexes = sql_shape == "like_insert"
    counts = _source_counts(source, tables, wheres)
    serial_schema = f"bench_native_{label}_{os.getpid()}_serial"
    threaded_schema = f"bench_native_{label}_{os.getpid()}_threaded"

    serial_totals: list[float] = []
    threaded_totals: list[float] = []
    serial_per_table: dict[str, float] = {}
    threaded_per_table: dict[str, float] = {}

    print(f"\nlabel={label} source={source} tables={tables}")
    print(
        f"sql={sql_shape} threads={max_threads} index_threads={index_threads} "
        f"threshold={threshold} repeat={repeat} wheres={wheres or {}}"
    )

    try:
        for run in range(repeat):
            _reset_schema(serial_schema)
            serial, _ = _run_pgcopy(
                binary,
                source,
                serial_schema,
                tables,
                counts,
                serial=True,
                max_threads=max_threads,
                index_threads=index_threads,
                threshold=threshold,
                sql_shape=sql_shape,
                wheres=wheres,
            )
            _assert_clean_run(serial, f"serial run {run + 1}")
            _verify_destination(
                serial_schema, counts, source, expect_indexes=expect_indexes
            )
            serial_totals.append(serial["seconds"]["TOTAL_SECONDS"])
            for item in serial["results"]:
                serial_per_table[item["table"]] = min(
                    serial_per_table.get(item["table"], float("inf")),
                    item["seconds"],
                )

            _reset_schema(threaded_schema)
            threaded, _ = _run_pgcopy(
                binary,
                source,
                threaded_schema,
                tables,
                counts,
                serial=False,
                max_threads=max_threads,
                index_threads=index_threads,
                threshold=threshold,
                sql_shape=sql_shape,
                wheres=wheres,
            )
            _assert_clean_run(threaded, f"threaded run {run + 1}")
            _verify_destination(
                threaded_schema, counts, source, expect_indexes=expect_indexes
            )
            threaded_totals.append(threaded["seconds"]["TOTAL_SECONDS"])
            for item in threaded["results"]:
                threaded_per_table[item["table"]] = min(
                    threaded_per_table.get(item["table"], float("inf")),
                    item["seconds"],
                )

            print(
                f"run={run + 1} serial={serial['seconds']['TOTAL_SECONDS']:.3f}s "
                f"(copy={serial['seconds']['COPY_SECONDS']:.3f}s, "
                f"index={serial['seconds']['INDEX_SECONDS']:.3f}s) "
                f"threaded={threaded['seconds']['TOTAL_SECONDS']:.3f}s "
                f"(copy={threaded['seconds']['COPY_SECONDS']:.3f}s, "
                f"index={threaded['seconds']['INDEX_SECONDS']:.3f}s)"
            )
    finally:
        _drop_schema(serial_schema)
        _drop_schema(threaded_schema)

    best_serial = min(serial_totals)
    best_threaded = min(threaded_totals)
    speedup = best_serial / best_threaded if best_threaded else float("inf")

    print("\nper-table copy seconds (best of runs):")
    for table in sorted(
        tables, key=lambda name: serial_per_table.get(name, 0), reverse=True
    ):
        print(
            f"  {table:12s} serial={serial_per_table[table]:7.3f} "
            f"threaded={threaded_per_table[table]:7.3f}"
        )
    print(
        f"\nSPEEDUP best_serial={best_serial:.3f}s "
        f"best_threaded={best_threaded:.3f}s "
        f"speedup={speedup:.2f}x"
    )
    return speedup


def _python_copy_table(conn, source, dest, table, sql_shape, where=None):
    """Execute the Python copy shape used by SchemaSanitizer backup/restore."""
    dst = _qualified(dest, table)
    src = _qualified(source, table)
    where_sql = f" WHERE {where}" if where else ""
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {dst} CASCADE;")
        if sql_shape == "like_insert":
            cur.execute(f"CREATE UNLOGGED TABLE {dst} (LIKE {src} INCLUDING INDEXES);")
            cur.execute(f"ALTER TABLE {dst} SET (autovacuum_enabled = false);")
            cur.execute(f"INSERT INTO {dst} SELECT * FROM {src}{where_sql};")
        else:
            cur.execute(f"CREATE UNLOGGED TABLE {dst} AS SELECT * FROM {src}{where_sql};")
            cur.execute(f"ALTER TABLE {dst} SET (autovacuum_enabled = false);")
    conn.commit()


def _run_python_copy(source, dest, tables, sql_shape="like_insert", wheres=None):
    """Time the default Python per-table copy, matching production SQL."""
    wheres = wheres or {}
    per_table = {}
    started = time.perf_counter()
    conn = _connect()
    try:
        for table in tables:
            one_started = time.perf_counter()
            _python_copy_table(
                conn, source, dest, table, sql_shape, wheres.get(table)
            )
            per_table[table] = time.perf_counter() - one_started
    finally:
        conn.close()
    return time.perf_counter() - started, per_table


def _test_settings():
    source = _env("PRISM_NATIVE_SOURCE", "fresh")
    tables = [
        table.strip()
        for table in _env("PRISM_NATIVE_TABLES", ",".join(DEFAULT_TABLES)).split(",")
        if table.strip()
    ]
    assert tables, "PRISM_NATIVE_TABLES is empty"
    return {
        "source": source,
        "tables": tables,
        "max_threads": int(_env("PRISM_NATIVE_THREADS", "4")),
        "index_threads": int(_env("PRISM_NATIVE_INDEX_THREADS", "4")),
        "threshold": int(_env("PRISM_NATIVE_THRESHOLD", "100000")),
        "repeat": max(1, int(_env("PRISM_NATIVE_REPEAT", "1"))),
    }


def test_native_threaded_copy_is_correct_and_faster(capsys):
    native_dir = Path(__file__).resolve().parents[1] / "native"
    binary = _build_pgcopy(native_dir)
    settings = _test_settings()

    sql_shape = _env("PRISM_NATIVE_SQL", "like_insert")
    assert sql_shape in {"like_insert", "ctas"}, (
        f"PRISM_NATIVE_SQL must be like_insert or ctas, got {sql_shape!r}"
    )

    speedup = _run_benchmark(
        binary,
        settings["source"],
        settings["tables"],
        sql_shape=sql_shape,
        wheres=None,
        max_threads=settings["max_threads"],
        index_threads=settings["index_threads"],
        threshold=settings["threshold"],
        repeat=settings["repeat"],
        label=f"copy_{sql_shape}",
    )

    # Correctness is the hard requirement. Speedup is measured and printed; on
    # very small table sets the pthread/libpq start-up cost can make the
    # threaded run slower, so a speed assertion is only made when requested.
    if os.environ.get("PRISM_NATIVE_ASSERT_SPEEDUP") == "1":
        assert speedup > 1.0, f"expected a speedup, measured {speedup:.2f}x"

    captured = capsys.readouterr()
    sys.stdout.write(captured.out)


def test_native_threaded_copy_with_where_predicates(capsys):
    native_dir = Path(__file__).resolve().parents[1] / "native"
    binary = _build_pgcopy(native_dir)
    settings = _test_settings()

    tables = settings["tables"]
    wheres = {table: TPCH_WHERES[table] for table in tables if table in TPCH_WHERES}
    assert wheres, (
        "none of the selected tables have a WHERE predicate; "
        f"choose from {sorted(TPCH_WHERES)}"
    )

    full_counts = _source_counts(settings["source"], tables)
    filtered_counts = _source_counts(settings["source"], tables, wheres)
    assert any(
        filtered_counts[table] < full_counts[table] for table in wheres
    ), "the WHERE predicates did not filter any rows"

    for sql_shape in ("ctas", "like_insert"):
        _run_benchmark(
            binary,
            settings["source"],
            tables,
            sql_shape=sql_shape,
            wheres=wheres,
            max_threads=settings["max_threads"],
            index_threads=settings["index_threads"],
            threshold=settings["threshold"],
            repeat=settings["repeat"],
            label=f"where_{sql_shape}",
        )

    captured = capsys.readouterr()
    sys.stdout.write(captured.out)


def test_native_copy_outperforms_python_default_copy(capsys):
    """Compare native threaded copies with PRISM's Python copy SQL.

    Both sides use the production default ``like_insert`` shape:
    ``CREATE UNLOGGED TABLE dst (LIKE src INCLUDING INDEXES); INSERT ...``.
    The native timing includes its separate index-build phase, so index work is
    counted on both sides.
    """
    native_dir = Path(__file__).resolve().parents[1] / "native"
    binary = _build_pgcopy(native_dir)
    settings = _test_settings()

    source = settings["source"]
    tables = settings["tables"]
    repeat = settings["repeat"]
    counts = _source_counts(source, tables)

    python_schema = f"bench_python_{os.getpid()}"
    native_schema = f"bench_native_{os.getpid()}"

    python_totals: list[float] = []
    native_totals: list[float] = []
    python_per_table: dict[str, float] = {}
    native_per_table: dict[str, float] = {}

    def run_python():
        _reset_schema(python_schema)
        total, per_table = _run_python_copy(source, python_schema, tables)
        _verify_destination(
            python_schema,
            counts,
            source,
            expect_indexes=True,
            compare_index_names=False,
        )
        python_totals.append(total)
        for table, seconds in per_table.items():
            python_per_table[table] = min(
                python_per_table.get(table, float("inf")), seconds
            )
        return total

    def run_native():
        _reset_schema(native_schema)
        parsed, _ = _run_pgcopy(
            binary,
            source,
            native_schema,
            tables,
            counts,
            serial=False,
            max_threads=settings["max_threads"],
            index_threads=settings["index_threads"],
            threshold=settings["threshold"],
            sql_shape="like_insert",
        )
        _assert_clean_run(parsed, "native vs python")
        _verify_destination(native_schema, counts, source, expect_indexes=True)
        total = parsed["seconds"]["TOTAL_SECONDS"]
        native_totals.append(total)
        for item in parsed["results"]:
            native_per_table[item["table"]] = min(
                native_per_table.get(item["table"], float("inf")),
                item["seconds"],
            )
        return total

    print(f"\nsource={source} tables={tables} repeat={repeat}")
    try:
        for run in range(repeat):
            # Alternate order to reduce cache/order bias.
            if run % 2 == 0:
                python_total = run_python()
                native_total = run_native()
            else:
                native_total = run_native()
                python_total = run_python()
            print(
                f"run={run + 1} python={python_total:.3f}s "
                f"native={native_total:.3f}s "
                f"speedup={python_total / native_total:.2f}x"
            )
    finally:
        _drop_schema(python_schema)
        _drop_schema(native_schema)

    best_python = min(python_totals)
    best_native = min(native_totals)
    speedup = best_python / best_native if best_native else float("inf")

    print("\nper-table copy seconds (best of runs):")
    for table in sorted(
        tables, key=lambda name: python_per_table.get(name, 0), reverse=True
    ):
        print(
            f"  {table:12s} python={python_per_table[table]:8.3f} "
            f"native={native_per_table[table]:8.3f}"
        )
    print(
        f"\nPYTHON_VS_NATIVE best_python={best_python:.3f}s "
        f"best_native={best_native:.3f}s speedup={speedup:.2f}x"
    )

    if os.environ.get("PRISM_NATIVE_ASSERT_SPEEDUP") == "1":
        assert speedup > 1.0, (
            f"expected native copy to beat Python copy, measured {speedup:.2f}x"
        )

    captured = capsys.readouterr()
    sys.stdout.write(captured.out)
