import copy

from ...util.Log import Log
from ...util.constants import UNMASQUE
from ...util.native_copy import (
    NativeCopyError,
    default_index_threads,
    default_threads,
    native_copy_available,
    run_native_copy,
)
from ....src.core.abstract.abstractConnection import AbstractConnectionHelper
from typing import List


class SchemaSanitizer:

    def __init__(self, connectionHelper: AbstractConnectionHelper, all_sizes=None):
        if all_sizes is None:
            all_sizes = {}
        self.all_sizes = all_sizes
        self.all_relations = []
        self.connectionHelper = connectionHelper
        self.logger = Log("SchemaSanitizer", connectionHelper.config.log_level)

    def remove_footprint(self):
        self.connectionHelper.execute_sql([f"Drop Schema if exists {self.connectionHelper.config.schema} cascade;"],
                                          self.logger)

    def _create_working_schema(self):
        self.remove_footprint()
        self.connectionHelper.execute_sql([f"Create Schema {self.connectionHelper.config.schema};"], self.logger)

    def get_fully_qualified_table_name(self, table):
        return f"{self.connectionHelper.config.schema}.{table}"

    def get_original_table_name(self, table):
        return f"{self.connectionHelper.config.user_schema}.{table}"

    def set_all_relations(self, relations: List[str]):
        self.all_relations.extend(copy.copy(relations))

    def _native_copy_enabled(self):
        # Mock/test connection helpers do not expose a complete libpq config,
        # so native_copy_available() rejects them and the Python path stays in
        # use even when the binary happens to be built on this machine.
        return native_copy_available(getattr(self.connectionHelper, "config", None))

    def _end_open_transaction(self):
        """Release locks held by this connection before a native worker runs.

        Native workers use their own libpq connections. If the planning
        connection still has an open transaction, its table locks can block the
        native DROP/CREATE/INSERT statements indefinitely.
        """
        try:
            self.connectionHelper.commit_transaction()
        except Exception:
            try:
                self.connectionHelper.rollback_transaction()
            except Exception:
                pass

    def _known_sizes(self, tables, sizes=None):
        sizes = self.all_sizes if sizes is None else sizes
        known = {}
        for table in tables:
            value = sizes.get(table)
            if isinstance(value, int) and value >= 0:
                known[table] = value
        return known or None

    def _log_native_result(self, action, result):
        self.logger.debug(
            f"Native {action}: {len(result.tables)} table(s) in "
            f"{result.total_seconds:.3f}s (copy={result.copy_seconds:.3f}s, "
            f"index={result.index_seconds:.3f}s)"
        )
        for index in result.index_failures:
            # Index failures are intentionally non-fatal: a source table may
            # have no usable index definition.
            self.logger.info(
                f"Native {action} index skipped for {index.table}: "
                f"{index.error or 'index build failed'}"
            )

    def take_backup(self, relations=None, sizes=None):
        self._create_working_schema()
        tables = list(self.all_relations if relations is None else relations)
        if not tables:
            return
        sizes = self.all_sizes if sizes is None else sizes

        if self._native_copy_enabled():
            try:
                if self.connectionHelper.config.use_index:
                    for table in tables:
                        self.__create_tab_indexes(table)
                for table in tables:
                    self.drop_derived_relations(table)
                self._end_open_transaction()
                result = run_native_copy(
                    self.connectionHelper.config,
                    source_schema=self.connectionHelper.config.user_schema,
                    dest_schema=self.connectionHelper.config.schema,
                    tables=tables,
                    sql="like_insert",
                    rows=self._known_sizes(tables, sizes),
                    max_threads=default_threads(),
                    index_threads=default_index_threads(),
                    logger=self.logger,
                )
                self._log_native_result("backup", result)
                return
            except NativeCopyError as error:
                self.logger.error(
                    f"Native backup failed, falling back to Python copy: {error}"
                )

        for table in tables:
            self.backup_one_table(table, use_native=False)

    def sanitize(self):
        self.connectionHelper.begin_transaction()
        tables = self.all_relations  # self.connectionHelper.get_all_tables_for_restore()
        for table in tables:
            # This method intentionally keeps all restores in the caller's
            # transaction, so native workers (separate connections) cannot join
            # it. Keep this path on the Python copy implementation.
            self.sanitize_one_table(table, use_native=False)
        self.connectionHelper.commit_transaction()

    def restore_db_finally(self):
        # for table in self.all_relations:
        #    self.drop_derived_relations(table)
        #   drop_fn = self.get_drop_fn(table)
        #   self.connectionHelper.execute_sql([drop_fn(table),
        #                                      self.connectionHelper.queries.alter_table_rename_to(self.connectionHelper.queries.get_backup(table), table)])"""
        """ This method is called only when UNMASQUE no more needs its working schema"""
        self._create_working_schema()

    def restore_one_table(self, table, use_native=True):
        self.drop_derived_relations(table)
        if use_native and self._native_copy_enabled():
            try:
                self._end_open_transaction()
                result = run_native_copy(
                    self.connectionHelper.config,
                    source_schema=self.connectionHelper.config.user_schema,
                    dest_schema=self.connectionHelper.config.schema,
                    tables=[table],
                    sql="like_insert",
                    rows=self._known_sizes([table]),
                    max_threads=default_threads(),
                    index_threads=default_index_threads(),
                    mode="restore",
                    logger=self.logger,
                )
                self._log_native_result("restore", result)
                return
            except NativeCopyError as error:
                self.logger.error(
                    f"Native restore of {table} failed, falling back to Python copy: {error}"
                )
        drop_fn = self.get_drop_fn(table)
        f_table = self.get_fully_qualified_table_name(table)
        backup_name = self.get_original_table_name(table)
        self.connectionHelper.execute_sql([drop_fn(f_table),
                                           self.connectionHelper.queries.create_table_like(f_table, backup_name),
                                           self.connectionHelper.queries.insert_into_tab_select_star_fromtab(
                                               f_table, backup_name)],
                                          self.logger)

    def __create_col_idx_if_not_exists(self, tab, col):
        idx = f"{tab}_{col}_idx"

        sql = f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                        FROM pg_index i
                            JOIN pg_attribute a ON a.attrelid = i.indrelid
                          AND a.attnum = ANY(i.indkey)
                            WHERE i.indrelid = '{tab}'::regclass
                            AND a.attname = '{col}'
                ) THEN
                    EXECUTE 'CREATE INDEX {idx} ON {tab} ({col})';
                END IF;
            END$$;
            """
        self.connectionHelper.execute_sql([sql], self.logger)

    def __get_cols_for_table(self, tab):
        res, desc = self.connectionHelper.execute_sql_fetchall(
            self.connectionHelper.queries.get_column_details_for_table(self.connectionHelper.config.user_schema,
                                                                       tab))
        tab_attribs = [row[0].lower() for row in res]
        return tab_attribs

    def __create_tab_indexes(self, tab):
        cols = self.__get_cols_for_table(tab)
        for col in cols:
            self.__create_col_idx_if_not_exists(tab, col)

    def backup_one_table(self, table, use_native=True):
        self.logger.debug(f"Backing up {table}...")
        if use_native and self._native_copy_enabled():
            try:
                if self.connectionHelper.config.use_index:
                    self.__create_tab_indexes(table)
                self.drop_derived_relations(table)
                self._end_open_transaction()
                result = run_native_copy(
                    self.connectionHelper.config,
                    source_schema=self.connectionHelper.config.user_schema,
                    dest_schema=self.connectionHelper.config.schema,
                    tables=[table],
                    sql="like_insert",
                    rows=self._known_sizes([table]),
                    max_threads=default_threads(),
                    index_threads=default_index_threads(),
                    mode="backup",
                    logger=self.logger,
                )
                self._log_native_result("backup", result)
                self.logger.debug(f"... done")
                return
            except NativeCopyError as error:
                self.logger.error(
                    f"Native backup of {table} failed, falling back to Python copy: {error}"
                )
        self.connectionHelper.begin_transaction()
        self.drop_derived_relations(table)
        working_table = self.get_fully_qualified_table_name(table)
        original_table = self.get_original_table_name(table)
        if self.connectionHelper.config.use_index:
            self.__create_tab_indexes(table)
        self.connectionHelper.execute_sqls_with_DictCursor(
            [self.connectionHelper.queries.create_table_like(working_table, original_table),
             self.connectionHelper.queries.insert_into_tab_select_star_fromtab(working_table, original_table)],
            self.logger)
        self.connectionHelper.commit_transaction()
        self.logger.debug(f"... done")

    def drop_r_tables(self):
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.drop_view(self.get_fully_qualified_table_name("r_e")),
             self.connectionHelper.queries.drop_table(self.get_fully_qualified_table_name("r_h"))])

    def sanitize_one_table(self, table, use_native=True):
        self.restore_one_table(table, use_native=use_native)
        self.drop_r_tables()

    def get_drop_fn(self, table):
        return self.connectionHelper.queries.drop_table_cascade \
            if self.connectionHelper.is_view_or_table(table, self.connectionHelper.config.schema) == 'table' \
            else self.connectionHelper.queries.drop_view

    def drop_derived_relations(self, table):
        derived_tables = self.connectionHelper.execute_sql_fetchall(f"select tablename from pg_tables "
                                                                    f"where schemaname = '{self.connectionHelper.config.schema}' "
                                                                    f"and tablename LIKE '{table}%{UNMASQUE}';",
                                                                    self.logger)
        if derived_tables is not None and len(derived_tables):
            derived_tables = derived_tables[0]
        else:
            derived_tables = []
        derived_views = self.connectionHelper.execute_sql_fetchall(f"select viewname from pg_views "
                                                                   f"where schemaname = '{self.connectionHelper.config.schema}' "
                                                                   f"and viewname LIKE '{table}%{UNMASQUE}';",
                                                                   self.logger)
        if derived_views is not None and len(derived_views):
            derived_views = derived_views[0]
        else:
            derived_views = []

        derived_objects = derived_tables + derived_views
        for obj in derived_objects:
            drop_fn = self.get_drop_fn(obj)
            self.connectionHelper.execute_sql([drop_fn(self.get_fully_qualified_table_name(obj))])

    def get_all_sizes(self):
        for tab in self.all_relations:
            row_count = self.connectionHelper.execute_sql_fetchone_0(
                self.connectionHelper.queries.get_row_count(self.get_original_table_name(tab)))
            if row_count is None:
                self.logger.debug(f"{tab} does not exists!")
                row_count = 0
            self.all_sizes[tab] = row_count
        return self.all_sizes
