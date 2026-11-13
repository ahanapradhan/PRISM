from .abstract.AppExtractorBase import AppExtractorBase
from .abstract.abstractConnection import AbstractConnectionHelper
from ..util.native_copy import (
    NativeCopyError,
    default_index_threads,
    default_threads,
    run_native_copy,
)

# Predicates that mean "copy the whole table". PRISM uses the literal string
# ``true`` when a disjunction has no falsifying predicate.
_FULL_WHERE_VALUES = {"", "true", "(true)"}


class DbRestorer(AppExtractorBase):
    def __init__(self, connectionHelper: AbstractConnectionHelper, core_relations: list, name="Database_Restorer"):
        super().__init__(connectionHelper, name)
        self.relations = []
        self.last_restored_size = {}
        if core_relations is not None:
            self.core_relations = core_relations
            self.core_relations = list(set(self.core_relations))
        else:
            self.core_relations = None

    def set_all_sizes(self, sizes):
        self.all_sizes = sizes
        self.relations = list(self.all_sizes.keys())
        self.relations.sort()

    def update_last_restored_size(self, sizes):
        for tab in sizes:
            self.last_restored_size[tab] = sizes[tab]

    def extract_params_from_args(self, args):
        return args[0]

    def restore_one_table_where(self, tab, where):
        # table = self.get_fully_qualified_table_name(tab)
        # backup_name = self.get_original_table_name(tab)
        self.drop_derived_relations(tab)
        drop_fn = self.get_drop_fn(tab)
        self.connectionHelper.execute_sql([drop_fn(self.get_fully_qualified_table_name(tab)),
                                           self.connectionHelper.queries.create_table_as_select_star_from_where(
                                               self.get_fully_qualified_table_name(tab),
                                               self.get_original_table_name(tab),
                                               where)],
                                          self.logger)

    def sanitize_one_table_where(self, table, where):
        self.restore_one_table_where(table, where)
        self.drop_r_tables()

    @staticmethod
    def _is_full_where(where):
        return where is None or str(where).strip().lower() in _FULL_WHERE_VALUES

    def _restore_native_batch(self, pairs):
        """Restore a group of tables with the native threaded helper.

        Full-table restores use ``like_insert`` (the same shape as
        ``SchemaSanitizer.restore_one_table``); partial restores use ``ctas``
        (the same shape as ``restore_one_table_where``). Predicates are passed
        per table so both kinds can be batched independently.
        """
        try:
            for tab, _ in pairs:
                self.drop_derived_relations(tab)
            self._end_open_transaction()

            full = [tab for tab, where in pairs if self._is_full_where(where)]
            partial = [(tab, where) for tab, where in pairs
                       if not self._is_full_where(where)]

            if full:
                result = run_native_copy(
                    self.connectionHelper.config,
                    source_schema=self.connectionHelper.config.user_schema,
                    dest_schema=self.connectionHelper.config.schema,
                    tables=full,
                    sql="like_insert",
                    rows=self._known_sizes(full, self.all_sizes),
                    max_threads=default_threads(),
                    index_threads=default_index_threads(),
                    mode="restore",
                    logger=self.logger,
                )
                self._log_native_result("restore", result)

            if partial:
                result = run_native_copy(
                    self.connectionHelper.config,
                    source_schema=self.connectionHelper.config.user_schema,
                    dest_schema=self.connectionHelper.config.schema,
                    tables=[tab for tab, _ in partial],
                    sql="ctas",
                    wheres=dict(partial),
                    max_threads=default_threads(),
                    index_threads=default_index_threads(),
                    mode="restore",
                    logger=self.logger,
                )
                self._log_native_result("restore", result)

            for tab, _ in pairs:
                self.__update_current_sizes(tab)
            self.drop_r_tables()
            return True
        except NativeCopyError as error:
            self.logger.error(f"Native restore failed: {error}")
            return False

    def doActualJob(self, args=None):
        self.logger.debug("core relations: ", self.core_relations, " all sizes: ", self.all_sizes)
        tabs_wheres = self.extract_params_from_args(args)
        if tabs_wheres is None:
            to_restore = self.core_relations if (self.core_relations is not None and len(self.core_relations)) \
                else self.relations
            pairs = [(tab, None) for tab in to_restore]
        else:
            self.logger.debug("All sizes:", self.all_sizes)
            self.logger.debug("Current sizes:", self.last_restored_size)
            self.logger.debug(tabs_wheres)
            pairs = [(entry[0], entry[1]) for entry in tabs_wheres]

        pending = []
        for tab, where in pairs:
            if tab not in self.last_restored_size.keys():
                self.__update_current_sizes(tab)
            if self._is_full_where(where) and \
                    self.last_restored_size.get(tab) == self.all_sizes.get(tab):
                self.logger.info("No need to restore table")
            else:
                pending.append((tab, where))

        if not pending:
            return True

        if self._native_copy_enabled():
            if self._restore_native_batch(pending):
                return True
            self.logger.error("Falling back to Python restore for all pending tables.")

        for tab, where in pending:
            check = self.restore_table_and_confirm(tab, where)
            if not check:
                return False
        return True

    def restore_table_and_confirm(self, tab, where=None):
        full = self._is_full_where(where)
        if self._native_copy_enabled():
            try:
                self.drop_derived_relations(tab)
                self._end_open_transaction()
                if full:
                    result = run_native_copy(
                        self.connectionHelper.config,
                        source_schema=self.connectionHelper.config.user_schema,
                        dest_schema=self.connectionHelper.config.schema,
                        tables=[tab],
                        sql="like_insert",
                        rows=self._known_sizes([tab], self.all_sizes),
                        max_threads=default_threads(),
                        index_threads=default_index_threads(),
                        mode="restore",
                        logger=self.logger,
                    )
                else:
                    result = run_native_copy(
                        self.connectionHelper.config,
                        source_schema=self.connectionHelper.config.user_schema,
                        dest_schema=self.connectionHelper.config.schema,
                        tables=[tab],
                        sql="ctas",
                        wheres={tab: where},
                        max_threads=default_threads(),
                        index_threads=default_index_threads(),
                        mode="restore",
                        logger=self.logger,
                    )
                self._log_native_result("restore", result)
                row_count = self.__update_current_sizes(tab)
                self.drop_r_tables()
                return row_count
            except NativeCopyError as error:
                self.logger.error(
                    f"Native restore of {tab} failed, falling back to Python copy: {error}"
                )
        try:
            if full:
                self.sanitize_one_table(tab, use_native=False)
            else:
                self.sanitize_one_table_where(tab, where)
            row_count = self.__update_current_sizes(tab)
            return row_count
        except Exception as e:
            self.logger.error("Error ", str(e))
            return 0

    def __update_current_sizes(self, tab):
        row_count = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_row_count(self.get_fully_qualified_table_name(tab)), self.logger)
        if row_count is None:  # table does not exists
            self.connectionHelper.rollback_transaction()
            self.connectionHelper.execute_sql([self.connectionHelper.queries.create_table_like(
                self.get_fully_qualified_table_name(tab), self.get_original_table_name(tab)),
                                               self.connectionHelper.queries.insert_into_tab_select_star_fromtab(
                                                   self.get_fully_qualified_table_name(tab),
                                                   self.get_original_table_name(tab))],
                                              self.logger)
            self.connectionHelper.commit_transaction()
            row_count = self.connectionHelper.execute_sql_fetchone_0(
                self.connectionHelper.queries.get_row_count(self.get_fully_qualified_table_name(tab)), self.logger)
        self.last_restored_size[tab] = row_count
        self.logger.debug(f"Updating {tab} size: ", self.last_restored_size[tab])
        return row_count
