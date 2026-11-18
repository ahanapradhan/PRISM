import os
import time

from ...src.pipeline.abstract.Comparator import Comparator


class ResultComparator(Comparator):
    INSERT_BATCH_SIZE = 1000

    def __init__(self, connectionHelper, isHash, core_relations=None):
        super().__init__(connectionHelper, "Result_Comparator", True, core_relations)
        self.isHash = isHash

    def is_match(self, len1, len2):
        self.logger.debug(f"{len1} len1, {len2} len2")
        if self.isHash:
            matched = len1 is not None and len1 == len2
        else:
            matched = super().is_match(len1, len2)
        if matched:
            self._create_working_schema()
        return matched

    def run_diff_queries(self):
        if self.isHash:
            return self.run_hash_diff_queries()
        return super().run_diff_queries()

    def run_hash_diff_queries(self):
        query_r_e = self.connectionHelper.queries.hashtext_query(
            self.r_e, self.get_fully_qualified_table_name(self.r_e)).rstrip().rstrip(';')
        query_r_h = self.connectionHelper.queries.hashtext_query(
            self.r_h, self.get_fully_qualified_table_name(self.r_h)).rstrip().rstrip(';')
        row = self.connectionHelper.execute_sql_fetchone(
            self.connectionHelper.queries.combine_hash_queries(query_r_e, query_r_h))
        if row is None:
            return None, None
        return row[0], row[1]

    def insert_data_into_Qh_table(self, res_Qh, table):
        header = str(res_Qh[0]).replace('\'', '').replace(',)', ')')
        qualified_table = self.get_fully_qualified_table_name(table)
        single_cell_result = len(res_Qh) == 2 and len(res_Qh[1]) == 1
        value_rows = []
        for row in res_Qh[1:]:
            temp = []
            nullrow = True
            for val in row:
                if val not in (None, 'None'):
                    nullrow = False
                temp.append('NULL' if val == 'None' else str(val))
            if nullrow:
                continue
            if single_cell_result:
                value = str(temp[0]).replace(',)', ')').replace("'NULL'", "NULL")
                if not value.startswith('('):
                    value = f"('{value}')"
            else:
                value = str(tuple(temp)).replace(',)', ')').replace("'NULL'", "NULL")
            value_rows.append(value)
            if len(value_rows) == self.INSERT_BATCH_SIZE:
                self._insert_rows(qualified_table, header, value_rows)
                value_rows = []
        if value_rows:
            self._insert_rows(qualified_table, header, value_rows)

    def _insert_rows(self, qualified_table, header, value_rows):
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.insert_values(
                qualified_table, header, value_rows)])


class FinalResultComparator(ResultComparator):
    """Comparator used only for the final answer verification.

    ``GenericPipeLine.verify_correctness`` is the sole caller.  NEP extraction
    keeps using ``ResultComparator`` (through ``NepComparator``), so this class
    cannot change extraction, backup or restore behaviour.

    Both sides are materialized server-side: Q_E becomes the table ``r_e`` and
    Q_H is copied into ``r_h`` by a single ``INSERT ... SELECT``.  The default
    comparator instead fetches every row of Q_H into Python and re-inserts it in
    1000-row batches, and it keeps Q_E as a view, so the query is evaluated once
    for the row count, again for the hash and again for each EXCEPT pass.
    """

    def __init__(self, connectionHelper, isHash, core_relations=None):
        super().__init__(connectionHelper, isHash, core_relations)
        self.phase_timings = {}

    def _record(self, phase, started):
        self.phase_timings[phase] = round(time.time() - started, 3)

    def _drop_relation(self, table):
        """Drop ``table`` whether it currently exists as a view or a table."""
        return self.connectionHelper.queries.drop_view_or_table_cascade(
            self.connectionHelper.config.schema, table)

    def _r_e_columns(self):
        rows, _ = self.connectionHelper.execute_sql_fetchall(
            self.connectionHelper.queries.get_column_details_for_table(
                self.connectionHelper.config.schema, self.r_e))
        return [row[0] for row in rows]

    def _execute_rowcount(self, sql):
        """Run ``sql`` and return the number of rows it wrote, or None on failure."""
        cur = self.connectionHelper.get_cursor()
        self.logger.debug("..cur execute.." + sql)
        try:
            cur.execute(sql.replace("'None'", "NULL"))
            return cur.rowcount
        except Exception as e:
            self.logger.error(e)
            return None

    def create_view_from_Q_E(self, Q_E):
        started = time.time()
        q_e = Q_E.strip().rstrip(';')
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.set_search_path(self.app.data_schema),
             self._drop_relation(self.r_e)])
        self.row_count_r_e = self._execute_rowcount(
            self.connectionHelper.queries.create_unlogged_table_as_query(
                self.get_fully_qualified_table_name(self.r_e), q_e))
        self._record("materialize_r_e", started)
        return self.row_count_r_e

    def create_table_from_Qh(self, Q_h):
        started = time.time()
        q_h = Q_h.strip().rstrip(';')
        r_h = self.get_fully_qualified_table_name(self.r_h)
        self.connectionHelper.execute_sql(
            [self._drop_relation(self.r_h),
             self.connectionHelper.queries.create_unlogged_table_like(
                 r_h, self.get_fully_qualified_table_name(self.r_e))])
        columns = ", ".join(f'"{col}"' for col in self._r_e_columns())
        self.row_count_r_h = self._execute_rowcount(
            self.connectionHelper.queries.insert_into_table_select_columns_from_query(
                r_h, columns, q_h))
        self._record("materialize_r_h", started)

    def run_diff_queries(self):
        if self.isHash:
            started = time.time()
            result = super().run_diff_queries()
            self._record("hash_diff", started)
            return result

        started = time.time()
        r_e = self.get_fully_qualified_table_name(self.r_e)
        r_h = self.get_fully_qualified_table_name(self.r_h)
        row = self.connectionHelper.execute_sql_fetchone(
            self.connectionHelper.queries.select_except_all_existence_flags(r_e, r_h))
        self._record("except_exists", started)
        if row is None:
            return None, None
        return row[0], row[1]

    def run_diff_query_match_and_dropViews(self):
        len1, len2 = self.run_diff_queries()
        self.connectionHelper.execute_sql(
            [self._drop_relation(self.r_e), self._drop_relation(self.r_h)])
        return self.is_match(len1, len2)

    def match(self, Q_h, Q_E):
        # Same flow as Comparator.match, but the row counts come from the
        # materialization statements instead of two extra count(*) scans.
        if Q_E is None:
            self.logger.error("Q_E is none. Please see why.")
            return False
        self.row_count_r_e = self.create_view_from_Q_E(Q_E)
        self.logger.debug(self.row_count_r_e)
        if self.row_count_r_e is None:
            return None
        if self.earlyExit and not self.row_count_r_e:
            return False
        self.create_table_from_Qh(Q_h)
        self.logger.debug(self.r_h, self.row_count_r_h)
        if self.row_count_r_e != self.row_count_r_h:
            matched = False
        else:
            matched = self.run_diff_query_match_and_dropViews()
        if os.environ.get("PRISM_COMPARE_PROFILE"):
            self.logger.info("COMPARE_PHASES " + str(self.phase_timings))
        return matched
