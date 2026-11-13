#!/usr/bin/env python3
"""Plot PRISM and the best CUBES result for each query.

CUBES_best selection priority:
    1. Correct result
    2. Incorrect completed result
    3. SQL conversion failure
    4. Interrupted result

Within the same status class, the result with the lower elapsed time wins.

Expected files in the current working directory:
    reviewed_results.json
    prism_results.csv

Expected prism_results.csv format:
    query_id,elapsed_seconds,status
    DS1,1.234,correct
    DS2,2.345,correct
    ...

The status column is optional. If omitted, PRISM is assumed correct.
PRISM_basic is deliberately not read or plotted.
"""

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from matplotlib.ticker import FixedLocator, FuncFormatter


QUERY_IDS = [
    "DS1",
    "DS2",
    "DS3",
    "NEP1_a",
    "NEP2_a",
    "NEP3_a",
    "OJ1",
    "OJ2",
    "OJ3",
    "UK3",
    "UK_a",
    "UN3",
    "UN_a",
]

CORRECT_STATUS = "correct_under_tpch_constraints"

STATUS_PRIORITY = {
    "correct_under_tpch_constraints": 0,
    "incorrect": 1,
    "sql_conversion_failed": 2,
    "interrupted": 3,
}

# UNMASQUE-style series colors.
PRISM_COLOR = "#8A2BE2"       # Violet
CUBES_COLOR = "#008080"       # Teal
DARK_GREEN = "#006400"        # Correct-result marker/annotation
FAILURE_COLOR = "#C73535"     # Incorrect or unsuccessful result
GRID_COLOR = "#B8B8B8"


def elapsed_seconds(record):
    """Extract and validate elapsed wall-clock time."""

    try:
        value = float(record["times"]["real"]["seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "Missing or invalid elapsed time for record: {}".format(record)
        ) from error

    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            "Elapsed time must be positive and finite: {}".format(value)
        )

    return value


def selection_key(record):
    """Return the ordering key used to select CUBES_best."""

    status = record.get("status")

    if status not in STATUS_PRIORITY:
        raise ValueError("Unrecognized CUBES status: {!r}".format(status))

    return STATUS_PRIORITY[status], elapsed_seconds(record)


def choose_cubes_best(records):
    """Choose one CUBES result per query."""

    grouped = {query_id: [] for query_id in QUERY_IDS}

    for record in records:
        query_id = record.get("query_id")

        if query_id not in grouped:
            continue

        # Validate the record before considering it.
        elapsed_seconds(record)
        grouped[query_id].append(record)

    selected = {}

    for query_id in QUERY_IDS:
        candidates = grouped[query_id]

        if not candidates:
            selected[query_id] = None
            continue

        selected[query_id] = min(candidates, key=selection_key)

    return selected


def read_cubes_results(path, run):
    """Read the reviewed CUBES JSON and select CUBES_best."""

    with path.open(encoding="utf-8-sig") as stream:
        document = json.load(stream)

    records = [
        record
        for record in document.get("records", [])
        if record.get("run") == run
    ]

    if not records:
        raise ValueError(
            "No CUBES records found for run {} in {}".format(run, path)
        )

    return choose_cubes_best(records)


def normalize_prism_status(value):
    """Normalize optional PRISM status strings."""

    if value is None or not str(value).strip():
        return CORRECT_STATUS

    normalized = str(value).strip().lower()

    if normalized in {
        "correct",
        "success",
        "successful",
        "true",
        "correct_under_tpch_constraints",
    }:
        return CORRECT_STATUS

    if normalized in {"incorrect", "false"}:
        return "incorrect"

    if normalized in {"timeout", "timed_out", "interrupted"}:
        return "interrupted"

    if normalized in {
        "sql_conversion_failed",
        "conversion_failed",
        "sql_error",
    }:
        return "sql_conversion_failed"

    return normalized


def read_prism_results(path):
    """Read the PRISM timing series from a CSV file."""

    if not path.is_file():
        return {}

    results = {}

    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)

        required = {"query_id", "elapsed_seconds"}
        available = set(reader.fieldnames or [])

        if not required.issubset(available):
            raise ValueError(
                "{} must have the columns query_id and elapsed_seconds."
                .format(path)
            )

        for row in reader:
            query_id = row["query_id"].strip()

            if query_id not in QUERY_IDS:
                continue

            if query_id in results:
                raise ValueError(
                    "Duplicate PRISM result for query {!r}".format(query_id)
                )

            try:
                elapsed = float(row["elapsed_seconds"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Invalid PRISM elapsed time for {}: {!r}".format(
                        query_id,
                        row["elapsed_seconds"],
                    )
                ) from error

            if not math.isfinite(elapsed) or elapsed <= 0:
                raise ValueError(
                    "Invalid PRISM elapsed time for {}: {}".format(
                        query_id,
                        elapsed,
                    )
                )

            results[query_id] = {
                "query_id": query_id,
                "elapsed_seconds": elapsed,
                "status": normalize_prism_status(row.get("status")),
            }

    return results


def status_is_correct(record):
    return (
        record is not None
        and record.get("status") == CORRECT_STATUS
    )


def status_symbol(record):
    """Return a short correctness marker."""

    if record is None:
        return "N/A"

    status = record.get("status")

    if status == CORRECT_STATUS:
        return "✓"

    if status == "incorrect":
        return "✗"

    if status == "interrupted":
        return "INT"

    if status == "sql_conversion_failed":
        return "SQL"

    return "?"


def format_time(value):
    """Format elapsed seconds compactly."""

    if value < 10:
        return "{:.2f}".format(value)

    if value < 100:
        return "{:.1f}".format(value)

    return "{:.0f}".format(value)


def annotation_color(record):
    if status_is_correct(record):
        return DARK_GREEN

    return FAILURE_COLOR


def determine_axis_limit(prism_results, cubes_results):
    """Calculate a common upper limit for the logarithmic Y axis."""

    values = []

    for query_id in QUERY_IDS:
        prism = prism_results.get(query_id)
        cubes = cubes_results.get(query_id)

        if prism is not None:
            values.append(prism["elapsed_seconds"])

        if cubes is not None:
            values.append(elapsed_seconds(cubes))

    if not values:
        raise ValueError("There are no timing values to plot.")

    return max(200, max(values) * 1.6)


def make_ticks(upper):
    candidates = [
        1,
        2,
        5,
        10,
        20,
        50,
        100,
        200,
        500,
        1000,
        2000,
        5000,
    ]

    ticks = [value for value in candidates if value <= upper]

    if not ticks:
        ticks = [1]

    return ticks


def plot_results(prism_results, cubes_results, output):
    """Create the two-series PRISM versus CUBES_best plot."""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 15,
        }
    )

    x = np.arange(len(QUERY_IDS))
    width = 0.36

    figure, ax = plt.subplots(figsize=(16, 8))

    upper = determine_axis_limit(prism_results, cubes_results)
    ticks = make_ticks(upper)

    prism_legend_added = False
    cubes_legend_added = False

    for index, query_id in enumerate(QUERY_IDS):
        prism = prism_results.get(query_id)
        cubes = cubes_results.get(query_id)

        prism_x = x[index] - width / 2
        cubes_x = x[index] + width / 2

        if prism is not None:
            value = prism["elapsed_seconds"]

            ax.bar(
                prism_x,
                value,
                width=width,
                color=PRISM_COLOR,
                edgecolor="none",
                label="PRISM" if not prism_legend_added else None,
                zorder=3,
            )
            prism_legend_added = True

            ax.text(
                prism_x,
                value * 1.08,
                "{}\n{}".format(
                    format_time(value),
                    status_symbol(prism),
                ),
                ha="center",
                va="bottom",
                fontsize=10,
                color=annotation_color(prism),
                linespacing=0.9,
                zorder=4,
            )
        else:
            ax.text(
                prism_x,
                0.025,
                "N/A",
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=10,
                color="#555555",
            )

        if cubes is not None:
            value = elapsed_seconds(cubes)

            ax.bar(
                cubes_x,
                value,
                width=width,
                color=CUBES_COLOR,
                edgecolor="none",
                label="CUBES_best" if not cubes_legend_added else None,
                zorder=3,
            )
            cubes_legend_added = True

            ax.text(
                cubes_x,
                value * 1.08,
                "{}\n{}".format(
                    format_time(value),
                    status_symbol(cubes),
                ),
                ha="center",
                va="bottom",
                fontsize=10,
                color=annotation_color(cubes),
                linespacing=0.9,
                zorder=4,
            )

    ax.set_yscale("log")
    ax.set_ylim(0.65, upper)
    ax.set_xlim(-0.65, len(QUERY_IDS) - 0.35)

    ax.set_xticks(x)
    ax.set_xticklabels(
        QUERY_IDS,
        rotation=45,
        ha="right",
        fontsize=15,
    )

    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: "{:g}".format(value))
    )
    ax.minorticks_off()

    # Match the clean UNMASQUE grid style.
    ax.grid(
        visible=True,
        axis="y",
        color=GRID_COLOR,
        linestyle="-",
        linewidth=0.6,
        alpha=0.55,
        zorder=0,
    )
    ax.set_axisbelow(True)

    ax.set_xlabel("Query ID", fontsize=18)
    ax.set_ylabel(
        "Elapsed wall time (seconds, log scale)",
        fontsize=18,
    )

    ax.tick_params(axis="both", labelsize=15)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    legend_handles = []

    if prism_results:
        legend_handles.append(
            Patch(
                facecolor=PRISM_COLOR,
                edgecolor="none",
                label="PRISM",
            )
        )

    legend_handles.append(
        Patch(
            facecolor=CUBES_COLOR,
            edgecolor="none",
            label="CUBES_best",
        )
    )

    figure.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.96),
        ncol=len(legend_handles),
        frameon=False,
        fontsize=16,
    )

    figure.subplots_adjust(
        left=0.09,
        right=0.985,
        bottom=0.20,
        top=0.88,
    )

    figure.savefig(
        output,
        format="png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(figure)


def print_cubes_selection(cubes_results):
    """Print an audit table showing which CUBES run won."""

    print()
    print("Selected CUBES_best results:")
    print(
        "{:<8} {:<11} {:<8} {:>10}  {}".format(
            "Query",
            "Mode",
            "Task",
            "Seconds",
            "Status",
        )
    )
    print("-" * 70)

    for query_id in QUERY_IDS:
        record = cubes_results.get(query_id)

        if record is None:
            print(
                "{:<8} {:<11} {:<8} {:>10}  {}".format(
                    query_id,
                    "-",
                    "-",
                    "-",
                    "missing",
                )
            )
            continue

        print(
            "{:<8} {:<11} {:<8} {:>10.3f}  {}".format(
                query_id,
                record["mode"],
                record["task"],
                elapsed_seconds(record),
                record["status"],
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--cubes-json",
        type=Path,
        default=Path("reviewed_results.json"),
        help="Reviewed CUBES JSON input.",
    )
    parser.add_argument(
        "--prism-csv",
        type=Path,
        default=Path("prism_results.csv"),
        help="CSV containing PRISM timings.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("prism_vs_cubes_best.png"),
        help="Output PNG file.",
    )
    parser.add_argument(
        "--run",
        type=int,
        default=1,
        help="Run number to select from the CUBES JSON.",
    )

    args = parser.parse_args()

    if not args.cubes_json.is_file():
        raise FileNotFoundError(
            "Could not find CUBES JSON file: {}".format(args.cubes_json)
        )

    cubes_results = read_cubes_results(
        args.cubes_json,
        args.run,
    )

    prism_results = read_prism_results(args.prism_csv)

    if not prism_results:
        print(
            "Warning: {} was not found or contained no matching PRISM rows."
            .format(args.prism_csv)
        )
        print("The output will contain only the CUBES_best bars.")

    print_cubes_selection(cubes_results)

    plot_results(
        prism_results,
        cubes_results,
        args.output,
    )

    print()
    print("Saved {}".format(args.output.resolve()))


if __name__ == "__main__":
    main()