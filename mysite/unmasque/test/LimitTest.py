import unittest

from mysite.unmasque.src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase
from mysite.unmasque.src.core.limit import Limit


class _FakeLogger:
    def debug(self, *args, **kwargs):
        pass


class _FakeApp:
    def __init__(self, results):
        self.results = results or [[]]
        self.calls = 0

    def doJob(self, query):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result

    @staticmethod
    def isQ_result_empty(result):
        return not result


class _FakeLimit(Limit):
    def __init__(self, *, core_relations, global_all_attribs, attrib_types, joined_attribs,
                 global_join_graph, filter_attrib_dict, filter_in_predicates,
                 global_min_instance_dict=None, group_by=(), no_rows=5,
                 rmin_card=0, app_results=None):
        self.limit = None
        self.global_groupby_attributes = list(group_by)
        self.joined_attrib_valDict = {}
        self.no_rows = no_rows
        self.rmin_card = rmin_card
        self.core_relations = list(core_relations)
        self.global_all_attribs = {tab: list(attribs) for tab, attribs in global_all_attribs.items()}
        self.attrib_types_dict = dict(attrib_types)
        self.joined_attribs = list(joined_attribs)
        self.global_join_graph = [tuple(edge) for edge in global_join_graph]
        self.filter_attrib_dict = dict(filter_attrib_dict)
        self.filter_in_predicates = list(filter_in_predicates)
        self.global_min_instance_dict = dict(global_min_instance_dict or {})
        self._Limit__dmin_cache = {}
        self._Limit__join_edges_by_attrib = self._Limit__build_join_edge_index()
        self._Limit__attrib_to_table = self._Limit__build_attrib_table_index()
        self._Limit__filter_in_values = self._Limit__build_filter_in_value_index()
        self._Limit__joined_attrib_set = set(self.joined_attribs)
        self.dmin_calls = []
        self.batch_insert_calls = []
        self.legacy_insert_calls = []
        self.logger = _FakeLogger()
        self.app = _FakeApp(app_results)

    def get_datatype(self, key):
        return self.attrib_types_dict[key]

    def get_dmin_val(self, attrib, tab):
        self.dmin_calls.append((tab, attrib))
        attribs, values = self.global_min_instance_dict[tab]
        return values[attribs.index(attrib)]

    def get_s_val(self, attrib, tab):
        key = (tab, attrib)
        if key not in self.filter_attrib_dict:
            return 100
        value = self.filter_attrib_dict[key]
        if isinstance(value, (list, tuple)):
            return value[0]
        return value

    def get_s_val_for_textType(self, attrib, tab):
        return self.filter_attrib_dict[(tab, attrib)]

    def insert_attrib_vals_into_table_many(self, att_order, attrib_list_inner,
                                           insert_rows, tabname_inner, insert_logger=False):
        self.batch_insert_calls.append((att_order, list(attrib_list_inner), list(insert_rows),
                                        tabname_inner, insert_logger))

    def insert_attrib_vals_into_table(self, att_order, attrib_list_inner,
                                      insert_rows, tabname_inner, insert_logger=True):
        self.legacy_insert_calls.append((att_order, list(attrib_list_inner), list(insert_rows),
                                         tabname_inner, insert_logger))


class LimitOptimizationTest(unittest.TestCase):
    def test_dmin_is_fetched_once_and_reused_for_every_row(self):
        limit = _FakeLimit(
            core_relations=['t'],
            global_all_attribs={'t': ['a', 'b']},
            attrib_types={('t', 'a'): 'int', ('t', 'b'): 'text'},
            joined_attribs=[],
            global_join_graph=[],
            filter_attrib_dict={},
            filter_in_predicates=[],
            global_min_instance_dict={'t': (['a', 'b'], [7, 'x'])},
            no_rows=4,
            app_results=[[0, 1, 2, 3]],
        )

        limit.doLimitExtractJob('query')

        self.assertEqual(limit.dmin_calls, [('t', 'a'), ('t', 'b')])
        self.assertEqual(len(limit.batch_insert_calls), 1)
        _, _, insert_rows, tabname, insert_logger = limit.batch_insert_calls[0]
        self.assertEqual(tabname, 't')
        self.assertFalse(insert_logger)
        self.assertEqual(insert_rows, [(7, 'x')] * 4)
        self.assertEqual(limit.legacy_insert_calls, [])

    def test_join_values_reuse_precomputed_edge_index(self):
        limit = _FakeLimit(
            core_relations=['t', 'u'],
            global_all_attribs={'t': ['a'], 'u': ['b']},
            attrib_types={('t', 'a'): 'int', ('u', 'b'): 'int'},
            joined_attribs=['a', 'b'],
            global_join_graph=[('a', 'b')],
            filter_attrib_dict={},
            filter_in_predicates=[],
        )

        plan_t = limit._Limit__build_insertion_plan(['a'], set(), {}, 't')
        plan_u = limit._Limit__build_insertion_plan(['b'], set(), {}, 'u')
        limit.global_join_graph = None
        rows_t, rows_u = [], []
        limit._Limit__determine_k_insert_rows(plan_t, {}, rows_t, 0, 't')
        limit._Limit__determine_k_insert_rows(plan_u, {}, rows_u, 0, 'u')

        self.assertEqual(rows_t, [(100,)])
        self.assertEqual(rows_u, [(100,)])

    def test_filter_in_values_use_precomputed_index(self):
        limit = _FakeLimit(
            core_relations=['t'],
            global_all_attribs={'t': ['a']},
            attrib_types={('t', 'a'): 'int'},
            joined_attribs=[],
            global_join_graph=[],
            filter_attrib_dict={},
            filter_in_predicates=[('t', 'a', 'IN', [1, 2, 3], [1, 2, 3])],
            no_rows=100,
        )

        limit.filter_in_predicates = None

        self.assertEqual(limit._Limit__compute_total_values('int', ('t', 'a'), 1), 3)

    def test_non_text_upper_bound_is_precomputed_in_plan(self):
        limit = _FakeLimit(
            core_relations=['t'],
            global_all_attribs={'t': ['a']},
            attrib_types={('t', 'a'): 'int'},
            joined_attribs=[],
            global_join_graph=[],
            filter_attrib_dict={('t', 'a'): (1, 5)},
            filter_in_predicates=[],
        )

        plan = limit._Limit__build_insertion_plan(['a'], {('t', 'a')}, {}, 't')
        rows = []
        limit._Limit__determine_k_insert_rows(plan, {}, rows, 10, 't')

        self.assertEqual(plan[0][5], 5)
        self.assertEqual(rows, [(5,)])

    def test_text_filter_value_is_precomputed_in_plan(self):
        limit = _FakeLimit(
            core_relations=['t'],
            global_all_attribs={'t': ['a']},
            attrib_types={('t', 'a'): 'char'},
            joined_attribs=[],
            global_join_graph=[],
            filter_attrib_dict={('t', 'a'): 'ABC_'},
            filter_in_predicates=[],
        )

        plan = limit._Limit__build_insertion_plan(['a'], {('t', 'a')}, {}, 't')
        limit.filter_attrib_dict = {}
        rows = []
        limit._Limit__determine_k_insert_rows(plan, {}, rows, 0, 't')

        self.assertEqual(plan, [('text', 'a', 'ABC_')])
        self.assertTrue(rows[0][0].startswith('ABC'))

    def test_attribute_to_table_index_is_precomputed(self):
        limit = _FakeLimit(
            core_relations=['t', 'u'],
            global_all_attribs={'t': ['a'], 'u': ['b']},
            attrib_types={('t', 'a'): 'int', ('u', 'b'): 'int'},
            joined_attribs=[],
            global_join_graph=[],
            filter_attrib_dict={},
            filter_in_predicates=[],
        )

        limit.global_all_attribs = {}

        self.assertEqual(limit._Limit__find_table_for_attrib('a'), 't')
        self.assertEqual(limit._Limit__find_table_for_attrib('b'), 'u')


class _FakeQueries:
    @staticmethod
    def insert_into_tab_attribs_format(att_order, esc_string, tab):
        return f"INSERT INTO {tab} {att_order} VALUES {esc_string}"


class _FakeConnection:
    def __init__(self):
        self.queries = _FakeQueries()
        self.many_calls = []

    def execute_sql_many(self, sql, params, logger=None):
        self.many_calls.append((sql, params, logger))


class _FakeGenerationPipeline:
    def __init__(self):
        self.connectionHelper = _FakeConnection()
        self.logger = _FakeLogger()

    @staticmethod
    def get_fully_qualified_table_name(tab):
        return f"public.{tab}"


class BatchInsertTest(unittest.TestCase):
    def test_insert_attrib_vals_into_table_many_executes_one_batch(self):
        pipeline = _FakeGenerationPipeline()
        rows = [(1, 'x'), (2, 'y')]

        GenerationPipeLineBase.insert_attrib_vals_into_table_many(
            pipeline, '(a,b)', ['a', 'b'], rows, 't')

        self.assertEqual(len(pipeline.connectionHelper.many_calls), 1)
        sql, params, logger = pipeline.connectionHelper.many_calls[0]
        self.assertIn('%s', sql)
        self.assertEqual(params, rows)
        self.assertIsNone(logger)

    def test_insert_attrib_vals_into_table_many_skips_empty_rows(self):
        pipeline = _FakeGenerationPipeline()

        GenerationPipeLineBase.insert_attrib_vals_into_table_many(
            pipeline, '(a,b)', ['a', 'b'], [], 't')

        self.assertEqual(pipeline.connectionHelper.many_calls, [])


if __name__ == '__main__':
    unittest.main()
