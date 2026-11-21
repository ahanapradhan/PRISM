#!/usr/bin/env python3
"""Compare ``PKView_Minimizer`` against the normal ``ViewMinimizer`` on MQ18.

Two full ``UnionPipeLine`` runs of MQ18 (union ON, outer-join ON, NEP/OR/CS2
off) are executed from the working schema:

* ``view`` -- the production ctid-based ``ViewMinimizer``;
* ``pk``   -- ``PKView_Minimizer``, which halves tables by primary-key range
  mid value (rename + temporary views + final CTAS only; the original table is
  never modified, no stats update, no extra index).

Every run follows the production flow, so the backup before extraction and the
restores inside the pipeline automatically use the native ``pgcopy`` helper
when it can be executed on this machine (``native`` mechanism), otherwise the
Python copy path (``python`` mechanism). The actually used mechanism is
recorded per case, together with wall time, the pipeline time profile, the
minimizer's elapsed time and app calls, and per-table halving rounds.

Output goes to ``test/results/pk_view_minimizer_mq18_comparison.{json,csv}``.

Run it as::

    python mysite/unmasque/test/PKViewMinimizerMq18Comparison.py

or restrict the cases::

    PRISM_PKVM_BENCH_CASES=view,pk python mysite/unmasque/test/PKViewMinimizerMq18Comparison.py
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

from mysite.unmasque.src.core.executables.nullfree_executable import NullFreeExecutable  # noqa: E402,F401 (keeps NullFree exe importable before the factory probes)
from mysite.unmasque.src.core.factory.ExecutableFactory import ExecutableFactory  # noqa: E402
from mysite.unmasque.src.core.from_clause import FromClause  # noqa: E402
from mysite.unmasque.src.core.pk_view_minimizer import PKView_Minimizer  # noqa: E402
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer  # noqa: E402
from mysite.unmasque.src.pipeline.UnionPipeLine import UnionPipeLine  # noqa: E402
from mysite.unmasque.src.pipeline.fragments import DisjunctionPipeLine  # noqa: E402
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # noqa: E402
from mysite.unmasque.src.util.native_copy import native_copy_available  # noqa: E402
from mysite.unmasque.src.util.workload_queries import create_workload  # noqa: E402

MQ18 = next(q.query for q in create_workload() if q.qid == "MQ18")

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JSON_PATH = RESULTS_DIR / "pk_view_minimizer_mq18_comparison.json"
CSV_PATH = RESULTS_DIR / "pk_view_minimizer_mq18_comparison.csv"

CASES = ("view", "pk")
CASE_LABELS = {
    "view": "ViewMinimizer (ctid halving)",
    "pk": "PKView_Minimizer (PK range halving)",
}

# MQ18 benchmark is about the database minimizer: union and outer-join
# detection stay on (per the comparison requirements), everything else off.
FEATURE_FLAGS = {
    "detect_union": True,
    "detect_oj": True,
    "detect_nep": False,
    "detect_or": False,
    "use_cs2": False,
    "scale_down": False,
    "use_index": False,
}

PROFILE_TIME_FIELDS = (
    "t_init",
    "t_from_clause",
    "t_union",
    "t_db_restore",
    "t_sampling",
    "t_view_min",
    "t_where_clause",
    "t_projection",
    "t_groupby",
    "t_aggregate",
    "t_orderby",
    "t_limit",
    "t_outer_join",
    "t_nep",
    "t_result_comp",
    "t_total",
)
PROFILE_APP_FIELDS = (
    "app_init",
    "app_from_clause",
    "app_union",
    "app_db_restore",
    "app_sampling",
    "app_view_min",
    "app_where_clause",
    "app_projection",
    "app_groupby",
    "app_aggregate",
    "app_orderby",
    "app_limit",
    "app_outer_join",
    "app_nep",
    "app_result_comp",
    "app_total",
)


def configure(conn):
    for name, value in FEATURE_FLAGS.items():
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
    conn.execute_sql([f"Drop Schema if exists {conn.config.schema} cascade;"])
    conn.commit_transaction()


@contextmanager
def spy_native_calls():
    """Record native helper invocations so the used mechanism is provable."""
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


class CountingViewMinimizer(ViewMinimizer):
    """ViewMinimizer that counts its halving rounds (ctid world)."""

    def __init__(self, connectionHelper, core_relations, all_sizes,
                 sampling_status, expect_populated=True):
        super().__init__(connectionHelper, core_relations, all_sizes,
                         sampling_status, expect_populated=expect_populated)
        self.halving_rounds = {"_total": 0}

    def create_view_execute_app_drop_view(self, *args, **kwargs):
        self.halving_rounds["_total"] += 1
        return super().create_view_execute_app_drop_view(*args, **kwargs)


@contextmanager
def patched_view_minimizer(kind, instances):
    """Route ``DisjunctionPipeLine``'s minimizer construction to the case class."""
    import mysite.unmasque.src.pipeline.fragments.DisjunctionPipeLine as dpl

    target = PKView_Minimizer if kind == "pk" else CountingViewMinimizer

    def factory(connectionHelper, core_relations, all_sizes, sampling_status,
                expect_populated=True):
        # ``Base`` memoizes one instance per concrete class: clear it so each
        # case gets a freshly initialized minimizer of the right subclass.
        target._instance = None
        kwargs = {"expect_populated": expect_populated}
        if kind == "pk":
            # The working tables carry no declared PK constraint on this
            # database, so hand the minimizer the pkfk-derived PK map the
            # pipeline's Initiator built (table -> "col1,col2").
            pk_dict = getattr(fc.init, "global_pk_dict", None)
            kwargs["pk_dict"] = pk_dict
        vm = target(connectionHelper, core_relations, all_sizes, sampling_status,
                    **kwargs)
        instances.append(vm)
        return vm

    original = dpl.ViewMinimizer
    dpl.ViewMinimizer = factory
    try:
        yield
    finally:
        dpl.ViewMinimizer = original


def serialize_pk_intervals(pk_intervals):
    out = {}
    for table, interval in (pk_intervals or {}).items():
        lo, hi = interval
        out[table] = [str(lo), str(hi)]
    return out


def run_case(conn, kind):
    label = CASE_LABELS[kind]
    print(f"\n=== {label}: preparing working schema and backup ===", flush=True)

    configure(conn)
    reset_working_schema(conn)

    # Initiator/FromClause are singletons: force a fresh init so the base
    # tables are backed up again (native copy when available).
    fc = FromClause(conn)
    fc.init.done = False
    fc.init.backup_done = False
    fc.reset_data_schema()

    instances = []
    case_started = time.perf_counter()
    with spy_native_calls() as native_calls, patched_view_minimizer(kind, instances):
        pipe = UnionPipeLine(conn)
        qe = []
        pipe.doJob(MQ18, qe)
    case_seconds = time.perf_counter() - case_started

    if qe and not qe[0]:
        qe[0] = pipe.error
    extracted = qe[0] if qe else pipe.error
    vm = instances[-1] if instances else None

    mechanism = "native" if native_copy_available(conn.config) else "python"
    native_ok = [call for call in native_calls if call["ok"]]
    if native_ok:
        mechanism = "native"
    elif native_copy_available(conn.config):
        # helper is runnable but nothing called it (unexpected for MQ18)
        mechanism = "native (unused)"

    profile = pipe.time_profile
    result = {
        "case": kind,
        "label": label,
        "mechanism": mechanism,
        "correct": bool(pipe.correct),
        "wall_seconds": case_seconds,
        "extracted_query": extracted,
        "core_relations": list(pipe.core_relations or []),
        "time_profile_seconds": {name: float(getattr(profile, name, 0.0) or 0.0)
                                 for name in PROFILE_TIME_FIELDS},
        "time_profile_app_calls": {name: int(getattr(profile, name, 0) or 0)
                                   for name in PROFILE_APP_FIELDS},
        "vm_local_elapsed_time": float(vm.local_elapsed_time) if vm else None,
        "vm_app_calls": int(vm.app_calls) if vm else None,
        "halving_rounds": getattr(vm, "halving_rounds", None),
        "pk_columns": dict(getattr(vm, "pk_columns", None) or {}),
        "pk_sources": dict(getattr(vm, "pk_sources", None) or {}),
        "pk_intervals": serialize_pk_intervals(getattr(vm, "pk_intervals", None)),
        "native_calls": native_calls,
    }

    print(
        f"{label}: correct={result['correct']} wall={case_seconds:.2f}s "
        f"vm={result['vm_local_elapsed_time']}s "
        f"vm_app_calls={result['vm_app_calls']} "
        f"rounds={result['halving_rounds']} mechanism={mechanism}",
        flush=True,
    )
    return result


def selected_cases():
    requested = os.environ.get("PRISM_PKVM_BENCH_CASES", "").strip()
    if not requested:
        return list(CASES)
    wanted = {item.strip() for item in requested.split(",") if item.strip()}
    filtered = [case for case in CASES if case in wanted]
    if not filtered:
        raise ValueError(
            f"PRISM_PKVM_BENCH_CASES={requested!r} did not match any case; "
            "use values like view or pk"
        )
    return filtered


def write_outputs(results):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    csv_rows = []
    for result in results:
        row = {
            "case": result["case"],
            "mechanism": result["mechanism"],
            "correct": result["correct"],
            "wall_seconds": f"{result['wall_seconds']:.3f}",
            "vm_local_elapsed_time": result["vm_local_elapsed_time"],
            "vm_app_calls": result["vm_app_calls"],
        }
        for name, value in result["time_profile_seconds"].items():
            row[f"time_{name}"] = f"{value:.3f}"
        for name, value in result["time_profile_app_calls"].items():
            row[f"app_{name}"] = value
        rounds = result["halving_rounds"] or {}
        row["halving_rounds_total"] = rounds.get("_total", sum(
            v for k, v in rounds.items() if k != "_total"))
        for table, count in sorted(rounds.items()):
            if table != "_total":
                row[f"rounds_{table}"] = count
        for table, interval in sorted((result["pk_intervals"] or {}).items()):
            row[f"pk_interval_{table}"] = f"[{interval[0]}, {interval[1]})"
        for table, col in sorted((result["pk_columns"] or {}).items()):
            row[f"pk_col_{table}"] = f"{col} ({result['pk_sources'].get(table, '?')})"
        csv_rows.append(row)

    fieldnames = sorted({key for row in csv_rows for key in row})
    with CSV_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    JSON_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {JSON_PATH} and {CSV_PATH}", flush=True)


def print_summary(results):
    print("\n=== Summary (MQ18, union ON, OJ ON) ===", flush=True)
    for result in results:
        print(
            f"{result['label']} [{result['mechanism']}]: "
            f"correct={result['correct']} "
            f"wall={result['wall_seconds']:.2f}s "
            f"vm={result['vm_local_elapsed_time']:.2f}s "
            f"vm_app_calls={result['vm_app_calls']} "
            f"t_view_min={result['time_profile_seconds']['t_view_min']:.2f}s "
            f"rounds={result['halving_rounds']}"
        )
    if len(results) == 2 and all(r["correct"] for r in results):
        view, pk = results if results[0]["case"] == "view" else results[::-1]
        if view["extracted_query"] == pk["extracted_query"]:
            print("Both cases produced the identical extracted query.", flush=True)
        else:
            print("NOTE: extracted queries differ between the two cases!", flush=True)


def run_benchmark():
    conn = ConnectionHelperFactory().createConnectionHelper()
    configure(conn)
    cases = selected_cases()
    if len(cases) == 2:
        # run the ctid baseline first, the PK variant second
        cases = ["view", "pk"]

    results = []
    try:
        for kind in cases:
            results.append(run_case(conn, kind))
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            JSON_PATH.write_text(json.dumps(results, indent=2))
    finally:
        try:
            drop_working_schema(conn)
        finally:
            conn.closeConnection()

    write_outputs(results)
    print_summary(results)
    return results


class PKViewMinimizerMq18ComparisonTest(unittest.TestCase):
    def test_pk_view_minimizer_mq18_comparison(self):
        results = run_benchmark()
        self.assertEqual(len(results), len(selected_cases()), "not every case ran")
        for result in results:
            self.assertTrue(
                result["correct"],
                f"{result['label']} did not extract MQ18 correctly",
            )
            self.assertIsNotNone(
                result["vm_local_elapsed_time"],
                f"{result['label']} never constructed a view minimizer",
            )
            self.assertTrue(
                JSON_PATH.is_file() and CSV_PATH.is_file(),
                "result files missing",
            )


if __name__ == "__main__":
    run_benchmark()
