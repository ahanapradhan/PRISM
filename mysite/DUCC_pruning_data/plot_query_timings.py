"""
Single combined bar chart of query extraction times, clustered by category
(Union, Algebraic Predicates, Outer Join, Fusion), each category colored
differently, with a gap between clusters.

Usage:
    python3 plot_query_timings.py query_timings.csv output-combined.png
"""

import sys
import csv
from collections import OrderedDict
import matplotlib.pyplot as plt

plt.rcParams.update({"font.size": 18, "hatch.linewidth": 1.5})

CATEGORY_COLORS = {
    "Union": "#1f77b4",               # blue
    "NEP": "#d62728",  # red
    "OuterJoin": "#2ca02c",           # green
    "Fusion": "#9467bd",              # purple
}

CATEGORY_HATCHES = {
    "Union": "///",
    "NEP": "xxx",
    "OuterJoin": "ooo",
    "Fusion": "***",
}

CATEGORY_LABELS = {
    "Union": "Union Queries",
    "NEP": "NEP Queries",
    "OuterJoin": "Outer Join Queries",
    "Fusion": "Fusion Queries",
}


def load_data(csv_path):
    # category -> list of (query_label, time)
    data = OrderedDict()
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = row["Category"]
            data.setdefault(cat, []).append((row["Query"], float(row["ExtractionTime"])))
    return data


def plot(csv_path, out_path):
    data = load_data(csv_path)

    gap = 1  # empty slots between clusters
    x_positions = []
    labels = []
    heights = []
    colors = []
    hatches = []
    cluster_centers = []

    pos = 0
    for cat, items in data.items():
        start = pos
        for label, height in items:
            x_positions.append(pos)
            labels.append(label)
            heights.append(height)
            colors.append(CATEGORY_COLORS[cat])
            hatches.append(CATEGORY_HATCHES[cat])
            pos += 1
        cluster_centers.append((start + pos - 1) / 2)
        pos += gap  # gap before next cluster

    fig, ax = plt.subplots(figsize=(14, 6))
    bars = ax.bar(x_positions, heights, color=colors, width=0.8,
                   edgecolor="black", linewidth=0.8)
    for bar, hatch in zip(bars, hatches):
        bar.set_hatch(hatch)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Extraction Time (m)")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    # legend, one entry per category
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=CATEGORY_COLORS[cat],
                      edgecolor="black", hatch=CATEGORY_HATCHES[cat])
        for cat in data
    ]
    labels_legend = [CATEGORY_LABELS[cat] for cat in data]
    ax.legend(handles, labels_legend, loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "query_timings.csv"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output-combined.png"
    plot(csv_file, out_file)