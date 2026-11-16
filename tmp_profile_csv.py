#!/usr/bin/env python3
"""Child runner: execute one PRISM workload query and dump its stage timings as JSON.

Invoked by tmp_run_matrix.py, one fresh process per query. Prints a single
machine-readable line prefixed with PROFILE_JSON: at the end of a successful run.
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
    """create_workload() plus the DS1..DS10 / UK2..UK8 queries added after its return."""
    from mysite.unmasque.src.main_cmd import (
        TestQuery, create_workload, disj_str_query, fixed_aux_query, FA_SPLITS)

    workload = {q.qid: q for q in create_workload()}
    for k in range(1, 11):
        qid = f"DS{k}"
        workload[qid] = TestQuery(qid, disj_str_query(k), False, False, False, False, True)
    for k in FA_SPLITS:
        qid = f"UK{k}"
        workload[qid] = TestQuery(qid, fixed_aux_query(k), False, True, False, False)
    return workload


def main():
    qid = sys.argv[1]
    hq = build_workload()[qid]

    from mysite.unmasque.src.core.factory.PipeLineFactory import PipeLineFactory
    from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory

    conn = ConnectionHelperFactory().createConnectionHelper()
    conn.config.detect_union = hq.union
    conn.config.detect_oj = hq.oj
    conn.config.detect_nep = hq.nep
    conn.config.use_cs2 = hq.cs2
    conn.config.detect_or = hq.orf

    print(hq.query)
    print(f"Flags: union={hq.union} oj={hq.oj} nep={hq.nep} cs2={hq.cs2} orf={hq.orf}")

    factory = PipeLineFactory()
    token = factory.init_job(conn, hq.query)
    factory.doJob(hq.query, token)

    if factory.result is None or not str(factory.result).strip():
        print("PROFILE_JSON:" + json.dumps({"error": "pipeline returned no/empty result"}))
        return 1

    print("=========== Extracted Query =============")
    print(factory.result)

    profile = factory.get_pipeline_obj(token).time_profile
    payload = {col: round(getattr(profile, attr), 3) for attr, col in STAGES}
    payload["prism_total"] = round(profile.get_prism_total(), 3)
    payload["wall_clock"] = round(profile.get_wall_clock_total(), 3)
    payload["t_backup_excluded"] = round(profile.t_backup, 3)
    payload["cs2"] = bool(hq.cs2)
    payload["union"] = bool(hq.union)
    payload["oj"] = bool(hq.oj)
    payload["nep"] = bool(hq.nep)
    payload["orf"] = bool(hq.orf)
    print("PROFILE_JSON:" + json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
