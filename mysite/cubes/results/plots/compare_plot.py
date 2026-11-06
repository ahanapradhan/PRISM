import math
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

# Match the Helvetica-style gnuplot rendering in the reference figure.
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Liberation Sans", "Arial"],
    "font.size": 16,
    "axes.labelsize": 22,
    "xtick.labelsize": 16,
    "ytick.labelsize": 18,
    "legend.fontsize": 17,
    "axes.linewidth": 1.25,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,
    "xtick.major.size": 6,
    "ytick.major.size": 6,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

# All timing values are elapsed wall-clock minutes from query_results.md.
# PRISM entries are entered in seconds and converted to minutes; None is plotted as NA.
QUERY_ORDER = [
    "DS1", "DS2", "DS3",
    "NEP1_a", "NEP2_a", "NEP3_a",
    "OJ1", "OJ2", "OJ3",
    "UK3", "UK_a", "UN3", "UN_a",
]

PRISM_DATA = {
    "DS1": {"prism_basic": 0.58/60.0, "prism": 0.66/60.0},
    "OJ1": {"prism_basic": 0.63 / 60.0, "prism": 0.85 / 60.0},
    "OJ2": {"prism_basic": 0.90 / 60.0, "prism": 0.80 / 60.0},
    "OJ3": {"prism_basic": 0.88 / 60.0, "prism": 0.94 / 60.0},
}

# A completed candidate has a numeric time and correctness True/False/None.
# A stopped or failed run has time=None and status="TO".
# A variant not run separately has status="NA".
def run(mode, seconds=None, correct=None, status="ok", note=""):
    return {
        "mode": mode,
        "time": None if seconds is None else seconds / 60.0,
        "correct": correct,
        "status": status,
        "note": note,
    }

CUBES_RUNS = {
    "DS1": {
        "with_hints": [run("parallel", 1.856), run("sequential", 1.789)],
        "without_hints": [run("parallel", 1.838), run("sequential", 40.889)],
    },
    "DS2": {
        "with_hints": [run("parallel", 1.827), run("sequential", 2.465)],
        "without_hints": [run("parallel", 1.919), run("sequential", 40.826)],
    },
    "DS3": {
        "with_hints": [run("parallel", 7.042), run("sequential", 15.323)],
        "without_hints": [run("parallel", 1.891), run("sequential", 40.826)],
    },
    "NEP1_a": {
        "with_hints": [run("parallel", 1.753, True), run("sequential", 2.076, True)],
        "without_hints": [
            run("parallel", None, None, "TO", "stopped at 10m24.294s"),
            run("sequential", None, None, "TO", "stopped at 9m48.189s"),
        ],
    },
    "NEP2_a": {
        "with_hints": [
            run("parallel", 3.266, False),
            run("sequential", 4.717, True),
        ],
        "without_hints": [
            run("parallel", None, None, "TO", "stopped at 22m8.161s"),
            run("sequential", None, None, "TO", "stopped at 7m39.206s"),
        ],
    },
    "NEP3_a": {
        "with_hints": [
            run("parallel", 140.569, False),
            run("sequential", 145.949, False),
        ],
        "without_hints": [
            run("parallel", None, None, "TO", "stopped at 5m5.233s"),
            run("sequential", None, None, "TO", "stopped at 13m0.042s"),
        ],
    },
    "OJ1": {
        "with_hints": [
            run("parallel", 29.455),
            run("sequential", None, None, "TO", "stopped at 11m18.597s"),
        ],
        "without_hints": [run("parallel", 3.701), run("sequential", 11.652)],
    },
    "OJ2": {
        "with_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
        "without_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
    },
    "OJ3": {
        "with_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
        "without_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
    },
    "UK3": {
        "with_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
        "without_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
    },
    "UK_a": {
        "with_hints": [
            run("parallel", None, None, "TO", "R found at 33.782s; SQL generation failed"),
            run("sequential", None, None, "TO"),
        ],
        "without_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
    },
    "UN3": {
        "with_hints": [run("parallel", None, None, "TO"), run("sequential", None, None, "TO")],
        "without_hints": [run(None, None, None, "NA", "not run separately; YAML identical to taskw")],
    },
    "UN_a": {
        "with_hints": [
            run("parallel", None, None, "TO", "R found at 1.796s; SQL generation failed"),
            run("sequential", None, None, "TO", "R found at 1.765s; SQL generation failed"),
        ],
        "without_hints": [run(None, None, None, "NA", "not run separately; YAML identical to taskw")],
    },
}

# Colors sampled/visually matched to the supplied gnuplot screenshot.
# UNMASQUE/CUBES violet, PRISM green, and PRISM_basic blue.
CUBES_VIOLET = "#8B16D1"
PRISM_BASIC_COLOR = "#6EADD8"
PRISM_COLOR = "#49A47A"
CORRECT_EDGE = "#16833B"
INCORRECT_EDGE = "#C62828"
PENDING_EDGE = "#111111"
WITH_HINTS_ALPHA = 1.0
WITHOUT_HINTS_ALPHA = 0.55


def choose_cubes_run(candidates):
    """Correctness first, then fastest completed extraction.

    Priority: correct > unknown > incorrect. Within a class, choose lower wall time.
    If no run completed, return TO; if the variant was not run, return NA.
    """
    completed = [r for r in candidates if r.get("time") is not None]
    if completed:
        rank = {True: 0, None: 0, False: 1}
        return min(completed, key=lambda r: (rank[r.get("correct")], r["time"]))
    if candidates and all(r.get("status") == "NA" for r in candidates):
        return {"time": None, "correct": None, "mode": None, "status": "NA"}
    return {"time": None, "correct": None, "mode": None, "status": "TO"}


def effective_correctness(correct):
    # Per requested visualization, pending/unknown cases are displayed as correct.
    return True if correct is None else correct


def correctness_style(correct):
    # Violet remains the base fill; dense colored hatching makes correctness prominent.
    if effective_correctness(correct):
        return CORRECT_EDGE, "////"
    return INCORRECT_EDGE, "\\\\"


def draw_missing(ax, x, label, color):
    # y uses axes coordinates so TO/NA always stays inside the plotting grid.
    ax.text(x, 0.018, label, transform=ax.get_xaxis_transform(), rotation=90,
            ha="center", va="bottom", fontsize=7.5, fontweight="bold",
            color=color, clip_on=True, zorder=5)


def draw_cubes(ax, x, width, selected, alpha):
    if selected.get("time") is None:
        label = selected.get("status", "NA")
        draw_missing(ax, x, label, "#D73027" if label == "TO" else "#777777")
        return
    edge, hatch = correctness_style(selected.get("correct"))
    # Base violet bar differentiates CUBES variants through opacity.
    ax.bar([x], [selected["time"]], width, color=CUBES_VIOLET,
           alpha=alpha, edgecolor="black", linewidth=0.65, zorder=3)
    # Transparent overlay adds strong green/red stripes without replacing violet.
    ax.bar([x], [selected["time"]], width, color="none",
           edgecolor=edge, linewidth=1.2, hatch=hatch, zorder=4)


def draw_prism(ax, x, width, value, color):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        draw_missing(ax, x, "NA", "#777777")
        return
    ax.bar([x], [value], width, color=color, edgecolor="black", linewidth=0.45, zorder=3)


def plot_comparison(output_stem="prism_vs_cubes_all_qids"):
    x = np.arange(len(QUERY_ORDER), dtype=float) * 0.82
    width = 0.095
    spacing = 0.115
    offsets = [-1.5 * spacing, -0.5 * spacing, 0.5 * spacing, 1.5 * spacing]
    fig, ax = plt.subplots(figsize=(12.5, 5.4))
    values = []

    for i, qid in enumerate(QUERY_ORDER):
        runs = CUBES_RUNS[qid]
        with_hints = choose_cubes_run(runs["with_hints"])
        without_hints = choose_cubes_run(runs["without_hints"])
        draw_cubes(ax, x[i] + offsets[0], width, with_hints, WITH_HINTS_ALPHA)
        draw_cubes(ax, x[i] + offsets[1], width, without_hints, WITHOUT_HINTS_ALPHA)
        values += [r["time"] for r in (with_hints, without_hints) if r.get("time") is not None]

        pdata = PRISM_DATA.get(qid, {})
        pb = pdata.get("prism_basic")
        pr = pdata.get("prism")
        draw_prism(ax, x[i] + offsets[2], width, pb, PRISM_BASIC_COLOR)
        draw_prism(ax, x[i] + offsets[3], width, pr, PRISM_COLOR)
        values += [v for v in (pb, pr) if v is not None]

    ymax = max(values, default=1.0)
    positive = [v for v in values if v is not None and v > 0]
    ymin = min(positive, default=1e-3)
    ax.set_yscale("log")
    ax.set_ylim(10 ** math.floor(math.log10(ymin)),
                10 ** math.ceil(math.log10(ymax * 1.35)))
    ax.set_ylabel("Extraction Time (m)")
    ax.set_xticks(x)
    ax.set_xticklabels(QUERY_ORDER, rotation=28, ha="right", rotation_mode="anchor")
    ax.set_xlim(x[0] - 0.42, x[-1] + 0.42)
    ax.margins(x=0.0)
    ax.grid(axis="y", linestyle=":", linewidth=0.9, color="#777777", alpha=0.85)
    ax.set_axisbelow(True)

    method_legend = ax.legend(handles=[
        Patch(facecolor=CUBES_VIOLET, alpha=WITH_HINTS_ALPHA, edgecolor="black", label="CUBES, with hints"),
        Patch(facecolor=CUBES_VIOLET, alpha=WITHOUT_HINTS_ALPHA, edgecolor="black", label="CUBES, without hints"),
        Patch(facecolor=PRISM_BASIC_COLOR, edgecolor="none", label=r"PRISM$_{basic}$"),
        Patch(facecolor=PRISM_COLOR, edgecolor="none", label="PRISM"),
    ], loc="upper left", ncol=4, frameon=False, columnspacing=1.55, handlelength=2.2,
       bbox_to_anchor=(0.0, 1.0))
    ax.add_artist(method_legend)
    ax.legend(handles=[
        Patch(facecolor=CUBES_VIOLET, edgecolor=CORRECT_EDGE, hatch="////", linewidth=1.2,
              label="CUBES correct"),
        Patch(facecolor=CUBES_VIOLET, edgecolor=INCORRECT_EDGE, hatch="\\\\", linewidth=1.2,
              label="CUBES incorrect"),
    ], loc="upper right", bbox_to_anchor=(0.995, 0.80), frameon=False, fontsize=13)


    # Gnuplot-like clean frame.
    for spine in ax.spines.values():
        spine.set_color("black")
        spine.set_linewidth(1.25)


    fig.subplots_adjust(left=0.075, right=0.992, top=0.985, bottom=0.155)
    fig.savefig(output_stem + ".png", dpi=300, bbox_inches="tight")
    fig.savefig(output_stem + ".pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plot_comparison("prism_vs_cubes_logscale_striped")
