#!/usr/bin/env python3
"""Per-query stage timings with a broken x-axis (125-550 s collapsed).

Same one-row-per-query input and query ordering as plot_timings.py, but:
  * Time (s) and its ticks appear on both the top and bottom of each axis,
  * the 125-550 s interval is collapsed (marked by a curly brace) so that F6's
    outlier where_clause stage does not squeeze every other query's detail.
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.path import Path as MplPath

from plot_timings import STAGE_COLUMNS

HERE = Path(__file__).resolve().parent

LEFT_MAX = 125
RIGHT_MIN = 550
RIGHT_MAX = 700


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", default=str(HERE / "timings_per_query_final.csv"))
    ap.add_argument("--out", default=str(HERE / "timings_per_query_broken_axis.png"))
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "status" in df.columns:
        df = df[df["status"] == "ok"]
    if df.empty:
        raise SystemExit("no ok rows to plot")

    if "prism_total" in df.columns:
        totals = pd.to_numeric(df["prism_total"], errors="coerce").fillna(float("inf"))
        df = (df.assign(_prism_total=totals)
                .sort_values("_prism_total", kind="stable")
                .drop_duplicates("query_id", keep="first")
                .drop(columns="_prism_total"))

    stages = [s for s in STAGE_COLUMNS if s in df.columns and df[s].fillna(0).sum() > 0]
    data = df.set_index("query_id")[stages].fillna(0)
    data = data.loc[data.sum(axis=1).sort_values(ascending=True).index]

    figsize = (13, max(5, 0.38 * len(data) + 2))
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, sharey=True, figsize=figsize,
        gridspec_kw={"width_ratios": [3, 1]},
    )
    fig.subplots_adjust(left=0.075, right=0.985, top=0.975, bottom=0.03, wspace=0.06)

    for ax in (ax_left, ax_right):
        data.plot.barh(
            stacked=True, ax=ax, width=0.75,
            colormap="tab20", legend=False,
        )
        ax.grid(axis="x", linestyle=":", alpha=0.4)
        ax.xaxis.set_ticks_position("both")
        ax.xaxis.set_label_position("top")
        ax.set_xlabel("Time (s)", labelpad=6)
        ax.text(0.5, -0.018, "Time (s)", transform=ax.transAxes,
                ha="center", va="top", fontsize=10)

    ax_left.set_xlim(0, LEFT_MAX)
    ax_right.set_xlim(RIGHT_MIN, RIGHT_MAX)
    ax_left.set_xticks([0, 25, 50, 75, 100, 125])
    ax_right.set_xticks([550, 600, 650, 700])
    ax_left.set_ylabel("Query")

    fig.suptitle("PRISM pipeline stage timings per query", y=0.998, fontsize=12)

    # A single curly brace lies ON the top x-axis at the cut, spanning the
    # omitted 125-550 s interval rather than floating in the panel gap.
    brace_verts = [
        (0.8, 1.0),
        (0.4, 1.0), (0.2, 0.95), (0.2, 0.85),
        (0.2, 0.7), (0.5, 0.65), (0.5, 0.5),
        (0.5, 0.35), (0.2, 0.3), (0.2, 0.15),
        (0.2, 0.05), (0.4, 0.0), (0.8, 0.0),
    ]
    brace_codes = [MplPath.MOVETO] + [MplPath.CURVE4] * (len(brace_verts) - 1)
    brace = MplPath(brace_verts, brace_codes).interpolated(200).vertices

    left_pos = ax_left.get_position()
    right_pos = ax_right.get_position()
    cut_x = (left_pos.x1 + right_pos.x0) / 2
    span = 0.045
    axis_y = 0.968
    thickness = 0.012
    xs = cut_x - span / 2 + span * brace[:, 1]
    ys = axis_y + thickness * (brace[:, 0] - 0.5)
    fig.add_artist(Line2D(xs, ys, transform=fig.transFigure,
                          color="black", linewidth=1.5))

    handles, labels = ax_left.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", fontsize=8, ncol=2)

    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out} ({len(data)} queries, {len(stages)} stages; "
          f"{LEFT_MAX}-{RIGHT_MIN} s collapsed)")


if __name__ == "__main__":
    main()
