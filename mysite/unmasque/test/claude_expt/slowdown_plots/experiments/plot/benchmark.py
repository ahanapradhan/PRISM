#!/usr/bin/env python3
"""
Matplotlib equivalent of benchmark.gnu.

The gnuplot script draws a clustered histogram of extraction times (seconds in
the data, minutes on the axis) for three systems on the MQ benchmark queries:

    set ylabel "Extraction Time (m)"
    plot 'data/languages.dat' using ($4/60):xtic(1) ti col fc rgb "#FF0000", \
         '' u ($2/60) ti col fc rgb "#00FF00", \
         '' u ($3/60) ti col fc rgb "#0000FF"

So the plotted order is column 4 (red), column 2 (green), column 3 (blue);
column 1 supplies the x tick labels and the header row supplies the legend
titles. Run this script from anywhere; paths default to the experiments
directory that contains data/ and figs/:

    python plot/benchmark.py
    python plot/benchmark.py --data data/languages.dat --out figs/comparison.png
"""
import argparse
import shlex
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# gnuplot: plot <col4> red, <col2> green, <col3> blue
COLUMN_ORDER = (2, 0, 1)          # zero-based positions in a data row (after the label)
COLORS = ("#FF0000", "#00FF00", "#0000FF")

# gnuplot: boxwidth 0.9, cluster gap 2 -> relative to one category slot
BAR_WIDTH = 0.18
BAR_OFFSETS = (-0.20, 0.0, 0.20)

BASE_DIR = Path(__file__).resolve().parent.parent   # experiments/
DEFAULT_DATA = BASE_DIR / "data" / "languages.dat"
DEFAULT_OUT = BASE_DIR / "figs" / "comparison.eps"


def read_dat(path):
    """Read gnuplot's whitespace-separated data: header row + label/value rows."""
    lines = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{path} is empty")
    header = shlex.split(lines[0])
    names = header[1:]                     # first header field is "Title"
    labels, rows = [], []
    for line in lines[1:]:
        fields = shlex.split(line)
        if len(fields) < 1 + len(names):
            raise ValueError(f"not enough columns in {path}: {line!r}")
        labels.append(fields[0])
        rows.append([float(v) for v in fields[1:1 + len(names)]])
    return names, labels, rows


def pretty_title(name):
    """gnuplot's `enhanced` term renders XPOSE_{basic} with a subscript."""
    if "_{" in name and name.endswith("}"):
        base, sub = name.split("_{", 1)
        return base + "$_{\\mathrm{" + sub[:-1] + "}}$"
    return name


def make_plot(path, out, dpi=200):
    names, labels, rows = read_dat(path)
    n = len(rows)

    fig, ax = plt.subplots(figsize=(6.6, 3.3))   # gnuplot: set size 1,0.6
    x = list(range(n))
    ymax = 0.0
    for col, color in zip(COLUMN_ORDER, COLORS):
        values = [row[col] / 60.0 for row in rows]     # seconds -> minutes
        ymax = max(ymax, max(values))
        ax.bar([xi + BAR_OFFSETS[COLUMN_ORDER.index(col)] for xi in x],
               values, width=BAR_WIDTH, color=color, edgecolor="black",
               linewidth=0.6, label=pretty_title(names[col]), zorder=2)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Extraction Time (m)", fontsize=20)
    ax.tick_params(axis="y", labelsize=18)
    ax.tick_params(axis="x", labelsize=11)
    ax.yaxis.set_major_locator(MultipleLocator(2))     # set ytics 2
    ax.set_ylim(0, ymax * 1.29 if ymax else 1)
    ax.set_xlim(-0.6, n - 0.4)
    ax.grid(True, axis="both", color="gray", linestyle=":", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(ncol=len(COLUMN_ORDER), loc="upper center", bbox_to_anchor=(0.5, 0.93),
              frameon=False, fontsize=15, handlelength=1.0, columnspacing=1.4,
              borderaxespad=0.2)

    fig.subplots_adjust(left=0.13, right=0.985, bottom=0.17, top=0.87)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    print("saved", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="gnuplot data file (default: data/languages.dat)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output image (default: figs/comparison.eps)")
    ap.add_argument("--dpi", type=int, default=200, help="resolution for raster outputs")
    args = ap.parse_args()
    make_plot(args.data, args.out, args.dpi)


if __name__ == "__main__":
    main()
