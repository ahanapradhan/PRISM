#!/usr/bin/env python3
"""
Control experiments for the OJ scalability figure: is the jump at OJ5 caused by PRISM, or by the cost of executing
the hidden join chain? Four chain variants separate the two factors (join type x fan-out):

    OJ   LEFT OUTER chain, lineitem joined on  p_partkey = l_partkey               (your workload; fan-out x4)
    IJ   INNER JOIN chain, same joins                                              (same result rows, no outer join)
    OJN  LEFT OUTER chain, lineitem joined on  p_partkey = l_partkey AND ps_suppkey = l_suppkey   (no fan-out)
    IJN  INNER JOIN chain, no fan-out

  * IJ spikes like OJ        -> the cost follows the join result size, not the outer-join extraction machinery.
  * OJN / IJN spike far less -> the fan-out (24M vs 6M result rows) is the cause.
  * seconds per step vs. chain result rows (panel c) lines up across ALL variants -> dose-response evidence.
OJ<k> for k < 5 are identical in all variants (no lineitem yet), so OJN/IJN only need k >= 5.

SUBCOMMANDS
  python oj_controls.py queries [--max-k 7] [--flags "False, False, False, False, False"]
        TestQuery lines for all variants (set --flags to the flag tuple your harness uses for OJ queries)
  python oj_controls.py cardinalities --tbl-dir DIR [--max-k 7]
        exact result rows of every chain on dbgen .tbl files (pure Python, no database) -> oj_chain_rows_SF1.csv
        (assumes TPC-H referential integrity: every lineitem has an order and a (part, supplier) pair in partsupp, ...)
  python oj_controls.py template
        writes oj_controls_results.csv: your measured OJ rows filled, all other cells empty -> fill in your runs
  python oj_controls.py plot [oj_controls_results.csv] [--rows-csv oj_chain_rows_SF1.csv] [--out oj_controls.png]
        (a) minimizer steps, (b) extraction time (s, log), (c) seconds per step vs chain result rows (log-log)
Results CSV columns: variant,k,steps,time_s   (empty cells are skipped; extra columns are ignored)
"""
import argparse
import csv
import os
import sys
from collections import Counter

OJ_SPEC = [("region", "r_name", None),
           ("nation", "n_name", "r_regionkey = n_regionkey"),
           ("supplier", "s_name", "n_nationkey = s_nationkey"),
           ("partsupp", "ps_availqty", "s_suppkey = ps_suppkey"),
           ("part", "p_name", "ps_partkey = p_partkey"),
           ("lineitem", "l_quantity", "p_partkey = l_partkey"),
           ("orders", "o_totalprice", "l_orderkey = o_orderkey"),
           ("customer", "c_name", "o_custkey = c_custkey")]
VARIANTS = {"OJ": (True, True), "IJ": (False, True), "OJN": (True, False), "IJN": (False, False)}  # (outer, fan-out)
STYLE = {"OJ": ("#3b75af", "o"), "IJ": ("#519e3e", "s"), "OJN": ("#ef8636", "^"), "IJN": ("#c03d3e", "D")}
DESC = {"OJ": "outer, fan-out", "IJ": "inner, fan-out", "OJN": "outer, no fan-out", "IJN": "inner, no fan-out"}

# your measured SF-1 readings for the OJ variant: k -> (steps, seconds)
MEASURED_OJ = {1: (11, 105), 2: (30, 133), 3: (54, 139), 4: (76, 131), 5: (115, 597), 6: (152, 961)}


# ------------------------------- queries ---------------------------------------
def chain_query(k, outer=True, fanout=True):
    sel = ", ".join(p for _, p, _ in OJ_SPEC[:k + 1])
    kw = "LEFT OUTER JOIN" if outer else "INNER JOIN"
    joins = ""
    for t, _, on in OJ_SPEC[1:k + 1]:
        if t == "lineitem" and not fanout:
            on += " AND ps_suppkey = l_suppkey"
        joins += f" {kw} {t} ON {on}"
    return f"SELECT {sel} FROM region{joins};"


def cmd_queries(a):
    for v, (outer, fan) in VARIANTS.items():
        print(f"# {v}: {DESC[v]}")
        for k in range(1, a.max_k + 1):
            if not fan and k < 5:
                continue                                    # identical to the fan-out variant
            print(f'TestQuery("{v}{k}",\n          "{chain_query(k, outer, fan)}",\n          {a.flags}),')
        print()


# ------------------------------- cardinalities ---------------------------------
def _rows(path):
    with open(path) as f:
        for line in f:
            yield line.rstrip("\n").split("|")


def cmd_cardinalities(a):
    d = a.tbl_dir
    nat_per_reg = Counter(int(r[2]) for r in _rows(os.path.join(d, "nation.tbl")))
    n_regions = sum(1 for _ in _rows(os.path.join(d, "region.tbl")))
    sup_per_nat = Counter(int(r[3]) for r in _rows(os.path.join(d, "supplier.tbl")))
    ps_per_supp, ps_pairs = Counter(), []
    for r in _rows(os.path.join(d, "partsupp.tbl")):
        pk, sk = int(r[0]), int(r[1]); ps_per_supp[sk] += 1; ps_pairs.append((pk, sk))
    li_part, li_pair = Counter(), Counter()
    with open(os.path.join(d, "lineitem.tbl")) as f:
        for line in f:
            x = line.split("|", 3); pk, sk = int(x[1]), int(x[2]); li_part[pk] += 1; li_pair[(pk, sk)] += 1

    out = []
    for v, (outer, fan) in VARIANTS.items():
        f = (lambda c: max(1, c)) if outer else (lambda c: c)
        rows = {1: sum(f(nat_per_reg.get(r, 0)) for r in range(n_regions)) if n_regions == 5 else sum(f(c) for c in nat_per_reg.values())}
        rows[2] = sum(f(c) for c in sup_per_nat.values()) if outer else sum(sup_per_nat.values())
        rows[3] = sum(f(c) for c in ps_per_supp.values())
        rows[4] = rows[3]                                   # every partsupp row has exactly one part
        cnt = (lambda pk, sk: li_part.get(pk, 0)) if fan else (lambda pk, sk: li_pair.get((pk, sk), 0))
        rows[5] = sum(f(cnt(pk, sk)) for pk, sk in ps_pairs)
        rows[6] = rows[7] = rows[5]                         # one order per lineitem, one customer per order
        for k in range(1, a.max_k + 1):
            out.append((v, k, rows[k]))
    with open("oj_chain_rows_SF1.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["variant", "k", "result_rows"]); w.writerows(out)
    print("result rows of the join chains (SF 1):")
    print(f"{'#OJs':>5} " + " ".join(f"{v:>12}" for v in VARIANTS))
    for k in range(1, a.max_k + 1):
        print(f"{k:5d} " + " ".join(f"{[r for (vv, kk, r) in out if vv == v and kk == k][0]:12,d}" for v in VARIANTS))
    print("\nwrote oj_chain_rows_SF1.csv")


# ------------------------------- template / plot -------------------------------
def cmd_template(a):
    with open("oj_controls_results.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["variant", "k", "steps", "time_s"])
        for v, (_, fan) in VARIANTS.items():
            for k in range(1, 8):
                if not fan and k < 5:
                    continue
                s, t = MEASURED_OJ.get(k, ("", "")) if v == "OJ" else ("", "")
                w.writerow([v, k, s, t])
    print("wrote oj_controls_results.csv (OJ rows 1-6 = your measurements; fill in the rest)")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cmd_plot(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, NullFormatter
    with open(a.csv, newline="") as f:
        data = {}
        for r in csv.DictReader(f):
            s, t = _num(r.get("steps")), _num(r.get("time_s"))
            if t is not None or s is not None:
                data.setdefault(r["variant"], {})[int(r["k"])] = (s, t)
    rows = {}
    if a.rows_csv and os.path.exists(a.rows_csv):
        with open(a.rows_csv, newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["variant"], int(r["k"]))] = float(r["result_rows"])
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
    for v in VARIANTS:
        if v not in data:
            continue
        col, mk = STYLE[v]
        # NOFAN variants share k<5 with their fan-out twin
        pts = dict(data[v])
        if v in ("OJN", "IJN"):
            for k, val in data.get("OJ" if v == "OJN" else "IJ", {}).items():
                if k < 5:
                    pts.setdefault(k, val)
        ks = sorted(pts)
        kw = dict(color=col, marker=mk, linewidth=3, markersize=8, label=f"{v} ({DESC[v]})")
        sx = [(k, pts[k][0]) for k in ks if pts[k][0] is not None]
        tx = [(k, pts[k][1]) for k in ks if pts[k][1] is not None]
        if sx: axes[0].plot(*zip(*sx), **kw)
        if tx: axes[1].plot(*zip(*tx), **kw)
        pr = [(rows[(v, k)], pts[k][1] / pts[k][0]) for k in ks
              if (v, k) in rows and pts[k][0] and pts[k][1]]
        if pr: axes[2].plot(*zip(*pr), linestyle="none", **{x: y for x, y in kw.items() if x != "linewidth"})
    axes[0].set_ylabel("Minimizer steps"); axes[1].set_ylabel("Extraction time (s)")
    axes[1].set_yscale("log")
    axes[1].yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}")); axes[1].yaxis.set_minor_formatter(NullFormatter())
    axes[2].set_xscale("log"); axes[2].set_yscale("log")
    axes[2].yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}")); axes[2].yaxis.set_minor_formatter(FuncFormatter(lambda x, _: f"{x:g}"))
    axes[2].set_xlabel("Join result rows (SF 1)"); axes[2].set_ylabel("Seconds per step")
    for ax in axes[:2]:
        ax.set_xlabel("# OJs"); ax.set_xticks(range(1, 8))
    for ax in axes:
        ax.tick_params(axis="both", labelsize=14); ax.xaxis.label.set_size(16); ax.yaxis.label.set_size(16)
        ax.grid(True, alpha=0.3)
    axes[0].legend(fontsize=10, loc="upper left")
    plt.tight_layout(); plt.savefig(a.out, dpi=200)
    print("saved", a.out, "| variants plotted:", [v for v in VARIANTS if v in data])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("queries"); p.add_argument("--max-k", type=int, default=7)
    p.add_argument("--flags", default="False, False, False, False, False"); p.set_defaults(fn=cmd_queries)
    p = sub.add_parser("cardinalities"); p.add_argument("--tbl-dir", required=True); p.add_argument("--max-k", type=int, default=7)
    p.set_defaults(fn=cmd_cardinalities)
    p = sub.add_parser("template"); p.set_defaults(fn=cmd_template)
    p = sub.add_parser("plot"); p.add_argument("csv", nargs="?", default="oj_controls_results.csv")
    p.add_argument("--rows-csv", default="oj_chain_rows_SF1.csv"); p.add_argument("--out", default="oj_controls.png")
    p.set_defaults(fn=cmd_plot)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
