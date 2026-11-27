"""Regressions for outer-join candidate generation around equi-join projections."""
from ...src.core.outer_join import OuterJoin


class _Stub:
    pass


def _no_op_logger():
    logger = _Stub()
    logger.debug = lambda *args, **kwargs: None
    logger.info = lambda *args, **kwargs: None
    logger.error = lambda *args, **kwargs: None
    return logger


def _bare_outer_join(q_gen=None):
    oj = object.__new__(OuterJoin)
    oj.logger = _no_op_logger()
    oj.q_gen = q_gen
    return oj


def test_join_key_projection_swaps_try_both_endpoints():
    oj = _bare_outer_join()
    graph = [[('c_custkey', 'customer'), ('o_custkey', 'orders')]]

    assert oj._OuterJoin__join_key_projection_swaps(
        graph, ['o_custkey', 'c_name', 'o_orderkey']) == [('o_custkey', 'c_custkey')]
    assert oj._OuterJoin__join_key_projection_swaps(
        graph, ['c_custkey', 'c_name', 'o_orderkey']) == [('c_custkey', 'o_custkey')]
    assert oj._OuterJoin__join_key_projection_swaps(graph, ['c_name']) == []


def test_join_key_projection_swaps_are_one_at_a_time():
    oj = _bare_outer_join()
    graph = [
        [('c_custkey', 'customer'), ('o_custkey', 'orders')],
        [('c_nationkey', 'customer'), ('n_nationkey', 'nation')],
    ]

    assert oj._OuterJoin__join_key_projection_swaps(
        graph, ['o_custkey', 'n_nationkey', 'c_name']) == [
            ('o_custkey', 'c_custkey'),
            ('n_nationkey', 'c_nationkey'),
        ]


class _FakeQueryGen:
    def __init__(self):
        self.global_projected_attributes = ['o_custkey', 'c_name']
        self.global_groupby_attributes = []
        self.global_aggregated_attributes = [('', ''), ('', '')]
        self._workingCopy = _Stub()
        self._workingCopy.order_by_op = ''
        self.from_op = ''
        self.where_op = ''
        self.select_op = ''

    def backup_query_before_new_generation(self):
        pass

    def clear_from_where_ops(self):
        self.from_op = ''
        self.where_op = ''

    def generate_from_on_clause(self, edge, fp_on, imp_t1, imp_t2, table1, table2):
        self.from_op = f"{table1} FULL OUTER JOIN {table2} ON {table1}.{edge[0][0]} = {table2}.{edge[1][0]}"

    def generate_where_clause(self, fp_where):
        self.where_op = '1=1'

    def generate_groupby_select(self):
        self.select_op = ', '.join(self.global_projected_attributes)

    def write_query(self):
        return f"SELECT {self.select_op} FROM {self.from_op} WHERE {self.where_op}"


def test_outer_join_candidates_include_both_projected_join_keys():
    q_gen = _FakeQueryGen()
    oj = _bare_outer_join(q_gen)
    oj._OuterJoin__determine_on_and_where_filters = lambda query: ([], [])
    oj._OuterJoin__determine_on_and_where_aoa = lambda query: ([], [])
    oj._OuterJoin__determine_join_edge_type = lambda edge, t1, t2: ('h', 'h')
    edge = [('c_custkey', 'customer'), ('o_custkey', 'orders')]

    candidates, _ = oj._OuterJoin__formulateQueries([[edge]], 'SELECT 1', [edge])

    assert any('SELECT o_custkey' in q and 'FULL OUTER JOIN' in q for q in candidates)
    assert any('SELECT c_custkey' in q and 'FULL OUTER JOIN' in q for q in candidates)
    assert q_gen.global_projected_attributes == ['o_custkey', 'c_name']
