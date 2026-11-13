"""
Compare ViewMinimizer (ctid) vs PKView_Minimizer (PK range) on MQ18,
with union + outer-join detection enabled and native (pgcopy) backup/restore.

Place in mysite/unmasque/test/.  Everything environment-specific is in the
ADAPT block; the rest only relies on the classes shown in the repo.

Env overrides:  PGCOPY_BIN   path to pgcopy / pgcopy.exe
                PGCOPY_CONNINFO  libpq conninfo string
"""
import os
import pathlib
import subprocess
import time
import unittest

# ----------------------------------------------------------------- ADAPT block
CORE_TABLES = ["customer", "orders", "lineitem"]       # MQ18 core relations
CONFIG_FLAGS = {"detect_union": True, "detect_oj": True, "use_native_copy": True}  # rename to your flags
PGCOPY_BIN = os.environ.get(
    "PGCOPY_BIN",
    str(pathlib.Path(__file__).resolve().parents[1] / "native" /
        ("pgcopy.exe" if os.name == "nt" else "pgcopy")))


def make_connection_helper():
    """Return a connected ConnectionHelper. Replace with your project's factory."""
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

from mysite.unmasque.src.core.initialization import Initiator            # noqa: E402  (adjust if needed)
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer    # noqa: E402
from mysite.unmasque.src.core.PKView_Minimizer import PKView_Minimizer  # noqa: E402


def run_minimizer(m, query):
    """Minimizer.extract_params_from_args may expect either the query or [query]."""
    args = [query] if isinstance(m.extract_params_from_args([query]), str) else query
    return m.doJob(args)


class PKViewMinimizerPerf(unittest.TestCase):

    def setUp(self):
        self.query = get_mq18()
        if self.query is None:
            self.skipTest("MQ18 not found; fix get_mq18()")
        if not pathlib.Path(PGCOPY_BIN).exists():
            self.skipTest(f"pgcopy binary not found at {PGCOPY_BIN}")
        self.conn = make_connection_helper()
        self.conn.connectUsingParams()
        for k, v in CONFIG_FLAGS.items():
            setattr(self.conn.config, k, v)
        self.cfg = self.conn.config

    def tearDown(self):
        self.conn.closeConnection()

    # ------------------------------------------------------------ native restore
    def _conninfo(self):
        if os.environ.get("PGCOPY_CONNINFO"):
            return os.environ["PGCOPY_CONNINFO"]
        c = self.cfg
        return (f"host={c.host} port={c.port} dbname={c.dbname} "
                f"user={c.user} password={c.password}")          # adjust attribute names

    def native_restore(self):
        """Fresh working schema, then restore CORE_TABLES from the user schema via pgcopy."""
        self.conn.execute_sql([f"DROP SCHEMA IF EXISTS {self.cfg.schema} CASCADE;",
                               f"CREATE SCHEMA {self.cfg.schema};"])
        out = subprocess.run(
            [PGCOPY_BIN, "--conninfo", self._conninfo(), "--source", self.cfg.user_schema,
             "--dest", self.cfg.schema, "--tables", ",".join(CORE_TABLES),
             "--mode", "restore", "--sql", "ctas"],
            capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("FAILURES\t0", out.stdout.replace("\r", ""))

    # ------------------------------------------------------------ original untouched
    def _fingerprint(self):
        s = self.cfg.user_schema
        fp = {}
        for t in CORE_TABLES:
            rows = self.conn.execute_sql_fetchone_0(f"SELECT count(*) FROM {s}.{t}")
            idx = self.conn.execute_sql_fetchone_0(
                f"SELECT count(*) FROM pg_indexes WHERE schemaname='{s}' AND tablename='{t}'")
            fp[t] = (rows, idx)
        return fp

    # ------------------------------------------------------------ the test
    def _one_run(self, cls):
        init = Initiator(self.conn)
        self.assertTrue(init.doJob(None))
        self.native_restore()                       # identical starting state for both classes
        m = cls(self.conn, CORE_TABLES, dict(init.all_sizes), False)
        t0 = time.perf_counter()
        ok = run_minimizer(m, self.query)
        elapsed = time.perf_counter() - t0
        self.assertTrue(ok)
        sizes = {t: int(self.conn.execute_sql_fetchone_0(
            f"SELECT count(*) FROM {self.cfg.schema}.{self.conn.queries.get_dmin_tabname(t)}"))
            for t in CORE_TABLES}
        return elapsed, sizes

    def test_compare_on_mq18(self):
        before = self._fingerprint()
        results = {}
        for cls in (ViewMinimizer, PKView_Minimizer):
            results[cls.__name__] = self._one_run(cls)
        self.assertEqual(before, self._fingerprint(),
                         "original tables were modified (row count or index count changed)")

        print("\n=== MQ18 | union+OJ | native copy ===")
        for name, (sec, sizes) in results.items():
            print(f"{name:<18} {sec:9.2f}s   D_min sizes: {sizes}")
        t_ctid, t_pk = results["ViewMinimizer"][0], results["PKView_Minimizer"][0]
        print(f"speed-up (ctid/pk): {t_ctid / t_pk:.2f}x")

        for name, (_, sizes) in results.items():
            for t, n in sizes.items():
                self.assertGreaterEqual(n, 1, f"{name}: {t} became empty")


if __name__ == "__main__":
    unittest.main()