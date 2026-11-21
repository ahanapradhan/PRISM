#!/usr/bin/env python3

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUTPUT_FILE = Path("all_queries.png")

# Extraction time (minutes), read off the original four-panel figure (approximate).
DATA = [
    # (a) Union queries
    ("U1", 1.47), ("U2", 1.16), ("U3", 2.19), ("U4", 2.26), ("U5", 2.33),
    ("U6", 2.30), ("U7", 1.64), ("U8", 3.40), ("U9", 0.60),
    # (b) Algebraic predicate queries
    ("D1", 0.9), ("D10", 1.32),
    ("N1", 4.86),
    # (c) Outer join queries
    ("O1", 0.42), ("O2", 1.58), ("O3", 2.75), ("O4", 1.87), ("O5", 0.75),
    ("O6", 1.91),
    # (d) Fusion queries
    ("F1", 1.84), ("F2", 3.94), ("F3", 1.22), ("F4", 1.79),
]

BLUE = "#1F6FD1"

# Use Helvetica if present, otherwise fall back quietly.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans"]


def main():
    labels = [q for q, _ in DATA]
    values = np.array([v for _, v in DATA])
    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(12, 3.8))

    ax.bar(x, values, width=0.62, color=BLUE, edgecolor="black", linewidth=0.6)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=14, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=18)
    ax.set_ylabel("Extraction Time (min)", fontsize=18)
    ax.set_ylim(0, 5.5)

    ax.grid(visible=True, axis="y", linestyle="-", linewidth=0.5, color="0.75")
    ax.set_axisbelow(True)

    ax.set_xlim(-0.7, len(labels) - 0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_FILE, format="png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"Created: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()