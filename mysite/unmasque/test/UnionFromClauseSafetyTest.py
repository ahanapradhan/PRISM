from types import SimpleNamespace

import pytest

from mysite.unmasque.src.core import algorithm1
from mysite.unmasque.src.core.union_from_clause import UnionFromClause


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class _FakeQueries:
    @staticmethod
    def alter_table_rename_to(old, new):
        if '.' not in new:
            new = old.split('.')[0] + '.' + new
        return 'rename', old, new

    @staticmethod
    def create_table_like(original, like):
        return 'create', original, like

    @staticmethod
    def drop_table_cascade(tab):
        return 'drop', tab

    @staticmethod
    def drop_table(tab):
        return 'drop', tab


class _FakeConnectionHelper:
    def __init__(self, tables):
        self.config = SimpleNamespace(user_schema='fresh', schema='unmasque', log_level='DEBUG')
        self.queries = _FakeQueries()
        self.tables = dict(tables)
        self.snapshot = None
        self.fail_on = set()

    def begin_transaction(self):
        self.snapshot = dict(self.tables)

    def commit_transaction(self):
        self.snapshot = None

    def rollback_transaction(self):
        if self.snapshot is not None:
            self.tables = self.snapshot
        self.snapshot = None

    def is_view_or_table(self, name, schema):
        target = f"{schema}.{name}".lower()
        return 'table' if any(key.lower() == target for key in self.tables) else None

    def execute_sql(self, statements, logger=None):
        for statement in statements:
            op = statement[0]
            if (op, statement[1]) in self.fail_on:
                raise RuntimeError(f"injected failure on {op} {statement[1]}")
            if op == 'drop':
                self.tables.pop(statement[1], None)
            elif op == 'rename':
                _, old, new = statement
                if old not in self.tables:
                    continue
                if new in self.tables:
                    raise RuntimeError(f"relation {new} already exists")
                self.tables[new] = self.tables.pop(old)
            elif op == 'create':
                _, original, like = statement
                if original in self.tables:
                    continue
                if like not in self.tables:
                    raise RuntimeError(f"relation {like} does not exist")
                self.tables[original] = set()
            else:
                raise AssertionError(f"unexpected operation {statement}")


def _build_union_from_clause(tables):
    helper = _FakeConnectionHelper(tables)
    ufc = UnionFromClause.__new__(UnionFromClause)
    ufc.connectionHelper = helper
    ufc.comtabs = set()
    ufc.to_nullify = set()
    ufc.nullified = set()
    ufc._transaction_open = False
    ufc.extractor_name = 'Union_fc'
    ufc.dirty_name = '_unmasque_Union_fc'
    ufc.logger = _NullLogger()
    return ufc, helper


def _dirty(tab):
    return f"fresh.{tab}_unmasque_Union_fc"


def test_nullify_and_revert_restore_original_table_and_data():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})

    ufc.nullify_except({'nation'})

    assert helper.tables['fresh.nation'] == set()
    assert helper.tables[_dirty('nation')] == {'real-data'}
    assert ufc.nullified == {'nation'}

    ufc.revert_nullify()

    assert helper.tables['fresh.nation'] == {'real-data'}
    assert _dirty('nation') not in helper.tables
    assert ufc.to_nullify == set()
    assert ufc.nullified == set()


def test_revert_is_idempotent():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})

    ufc.nullify_except({'nation'})
    ufc.revert_nullify()
    ufc.revert_nullify()

    assert helper.tables['fresh.nation'] == {'real-data'}
    assert _dirty('nation') not in helper.tables


def test_failed_revert_rolls_back_and_restores_original_data():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})
    ufc.nullify_except({'nation'})

    helper.fail_on = {('rename', _dirty('nation'))}
    with pytest.raises(RuntimeError):
        ufc.revert_nullify()

    # The nullify transaction was never committed, so rollback restores the
    # original table and removes the temporary backup.
    assert helper.tables['fresh.nation'] == {'real-data'}
    assert _dirty('nation') not in helper.tables
    assert ufc.nullified == set()


def test_rollback_before_revert_leaves_user_tables_untouched():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})

    ufc.nullify_except({'nation'})
    # Simulate a crash/connection loss before revert: no commit happened.
    ufc.abort_nullify()

    assert helper.tables['fresh.nation'] == {'real-data'}
    assert _dirty('nation') not in helper.tables


def test_failed_nullify_keeps_original_table():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})
    helper.fail_on = {('create', 'fresh.nation')}

    with pytest.raises(RuntimeError):
        ufc.nullify_except({'nation'})

    assert helper.tables['fresh.nation'] == {'real-data'}
    assert _dirty('nation') not in helper.tables
    assert ufc.nullified == set()


def test_nullify_recovers_leftover_dirty_table_when_original_is_missing():
    ufc, helper = _build_union_from_clause({_dirty('nation'): {'real-data'}})

    ufc.nullify_except({'nation'})

    assert helper.tables['fresh.nation'] == set()
    assert helper.tables[_dirty('nation')] == {'real-data'}

    ufc.revert_nullify()

    assert helper.tables['fresh.nation'] == {'real-data'}


class _RaisingDb:
    def __init__(self):
        self.reverted = False
        self.nullified = False

    def nullify_except(self, tables):
        self.nullified = True

    def run_query(self, query):
        raise RuntimeError("oracle failed")

    def revert_nullify(self):
        self.reverted = True


def test_revert_runs_even_when_oracle_raises():
    db = _RaisingDb()

    with pytest.raises(RuntimeError):
        algorithm1.nullify_and_runQuery('union query', db, {'nation'})

    assert db.nullified
    assert db.reverted


class _FakeFromClause:
    def __init__(self, result):
        self.result = result

    def doJob(self, query, method):
        return self.result


def test_get_from_tabs_discards_error_strings():
    ufc, _ = _build_union_from_clause({})
    ufc.fromtabs = None
    ufc.fromClause = _FakeFromClause('OK ')

    assert list(ufc.get_fromTabs('query')) == []
    assert ufc.fromtabs == []


def test_revert_does_not_touch_unrecorded_tables():
    ufc, helper = _build_union_from_clause({'fresh.nation': {'real-data'}})
    ufc.to_nullify = {'nation'}

    ufc.revert_nullify()

    assert helper.tables['fresh.nation'] == {'real-data'}
