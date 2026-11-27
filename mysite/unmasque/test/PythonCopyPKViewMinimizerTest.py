"""
Compare ViewMinimizer (ctid) vs PKView_Minimizer (PK range) on MQ18,
with union + outer-join detection enabled, using the EXISTING Python
backup/restore (SchemaSanitizer), not pgcopy.

Initiator is NOT run. The test does Initiator's essential job itself
(prepare_working_schema): create a fresh working schema, back up the MQ18
core tables from the user schema, and read their row counts. The pk-fk file
parsing, key-list building and scale-down of Initiator are not needed here:
PKView_Minimizer reads the PK columns from pkfkrelations.csv on its own.

Place in mysite/unmasque/test/.
"""
import time
import unittest

# ----------------------------------------------------------------- ADAPT block
CORE_TABLES = ["customer", "orders", "lineitem"]       # MQ18 core relations
CONFIG_FLAGS = {"detect_union": True, "detect_oj": True}  # rename to your real flags


def make_connection_helper():
    """Return a ConnectionHelper. Replace with your project's factory."""
    from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory  # adjust path
    return ConnectionHelperFactory().createConnectionHelper()


def get_mq18():
    return """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%' 
  AND c_custkey = o_custkey 
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;"""
# ---------------------------------------------------------------------------

from mysite.unmasque.src.core.abstract.ExtractorBase import Base   # noqa: E402
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer    # noqa: E402
from mysite.unmasque.src.core.PKView_Minimizer import PKView_Minimizer  # noqa: E402


def run_minimizer(m, query):
    """Minimizer.doJob(*args) -> extract_params_from_args returns args[0],
    so the query itself must be passed (NOT wrapped in a list)."""
    ret = m.doActualJob(query)
    print(f"  [{type(m)}] doJob returned {ret!r}")
    return ret


class PKViewMinimizerPerf(unittest.TestCase):

    def setUp(self):
        self.query = get_mq18()
        self.conn = make_connection_helper()
        self.conn.connectUsingParams()
        for k, v in CONFIG_FLAGS.items():
            setattr(self.conn.config, k, v)
        self.cfg = self.conn.config

    def tearDown(self):
        self.conn.closeConnection()

    # ------------------------------------------------------------ original untouched
    def _fingerprint(self):
        """Row count + index count of each core table in the USER schema."""
        s = self.cfg.user_schema
        fp = {}
        try:
            for t in CORE_TABLES:
                rows = self.conn.execute_sql_fetchone_0(f"SELECT count(*) FROM {s}.{t}")
                idx = self.conn.execute_sql_fetchone_0(
                    f"SELECT count(*) FROM pg_indexes WHERE schemaname='{s}' AND tablename='{t}'")
                fp[t] = (rows, idx)
        except Exception:
            self.conn.conn.rollback()      # never leave the transaction aborted
            raise
        return fp

    # ------------------------------------------------------------ Initiator's job
    def prepare_working_schema(self):
        """Fresh working schema + Python-copy backup of the core tables.
        Returns {table: row_count}. Replaces Initiator.doJob for this test."""
        prep = Base(self.conn, "TestPrep")              # Base -> SchemaSanitizer helpers
        prep.set_all_relations(list(CORE_TABLES))
        prep._create_working_schema()                   # drop + create working schema
        prep.take_backup()                              # user_schema.t -> working_schema.t
        return dict(prep.get_all_sizes())               # counts from the user schema

    # ------------------------------------------------------------ the test
    def _one_run(self, cls):
        all_sizes = self.prepare_working_schema()
        # Fingerprint AFTER the backup: take_backup() may itself create indexes
        # (config.use_index), which is not the minimizer's doing. We only want
        # to prove that the MINIMIZER leaves the original tables alone.
        before = self._fingerprint()
        if cls == "ViewMinimizer":
            m = ViewMinimizer(self.conn, CORE_TABLES, all_sizes, False)
        else:
            m = PKView_Minimizer(self.conn, CORE_TABLES, all_sizes, False)
        t0 = time.perf_counter()
        run_minimizer(m, self.query)
        elapsed = time.perf_counter() - t0

        self.assertEqual(before, self._fingerprint(),
                         f"{cls} modified the original tables "
                         "(row count or index count changed)")

        # Judge success by the resulting state, not by doJob's return value.
        sizes = {}
        for t in CORE_TABLES:
            dmin = self.conn.queries.get_dmin_tabname(t)
            sizes[t] = int(self.conn.execute_sql_fetchone_0(
                f"SELECT count(*) FROM {self.cfg.schema}.{dmin}"))
        self.assertTrue(m.sanity_check(self.query),
                        f"{cls}: app returns no result on the minimized database")
        return elapsed, sizes

    def test_compare_on_mq18(self):
        results = {}
        for cls in ("ViewMinimizer", "PKView_Minimizer"):
            results[cls] = self._one_run(cls)

        print("\n=== MQ18 | union+OJ | Python copy backup/restore ===")
        for name, (sec, sizes) in results.items():
            print(f"{name:<18} {sec:9.2f}s   D_min sizes: {sizes}")
        t_ctid, t_pk = results["ViewMinimizer"][0], results["PKView_Minimizer"][0]
        print(f"speed-up (ctid/pk): {t_ctid / t_pk:.2f}x")

        for name, (_, sizes) in results.items():
            for t, n in sizes.items():
                self.assertGreaterEqual(n, 1, f"{name}: {t} became empty")


if __name__ == "__main__":
    unittest.main()