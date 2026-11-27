"""Cold-cache wall-clock experiment for Copy/View/PK/Hybrid minimizers (rev 2).

Measures all 4 minimizer techniques (expt1, including PK minimizer) on
MQ2, MQ3, MQ5, MQ18 with 1 probe per halving round and configurable cold-cache
runs per minimizer (default 3). Hybrid uses default arms [view, copy] (PK off).

Metric: total wall-clock of the whole run (end-to-end). Plots per iteration and
cumulative wall-clock; no plan cost.
"""
import csv
import json
import os
import statistics
import time
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402

from .copy_based_minimizer import CopyBasedMinimizer  # noqa: E402
from .view_minimizer import ViewMinimizer  # noqa: E402
from .pk_view_minimizer import PKViewMinimizer  # noqa: E402
from .hybrid_minimizer import HybridMinimizer  # noqa: E402

from .CopyBasedMinimizerExperiment import MQ_QUERIES, RESULTS_DIR, CSV_DIR  # noqa: E402
from . import CopyBasedMinimizerExperiment as _cbme_mod  # noqa: E402

DEFAULT_RUNS = 3
DEFAULT_REPEATS = 1  # 1 probe per halving round

QUERIES = ["MQ2", "MQ3", "MQ5", "MQ18"]

# expt1 order including PK minimizer, plus Hybrid as 4th technique
MINIMIZERS = (
    ("CopyBasedMinimizer", CopyBasedMinimizer, "copy"),
    ("ViewMinimizer", ViewMinimizer, "view"),
    ("PKViewMinimizer", PKViewMinimizer, "view"),
    ("HybridMinimizer", HybridMinimizer, "hybrid"),
)

COLORS = {
    "CopyBasedMinimizer": "tab:orange",
    "ViewMinimizer": "tab:blue",
    "PKViewMinimizer": "tab:green",
    "HybridMinimizer": "tab:red",
}

WIN_COLORS = {
    "view": "tab:blue",
    "copy": "tab:orange",
    "pk": "tab:green",
    "error": "tab:gray",
}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _median(vals):
    return statistics.median(vals) if vals else 0.0


class HybridExperiment(_cbme_mod.CopyBasedMinimizerExperiment):
    """Measure 4 minimization techniques (total wall-clock, cold-cache)."""

    def setUp(self):
        super().setUp()
        self.runs = _env_int("HYBRID_RUNS", _env_int("PRISM_MQ_RUNS", DEFAULT_RUNS))
        self.repeats = _env_int("HYBRID_REPEATS", DEFAULT_REPEATS)
        self.queries = [q.strip() for q in os.environ.get("HYBRID_MQ_IDS", ",".join(QUERIES)).split(",") if q.strip()]
        self.expt_name = "expt1"

    # ------------------------------------------------------------------ helpers
    def _iter_wall_series(self, timings):
        """Return list of (iteration, wall_s) in iteration order for one run."""
        by_iter = {}
        for r in timings:
            it = r.get("iteration")
            val = r.get("with_overhead_s", r.get("exec_only_s"))
            if it is None or val is None:
                continue
            by_iter.setdefault(it, []).append(float(val))
        series = []
        for it in sorted(by_iter):
            vals = by_iter[it]
            series.append((it, vals[0] if len(vals) == 1 else sum(vals) / len(vals)))
        return series

    # ------------------------------------------------------------------ plotting (wall-clock only, rev 2)
    def _plot_wallclock(self, per_query_results, query_id):
        tag = f"{self.repeats}rep_{self.runs}runs_{self.expt_name}_{query_id}"

        # Figure: (a) total per run dots+median; (b) cumulative per run; (c) winner strip for hybrid
        fig = plt.figure(figsize=(15, 8))
        gs = GridSpec(2, 2, height_ratios=[3, 0.5], hspace=0.35, wspace=0.3)
        ax_tot = fig.add_subplot(gs[0, 0])
        ax_cum = fig.add_subplot(gs[0, 1])
        ax_strip = fig.add_subplot(gs[1, 1])

        names = list(per_query_results.keys())

        # (a) total wall-clock per query: one dot per run with median marked
        for i, name in enumerate(names):
            color = COLORS.get(name)
            runs = per_query_results[name]["runs"]
            vals = [r["total_s"] for r in runs]
            xs = [i + (j - (len(vals) - 1) / 2) * 0.06 for j in range(len(vals))]
            ax_tot.scatter(xs, vals, color=color, alpha=0.8, zorder=3, label=name)
            med = _median(vals)
            ax_tot.hlines(med, i - 0.25, i + 0.25, colors=color, linewidth=3, zorder=4)
            ax_tot.text(i + 0.28, med, f"{med:.2f}s", va="center", fontsize=8, color=color)
        ax_tot.set_xticks(range(len(names)))
        ax_tot.set_xticklabels([n.replace("Minimizer", "") for n in names], rotation=20, ha="right")
        ax_tot.set_ylabel("Total wall-clock (s)")
        ax_tot.set_title(f"(a) Total wall-clock per run + median ({query_id})")
        ax_tot.grid(True, axis="y", alpha=0.3)
        ax_tot.legend(fontsize=7, loc="upper right")

        # (b) cumulative wall-clock vs iteration, one line per run
        for name in names:
            color = COLORS.get(name)
            for ri, run in enumerate(per_query_results[name]["runs"]):
                series = run.get("series") or []
                if not series:
                    continue
                xs = [p[0] for p in series]
                cum = []
                s = 0.0
                for _, w in series:
                    s += w
                    cum.append(s)
                ax_cum.plot(xs, cum, color=color, alpha=0.6, linewidth=1.2,
                            label=name if ri == 0 else None)
        ax_cum.set_xlabel("Iteration")
        ax_cum.set_ylabel("Cumulative wall-clock (s)")
        ax_cum.set_title(f"(b) Cumulative wall-clock vs iteration ({query_id})")
        ax_cum.grid(True, alpha=0.3)
        ax_cum.legend(fontsize=7, loc="upper left")

        # (c) strip under (b): winning arm per iteration for Hybrid (first run shown / all runs stacked)
        hybrid = per_query_results.get("HybridMinimizer")
        if hybrid and hybrid["runs"]:
            # show winner strips for each hybrid run stacked
            n_runs = len(hybrid["runs"])
            for ri, run in enumerate(hybrid["runs"]):
                winners = run.get("winner_arms") or []
                if not winners:
                    continue
                # winners: list of (iteration, arm)
                for it, arm in winners:
                    ax_strip.barh(ri, 1.0, left=it - 0.5, height=0.8,
                                  color=WIN_COLORS.get(arm, "tab:gray"), edgecolor="none")
            ax_strip.set_yticks(range(len(hybrid["runs"])))
            ax_strip.set_yticklabels([f"run {i+1}" for i in range(len(hybrid["runs"]))], fontsize=8)
            ax_strip.set_xlabel("Iteration (winner arm)")
            ax_strip.set_title("(c) Hybrid winner arm per iteration", fontsize=9)
            # legend for arms present
            seen = set()
            for run in hybrid["runs"]:
                for _, arm in (run.get("winner_arms") or []):
                    seen.add(arm)
            handles = [plt.Line2D([0], [0], color=WIN_COLORS.get(a, "tab:gray"), lw=6, label=a)
                       for a in sorted(seen)]
            if handles:
                ax_strip.legend(handles=handles, fontsize=7, loc="upper right", ncol=max(1, len(handles)))
            # align x with cumulative axis
            ax_strip.set_xlim(ax_cum.get_xlim())
        else:
            ax_strip.axis("off")

        fig.suptitle(f"Hybrid wall-clock - {query_id} ({self.expt_name}, {self.runs} cold-cache runs, 1 probe/round)", fontsize=12)
        out = RESULTS_DIR / f"hybrid_wallclock_{tag}.png"
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"wrote {out}")

        # CSVs
        csv_path = CSV_DIR / f"hybrid_wallclock_{tag}.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["minimizer", "run", "total_wallclock_s", "iterations"])
            for name, data in per_query_results.items():
                for ri, run in enumerate(data["runs"], 1):
                    w.writerow([name, ri, round(run["total_s"], 4), len(run.get("series") or [])])
        print(f"wrote {csv_path}")

        it_csv = CSV_DIR / f"hybrid_wallclock_iterations_{tag}.csv"
        with open(it_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["minimizer", "run", "iteration", "wallclock_s", "cumulative_s", "winner_arm"])
            for name, data in per_query_results.items():
                for ri, run in enumerate(data["runs"], 1):
                    cum = 0.0
                    winners = {it: arm for it, arm in (run.get("winner_arms") or [])}
                    for it, ws in (run.get("series") or []):
                        cum += ws
                        w.writerow([name, ri, it, round(ws, 6), round(cum, 6), winners.get(it, "")])
        print(f"wrote {it_csv}")

        # hybrid detailed log dump (JSONL copy) per query
        for name, data in per_query_results.items():
            for ri, run in enumerate(data["runs"], 1):
                logs = run.get("hybrid_iter_logs")
                if logs:
                    p = CSV_DIR / f"hybrid_race_log_{tag}_{name}_run{ri}.jsonl"
                    with open(p, "w", encoding="utf-8") as f:
                        for rec in logs:
                            f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
                    print(f"wrote {p}")

        return out

    # ------------------------------------------------------------------ run
    def _run_one(self, cls, mode, all_sizes, run, query_id):
        minimizer = cls(self.conn, self.core_tables, all_sizes, False)
        minimizer.repeats = self.repeats
        t0 = time.perf_counter()
        ok = minimizer.doJob(self.query)
        end_to_end = time.perf_counter() - t0
        if not ok:
            raise AssertionError(f"{query_id} {cls.__name__} failed")
        timings = list(getattr(minimizer, "timing_records", []) or [])
        for r in timings:
            r["run"] = run
        series = self._iter_wall_series(timings)
        total_wall = end_to_end  # authoritative total wall-clock of whole run

        # hybrid extras
        winner_arms = []
        hybrid_iter_logs = None
        if hasattr(minimizer, "hybrid_logs") and minimizer.hybrid_logs:
            hybrid_iter_logs = []
            for log in minimizer.hybrid_logs:
                # log may be IterLog dataclass
                try:
                    rec = {
                        "iter": log.iter,
                        "candidate_size": log.candidate_size,
                        "winner_arm": log.winner_arm,
                        "outcome": log.outcome,
                        "wall_time_s": round(log.wall_time_s, 6),
                        "arms": {a: {"status": r.status, "elapsed_s": round(r.elapsed_s, 6),
                                     **({"error": r.error} if r.error else {})}
                                 for a, r in log.arms.items()},
                    }
                except Exception:
                    rec = {"raw": str(log)}
                hybrid_iter_logs.append(rec)
                if hasattr(log, 'iter') and hasattr(log, 'winner_arm'):
                    winner_arms.append((log.iter, log.winner_arm))

        return {
            "total_s": float(total_wall),
            "series": series,
            "iterations": getattr(minimizer, "iteration", len(series)),
            "timings": timings,
            "winner_arms": winner_arms,
            "hybrid_iter_logs": hybrid_iter_logs,
        }

    def _run_query(self, query_id):
        self.configure_query(query_id)
        print(f"\n=== HybridExperiment {self.expt_name} {query_id}: minimizers {[m[0] for m in MINIMIZERS]} runs={self.runs} repeats={self.repeats} ===")
        per_min = {}
        for name, cls, mode in MINIMIZERS:
            per_min[name] = {"runs": []}
            for run in range(1, self.runs + 1):
                all_sizes = self._prepare_working_schema()
                self._restart_database()
                res = self._run_one(cls, mode, all_sizes, run, query_id)
                per_min[name]["runs"].append(res)
                print(f"{query_id} {self.expt_name} run {run}/{self.runs}: {name} total_wall={res['total_s']:.3f}s iterations={res['iterations']}", flush=True)
        self._plot_wallclock(per_min, query_id)
        # summary
        print(f"--- {query_id} summary (median/mean total wall-clock s) ---")
        for name, data in per_min.items():
            vals = [r['total_s'] for r in data['runs']]
            med = _median(vals)
            mean = sum(vals) / len(vals) if vals else 0.0
            print(f"  {name}: runs={[round(v,3) for v in vals]} median={med:.3f}s mean={mean:.3f}s")
        return per_min

    def test_do(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        all_results = {}
        for q in self.queries:
            if q not in MQ_QUERIES:
                print(f"skip unknown query {q}")
                continue
            all_results[q] = self._run_query(q)
        # overall summary CSV
        tag = f"{self.repeats}rep_{self.runs}runs_{self.expt_name}"
        out = CSV_DIR / f"hybrid_wallclock_summary_{tag}.csv"
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["query", "minimizer", "run", "total_wallclock_s", "iterations"])
            for q, per_min in all_results.items():
                for name, data in per_min.items():
                    for ri, run in enumerate(data["runs"], 1):
                        w.writerow([q, name, ri, round(run["total_s"], 4), run["iterations"]])
        print(f"wrote {out}")
        self.assertTrue(all_results, "no queries executed")


if __name__ == "__main__":
    unittest.main()
