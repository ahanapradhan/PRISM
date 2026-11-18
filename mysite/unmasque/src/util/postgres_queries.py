from .abstract_queries import CommonQueries
from .constants import WORKING_SCHEMA
from .utils import get_format


class PostgresQueries(CommonQueries):
    schema = WORKING_SCHEMA

    def _create_table(self, tab, definition, if_not_exists=False):
        """Build a CREATE TABLE statement, unlogged for working-schema tables."""
        schema = self.schema or WORKING_SCHEMA
        table_kind = "unlogged table" if str(tab).startswith(f"{schema}.") else "table"
        exists = " if not exists" if if_not_exists else ""
        return f"Create {table_kind}{exists} {tab} {definition}; "

    def create_table_as_select_star_from_where(self, tab, fromtab, where):
        return self._create_table(tab, f"as (Select * from {fromtab} where {where})")

    def create_table_as_select_star_from_limit_1(self, tab, fromtab):
        return self._create_table(tab, f"as (Select * from {fromtab} limit 1)")

    def form_update_query_with_value(self, update_string, datatype, val):
        update_val = get_format(datatype, val)
        return f"{update_string} {update_val};"

    DEBUG_QUERY = "select pid, state, query from pg_stat_activity where datname = 'tpch';"
    TERMINATE_STUCK_QUERIES = "SELECT pg_terminate_backend(pid);"

    def get_explain_query(self, sql):
        return f"EXPLAIN {sql}"

    def analyze_table(self, tab):
        return f"ANALYZE {tab};"

    def drop_schema(self, schema):
        return f"Drop Schema if exists {schema} cascade;"

    def create_schema(self, schema):
        return f"Create Schema {schema};"

    def drop_table(self, tab):
        return f"drop table if exists {tab};"

    def drop_table_cascade(self, tab):
        return f"drop table if exists {tab} CASCADE;"

    def alter_table_rename_to(self, tab, retab):
        return f"Alter table if exists {tab} rename to {retab};"

    def alter_view_rename_to(self, tab, retab):
        return f"Alter view {tab} rename to {retab};"

    def create_table_like(self, tab, ctab):
        return self._create_table(tab, f"(like {ctab} including indexes)", if_not_exists=True)

    def create_table_as_select_star_from(self, tab, fromtab):
        return self._create_table(tab, f"as select * from {fromtab}", if_not_exists=True)

    def select_row_count_from_query(self, query):
        return f"select count(*) from ({query});"

    def get_row_count(self, tab):
        return f"select count(*) from {tab};"

    def get_non_null_row_count(self, tab):
        pass

    def get_star(self, tab):
        return f"select * from {tab};"

    def get_star_from_except_all_get_star_from(self, tab1, tab2):
        return f"(select * from {tab1} except all select * from {tab2})"

    def get_min_max_ctid(self, tab):
        return f"select min(ctid), max(ctid) from {tab};"

    def select_rows_by_ctid_order(self, tab, limit):
        return f"select ctid, * from {tab} order by ctid limit {limit};"

    def get_min_max_of_col(self, tab, col):
        return f"select min({col}), max({col}) from {tab};"

    def get_pk_columns(self, schema, tab):
        """Primary-key column names of ``schema.tab`` in key order, from the catalog."""
        return (f"select a.attname from pg_index i "
                f"join pg_class c on c.oid = i.indrelid "
                f"join pg_namespace n on n.oid = c.relnamespace "
                f"join pg_attribute a on a.attrelid = c.oid and a.attnum = any(i.indkey::int2[]) "
                f"where i.indisprimary and n.nspname = '{schema}' and c.relname = '{tab}' "
                f"order by array_position(i.indkey::int2[], a.attnum);")

    def drop_view(self, tab):
        return f"drop view if exists {tab} cascade;"

    def create_view_as(self, view, q):
        return f"create view {view}  as {q}"

    def create_view_as_select_star_where_ctid(self, mid_ctid1, start_ctid, view, tab):
        _start_citd = str(start_ctid)
        _end_ctid = str(mid_ctid1)
        return f"create view {view} as select * from {tab} where ctid >= '{_start_citd}' and ctid <= '{_end_ctid}';"

    def create_view_as_select_star_where_pk_range(self, view, tab, col, lo, hi):
        """Half-open PK range view: rows with ``col`` in ``[lo, hi)``."""
        return (f"create view {view} as select * from {tab} "
                f"where {col} >= {self._format_pk_value(lo)} and {col} < {self._format_pk_value(hi)};")

    def create_table_as_select_star_from_pk_range(self, tab, fromtab, col, lo, hi):
        """Materialize rows with ``col`` in ``[lo, hi)`` into a real table."""
        return self._create_table(tab, f"as select * from {fromtab} "
                                       f"where {col} >= {self._format_pk_value(lo)} "
                                       f"and {col} < {self._format_pk_value(hi)}")

    @staticmethod
    def _format_pk_value(val):
        import datetime
        if isinstance(val, datetime.datetime):
            return f"'{val.isoformat(sep=' ')}'"
        if isinstance(val, datetime.date):
            return f"'{val.isoformat()}'"
        return str(val)

    def create_table_as_select_star_from_ctid(self, end_ctid, start_ctid, tab, fromtab):
        _start_citd = str(start_ctid)
        _end_ctid = str(end_ctid)
        return self._create_table(tab, f"as select * from {fromtab} "
                                       f"where ctid >= '{_start_citd}' and ctid <= '{_end_ctid}'")

    def get_ctid_from(self, min_or_max, tabname):
        return f"select {min_or_max}(ctid) from {tabname};"

    def truncate_table(self, table):
        return f"Truncate Table {table};"

    def insert_into_tab_attribs_format(self, att_order, esc_string, tab):
        if esc_string == "":
            _count = att_order.count(",")
            esc_list = [f"%s"] * (_count + 1)
            esc_string = ",".join(esc_list)
            esc_string = f"({esc_string})"
        return f"INSERT INTO {tab} {att_order}  VALUES {esc_string};"

    def update_key_attrib_with_val(self, tab, attrib, value, prev, qoted):
        if qoted:
            value = f"'{value}'"
            prev = f"'{prev}'"
        query = f"UPDATE {tab} SET {attrib} = CASE WHEN {attrib} = {prev} THEN {value} WHEN {attrib} = {value} THEN {prev} ELSE {attrib} END;"
        return query

    def update_tab_attrib_with_value(self, tab, attrib, value):
        str_value = str(value)
        query = f"UPDATE {tab}  SET {attrib}={str_value};"
        # print(query)
        return query

    def update_tab_attrib_with_quoted_value(self, tab, attrib, value):
        query = f"UPDATE {tab}  SET {attrib}= '{value}';"
        # print(query)
        return query

    def update_sql_query_tab_attribs(self, tab, attrib):
        tabname = str(tab)
        col = str(attrib)
        return f"update {tabname} set {col} = "

    def get_column_details_for_table(self, schema, tab):
        return f"select column_name, data_type, character_maximum_length from information_schema.columns where " \
               f"table_schema = '{schema}' and table_name = '{tab}';"

    def select_attribs_from_relation(self, tab_attribs, relation):
        attribs = ", ".join(tab_attribs)
        return f"select {attribs} from {relation};"

    def insert_into_tab_select_star_fromtab(self, tab, fromtab):
        return f"Insert into {tab} Select * from {fromtab};"

    def insert_into_tab_select_star_fromtab_with_ctid(self, tab, fromtab, ctid):
        return f"Insert into {tab} (Select * from {fromtab} Where ctid = {ctid});"

    def insert_into_tab_select_star_from_ctid_range(self, tab, fromtab, start_ctid, end_ctid=None):
        """Copy a disjoint ctid page range with reversed physical order.

        ``end_ctid`` is exclusive.  The explicit ``ORDER BY ctid DESC`` makes
        each worker insert its slice back-to-front; combined with concurrent
        workers this deliberately changes the physical row order in the
        destination (working) table compared with the source table.
        """
        where = f"ctid >= '{start_ctid}'"
        if end_ctid is not None:
            where += f" and ctid < '{end_ctid}'"
        return f"Insert into {tab} Select * from {fromtab} Where {where} Order By ctid Desc;"

    def select_ctid_from_tabname_offset(self, tabname, offset):
        return f"Select ctid from {tabname} offset {offset} Limit 1;"

    def select_next_ctid(self, tabname, mid_ctid1):
        return f"Select Min(ctid) from {tabname} Where ctid > '{mid_ctid1}';"

    def select_previous_ctid(self, tab, ctid1):
        return f"Select MAX(ctid) from {tab} Where ctid < '{ctid1}';"

    def select_max_ctid(self, tab):
        return f"Select MAX(ctid) from {tab};"

    def select_start_ctid_of_any_table(self):
        return '(0,1)'

    def hashtext_query(self, tab, qualified_name):
        return f"select sum(hashtext) from (select hashtext({tab}::TEXT) FROM {qualified_name}) as T;"

    def wrap_query_for_executable(self, schema, query):
        return (f"set search_path='{schema}'; "
                "SET enable_indexscan = on; SET enable_indexonlyscan = on; "
                f"SET enable_seqscan = off; {query}")

    def select_limited_rows_from_query(self, query, limit):
        return f"SELECT q.* FROM ({query}) AS q LIMIT {limit};"

    def select_nullfree_existence_from_query(self, query):
        return f"SELECT 1 FROM ({query}) AS q WHERE ROW(q.*) IS NOT NULL LIMIT 1;"

    HASH_AGGREGATE_PREFIX = (
        "SET enable_sort=off; SET enable_hashagg=on; "
        "SET enable_indexscan=off; SET enable_indexonlyscan=off; "
        "SET enable_seqscan=on; "
    )

    def wrap_query_for_hash_aggregate_confirmation(self, query):
        return self.HASH_AGGREGATE_PREFIX + query

    def show_configuration(self, setting):
        return f"SHOW {setting};"

    def set_configuration(self, setting, value):
        return f"SET {setting}={value};"

    def hash_aggregate_probe_settings(self):
        return [self.set_configuration("enable_sort", "off"),
                self.set_configuration("enable_hashagg", "on")]

    def set_search_path(self, schema):
        return f"set search_path='{schema}';"

    def combine_hash_queries(self, left_query, right_query):
        return f"select ({left_query}), ({right_query});"

    def insert_values(self, table, header, value_rows):
        return f"INSERT INTO {table}{header} VALUES {', '.join(value_rows)};"

    def drop_view_or_table_cascade(self, schema, table):
        return (
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = '{schema}' AND c.relname = '{table}' AND c.relkind = 'v') THEN "
            f"EXECUTE 'DROP VIEW {schema}.{table} CASCADE'; "
            "ELSIF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = '{schema}' AND c.relname = '{table}') THEN "
            f"EXECUTE 'DROP TABLE {schema}.{table} CASCADE'; "
            "END IF; END $$;")

    def create_unlogged_table_as_query(self, table, query):
        return f"create unlogged table {table} as {query};"

    def create_unlogged_table_like(self, table, like_table):
        return f"create unlogged table {table} (like {like_table});"

    def insert_into_table_select_columns_from_query(self, table, columns, query):
        return f"insert into {table} ({columns}) select {columns} from ({query}) as q;"

    def select_except_all_existence_flags(self, left_table, right_table):
        only_left = self.get_star_from_except_all_get_star_from(left_table, right_table)
        only_right = self.get_star_from_except_all_get_star_from(right_table, left_table)
        return (f"select exists(select 1 from {only_left} as x)::int, "
                f"exists(select 1 from {only_right} as y)::int;")
