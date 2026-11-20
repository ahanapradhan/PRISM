"""Plot wall-clock (per iteration and cumulative) from HybridExperiment CSVs.

Usage:
  python3 mysite/unmasque/test/native_test/plot_hybrid_wallclock.py [--tag TAG] [--query MQ2] [--results-dir DIR]

Reads hybrid_wallclock_iterations_<tag>_<query>.csv (or matching files) and
produces wall-clock plots: per-iteration time and cumulative time vs iteration.
Plan cost is not plotted.
"""
import argparse
import csv
import glob
import os
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLORS = {
    "CopyBasedMinimizer": "tab:orange",
    "ViewMinimizer": "tab:blue",
    "PKViewMinimizer": "tab:green",
    "HybridMinimizer": "tab:red",
}


def load_iterations_csv(path):
    # rows: minimizer, run, iteration, wallclock_s, cumulative_s, winner_arm
    data = defaultdict(lambda: defaultdict(list))  # minimizer -> run -> [(it, wall, cum)]
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            name = row["minimizer"]
            run = int(row["run"])
            it = int(row["iteration"])
            wall = float(row["wallclock_s"]) if row.get("wallclock_s") else 0.0
            cum = float(row["cumulative_s"]) if row.get("cumulative_s") else 0.0
            data[name][run].append((it, wall, cum))
    for name in data:
        for run in data[name]:
            data[name][run].sort()
    return data


def plot(data, title, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # per-iteration wall-clock
    ax = axes[0]
    for name, runs in data.items():
        color = COLORS.get(name)
        for run, series in sorted(runs.items()):
            xs = [p[0] for p in series]
            ys = [p[1] for p in series]
            ax.plot(xs, ys, color=color, alpha=0.35, linewidth=1)
        # mean
        if runs:
            maxlen = max(len(s) for s in runs.values())
            mx, my = [], []
            for i in range(maxlen):
                vals = []
                it = None
                for s in runs.values():
                    if i < len(s):
                        it = s[i][0]
                        vals.append(s[i][1])
                if vals:
                    mx.append(it)
                    my.append(sum(vals) / len(vals))
            ax.plot(mx, my, color=color, linewidth=2, label=f"{name} (mean)")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Wall-clock time (s)")
    ax.set_title("Per-iteration wall-clock")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    # cumulative wall-clock
    ax = axes[1]
    for name, runs in data.items():
        color = COLORS.get(name)
        for run, series in sorted(runs.items()):
            xs = [p[0] for p in series]
            ys = [p[2] for p in series]
            ax.plot(xs, ys, color=color, alpha=0.35, linewidth=1)
        if runs:
            maxlen = max(len(s) for s in runs.values())
            mx, my = [], []
            for i in range(maxlen):
                vals = []
                it = None
                for s in runs.values():
                    if i < len(s):
                        it = s[i][0]
                        vals.append(s[i][2])
                if vals:
                    mx.append(it)
                    my.append(sum(vals) / len(vals))
            ax.plot(mx, my, color=color, linewidth=2, label=f"{name} (mean)")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Cumulative wall-clock (s)")
    ax.set_title("Cumulative wall-clock")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=None)
    ap.add_argument("--tag", default=None, help="e.g. 1rep_3runs_expt1_MQ2 (or substring)")
    ap.add_argument("--query", default=None, help="e.g. MQ2 (used to find matching files)")
    args = ap.parse_args()

    base = Path(__file__).parent / "results" / "csv"
    if args.results_dir:
        base = Path(args.results_dir)
    pattern = str(base / "hybrid_wallclock_iterations_*.csv")
    files = sorted(glob.glob(pattern))
    if args.tag:
        files = [f for f in files if args.tag in f]
    if args.query:
        files = [f for f in files if args.query in f]
    if not files:
        print(f"no matching iteration CSVs found for pattern {pattern}")
        return
    for path in files:
        data = load_iterations_csv(path)
        name = Path(path).stem.replace("hybrid_wallclock_iterations_", "")
        out = Path(path).parent.parent / f"plot_hybrid_wallclock_{name}.png"
        plot(data, f"Wall-clock per iteration and cumulative ({name})", out)


if __name__ == "__main__":
    main()
