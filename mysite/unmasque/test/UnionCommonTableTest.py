from types import SimpleNamespace

import pytest

from mysite.unmasque.src.core.from_clause import FromClause


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class _FakeQueries:
    @staticmethod
    def alter_table_rename_to(original, dirty):
        return 'void', original.split('.')[-1]

    @staticmethod
    def create_table_like(original, like):
        return 'create', original


class _FakeConnectionHelper:
    def __init__(self):
        self.config = SimpleNamespace(user_schema='fresh', schema='unmasque')
        self.queries = _FakeQueries()
        self.voided = set()

    def begin_transaction(self):
        self.voided.clear()

    def rollback_transaction(self):
        self.voided.clear()

    def execute_sql(self, statements, logger=None):
        for statement in statements:
            if isinstance(statement, tuple) and statement[0] == 'void':
                self.voided.add(statement[1])


class _FakeApp:
    def __init__(self, helper, branch_tables, active_branches):
        self.helper = helper
        self.branch_tables = branch_tables
        self.active_branches = active_branches

    def doJob(self, query):
        all_tables = set().union(*self.branch_tables)
        available = all_tables.difference(self.helper.voided)
        return any(active and tables.issubset(available)
                   for tables, active in zip(self.branch_tables, self.active_branches))

    @staticmethod
    def isQ_result_no_full_nullfree_row(result):
        return not result


def _build_from_clause(branch_tables, active_branches):
    helper = _FakeConnectionHelper()
    from_clause = FromClause.__new__(FromClause)
    from_clause.connectionHelper = helper
    from_clause.check_relations = set().union(*branch_tables)
    from_clause.all_relations = set().union(*branch_tables)
    from_clause.dirty_name = '__unmasque_dirty'
    from_clause.logger = _NullLogger()
    from_clause.core_relations = []
    from_clause.timeout = False
    from_clause.method = FromClause.TYPE_RENAME
    from_clause.app = _FakeApp(helper, branch_tables, active_branches)
    return from_clause


def test_union_common_tables_are_branch_intersection_when_both_branches_active():
    branch_tables = [
        {'customer', 'orders', 'nation'},
        {'supplier', 'lineitem', 'orders', 'nation', 'region'},
    ]
    from_clause = _build_from_clause(branch_tables, [True, True])
    from_clause.get_core_relations_by_void('union query')
    core_relations = set(from_clause.core_relations)
    assert core_relations == {'orders', 'nation'}


@pytest.mark.xfail(
    strict=True,
    reason="Union common-table detection treats branch-local tables as common when one branch is empty",
)
def test_union_common_tables_ignore_data_empty_branch():
    branch_tables = [
        {'customer', 'orders', 'nation'},
        {'supplier', 'lineitem', 'orders', 'nation', 'region'},
    ]
    from_clause = _build_from_clause(branch_tables, [False, True])
    from_clause.get_core_relations_by_void('union query')
    core_relations = set(from_clause.core_relations)
    assert core_relations == {'orders', 'nation'}
