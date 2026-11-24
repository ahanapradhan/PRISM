#!/usr/bin/env python3
"""Run the full main_cmd workload (except demo/TPC-DS) and record stage timings.

Each query runs in a fresh process with:
  union / outer join / NEP / OR = True, CS2 = False,
  native (C) backup, and minimizer = hybrid for queries mentioning lineitem,
  view otherwise.

The CSV is upserted by (query_id, label) after every query, and the PNG plot is
refreshed after every 10 completed queries.
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
sys.path.insert(0, str(REPO / "mysite"))

from mysite.unmasque.src.main_cmd import build_workload  # noqa: E402

CSV_PATH = REPO / "timings_per_query.csv"
LOG_DIR = Path("/tmp/prism_matrix_logs")
CHILD = REPO / "tmp_profile_csv.py"
APP_LOG = REPO / "mysite" / "unmasque.log"

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
    ["query_id", "status", "label", "cs2", "union", "oj", "nep", "orf", "minimizer", "correct"]
    + STAGE_COLUMNS
    + ["t_backup_excluded", "prism_total", "wall_clock", "wall_measured", "return_code"]
)

# TPC-DS queries have no tables in this TPC-H database; the user asked to skip them.
TPCDS_PREFIXES = ("T3B", "T6B")


def default_qids():
    return [q.qid for q in build_workload()
            if q.qid != "demo" and not q.qid.startswith(TPCDS_PREFIXES)]


def psql(*args, capture=False):
    env = dict(os.environ, PGPASSWORD=os.environ.get("PGPASSWORD", "postgres"))
    return subprocess.run(
        ["psql", "-h", "localhost", "-U", "postgres", "-d", "tpch",
         "-v", "ON_ERROR_STOP=1", "-q", *args],
        check=True, capture_output=capture, text=True, env=env,
    )


def reset_schema():
    """Start each run from the same state: working schema present, data intact."""
    psql("-c", "select pg_terminate_backend(pid) from pg_stat_activity "
               "where datname = 'tpch' and pid <> pg_backend_pid();", capture=True)
    psql("-c", "DROP SCHEMA IF EXISTS unmasque CASCADE;",
         "-c", "CREATE SCHEMA unmasque;")
    out = psql("-Atc", "select count(*) from pg_tables where schemaname = 'public';",
               capture=True).stdout.strip()
    if out != "8":
        raise SystemExit(f"public schema has {out} tables, expected 8 - aborting")


def rss_mb(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True).stdout.strip()
        return int(out) // 1024 if out else 0
    except (ValueError, OSError):
        return 0


def postgres_tpch_mb():
    out = subprocess.run(["ps", "-axo", "rss=,command="],
                         capture_output=True, text=True).stdout
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
    env = dict(os.environ,
               PGOPTIONS="-c enable_nestloop=off",
               PRISM_NATIVE_COPY=os.environ.get("PRISM_NATIVE_COPY", "on"))
    start = time.time()
    status = "ok"

    with open(log_path, "w") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(CHILD), qid],
            cwd=str(REPO), env=env,
            stdout=fh, stderr=subprocess.STDOUT,
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

    log_text = log_path.read_text(errors="replace")
    payload = {}
    for line in log_text.splitlines():
        if line.startswith("PROFILE_JSON:"):
            payload = json.loads(line[len("PROFILE_JSON:"):])
            break

    if status == "ok" and (rc != 0 or "error" in payload):
        status = "error"
    if status == "ok" and "Traceback (most recent call last)" in log_text:
        status = "error"

    row = {
        "query_id": qid,
        "status": status,
        "return_code": rc,
        "wall_measured": round(wall, 2),
    }
    row.update(payload)
    return row, log_path


def upsert_row(csv_path, row):
    rows = []
    if csv_path.exists() and csv_path.stat().st_size:
        with open(csv_path, newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if not (r.get("query_id") == row["query_id"]
                            and r.get("label") == row["label"])]
    rows.append(row)
    tmp_path = csv_path.with_suffix(".csv.tmp")
    with open(tmp_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in COLUMNS})
    tmp_path.replace(csv_path)


def refresh_plot(csv_path, label, out):
    cmd = [sys.executable, str(REPO / "plot_timings.py"), str(csv_path),
           "--label", label, "--out", str(out)]
    try:
        subprocess.run(cmd, cwd=str(REPO), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(f"  plot updated: {out}", flush=True)
    except subprocess.CalledProcessError as exc:
        print(f"  plot skipped: {exc.stdout.strip()}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated query ids")
    parser.add_argument("--label", default="allflags", help="tag written to the label column")
    parser.add_argument("--csv", default=str(CSV_PATH), help="output CSV path")
    parser.add_argument("--fresh", action="store_true", help="truncate the CSV before writing")
    parser.add_argument("--timeout", type=int, default=1800, help="per-query timeout in seconds")
    parser.add_argument("--max-child-mb", type=int, default=6000, help="kill a run above this RSS")
    parser.add_argument("--max-total-mb", type=int, default=9000,
                        help="kill a run when child + tpch backends exceed this")
    parser.add_argument("--plot-out", default=str(REPO / "timings_per_query.png"))
    args = parser.parse_args()

    qids = args.only.split(",") if args.only else default_qids()
    csv_path = Path(args.csv)
    if args.fresh and csv_path.exists():
        csv_path.unlink()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    failures = []
    for i, qid in enumerate(qids, 1):
        reset_schema()
        row, log_path = run_one(qid, args.timeout, args.max_child_mb, args.max_total_mb)
        row["label"] = args.label
        row.setdefault("correct", "")
        upsert_row(csv_path, row)
        if row["status"] != "ok":
            failures.append(qid)
        print(
            f"[{i}/{len(qids)}] {qid}: {row['status']} "
            f"minimizer={row.get('minimizer', '')} correct={row.get('correct', '')} "
            f"wall={row['wall_measured']}s prism={row.get('prism_total', '')} "
            f"sampling={row.get('t_correlated_sampling', '')} log={log_path}",
            flush=True,
        )
        if i % 10 == 0:
            refresh_plot(csv_path, args.label, args.plot_out)

    if failures:
        print("FAILED/INCOMPLETE QUERIES: " + ",".join(failures), flush=True)
    print(f"CSV written to {csv_path}")
    if len(qids) % 10 != 0:
        refresh_plot(csv_path, args.label, args.plot_out)


if __name__ == "__main__":
    main()
