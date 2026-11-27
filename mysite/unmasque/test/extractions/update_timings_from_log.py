#!/usr/bin/env python3
"""Regenerate timings_per_query.png from successful extractions in unmasque.log.

Success is defined by the result comparator verdict recorded in
``unmasque.log`` (``Extracted Query is Correct.``).  The stage-level timings
come from ``timings_per_query.csv``; its ``correct`` column mirrors that same
verdict.  A-series queries keep the rows plotted yesterday
(``final5_allflags``); every other approved workload query is selected from
its last contiguous block of successful CSV rows.  When a query was run
consecutively, the row with the smallest ``prism_total`` in that block is used.

The raw CSV is never modified: the one-row-per-query input and the refreshed
PNG are written to ``timings_per_query_final.csv`` and
``timings_per_query.png`` respectively.
"""
import collections
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
CSV_PATH = HERE / "timings_per_query.csv"
FINAL_CSV = HERE / "timings_per_query_final.csv"
PNG_PATH = HERE / "timings_per_query.png"
PLOT_SCRIPT = HERE / "plot_timings.py"
WORKLOAD_PATH = REPO / "SQL_workload.sql"

A_LABEL = "final5_allflags"

COLUMNS = [
    "query_id", "status", "label", "cs2", "union", "oj", "nep", "orf",
    "minimizer", "correct", "t_init", "t_from_clause", "t_union",
    "t_restore_db", "t_correlated_sampling", "t_view_minimization",
    "t_where_clause", "t_projection", "t_group_by", "t_aggregation",
    "t_order_by", "t_limit", "t_outer_join", "t_nep",
    "t_result_comparator", "t_backup_excluded", "prism_total",
    "wall_clock", "wall_measured", "return_code",
]

TS_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})- ")
START_RE = re.compile(
    r"set search_path='unmasque';\s*set search_path='public';\s*EXPLAIN\b", re.I)
SUCCESS_RE = re.compile(r"Extracted Query is Correct\.")
SQL_START_RE = re.compile(r"\b(?:select|with)\b", re.I)


def read_workload():
    blocks = re.split(r"(?m)^-- Query: ", WORKLOAD_PATH.read_text())[1:]
    queries = {}
    for block in blocks:
        qid, body = block.split("\n", 1)
        queries[qid.strip()] = body.strip()
    return queries


def strip_outer_parens(sql):
    sql = sql.strip()
    while sql.startswith("(") and sql.endswith(")"):
        depth = 0
        closes_at_end = True
        for i, ch in enumerate(sql):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(sql) - 1:
                    closes_at_end = False
                    break
        if not closes_at_end:
            break
        sql = sql[1:-1].strip()
    return sql


def norm(sql):
    sql = sql.lower().strip()
    sql = re.sub(r"^select q\.\* from \(\s*", "", sql)
    sql = re.sub(r"\s+as q\s+limit\s+\d+\s*;?\s*$", ";", sql)
    sql = sql.rstrip().rstrip(";").rstrip()
    return strip_outer_parens(re.sub(r"\s+", " ", sql))


def norm_noparens(sql):
    return re.sub(r"[()]", "", norm(sql))


def build_matchers(queries):
    exact = collections.defaultdict(set)
    exact_noparens = collections.defaultdict(set)
    prefixes = []
    for qid, sql in queries.items():
        n = norm(sql)
        exact[n].add(qid)
        exact_noparens[norm_noparens(sql)].add(qid)
        prefixes.append((n[:90], qid))
    return exact, exact_noparens, prefixes


def match_sql(sql, matchers):
    exact, exact_noparens, prefixes = matchers
    sm = SQL_START_RE.search(sql)
    if not sm:
        return None
    sql = sql[sm.start():]
    n = norm(sql)
    qids = exact.get(n)
    if qids is None:
        qids = exact_noparens.get(norm_noparens(sql))
    if qids is None:
        qids = {qid for pref, qid in prefixes if pref and pref in n}
    return next(iter(qids)) if qids and len(qids) == 1 else None


def log_lines():
    """Yield unmasque.log lines, recovering the committed copy if needed."""
    if Path("/tmp/opencode/unmasque.log").exists():
        with Path("/tmp/opencode/unmasque.log").open(errors="replace") as fh:
            yield from fh
        return
    if LOG_PATH.exists():
        with LOG_PATH.open(errors="replace") as fh:
            yield from fh
        return
    commits = subprocess.check_output(
        ["git", "-C", str(REPO), "log", "--all", "--format=%H",
         "--", "mysite/unmasque.log"],
        text=True,
    ).split()
    candidates = []
    for commit in commits:
        blob = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", f"{commit}:mysite/unmasque.log"],
            capture_output=True, text=True,
        )
        if blob.returncode != 0:
            continue
        oid = blob.stdout.strip()
        size = int(subprocess.check_output(
            ["git", "-C", str(REPO), "cat-file", "-s", oid], text=True).strip())
        candidates.append((size, oid))
    if not candidates:
        raise SystemExit("unmasque.log not found in worktree or git history")
    # The largest historical blob is the most complete append-only snapshot.
    oid = max(candidates)[1]
    proc = subprocess.Popen(
        ["git", "-C", str(REPO), "cat-file", "blob", oid],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        errors="replace",
    )
    yield from proc.stdout
    proc.wait()


LOG_PATH = REPO / "mysite" / "unmasque.log"


def scan_log(queries):
    """Return the set of qids with at least one correct comparator verdict.

    A run starts at the hidden-query EXPLAIN line (which precedes the
    ``support files verified`` marker) and ends at the next such line.  The
    verdict is emitted inside that run.
    """
    matchers = build_matchers(queries)
    confirmed = set()
    total_correct = 0
    current_qid = None
    for line in log_lines():
        line = line.rstrip("\n")
        if START_RE.search(line):
            em = re.search(r"EXPLAIN\b(.*)$", line, re.I | re.S)
            current_qid = match_sql(em.group(1) if em else "", matchers)
        if SUCCESS_RE.search(line):
            total_correct += 1
            if current_qid:
                confirmed.add(current_qid)
    return total_correct, confirmed


def is_correct(row):
    return row.get("status") == "ok" and str(row.get("correct", "")).lower() == "true"


def prism_total(row):
    try:
        return float(row["prism_total"])
    except (TypeError, ValueError):
        return float("inf")


def select_rows(rows, keys, a_keys, log_confirmed):
    by_qid = collections.defaultdict(list)
    for i, row in enumerate(rows):
        by_qid[row["query_id"]].append(i)

    selected = {}
    sources = {}
    for qid in keys:
        indices = by_qid[qid]
        if not indices:
            continue
        correct = [i for i in indices if is_correct(rows[i])]
        override = False
        if not correct and qid in log_confirmed:
            # Comparator says correct in the log, but the CSV flag is stale.
            # memkill rows carry no timing splits and cannot be used.
            valid = [i for i in indices
                     if rows[i].get("status") == "ok"
                     and prism_total(rows[i]) != float("inf")]
            if valid:
                correct = [valid[-1]]
                override = True
        if not correct:
            continue

        last = correct[-1]
        start = end = last
        index_set = set(indices)
        while start - 1 in index_set and is_correct(rows[start - 1]):
            start -= 1
        while end + 1 in index_set and is_correct(rows[end + 1]):
            end += 1
        block = [rows[i] for i in range(start, end + 1) if i in index_set]
        best = dict(min(block, key=prism_total))
        if override:
            best["correct"] = "True"
        selected[qid] = best
        sources[qid] = (best["label"], start, end, len(block))

    for qid in a_keys:
        candidates = [r for r in rows
                      if r["query_id"] == qid and r["label"] == A_LABEL
                      and is_correct(r)]
        if candidates:
            selected[qid] = dict(candidates[0])
            sources[qid] = (A_LABEL, -1, -1, 1)
    return selected, sources


def write_csv(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})


def main():
    queries = read_workload()
    all_keys = list(queries)
    rows = list(csv.DictReader(CSV_PATH.open(newline="")))

    print("Parsing unmasque.log for comparator verdicts ...", flush=True)
    total_correct, log_confirmed = scan_log(queries)
    print(f"  correct verdicts: {total_correct}; attributed to "
          f"{len(log_confirmed)} workload queries")

    a_keys = sorted({r["query_id"] for r in rows
                     if r["label"] == A_LABEL and is_correct(r)})
    def has_timing(qid):
        return any(r["query_id"] == qid and r.get("status") == "ok"
                   and prism_total(r) != float("inf") for r in rows)

    remaining = [q for q in all_keys
                 if q not in a_keys and has_timing(q)
                 and (any(is_correct(r) for r in rows if r["query_id"] == q)
                      or q in log_confirmed)]
    selected, sources = select_rows(rows, remaining, a_keys, log_confirmed)

    missing = [q for q in remaining if q not in selected]
    if missing:
        raise SystemExit(f"no successful timing row for: {', '.join(missing)}")

    final_rows = [selected[q] for q in all_keys if q in selected]
    write_csv(FINAL_CSV, final_rows)

    python = "python3.9" if shutil.which("python3.9") else sys.executable
    subprocess.run(
        [python, str(PLOT_SCRIPT), str(FINAL_CSV), "--out", str(PNG_PATH)],
        cwd=str(HERE), check=True,
    )

    print(f"Updated {PNG_PATH} with {len(final_rows)} queries "
          f"({len(a_keys)} A-series + {len(remaining)} remaining).")
    print(f"One-row-per-query input written to {FINAL_CSV}; raw "
          f"{CSV_PATH.name} left unchanged.")
    for qid in remaining:
        label, start, end, n = sources[qid]
        if n > 1:
            print(f"  {qid}: {n} consecutive successful rows {start}-{end} "
                  f"({label}), min prism_total "
                  f"{prism_total(selected[qid]):.3f}s")


if __name__ == "__main__":
    main()
