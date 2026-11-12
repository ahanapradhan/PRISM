"""
Average total extraction time: UNMASQUE vs PRISM.

Requirements:  pip install matplotlib numpy
Run:           python plot_total_time.py
Output:        total_extraction_time.png

All timings below are in seconds. The six components are summed and
the resulting total is converted to minutes before plotting.

Component order:
    [DB Minimization, From Clause (+ Union),
     Where Clause, NEP, Outer Join, Others]
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mt
import numpy as np


# ----------------------------- DATA (seconds) -----------------------------

QUERIES = [
    "MQ1", "MQ2", "MQ3", "MQ4", "MQ5", "MQ6",
    "MQ10", "MQ11", "MQ17", "MQ18", "MQ21"
]

UNMASQUE = {
    #         DBmin  From  Where  NEP  Outer  Others
    "MQ1":  [5,      7.5,  0,     0,   0,     1.5],
    "MQ2":  [1.5,    0.3,  0,     0,   0,     3.2],
    "MQ3":  [7,      5,    0,     0,   0,     3],
    "MQ4":  [0.5,    0.5,  0,     0.2, 0,     1.0],
    "MQ5":  [22,     2,    0,     0,   0,     4],
    "MQ6":  [2,      1.5,  0,     0,   0,     1.5],
    "MQ10": [11,     3,    0,     0,   0,     2],
    "MQ11": [1,      0.5,  0,     0,   0,     1.5],
    "MQ17": [3.5,    1.5,  0,     0,   0,     1],
    "MQ18": [116,    1,    0,     0,   0,     2.5],
    "MQ21": [4,      3,    0,     0,   0,     4],
}

PRISM = {
    #         DBmin  From  Where  NEP  Outer  Others
    "MQ1":  [5,      8.5,  12,    0,   0,     2],
    "MQ2":  [2,      1.3,  0,     0,   0,     5],
    "MQ3":  [14,     6,    40,    0,   0,     4],
    "MQ4":  [0.5,    1.5,  0,     0,   0,     1.5],
    "MQ5":  [25,     3,    20,    0,   1.5,   7],
    "MQ6":  [1.5,    2.5,  7,     0,   0,     1.5],
    "MQ10": [11,     4,    12,    0,   0,     4],
    "MQ11": [0.5,    1.5,  0,     0,   0,     2],
    "MQ17": [4.5,    2.5,  7,     0,   0,     2],
    "MQ18": [124,    2,    12,    0,   0,     3],
    "MQ21": [5.5,    4,    10,    0,   0,     3],
}


# ----------------------------- STYLE -----------------------------

UNMASQUE_COLOR = "#8A2BE2"   # violet
PRISM_COLOR = "#1F5D17"      # dark green

plt.rcParams["font.family"] = [
    "Arial",
    "Liberation Sans",
    "DejaVu Sans"
]

TICK_FS = 27
LABEL_FS = 35
LEGEND_FS = 35

BAR_W = 0.38
YMAX = 3  # minutes


# ----------------------------- TOTALS -----------------------------

# Sum all components and convert seconds to minutes.
unmasque_totals = np.array(
    [sum(UNMASQUE[q]) for q in QUERIES],
    dtype=float
) / 60.0

prism_totals = np.array(
    [sum(PRISM[q]) for q in QUERIES],
    dtype=float
) / 60.0


# ----------------------------- PLOT -----------------------------

fig, ax = plt.subplots(figsize=(20, 6.6), dpi=200)

x = np.arange(len(QUERIES))

ax.bar(
    x - BAR_W / 2,
    unmasque_totals,
    width=BAR_W,
    color=UNMASQUE_COLOR,
    edgecolor="black",
    linewidth=1.0,
    label="UNMASQUE",
    zorder=3
)

ax.bar(
    x + BAR_W / 2,
    prism_totals,
    width=BAR_W,
    color=PRISM_COLOR,
    edgecolor="black",
    linewidth=1.0,
    label="PRISM",
    zorder=3
)


# ----------------------------- AXES -----------------------------

ax.set_xticks(x)
ax.set_xticklabels(QUERIES, fontsize=TICK_FS)

ax.set_yticks([0, 1, 2, 3])
ax.set_yticklabels(["0", "1", "2", "3"])

# Minor gridlines every 0.25 minutes.
ax.yaxis.set_minor_locator(mt.MultipleLocator(1))

ax.grid(
    axis="y",
    which="both",
    color="#bbbbbb",
    linewidth=0.8,
    zorder=0
)

ax.tick_params(axis="y", labelsize=TICK_FS)
ax.tick_params(axis="y", which="minor", length=0)

ax.set_ylim(0, YMAX)
ax.set_xlim(-0.5, len(QUERIES) - 0.5)

ax.set_ylabel("Extraction Time (min)", fontsize=LABEL_FS)


# ----------------------------- LEGEND -----------------------------

ax.legend(
    loc="upper left",
    ncol=2,
    fontsize=LEGEND_FS,
    frameon=True,
    facecolor="white",
    edgecolor="none",
    framealpha=1,
    columnspacing=1.2,
    handlelength=1.5,
    handletextpad=0.5
)


# ----------------------------- SAVE -----------------------------

plt.tight_layout()
plt.savefig(
    "total_extraction_time.png",
    dpi=200,
    bbox_inches="tight"
)
plt.close(fig)

print("Saved total_extraction_time.png")