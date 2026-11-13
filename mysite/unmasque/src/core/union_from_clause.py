from ..mocks.database import Schema
from ...src.core.abstract.AppExtractorBase import AppExtractorBase
from ...src.core.from_clause import FromClause


class UnionFromClause(Schema, AppExtractorBase):

    def __init__(self, connectionHelper):
        super().__init__(connectionHelper, "Union_fc")
        self.comtabs = None
        self.fromtabs = None
        self.to_nullify = set()
        self.nullified = set()
        self.fromClause = FromClause(connectionHelper)

    def get_relations(self):
        if not self.fromClause.init.done:
            self.fromClause.init.doJob()
        self.set_all_relations(self.fromClause.all_relations)
        return self.all_relations

    def _relation_exists(self, table):
        schema, _, name = table.partition(".")
        return self.connectionHelper.is_view_or_table(name.lower(), schema.lower()) is not None

    def _nullify_one(self, tab):
        original = self.get_original_table_name(tab)
        dirty_name = self._get_dirty_name(tab)
        dirty = self.get_original_table_name(dirty_name)

        self.connectionHelper.begin_transaction()
        try:
            if not self._relation_exists(original):
                if not self._relation_exists(dirty):
                    raise RuntimeError(f"relation {original} does not exist")
                self.connectionHelper.execute_sql(
                    [self.connectionHelper.queries.alter_table_rename_to(dirty, tab)], self.logger)
            self.connectionHelper.execute_sql(
                [self.connectionHelper.queries.drop_table_cascade(dirty),
                 self.connectionHelper.queries.alter_table_rename_to(original, dirty_name),
                 self.connectionHelper.queries.create_table_like(original, dirty)],
                self.logger)
            if not self._relation_exists(original) or not self._relation_exists(dirty):
                raise RuntimeError(f"could not nullify {original}")
            self.connectionHelper.commit_transaction()
        except Exception as error:
            self.connectionHelper.rollback_transaction()
            self.logger.error(f"Could not nullify {original}: {error}")
            raise
        self.nullified.add(tab)

    def nullify_except(self, s_set):
        self.to_nullify = set()
        self.nullified = set()
        if self.comtabs is None:
            return
        self.to_nullify = set(s_set).difference(self.comtabs)
        self.logger.debug("to nullify " + str(self.to_nullify))
        for tab in sorted(self.to_nullify):
            self._nullify_one(tab)

    def run_query(self, QH):
        return self.app.doJob(QH)

    def _revert_one(self, tab):
        original = self.get_original_table_name(tab)
        dirty = self.get_original_table_name(self._get_dirty_name(tab))

        self.connectionHelper.begin_transaction()
        try:
            original_exists = self._relation_exists(original)
            dirty_exists = self._relation_exists(dirty)
            if dirty_exists:
                statements = []
                if original_exists:
                    statements.append(self.connectionHelper.queries.drop_table_cascade(original))
                statements.append(self.connectionHelper.queries.alter_table_rename_to(dirty, tab))
                self.connectionHelper.execute_sql(statements, self.logger)
            elif not original_exists:
                raise RuntimeError(f"relation {original} does not exist and has no backup")
            if not self._relation_exists(original):
                raise RuntimeError(f"could not restore {original}")
            self.connectionHelper.commit_transaction()
        except Exception as error:
            self.connectionHelper.rollback_transaction()
            self.logger.error(f"Could not restore {original}: {error}")
            raise

    def revert_nullify(self):
        for tab in sorted(self.nullified):
            self._revert_one(tab)
        self.nullified = set()
        self.to_nullify = set()

    def get_partial_QH(self, QH):
        return self.doJob(QH)

    def isEmpty(self, Res):
        return self.app.isQ_result_no_full_nullfree_row(Res)

    def extract_params_from_args(self, args):
        return args[0]

    def doActualJob(self, args=None):
        QH = self.extract_params_from_args(args)
        fromTabQ = set(self.get_fromTabs(QH))
        comTabQ = set(self.get_comTabs(QH, fromTabQ))
        self.logger.debug(f"from tab: {fromTabQ}, com tab: {comTabQ}")
        partTabQ = fromTabQ.difference(comTabQ)
        self.logger.debug(f"part tab: {partTabQ}")
        return partTabQ

    def get_fromTabs(self, QH):
        if self.fromtabs is None:
            res = self.fromClause.doJob(QH, FromClause.TYPE_ERROR)
            if isinstance(res, str):
                self.logger.error(f"from-table extraction failed, got {res!r} instead of a table list")
                res = []
            self.fromtabs = res
        self.logger.debug(str(self.fromtabs))
        return self.fromtabs

    def get_comTabs(self, QH, tabs):
        if self.comtabs is None:
            self.fromClause.set_check_relations(tabs)
            res = self.fromClause.doJob(QH, FromClause.TYPE_RENAME)
            self.fromClause.reset_check_relations()
            if isinstance(res, str):
                self.logger.error(f"common-table check failed, got {res!r} instead of a table list")
                res = []
            self.comtabs = set(res or []) & set(tabs)
        return self.comtabs
