#!/usr/bin/env python3

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

OUTPUT_FILE = Path("time_breakdown.png")

# If True: "Other" = Total - Restore DB - (VM + From + Where + NEP + OJ), i.e. all
# remaining time incl. time the profile does not attribute to any row.
# If False: "Other" = only the remaining profile rows (Projection, Group By,
# Aggregation, Order by, Limit, Corr. Sampling).
OTHER_FROM_TOTAL = False


def run(frm, uni, restore, vm, where, nep, oj, rest, total):
    """One profile table (seconds). `rest` = sum of the remaining profile rows."""
    return dict(frm=frm, uni=uni, restore=restore, vm=vm, where=where,
                nep=nep, oj=oj, rest=rest, total=total)


# Failed run excluded: MQ4 (union off, empty extraction).
# off = UNMASQUE (PRISM, union=False); on = PRISM (union=True)
RUNS = {
    "MQ1": {
        "off": [run(7.36, 0, 0.3, 4.77, 0.05, 0, 0, 0.18+0.07+0.05+0.03+1.27, 60.56)],
        "on":  [run(55.17, 0, 0.31, 4.82, 0.07, 0, 0.12, 0.2+0.06+0.04+0.05+1.31, 87.72)],
    },
    "MQ2": {
        "off": [run(0.24, 0, 0.1, 1.34, 0.16, 0, 0, 0.12+0.42+0.03+0.29+2.21, 51.74)],
        "on":  [run(46.14, 0, 2.35, 206.91, 0.13, 1.79, 0.03, 0.07+0.4+0.03+0.3+1.51, 292.99),
                run(47.48, 0, 2.32, 1.87, 0.17, 0, 0.04, 0.12+0.42+0.03+0.3+2.13, 61.66)],
    },
    "MQ3": {
        "off": [run(4.89, 0, 0.45, 6.46, 0.22, 0, 0, 0.22+0.33+0.05+0.17+2.47, 62.85)],
        "on":  [run(49.99, 0, 40.13, 6.12, 0.21, 0, 1.16, 0.17+0.31+0.02+0.18+2.48, 146.27),
                run(58.72, 0, 90.67, 7.21, 0.16, 0, 0.16, 0.17+0.33+0.03+0.17+2.42, 215.05)],
    },
    "MQ4": {
        "off": [run(0.75, 0, 0.09, 0.6, 0.05, 0, 0, 0.03+0.03+0+0.03+0.64, 48.8)],
        "on":  [run(48.92, 0, 2.85, 0.72, 0.05, 0, 0.06, 0.03+0.08+0+0.06+0.8, 81.78)],
    },
    "MQ5": {
        "off": [run(1.44, 0, 0.41, 22.13, 0.24, 0, 0, 0.23+0.81+0.05+0.16+2.72, 74.1)],
        "on":  [run(55.67, 0, 13.16, 42.84, 0.26, 0, 2.19, 0.22+0.87+0.06+0.15+3.34, 186.1),
                run(49.57, 0, 12.87, 51.79, 0.27, 0, 1.28, 0.21+0.85+0.05+0.16+2.79, 196.73)],
    },
    "MQ6": {
        "off": [run(1.7, 0, 0.3, 1.71, 0.08, 0, 0, 0.11+0.06+0+0.02+1.2, 52.09)],
        "on":  [run(56.57, 0, 0.31, 1.68, 0.09, 0, 0.11, 0.15+0.08+0.02+0.02+1.35, 84.77)],
    },
    "MQ10": {
        "off": [run(1.82, 0, 0.41, 10.97, 0.14, 0, 0, 0.17+0.48+0.03+0.29+1.98, 95.93)],
        "on":  [run(48.09, 0, 19.96, 10.89, 0.21, 0, 0.26, 0.18+0.47+0.04+0.38+2.37, 127.47)],
    },
    "MQ11": {
        "off": [run(0.37, 0, 0.05, 0.57, 0.08, 0, 0, 0.11+0.14+0.02+0.08+1.05, 48.02)],
        "on":  [run(66.75, 0, 1.52, 0.65, 0.07, 0, 0.04, 0.15+0.15+0.02+0.08+1.25, 75.46)],
    },
    "MQ17": {
        "off": [run(1.17, 0, 0.33, 3.09, 0.07, 0, 0, 0.06+0.14+0.02+0.02+1.53, 53.09)],
        "on":  [run(59.32, 0, 9.93, 4.44, 0.1, 0, 0.12, 0.05+0.16+0.01+0.02+1.54, 98.78)],
    },
    "MQ18": {
        "off": [run(0.09, 0, 0.45, 221.85, 0.09, 0, 0, 0.08+0.3+0.02+0.15+2.27, 271.33),
                run(0.1, 0, 0.46, 100.9, 0.11, 0, 0, 0.08+0.32+0.03+0.16+1.84, 150.62),
                run(0.08, 0, 0.41, 70.25, 0.09, 0, 0, 0.08+0.33+0.03+0.16+1.83, 121.72),
                run(0.08, 0, 0.46, 71.85, 0.08, 0, 0, 0.08+0.34+0.03+0.16+1.86, 122.99)],
        "on":  [run(52.24, 0, 10.87, 197.87, 0.1, 0, 0.25, 0.08+0.3+0.04+0.15+2.3, 312.37),
                run(47.13, 0, 11.09, 180.62, 0.12, 0, 0.14, 0.08+0.3+0.03+0.14+1.9, 305.98)],
    },
    "MQ21": {
        "off": [run(1.74, 0, 0.41, 4.4, 0.21, 0, 0, 0.18+0.77+0.05+0.19+3.68, 77.67)],
        "on":  [run(48.78, 0, 12.25, 5.4, 0.13, 0, 0.22, 0.07+0.43+0.02+0.1+2.28, 132.57)],
    },
}

# component -> (legend label, color)
COMPONENTS = [
    ("vm",    "DB Minimization", "#8A2BE2"),
    ("frm",   "From Clause (+ Union)", "#2CA6A4"),
    ("where", "Where Clause", "#F28E2B"),
    ("nep",   "NEP", "#D62728"),
    ("oj",    "Outer Join", "#E8C547"),
    ("other", "Others", "#B0B0B0"),
]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans"]


def breakdown(r):
    d = {
        "vm": r["vm"],
        "frm": r["frm"] + r["uni"],
        "where": r["where"],
        "nep": r["nep"],
        "oj": r["oj"],
    }
    if OTHER_FROM_TOTAL:
        d["other"] = r["total"] - r["restore"] - sum(d.values())
    else:
        d["other"] = r["rest"]
    return d


def avg_breakdown(runs):
    parts = [breakdown(r) for r in runs]
    return {k: float(np.mean([p[k] for p in parts])) for k, _, _ in COMPONENTS}


def main():
    labels = list(RUNS.keys())
    x = np.arange(len(labels))

    bar_width = 0.38
    modes = [
        ("off", -bar_width / 2, "", "UNMASQUE"),   # PRISM, union = False
        ("on", bar_width / 2, "///", "PRISM"),      # PRISM, union = True
    ]

    fig, ax = plt.subplots(figsize=(11, 4.4))

    for mode, offset, hatch, _ in modes:
        bottoms = np.zeros(len(labels))
        data = [avg_breakdown(RUNS[q][mode]) for q in labels]
        for key, _, color in COMPONENTS:
            vals = np.array([d[key] for d in data])
            ax.bar(
                x + offset, vals, width=bar_width, bottom=bottoms,
                color=color, edgecolor="black", linewidth=0.6, hatch=hatch,
            )
            bottoms += vals

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=15)
    ax.tick_params(axis="y", labelsize=16)
    ax.set_ylabel("Avg. Extraction Time (s)", fontsize=17)

    ax.grid(visible=True, axis="y", linestyle="-", linewidth=0.5, color="0.75")
    ax.set_axisbelow(True)
    ax.set_ylim(0, 330)

    comp_handles = [
        Patch(facecolor=c, edgecolor="black", linewidth=0.6, label=lab)
        for _, lab, c in COMPONENTS
    ]
    tex_handles = [
        Patch(facecolor="white", edgecolor="black", linewidth=0.6, hatch=h, label=lab)
        for _, _, h, lab in modes
    ]
    leg1 = ax.legend(handles=comp_handles, loc="upper left", ncol=3,
                     frameon=False, prop={"size": 12})
    ax.add_artist(leg1)
    ax.legend(handles=tex_handles, loc="upper right", ncol=1,
              frameon=False, prop={"size": 12}, handleheight=1.6, handlelength=2.4)

    ax.autoscale(axis="x", tight=True)
    fig.tight_layout()
    fig.savefig(OUTPUT_FILE, format="png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"Created: {OUTPUT_FILE.resolve()}")
    print(f"{'Query':6} {'mode':6}" + "".join(f"{k:>8}" for k, _, _ in COMPONENTS) + "   total")
    for q in labels:
        for mode, _, _, name in modes:
            d = avg_breakdown(RUNS[q][mode])
            print(f"{q:6} {name[:6]:6}" + "".join(f"{d[k]:8.2f}" for k, _, _ in COMPONENTS)
                  + f"{sum(d.values()):8.2f}")


if __name__ == "__main__":
    main()