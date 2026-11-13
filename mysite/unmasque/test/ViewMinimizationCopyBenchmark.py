#!/usr/bin/env python3
"""Benchmark View Minimization timing for the native and Python copy paths.

The benchmark runs MQ18 six times:

* native threaded backup/restore + ``NullFreeExecutable``
* native threaded backup/restore + ``ZeroResultExecutable``
* native threaded backup/restore + ``Executable``
* Python serial backup/restore + the same three executables

Each case follows the production flow:

1. reset the working schema to an empty schema;
2. run ``Initiator``/``FromClause.doJob`` so the core relations are probed
   and backed up exactly once by ``SchemaSanitizer.take_backup``;
3. run ``ViewMinimizer`` for MQ18 with the chosen executable, recording the
   duration of every QH (``app.doJob``) call and the halving round in which it
   happened;
4. restore the minimized working tables with ``DbRestorer`` using the same
   copy mechanism.

After all six cases the raw per-call timings are written to CSV/JSON and a
single figure plots QH timing (Y) against view-minimization round (X) for all
six cases.

Run it as a normal test::

    python -m pytest mysite/unmasque/test/ViewMinimizationCopyBenchmark.py -s

or directly::

    python mysite/unmasque/test/ViewMinimizationCopyBenchmark.py

For a quick smoke test of one case::

    PRISM_VIEW_BENCH_CASES=native:Null_Free_Executable \
        python mysite/unmasque/test/ViewMinimizationCopyBenchmark.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

# Allow running this file directly from any directory.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from mysite.unmasque.src.core.db_restorer import DbRestorer  # noqa: E402
from mysite.unmasque.src.core.executables.ZeroResultExecutable import ZeroResultExecutable  # noqa: E402
from mysite.unmasque.src.core.executables.executable import Executable  # noqa: E402
from mysite.unmasque.src.core.executables.nullfree_executable import NullFreeExecutable  # noqa: E402
from mysite.unmasque.src.core.factory.ExecutableFactory import ExecutableFactory  # noqa: E402
from mysite.unmasque.src.core.from_clause import FromClause  # noqa: E402
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer  # noqa: E402
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # noqa: E402
from mysite.unmasque.src.util.native_copy import native_copy_available  # noqa: E402
from mysite.unmasque.src.util.workload_queries import create_workload  # noqa: E402

MQ18 = next(q.query for q in create_workload() if q.qid == "MQ18")

EXECUTABLES = (
    "Null_Free_Executable",
    "Zero_Result_Executable",
    "Executable",
)
MECHANISMS = ("native", "python")

RESULTS_DIR = Path(__file__).resolve().parent / "results"
PLOT_PATH = RESULTS_DIR / "view_minimization_copy_benchmark.png"
CSV_PATH = RESULTS_DIR / "view_minimization_copy_benchmark.csv"
JSON_PATH = RESULTS_DIR / "view_minimization_copy_benchmark.json"
PARTIAL_PATH = RESULTS_DIR / "view_minimization_copy_benchmark.partial.json"

# Keep only the extraction pipeline active.  The MQ18 benchmark is about the
# database minimizer, so every other feature is deliberately switched off.
DISABLED_FEATURES = {
    "detect_union": False,
    "detect_nep": False,
    "detect_or": False,
    "detect_oj": False,
    "use_cs2": False,
    "scale_down": False,
    "use_index": False,
}

CASE_COLORS = {
    ("native", "Null_Free_Executable"): "#1b9e77",
    ("native", "Zero_Result_Executable"): "#d95f02",
    ("native", "Executable"): "#7570b3",
    ("python", "Null_Free_Executable"): "#66c2a5",
    ("python", "Zero_Result_Executable"): "#fc8d62",
    ("python", "Executable"): "#8da0cb",
}


class QHCallRecorder:
    """Collect one timing sample for every executable callback."""

    def __init__(self):
        self.events = []
        self.enabled = False
        self.reset()

    def reset(self):
        self.events = []
        self.round = 0
        self.phase = "idle"
        self.table = None
        self.stage = None
        self._call_index = 0
        self.enabled = False

    def record(self, seconds):
        if not self.enabled:
            return
        self._call_index += 1
        self.events.append(
            {
                "call": self._call_index,
                "round": self.round,
                "phase": self.phase,
                "table": self.table,
                "stage": self.stage,
                "seconds": float(seconds),
            }
        )


def install_qh_timer(app, recorder):
    """Wrap ``app.doJob`` once, preserving the real executable type.

    ``Minimizer.create_view_execute_app_drop_view`` checks
    ``isinstance(self.app, NullFreeExecutable)``.  Keeping the original object
    and only replacing its bound ``doJob`` preserves that check.
    """
    if getattr(app, "_prism_qh_timer_installed", False):
        return

    original_do_job = app.doJob

    def timed_do_job(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original_do_job(*args, **kwargs)
        finally:
            recorder.record(time.perf_counter() - started)

    app.doJob = timed_do_job
    app._prism_qh_timer_installed = True


class TimedViewMinimizer(ViewMinimizer):
    """ViewMinimizer that labels every QH call with its halving round."""

    def __init__(
        self,
        connectionHelper,
        core_relations,
        all_sizes,
        sampling_status,
        app,
        recorder,
        expect_populated=True,
    ):
        super().__init__(
            connectionHelper,
            core_relations,
            all_sizes,
            sampling_status,
            expect_populated=expect_populated,
        )
        self.app = app
        self.recorder = recorder
        self._round_no = 0
        self.recorder.reset()
        self.recorder.enabled = True
        # QH calls inside the minimizer must see the working schema, not the
        # user schema used by the from-clause probes.
        self.app.data_schema = connectionHelper.config.schema

    def sanity_check(self, query, expect_populated=True):
        previous_phase = self.recorder.phase
        self.recorder.phase = "sanity"
        try:
            return super().sanity_check(query, expect_populated=expect_populated)
        finally:
            self.recorder.phase = previous_phase

    def create_view_execute_app_drop_view(self, *args, **kwargs):
        self._round_no += 1
        self.recorder.round = self._round_no
        previous_phase = self.recorder.phase
        self.recorder.phase = "halving"
        try:
            return super().create_view_execute_app_drop_view(*args, **kwargs)
        finally:
            self.recorder.phase = previous_phase
            events = [
                event
                for event in self.recorder.events
                if event["round"] == self._round_no
                and event["phase"] == "halving"
            ]
            if events:
                total = sum(event["seconds"] for event in events)
                print(
                    f"  round {self._round_no}: {len(events)} QH call(s), "
                    f"{total:.3f}s "
                    f"(table={self.recorder.table}, stage={self.recorder.stage})",
                    flush=True,
                )

    def do_interPage_viewBased_binary_halving(
        self, core_sizes, query, tabname, rctid, dirty_tab
    ):
        self.recorder.table = tabname
        self.recorder.stage = "inter-page"
        return super().do_interPage_viewBased_binary_halving(
            core_sizes, query, tabname, rctid, dirty_tab
        )

    def do_intraPage_copyBased_binary_halving(
        self, core_sizes, query, tabname, dirty_tab
    ):
        self.recorder.table = tabname
        self.recorder.stage = "intra-page"
        return super().do_intraPage_copyBased_binary_halving(
            core_sizes, query, tabname, dirty_tab
        )


@contextmanager
def spy_native_calls():
    """Record successful/failed native helper invocations."""
    import mysite.unmasque.src.core.db_restorer as restorer_module
    import mysite.unmasque.src.pipeline.abstract.SchemaSanitizer as sanitizer_module

    calls = []

    def make_spy(original, component):
        def spy(*args, **kwargs):
            started = time.perf_counter()
            try:
                result = original(*args, **kwargs)
            except Exception as error:
                calls.append(
                    {
                        "component": component,
                        "mode": kwargs.get("mode", "copy"),
                        "ok": False,
                        "seconds": time.perf_counter() - started,
                        "error": str(error),
                    }
                )
                raise
            calls.append(
                {
                    "component": component,
                    "mode": kwargs.get("mode", "copy"),
                    "ok": True,
                    "seconds": time.perf_counter() - started,
                    "error": "",
                }
            )
            return result

        return spy

    original_sanitizer = sanitizer_module.run_native_copy
    original_restorer = restorer_module.run_native_copy
    sanitizer_module.run_native_copy = make_spy(original_sanitizer, "SchemaSanitizer")
    restorer_module.run_native_copy = make_spy(original_restorer, "DbRestorer")
    try:
        yield calls
    finally:
        sanitizer_module.run_native_copy = original_sanitizer
        restorer_module.run_native_copy = original_restorer


def configure(conn):
    for name, value in DISABLED_FEATURES.items():
        setattr(conn.config, name, value)
    conn.config.log_level = "INFO"


def open_connection(conn):
    if conn.conn is None:
        conn.connectUsingParams()


def rollback_quietly(conn):
    try:
        conn.rollback_transaction()
    except Exception:
        pass


def reset_working_schema(conn):
    """Create an empty, committed working schema before each case."""
    open_connection(conn)
    rollback_quietly(conn)
    schema = conn.config.schema
    conn.execute_sql(
        [f"Drop Schema if exists {schema} cascade;", f"Create Schema {schema};"]
    )
    conn.commit_transaction()


def drop_working_schema(conn):
    if conn.conn is None:
        return
    rollback_quietly(conn)
    conn.execute_sql(
        [f"Drop Schema if exists {conn.config.schema} cascade;"]
    )
    conn.commit_transaction()


def make_executables(conn, recorder):
    """Create one real instance of each executable, in singleton-safe order.

    ``Executable`` and its subclasses inherit ``Base``'s singleton in a way
    that lets ``NullFreeExecutable`` fall back to an already-created plain
    ``Executable``.  Create ``NullFreeExecutable`` first and reuse the three
    instances for the whole benchmark.
    """
    nullfree = NullFreeExecutable(conn)
    zero = ZeroResultExecutable(conn)
    plain = Executable(conn)

    apps = {
        "Null_Free_Executable": nullfree,
        "Zero_Result_Executable": zero,
        "Executable": plain,
    }
    for app in apps.values():
        install_qh_timer(app, recorder)

    # FromClause and other AppExtractorBase users should keep using the
    # zero-result executable for probing.
    ExecutableFactory().app = zero
    return apps


def restore_and_verify(conn, core_relations, sizes):
    restorer = DbRestorer(conn, core_relations)
    restorer.set_all_sizes(sizes)
    started = time.perf_counter()
    check = restorer.doJob(None)
    elapsed = time.perf_counter() - started
    if not check or not restorer.done:
        raise RuntimeError(f"Restore failed for {core_relations}")
    conn.commit_transaction()

    restored = {}
    for table in core_relations:
        count = conn.execute_sql_fetchone_0(
            f"select count(*) from {conn.config.schema}.{table}"
        )
        restored[table] = int(count) if count is not None else 0
    mismatched = {
        table: (sizes[table], restored[table])
        for table in core_relations
        if restored[table] != sizes[table]
    }
    if mismatched:
        raise RuntimeError(f"Restore row-count mismatch (expected, actual): {mismatched}")
    return elapsed, restored


def run_case(conn, mechanism, executable_name, app, recorder):
    label = f"{mechanism} / {executable_name}"
    print(f"\n=== {label}: preparing working schema and backup ===", flush=True)

    os.environ["PRISM_NATIVE_COPY"] = "off" if mechanism == "python" else "on"
    reset_working_schema(conn)

    fc = FromClause(conn)
    # Initiator/FromClause/executables are singletons: force a fresh init and
    # make sure probing runs against the user schema, not the working schema
    # left behind by the previous case's minimizer.
    fc.init.done = False
    fc.init.backup_done = False
    fc.reset_data_schema()

    case_started = time.perf_counter()
    native_calls = []
    with spy_native_calls() as calls:
        native_calls = calls
        prepare_started = time.perf_counter()
        check = fc.doJob(MQ18)
        prepare_seconds = time.perf_counter() - prepare_started
        if not check or not fc.done or not fc.core_relations:
            raise RuntimeError(f"{label}: from-clause extraction/backup failed")

        core_relations = list(fc.core_relations)
        if not core_relations:
            raise RuntimeError(f"{label}: no core relations found")
        sizes = {
            table: int(fc.init.all_sizes[table]) for table in core_relations
        }
        print(
            f"{label}: core relations={core_relations}, sizes={sizes}, "
            f"init+probe+backup={prepare_seconds:.2f}s",
            flush=True,
        )

        print(f"=== {label}: running ViewMinimizer ===", flush=True)
        vm_started = time.perf_counter()
        vm = TimedViewMinimizer(
            conn,
            core_relations,
            sizes,
            False,
            app,
            recorder,
            expect_populated=True,
        )
        vm_result = vm.doJob(MQ18)
        vm_seconds = time.perf_counter() - vm_started
        recorder.enabled = False
        if vm_result is not True or not vm.done:
            raise RuntimeError(
                f"{label}: ViewMinimizer failed with result {vm_result!r}"
            )

        halving_calls = sum(
            1 for event in recorder.events if event["phase"] == "halving"
        )
        print(
            f"{label}: ViewMinimizer done in {vm_seconds:.2f}s, "
            f"{recorder.round} halving rounds, {halving_calls} QH calls",
            flush=True,
        )

        print(f"=== {label}: restoring minimized tables ===", flush=True)
        restore_seconds, restored_counts = restore_and_verify(
            conn, core_relations, sizes
        )
        print(
            f"{label}: restore done in {restore_seconds:.2f}s, "
            f"counts={restored_counts}",
            flush=True,
        )

    case_seconds = time.perf_counter() - case_started

    if mechanism == "native":
        if not native_copy_available(conn.config):
            raise RuntimeError(
                f"{label}: native copy helper is not available"
            )
        backup_calls = [
            call
            for call in native_calls
            if call["ok"]
            and call["component"] == "SchemaSanitizer"
            and call["mode"] in ("copy", "backup")
        ]
        restore_calls = [
            call
            for call in native_calls
            if call["ok"]
            and call["component"] == "DbRestorer"
            and call["mode"] == "restore"
        ]
        if not backup_calls or not restore_calls:
            raise RuntimeError(
                f"{label}: expected native backup and restore calls, got {native_calls}"
            )
    elif any(call["ok"] for call in native_calls):
        raise RuntimeError(
            f"{label}: Python case unexpectedly used the native helper: {native_calls}"
        )

    return {
        "label": label,
        "mechanism": mechanism,
        "executable": executable_name,
        "core_relations": core_relations,
        "sizes": sizes,
        "prepare_seconds": prepare_seconds,
        "view_minimization_seconds": vm_seconds,
        "restore_seconds": restore_seconds,
        "case_seconds": case_seconds,
        "rounds": recorder.round,
        "native_calls": native_calls,
        "events": list(recorder.events),
        "minimized_instance": {
            table: [list(row) for row in rows]
            for table, rows in vm.global_min_instance_dict.items()
        },
    }


def selected_cases():
    requested = os.environ.get("PRISM_VIEW_BENCH_CASES", "").strip()
    all_cases = [
        (mechanism, executable)
        for mechanism in MECHANISMS
        for executable in EXECUTABLES
    ]
    if not requested:
        return all_cases

    wanted = {item.strip() for item in requested.split(",") if item.strip()}
    filtered = []
    for mechanism, executable in all_cases:
        key = f"{mechanism}:{executable}"
        if key in wanted or f"{mechanism} / {executable}" in wanted:
            filtered.append((mechanism, executable))
    if not filtered:
        raise ValueError(
            f"PRISM_VIEW_BENCH_CASES={requested!r} did not match any case; "
            "use values like native:Null_Free_Executable"
        )
    return filtered


def write_csv(results):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case",
                "mechanism",
                "executable",
                "call",
                "round",
                "phase",
                "table",
                "stage",
                "seconds",
            ]
        )
        for result in results:
            for event in result["events"]:
                writer.writerow(
                    [
                        result["label"],
                        result["mechanism"],
                        result["executable"],
                        event["call"],
                        event["round"],
                        event["phase"],
                        event["table"],
                        event["stage"],
                        f"{event['seconds']:.9f}",
                    ]
                )


def write_json(results):
    payload = []
    for result in results:
        payload.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"events", "minimized_instance"}
            }
        )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2))


def save_partial(results):
    """Persist completed cases so a long run can be resumed/plotted early."""
    payload = [
        {
            key: value
            for key, value in result.items()
            if key not in {"minimized_instance"}
        }
        for result in results
    ]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PARTIAL_PATH.write_text(json.dumps(payload, indent=2))


def load_partial():
    if not PARTIAL_PATH.is_file():
        return []
    try:
        return json.loads(PARTIAL_PATH.read_text())
    except (OSError, ValueError):
        return []


def plot_results(results):
    """Plot per-QH-call timing and per-round total timing for all cases."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    fig, (ax_calls, ax_rounds) = plt.subplots(
        2, 1, figsize=(14, 10), sharex=True
    )

    for result in results:
        color = CASE_COLORS.get(
            (result["mechanism"], result["executable"]), None
        )
        halving = [
            event for event in result["events"] if event["phase"] == "halving"
        ]
        if not halving:
            continue

        xs = [event["round"] for event in halving]
        ys = [event["seconds"] for event in halving]
        ax_calls.plot(
            xs,
            ys,
            marker="o",
            markersize=3.2,
            linewidth=1.25,
            alpha=0.9,
            color=color,
            label=result["label"],
        )

        round_totals = {}
        for event in halving:
            round_totals[event["round"]] = (
                round_totals.get(event["round"], 0.0) + event["seconds"]
            )
        rounds = sorted(round_totals)
        ax_rounds.plot(
            rounds,
            [round_totals[round_no] for round_no in rounds],
            marker="o",
            markersize=3.2,
            linewidth=1.25,
            alpha=0.9,
            color=color,
            label=result["label"],
        )

    ax_calls.set_ylabel("QH call time (s)")
    ax_calls.set_title(
        "MQ18 View Minimization: per-QH-call timing by halving round"
    )
    ax_calls.grid(True, alpha=0.25)
    ax_calls.legend(fontsize=8, ncol=2, loc="best")

    ax_rounds.set_xlabel("View minimization round")
    ax_rounds.set_ylabel("Total QH time in round (s)")
    ax_rounds.set_title(
        "MQ18 View Minimization: total QH time per halving round "
        "(NullFreeExecutable can make two calls per round)"
    )
    ax_rounds.grid(True, alpha=0.25)
    ax_rounds.legend(fontsize=8, ncol=2, loc="best")

    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot written to {PLOT_PATH}", flush=True)


def run_benchmark():
    configure_conn = ConnectionHelperFactory().createConnectionHelper()
    configure(configure_conn)
    selected = selected_cases()
    if "native" in {mechanism for mechanism, _ in selected}:
        if not native_copy_available(configure_conn.config):
            raise RuntimeError(
                "Native copy helper is unavailable. Build "
                "mysite/unmasque/native/pgcopy or run only the python cases "
                "with PRISM_VIEW_BENCH_CASES=python:Null_Free_Executable,..."
            )

    resume = os.environ.get("PRISM_VIEW_BENCH_RESUME", "").strip().lower() not in (
        "",
        "0",
        "off",
        "no",
        "false",
    )
    selected_labels = {f"{mechanism} / {executable}" for mechanism, executable in selected}
    results = (
        [
            result
            for result in load_partial()
            if result.get("label") in selected_labels
        ]
        if resume
        else []
    )
    completed = {result["label"] for result in results}
    if completed:
        print(
            f"Resuming: {sorted(completed)} already in {PARTIAL_PATH.name}",
            flush=True,
        )

    recorder = QHCallRecorder()
    apps = make_executables(configure_conn, recorder)

    try:
        for mechanism, executable in selected:
            label = f"{mechanism} / {executable}"
            if label in completed:
                print(f"=== {label}: already recorded, skipping ===", flush=True)
                continue
            result = run_case(
                configure_conn,
                mechanism,
                executable,
                apps[executable],
                recorder,
            )
            results.append(result)
            completed.add(label)
            save_partial(results)
    finally:
        try:
            drop_working_schema(configure_conn)
        finally:
            configure_conn.closeConnection()

    order = {
        f"{mechanism} / {executable}": index
        for index, (mechanism, executable) in enumerate(selected)
    }
    results.sort(key=lambda result: order.get(result["label"], 10_000))

    write_csv(results)
    write_json(results)
    plot_results(results)

    print("\n=== Summary ===", flush=True)
    for result in results:
        print(
            f"{result['label']}: prepare={result['prepare_seconds']:.2f}s "
            f"VM={result['view_minimization_seconds']:.2f}s "
            f"rounds={result['rounds']} "
            f"restore={result['restore_seconds']:.2f}s "
            f"total={result['case_seconds']:.2f}s"
        )
    return results


class ViewMinimizationCopyBenchmarkTest(unittest.TestCase):
    def test_view_minimization_copy_benchmark(self):
        results = run_benchmark()
        self.assertEqual(
            len(results), len(selected_cases()), "not every selected case ran"
        )
        for result in results:
            halving = [
                event
                for event in result["events"]
                if event["phase"] == "halving"
            ]
            self.assertTrue(
                halving, f"{result['label']} recorded no halving QH calls"
            )
            self.assertTrue(
                PLOT_PATH.is_file(), f"missing plot {PLOT_PATH}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
