"""
Avg. extraction time breakdown: UNMASQUE vs PRISM.

Requirements:  pip install matplotlib numpy
Run:           python plot_time_breakdown.py
Output:        time_breakdown_revised.png (current directory)

All timings below are in SECONDS (values read off the original figure, with
the corrections applied). They are converted to minutes when plotted.
Component order in each list:
    [DB Minimization, From Clause (+ Union), Where Clause, NEP, Outer Join, Others]
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mt
from matplotlib.patches import Patch, Rectangle
import numpy as np

# ----------------------------- DATA (seconds) -----------------------------
QUERIES = ["MQ1", "MQ2", "MQ3", "MQ4", "MQ5", "MQ6",
           "MQ10", "MQ11", "MQ17", "MQ18", "MQ21"]

COMPONENTS = ["DB Minimization", "From Clause (+ Union)",
              "Where Clause", "NEP", "Outer Join", "Others"]

UNMASQUE = {
    #         DBmin  From  Where NEP  Outer Others
    "MQ1":  [5,      7.5,  0,    0,   0,    1.5],
    "MQ2":  [1.5,    0.3,  0,    0,   0,    3.2],
    "MQ3":  [7,      5,    0,    0,   0,    3],
    "MQ4":  [0.5,    0.5,  0,    0.2, 0,    1.0],
    "MQ5":  [22,     2,    0,    0,   0,    4],
    "MQ6":  [2,      1.5,  0,    0,   0,    1.5],
    "MQ10": [11,     3,    0,    0,   0,    2],
    "MQ11": [1,      0.5,  0,    0,   0,    1.5],
    "MQ17": [3.5,    1.5,  0,    0,   0,    1],
    "MQ18": [116,    1,    0,    0,   0,    2.5],
    "MQ21": [4,      3,    0,    0,   0,    4],
}

# PRISM From Clause (+ Union) = UNMASQUE From Clause + 1 s for every query.
PRISM = {
    #         DBmin  From  Where NEP  Outer Others
    "MQ1":  [5,      8.5,  7,    0,   0,    2],
    "MQ2":  [2,      1.3,  2,    0,   0,    5],
    "MQ3":  [14,      6,    40,    0,   0,    4],
    "MQ4":  [0.5,    1.5,  1,    0,   0,    1.5],
    "MQ5":  [30,     3,    12,    0,   1.5,  7],
    "MQ6":  [1.5,    2.5,  7,    0,   0,    1.5],
    "MQ10": [14,     4,    20,    0,   0,    4],
    "MQ11": [0.5,    1.5,  1,    0,   0,    2],
    "MQ17": [4.5,    2.5,  7,    0,   0,    2],
    "MQ18": [124,    2,    12,    0,   0,    3],
    "MQ21": [5.5,    4,    12.5,    0,   0,    3],
}

# ----------------------------- STYLE -----------------------------
COLORS = ["#8A2BE2", "#2AA7A7", "#F28E2B", "#D62728", "#E8C547", "#B0B0B0"]
UNMASQUE_BORDER = "#1F5FD6"   # blue
PRISM_BORDER = "#D62020"      # red
HATCH = "//"

plt.rcParams["hatch.linewidth"] = 2.2
plt.rcParams["font.family"] = ["Arial", "Liberation Sans", "DejaVu Sans"]

TICK_FS, LABEL_FS, LEGEND_FS = 30, 31, 27
YMAX = 2.5            # minutes
BAR_W = 0.38

# ----------------------------- PLOT -----------------------------
fig, ax = plt.subplots(figsize=(20, 6.6), dpi=200)
x = np.arange(len(QUERIES))

for offset, data, hatch, border in [
    (-BAR_W / 2, UNMASQUE, None, UNMASQUE_BORDER),
    (+BAR_W / 2, PRISM, HATCH, PRISM_BORDER),
]:
    bottom = np.zeros(len(QUERIES))
    for i, color in enumerate(COLORS):
        vals = np.array([data[q][i] for q in QUERIES]) / 60.0   # sec -> min
        ax.bar(x + offset, vals, BAR_W, bottom=bottom, color=color,
               edgecolor="black", linewidth=1.0, hatch=hatch, zorder=3)
        bottom += vals
    # coloured outer border around each whole bar
    for xi, total in zip(x, bottom):
        ax.add_patch(Rectangle((xi + offset - BAR_W / 2, 0), BAR_W, total,
                               fill=False, edgecolor=border,
                               linewidth=3.5, zorder=6))

# axes
ax.set_xticks(x)
ax.set_xticklabels(QUERIES, fontsize=TICK_FS)
ax.set_yticks([0, 0.5, 1, 1.5, 2, 2.5])
ax.set_yticklabels(["0", "0.5", "1", "1.5", "2", "2.5"])
ax.yaxis.set_minor_locator(mt.MultipleLocator(0.25))      # grid every 0.25 min
ax.grid(axis="y", which="both", color="black", linewidth=1, zorder=0)
ax.tick_params(axis="y", labelsize=TICK_FS)
ax.tick_params(axis="y", which="minor", length=0)
ax.set_ylim(0, YMAX)
ax.set_xlim(-0.5, len(QUERIES) - 0.5)
ax.set_ylabel("Extraction Time (m)", fontsize=LABEL_FS)

# legends
comp_handles = [Patch(facecolor=c, edgecolor="black", label=l)
                for c, l in zip(COLORS, COMPONENTS)]
leg1 = ax.legend(handles=comp_handles, ncol=3, loc="upper left",
                 bbox_to_anchor=(0.0, 0.95), fontsize=LEGEND_FS,
                 frameon=True, facecolor="white", edgecolor="black",
                 framealpha=1, columnspacing=1.0, handlelength=1.4)
leg1.set_zorder(10)
ax.add_artist(leg1)

sys_handles = [
    Patch(facecolor="white", edgecolor=UNMASQUE_BORDER, linewidth=3,
          label="UNMASQUE"),
    Patch(facecolor="white", edgecolor=PRISM_BORDER, linewidth=3,
          hatch=HATCH, label="PRISM"),
]
ax.legend(handles=sys_handles, loc="upper center",
          bbox_to_anchor=(7.9 / 11, 0.95),      # centred over MQ11
          fontsize=LEGEND_FS, frameon=True, facecolor="white",
          edgecolor="none", framealpha=1, handlelength=1.8,
          handleheight=1.6)

plt.tight_layout()
plt.savefig("time_breakdown_revised.png")
print("Saved time_breakdown_revised.png")