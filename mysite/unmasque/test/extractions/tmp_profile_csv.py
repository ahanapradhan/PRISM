#!/usr/bin/env python3
"""Child runner: execute one main_cmd workload query and dump its stage timings.

Invoked by tmp_run_matrix.py, one fresh process per query. Prints a single
machine-readable line prefixed with PROFILE_JSON: at the end of a run.
"""
import json
import sys

# (ElapsedTime attribute, CSV column name)
STAGES = [
    ("t_init", "t_init"),
    ("t_from_clause", "t_from_clause"),
    ("t_union", "t_union"),
    ("t_db_restore", "t_restore_db"),
    ("t_sampling", "t_correlated_sampling"),
    ("t_view_min", "t_view_minimization"),
    ("t_where_clause", "t_where_clause"),
    ("t_projection", "t_projection"),
    ("t_groupby", "t_group_by"),
    ("t_aggregate", "t_aggregation"),
    ("t_orderby", "t_order_by"),
    ("t_limit", "t_limit"),
    ("t_outer_join", "t_outer_join"),
    ("t_nep", "t_nep"),
    ("t_result_comp", "t_result_comparator"),
]


def build_workload():
    """The exact workload built by main_cmd.py, including generated queries."""
    from mysite.unmasque.src.main_cmd import build_workload as main_cmd_workload

    return {q.qid: q for q in main_cmd_workload()}


def main():
    qid = sys.argv[1]
    hq = build_workload()[qid]

    from mysite.unmasque.src.core.factory.PipeLineFactory import PipeLineFactory
    from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory

    conn = ConnectionHelperFactory().createConnectionHelper()
    # Requested run configuration: all advanced extractors forced on, CS2 off.
    conn.config.detect_union = True
    conn.config.detect_oj = True
    conn.config.detect_nep = True
    conn.config.use_cs2 = False
    conn.config.detect_or = True
    conn.config.backup_method = "native"
    conn.config.minimizer = "hybrid" if "lineitem" in hq.query.lower() else "view"

    print(hq.query)
    print(f"Flags: union={conn.config.detect_union} oj={conn.config.detect_oj} "
          f"nep={conn.config.detect_nep} cs2={conn.config.use_cs2} "
          f"orf={conn.config.detect_or} minimizer={conn.config.minimizer} "
          f"backup={conn.config.backup_method}")

    pipeline = None
    try:
        factory = PipeLineFactory()
        token = factory.init_job(conn, hq.query)
        factory.doJob(hq.query, token)
        pipeline = factory.get_pipeline_obj(token)
    except Exception as exc:
        payload = {
            "error": f"{type(exc).__name__}: {exc}",
            "cs2": False,
            "union": True,
            "oj": True,
            "nep": True,
            "orf": True,
            "minimizer": conn.config.minimizer,
        }
        print("PROFILE_JSON:" + json.dumps(payload))
        return 1

    result = factory.result
    if result is None or not str(result).strip():
        payload = {
            "error": "pipeline returned no/empty result",
            "cs2": False,
            "union": True,
            "oj": True,
            "nep": True,
            "orf": True,
            "minimizer": conn.config.minimizer,
            "correct": bool(getattr(pipeline, "correct", False)),
        }
        print("PROFILE_JSON:" + json.dumps(payload))
        return 1

    print("=========== Extracted Query =============")
    print(result)

    profile = pipeline.time_profile
    payload = {col: round(getattr(profile, attr), 3) for attr, col in STAGES}
    payload["prism_total"] = round(profile.get_prism_total(), 3)
    payload["wall_clock"] = round(profile.get_wall_clock_total(), 3)
    payload["t_backup_excluded"] = round(profile.t_backup, 3)
    payload["cs2"] = False
    payload["union"] = True
    payload["oj"] = True
    payload["nep"] = True
    payload["orf"] = True
    payload["minimizer"] = conn.config.minimizer
    payload["correct"] = bool(getattr(pipeline, "correct", False))
    print("PROFILE_JSON:" + json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
