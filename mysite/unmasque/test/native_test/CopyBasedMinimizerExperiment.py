"""Parameterized cold-cache tail-latency experiment for MQ minimizers.

Runs CopyBasedMinimizer, ViewMinimizer, and PKViewMinimizer on MQ-series queries.
Inside the minimizers the first probe of every halving iteration is executed
``repeats`` times (default 1).  Two views of the time are reported:

* ``with_overhead_s`` = create + index + analyze + exec + drop
* ``exec_only_s``     = query execution only

To measure a cold-cache view, the whole minimizer is run ``runs`` times
(default 3) and the database is restarted immediately before every run.  The
expt1 interleaved order is::

    prepare working schema -> restart DB -> CopyBased run 1
    prepare working schema -> restart DB -> ViewMinimizer run 1
    prepare working schema -> restart DB -> PKViewMinimizer run 1
    ...
    prepare working schema -> restart DB -> PKViewMinimizer run N

Because ``repeats`` is 1, every iteration contributes one timing sample per
run; the per-iteration metric is the **95th percentile (p95)** of those
cold-cache samples.  The cumulative curve is the running sum of per-iteration
p95 values.  The working schema is copied *before* the restart so the copy does
not warm caches used by the measured minimizer.

Outputs
-------
* Per-query merged plot: ``results/copy_minimizer_all_plots_<tag>_<expt>_<MQ>.png``
* Per-query CSVs: ``results/csv/copy_minimizer_{timings,costs,tail_latency}_<tag>_<expt>_<MQ>.csv``
* Aggregate summary (all run queries): ``results/copy_minimizer_mq_summary_<tag>_<expt>.png``
  and ``results/csv/copy_minimizer_mq_summary_<tag>_<expt>.csv``

Run (remaining MQ queries, excluding MQ18, expt1, 3 runs)::

    cd /Users/ahanapradhan/pycharm_projects/PRISM
    python3 -m pytest mysite/unmasque/test/native_test/CopyBasedMinimizerExperiment.py -s

Environment overrides::

    PRISM_DB_RESTART_CMD   explicit DB restart command
    PRISM_PG_BINDIR        PostgreSQL bin dir (pg_ctl + postgres)
    PRISM_PG_DATA_DIR      PostgreSQL data directory
    PRISM_MQ_IDS           comma-separated subset, e.g. MQ1,MQ2
    PRISM_MQ_RUNS          number of cold-cache runs (default: 3)
    PRISM_MQ_EXPTS         comma-separated experiments (default: expt1)
"""
import csv
import glob
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from mysite.unmasque.src.core.abstract.ExtractorBase import Base  # noqa: E402
from .copy_based_minimizer import CopyBasedMinimizer  # noqa: E402
from .view_minimizer import ViewMinimizer  # noqa: E402
from .pk_view_minimizer import PKViewMinimizer  # noqa: E402
from .hybrid_minimizer import HybridMinimizer  # noqa: E402
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # noqa: E402
from mysite.unmasque.src.util.Log import Log  # noqa: E402

DEFAULT_REPEATS = 1
DEFAULT_RUNS = 3

MINIMIZERS = (
    ("CopyBasedMinimizer", CopyBasedMinimizer, "copy"),
    ("ViewMinimizer", ViewMinimizer, "view"),
    ("PKViewMinimizer", PKViewMinimizer, "view"),
    ("HybridMinimizer", HybridMinimizer, "hybrid"),
)

EXPERIMENTS = {
    "expt1": (
        ("CopyBasedMinimizer", CopyBasedMinimizer, "copy"),
        ("ViewMinimizer", ViewMinimizer, "view"),
        ("PKViewMinimizer", PKViewMinimizer, "view"),
        ("HybridMinimizer", HybridMinimizer, "hybrid"),
    ),
    "expt2": (
        ("ViewMinimizer", ViewMinimizer, "view"),
        ("CopyBasedMinimizer", CopyBasedMinimizer, "copy"),
    ),
    "expt3": (
        ("CopyBasedMinimizer", CopyBasedMinimizer, "copy"),
        ("ViewMinimizer", ViewMinimizer, "view"),
    ),
}

MQ_SERIES_ORDER = ["MQ1", "MQ2", "MQ3", "MQ4", "MQ5", "MQ6", "MQ10", "MQ11", "MQ17", "MQ18", "MQ21"]

MQ_QUERIES = {
    "MQ1": {
        "core_tables": ["lineitem"],
        "sql": """SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM lineitem
WHERE
    l_shipdate <= DATE '1998-12-01' - INTERVAL '71 days'
GROUP BY
    l_returnflag,
    l_linestatus
ORDER BY
    l_returnflag,
    l_linestatus;""",
    },
    "MQ2": {
        "core_tables": ["part", "supplier", "partsupp", "nation", "region"],
        "sql": """SELECT
    s_acctbal,
    s_name,
    n_name,
    p_partkey,
    p_mfgr,
    s_address,
    s_phone,
    s_comment
FROM part, supplier, partsupp, nation, region
WHERE
    p_partkey = ps_partkey
    AND s_suppkey = ps_suppkey
    AND p_size = 38
    AND p_type LIKE '%TIN'
    AND s_nationkey = n_nationkey
    AND n_regionkey = r_regionkey
    AND r_name = 'MIDDLE EAST'
ORDER BY
    s_acctbal DESC,
    n_name,
    s_name,
    p_partkey
LIMIT 100;""",
    },
    "MQ3": {
        "core_tables": ["customer", "orders", "lineitem"],
        "sql": """SELECT
    l_orderkey,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
    o_orderdate,
    o_shippriority
FROM customer, orders, lineitem
WHERE
    c_mktsegment = 'BUILDING'
    AND c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND o_orderdate < DATE '1995-03-15'
    AND l_shipdate > DATE '1995-03-15'
GROUP BY
    l_orderkey,
    o_orderdate,
    o_shippriority
ORDER BY
    revenue DESC,
    o_orderdate
LIMIT 10;""",
    },
    "MQ4": {
        "core_tables": ["orders"],
        "sql": """SELECT
    o_orderdate,
    o_orderpriority,
    COUNT(*) AS order_count
FROM orders
WHERE
    o_orderdate >= DATE '1997-07-01'
    AND o_orderdate < DATE '1997-07-01' + INTERVAL '3 months'
GROUP BY
    o_orderdate,
    o_orderpriority
ORDER BY
    o_orderpriority
LIMIT 10;""",
    },
    "MQ5": {
        "core_tables": ["customer", "orders", "lineitem", "supplier", "nation", "region"],
        "sql": """SELECT
    n_name,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM customer, orders, lineitem, supplier, nation, region
WHERE
    c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND l_suppkey = s_suppkey
    AND c_nationkey = s_nationkey
    AND s_nationkey = n_nationkey
    AND n_regionkey = r_regionkey
    AND r_name = 'MIDDLE EAST'
    AND o_orderdate >= DATE '1994-01-01'
    AND o_orderdate < DATE '1994-01-01' + INTERVAL '1 year'
GROUP BY
    n_name
ORDER BY
    revenue DESC
LIMIT 100;""",
    },
    "MQ6": {
        "core_tables": ["lineitem"],
        "sql": """SELECT
    l_shipmode,
    SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE
    l_shipdate >= DATE '1994-01-01'
    AND l_shipdate < DATE '1994-01-01' + INTERVAL '1 year'
    AND l_quantity < 24
GROUP BY
    l_shipmode
LIMIT 100;""",
    },
    "MQ10": {
        "core_tables": ["customer", "orders", "lineitem", "nation"],
        "sql": """SELECT
    c_name,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
    c_acctbal,
    n_name,
    c_address,
    c_phone,
    c_comment
FROM customer, orders, lineitem, nation
WHERE
    c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND o_orderdate >= DATE '1994-01-01'
    AND o_orderdate < DATE '1994-01-01' + INTERVAL '3 months'
    AND l_returnflag = 'R'
    AND c_nationkey = n_nationkey
GROUP BY
    c_name,
    c_acctbal,
    c_phone,
    n_name,
    c_address,
    c_comment
ORDER BY
    revenue DESC
LIMIT 20;""",
    },
    "MQ11": {
        "core_tables": ["partsupp", "supplier", "nation"],
        "sql": """SELECT
    ps_comment,
    SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE
    ps_suppkey = s_suppkey
    AND s_nationkey = n_nationkey
    AND n_name = 'ARGENTINA'
GROUP BY
    ps_comment
ORDER BY
    value DESC
LIMIT 100;""",
    },
    "MQ17": {
        "core_tables": ["lineitem", "part"],
        "sql": """SELECT
    AVG(l_extendedprice) AS avg_total
FROM lineitem, part
WHERE
    p_partkey = l_partkey
    AND p_brand = 'Brand#52'
    AND p_container = 'LG CAN';""",
    },
    "MQ18": {
        "core_tables": ["customer", "orders", "lineitem"],
        "sql": """SELECT
    c_name,
    o_orderdate,
    o_totalprice,
    SUM(l_quantity)
FROM customer, orders, lineitem
WHERE
    c_phone LIKE '27-%'
    AND c_custkey = o_custkey
    AND o_orderkey = l_orderkey
GROUP BY
    c_name,
    o_orderdate,
    o_totalprice
ORDER BY
    o_orderdate,
    o_totalprice DESC
LIMIT 100;""",
    },
    "MQ21": {
        "core_tables": ["supplier", "lineitem", "orders", "nation"],
        "sql": """SELECT
    s_name,
    COUNT(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE
    s_suppkey = l1.l_suppkey
    AND o_orderkey = l1.l_orderkey
    AND o_orderstatus = 'F'
    AND s_nationkey = n_nationkey
    AND n_name = 'GERMANY'
GROUP BY
    s_name
ORDER BY
    numwait DESC,
    s_name
LIMIT 100;""",
    },
}

RESULTS_DIR = Path(__file__).parent / "results"
CSV_DIR = RESULTS_DIR / "csv"
MINIMIZER_COLORS = {
    "ViewMinimizer": "tab:blue",
    "CopyBasedMinimizer": "tab:orange",
    "PKViewMinimizer": "tab:green",
    "HybridMinimizer": "tab:red",
}

TIMING_FIELDS = ["run", "iteration", "table", "rep", "create_s", "index_s", "analyze_s", "exec_s",
                 "drop_s", "with_overhead_s", "exec_only_s"]
COST_FIELDS = ["run", "iteration", "table", "total_cost", "limit_cost",
               "scan_node", "scan_cost", "scan_rows"]


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def p95(values):
    """95th percentile with linear interpolation (numpy's default method)."""
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    position = (len(data) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(data) - 1)
    return data[lower] + (data[upper] - data[lower]) * (position - lower)


# --------------------------------------------------------------------------- #
# EXPLAIN parsing
# --------------------------------------------------------------------------- #
def _iter_nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _iter_nodes(child)


def summarize_plan(rows, table_names):
    """Pull the interesting costs out of one ``EXPLAIN (FORMAT JSON)`` result."""
    data = rows[0][0]
    if isinstance(data, str):
        data = json.loads(data)
    root = data[0]["Plan"]

    limit_cost = None
    body = root
    if root["Node Type"] == "Limit" and root.get("Plans"):
        limit_cost = root["Total Cost"]
        body = root["Plans"][0]

    scan = next((n for n in _iter_nodes(root) if n.get("Relation Name") in table_names), None)
    return {
        "total_cost": body["Total Cost"],
        "limit_cost": limit_cost,
        "scan_node": scan["Node Type"] if scan else None,
        "scan_cost": scan["Total Cost"] if scan else None,
        "scan_rows": scan["Plan Rows"] if scan else None,
    }


class CopyBasedMinimizerExperiment(unittest.TestCase):
    repeats = DEFAULT_REPEATS
    runs = DEFAULT_RUNS
    restart_timeout_s = 120
    restart_wait_s = 120

    def setUp(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = ConnectionHelperFactory().createConnectionHelper()
        self.conn.connectUsingParams()
        self.config = self.conn.config
        self.prep = Base(self.conn, "ExperimentPrep")
        self._saved_flags = {name: getattr(self.config, name) for name in
                             ("detect_union", "detect_oj", "detect_nep", "detect_or", "use_cs2")}
        for name in self._saved_flags:
            setattr(self.config, name, False)
        self.query_id = "MQ18"
        self.query = MQ_QUERIES["MQ18"]["sql"]
        self.core_tables = list(MQ_QUERIES["MQ18"]["core_tables"])
        self.expt_name = None
        self._public_sizes = {}

    def tearDown(self):
        try:
            self._restore_normal_schema()
        finally:
            self.conn.closeConnection()
        for name, value in self._saved_flags.items():
            setattr(self.config, name, value)

    def configure_query(self, query_id):
        info = MQ_QUERIES[query_id]
        self.query_id = query_id
        self.query = info["sql"]
        self.core_tables = list(info["core_tables"])
        self.prep.set_all_relations(list(self.core_tables))
        self._public_sizes = self._sizes(self.config.user_schema)

    def _sizes(self, schema):
        return {table: int(self.conn.execute_sql_fetchone_0(
            self.conn.queries.get_row_count(f"{schema}.{table}")))
            for table in self.core_tables}

    def _restore_normal_schema(self):
        """Normal backup/restore end state: user schema intact, working schema gone."""
        if self.conn.conn is None:
            return
        self.conn.conn.rollback()
        if self._public_sizes:
            self.assertEqual(self._sizes(self.config.user_schema), self._public_sizes,
                             f"the user schema must not be modified by the experiment ({self.query_id})")
        self.prep.remove_footprint()  # DROP SCHEMA unmasque CASCADE
        self.conn.conn.commit()
        still_there = self.conn.execute_sql_fetchone_0(
            "select exists(select 1 from pg_namespace where nspname = 'unmasque');")
        self.assertFalse(still_there, "working schema must be deleted after the test")

    def _prepare_working_schema(self):
        """Fresh unmasque schema + Python-threaded copy of the core tables."""
        self.conn.conn.rollback()
        self.prep._create_working_schema()
        self.prep.take_backup(self.core_tables)
        return self._sizes(self.config.schema)

    def _assert_physical_order_changed(self, table):
        """The threaded copy must leave a different physical row order."""
        queries = self.conn.queries
        source_rows = self.conn.execute_sql_fetchall(
            queries.select_rows_by_ctid_order(f"{self.config.user_schema}.{table}", 100))[0]
        copied_rows = self.conn.execute_sql_fetchall(
            queries.select_rows_by_ctid_order(f"{self.config.schema}.{table}", 100))[0]
        self.assertEqual(len(source_rows), len(copied_rows))
        self.assertNotEqual([row[1:] for row in source_rows], [row[1:] for row in copied_rows],
                            f"threaded copy did not change the physical row order of {table}")

    # ----------------------------------------------------------------------- #
    # database restart (cold-cache setup)
    # ----------------------------------------------------------------------- #
    @staticmethod
    def _data_directory(conn):
        try:
            path = conn.execute_sql_fetchone_0("show data_directory;")
            return str(path) if path else None
        except Exception:
            return os.environ.get("PRISM_PG_DATA_DIR")

    @staticmethod
    def _postgres_bindir():
        """Directory holding both ``pg_ctl`` and ``postgres`` (the server build)."""
        override = os.environ.get("PRISM_PG_BINDIR")
        candidates = [Path(override)] if override else []
        for executable in ("postgres", "pg_ctl"):
            found = shutil.which(executable)
            if found:
                candidates.append(Path(found).resolve().parent)
        for pattern in ("/opt/homebrew/opt/postgresql@*/bin",
                        "/opt/homebrew/opt/postgresql/bin",
                        "/usr/local/opt/postgresql@*/bin",
                        "/usr/local/opt/postgresql/bin",
                        "/usr/lib/postgresql/*/bin",
                        "/usr/pgsql-*/bin"):
            candidates.extend(Path(path) for path in sorted(glob.glob(pattern), reverse=True))
        for directory in candidates:
            if (directory / "pg_ctl").is_file() and (directory / "postgres").is_file():
                return directory
        return None

    @staticmethod
    def _launchd_label(data_dir):
        """Homebrew launchd label whose plist points at this data directory."""
        if sys.platform != "darwin" or data_dir is None:
            return None
        for plist in sorted((Path.home() / "Library" / "LaunchAgents").glob("*postgres*.plist")):
            try:
                text = plist.read_text()
            except OSError:
                continue
            if data_dir not in text:
                continue
            label = plist.stem
            probe = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                   capture_output=True, text=True)
            if probe.returncode == 0:
                return label
        return None

    def _restart_command(self, data_dir):
        """Return (args, use_shell, description) for the configured restart."""
        override = os.environ.get("PRISM_DB_RESTART_CMD")
        if override:
            return override, True, override

        label = self._launchd_label(data_dir)
        if label:
            args = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]
            return args, False, " ".join(args)

        bindir = self._postgres_bindir()
        if data_dir and bindir:
            args = [str(bindir / "pg_ctl"), "-D", data_dir, "-m", "fast",
                    "-w", "-t", str(self.restart_timeout_s), "restart"]
            return args, False, " ".join(args)

        raise RuntimeError(
            "Could not determine how to restart PostgreSQL. Set PRISM_DB_RESTART_CMD "
            "(for example 'brew services restart postgresql@17') or PRISM_PG_BINDIR "
            "and PRISM_PG_DATA_DIR.")

    def _restart_database(self):
        """Restart PostgreSQL and wait until a *new* postmaster accepts queries."""
        if os.environ.get("PRISM_MQ_SKIP_RESTART", "").strip().lower() in {"1", "true", "yes"}:
            print("skipping database restart (PRISM_MQ_SKIP_RESTART set)")
            return
        data_dir = self._data_directory(self.conn)
        old_start = self.conn.execute_sql_fetchone_0("select pg_postmaster_start_time();")
        args, use_shell, description = self._restart_command(data_dir)

        self.conn.closeConnection()
        print(f"restarting database: {description}")
        started = time.perf_counter()
        try:
            subprocess.run(args, shell=use_shell, check=True, capture_output=True,
                           text=True, timeout=self.restart_timeout_s + 30)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"database restart failed: {exc.stderr or exc.stdout}") from exc
        self._reconnect(old_start)
        print(f"database restarted in {time.perf_counter() - started:.2f}s")

    def _reconnect(self, old_start):
        """Reconnect, retrying until the restarted postmaster is visible."""
        deadline = time.monotonic() + self.restart_wait_s
        last_error = None
        while time.monotonic() < deadline:
            try:
                self.conn.connectUsingParams()
                current_start = self.conn.execute_sql_fetchone_0(
                    "select pg_postmaster_start_time();")
            except Exception as exc:  # server still down / shutting down
                last_error = exc
                try:
                    self.conn.closeConnection()
                except Exception:
                    try:
                        if getattr(self.conn, "conn", None) is not None:
                            self.conn.conn.close()
                    except Exception:
                        pass
                    self.conn.conn = None
                time.sleep(0.25)
                continue
            if self.conn.conn is None:
                last_error = RuntimeError("reconnect completed without an active connection")
                time.sleep(0.25)
                continue
            if old_start is None or (current_start is not None and current_start != old_start):
                return
            # We reached the old postmaster while it was still shutting down.
            try:
                self.conn.closeConnection()
            except Exception:
                try:
                    if getattr(self.conn, "conn", None) is not None:
                        self.conn.conn.close()
                except Exception:
                    pass
                self.conn.conn = None
            time.sleep(0.25)
        raise RuntimeError(f"database did not restart within {self.restart_wait_s}s: {last_error}")

    # ----------------------------------------------------------------------- #
    # cost capture
    # ----------------------------------------------------------------------- #
    def _cost_hook(self, mode, minimizer):
        """Capture planner costs once per halving iteration (called by the minimizer)."""
        queries = self.conn.queries
        logger = Log("PlanCost", self.config.log_level)
        costs = []

        def hook(iteration, tabname, query):
            names = {tabname,
                     minimizer._get_dirty_name(tabname),
                     queries.get_restore_name(tabname)}
            view_name = None
            summary = dict.fromkeys(COST_FIELDS[3:])
            try:
                set_path = queries.set_search_path(self.config.schema)
                if mode == "view":
                    view_name = f"{self.config.schema}.explain_query_view_{iteration}"
                    self.conn.execute_sql([set_path,
                                           queries.drop_view(view_name),
                                           queries.create_view_as(view_name, query)])
                    target = queries.get_star(view_name)
                else:
                    target = query
                target = target.strip().rstrip(";")
                rows, _ = self.conn.execute_sql_fetchall(
                    f"{set_path} EXPLAIN (FORMAT JSON) {target}")
                summary = summarize_plan(rows, names)
            except Exception as exc:
                self.conn.conn.rollback()
                logger.error(f"EXPLAIN cost probe failed: {exc}")
            finally:
                if view_name is not None:
                    self.conn.execute_sql([queries.drop_view(view_name)])
            costs.append({"iteration": iteration, "table": tabname, **summary})
            logger.debug(f"PLAN_COST: {iteration} {tabname} {summary}")

        return hook, costs

    def _run_minimizer(self, cls, mode, all_sizes, run):
        minimizer = cls(self.conn, self.core_tables, all_sizes, False)
        minimizer.repeats = self.repeats
        hook, costs = self._cost_hook(mode, minimizer)
        minimizer.on_iteration = hook
        self.assertTrue(minimizer.doJob(self.query), f"{self.query_id} {cls.__name__} failed")
        for record in minimizer.timing_records:
            record["run"] = run
        for cost in costs:
            cost["run"] = run
        return minimizer.timing_records, costs, minimizer.iteration

    # ----------------------------------------------------------------------- #
    # output
    # ----------------------------------------------------------------------- #
    @staticmethod
    def _group(records, key):
        grouped = {}
        for record in records:
            if record.get(key) is not None:
                grouped.setdefault(record["iteration"], []).append(record[key])
        return grouped

    @staticmethod
    def _group_by_run(records, key):
        grouped = {}
        for record in records:
            if record.get(key) is not None:
                grouped.setdefault(record["run"], []).append(record[key])
        return grouped

    @staticmethod
    def _cumulative(grouped):
        iterations = sorted(grouped)
        total, running = 0.0, []
        for i in iterations:
            total += p95(grouped[i])
            running.append(total)
        return iterations, running

    def _write_csv(self, filename, fields, per_minimizer):
        path = CSV_DIR / filename
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["minimizer"] + fields)
            for name, records in per_minimizer.items():
                for record in records:
                    writer.writerow([name] + [record.get(f, "") for f in fields])
        print(f"wrote {path}")

    def _write_tail_csv(self, timings, filename):
        path = CSV_DIR / filename
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["minimizer", "iteration", "samples",
                             "p95_with_overhead_s", "p95_exec_only_s"])
            for name, records in timings.items():
                overhead = self._group(records, "with_overhead_s")
                exec_only = self._group(records, "exec_only_s")
                for iteration in sorted(set(overhead) | set(exec_only)):
                    writer.writerow([
                        name,
                        iteration,
                        len(overhead.get(iteration, exec_only.get(iteration, []))),
                        round(p95(overhead[iteration]), 4) if overhead.get(iteration) else "",
                        round(p95(exec_only[iteration]), 4) if exec_only.get(iteration) else "",
                    ])
        print(f"wrote {path}")

    def _tag(self, filename, expt=None, query_id=None):
        path = Path(filename)
        expt = expt or getattr(self, "expt_name", None)
        query_id = query_id or getattr(self, "query_id", None)
        suffix = f"_{self.repeats}rep_{self.runs}runs"
        if expt:
            suffix += f"_{expt}"
        if query_id:
            suffix += f"_{query_id}"
        return f"{path.stem}{suffix}{path.suffix}"

    def _metric_label(self, filename):
        stem = Path(filename).stem
        # remove known suffix parts
        for part in (f"_{self.repeats}rep_{self.runs}runs",
                     f"_{getattr(self, 'expt_name', '')}" if getattr(self, 'expt_name', None) else "",
                     f"_{getattr(self, 'query_id', '')}" if getattr(self, 'query_id', None) else ""):
            if part and stem.endswith(part):
                stem = stem[:-len(part)]
            elif part and part in stem:
                stem = stem.replace(part, "")
        prefix = "copy_minimizer_"
        return stem[len(prefix):] if stem.startswith(prefix) else stem

    def _plot_readings(self, timings, key, ylabel, title, filename):
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax2 = ax.twinx()
        for name, records in timings.items():
            color = MINIMIZER_COLORS[name]
            grouped = self._group(records, key)
            iterations = sorted(grouped)
            ax.scatter([i for i in iterations for _ in grouped[i]],
                       [v for i in iterations for v in grouped[i]],
                       s=18, alpha=0.40, color=color,
                       label=f"{name}: cold-cache runs (n={self.runs})")
            ax.plot(iterations, [p95(grouped[i]) for i in iterations],
                    marker="o", linewidth=2, color=color, label=f"{name}: p95")
            cum_x, cum_y = self._cumulative(grouped)
            ax2.plot(cum_x, cum_y, linestyle="--", linewidth=1.5, color=color,
                     label=f"{name}: cumulative p95 (right axis)")
        ax.set_xlabel("ctid-halving iteration")
        ax.set_ylabel(ylabel)
        ax2.set_ylabel("Cumulative p95 time (s)")
        ax.grid(linestyle=":", alpha=0.5)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=9)
        fig.suptitle(f"{title} ({self.query_id}, {self.runs} cold-cache runs, p95)")
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _plot_tail_summary(self, timings, filename):
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        runs = list(range(1, self.runs + 1))
        width = 0.36
        for ax, (key, title) in zip(axes, (("with_overhead_s", "Including create / index / analyze / drop"),
                                           ("exec_only_s", "Query execution only"))):
            for index, (name, records) in enumerate(timings.items()):
                color = MINIMIZER_COLORS[name]
                grouped = self._group_by_run(records, key)
                values = [p95(grouped.get(run, [])) or 0.0 for run in runs]
                positions = [run + (index - 0.5) * width for run in runs]
                ax.bar(positions, values, width=width, color=color,
                       label=f"{name}: per-run p95")
                overall_vals = [r[key] for r in records if r.get(key) is not None]
                if overall_vals:
                    overall = p95(overall_vals)
                    ax.axhline(overall, linestyle="--", linewidth=1.3, color=color, alpha=0.85,
                               label=f"{name}: overall p95 = {overall:.3f}s")
                for x, value in zip(positions, values):
                    ax.text(x, value, f"{value:.2f}", ha="center", va="bottom",
                            fontsize=7, rotation=90)
            ax.set_xticks(runs)
            ax.set_xticklabels([f"run {run}" for run in runs])
            ax.set_title(title)
            ax.set_ylabel("Tail latency p95 (s)")
            ax.grid(axis="y", linestyle=":", alpha=0.5)
            ax.legend(fontsize=8)
        fig.suptitle(f"Cold-cache tail latency per run ({self.query_id}, {self.runs} runs, p95)")
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _plot_costs(self, costs, key, ylabel, title, filename):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for name, entries in costs.items():
            grouped = {}
            for cost in entries:
                if cost[key] is not None:
                    grouped.setdefault(cost["iteration"], []).append(cost[key])
            points = sorted((iteration, statistics.median(values))
                            for iteration, values in grouped.items())
            if points:
                ax.plot([p[0] for p in points], [p[1] for p in points], marker="o",
                        linewidth=1.5, color=MINIMIZER_COLORS[name], label=name)
        ax.set_yscale("log")
        ax.set_xlabel("ctid-halving iteration")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title} ({self.query_id}, median over {self.runs} runs)", fontsize=10)
        ax.grid(linestyle=":", alpha=0.5, which="both")
        ax.legend()
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _combine_plots(self, rows, out_name):
        import matplotlib.image as mpimg
        loaded = [[(name, mpimg.imread(RESULTS_DIR / name)) for name in row] for row in rows]
        ratios = [max(img.shape[0] / img.shape[1] for _, img in row) / len(row) for row in loaded]
        fig = plt.figure(figsize=(14, 14 * sum(ratios) + 0.8), layout="constrained")
        grid = fig.add_gridspec(len(loaded), 1, height_ratios=ratios)
        for r, row in enumerate(loaded):
            cells = grid[r].subgridspec(1, len(row))
            for c, (name, img) in enumerate(row):
                ax = fig.add_subplot(cells[0, c])
                ax.imshow(img)
                ax.axis("off")
                ax.set_title(self._metric_label(name), loc="left", fontsize=12, fontweight="bold")
        expt = getattr(self, "expt_name", None)
        title = f"{self.query_id} - {self.runs} cold-cache runs, {self.repeats} probe/iteration, tail latency p95"
        if expt:
            title += f" ({expt})"
        fig.suptitle(title, fontsize=14)
        path = RESULTS_DIR / out_name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    # ----------------------------------------------------------------------- #
    def _run_experiment(self, minimizer_order=None, expt_name=None):
        minimizer_order = minimizer_order or MINIMIZERS
        self.expt_name = expt_name
        timings = {name: [] for name, _, _ in minimizer_order}
        costs = {name: [] for name, _, _ in minimizer_order}
        iterations = {name: [] for name, _, _ in minimizer_order}
        checked_order = False
        order_names = [name for name, _, _ in minimizer_order]
        print(f"\n=== {self.query_id} {expt_name or 'expt'}: order {' -> '.join(order_names)} ===")

        for run in range(1, self.runs + 1):
            for name, cls, mode in minimizer_order:
                all_sizes = self._prepare_working_schema()
                if not checked_order:
                    for table in all_sizes:
                        self._assert_physical_order_changed(table)
                    checked_order = True

                self._restart_database()
                run_timings, run_costs, iters = self._run_minimizer(
                    cls, mode, all_sizes, run)
                timings[name].extend(run_timings)
                costs[name].extend(run_costs)
                iterations[name].append(iters)
                exec_vals = [r['exec_only_s'] for r in run_timings]
                exec_p95 = p95(exec_vals) if exec_vals else 0.0
                print(f"{self.query_id} {expt_name or 'expt'} run {run}/{self.runs}: {name} finished, "
                      f"{len(run_timings)} readings over {iters} iterations "
                      f"(exec-only p95 {exec_p95:.3f}s)", flush=True)

        for name, counts in iterations.items():
            print(f"{self.query_id} {expt_name or 'expt'} {name} iteration counts per run: {counts}")

        self._write_csv(self._tag("copy_minimizer_timings.csv"), TIMING_FIELDS, timings)
        self._write_csv(self._tag("copy_minimizer_costs.csv"), COST_FIELDS, costs)
        self._write_tail_csv(timings, self._tag("copy_minimizer_tail_latency.csv"))

        for name, records in timings.items():
            for key in ("with_overhead_s", "exec_only_s"):
                values = [r[key] for r in records if r.get(key) is not None]
                if values:
                    print(f"{self.query_id} {name} overall {key} p95: {p95(values):.4f}s")

        plot_files = [self._tag("copy_minimizer_timings_with_overhead.png"),
                      self._tag("copy_minimizer_timings_exec_only.png"),
                      self._tag("copy_minimizer_timings_tail_summary.png"),
                      self._tag("copy_minimizer_cost_total.png"),
                      self._tag("copy_minimizer_cost_scan.png")]
        self._plot_readings(timings, "with_overhead_s", "Time (s)",
                            "Per-iteration time INCLUDING create/index/analyze/drop",
                            plot_files[0])
        self._plot_readings(timings, "exec_only_s", "Time (s)",
                            "Per-iteration time, query execution only",
                            plot_files[1])
        self._plot_tail_summary(timings, plot_files[2])
        self._plot_costs(costs, "total_cost", "Planner total cost (below LIMIT)",
                         "Per-iteration estimated cost of the whole query",
                         plot_files[3])
        self._plot_costs(costs, "scan_cost", "Planner cost of scan on halved table",
                         "Per-iteration estimated cost of scanning the halved table",
                         plot_files[4])
        self._combine_plots([[plot_files[0]],
                             [plot_files[1]],
                             [plot_files[2]],
                             [plot_files[3], plot_files[4]]],
                            self._tag("copy_minimizer_all_plots.png"))
        for name in plot_files:
            (RESULTS_DIR / name).unlink(missing_ok=True)
        self.assertTrue(all(timings.values()), f"no timing records collected for {self.query_id}")
        return timings, costs, iterations

    # ----------------------------------------------------------------------- #
    # summary
    # ----------------------------------------------------------------------- #
    @staticmethod
    def _summary_row(query_id, minimizer, timings):
        exec_vals = [float(r['exec_only_s']) for r in timings]
        oh_vals = [float(r['with_overhead_s']) for r in timings]
        by_iter_exec = {}
        by_iter_oh = {}
        for r in timings:
            by_iter_exec.setdefault(int(r['iteration']), []).append(float(r['exec_only_s']))
            by_iter_oh.setdefault(int(r['iteration']), []).append(float(r['with_overhead_s']))
        cum_exec = sum(p95(v) for v in by_iter_exec.values())
        cum_oh = sum(p95(v) for v in by_iter_oh.values())
        iters = sorted(set(int(r['iteration']) for r in timings))
        runs = sorted(set(int(r['run']) for r in timings))
        return {
            "query": query_id,
            "minimizer": minimizer,
            "runs": len(runs),
            "iterations": len(iters),
            "cum_p95_exec_s": round(cum_exec, 4),
            "cum_p95_overhead_s": round(cum_oh, 4),
            "overall_p95_exec_s": round(p95(exec_vals), 4) if exec_vals else "",
            "overall_p95_overhead_s": round(p95(oh_vals), 4) if oh_vals else "",
        }

    def _write_summary_csv(self, summary_rows, expt_name):
        filename = f"copy_minimizer_mq_summary_{self.repeats}rep_{self.runs}runs_{expt_name}.csv"
        path = CSV_DIR / filename
        fields = ["query", "minimizer", "runs", "iterations",
                  "cum_p95_exec_s", "cum_p95_overhead_s",
                  "overall_p95_exec_s", "overall_p95_overhead_s"]
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in summary_rows:
                writer.writerow(row)
        print(f"wrote {path}")
        return path

    def _plot_summary(self, summary_rows, query_ids, expt_name):
        if not summary_rows:
            return None
        minimizers = [m[0] for m in MINIMIZERS]
        q_index = {q: i for i, q in enumerate(query_ids)}
        # maps[minimizer][query] = row
        maps = {m: {} for m in minimizers}
        for row in summary_rows:
            maps[row["minimizer"]][row["query"]] = row

        metrics = [
            ("cum_p95_exec_s", "Cumulative p95 exec-only (s)", False),
            ("cum_p95_overhead_s", "Cumulative p95 with overhead (s)", False),
        ]
        fig, axes = plt.subplots(2, 1, figsize=(max(12, len(query_ids) * 1.1), 10), sharex=True)
        x = list(range(len(query_ids)))
        width = 0.25
        for ax, (key, ylabel, _) in zip(axes, metrics):
            for i, m in enumerate(minimizers):
                vals = []
                for q in query_ids:
                    row = maps[m].get(q)
                    vals.append(float(row[key]) if row and row.get(key) not in (None, "") else 0.0)
                positions = [xi + (i - 1) * width for xi in x]
                bars = ax.bar(positions, vals, width=width, label=m, color=MINIMIZER_COLORS[m])
                for b, v in zip(bars, vals):
                    if v > 0:
                        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}",
                                ha="center", va="bottom", fontsize=6, rotation=90)
            ax.set_ylabel(ylabel)
            ax.grid(axis="y", linestyle=":", alpha=0.5)
            ax.legend(fontsize=9)
            # use log scale if values span wide range
            all_vals = [float(maps[m].get(q, {}).get(key) or 0) for m in minimizers for q in query_ids]
            pos_vals = [v for v in all_vals if v > 0]
            if pos_vals and max(pos_vals) / max(min(pos_vals), 1e-9) > 50:
                ax.set_yscale("log")

        axes[-1].set_xticks(x)
        axes[-1].set_xticklabels(query_ids)
        axes[-1].set_xlabel("MQ query")
        fig.suptitle(f"MQ series summary - {expt_name}, {self.runs} cold-cache runs, p95 tail latency", fontsize=14)
        fig.tight_layout()
        filename = f"copy_minimizer_mq_summary_{self.repeats}rep_{self.runs}runs_{expt_name}.png"
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")
        return path

    # ----------------------------------------------------------------------- #
    # batch run
    # ----------------------------------------------------------------------- #
    def run_batch(self, query_ids, expt_names=None):
        expt_names = expt_names or ["expt1"]
        summary_rows = []
        for expt_name in expt_names:
            order = EXPERIMENTS[expt_name]
            expt_rows = []
            for qid in query_ids:
                self.configure_query(qid)
                try:
                    timings, costs, iterations = self._run_experiment(order, expt_name)
                    for mname, trecs in timings.items():
                        expt_rows.append(self._summary_row(qid, mname, trecs))
                    summary_rows.extend([r for r in expt_rows if r["query"] == qid])
                finally:
                    # clean up working schema between queries
                    try:
                        self._restore_normal_schema()
                    except Exception as e:
                        print(f"cleanup warning for {qid}: {e}")
                        try:
                            self.conn.conn.rollback()
                            self.prep.remove_footprint()
                            self.conn.conn.commit()
                        except Exception:
                            pass
            # write summary for this experiment over all queries run
            if expt_rows:
                self._write_summary_csv(expt_rows, expt_name)
                self._plot_summary(expt_rows, [q for q in query_ids], expt_name)
        return summary_rows

    def test_do(self):
        # Default batch: remaining MQ queries (excluding MQ18), expt1, 3 runs
        env_ids = os.environ.get("PRISM_MQ_IDS")
        if env_ids:
            query_ids = [q.strip() for q in env_ids.split(",") if q.strip()]
        else:
            query_ids = [q for q in MQ_SERIES_ORDER if q != "MQ18"]
        env_expts = os.environ.get("PRISM_MQ_EXPTS")
        expt_names = [e.strip() for e in env_expts.split(",") if e.strip()] if env_expts else ["expt1"]
        self.runs = int(os.environ.get("PRISM_MQ_RUNS", str(DEFAULT_RUNS)))
        self.run_batch(query_ids, expt_names)


if __name__ == "__main__":
    CopyBasedMinimizerExperiment.repeats = DEFAULT_REPEATS
    CopyBasedMinimizerExperiment.runs = int(os.environ.get("PRISM_MQ_RUNS", str(DEFAULT_RUNS)))
    unittest.main()
