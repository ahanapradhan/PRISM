from types import SimpleNamespace

import mysite.unmasque.src.core.union as union_module
from mysite.unmasque.src.core.union import Union


class _Init:
    done = True
    global_key_lists = []


class _FromClause:
    def __init__(self):
        self.init = _Init()


class _Db:
    def __init__(self):
        self.fromClause = _FromClause()
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


def _run_union(monkeypatch):
    captured = {}

    def make_db(connection, initiator=None):
        captured['initiator'] = initiator
        return _Db()

    monkeypatch.setattr(union_module, 'UnionFromClause', make_db)
    monkeypatch.setattr(union_module, 'algorithm1', _Algorithm)

    union = Union.__new__(Union)
    union.connectionHelper = SimpleNamespace()
    union.initiator = SimpleNamespace(done=True)
    union.all_relations = None
    result = union.doActualJob('query')
    return union, result, captured


def test_initiator_is_forwarded_to_union_from_clause(monkeypatch):
    union, result, captured = _run_union(monkeypatch)

    assert result[1] == 'pretty'
    assert captured['initiator'] is union.initiator


def test_initiator_stats_are_no_longer_captured_by_union(monkeypatch):
    union, _, _ = _run_union(monkeypatch)

    assert not hasattr(union, 'init_elapsed_time')
    assert not hasattr(union, 'init_app_calls')
