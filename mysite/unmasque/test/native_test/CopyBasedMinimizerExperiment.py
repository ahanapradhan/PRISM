"""Lineitem / orders experiment: ViewMinimizer vs CopyBasedMinimizer on MQ18.

Both minimizers are run on the same core relations.  Inside the minimizers the
first probe of every ctid-halving iteration is executed `repeats` (default 5) times; each
run is timed in three parts (candidate creation / materialization, ANALYZE,
query execution, candidate drop).  Two views of the time are reported:

* ``with_overhead_s`` = create + analyze + exec + drop
* ``exec_only_s``     = query execution only

Estimated costs come from ``EXPLAIN (FORMAT JSON)`` (the copy minimizer explains
the query on the materialized table, the view minimizer explains a view wrapping
the query).  Three numbers are kept per iteration:

* ``total_cost``  - cost of the whole query plan *below* the LIMIT node
                    (the LIMIT node scales its child's cost, hiding input size)
* ``scan_cost``   - cost of the scan node on the table being halved
* ``scan_rows``   - planner row estimate of that scan (plus its node type)

Run with::

    python -m pytest mysite/unmasque/test/CopyBasedMinimizerExperiment.py -s

PNGs and CSVs are written to ``mysite/unmasque/test/results/``.  The working
schema is dropped at the end of every test, leaving the user schema untouched.
"""
import csv
import json
import statistics
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from mysite.unmasque.src.core.abstract.ExtractorBase import Base  # noqa: E402
from .copy_based_minimizer import CopyBasedMinimizer  # noqa: E402
from .view_minimizer import ViewMinimizer  # noqa: E402
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # noqa: E402
from mysite.unmasque.src.util.Log import Log  # noqa: E402

CORE_TABLES = ["customer", "orders", "lineitem"]
DEFAULT_REPEATS = 10

MQ18 = """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%'
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;"""

RESULTS_DIR = Path(__file__).parent / "results"
READING_COLOR = "tab:blue"
AVERAGE_COLOR = "tab:red"
MINIMIZER_COLORS = {"ViewMinimizer": "tab:blue", "CopyBasedMinimizer": "tab:orange"}
CUMULATIVE_COLOR = "tab:green"

TIMING_FIELDS = ["iteration", "table", "rep", "create_s", "analyze_s", "exec_s",
                 "drop_s", "with_overhead_s", "exec_only_s"]
COST_FIELDS = ["iteration", "table", "total_cost", "limit_cost",
               "scan_node", "scan_cost", "scan_rows"]


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
    # Runs per halving iteration. Set from __main__ (see bottom of file);
    # falls back to DEFAULT_REPEATS when run through pytest.
    repeats = DEFAULT_REPEATS


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

    # ----------------------------------------------------------------------- #
    # cost capture
    # ----------------------------------------------------------------------- #
    def _cost_hook(self, mode, minimizer):
        """Capture planner costs once per halving iteration (called by the minimizer)."""
        queries = self.conn.queries
        logger = Log("PlanCost", self.config.log_level)
        costs = []

        def hook(iteration, tabname, query):
            # `tabname` is the candidate's name.  In view mode the plan shows
            # the underlying dirty/restore table instead, so match all names.
            names = {tabname,
                     minimizer._get_dirty_name(tabname),
                     queries.get_restore_name(tabname)}
            view_name = None
            summary = dict.fromkeys(COST_FIELDS[2:])
            try:
                # The app wraps probes with SET search_path; EXPLAIN must do
                # the same or MQ18 would bind to the user schema instead.
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

    def _run_minimizer(self, cls, mode, all_sizes):
        minimizer = cls(self.conn, CORE_TABLES, all_sizes, False)
        minimizer.repeats = self.repeats
        hook, costs = self._cost_hook(mode, minimizer)
        minimizer.on_iteration = hook
        self.assertTrue(minimizer.doJob(MQ18), f"{cls.__name__} failed")
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
    def _cumulative(grouped):
        """Running total of the per-iteration average: (iterations, cumulative seconds)."""
        iterations = sorted(grouped)
        total, running = 0.0, []
        for i in iterations:
            total += statistics.fmean(grouped[i])
            running.append(total)
        return iterations, running

    def _write_csv(self, filename, fields, per_minimizer):
        path = RESULTS_DIR / filename
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["minimizer"] + fields)
            for name, records in per_minimizer.items():
                for record in records:
                    writer.writerow([name] + [record.get(f, "") for f in fields])
        print(f"wrote {path}")

    def _plot_readings(self, timings, key, ylabel, title, filename):
        """One panel per minimizer: every individual run (blue) + the per-iteration mean (red)."""
        fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
        for ax, (name, records) in zip(axes, timings.items()):
            grouped = self._group(records, key)
            iterations = sorted(grouped)
            ax.scatter([i for i in iterations for _ in grouped[i]],
                       [v for i in iterations for v in grouped[i]],
                       s=18, alpha=0.55, color=READING_COLOR, label=f"individual runs (n={self.repeats})")
            ax.plot(iterations, [statistics.fmean(grouped[i]) for i in iterations],
                    marker="o", linewidth=2, color=AVERAGE_COLOR, label=f"average of {self.repeats} runs")
            ax2 = ax.twinx()
            cum_x, cum_y = self._cumulative(grouped)
            ax2.plot(cum_x, cum_y, linestyle="--", linewidth=2, color=CUMULATIVE_COLOR,
                     label="cumulative time (right axis)")
            ax2.set_ylabel("Cumulative time (s)")
            ax.set_title(name)
            ax.set_xlabel("ctid-halving iteration")
            ax.grid(linestyle=":", alpha=0.5)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, loc="upper left")
        axes[0].set_ylabel(ylabel)
        fig.suptitle(f"{title} (MQ18)")
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _plot_average_comparison(self, timings, filename):
        """Averages of both minimizers on the same axes; left: with overhead, right: exec only."""
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        for ax, (key, title) in zip(axes, (("with_overhead_s", "Including create / analyze / drop"),
                                           ("exec_only_s", "Query execution only"))):
            ax2 = ax.twinx()
            ax2.set_ylabel("Cumulative time (s)")
            for name, records in timings.items():
                grouped = self._group(records, key)
                iterations = sorted(grouped)
                ax.plot(iterations, [statistics.fmean(grouped[i]) for i in iterations],
                        marker="o", linewidth=1.5, color=MINIMIZER_COLORS[name], label=name)
                cum_x, cum_y = self._cumulative(grouped)
                ax2.plot(cum_x, cum_y, linestyle="--", linewidth=1.5,
                         color=MINIMIZER_COLORS[name], label=f"{name} cumulative (right axis)")
            ax.set_title(title)
            ax.set_xlabel("ctid-halving iteration")
            ax.set_ylabel(f"Average time over {self.repeats} runs (s)")
            ax.grid(linestyle=":", alpha=0.5)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, loc="upper left")
        fig.suptitle("Per-iteration average time (MQ18)")
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _plot_costs(self, costs, key, ylabel, title, filename):
        # Cost falls geometrically while halving, so a log axis is needed to
        # see it; on a linear axis everything after the first few iterations
        # collapses onto the floor and looks like a horizontal line.
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for name, entries in costs.items():
            points = sorted((c["iteration"], c[key]) for c in entries if c[key] is not None)
            if points:
                ax.plot([p[0] for p in points], [p[1] for p in points], marker="o",
                        linewidth=1.5, color=MINIMIZER_COLORS[name], label=name)
        ax.set_yscale("log")
        ax.set_xlabel("ctid-halving iteration")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{title} (MQ18)", fontsize=10)
        ax.grid(linestyle=":", alpha=0.5, which="both")
        ax.legend()
        fig.tight_layout()
        path = RESULTS_DIR / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    def _tag(self, filename):
        """copy_minimizer_cost_scan.png -> copy_minimizer_cost_scan_<repeats>.png"""
        path = Path(filename)
        return f"{path.stem}_{self.repeats}{path.suffix}"

    def _metric_label(self, filename):
        """copy_minimizer_cost_scan_10.png -> cost_scan (the metric named by the file)."""
        stem = Path(filename).stem
        suffix = f"_{self.repeats}"
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
        prefix = "copy_minimizer_"
        return stem[len(prefix):] if stem.startswith(prefix) else stem

    def _combine_plots(self, rows, out_name):
        """Merge saved PNGs into one image.

        `rows` is a list of rows; each row is a list of filenames placed side by
        side.  Every image is titled with the metric name taken from its file name.
        """
        import matplotlib.image as mpimg
        loaded = [[(name, mpimg.imread(RESULTS_DIR / name)) for name in row] for row in rows]
        # Row height (in units of figure width): tallest image in the row, scaled by its width share.
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
        fig.suptitle(f"MQ18 - {self.repeats} runs per halving iteration", fontsize=14)
        path = RESULTS_DIR / out_name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")

    # ----------------------------------------------------------------------- #
    def _run_experiment(self):
        all_sizes = self._prepare_working_schema()
        for table in all_sizes.keys():
            self._assert_physical_order_changed(table)

        view_timings, view_costs, view_iterations = self._run_minimizer(
            ViewMinimizer, "view", all_sizes)
        all_sizes = self._prepare_working_schema()
        copy_timings, copy_costs, copy_iterations = self._run_minimizer(
            CopyBasedMinimizer, "copy", all_sizes)

        print(f"ViewMinimizer iterated {view_iterations} times, "
              f"CopyBasedMinimizer {copy_iterations} times")

        timings = {"ViewMinimizer": view_timings, "CopyBasedMinimizer": copy_timings}
        costs = {"ViewMinimizer": view_costs, "CopyBasedMinimizer": copy_costs}
        self._write_csv(self._tag("copy_minimizer_timings.csv"), TIMING_FIELDS, timings)
        self._write_csv(self._tag("copy_minimizer_costs.csv"), COST_FIELDS, costs)

        for name, entries in costs.items():  # quick console diagnostic
            first = next((c for c in entries if c["scan_cost"] is not None), None)
            last = next((c for c in reversed(entries) if c["scan_cost"] is not None), None)
            if first and last:
                print(f"{name}: scan node {first['scan_node']} -> {last['scan_node']}, "
                      f"scan cost {first['scan_cost']:.1f} -> {last['scan_cost']:.1f}, "
                      f"scan rows {first['scan_rows']} -> {last['scan_rows']}, "
                      f"total cost {first['total_cost']:.1f} -> {last['total_cost']:.1f}")

        plot_files = [self._tag("copy_minimizer_timings_with_overhead.png"),
                      self._tag("copy_minimizer_timings_exec_only.png"),
                      self._tag("copy_minimizer_timings_avg_compare.png"),
                      self._tag("copy_minimizer_cost_total.png"),
                      self._tag("copy_minimizer_cost_scan.png")]
        self._plot_readings(timings, "with_overhead_s", "Time (s)",
                            "Per-iteration time INCLUDING create/materialize/analyze/drop",
                            plot_files[0])
        self._plot_readings(timings, "exec_only_s", "Time (s)",
                            "Per-iteration time, query execution only",
                            plot_files[1])
        self._plot_average_comparison(timings, plot_files[2])
        self._plot_costs(costs, "total_cost", "Planner total cost (below LIMIT)",
                         "Per-iteration estimated cost of the whole query",
                         plot_files[3])
        self._plot_costs(costs, "scan_cost", "Planner cost of scan on halved table",
                         "Per-iteration estimated cost of scanning the halved table",
                         plot_files[4])
        self._combine_plots([[plot_files[0]],                  # one plot per row ...
                             [plot_files[1]],
                             [plot_files[2]],
                             [plot_files[3], plot_files[4]]],  # ... cost plots side by side
                            self._tag("copy_minimizer_all_plots.png"))
        for name in plot_files:  # keep only the merged image
            (RESULTS_DIR / name).unlink(missing_ok=True)
        self.assertTrue(view_timings and copy_timings, "no timing records collected")

    def test_do(self):
        self._run_experiment()


if __name__ == "__main__":
    CopyBasedMinimizerExperiment.repeats = 10
    unittest.main()