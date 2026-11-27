"""
Recreate the CUBES vs PRISM extraction-time plot from the supplied image.

The values are inferred approximately from the raster image and are expressed
in minutes. For CUBES, None represents a timeout (TO).

Requirements:
    pip install matplotlib numpy

Run:
    python recreate_extraction_time.py

Output:
    extraction_time_recreated.png
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


# -------------------------------------------------------------------------
# DATA INFERRED FROM THE IMAGE
# -------------------------------------------------------------------------

QUERIES = [
    "D1",
    "D2",
    "D3",
    "NEP1",
    "NEP2",
    "NEP3",
    "OJ1"
]

# Approximate extraction times in minutes.
#
# None means that CUBES timed out, so no purple bar is drawn.
CUBES = [
    0.030,   # DS1
    0.033,   # DS2
    0.033,   # DS3
    0.029,   # NEP1_a
    0.078,   # NEP2_a
    3.10,    # NEP3_a: marked "incorrect"
    0.063,   # OJ1
]

PRISM = [
    0.0060,  # DS1
    0.0075,  # DS2
    0.0090,  # DS3
    0.0072,  # NEP1_a
    0.0090,  # NEP2_a
    0.0130,  # NEP3_a
    0.0072,  # OJ1
]


# -------------------------------------------------------------------------
# APPEARANCE
# -------------------------------------------------------------------------

CUBES_COLOR = "#7C2DD2"
PRISM_COLOR = "#1E5D18"

BAR_WIDTH = 0.22

plt.rcParams.update(
    {
        "font.family": ["Arial", "Liberation Sans", "DejaVu Sans"],
        "font.size": 20,
        "axes.linewidth": 1.0,
        "xtick.major.width": 1.0,
        "ytick.major.width": 1.0,
    }
)


# -------------------------------------------------------------------------
# FIGURE
# -------------------------------------------------------------------------

# This intentionally uses a large canvas with whitespace below the plot,
# matching the supplied image.
fig = plt.figure(
    figsize=(15.36, 10.24),
    dpi=100,
    facecolor="white",
)

# [left, bottom, width, height]
ax = fig.add_axes([0.128, 0.58, 0.677, 0.325])

x = np.arange(len(QUERIES), dtype=float)

cubes_x = x - BAR_WIDTH / 2
prism_x = x + BAR_WIDTH / 2


# -------------------------------------------------------------------------
# BARS
# -------------------------------------------------------------------------

# Only draw CUBES bars that have numerical values.
valid_cubes_indices = [
    i for i, value in enumerate(CUBES) if value is not None
]

valid_cubes_x = np.array(
    [cubes_x[i] for i in valid_cubes_indices]
)

valid_cubes_values = np.array(
    [CUBES[i] for i in valid_cubes_indices],
    dtype=float,
)

ax.bar(
    valid_cubes_x,
    valid_cubes_values,
    width=BAR_WIDTH,
    color=CUBES_COLOR,
    edgecolor="#4E177F",
    linewidth=1.0,
    label="CUBES",
    zorder=3,
)

ax.bar(
    prism_x,
    PRISM,
    width=BAR_WIDTH,
    color=PRISM_COLOR,
    edgecolor="#123A0E",
    linewidth=1.0,
    label="PRISM",
    zorder=3,
)


# -------------------------------------------------------------------------
# LOGARITHMIC Y AXIS
# -------------------------------------------------------------------------

ax.set_yscale("log")
ax.set_ylim(1e-3, 1e1)

# Show only the three labels visible in the supplied image.
ax.set_yticks([1e-3, 1e-1, 1e1])

ax.yaxis.set_major_formatter(
    mticker.LogFormatterMathtext(base=10)
)

# Prevent additional minor tick marks and minor gridlines.
ax.yaxis.set_minor_locator(mticker.NullLocator())
ax.yaxis.set_minor_formatter(mticker.NullFormatter())

ax.tick_params(
    axis="y",
    which="major",
    labelsize=38,
    length=6,
    pad=8,
)


# -------------------------------------------------------------------------
# X AXIS
# -------------------------------------------------------------------------

ax.set_xticks(x)

ax.set_xticklabels(
    QUERIES,
    rotation=36,
    ha="right",
    rotation_mode="anchor",
    fontsize=21,
)

ax.tick_params(
    axis="x",
    which="major",
    length=5,
    pad=5,
)


# -------------------------------------------------------------------------
# LABEL AND GRID
# -------------------------------------------------------------------------

ax.set_ylabel(
    "Extraction Time (min)",
    fontsize=30,
    labelpad=7,
)

# Major horizontal gridlines and vertical category gridlines.
ax.grid(
    axis="y",
    which="major",
    color="#BFC0C0",
    linewidth=0.8,
    alpha=0.65,
    zorder=0,
)

ax.grid(
    axis="x",
    which="major",
    color="#D0D0D0",
    linewidth=0.8,
    alpha=0.65,
    zorder=0,
)

ax.set_axisbelow(True)
ax.set_xlim(-0.35, len(QUERIES) - 0.65)


# -------------------------------------------------------------------------
# LEGEND
# -------------------------------------------------------------------------

legend = ax.legend(
    loc="upper left",
    bbox_to_anchor=(0.012, 0.985),
    borderaxespad=0,
    fontsize=27,
    frameon=True,
    facecolor="white",
    edgecolor="none",
    framealpha=1.0,
    handlelength=1.8,
    handletextpad=0.7,
    labelspacing=0.45,
)

legend.set_zorder(10)


# -------------------------------------------------------------------------
# TIMEOUT ANNOTATIONS
# -------------------------------------------------------------------------

timeout_indices = [
    i for i, value in enumerate(CUBES) if value is None
]

# Put TO immediately above the lower limit so it remains visible on the
# logarithmic axis.
timeout_y = 1.18e-3

for i in timeout_indices:
    ax.text(
        cubes_x[i],
        timeout_y,
        "TO",
        color="red",
        fontsize=17,
        rotation=90,
        ha="center",
        va="bottom",
        zorder=7,
        clip_on=True,
    )


# -------------------------------------------------------------------------
# INCORRECT ANNOTATION
# -------------------------------------------------------------------------

nep3_index = QUERIES.index("NEP3")

ax.annotate(
    "incorrect",
    xy=(cubes_x[nep3_index], CUBES[nep3_index]),
    xytext=(cubes_x[nep3_index], 3.45),
    ha="center",
    va="bottom",
    fontsize=17,
    color="red",
    bbox={
        "boxstyle": "round,pad=0.18",
        "facecolor": "white",
        "edgecolor": "red",
        "linewidth": 1.2,
    },
    zorder=8,
)


# -------------------------------------------------------------------------
# SAVE
# -------------------------------------------------------------------------

OUTPUT_FILE = "extraction_time_recreated.png"

fig.savefig(
    OUTPUT_FILE,
    dpi=100,
    facecolor="white",
)

plt.close(fig)

print(f"Saved {OUTPUT_FILE}")