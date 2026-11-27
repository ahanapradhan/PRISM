from abc import ABC, abstractmethod

from ...src.util.constants import UNMASQUE


class CommonQueries(ABC):
    schema = None

    def set_schema(self, schema):
        self.schema = schema

    @abstractmethod
    def select_row_count_from_query(self, query):
        pass

    @abstractmethod
    def get_explain_query(self, sql):
        pass

    @abstractmethod
    def analyze_table(self, tab):
        pass

    @abstractmethod
    def drop_schema(self, schema):
        pass

    @abstractmethod
    def create_schema(self, schema):
        pass

    @abstractmethod
    def drop_table(self, tab):
        pass

    @abstractmethod
    def drop_table_cascade(self, tab):
        pass

    @abstractmethod
    def alter_table_rename_to(self, tab, retab):
        pass

    @abstractmethod
    def alter_view_rename_to(self, tab, retab):
        pass

    @abstractmethod
    def create_table_like(self, tab, ctab):
        pass

    @abstractmethod
    def create_table_as_select_star_from(self, tab, fromtab):
        pass

    @abstractmethod
    def create_table_as_select_star_from_where(self, tab, fromtab, where):
        pass

    @abstractmethod
    def get_row_count(self, tab):
        pass

    @abstractmethod
    def get_non_null_row_count(self, tab):
        pass

    @abstractmethod
    def get_star(self, tab):
        pass

    @abstractmethod
    def get_star_from_except_all_get_star_from(self, tab1, tab2):
        pass

    def get_restore_name(self, tab):
        return f"{tab}_restore"

    def get_backup(self, tab):
        return f"{tab}_backup"

    @abstractmethod
    def get_min_max_ctid(self, tab):
        pass

    @abstractmethod
    def select_rows_by_ctid_order(self, tab, limit):
        pass

    @abstractmethod
    def drop_view(self, tab):
        pass

    def get_dmin_tabname(self, tab):
        return f"{tab}_{UNMASQUE}_dmin"

    def get_union_tabname(self, tab):
        return f"{tab}_{UNMASQUE}_union"

    @abstractmethod
    def create_view_as(self, view, q):
        pass

    @abstractmethod
    def create_view_as_select_star_where_ctid(self, mid_ctid1, start_ctid, view, tab):
        pass

    @abstractmethod
    def get_min_max_of_col(self, tab, col):
        pass

    @abstractmethod
    def get_pk_columns(self, schema, tab):
        pass

    @abstractmethod
    def create_view_as_select_star_where_pk_range(self, view, tab, col, lo, hi):
        pass

    @abstractmethod
    def create_table_as_select_star_from_pk_range(self, tab, fromtab, col, lo, hi):
        pass

    @abstractmethod
    def create_table_as_select_star_from_ctid(self, end_ctid, start_ctid, tab, fromtab):
        pass

    @abstractmethod
    def get_ctid_from(self, min_or_max, tabname):
        pass

    @abstractmethod
    def truncate_table(self, table):
        pass

    @abstractmethod
    def insert_into_tab_attribs_format(self, att_order, esc_string, tab):
        pass

    @abstractmethod
    def update_key_attrib_with_val(self, tab, attrib, value, prev, qoted):
        pass

    @abstractmethod
    def update_tab_attrib_with_value(self, tab, attrib, value):
        pass

    @abstractmethod
    def update_tab_attrib_with_quoted_value(self, tab, attrib, value):
        pass

    @abstractmethod
    def update_sql_query_tab_attribs(self, tab, attrib):
        pass

    def update_sql_query_tab_date_attrib_value(self, tab, attrib, value):
        return self.update_tab_attrib_with_value(tab, attrib, value)

    @abstractmethod
    def form_update_query_with_value(self, update_string, datatype, val):
        pass

    @abstractmethod
    def get_column_details_for_table(self, schema, tab):
        pass

    @abstractmethod
    def select_attribs_from_relation(self, tab_attribs, relation):
        pass

    @abstractmethod
    def insert_into_tab_select_star_fromtab(self, tab, fromtab):
        pass

    @abstractmethod
    def insert_into_tab_select_star_fromtab_with_ctid(self, tab, fromtab, ctid):
        pass

    @abstractmethod
    def insert_into_tab_select_star_from_ctid_range(self, tab, fromtab, start_ctid, end_ctid=None):
        pass

    @abstractmethod
    def select_ctid_from_tabname_offset(self, tabname, offset):
        pass

    @abstractmethod
    def select_next_ctid(self, tabname, mid_ctid1):
        pass

    @abstractmethod
    def select_previous_ctid(self, tab, ctid1):
        pass

    @abstractmethod
    def select_max_ctid(self, tab):
        pass

    @abstractmethod
    def select_start_ctid_of_any_table(self):
        return '(0,1)'

    @abstractmethod
    def hashtext_query(self, tab, qualified_name):
        pass

    @abstractmethod
    def create_table_as_select_star_from_limit_1(self, tab, fromtab):
        pass

    @abstractmethod
    def wrap_query_for_executable(self, schema, query):
        pass

    @abstractmethod
    def select_limited_rows_from_query(self, query, limit):
        pass

    @abstractmethod
    def select_nullfree_existence_from_query(self, query):
        pass

    @abstractmethod
    def wrap_query_for_hash_aggregate_confirmation(self, query):
        pass

    @abstractmethod
    def show_configuration(self, setting):
        pass

    @abstractmethod
    def set_configuration(self, setting, value):
        pass

    @abstractmethod
    def hash_aggregate_probe_settings(self):
        pass

    @abstractmethod
    def set_search_path(self, schema):
        pass

    @abstractmethod
    def combine_hash_queries(self, left_query, right_query):
        pass

    @abstractmethod
    def insert_values(self, table, header, value_rows):
        pass

    @abstractmethod
    def drop_view_or_table_cascade(self, schema, table):
        pass

    @abstractmethod
    def create_unlogged_table_as_query(self, table, query):
        pass

    @abstractmethod
    def create_unlogged_table_like(self, table, like_table):
        pass

    @abstractmethod
    def insert_into_table_select_columns_from_query(self, table, columns, query):
        pass

    @abstractmethod
    def select_except_all_existence_flags(self, left_table, right_table):
        pass

    # Result comparison canonicalizes every projected value to trimmed text.
    # UNION arm order decides the first arm's type/typmod in PostgreSQL; two
    # semantically identical results can therefore differ only in padding or
    # representation. Casting both sides to text and trimming surrounding
    # whitespace makes the comparator depend on the values, not on that order.
    CANONICAL_TRIM_CHARS = " \\t\\n\\r\\f\\v"

    def quote_identifier(self, identifier):
        return '"' + str(identifier).replace('"', '""') + '"'

    def canonical_text_expression(self, column, alias=None):
        quoted = self.quote_identifier(column)
        if alias is not None:
            quoted = f"{self.quote_identifier(alias)}.{quoted}"
        return f"btrim({quoted}::text, E'{self.CANONICAL_TRIM_CHARS}')"

    def canonical_select_list(self, columns, alias=None):
        return ", ".join(
            f"{self.canonical_text_expression(column, alias)} AS {self.quote_identifier(column)}"
            for column in columns
        )

    def canonical_query(self, query, columns):
        return f"select {self.canonical_select_list(columns, 'q')} from ({query}) as q"

    def insert_canonical_into_table_select_columns_from_query(self, table, columns, query):
        quoted_columns = ", ".join(self.quote_identifier(column) for column in columns)
        return (
            f"insert into {table} ({quoted_columns}) "
            f"select {self.canonical_select_list(columns, 'q')} from ({query}) as q;"
        )
