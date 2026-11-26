#!/usr/bin/env python3
"""Stacked-bar plot of per-query pipeline stage timings from timings_per_query.csv.

Usage:
    python plot_timings.py                          # writes timings_per_query.png
    python plot_timings.py --label patched --log-x  # filter rows, log-scaled x axis
    python plot_timings.py --stages from_clause,view_minimization,result_comparator

For queries with multiple timing rows, the run with the smallest ``prism_total``
is plotted.
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", default="timings_per_query.csv")
    ap.add_argument("--out", default="timings_per_query.png")
    ap.add_argument("--label", help="only plot rows with this label")
    ap.add_argument("--stages", help="comma-separated stage columns (default: all with nonzero time)")
    ap.add_argument("--log-x", action="store_true", help="log-scale the time axis")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if args.label:
        df = df[df["label"] == args.label]
    if "status" in df.columns:
        df = df[df["status"] == "ok"]
    if df.empty:
        raise SystemExit("no ok rows to plot")

    # Reruns of the same query are kept as separate rows. Plot only the fastest
    # run for each query, as measured by prism_total.
    if "prism_total" in df.columns:
        totals = pd.to_numeric(df["prism_total"], errors="coerce").fillna(float("inf"))
        df = (df.assign(_prism_total=totals)
                .sort_values("_prism_total", kind="stable")
                .drop_duplicates("query_id", keep="first")
                .drop(columns="_prism_total"))

    if args.stages:
        stages = [s.strip() for s in args.stages.split(",")]
    else:
        stages = [s for s in STAGE_COLUMNS if s in df.columns and df[s].fillna(0).sum() > 0]

    df = df.reset_index(drop=True)
    data = df.set_index("query_id")[stages].fillna(0)
    data = data.loc[data.sum(axis=1).sort_values(ascending=True).index]

    ax = data.plot.barh(
        stacked=True,
        figsize=(13, max(5, 0.38 * len(data) + 2)),
        width=0.75,
        colormap="tab20",
    )
    if args.log_x:
        ax.set_xscale("log")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Query")
    ax.set_title("PRISM pipeline stage timings per query")
    ax.legend(loc="lower right", fontsize=8, ncols=2)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(args.out, dpi=150)
    print(f"wrote {args.out} ({len(data)} queries, {len(stages)} stages; "
          f"min prism_total per query)")


if __name__ == "__main__":
    main()
