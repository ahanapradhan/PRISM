#!/usr/bin/env python3
"""Build extraction_results.md from timings_per_query.csv and per-query logs.

Left column: input (hidden) query from main_cmd's workload.
Right column: extracted output query captured in /tmp/prism_matrix_logs/<qid>.log.
"""
import csv
import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
CSV_PATH = HERE / "timings_per_query.csv"
LOG_DIR = Path("/tmp/prism_matrix_logs")
OUT_PATH = HERE / "extraction_results.md"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "mysite"))
from mysite.unmasque.src.main_cmd import build_workload  # noqa: E402


def cell(text):
    """Escape SQL for an HTML/Markdown table cell."""
    text = html.escape(text.strip(), quote=False)
    return text.replace("|", "\\|").replace("\n", "<br>")


def extracted_query(qid):
    log = LOG_DIR / f"{qid}.log"
    if not log.exists():
        return "N/A (no log)"
    lines = log.read_text(errors="replace").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("=========== Extracted Query ============="):
            start = i + 1
            break
    if start is None:
        return "N/A (no extracted query in log)"
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("PROFILE_JSON:"):
            end = i
            break
    result = "\n".join(lines[start:end]).strip()
    return result if result else "N/A (pipeline returned no result)"


def main():
    workload = {q.qid: q.query for q in build_workload()}
    with open(CSV_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))

    lines = [
        "# Extraction results",
        "",
        "Input queries and queries extracted by PRISM for every query whose timing "
        "row is retained in `timings_per_query.csv`.",
        "",
        "| Input query | Output query |",
        "|---|---|",
    ]
    for row in rows:
        qid = row["query_id"]
        inp = workload.get(qid, "N/A (query no longer in workload)")
        out = extracted_query(qid)
        lines.append(f"| **{html.escape(qid)}**<br><code>{cell(inp)}</code> "
                     f"| <code>{cell(out)}</code> |")
    OUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT_PATH} ({len(rows)} queries)")


if __name__ == "__main__":
    main()
