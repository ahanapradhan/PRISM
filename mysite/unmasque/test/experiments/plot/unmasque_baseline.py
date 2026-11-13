#!/usr/bin/env python3

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator


DATA_FILE = Path("languages.dat")
OUTPUT_FILE = Path("comparison.png")


def main():
    """Generate a clustered bar chart from languages.dat."""

    if not DATA_FILE.is_file():
        raise FileNotFoundError(
            f"Could not find '{DATA_FILE}' in the current working directory:\n"
            f"{Path.cwd()}"
        )

    data = pd.read_csv(
        DATA_FILE,
        sep=r"\s+",
        header=0,
    )

    labels = data.iloc[:, 0].astype(str)
    x = np.arange(len(labels))

    # Plot columns 4, 2, and 3, matching the original Gnuplot order.
    # Convert values from seconds to minutes.
    series = [
       # (data.iloc[:, 3] / 60.0, data.columns[3], "#8A2BE2"),  # Violet
        (data.iloc[:, 1] / 60.0, data.columns[1], "#8A2BE2"),  # Teal
        (data.iloc[:, 2] / 60.0, data.columns[2], "#006400"),  # Dark green
    ]

    fig, ax = plt.subplots(figsize=(10, 3.6))

    bar_width = 0.24
    offsets = [-bar_width, 0, bar_width]

    for offset, (values, title, color) in zip(offsets, series):
        ax.bar(
            x + offset,
            values,
            width=bar_width,
            label=title,
            color=color,
            edgecolor="black",
            linewidth=0.6,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(
        labels,
        fontsize=15,
        fontname="Helvetica",
    )

    ax.tick_params(
        axis="y",
        labelsize=28,
    )

    for tick in ax.get_yticklabels():
        tick.set_fontname("Helvetica")

    ax.set_ylabel(
        "Extraction Time (m)",
        fontsize=20,
        fontname="Helvetica",
    )

    # Equivalent to Gnuplot: set ytics 2
    ax.yaxis.set_major_locator(MultipleLocator(2))

    # Equivalent to Gnuplot: set grid
    ax.grid(
        visible=True,
        axis="both",
        linestyle="-",
        linewidth=0.5,
        color="0.75",
    )
    ax.set_axisbelow(True)

    # Equivalent to Gnuplot: set key horizontal
    ax.legend(
        loc="best",
        ncol=1,
        frameon=False,
        prop={
            "family": "Helvetica",
            "size": 20,
        },
    )

    ax.autoscale(axis="x", tight=True)
    fig.tight_layout()

    fig.savefig(
        OUTPUT_FILE,
        format="png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(fig)

    print(f"Created: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()