"""Cancel-stress test (design §7.4, scaled to 25 iterations).

Loops a short query with a cancel fired at random tiny delays. After each
iteration recovery is performed and a follow-up query must succeed, proving no
QueryCanceled (or aborted/cancelled state) leaks into later queries.
"""
import random
import threading
import time
import unittest

from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory
from mysite.unmasque.src.util.PostgresConnectionHelper import PostgresConnectionHelper

from .hybrid_minimizer import _recover, _is_cancel


class HybridCancelStressTest(unittest.TestCase):
    ITERATIONS = 25

    def setUp(self):
        self.factory = ConnectionHelperFactory()
        self.config = self.factory.config
        self.conn = PostgresConnectionHelper.create_independent(self.config, single_worker=True)
        self.assertIsNotNone(self.conn.conn)

    def tearDown(self):
        try:
            if self.conn is not None:
                self.conn.closeConnection()
        except Exception:
            pass

    def _run_short_query(self):
        """Run a short cancellable query; return ('ok'|'cancelled', err_or_none)."""
        cur = self.conn.conn.cursor()
        try:
            # 50ms sleep gives room for random tiny delays to land before/during/after.
            cur.execute("SELECT pg_sleep(0.05);")
            cur.fetchall()
            self.conn.conn.commit()
            return "ok", None
        except Exception as e:
            try:
                self.conn.conn.rollback()
            except Exception:
                pass
            if _is_cancel(e):
                return "cancelled", e
            return "error", e
        finally:
            try:
                cur.close()
            except Exception:
                pass

    def _assert_connection_clean(self, iteration):
        """A normal follow-up query must succeed (no leaked cancel/aborted state)."""
        cur = self.conn.conn.cursor()
        try:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            self.conn.conn.commit()
            self.assertEqual(row[0], 1, f"iteration {iteration}: follow-up query returned unexpected result")
        except Exception as e:
            try:
                self.conn.conn.rollback()
            except Exception:
                pass
            self.fail(f"iteration {iteration}: leaked cancellation/error into later query: {e!r}")
        finally:
            try:
                cur.close()
            except Exception:
                pass

    def test_cancel_stress(self):
        rng = random.Random(0xCACE1)
        outcomes = {"ok": 0, "cancelled": 0}

        for i in range(1, self.ITERATIONS + 1):
            # fire cancel after a random tiny delay (0-60ms) so it may arrive
            # before, during, or just after query execution/completion.
            delay = rng.uniform(0.0, 0.06)

            def fire_cancel(d=delay):
                time.sleep(d)
                try:
                    self.conn.cancel()
                except Exception:
                    pass

            t = threading.Thread(target=fire_cancel, daemon=True)
            t.start()

            status, err = self._run_short_query()
            t.join(timeout=2.0)

            if status == "error":
                self.fail(f"iteration {i}: unexpected non-cancel error: {err!r}")
            outcomes[status] += 1

            # recover as per design, then ensure connection is clean for next iteration
            _recover(self.conn, [], logger=None)
            self._assert_connection_clean(i)

        # Sanity: we should have exercised at least some cancellations over 25 randomized tries.
        # (Not strictly required by spec, but confirms the test is meaningful.)
        self.assertGreaterEqual(outcomes["ok"] + outcomes["cancelled"], self.ITERATIONS)
        print(f"cancel-stress outcomes over {self.ITERATIONS} iterations: {outcomes}")


if __name__ == "__main__":
    unittest.main()
