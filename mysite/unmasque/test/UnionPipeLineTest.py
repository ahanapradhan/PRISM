from types import SimpleNamespace

import mysite.unmasque.src.pipeline.UnionPipeLine as union_pipeline_module
from mysite.unmasque.src.pipeline.UnionPipeLine import UnionPipeLine


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _TimeProfile:
    def update_for_from_clause(self, *args, **kwargs):
        pass

    def update_for_union(self, *args, **kwargs):
        pass


class _Queries:
    def get_row_count(self, table):
        return f"count {table}"


class _Connection:
    def __init__(self):
        self.config = SimpleNamespace(schema='unmasque', user_schema='fresh')
        self.queries = _Queries()

    def connectUsingParams(self, *args, **kwargs):
        pass

    def closeConnection(self):
        pass

    def execute_sql_fetchone_0(self, sql, logger=None):
        return 25


class _QueryGenerator:
    def reset(self):
        pass


class _FakeUnion:
    all_relations = {'customer', 'lineitem', 'nation', 'part', 'partsupp', 'supplier'}
    all_sizes = {relation: 25 for relation in all_relations}
    key_lists = {}
    local_elapsed_time = 0
    app_calls = 0

    def __init__(self, connectionHelper):
        pass

    def doJob(self, query):
        branches = [
            frozenset({'customer', 'nation'}),
            frozenset({'supplier', 'nation'}),
            frozenset({'part', 'lineitem'}),
        ]
        return branches, 'union profile', (0, 0)


class _FakeSchemaSanitizer:
    restored_relations = []

    def __init__(self, connectionHelper, all_sizes):
        self.connectionHelper = connectionHelper

    def set_all_relations(self, relations):
        self.relations = relations

    def sanitize(self):
        self.__class__.restored_relations.append(frozenset(self.relations))

    def get_fully_qualified_table_name(self, table):
        return f"unmasque.{table}"


class _UnionPipeline(UnionPipeLine):
    def __init__(self):
        self.connectionHelper = _Connection()
        self.state = []
        self.info = {}
        self.logger = _NullLogger()
        self.time_profile = _TimeProfile()
        self.pipeLineError = False
        self.q_generator = _QueryGenerator()
        self.core_relations = None
        self.all_relations = None
        self.all_sizes = {}
        self.key_lists = {}
        self.error = ''
        self.nullified_relations = []
        self.reverted_relations = []
        self.extracted_branches = []

    def update_state(self, state):
        self.state.append(state)

    def _UnionPipeLine__nullify_relations(self, relations):
        self.nullified_relations.append(frozenset(relations))

    def _UnionPipeLine__revert_nullifications(self, relations):
        self.reverted_relations.append(frozenset(relations))

    def _after_from_clause_extract(self, query, core_relations):
        self.extracted_branches.append(frozenset(core_relations))
        return f"Select {','.join(sorted(core_relations))};"


def test_core_relations_restored_after_each_union_branch(monkeypatch):
    _FakeSchemaSanitizer.restored_relations = []
    monkeypatch.setattr(union_pipeline_module, 'Union', _FakeUnion)
    monkeypatch.setattr(union_pipeline_module, 'SchemaSanitizer', _FakeSchemaSanitizer)
    pipeline = _UnionPipeline()

    result = pipeline.extract('union query')

    branches = [
        frozenset({'customer', 'nation'}),
        frozenset({'supplier', 'nation'}),
        frozenset({'part', 'lineitem'}),
    ]
    nullified = [_FakeUnion.all_relations - branch for branch in branches]
    assert pipeline.extracted_branches == branches
    assert _FakeSchemaSanitizer.restored_relations == branches
    assert pipeline.nullified_relations == nullified
    assert pipeline.reverted_relations == nullified
    for relation in _FakeUnion.all_relations:
        assert pipeline.all_sizes[relation] == 25
    assert result.count('UNION ALL') == 2
