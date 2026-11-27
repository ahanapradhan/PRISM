#!/usr/bin/env python3
"""Watchdog for CopyBasedMinimizerExperiment batch runs.

Monitors a running experiment process (or launches one) and, if the process
dies before the batch is complete, resumes it for the remaining queries.

Progress detection
------------------
A query is considered complete when its per-query merged plot exists::

    results/copy_minimizer_all_plots_{repeats}rep_{runs}runs_{expt}_{MQ}.png

(The experiment writes per-query CSVs/plots only after that query finishes.)
If the process dies mid-query, that query is treated as incomplete and will be
rerun from scratch on resume.

Resume behavior
---------------
On unexpected termination, the watchdog:
1. Detects completed/remaining queries from output files.
2. Cleans up DB state left by a crash (terminates active tpch queries and
   drops the ``unmasque`` schema) so the next run can start cleanly.
3. Relaunches the experiment for remaining queries only via ``PRISM_MQ_IDS``.

Examples
--------
Launch and supervise a full batch (default: remaining MQs, expt1, 3 runs)::

    python3 mysite/unmasque/test/native_test/watchdog_experiment.py

Monitor an already-running experiment PID and resume if it dies::

    python3 mysite/unmasque/test/native_test/watchdog_experiment.py --pid 17705

Resume manually from current outputs (no monitored process)::

    python3 mysite/unmasque/test/native_test/watchdog_experiment.py --resume-only
"""
from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

MQ_SERIES_ORDER = [
    "MQ1", "MQ2", "MQ3", "MQ4", "MQ5", "MQ6",
    "MQ10", "MQ11", "MQ17", "MQ18", "MQ21",
]
DEFAULT_REMAINING = [q for q in MQ_SERIES_ORDER if q != "MQ18"]
EXPERIMENT_MODULE = "mysite.unmasque.test.native_test.CopyBasedMinimizerExperiment"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pid", type=int, help="Monitor this existing PID instead of launching.")
    p.add_argument("--resume-only", action="store_true",
                   help="Do not launch/monitor; clean DB and run remaining queries once from current outputs.")
    p.add_argument("--mq-ids", default=",".join(DEFAULT_REMAINING),
                   help="Comma-separated intended query IDs in run order (default: all except MQ18).")
    p.add_argument("--expt", default=os.environ.get("PRISM_MQ_EXPTS", "expt1"),
                   help="Experiment name (default: expt1 or PRISM_MQ_EXPTS).")
    p.add_argument("--runs", type=int, default=int(os.environ.get("PRISM_MQ_RUNS", "3")),
                   help="Cold-cache runs per minimizer/query (default: 3 or PRISM_MQ_RUNS).")
    p.add_argument("--repeats", type=int, default=1, help="Probes per iteration (default: 1).")
    p.add_argument("--repo-root", default="/Users/ahanapradhan/pycharm_projects/PRISM",
                   help="Repository root / working directory.")
    p.add_argument("--results-dir", default=None,
                   help="Results directory (default: <repo>/mysite/unmasque/test/native_test/results).")
    p.add_argument("--db-name", default=os.environ.get("PRISM_DB_NAME", "tpch"),
                   help="PostgreSQL database name for cleanup (default: tpch).")
    p.add_argument("--poll-interval", type=float, default=15.0,
                   help="Seconds between liveness checks (default: 15).")
    p.add_argument("--max-restarts", type=int, default=50,
                   help="Maximum automatic resume attempts (default: 50).")
    p.add_argument("--cleanup-wait", type=float, default=5.0,
                   help="Seconds to wait after DB cleanup before relaunch (default: 5).")
    p.add_argument("--log-file", default=None,
                   help="Append watchdog log to this file (default: stdout only).")
    p.add_argument("--child-log-file", default=None,
                   help="Append experiment stdout/stderr to this file when watchdog launches it.")
    p.add_argument("--no-db-cleanup", action="store_true",
                   help="Skip DB cleanup before resume (not recommended after crashes).")
    p.add_argument("extra_pytest_args", nargs="*", help="Extra args passed to pytest.")
    return p.parse_args()


def log(msg, log_file=None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def intended_queries(args):
    ids = [q.strip() for q in args.mq_ids.split(",") if q.strip()]
    if not ids:
        raise ValueError("No intended MQ IDs provided")
    return ids


def result_paths(results_dir: Path, repeats: int, runs: int, expt: str, mq: str):
    tag = f"{repeats}rep_{runs}runs_{expt}_{mq}"
    merged = results_dir / f"copy_minimizer_all_plots_{tag}.png"
    csv_dir = results_dir / "csv"
    csvs = [
        csv_dir / f"copy_minimizer_timings_{tag}.csv",
        csv_dir / f"copy_minimizer_costs_{tag}.csv",
        csv_dir / f"copy_minimizer_tail_latency_{tag}.csv",
    ]
    return merged, csvs


def is_query_complete(results_dir: Path, repeats: int, runs: int, expt: str, mq: str) -> bool:
    merged, csvs = result_paths(results_dir, repeats, runs, expt, mq)
    # merged plot is the clearest end-of-query artifact; require it and CSVs for robustness
    return merged.exists() and all(p.exists() for p in csvs)


def completed_and_remaining(args, results_dir: Path):
    intended = intended_queries(args)
    completed = [mq for mq in intended if is_query_complete(results_dir, args.repeats, args.runs, args.expt, mq)]
    remaining = [mq for mq in intended if mq not in set(completed)]
    return intended, completed, remaining


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def run_cmd(cmd, cwd=None, env=None, capture=False, log_file=None, append_path=None):
    if append_path:
        Path(append_path).parent.mkdir(parents=True, exist_ok=True)
        with open(append_path, "a", encoding="utf-8") as out:
            return subprocess.run(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT)
    if capture:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    return subprocess.run(cmd, cwd=cwd, env=env)


def cleanup_db(args, log_file=None):
    if args.no_db_cleanup:
        log("DB cleanup skipped (--no-db-cleanup)", log_file)
        return
    db = args.db_name
    log(f"Cleaning DB state for '{db}' (terminate active queries, drop unmasque schema)", log_file)
    # terminate other active sessions on target db
    term_sql = (
        "select pg_terminate_backend(pid) "
        "from pg_stat_activity "
        f"where datname = '{db}' and pid <> pg_backend_pid() and state <> 'idle';"
    )
    r1 = run_cmd(["psql", "-d", db, "-v", "ON_ERROR_STOP=0", "-c", term_sql], capture=True)
    if r1.returncode != 0:
        log(f"Warning: terminate-backends command returned {r1.returncode}: {(r1.stderr or r1.stdout or '').strip()}", log_file)
    else:
        out = (r1.stdout or "").strip()
        if out:
            log(f"terminate_backends: {out.splitlines()[-1] if out.splitlines() else out}", log_file)
    r2 = run_cmd(["psql", "-d", db, "-v", "ON_ERROR_STOP=0", "-c", "drop schema if exists unmasque cascade;"], capture=True)
    if r2.returncode != 0:
        log(f"Warning: drop schema returned {r2.returncode}: {(r2.stderr or r2.stdout or '').strip()}", log_file)
    else:
        log(f"drop unmasque schema: {(r2.stdout or '').strip() or 'ok'}", log_file)


def build_env(args, remaining):
    env = os.environ.copy()
    env["PYTHONPATH"] = args.repo_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PRISM_MQ_IDS"] = ",".join(remaining)
    env["PRISM_MQ_EXPTS"] = args.expt
    env["PRISM_MQ_RUNS"] = str(args.runs)
    # repeats is class default (1); script doesn't take env for repeats, but keep explicit via env for info
    env["PRISM_WATCHDOG"] = "1"
    return env


def launch_experiment(args, remaining, log_file=None):
    cmd = [sys.executable, "-m", "pytest", f"mysite/unmasque/test/native_test/CopyBasedMinimizerExperiment.py", "-s"]
    cmd.extend(args.extra_pytest_args or [])
    env = build_env(args, remaining)
    log(f"Launching experiment for remaining queries ({len(remaining)}): {','.join(remaining)}", log_file)
    log(f"Command: {shlex.join(cmd)}", log_file)
    append = args.child_log_file
    if append:
        Path(append).parent.mkdir(parents=True, exist_ok=True)
        with open(append, "a", encoding="utf-8") as out:
            out.write(f"\n===== watchdog launch {time.strftime('%Y-%m-%d %H:%M:%S')} remaining={','.join(remaining)} =====\n")
            out.flush()
            proc = subprocess.Popen(cmd, cwd=args.repo_root, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True)
    else:
        proc = subprocess.Popen(cmd, cwd=args.repo_root, env=env, start_new_session=True)
    log(f"Experiment process started: pid={proc.pid}", log_file)
    return proc


def report_status(args, results_dir: Path, log_file=None):
    intended, completed, remaining = completed_and_remaining(args, results_dir)
    log(f"Intended ({len(intended)}): {','.join(intended)}", log_file)
    log(f"Completed ({len(completed)}): {','.join(completed) if completed else '(none)'}", log_file)
    if completed:
        log(f"Last completed query: {completed[-1]}", log_file)
    log(f"Remaining ({len(remaining)}): {','.join(remaining) if remaining else '(none)'}", log_file)
    return intended, completed, remaining


def wait_for_pid(pid: int, poll_interval: float, log_file=None):
    log(f"Monitoring existing PID {pid}", log_file)
    while process_alive(pid):
        time.sleep(poll_interval)
    log(f"Monitored PID {pid} is no longer alive", log_file)


def main():
    args = parse_args()
    if args.repeats != 1:
        log("Warning: experiment script currently uses class/default repeats=1; outputs are tagged with provided --repeats.", args.log_file)
    results_dir = Path(args.results_dir) if args.results_dir else Path(args.repo_root) / "mysite/unmasque/test/native_test/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "csv").mkdir(parents=True, exist_ok=True)

    intended, completed, remaining = report_status(args, results_dir, args.log_file)

    if not remaining:
        log("All intended queries already complete. Nothing to do.", args.log_file)
        return 0

    if args.resume_only:
        cleanup_db(args, args.log_file)
        time.sleep(args.cleanup_wait)
        proc = launch_experiment(args, remaining, args.log_file)
        rc = proc.wait()
        _, _, remaining_after = report_status(args, results_dir, args.log_file)
        if rc == 0 and not remaining_after:
            log("Experiment completed successfully.", args.log_file)
            return 0
        log(f"Experiment exited rc={rc}, remaining={','.join(remaining_after) if remaining_after else '(none)'}", args.log_file)
        return rc if rc != 0 else 1

    restarts = 0
    current_proc = None
    monitoring_external = args.pid is not None

    # Initial run/attach
    if monitoring_external:
        if not process_alive(args.pid):
            log(f"PID {args.pid} is not alive; treating as dead and resuming remaining.", args.log_file)
        else:
            wait_for_pid(args.pid, args.poll_interval, args.log_file)
        # external process ended (or was dead) -> fall through to resume loop check
        current_proc = None
    else:
        cleanup_db(args, args.log_file) if completed else None  # clean only if resuming into partial state
        time.sleep(args.cleanup_wait if completed else 0)
        _, _, remaining = completed_and_remaining(args, results_dir)
        if not remaining:
            log("All intended queries already complete.", args.log_file)
            return 0
        current_proc = launch_experiment(args, remaining, args.log_file)

    while True:
        if current_proc is not None:
            rc = current_proc.wait()
            log(f"Experiment process pid={current_proc.pid} exited with code {rc}", args.log_file)
            current_proc = None
        else:
            rc = None

        intended, completed, remaining = report_status(args, results_dir, args.log_file)
        if not remaining:
            log("Batch complete (all intended queries have per-query outputs).", args.log_file)
            return 0

        # died or finished but incomplete
        if rc == 0:
            log("Process exited with code 0 but some queries remain incomplete; will attempt resume.", args.log_file)
        else:
            log("Process is gone before batch completion; preparing resume.", args.log_file)

        if restarts >= args.max_restarts:
            log(f"Max restarts reached ({args.max_restarts}); giving up. Remaining: {','.join(remaining)}", args.log_file)
            return 2

        restarts += 1
        log(f"Resume attempt {restarts}/{args.max_restarts} for remaining: {','.join(remaining)}", args.log_file)
        cleanup_db(args, args.log_file)
        time.sleep(args.cleanup_wait)

        # re-evaluate after cleanup pause (no file changes expected, but cheap)
        _, _, remaining = completed_and_remaining(args, results_dir)
        if not remaining:
            log("All intended queries complete after cleanup/check.", args.log_file)
            return 0

        current_proc = launch_experiment(args, remaining, args.log_file)
        monitoring_external = False  # from now on we own child processes


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[watchdog] Interrupted by user", flush=True)
        sys.exit(130)
