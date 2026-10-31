#!/usr/bin/env python3
"""
Observability-boundary experiment for UNMASQUE-II on TPC-H (PostgreSQL only).

You only need to (1) edit the credentials in CONFIG, (2) paste the extracted
queries into EXTRACTED_QE.  Everything else is automatic.

HOW IT WORKS
  Hidden queries QH (list HIDDEN_QUERIES) are extracted by UNMASQUE-II on
  several slightly different databases ("variants").  Each variant differs
  from the full data only in the witness tuples a condition needs.
    - condition holds     -> QE should equal QH        (sufficiency, H1)
    - condition violated  -> QE should fail in the predicted way (tightness, H2)

DATA
  * If the 8 TPC-H tables exist in SOURCE_SCHEMA, they are only READ: they are
    copied into new "silo" schemas and all work happens there.
  * If they do not exist, a small dummy TPC-H database is generated in a
    temporary schema (it contains every kind of tuple the experiment needs).
  * Every schema this script creates is dropped at the end, and the original
    tables are verified unchanged (row count + checksum).

THREE STEPS (one command each; the first two happen automatically)
  python observability_experiment.py setup     # builds one silo schema per run
        -> prints, per run: schema name + hidden query.  Run UNMASQUE-II on
           that schema and paste the extracted SQL into EXTRACTED_QE below.
  python observability_experiment.py evaluate  # compares QE vs QH, writes CSV,
        -> drops ALL silo schemas when finished.
  python observability_experiment.py clean     # drop everything this script made
  (No argument: runs "evaluate" if any QE is filled in, otherwise "setup".)

NOTE: QE column order must match QH column order (results are compared as
bags of rows).  QE must use unqualified table names (the script sets
search_path), i.e. UNMASQUE-II output as-is is fine.
"""
import csv
import subprocess
import sys
from collections import Counter
from decimal import Decimal

try:
    import psycopg2
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "psycopg2-binary"])
    import psycopg2

# =========================================================================
# CONFIG -- the only thing to edit besides EXTRACTED_QE
# =========================================================================
CONN = dict(host="localhost", port=5432, dbname="tpch",
            user="postgres", password="postgres")
SOURCE_SCHEMA = "public"   # where your original TPC-H tables live (if any)
FORCE_DUMMY = False        # True: ignore any real TPC-H tables, use dummy data

# =========================================================================
# ALL HIDDEN QUERIES (QH) -- one list
# =========================================================================
HIDDEN_QUERIES = [
    ("QN1", "SELECT c_name, c_acctbal FROM customer "
            "WHERE c_mktsegment <> 'BUILDING' AND c_acctbal > 9000"),
    ("QN2", "SELECT o_orderkey, o_totalprice FROM orders "
            "WHERE o_orderstatus <> 'F' AND o_orderpriority <> '1-URGENT'"),
    ("QJ",  "SELECT c_name, c_acctbal, o_orderkey, o_totalprice "
            "FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey"),
    ("QJi", "SELECT c_name, c_acctbal, o_orderkey, o_totalprice "
            "FROM customer, orders WHERE c_custkey = o_custkey"),
    # outer join, no attribute of orders in the projection
    ("QJp", "SELECT c_name, c_acctbal "
            "FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey"),
]

# =========================================================================
# ALL EXTRACTED QUERIES (QE) -- one list.  INSERT the UNMASQUE-II output
# between the quotes.  Each run has its own database, so each needs its own QE.
# Leave "" to skip a run.
# =========================================================================
EXTRACTED_QE = [
    ("R1",  ""),   # QH=QN1  on the full data
    ("R2",  ""),   # QH=QN1  on variant qn1_a
    ("R3",  ""),   # QH=QN1  on variant qn1_b
    ("R4a", ""),   # QH=QN2  on the full data
    ("R4",  ""),   # QH=QN2  on variant qn2_sep
    ("R5",  ""),   # QH=QN2  on variant qn2_joint
    ("R6",  ""),   # QH=QN2  on variant qn2_half
    ("R7",  ""),   # QH=QJ   on the full data
    ("R8",  ""),   # QH=QJp  on the full data
    ("R9",  ""),   # QH=QJ   on variant qj_unm
    ("R10", ""),   # QH=QJi  on variant qji_null
]

# run id, QH id, variant, condition status,
# predicted "QE==QH on the variant D", predicted "QE==QH on the full data"
RUNS = [
    ("R1",  "QN1", "full",      "holds",                         True,  True),
    ("R2",  "QN1", "qn1_a",     "other predicate violated",      True,  False),
    ("R3",  "QN1", "qn1_b",     "no witness",                    True,  False),
    ("R4a", "QN2", "full",      "holds",                         True,  True),
    ("R4",  "QN2", "qn2_sep",   "holds (single violators)",      True,  True),
    ("R5",  "QN2", "qn2_joint", "fails jointly",                 False, False),
    ("R6",  "QN2", "qn2_half",  "holds for NEP1 only",           True,  False),
    ("R7",  "QJ",  "full",      "holds",                         True,  True),
    ("R8",  "QJp", "full",      "no orders attribute projected", False, False),
    ("R9",  "QJ",  "qj_unm",    "no unmatched tuple",            True,  False),
    ("R10", "QJi", "qji_null",  "D not NULL-free",               False, False),
]

# =========================================================================
# Internals below -- no need to edit
# =========================================================================
TABLES = ["region", "nation", "supplier", "customer",
          "part", "partsupp", "orders", "lineitem"]
MARKER = "created by observability_experiment.py - safe to drop"
DUMMY_BASE = "obs_dummy_base"
EVAL_VAR, EVAL_FULL = "obs_silo_eval_var", "obs_silo_eval_full"


def run_schema(rid):
    return "obs_silo_" + rid.lower()


# ---------------------------------------------------------------- variants
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
    "qn1_a": on_customer("c_mktsegment = 'BUILDING' AND c_acctbal > 9000"),
    "qn1_b": on_customer("c_mktsegment = 'BUILDING'"),
    "qn2_sep": on_orders("o_orderstatus = 'F' AND o_orderpriority = '1-URGENT'"),
    "qn2_joint": on_orders("(o_orderstatus = 'F') <> (o_orderpriority = '1-URGENT')"),
    "qn2_half": on_orders("o_orderpriority = '1-URGENT'"),
    "qj_unm": ["DELETE FROM {s}.customer WHERE c_custkey NOT IN "
               "(SELECT o_custkey FROM {s}.orders)"],
    "qji_null": ["ALTER TABLE {s}.orders ALTER COLUMN o_totalprice DROP NOT NULL",
                 "UPDATE {s}.orders SET o_totalprice = NULL "
                 "WHERE o_orderkey % 100 = 0"],
}

UNMATCHED = ("SELECT count(*) FROM {s}.customer WHERE c_custkey NOT IN "
             "(SELECT o_custkey FROM {s}.orders)")


def cnt(table, cond):
    return "SELECT count(*) FROM {s}.%s WHERE %s" % (table, cond)


SANITY = {  # non-vacuity checks: (description, sql, "pos" | "zero")
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

# ------------------------------------------------------------ dummy TPC-H
DUMMY_DDL = [
    "CREATE TABLE {s}.region (r_regionkey int PRIMARY KEY, r_name varchar(25) NOT NULL, r_comment varchar(152))",
    "CREATE TABLE {s}.nation (n_nationkey int PRIMARY KEY, n_name char(25) NOT NULL, n_regionkey int NOT NULL, n_comment varchar(152))",
    "CREATE TABLE {s}.supplier (s_suppkey int PRIMARY KEY, s_name char(25) NOT NULL, s_address varchar(40) NOT NULL, s_nationkey int NOT NULL, s_phone char(15) NOT NULL, s_acctbal numeric(15,2) NOT NULL, s_comment varchar(101) NOT NULL)",
    "CREATE TABLE {s}.customer (c_custkey int PRIMARY KEY, c_name varchar(25) NOT NULL, c_address varchar(40) NOT NULL, c_nationkey int NOT NULL, c_phone char(15) NOT NULL, c_acctbal numeric(15,2) NOT NULL, c_mktsegment char(10) NOT NULL, c_comment varchar(117) NOT NULL)",
    "CREATE TABLE {s}.part (p_partkey int PRIMARY KEY, p_name varchar(55) NOT NULL, p_mfgr char(25) NOT NULL, p_brand char(10) NOT NULL, p_type varchar(25) NOT NULL, p_size int NOT NULL, p_container char(10) NOT NULL, p_retailprice numeric(15,2) NOT NULL, p_comment varchar(23) NOT NULL)",
    "CREATE TABLE {s}.partsupp (ps_partkey int NOT NULL, ps_suppkey int NOT NULL, ps_availqty int NOT NULL, ps_supplycost numeric(15,2) NOT NULL, ps_comment varchar(199) NOT NULL, PRIMARY KEY (ps_partkey, ps_suppkey))",
    "CREATE TABLE {s}.orders (o_orderkey int PRIMARY KEY, o_custkey int NOT NULL, o_orderstatus char(1) NOT NULL, o_totalprice numeric(15,2) NOT NULL, o_orderdate date NOT NULL, o_orderpriority char(15) NOT NULL, o_clerk char(15) NOT NULL, o_shippriority int NOT NULL, o_comment varchar(79) NOT NULL)",
    "CREATE TABLE {s}.lineitem (l_orderkey int NOT NULL, l_partkey int NOT NULL, l_suppkey int NOT NULL, l_linenumber int NOT NULL, l_quantity numeric(15,2) NOT NULL, l_extendedprice numeric(15,2) NOT NULL, l_discount numeric(15,2) NOT NULL, l_tax numeric(15,2) NOT NULL, l_returnflag char(1) NOT NULL, l_linestatus char(1) NOT NULL, l_shipdate date NOT NULL, l_commitdate date NOT NULL, l_receiptdate date NOT NULL, l_shipinstruct char(25) NOT NULL, l_shipmode char(10) NOT NULL, l_comment varchar(44) NOT NULL, PRIMARY KEY (l_orderkey, l_linenumber))",
]

DUMMY_DATA = [
    "INSERT INTO {s}.region SELECT i, 'REGION'||i, 'c' FROM generate_series(0,4) i",
    "INSERT INTO {s}.nation SELECT i, 'NATION'||i, i%5, 'c' FROM generate_series(0,24) i",
    "INSERT INTO {s}.supplier SELECT i, 'Supplier#'||lpad(i::text,9,'0'), 'addr'||i, i%25, "
    "'10-000-000-'||lpad(i::text,4,'0'), (i*53)%10000, 'c' FROM generate_series(1,20) i",
    # acctbal spans roughly -999..10000; segment independent of balance
    "INSERT INTO {s}.customer SELECT i, 'Customer#'||lpad(i::text,9,'0'), 'addr'||i, i%25, "
    "'20-000-000-'||lpad(i::text,4,'0'), ((i*37)%11000)-999, "
    "(ARRAY['AUTOMOBILE','BUILDING','FURNITURE','HOUSEHOLD','MACHINERY'])[i%5+1], 'c' "
    "FROM generate_series(1,1000) i",
    "INSERT INTO {s}.part SELECT i, 'part'||i, 'Manufacturer#'||(i%5+1), 'Brand#'||(i%5+1), "
    "'TYPE'||(i%7), i%50+1, 'SM BOX', 900+i, 'c' FROM generate_series(1,200) i",
    "INSERT INTO {s}.partsupp SELECT p, (p%20)+1, 100, p, 'c' FROM generate_series(1,200) p",
    "INSERT INTO {s}.partsupp SELECT p, ((p+10)%20)+1, 100, p, 'c' FROM generate_series(1,200) p",
    # customers 801..1000 have no orders; status x priority fully crossed
    "INSERT INTO {s}.orders SELECT i, (i%800)+1, (ARRAY['O','F','P'])[i%3+1], "
    "1000+(i*13)%50000, DATE '1993-01-01'+(i%2000), "
    "(ARRAY['1-URGENT','2-HIGH','3-MEDIUM','4-NOT SPECIFIED','5-LOW'])[(i/3)%5+1], "
    "'Clerk#'||lpad((i%50)::text,9,'0'), 0, 'c' FROM generate_series(1,3000) i",
    "INSERT INTO {s}.lineitem SELECT o.o_orderkey, p.pk, "
    "CASE WHEN n=1 THEN (p.pk%20)+1 ELSE ((p.pk+10)%20)+1 END, n, 10+n, 100*n, 0.05, 0.02, "
    "'N', 'O', o.o_orderdate+1, o.o_orderdate+2, o.o_orderdate+3, 'NONE', 'AIR', 'c' "
    "FROM {s}.orders o CROSS JOIN generate_series(1,2) n "
    "CROSS JOIN LATERAL (SELECT (o.o_orderkey%200)+1 AS pk) p",
]


# ---------------------------------------------------------------- helpers
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


def have_tpch(db, schema):
    for t in TABLES:
        if not db.x("SELECT 1 FROM information_schema.tables WHERE "
                    "table_schema='%s' AND table_name='%s'" % (schema, t), True):
            return False
    return True


def fingerprint(db, schema):
    out = {}
    for t in TABLES:
        out[t] = tuple(db.x("SELECT count(*), coalesce(sum(hashtext(x::text)::bigint),0) "
                            "FROM %s.%s x" % (schema, t), True)[0])
    return out


def mine_or_absent(db, schema):
    r = db.x("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace "
             "WHERE nspname='%s'" % schema, True)
    if r and r[0][0] != MARKER:
        sys.exit("schema %s exists and was not created by this script; "
                 "refusing to touch it" % schema)


def new_schema(db, name):
    mine_or_absent(db, name)
    db.x("DROP SCHEMA IF EXISTS %s CASCADE" % name)
    db.x("CREATE SCHEMA %s" % name)
    db.x("COMMENT ON SCHEMA %s IS '%s'" % (name, MARKER))


def drop_schema(db, name):
    mine_or_absent(db, name)
    db.x("DROP SCHEMA IF EXISTS %s CASCADE" % name)


def make_dummy_base(db):
    print("No TPC-H tables found -> generating dummy TPC-H in schema %s" % DUMMY_BASE)
    new_schema(db, DUMMY_BASE)
    for st in DUMMY_DDL + DUMMY_DATA:
        db.x(st.format(s=DUMMY_BASE))
    for t in TABLES:
        print("    %-9s %6d rows" % (t, db.x("SELECT count(*) FROM %s.%s" %
                                             (DUMMY_BASE, t), True)[0][0]))


def build_silo(db, base, silo, variant, verbose=True):
    new_schema(db, silo)
    for t in TABLES:
        db.x("CREATE TABLE %s.%s (LIKE %s.%s INCLUDING ALL)" % (silo, t, base, t))
    for t in TABLES:
        db.x("INSERT INTO %s.%s SELECT * FROM %s.%s" % (silo, t, base, t))
    for st in VARIANTS[variant]:
        db.x(st.format(s=silo))
    for st in FK_SQL:
        try:
            db.x(st.format(s=silo))
        except psycopg2.Error as e:
            if verbose:
                print("  warning: FK not added (%s)" % str(e).splitlines()[0])
    for desc, sql, exp in SANITY.get(variant, []):
        n = db.x(sql.format(s=silo), True)[0][0]
        good = (n > 0) if exp == "pos" else (n == 0)
        if verbose:
            print("    [%s] %-50s count=%s" % ("ok" if good else "FAIL", desc, n))
        if not good:
            raise RuntimeError("variant %s is vacuous: %s" % (variant, desc))


def norm(v):
    return round(float(v), 2) if isinstance(v, (float, Decimal)) else v


def bag(db, schema, sql):
    db.x("SET search_path TO %s" % schema)
    try:
        return Counter(tuple(norm(v) for v in r) for r in db.x(sql, True))
    finally:
        db.x("SET search_path TO public")


def qe_map():
    return {rid: q.strip().rstrip(";") for rid, q in EXTRACTED_QE if q and q.strip()}


def setup_base(db):
    """Return (base_schema, created_by_us)."""
    if not FORCE_DUMMY and have_tpch(db, SOURCE_SCHEMA):
        print("Using TPC-H tables in schema '%s' (read-only; copies are made)." %
              SOURCE_SCHEMA)
        return SOURCE_SCHEMA, False
    make_dummy_base(db)
    return DUMMY_BASE, True


# ------------------------------------------------------------------ steps
def step_setup(db):
    base, _ = setup_base(db)
    hq = dict(HIDDEN_QUERIES)
    print("\nBuilding one silo schema per run ...")
    for rid, qh, variant, cond, _, _ in RUNS:
        print("\n== %s (variant %s)" % (rid, variant))
        build_silo(db, base, run_schema(rid), variant)
    print("\n" + "=" * 70)
    print("NEXT: run UNMASQUE-II once per row below, pointing it at the given")
    print("schema (database '%s'), then paste each extracted SQL into" % CONN["dbname"])
    print("EXTRACTED_QE in this file and run:  python %s evaluate" % sys.argv[0])
    print("=" * 70)
    for rid, qh, variant, cond, _, _ in RUNS:
        print("\n%s  schema=%s  condition: %s" % (rid, run_schema(rid), cond))
        print("    QH (%s): %s" % (qh, hq[qh]))
    if base == DUMMY_BASE:
        print("\n(The dummy base schema %s is kept so 'evaluate' can reuse it.)" % DUMMY_BASE)
    print("\nWhen finished: 'evaluate' drops everything, or run 'clean'.")


def step_clean(db):
    for rid, *_ in RUNS:
        drop_schema(db, run_schema(rid))
    for s in (EVAL_VAR, EVAL_FULL, DUMMY_BASE):
        drop_schema(db, s)
    print("all schemas created by this script dropped")


def step_evaluate(db):
    qes = qe_map()
    hq = dict(HIDDEN_QUERIES)
    before = None
    results = []
    created_base = False
    try:
        base, created_base = setup_base(db)
        if not created_base:
            before = fingerprint(db, base)
        for rid, qh, variant, cond, p_var, p_full in RUNS:
            row = dict(run=rid, qh=qh, variant=variant, cond=cond)
            if rid not in qes:
                print("%s: no extracted query -> skipped" % rid)
                results.append(row)
                continue
            qe = qes[rid]
            print("\n== %s: QH=%s variant=%s" % (rid, qh, variant))
            try:
                # fresh copies: UNMASQUE-II may have modified the run schema
                build_silo(db, base, EVAL_VAR, variant, verbose=False)
                build_silo(db, base, EVAL_FULL, "full", verbose=False)
                rh_v, re_v = bag(db, EVAL_VAR, hq[qh]), bag(db, EVAL_VAR, qe)
                rh_f, re_f = bag(db, EVAL_FULL, hq[qh]), bag(db, EVAL_FULL, qe)
            except psycopg2.Error as e:
                msg = str(e).splitlines()[0]
                print("   extracted query failed to run: %s" % msg)
                row.update(qe=qe, error=msg)
                results.append(row)
                continue
            o_var, o_full = rh_v == re_v, rh_f == re_f
            row.update(qe=qe, eq_var=o_var, pred_var=p_var, eq_full=o_full,
                       pred_full=p_full,
                       delta=sum(re_f.values()) - sum(rh_f.values()),
                       match=(o_var, o_full) == (p_var, p_full))
            results.append(row)
    finally:
        for rid, *_ in RUNS:
            drop_schema(db, run_schema(rid))
        for s in (EVAL_VAR, EVAL_FULL):
            drop_schema(db, s)
        if created_base:
            drop_schema(db, DUMMY_BASE)
        print("\nall silo schemas dropped")
        if before is not None:
            print("source tables unchanged: %s" %
                  ("YES" if before == fingerprint(db, SOURCE_SCHEMA)
                   else "NO  <-- INVESTIGATE"))

    # ----------------------------------------------------------- report
    print("\n%-4s %-4s %-10s | %-17s | %-19s | %s" %
          ("run", "QH", "variant", "QE=QH on D (o/p)", "exact on full (o/p)", "verdict"))
    done = [r for r in results if "eq_var" in r]
    for r in results:
        if "eq_var" not in r:
            print("%-4s %-4s %-10s | %s" % (r["run"], r["qh"], r["variant"],
                                            r.get("error", "skipped")))
            continue
        print("%-4s %-4s %-10s | %-7s / %-7s | %-7s / %-7s   | %s (|RE|-|RH| on full = %+d)" %
              (r["run"], r["qh"], r["variant"], r["eq_var"], r["pred_var"],
               r["eq_full"], r["pred_full"], "MATCH" if r["match"] else "MISMATCH",
               r["delta"]))
    h1 = [r for r in done if r["pred_full"]]
    h2 = [r for r in done if not r["pred_full"]]
    print("\nH1 (sufficiency): %d/%d satisfied-condition runs are exact" %
          (sum(r["eq_full"] for r in h1), len(h1)))
    print("H2 (tightness)  : %d/%d violated-condition runs behave as predicted" %
          (sum(r["match"] for r in h2), len(h2)))
    for r in h2:
        if r["eq_full"]:
            print("   note: %s is exact although its condition is violated -> "
                  "condition not necessary here" % r["run"])
    if len(done) < len(RUNS):
        print("(%d of %d runs had no extracted query or failed)" %
              (len(RUNS) - len(done), len(RUNS)))
    with open("observability_results.csv", "w", newline="") as f:
        cols = ["run", "qh", "variant", "cond", "eq_var", "pred_var",
                "eq_full", "pred_full", "delta", "match", "error", "qe"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({c: r.get(c, "") for c in cols})
    print("wrote observability_results.csv")


def main():
    db = PG(CONN)
    arg = sys.argv[1] if len(sys.argv) > 1 else ("evaluate" if qe_map() else "setup")
    {"setup": step_setup, "evaluate": step_evaluate, "clean": step_clean}[arg](db)


if __name__ == "__main__":
    main()
