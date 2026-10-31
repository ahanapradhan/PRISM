"""
Heatmap of average PruningPercent, with |AuxTables| on one axis and
NumSubqueries on the other. Cells with no data are left blank (masked).

Usage:
    python3 plot_pruning_heatmap.py data_pruning.csv output-heatmap.png
"""

import sys
import csv
from collections import defaultdict
import numpy as np
import matplotlib.pyplot as plt

plt.rcParams.update({"font.size": 14})


def load_data(csv_path):
    values = defaultdict(list)  # (aux_tables, num_subqueries) -> [pruning_percent, ...]
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aux = int(row["AuxTables"])
            nsq = int(row["NumSubqueries"])
            pp = float(row["PruningPercent"])
            values[(aux, nsq)].append(pp)
    return values


def build_grid(values):
    aux_tables = sorted({k[0] for k in values})
    num_subqueries = sorted({k[1] for k in values})

    # rows = NumSubqueries, cols = |AuxTables|
    grid = np.full((len(num_subqueries), len(aux_tables)), np.nan)
    for i, nsq in enumerate(num_subqueries):
        for j, aux in enumerate(aux_tables):
            if (aux, nsq) in values:
                grid[i, j] = np.mean(values[(aux, nsq)])

    return grid, aux_tables, num_subqueries


def plot(csv_path, out_path):
    values = load_data(csv_path)
    grid, aux_tables, num_subqueries = build_grid(values)

    fig, ax = plt.subplots(figsize=(10, 6))

    masked_grid = np.ma.masked_invalid(grid)
    cmap = plt.cm.RdYlGn  # red = low pruning, green = high pruning
    cmap.set_bad(color="lightgray")  # missing combos shown as gray

    im = ax.imshow(masked_grid, cmap=cmap, vmin=0, vmax=100, aspect="auto")

    ax.set_xticks(range(len(aux_tables)))
    ax.set_xticklabels(aux_tables)
    ax.set_yticks(range(len(num_subqueries)))
    ax.set_yticklabels(num_subqueries)
    ax.set_xlabel("|AUX|")
    ax.set_ylabel("NumSubqueries")
    ax.set_title("Average Pruning % by |AUX| and NumSubqueries")

    # annotate each cell with its value
    for i in range(len(num_subqueries)):
        for j in range(len(aux_tables)):
            if not np.isnan(grid[i, j]):
                ax.text(
                    j, i, f"{grid[i, j]:.1f}",
                    ha="center", va="center",
                    color="black", fontsize=11,
                )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Pruning %")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "data_pruning.csv"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output-heatmap.png"
    plot(csv_file, out_file)