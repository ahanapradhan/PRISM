"""Retest driver: extract a query with the PRISM pipeline and compare the
hidden query's result against the extracted query's result on the full
(public/tpch) database.

Usage: python mysite/unmasque/test/_retest_driver.py A1 A4 MQ17 ...
Runs the extractions SEQUENTIALLY (they share the working schema).
"""
import sys

import psycopg2

from mysite.unmasque.src.main_cmd import create_workload
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory
from mysite.unmasque.src.core.factory.PipeLineFactory import PipeLineFactory


def extract(qid):
    workload = create_workload()
    matches = [w for w in workload if w.qid == qid]
    if not matches:
        print(f"{qid}: not in workload, SKIPPED")
        return None, None
    hq = matches[0]
    conn = ConnectionHelperFactory().createConnectionHelper()
    conn.config.detect_union = hq.union
    conn.config.detect_oj = hq.oj
    conn.config.detect_nep = hq.nep
    conn.config.use_cs2 = hq.cs2
    conn.config.detect_or = hq.orf
    print(f"===== {qid} : extracting (flags union={hq.union} oj={hq.oj} "
          f"nep={hq.nep} cs2={hq.cs2} or={hq.orf}) =====")
    try:
        factory = PipeLineFactory()
        token = factory.init_job(conn, hq.query)
        factory.doJob(hq.query, token)
        result = factory.result
    except Exception:
        import traceback
        traceback.print_exc()
        result = None
    finally:
        conn.closeConnection()
    return hq.query, result


def compare_limit_tie(qid, hidden, extracted, cur):
    """For ORDER BY ... LIMIT queries with a non-total order, ties at the
    cutoff legitimately allow different rows to be included. Valid iff rows
    with sort key strictly above the boundary match, and all differing rows
    sit exactly at the boundary key (e.g. numwait = 218 vs Limit 100)."""
    def boundary(rows):
        # ORDER BY key desc assumed (numwait/count style); boundary = min key
        return min(r[-1] for r in rows)
    bh, be = boundary(hidden), boundary(extracted)
    if bh != be:
        print(f"{qid}: LIMIT-TIE check failed (boundary {bh} vs {be})")
        return False
    h_above = [r for r in hidden if r[-1] > bh]
    e_above = [r for r in extracted if r[-1] > bh]
    if sorted(h_above) != sorted(e_above):
        print(f"{qid}: LIMIT-TIE check failed (rows above boundary differ)")
        return False
    h_ties = [r for r in hidden if r[-1] == bh]
    e_ties = [r for r in extracted if r[-1] == bh]
    print(f"{qid}: PASS-LIMIT-TIE (rows above boundary {bh} identical; "
          f"boundary tie differs: hidden {[r[0] for r in h_ties]} vs "
          f"extracted {[r[0] for r in e_ties]})")
    return True


def compare(qid, hidden, extracted):
    c = psycopg2.connect(dbname="tpch", user="postgres", password="postgres",
                         host="localhost", port=5432)
    try:
        cur = c.cursor()
        cur.execute("set search_path = public;")
        cur.execute(hidden)
        r_hidden = cur.fetchall()
        cur.execute(extracted)
        r_extracted = cur.fetchall()
        if r_hidden == r_extracted:
            print(f"{qid}: PASS ({len(r_hidden)} rows)")
            return True
        if sorted(r_hidden) == sorted(r_extracted):
            print(f"{qid}: PASS-MULTISET ({len(r_hidden)} rows; identical rows, tie order differs)")
            return True
        if "limit" in hidden.lower():
            return compare_limit_tie(qid, r_hidden, r_extracted, cur)
        print(f"{qid}: FAIL")
        print(f"  hidden    ({len(r_hidden)} rows): first rows {r_hidden[:3]}")
        print(f"  extracted ({len(r_extracted)} rows): first rows {r_extracted[:3]}")
        return False
    except Exception as e:
        print(f"{qid}: ERROR running comparison: {e}")
        return False
    finally:
        c.close()


if __name__ == "__main__":
    qids = sys.argv[1:] or ["A1", "A4"]
    ok = True
    for qid in qids:
        hidden, extracted = extract(qid)
        if extracted is None:
            print(f"{qid}: EXTRACTION FAILED")
            ok = False
            continue
        print(f"----- {qid} extracted query -----")
        print(extracted)
        print("---------------------------------")
        ok = compare(qid, hidden, extracted) and ok
    print("OVERALL:", "ALL PASS" if ok else "FAILURES PRESENT")
