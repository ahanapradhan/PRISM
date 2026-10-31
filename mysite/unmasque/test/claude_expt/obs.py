#!/usr/bin/env python3
"""
Observability-boundary experiment for UNMASQUE-II on TPC-H (PostgreSQL only).

WHAT THIS EXPERIMENT TESTS
  Each observability condition (for NEPs and outer joins) is tested with PAIRED
  databases that differ ONLY in the witness tuples the condition asks for:
    H1 (sufficiency): when the condition holds, UNMASQUE-II extracts a query
        equivalent to the hidden query QH.
    H2 (tightness):   when the condition is violated by the minimal change,
        extraction fails in the predicted way (construct missing / spurious),
        and the failure is explained by D: QE and QH either agree on D (the
        construct is invisible) or disagree on D without being resolvable.
  A violated-condition run that is still exact means the condition is not
  necessary; a satisfied-condition run that is not exact means it is not
  sufficient. Either outcome is a result about the condition, not a bug.

WHAT THE SCRIPT DOES (no manual steps)
  1. Copies the 8 TPC-H tables from SOURCE_SCHEMA into a NEW silo schema.
     The source schema is only ever READ.
  2. For each run: rebuilds the silo, applies the database variant, checks by
     SQL that the variant is non-vacuous, obtains QE from UNMASQUE-II
     (see INTEGRATION POINTS), then compares QE with QH on the variant and on
     the full (unmodified) data.
  3. Always drops the silo schema at the end, even on errors, and verifies
     that the source tables are bit-for-bit unchanged (row count + checksum).
  4. Prints a summary and writes observability_results.csv.

INTEGRATION POINTS (where UNMASQUE-II output goes) -- search for "INSERT"
  (A) run_unmasque2()      : implement once; called per run with the hidden
                             SQL and the silo schema; return the extracted SQL.
  (B) EXTRACTED_QE         : OR paste the extracted SQL per run id here.
  (C) interactive prompt   : if neither A nor B supplies a query and a terminal
                             is attached, the script pauses and asks you to
                             paste it (database and schema are shown).
  Order of precedence: A, then B, then C.

Edit the credentials in main() and run:   python observability_experiment.py
"""
import csv
import subprocess
import sys
from collections import Counter
from decimal import Decimal

try:
    import psycopg2
except ImportError:  # self-sufficient: install the driver if it is missing
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "psycopg2-binary"])
    import psycopg2

TABLES = ["region", "nation", "supplier", "customer",
          "part", "partsupp", "orders", "lineitem"]
MARKER = "created by observability_experiment.py - safe to drop"

# =========================================================================
# INTEGRATION POINT (B): INSERT the UNMASQUE-II output (the extracted SQL
# string QE) for each run below. Each run has its own database variant, so
# each run needs its own QE. Leave "" to use (A) or the prompt (C).
# =========================================================================
EXTRACTED_QE = {
    "R1":  "",   # QH=QN1  on the full instance
    "R2":  "",   # QH=QN1  on variant qn1_a
    "R3":  "",   # QH=QN1  on variant qn1_b
    "R4a": "",   # QH=QN2  on the full instance
    "R4":  "",   # QH=QN2  on variant qn2_sep
    "R5":  "",   # QH=QN2  on variant qn2_joint
    "R6":  "",   # QH=QN2  on variant qn2_half
    "R7":  "",   # QH=QJ   on the full instance
    "R8":  "",   # QH=QJp  on the full instance
    "R9":  "",   # QH=QJ   on variant qj_unm
    "R10": "",   # QH=QJi  on variant qji_null
}


def run_unmasque2(hidden_sql, schema, conn):
    """INTEGRATION POINT (A): INSERT your UNMASQUE-II invocation here.

    hidden_sql : the hidden query QH (wrap it as the executable that
                 UNMASQUE-II treats as a black box).
    schema     : the silo schema holding this run's database. UNMASQUE-II must
                 read and mutate ONLY this schema (e.g. set search_path to it,
                 or pass it in UNMASQUE-II's own configuration).
    conn       : the connection parameters dict from main().
    Return the extracted query as a SQL string, or None to fall back to
    EXTRACTED_QE / the interactive prompt.
    """
    return None


# ------------------------------------------------------------------ queries
HQ = {
    "QN1": "SELECT c_name, c_acctbal FROM customer "
           "WHERE c_mktsegment <> 'BUILDING' AND c_acctbal > 9000",
    "QN2": "SELECT o_orderkey, o_totalprice FROM orders "
           "WHERE o_orderstatus <> 'F' AND o_orderpriority <> '1-URGENT'",
    "QJ":  "SELECT c_name, c_acctbal, o_orderkey, o_totalprice "
           "FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey",
    "QJi": "SELECT c_name, c_acctbal, o_orderkey, o_totalprice "
           "FROM customer, orders WHERE c_custkey = o_custkey",
    # outer join with no attribute of orders in the projection
    "QJp": "SELECT c_name, c_acctbal "
           "FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey",
}


# --------------------------------------------------------------- variants
# Statements are ordered so that foreign keys (if present) are never violated.
def on_customer(pred):
    sub = "SELECT c_custkey FROM {s}.customer WHERE " + pred
    return [
        "DELETE FROM {s}.lineitem WHERE l_orderkey IN (SELECT o_orderkey "
        "FROM {s}.orders WHERE o_custkey IN (" + sub + "))",
        "DELETE FROM {s}.orders WHERE o_custkey IN (" + sub + ")",
        "DELETE FROM {s}.customer WHERE " + pred,
    ]


def on_orders(pred):
    return [
        "DELETE FROM {s}.lineitem WHERE l_orderkey IN (SELECT o_orderkey "
        "FROM {s}.orders WHERE " + pred + ")",
        "DELETE FROM {s}.orders WHERE " + pred,
    ]


VARIANTS = {
    "full": [],
    # BUILDING rows exist, but none satisfies c_acctbal > 9000
    "qn1_a": on_customer("c_mktsegment = 'BUILDING' AND c_acctbal > 9000"),
    # no BUILDING rows at all
    "qn1_b": on_customer("c_mktsegment = 'BUILDING'"),
    # no tuple violates both NEPs (single violators remain)
    "qn2_sep": on_orders("o_orderstatus = 'F' AND o_orderpriority = '1-URGENT'"),
    # no single violators: only conforming tuples and double violators
    "qn2_joint": on_orders("(o_orderstatus = 'F') <> (o_orderpriority = '1-URGENT')"),
    # no tuple violates NEP2 (o_orderpriority <> '1-URGENT'); NEP1 witnesses stay
    "qn2_half": on_orders("o_orderpriority = '1-URGENT'"),
    # every customer has at least one order (no unmatched preserved tuple)
    "qj_unm": ["DELETE FROM {s}.customer WHERE c_custkey NOT IN "
               "(SELECT o_custkey FROM {s}.orders)"],
    # D is not NULL-free: NULLs in a projected attribute of matched tuples
    "qji_null": ["ALTER TABLE {s}.orders ALTER COLUMN o_totalprice DROP NOT NULL",
                 "UPDATE {s}.orders SET o_totalprice = NULL "
                 "WHERE o_orderkey % 100 = 0"],
}

UNMATCHED = ("SELECT count(*) FROM {s}.customer WHERE c_custkey NOT IN "
             "(SELECT o_custkey FROM {s}.orders)")


def cnt(table, cond):
    return "SELECT count(*) FROM {s}.%s WHERE %s" % (table, cond)


# Non-vacuity checks: ("description", sql, "pos" | "zero")
SANITY = {
    "full": [
        ("customers without orders exist", UNMATCHED, "pos"),
        ("BUILDING customers with acctbal>9000 exist",
         cnt("customer", "c_mktsegment='BUILDING' AND c_acctbal>9000"), "pos"),
        ("orders violating both NEPs exist",
         cnt("orders", "o_orderstatus='F' AND o_orderpriority='1-URGENT'"), "pos"),
        ("orders violating NEP1 only exist",
         cnt("orders", "o_orderstatus='F' AND o_orderpriority<>'1-URGENT'"), "pos"),
        ("orders violating NEP2 only exist",
         cnt("orders", "o_orderstatus<>'F' AND o_orderpriority='1-URGENT'"), "pos"),
    ],
    "qn1_a": [
        ("BUILDING rows exist", cnt("customer", "c_mktsegment='BUILDING'"), "pos"),
        ("no BUILDING row with acctbal>9000",
         cnt("customer", "c_mktsegment='BUILDING' AND c_acctbal>9000"), "zero"),
        ("non-BUILDING rows with acctbal>9000 exist",
         cnt("customer", "c_mktsegment<>'BUILDING' AND c_acctbal>9000"), "pos"),
    ],
    "qn1_b": [
        ("no BUILDING rows", cnt("customer", "c_mktsegment='BUILDING'"), "zero"),
        ("non-BUILDING rows with acctbal>9000 exist",
         cnt("customer", "c_mktsegment<>'BUILDING' AND c_acctbal>9000"), "pos"),
    ],
    "qn2_sep": [
        ("no double violators",
         cnt("orders", "o_orderstatus='F' AND o_orderpriority='1-URGENT'"), "zero"),
        ("violators of NEP1 only exist",
         cnt("orders", "o_orderstatus='F' AND o_orderpriority<>'1-URGENT'"), "pos"),
        ("violators of NEP2 only exist",
         cnt("orders", "o_orderstatus<>'F' AND o_orderpriority='1-URGENT'"), "pos"),
        ("tuples satisfying both exist",
         cnt("orders", "o_orderstatus<>'F' AND o_orderpriority<>'1-URGENT'"), "pos"),
    ],
    "qn2_joint": [
        ("no single violators",
         cnt("orders", "(o_orderstatus='F') <> (o_orderpriority='1-URGENT')"), "zero"),
        ("double violators exist",
         cnt("orders", "o_orderstatus='F' AND o_orderpriority='1-URGENT'"), "pos"),
        ("tuples satisfying both exist",
         cnt("orders", "o_orderstatus<>'F' AND o_orderpriority<>'1-URGENT'"), "pos"),
    ],
    "qn2_half": [
        ("no tuple violates NEP2", cnt("orders", "o_orderpriority='1-URGENT'"), "zero"),
        ("NEP1 violators exist", cnt("orders", "o_orderstatus='F'"), "pos"),
        ("tuples satisfying both exist",
         cnt("orders", "o_orderstatus<>'F' AND o_orderpriority<>'1-URGENT'"), "pos"),
    ],
    "qj_unm": [
        ("no customer without orders", UNMATCHED, "zero"),
        ("orders exist", cnt("orders", "1=1"), "pos"),
    ],
    "qji_null": [
        ("NULLs in o_totalprice", cnt("orders", "o_totalprice IS NULL"), "pos"),
        ("customers without orders exist", UNMATCHED, "pos"),
    ],
}

# run, hidden query, variant, condition status, predicted eq on variant,
# predicted eq on full instance.
#   eq on variant True  : QE and QH agree on D (missing construct is invisible)
#   eq on variant False : they disagree on D (visible but not resolvable)
#   eq on full True     : QE equals QH on the full instance (exact)
RUNS = [
    ("R1",  "QN1", "full",      "holds",                       True,  True),
    ("R2",  "QN1", "qn1_a",     "other predicate violated",    True,  False),
    ("R3",  "QN1", "qn1_b",     "no witness",                  True,  False),
    ("R4a", "QN2", "full",      "holds",                       True,  True),
    ("R4",  "QN2", "qn2_sep",   "holds (single violators)",    True,  True),
    ("R5",  "QN2", "qn2_joint", "fails jointly",               False, False),
    ("R6",  "QN2", "qn2_half",  "holds for NEP1 only",         True,  False),
    ("R7",  "QJ",  "full",      "holds",                       True,  True),
    ("R8",  "QJp", "full",      "no orders attribute projected", False, False),
    ("R9",  "QJ",  "qj_unm",    "no unmatched tuple",          True,  False),
    ("R10", "QJi", "qji_null",  "D not NULL-free",             False, False),
]

FK_SQL = [
    "ALTER TABLE {s}.nation ADD FOREIGN KEY (n_regionkey) REFERENCES {s}.region (r_regionkey)",
    "ALTER TABLE {s}.supplier ADD FOREIGN KEY (s_nationkey) REFERENCES {s}.nation (n_nationkey)",
    "ALTER TABLE {s}.customer ADD FOREIGN KEY (c_nationkey) REFERENCES {s}.nation (n_nationkey)",
    "ALTER TABLE {s}.partsupp ADD FOREIGN KEY (ps_partkey) REFERENCES {s}.part (p_partkey)",
    "ALTER TABLE {s}.partsupp ADD FOREIGN KEY (ps_suppkey) REFERENCES {s}.supplier (s_suppkey)",
    "ALTER TABLE {s}.orders ADD FOREIGN KEY (o_custkey) REFERENCES {s}.customer (c_custkey)",
    "ALTER TABLE {s}.lineitem ADD FOREIGN KEY (l_orderkey) REFERENCES {s}.orders (o_orderkey)",
    "ALTER TABLE {s}.lineitem ADD FOREIGN KEY (l_partkey, l_suppkey) "
    "REFERENCES {s}.partsupp (ps_partkey, ps_suppkey)",
]


# --------------------------------------------------------------- helpers
class PG:
    def __init__(self, params):
        self.c = psycopg2.connect(**params)
        self.c.autocommit = True

    def x(self, sql, fetch=False):
        cur = self.c.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall() if fetch else None
        finally:
            cur.close()


def fingerprint(db, schema, exact):
    """Row count (+ order-independent checksum) of each of the 8 tables."""
    out = {}
    for t in TABLES:
        if exact:
            sql = ("SELECT count(*), coalesce(sum(hashtext(x::text)::bigint),0) "
                   "FROM %s.%s x" % (schema, t))
        else:
            sql = "SELECT count(*), 0 FROM %s.%s" % (schema, t)
        out[t] = tuple(db.x(sql, True)[0])
    return out


def build_silo(db, src, silo, variant, add_fks):
    """(Re)create the silo schema as a copy of src, then apply the variant."""
    db.x("DROP SCHEMA IF EXISTS %s CASCADE" % silo)
    db.x("CREATE SCHEMA %s" % silo)
    db.x("COMMENT ON SCHEMA %s IS '%s'" % (silo, MARKER))
    for t in TABLES:
        db.x("CREATE TABLE %s.%s (LIKE %s.%s INCLUDING ALL)" % (silo, t, src, t))
    for t in TABLES:
        db.x("INSERT INTO %s.%s SELECT * FROM %s.%s" % (silo, t, src, t))
    for st in VARIANTS[variant]:
        db.x(st.format(s=silo))
    if add_fks:
        for st in FK_SQL:
            try:
                db.x(st.format(s=silo))
            except psycopg2.Error as e:
                print("  warning: foreign key not added (%s)" % str(e).splitlines()[0])
    for desc, sql, exp in SANITY.get(variant, []):
        n = db.x(sql.format(s=silo), True)[0][0]
        good = (n > 0) if exp == "pos" else (n == 0)
        print("    [%s] %-52s count=%s" % ("ok" if good else "FAIL", desc, n))
        if not good:
            raise RuntimeError("variant %s is vacuous: %s" % (variant, desc))


def norm(v):
    return round(float(v), 2) if isinstance(v, (float, Decimal)) else v


def bag(db, silo, sql):
    db.x("SET search_path TO %s" % silo)
    return Counter(tuple(norm(v) for v in r) for r in db.x(sql, True))


def obtain_qe(rid, hidden_sql, silo, conn_params, db_label):
    q = run_unmasque2(hidden_sql, silo, conn_params)
    if q and q.strip():
        return q.strip().rstrip(";"), "hook"
    if EXTRACTED_QE.get(rid, "").strip():
        return EXTRACTED_QE[rid].strip().rstrip(";"), "dict"
    if sys.stdin.isatty():
        print("\n>>> %s: run UNMASQUE-II now on database '%s', schema '%s'." %
              (rid, db_label, silo))
        print(">>> Hidden query QH:\n    %s" % hidden_sql)
        print(">>> Paste the extracted SQL, then a line containing only ;; "
              "(or just ;; to skip):")
        lines = []
        while True:
            line = sys.stdin.readline()
            if not line or line.strip() == ";;":
                break
            lines.append(line)
        q = "".join(lines).strip().rstrip(";")
        if q:
            return q, "prompt"
    return None, "none"


# ----------------------------------------------------------------- main
def main():
    # ===================== EDIT: connection credentials ====================
    conn_params = dict(host="localhost", port=5432, dbname="tpch",
                       user="postgres", password="postgres")
    SOURCE_SCHEMA = "public"            # schema holding the original 8 tables
    SILO_SCHEMA = "obs_silo_u2"         # new schema, dropped at the end
    ADD_FKS = True                      # re-add TPC-H foreign keys in the silo
    EXACT_FINGERPRINT = True            # checksum (slower) vs row counts only
    # =======================================================================

    db = PG(conn_params)
    for t in TABLES:
        if not db.x("SELECT 1 FROM information_schema.tables WHERE "
                    "table_schema='%s' AND table_name='%s'" % (SOURCE_SCHEMA, t), True):
            sys.exit("source table %s.%s not found" % (SOURCE_SCHEMA, t))
    owner = db.x("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace "
                 "WHERE nspname='%s'" % SILO_SCHEMA, True)
    if owner and owner[0][0] != MARKER:
        sys.exit("schema %s exists and was not created by this script; "
                 "change SILO_SCHEMA" % SILO_SCHEMA)

    before = fingerprint(db, SOURCE_SCHEMA, EXACT_FINGERPRINT)
    results = []
    try:
        for rid, hq, variant, cond, p_var, p_full in RUNS:
            print("\n== %s: QH=%s, database variant=%s (condition: %s)" %
                  (rid, hq, variant, cond))
            build_silo(db, SOURCE_SCHEMA, SILO_SCHEMA, variant, ADD_FKS)
            qe, how = obtain_qe(rid, HQ[hq], SILO_SCHEMA, conn_params,
                                conn_params["dbname"])
            if qe is None:
                print("   no extracted query supplied; run skipped")
                results.append(dict(run=rid, qh=hq, variant=variant, cond=cond,
                                    qe="", source="none"))
                continue
            try:
                # UNMASQUE-II may have altered the silo; evaluate on a fresh
                # copy of the same variant, then on the full data.
                build_silo(db, SOURCE_SCHEMA, SILO_SCHEMA, variant, ADD_FKS)
                rh_v, re_v = bag(db, SILO_SCHEMA, HQ[hq]), bag(db, SILO_SCHEMA, qe)
                build_silo(db, SOURCE_SCHEMA, SILO_SCHEMA, "full", ADD_FKS)
                rh_f, re_f = bag(db, SILO_SCHEMA, HQ[hq]), bag(db, SILO_SCHEMA, qe)
            except psycopg2.Error as e:
                print("   extracted query failed to run: %s" % str(e).splitlines()[0])
                results.append(dict(run=rid, qh=hq, variant=variant, cond=cond,
                                    qe=qe, source=how, error=str(e).splitlines()[0]))
                continue
            o_var, o_full = rh_v == re_v, rh_f == re_f
            results.append(dict(
                run=rid, qh=hq, variant=variant, cond=cond, qe=qe, source=how,
                eq_var=o_var, pred_var=p_var, eq_full=o_full, pred_full=p_full,
                delta=sum(re_f.values()) - sum(rh_f.values()),
                match=(o_var, o_full) == (p_var, p_full)))
    finally:
        db.x("DROP SCHEMA IF EXISTS %s CASCADE" % SILO_SCHEMA)
        print("\nsilo schema %s dropped" % SILO_SCHEMA)
        after = fingerprint(db, SOURCE_SCHEMA, EXACT_FINGERPRINT)
        print("source tables unchanged: %s" % ("YES" if before == after else
                                              "NO  <-- INVESTIGATE"))

    # ------------------------------------------------------------ report
    print("\n%-4s %-4s %-10s | %-17s | %-17s | %s" %
          ("run", "QH", "variant", "QE=QH on D (o/p)", "exact on full (o/p)", "verdict"))
    done = [r for r in results if "eq_var" in r]
    for r in results:
        if "eq_var" not in r:
            print("%-4s %-4s %-10s | %s" % (r["run"], r["qh"], r["variant"],
                                            r.get("error", "skipped")))
            continue
        print("%-4s %-4s %-10s | %-7s / %-7s | %-7s / %-7s | %s (|RE|-|RH| on full = %+d)" %
              (r["run"], r["qh"], r["variant"], r["eq_var"], r["pred_var"],
               r["eq_full"], r["pred_full"], "MATCH" if r["match"] else "MISMATCH",
               r["delta"]))

    h1 = [r for r in done if r["pred_full"]]
    h2 = [r for r in done if not r["pred_full"]]
    print("\nH1 (sufficiency): %d/%d runs with a satisfied condition are exact"
          % (sum(r["eq_full"] for r in h1), len(h1)))
    print("H2 (tightness)  : %d/%d violated-condition runs behave as predicted"
          % (sum(r["match"] for r in h2), len(h2)))
    for r in h2:
        if r["eq_full"]:
            print("   note: %s is exact although its condition is violated -> "
                  "condition not necessary here" % r["run"])
    if len(done) < len(RUNS):
        print("(%d of %d runs had no extracted query or failed)" %
              (len(RUNS) - len(done), len(RUNS)))

    with open("observability_results.csv", "w", newline="") as f:
        cols = ["run", "qh", "variant", "cond", "source", "eq_var", "pred_var",
                "eq_full", "pred_full", "delta", "match", "error", "qe"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({c: r.get(c, "") for c in cols})
    print("wrote observability_results.csv")


if __name__ == "__main__":
    main()
