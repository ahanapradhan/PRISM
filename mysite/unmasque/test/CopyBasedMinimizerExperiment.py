"""Lineitem / orders experiment: ViewMinimizer vs CopyBasedMinimizer on MQ18.

Both minimizers are run on the same core relations.  Per-iteration execution
times are parsed from ``mysite/unmasque.log`` (the ``Exe time:`` lines emitted
by ``Executable``), and per-iteration estimated costs come from EXPLAIN: the
copy minimizer explains the query on the materialized table, the view
minimizer explains a view wrapping the query.

Run with::

    python -m pytest mysite/unmasque/test/CopyBasedMinimizerExperiment.py -s

Two PNGs (timings and estimated cost) plus a CSV are written to
``mysite/unmasque/test/results/`` for each focus table.  The working schema is
dropped at the end of every test, leaving the user schema untouched.
"""
import re
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from mysite.unmasque.src.core.abstract.ExtractorBase import Base  # noqa: E402
from mysite.unmasque.src.core.copy_based_minimizer import CopyBasedMinimizer  # noqa: E402
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer  # noqa: E402
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # noqa: E402
from mysite.unmasque.src.util.Log import Log  # noqa: E402

CORE_TABLES = ["customer", "orders", "lineitem"]

MQ18 = """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%'
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;"""

ITER_START_RE = re.compile(r"MIN_ITER_START:\s*(\d+)")
ITER_END_RE = re.compile(r"MIN_ITER_END:\s*(\d+)")
EXE_TIME_RE = re.compile(r"Exe time:\s*([0-9]+(?:\.[0-9]+)?)")
COST_RE = re.compile(r"cost=[0-9.]+\.\.([0-9.]+)")

LOG_PATH = Path(__file__).parents[2] / "unmasque.log"
RESULTS_DIR = Path(__file__).parent / "results"


def parse_exe_times_from_log(text):
    """Return {iteration: [exe seconds, ...]} from one log segment."""
    timings = {}
    current = None
    for line in text.splitlines():
        start = ITER_START_RE.search(line)
        if start:
            current = int(start.group(1))
            timings.setdefault(current, [])
            continue
        if ITER_END_RE.search(line):
            current = None
            continue
        if current is not None:
            match = EXE_TIME_RE.search(line)
            if match:
                timings[current].append(float(match.group(1)))
    return timings


def parse_total_cost(rows):
    """Planner total cost is the upper bound of the first EXPLAIN line."""
    if not rows:
        return None
    match = COST_RE.search(str(rows[0][0]))
    return float(match.group(1)) if match else None


class CopyBasedMinimizerExperiment(unittest.TestCase):

    def setUp(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = ConnectionHelperFactory().createConnectionHelper()
        self.conn.connectUsingParams()
        self.config = self.conn.config
        self.prep = Base(self.conn, "ExperimentPrep")
        self.prep.set_all_relations(list(CORE_TABLES))
        self._saved_flags = {name: getattr(self.config, name) for name in
                             ("detect_union", "detect_oj", "detect_nep", "detect_or", "use_cs2")}
        for name in self._saved_flags:
            setattr(self.config, name, False)  # MQ18 flags
        self._public_sizes = self._sizes(self.config.user_schema)

    def tearDown(self):
        try:
            self._restore_normal_schema()
        finally:
            self.conn.closeConnection()
        for name, value in self._saved_flags.items():
            setattr(self.config, name, value)

    def _sizes(self, schema):
        return {table: int(self.conn.execute_sql_fetchone_0(
            self.conn.queries.get_row_count(f"{schema}.{table}")))
            for table in CORE_TABLES}

    def _restore_normal_schema(self):
        """Normal backup/restore end state: user schema intact, working schema gone."""
        if self.conn.conn is None:
            return
        self.conn.conn.rollback()
        self.assertEqual(self._sizes(self.config.user_schema), self._public_sizes,
                         "the user schema must not be modified by the experiment")
        self.prep.remove_footprint()  # DROP SCHEMA unmasque CASCADE
        self.conn.conn.commit()
        still_there = self.conn.execute_sql_fetchone_0(
            "select exists(select 1 from pg_namespace where nspname = 'unmasque');")
        self.assertFalse(still_there, "working schema must be deleted after the test")

    def _prepare_working_schema(self):
        """Fresh unmasque schema + Python-threaded copy of the core tables."""
        self.prep._create_working_schema()
        self.prep.take_backup(CORE_TABLES)
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

    def _cost_hook(self, mode):
        """Capture planner cost for one halving iteration."""
        queries = self.conn.queries
        logger = Log("PlanCost", self.config.log_level)
        costs = []

        def hook(iteration, tabname, query):
            view_name = None
            try:
                # The app wraps probes with SET search_path; EXPLAIN must do
                # the same or MQ18 would bind to the user schema instead.
                set_path = queries.set_search_path(self.config.schema)
                if mode == "view":
                    # ViewMinimizer: cost of the query by running EXPLAIN <view>.
                    view_name = f"{self.config.schema}.explain_query_view_{iteration}"
                    self.conn.execute_sql([set_path,
                                           queries.drop_view(view_name),
                                           queries.create_view_as(view_name, query)])
                    explain = queries.get_explain_query(queries.get_star(view_name))
                else:
                    # CopyMinimizer: cost of the query on the new materialized table.
                    explain = queries.get_explain_query(query)
                rows, _ = self.conn.execute_sql_fetchall(set_path + " " + explain)
                cost = parse_total_cost(rows)
            except Exception as exc:
                self.conn.conn.rollback()
                logger.error(f"EXPLAIN cost probe failed: {exc}")
                cost = None
            finally:
                if view_name is not None:
                    self.conn.execute_sql([queries.drop_view(view_name)])
            costs.append((iteration, cost))
            logger.debug(f"PLAN_COST: {iteration} {cost}")

        return hook, costs

    def _run_minimizer(self, cls, mode, all_sizes):
        minimizer = cls(self.conn, CORE_TABLES, all_sizes, False)
        hook, costs = self._cost_hook(mode)
        minimizer.on_iteration = hook
        log_start = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0
        self.assertTrue(minimizer.doJob(MQ18), f"{cls.__name__} failed")
        with LOG_PATH.open("rb") as log_file:
            log_file.seek(log_start)
            segment = log_file.read().decode("utf-8", errors="replace")
        return parse_exe_times_from_log(segment), costs, minimizer.iteration

    @staticmethod
    def _series(per_iteration):
        """{iteration: [values]} -> (iterations, one averaged value per iteration)."""
        items = []
        for iteration, values in per_iteration.items():
            usable = [value for value in values if value is not None]
            if usable:
                items.append((iteration, sum(usable) / len(usable)))
        items.sort()
        return ([i for i, _ in items], [v for _, v in items])

    def _write_csv(self, focus, view_timings, copy_timings, view_costs, copy_costs):
        path = RESULTS_DIR / f"copy_minimizer_{focus}.csv"
        with path.open("w", newline="") as handle:
            handle.write("focus,minimizer,iteration,exe_time_s,estimated_cost\n")
            for name, timings, costs in (("ViewMinimizer", view_timings, view_costs),
                                         ("CopyBasedMinimizer", copy_timings, copy_costs)):
                cost_map = dict(costs)
                for iteration in sorted(set(timings) | set(cost_map)):
                    times = timings.get(iteration, [])
                    exe = sum(times) / len(times) if times else ""
                    handle.write(f"{focus},{name},{iteration},{exe},{cost_map.get(iteration, '')}\n")
        print(f"wrote {path}")

    def _plot(self, focus, view_values, copy_values, ylabel, filename, title):
        fig, ax = plt.subplots(figsize=(11, 5))
        for label, (x, y) in (("ViewMinimizer", view_values),
                              ("CopyBasedMinimizer", copy_values)):
            if x:
                ax.plot(x, y, marker="o", linewidth=1.5, label=label)
        ax.set_xlabel("ctid-halving iteration")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title} ({focus}, MQ18)")
        ax.grid(linestyle=":", alpha=0.5)
        ax.legend()
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _run_experiment(self, focus):
        all_sizes = self._prepare_working_schema()
        self._assert_physical_order_changed(focus)

        view_timings, view_costs, view_iterations = self._run_minimizer(
            ViewMinimizer, "view", all_sizes)
        all_sizes = self._prepare_working_schema()
        copy_timings, copy_costs, copy_iterations = self._run_minimizer(
            CopyBasedMinimizer, "copy", all_sizes)

        print(f"{focus}: ViewMinimizer iterated {view_iterations} times, "
              f"CopyBasedMinimizer {copy_iterations} times")
        self._write_csv(focus, view_timings, copy_timings,
                        [(i, c) for i, c in view_costs if c is not None],
                        [(i, c) for i, c in copy_costs if c is not None])
        self._plot(focus, self._series(view_timings), self._series(copy_timings),
                   "Execution time (s)", f"copy_minimizer_{focus}_timings.png",
                   "Per-iteration execution time")
        view_cost_series = {i: [c] for i, c in view_costs if c is not None}
        copy_cost_series = {i: [c] for i, c in copy_costs if c is not None}
        self._plot(focus, self._series(view_cost_series), self._series(copy_cost_series),
                   "Planner estimated cost", f"copy_minimizer_{focus}_cost.png",
                   "Per-iteration estimated query cost")
        self.assertTrue(view_timings and copy_timings, "no Exe time lines found in the log")

    def test_lineitem(self):
        self._run_experiment("lineitem")

    def test_orders(self):
        self._run_experiment("orders")


if __name__ == "__main__":
    unittest.main()
