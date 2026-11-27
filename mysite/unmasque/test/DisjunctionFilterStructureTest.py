import unittest

from mysite.unmasque.src.core.disjunction.filter_structure import (
    Domain,
    attr_domain_under_route,
    attr_global_union_domain,
    is_attr_free_under_route,
    route_probe_plan,
    sample_values_from_domain,
    select_freeing_route_for_attr,
)
from mysite.unmasque.src.core.disjunction.model import Atom, Clause, CNF


class DisjunctionFilterStructureTest(unittest.TestCase):
    def test_cross_column_clause_frees_other_attr_on_route(self):
        # (n_name='ARGENTINA' OR n_regionkey=3)
        a_name = Atom(table='nation', col='n_name', kind='text', text=('eq', 'ARGENTINA'), id='a1')
        a_region = Atom(table='nation', col='n_regionkey', kind='num', intervals=[(3, 3)], id='a2')
        cnf = CNF(clauses=[Clause(atoms=[a_name, a_region], id='c1')])

        route_free_name = (a_region,)
        self.assertTrue(is_attr_free_under_route(cnf, route_free_name, ('nation', 'n_name')))
        d = attr_domain_under_route(cnf, route_free_name, ('nation', 'n_name'))
        self.assertEqual('free', d.kind)

        route_pin_name = (a_name,)
        self.assertFalse(is_attr_free_under_route(cnf, route_pin_name, ('nation', 'n_name')))
        d2 = attr_domain_under_route(cnf, route_pin_name, ('nation', 'n_name'))
        self.assertEqual('pinned', d2.kind)
        self.assertEqual('ARGENTINA', d2.values[0])

    def test_single_attr_clause_union_and_singleton(self):
        # (p_size = 10 OR p_size = 20)
        a1 = Atom(table='part', col='p_size', kind='num', intervals=[(10, 10)], id='a1')
        a2 = Atom(table='part', col='p_size', kind='num', intervals=[(20, 20)], id='a2')
        cnf = CNF(clauses=[Clause(atoms=[a1, a2], id='c1')])
        d = attr_global_union_domain(cnf, ('part', 'p_size'))
        self.assertIsNotNone(d)
        self.assertEqual('union', d.kind)
        vals = sample_values_from_domain(d, count=2)
        self.assertEqual(2, len(vals))
        self.assertTrue(set(vals).issubset({10, 20}))

        cnf_single = CNF(clauses=[Clause(atoms=[a1, Atom(table='part', col='p_size', kind='num', intervals=[(10, 10)], id='a3')], id='c1')])
        d1 = attr_global_union_domain(cnf_single, ('part', 'p_size'))
        self.assertEqual('pinned', d1.kind)

    def test_select_freeing_route_prefers_other_column(self):
        a_name = Atom(table='nation', col='n_name', kind='text', text=('eq', 'ARGENTINA'), id='a1')
        a_region = Atom(table='nation', col='n_regionkey', kind='num', intervals=[(3, 3)], id='a2')
        cnf = CNF(clauses=[Clause(atoms=[a_name, a_region], id='c1')])
        route = select_freeing_route_for_attr(cnf, ('nation', 'n_name'))
        self.assertIsNotNone(route)
        self.assertEqual(('nation', 'n_regionkey'), (route[0].table, route[0].col))

    def test_cross_table_carrier_plan(self):
        a = Atom(table='t1', col='a', kind='num', intervals=[(1, 1)], id='a1')
        b = Atom(table='t2', col='b', kind='num', intervals=[(2, 2)], id='a2')
        cnf = CNF(clauses=[Clause(atoms=[a, b], id='c1')])
        plans = route_probe_plan(cnf, (a,))
        self.assertEqual(1, len(plans))
        self.assertTrue(plans[0]['ok'])
        self.assertEqual('t1', plans[0]['carrier_table'])
        self.assertTrue(plans[0]['cross_table'])
        self.assertTrue(plans[0]['needs_all_rows'])

    def test_sample_values_from_interval_domain(self):
        d = Domain(kind='union', intervals=[(1, 5)], values=[])
        vals = sample_values_from_domain(d, count=2)
        self.assertEqual(2, len(vals))
        self.assertEqual(len(set(vals)), 2)
        for v in vals:
            self.assertTrue(1 <= v <= 5)


if __name__ == '__main__':
    unittest.main()
