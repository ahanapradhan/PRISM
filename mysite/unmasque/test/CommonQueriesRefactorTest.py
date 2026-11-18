import inspect
import unittest
from types import SimpleNamespace

from mysite.unmasque.src.core.executables.ZeroResultExecutable import ZeroResultExecutable
from mysite.unmasque.src.core.executables.executable import Executable
from mysite.unmasque.src.core.executables.nullfree_executable import NullFreeExecutable
from mysite.unmasque.src.core.result_comparator import FinalResultComparator
from mysite.unmasque.src.util.postgres_queries import PostgresQueries


class _FakeLogger:
    def isEnabledFor(self, level):
        return False

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _FakeConfig:
    schema = "fresh"
    user_schema = "public"
    log_level = "DEBUG"


class _ExecutableConnection:
    def __init__(self):
        self.config = _FakeConfig()
        self.queries = PostgresQueries()
        self.queries.set_schema(self.config.schema)
        self.fetchall_queries = []

    def execute_sql_fetchall(self, sql, logger=None):
        self.fetchall_queries.append(sql)
        return [], None


class _FakeCursor:
    def __init__(self, rowcounts):
        self._rowcounts = list(rowcounts)
        self.executed = []

    @property
    def rowcount(self):
        return self._rowcounts.pop(0) if self._rowcounts else -1

    def execute(self, sql):
        self.executed.append(sql)


class _ComparatorConnection:
    def __init__(self, rowcounts=(3, 3)):
        self.config = _FakeConfig()
        self.queries = PostgresQueries()
        self.queries.set_schema(self.config.schema)
        self.cursor = _FakeCursor(rowcounts)
        self.sql = []
        self.fetchone_queries = []
        self.fetchone_result = (0, 0)
        self.fetchall_queries = []

    def get_cursor(self):
        return self.cursor

    def execute_sql(self, queries, logger=None):
        self.sql.append(list(queries))

    def execute_sql_fetchone(self, sql, logger=None):
        self.fetchone_queries.append(sql)
        return self.fetchone_result

    def execute_sql_fetchall(self, sql, logger=None):
        self.fetchall_queries.append(sql)
        return [("c1",), ("c2",)], None


class QueryBuilderContractTest(unittest.TestCase):
    def test_postgres_queries_is_a_concrete_common_queries(self):
        self.assertFalse(inspect.isabstract(PostgresQueries))
        self.assertIsInstance(PostgresQueries(), PostgresQueries)

    def test_executable_wrapper_and_bounded_probes(self):
        queries = PostgresQueries()

        self.assertEqual(
            "set search_path='fresh'; SET enable_indexscan = on; "
            "SET enable_indexonlyscan = on; SET enable_seqscan = off; select 1;",
            queries.wrap_query_for_executable("fresh", "select 1;"))
        self.assertEqual(
            "SELECT q.* FROM (select 1) AS q LIMIT 1;",
            queries.select_limited_rows_from_query("select 1", 1))
        self.assertEqual(
            "SELECT q.* FROM (select 1) AS q LIMIT 2;",
            queries.select_limited_rows_from_query("select 1", 2))

    def test_nullfree_probe_keeps_row_whole_row_predicate(self):
        queries = PostgresQueries()

        self.assertEqual(
            "SELECT 1 FROM (select 1) AS q "
            "WHERE ROW(q.*) IS NOT NULL LIMIT 1;",
            queries.select_nullfree_existence_from_query("select 1"))

    def test_hash_aggregate_confirmation_keeps_set_order(self):
        queries = PostgresQueries()

        self.assertEqual(
            "SET enable_sort=off; SET enable_hashagg=on; "
            "SET enable_indexscan=off; SET enable_indexonlyscan=off; "
            "SET enable_seqscan=on; select 1;",
            queries.wrap_query_for_hash_aggregate_confirmation("select 1;"))
        self.assertEqual(["SET enable_sort=off;", "SET enable_hashagg=on;"],
                         queries.hash_aggregate_probe_settings())
        self.assertEqual("SHOW enable_sort;", queries.show_configuration("enable_sort"))
        self.assertEqual("SET enable_sort=on;",
                         queries.set_configuration("enable_sort", "on"))

    def test_final_comparator_builders(self):
        queries = PostgresQueries()

        self.assertEqual(
            "set search_path='public';", queries.set_search_path("public"))
        self.assertIn("c.relkind = 'v'",
                      queries.drop_view_or_table_cascade("fresh", "r_e"))
        self.assertIn("EXECUTE 'DROP TABLE fresh.r_e CASCADE';",
                      queries.drop_view_or_table_cascade("fresh", "r_e"))
        self.assertEqual(
            "create unlogged table fresh.r_e as select 1;",
            queries.create_unlogged_table_as_query("fresh.r_e", "select 1"))
        self.assertEqual(
            "create unlogged table fresh.r_h (like fresh.r_e);",
            queries.create_unlogged_table_like("fresh.r_h", "fresh.r_e"))
        self.assertEqual(
            'insert into fresh.r_h ("c1", "c2") select "c1", "c2" from (select 1) as q;',
            queries.insert_into_table_select_columns_from_query(
                "fresh.r_h", '"c1", "c2"', "select 1"))
        self.assertEqual(
            "select exists(select 1 from (select * from fresh.r_e except all "
            "select * from fresh.r_h) as x)::int, "
            "exists(select 1 from (select * from fresh.r_h except all "
            "select * from fresh.r_e) as y)::int;",
            queries.select_except_all_existence_flags("fresh.r_e", "fresh.r_h"))


class ExecutableProbeSqlTest(unittest.TestCase):
    def setUp(self):
        # Executable uses a cached singleton shared by its subclasses; reset it
        # so each probe test gets its own fake connection.
        Executable._instance = None
        ZeroResultExecutable._instance = None
        NullFreeExecutable._instance = None
        self.conn = _ExecutableConnection()

    def test_base_executable_uses_builder_for_prefix_and_probe(self):
        executable = Executable(self.conn)

        executable.doActualJob(["select 1;"])
        self.assertEqual(
            [self.conn.queries.wrap_query_for_executable("fresh", "select 1;")],
            self.conn.fetchall_queries)

        self.conn.fetchall_queries.clear()
        executable.is_query_result_no_full_nullfree_row("select 1;")
        probe = self.conn.queries.select_limited_rows_from_query("select 1", 1)
        self.assertEqual(
            [self.conn.queries.wrap_query_for_executable("fresh", probe)],
            self.conn.fetchall_queries)

    def test_zero_result_executable_uses_builder_for_two_row_probe(self):
        executable = ZeroResultExecutable(self.conn)

        executable.is_query_result_no_full_nullfree_row("select 1;")

        probe = self.conn.queries.select_limited_rows_from_query("select 1", 2)
        self.assertEqual(
            [self.conn.queries.wrap_query_for_executable("fresh", probe)],
            self.conn.fetchall_queries)

    def test_nullfree_executable_uses_builder_for_row_probe(self):
        executable = NullFreeExecutable(self.conn)

        executable.is_query_result_no_full_nullfree_row("select 1;")

        probe = self.conn.queries.select_nullfree_existence_from_query("select 1")
        self.assertEqual(
            [self.conn.queries.wrap_query_for_executable("fresh", probe)],
            self.conn.fetchall_queries)


class FinalComparatorSqlTest(unittest.TestCase):
    def _comparator(self, rowcounts=(3, 3)):
        conn = _ComparatorConnection(rowcounts)
        comparator = object.__new__(FinalResultComparator)
        comparator.connectionHelper = conn
        comparator.logger = _FakeLogger()
        comparator.app = SimpleNamespace(data_schema="public")
        comparator.r_e = "r_e"
        comparator.r_h = "r_h"
        comparator.isHash = False
        comparator.earlyExit = True
        comparator.phase_timings = {}
        comparator.row_count_r_e = 0
        comparator.row_count_r_h = 0
        return comparator, conn

    def test_materialization_and_diff_sql_come_from_builder(self):
        comparator, conn = self._comparator()

        self.assertEqual(3, comparator.create_view_from_Q_E("select * from t"))
        self.assertEqual(
            [conn.queries.set_search_path("public"),
             conn.queries.drop_view_or_table_cascade("fresh", "r_e")],
            conn.sql[-1])
        self.assertEqual(
            conn.queries.create_unlogged_table_as_query(
                "fresh.r_e", "select * from t"),
            conn.cursor.executed[0])

        comparator.create_table_from_Qh("select * from h")
        self.assertEqual(
            [conn.queries.drop_view_or_table_cascade("fresh", "r_h"),
             conn.queries.create_unlogged_table_like("fresh.r_h", "fresh.r_e")],
            conn.sql[-1])
        self.assertEqual(
            conn.queries.insert_into_table_select_columns_from_query(
                "fresh.r_h", '"c1", "c2"', "select * from h"),
            conn.cursor.executed[1])

        conn.fetchone_result = (1, 0)
        self.assertEqual((1, 0), comparator.run_diff_queries())
        self.assertEqual(
            conn.queries.select_except_all_existence_flags("fresh.r_e", "fresh.r_h"),
            conn.fetchone_queries[-1])

        self.assertFalse(comparator.run_diff_query_match_and_dropViews())
        self.assertEqual(
            [conn.queries.drop_view_or_table_cascade("fresh", "r_e"),
             conn.queries.drop_view_or_table_cascade("fresh", "r_h")],
            conn.sql[-1])

    def test_base_hash_and_insert_sql_come_from_builder(self):
        comparator, conn = self._comparator()
        comparator.isHash = True
        conn.fetchone_result = (7, 7)
        comparator.r_e = "re_E"
        comparator.r_h = "rh_E"
        conn.queries.hashtext_query = lambda alias, table: f"hashtext({alias})"

        self.assertEqual((7, 7), comparator.run_hash_diff_queries())
        self.assertEqual(
            conn.queries.combine_hash_queries("hashtext(re_E)", "hashtext(rh_E)"),
            conn.fetchone_queries[-1])

        comparator._insert_rows("fresh.qh", "(a, b)", ["('1', '2')"])
        self.assertEqual(
            conn.queries.insert_values("fresh.qh", "(a, b)", ["('1', '2')"]),
            conn.sql[-1][0])


if __name__ == "__main__":
    unittest.main()
