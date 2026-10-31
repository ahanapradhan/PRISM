"""
Plot |AuxTables| (x-axis) against TotalSubsets and QueriesNeeded (left y-axis, dots),
and NumSubqueries (right / y2-axis).

Usage:
    python3 plot_data.py data.csv output.png
"""

import sys
import csv
import matplotlib.pyplot as plt

plt.rcParams.update({"font.size": 18})

def load_data(csv_path):
    aux_tables, total_subsets, queries_needed, num_subqueries = [], [], [], []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aux_tables.append(int(row["AuxTables"]))
            total_subsets.append(int(row["TotalSubsets"]))
            queries_needed.append(int(row["QueriesNeeded"]))
    return aux_tables, total_subsets, queries_needed, num_subqueries


def plot(csv_path, out_path):
    aux_tables, total_subsets, queries_needed, num_subqueries = load_data(csv_path)

    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Left y-axis: TotalSubsets (red dots) and QueriesNeeded (green dots)
    ax1.scatter(aux_tables, total_subsets, color="red", label="TotalSubsets", s=60)
    ax1.scatter(aux_tables, queries_needed, color="green", label="QueriesNeeded", s=60)
    ax1.set_xlabel("|AUX|")
    ax1.set_yscale("log")  # TotalSubsets grows exponentially; log scale keeps both series readable
    ax1.grid(True)

    # Combine legends from both axes
    handles1, labels1 = ax1.get_legend_handles_labels()
    ax1.legend(handles1 , labels1 , loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output.png"
    plot(csv_file, out_file)