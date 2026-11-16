#!/usr/bin/env python3
"""Run a matrix of PRISM queries and record per-stage timings in one CSV.

For every query the `unmasque` working schema is dropped and re-created first,
so each run starts from the same state (the pipeline needs the schema to exist;
its own CREATE SCHEMA is rolled back by From-Clause probing).

Usage:
    python tmp_run_matrix.py                 # default battery, writes timings_per_query.csv
    python tmp_run_matrix.py --fresh         # same, but truncate the CSV first
    python tmp_run_matrix.py --only U2,DS3   # subset
    python tmp_run_matrix.py --label pre     # tag rows (default: patched)

One row per query; columns are the pipeline stage times in seconds plus
prism_total / wall_clock and bookkeeping fields. A plotting script can read
the CSV directly (see plot_timings.py).
"""
import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
CSV_PATH = REPO / "timings_per_query.csv"
LOG_DIR = Path("/tmp/prism_matrix_logs")
CHILD = REPO / "tmp_profile_csv.py"

STAGE_COLUMNS = [
    "t_init",
    "t_from_clause",
    "t_union",
    "t_restore_db",
    "t_correlated_sampling",
    "t_view_minimization",
    "t_where_clause",
    "t_projection",
    "t_group_by",
    "t_aggregation",
    "t_order_by",
    "t_limit",
    "t_outer_join",
    "t_nep",
    "t_result_comparator",
]

COLUMNS = (
    ["query_id", "status", "label", "cs2", "union", "oj", "nep", "orf"]
    + STAGE_COLUMNS
    + ["t_backup_excluded", "prism_total", "wall_clock", "wall_measured", "return_code"]
)


def default_qids():
    return (
        [f"U{k}" for k in range(2, 10)]
        + [f"A{k}" for k in range(1, 6)]
        + ["N1"]
        + [f"DS{k}" for k in range(1, 11)]
        + [f"F{k}" for k in range(1, 5)]
    )


def psql(*args, capture=False):
    return subprocess.run(
        ["psql", "-d", "tpch", "-v", "ON_ERROR_STOP=1", "-q", *args],
        check=True,
        capture_output=capture,
        text=True,
    )


def reset_schema():
    """Make the working schema safe: kill stale sessions, drop, re-create."""
    psql(
        "-c",
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname = 'tpch' and pid <> pg_backend_pid();",
        capture=True,
    )
    psql(
        "-c", "DROP SCHEMA IF EXISTS unmasque CASCADE;",
        "-c", "CREATE SCHEMA unmasque;",
    )
    out = psql(
        "-Atc", "select count(*) from pg_tables where schemaname = 'fresh';",
        capture=True,
    ).stdout.strip()
    if out != "8":
        raise SystemExit(f"fresh schema has {out} tables, expected 8 - aborting")


def rss_mb(pid):
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        return int(out) // 1024 if out else 0
    except (ValueError, OSError):
        return 0


def postgres_tpch_mb():
    out = subprocess.run(
        ["ps", "-axo", "rss=,command="], capture_output=True, text=True
    ).stdout
    total = 0
    for line in out.splitlines():
        if "postgres" in line and "tpch" in line:
            try:
                total += int(line.split(None, 1)[0])
            except ValueError:
                pass
    return total // 1024


def run_one(qid, timeout, max_child_mb, max_total_mb):
    log_path = LOG_DIR / f"{qid}.log"
    env = dict(os.environ, PGOPTIONS="-c enable_nestloop=off")
    start = time.time()
    status = "ok"

    with open(log_path, "w") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(CHILD), qid],
            cwd=str(REPO),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while proc.poll() is None:
            elapsed = time.time() - start
            child_mb = rss_mb(proc.pid)
            if elapsed > timeout:
                status = "timeout"
                os.killpg(proc.pid, signal.SIGKILL)
                break
            if child_mb > max_child_mb or child_mb + postgres_tpch_mb() > max_total_mb:
                status = "memkill"
                os.killpg(proc.pid, signal.SIGKILL)
                break
            time.sleep(5)
        rc = proc.wait()
    wall = time.time() - start

    payload = {}
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith("PROFILE_JSON:"):
            payload = json.loads(line[len("PROFILE_JSON:"):])
            break

    if status == "ok" and (rc != 0 or "error" in payload):
        status = "error"

    row = {
        "query_id": qid,
        "status": status,
        "return_code": rc,
        "wall_measured": round(wall, 2),
    }
    row.update(payload)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated query ids (default: full battery)")
    parser.add_argument("--label", default="patched", help="tag written to the label column")
    parser.add_argument("--csv", default=str(CSV_PATH), help="output CSV path")
    parser.add_argument("--fresh", action="store_true", help="truncate the CSV before writing")
    parser.add_argument("--timeout", type=int, default=1800, help="per-query timeout in seconds")
    parser.add_argument("--max-child-mb", type=int, default=6000, help="kill a run above this RSS")
    parser.add_argument("--max-total-mb", type=int, default=9000,
                        help="kill a run when child + tpch backends exceed this")
    args = parser.parse_args()

    qids = args.only.split(",") if args.only else default_qids()
    csv_path = Path(args.csv)
    if args.fresh:
        csv_path.unlink(missing_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
            fh.flush()
        for i, qid in enumerate(qids, 1):
            reset_schema()
            row = run_one(qid, args.timeout, args.max_child_mb, args.max_total_mb)
            row["label"] = args.label
            writer.writerow({c: row.get(c, "") for c in COLUMNS})
            fh.flush()
            print(
                f"[{i}/{len(qids)}] {qid}: {row['status']} "
                f"wall={row['wall_measured']}s prism={row.get('prism_total', '')} "
                f"log={LOG_DIR / (qid + '.log')}",
                flush=True,
            )
    print(f"CSV written to {csv_path}")


if __name__ == "__main__":
    main()
