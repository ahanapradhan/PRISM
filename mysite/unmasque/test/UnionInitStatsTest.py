from types import SimpleNamespace

import mysite.unmasque.src.core.union as union_module
from mysite.unmasque.src.core.union import Union


class _Init:
    def __init__(self, app_calls=None):
        self.done = False
        self.local_elapsed_time = 1.25
        self.global_key_lists = []
        if app_calls is not None:
            self.app_calls = app_calls


class _FromClause:
    def __init__(self, app_calls=None):
        self.init = _Init(app_calls)


class _Db:
    def __init__(self, connection, app_calls=None):
        self.fromClause = _FromClause(app_calls)
        self.fromtabs = {'a'}

    def reset_data_schema(self):
        pass

    def get_relations(self):
        return ['a']

    def get_all_sizes(self):
        return {'a': 1}


class _Algorithm:
    @staticmethod
    def algo(db, query):
        return {frozenset(db.fromtabs)}, 'pretty', (0.0, 0)


def _run_union(monkeypatch, app_calls):
    monkeypatch.setattr(union_module, 'UnionFromClause',
                        lambda connection: _Db(connection, app_calls))
    monkeypatch.setattr(union_module, 'algorithm1', _Algorithm)

    union = Union.__new__(Union)
    union.connectionHelper = SimpleNamespace()
    union.init_elapsed_time = 0
    union.init_app_calls = 0
    union.all_relations = None
    result = union.doActualJob('query')
    return union, result


def test_missing_app_calls_stat_does_not_break_extraction(monkeypatch):
    union, result = _run_union(monkeypatch, app_calls=None)

    assert result[1] == 'pretty'
    assert union.init_elapsed_time == 1.25
    assert union.init_app_calls == 0


def test_present_app_calls_stat_is_recorded(monkeypatch):
    union, _ = _run_union(monkeypatch, app_calls=7)

    assert union.init_elapsed_time == 1.25
    assert union.init_app_calls == 7
