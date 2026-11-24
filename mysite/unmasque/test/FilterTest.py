import copy
import datetime
import unittest
from _decimal import Decimal

from mysite.unmasque.src.core.aoa import InequalityPredicate
from mysite.unmasque.src.core.equi_join import U2EquiJoin
from mysite.unmasque.src.core.filter import Filter
from mysite.unmasque.src.core.projection import Projection
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory
from mysite.unmasque.src.util.utils import find_diff_idx
from mysite.unmasque.test.util import tpchSettings


class MyTestCase(unittest.TestCase):
    conn = ConnectionHelperFactory().createConnectionHelper()
    global_attrib_types = []
    global_attrib_types_dict = {}
    global_min_instance_dict = {}

    def get_dmin_val(self, attrib: str, tab: str):
        values = self.global_min_instance_dict[tab]
        attribs, vals = values[0], values[1]
        attrib_idx = attribs.index(attrib)
        val = vals[attrib_idx]
        ret_val = float(val) if isinstance(val, Decimal) else val
        return ret_val

    def do_init(self):
        for entry in self.global_attrib_types:
            # aoa change
            self.global_attrib_types_dict[(entry[0], entry[1])] = entry[2]

    def test_filter_outer_join(self):
        self.conn.config.detect_oj = True
        self.global_attrib_types = {('nation', "n_nationkey", "integer"),
                                    ('nation', "n_name", "character"),
                                    ('nation', "n_regionkey", "integer"),
                                    ('nation', "n_comment", "character varying"),
                                    ('region', 'r_regionkey', 'integer'),
                                    ('region', 'r_name', 'character'),
                                    ('region', 'r_comment', 'character varying')
                                    }
        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        self.conn.config.detect_oj = True
        from_rels = ['nation', 'region']
        query = "select n_name, r_comment from nation LEFT OUTER JOIN region " \
                "on n_regionkey = r_regionkey and r_name = 'AFRICA';"

        self.conn.execute_sql([self.conn.queries.alter_table_rename_to('nation', 'nation_back'),
                               self.conn.queries.create_table_like('nation', 'nation_back'),
                               "insert into nation select * from nation_back where n_nationkey = 16 and n_regionkey = "
                               "0;"])
        self.conn.execute_sql([self.conn.queries.alter_table_rename_to('region', 'region_back'),
                               self.conn.queries.create_table_like('region', 'region_back'),
                               "insert into region select * from region_back where r_regionkey = 0;"])

        self.do_init()

        minimizer = ViewMinimizer(self.conn, from_rels, tpchSettings.all_size, False)
        check = minimizer.doJob(query)
        print(minimizer.global_min_instance_dict)
        self.assertTrue(check)

        wc = Filter(self.conn, from_rels, minimizer.global_min_instance_dict)
        filters = wc.doJob(query)
        print(filters)
        self.assertEqual(len(filters), 3)
        self.assertTrue(('region', 'r_name', 'equal', 'AFRICA', 'AFRICA') in filters)

        equi_join = U2EquiJoin(self.conn, from_rels, wc.filter_predicates,
                               wc, minimizer.global_min_instance_dict)
        check = equi_join.doJob(query)
        self.assertTrue(check)
        self.assertTrue(len(equi_join.algebraic_eq_predicates))
        self.assertTrue(len(equi_join.arithmetic_eq_predicates))
        # self.assertTrue(len(equi_join.join_graph))
        print(equi_join.algebraic_eq_predicates)
        print(equi_join.arithmetic_eq_predicates)
        # print(equi_join.join_graph)

        aoa = InequalityPredicate(self.conn, from_rels, equi_join.pending_predicates,
                                  equi_join.arithmetic_eq_predicates,
                                  equi_join.algebraic_eq_predicates, wc,
                                  minimizer.global_min_instance_dict)
        check = aoa.doJob(query)
        self.assertTrue(check)
        aoa.post_process_for_generation_pipeline(query)

        delivery = copy.copy(aoa.nextPipelineCtx)

        pj = Projection(self.conn, delivery)
        check = pj.doJob(query)
        self.assertTrue(check)

        self.conn.execute_sql([self.conn.queries.drop_table('nation'),
                               self.conn.queries.create_table_like('nation', 'nation_back'),
                               self.conn.queries.drop_table('nation_back')])
        self.conn.execute_sql([self.conn.queries.drop_table('region'),
                               self.conn.queries.create_table_like('region', 'region_back'),
                               self.conn.queries.drop_table('region_back')])

        self.conn.closeConnection()

    def test_a7_pre_aoa(self):
        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        self.conn.config.schema = "unmasque"
        self.conn.execute_sql(["Create Schema if not exists unmasque;"])
        self.global_attrib_types = [
            ('customer', 'c_custkey', 'integer'),
            ('customer', 'c_name', 'character varying'),
            ('customer', 'c_address', 'character varying'),
            ('customer', 'c_nationkey', 'integer'),
            ('customer', 'c_phone', 'character'),
            ('customer', 'c_acctbal', 'numeric'),
            ('customer', 'c_mktsegment', 'character'),
            ('customer', 'c_comment', 'character varying'),
            ('nation', 'n_nationkey', 'integer'),
            ('nation', 'n_name', 'character'),
            ('nation', 'n_regionkey', 'integer'),
            ('nation', 'n_comment', 'character varying'),
            ('orders', 'o_orderkey', 'integer'),
            ('orders', 'o_custkey', 'integer'),
            ('orders', 'o_orderstatus', 'character'),
            ('orders', 'o_totalprice', 'numeric'),
            ('orders', 'o_orderdate', 'date'),
            ('orders', 'o_orderpriority', 'character'),
            ('orders', 'o_clerk', 'character'),
            ('orders', 'o_shippriority', 'integer'),
            ('orders', 'o_comment', 'character varying'),
        ]
        self.do_init()
        from_rels = ['customer', 'nation', 'orders']
        query = """SELECT c_name, n_name, c_acctbal, o_totalprice
FROM customer, nation, orders
WHERE c_custkey = o_custkey
AND c_nationkey = n_nationkey
AND c_acctbal >= o_totalprice
AND n_regionkey = 1
AND o_orderdate <= '1995-06-30'
AND c_mktsegment = 'MACHINERY';"""

        global_min_instance_dict = {
            'customer': [
                ('c_custkey', 'c_name', 'c_address', 'c_nationkey', 'c_phone', 'c_acctbal', 'c_mktsegment', 'c_comment'),
                (427, 'Customer#000000427', 'gjs3QUZ6YqlALPAIZt22BvYem4ARRN5E2', 2, '12-124-309-3821', Decimal('4376.80'), 'MACHINERY', 'ously special deposits wake quickly expr')
            ],
            'nation': [
                ('n_nationkey', 'n_name', 'n_regionkey', 'n_comment'),
                (2, 'BRAZIL', 1, 'asymptotes use fluffily quickly bold instructions. slyly bold dependencies sleep carefully pending accounts')
            ],
            'orders': [
                ('o_orderkey', 'o_custkey', 'o_orderstatus', 'o_totalprice', 'o_orderdate', 'o_orderpriority', 'o_clerk', 'o_shippriority', 'o_comment'),
                (1222564, 427, 'F', Decimal('3764.89'), datetime.date(1992, 7, 25), '2-HIGH', 'Clerk#000000840', 0, 'efully pending deposits. quickly brave deposits x-ray doggedly special theodo')
            ],
        }

        def fmt(v):
            if v is None:
                return 'NULL'
            if isinstance(v, (int, float, Decimal)):
                return str(v)
            if isinstance(v, datetime.date):
                return f"'{v.isoformat()}'"
            return "'" + str(v).replace("'", "''") + "'"

        for tab in from_rels:
            self.conn.execute_sql([f"drop table if exists unmasque.{tab};",
                                   f"create table unmasque.{tab} as select * from public.{tab} where 1=2;"])
            attribs, vals = global_min_instance_dict[tab]
            col_str = ",".join(attribs)
            val_str = ",".join(fmt(v) for v in vals)
            self.conn.execute_sql([f"insert into unmasque.{tab} ({col_str}) values ({val_str});"])
        self.conn.commit_transaction()

        print("DMIN:", global_min_instance_dict)

        wc = Filter(self.conn, from_rels, global_min_instance_dict)
        filters = wc.doJob(query)
        print("FILTER_DONE:", wc.done)
        print("FILTER_PREDICATES:", wc.filter_predicates)

        equi_join = U2EquiJoin(self.conn, from_rels, wc.filter_predicates,
                               wc, global_min_instance_dict)
        check = equi_join.doJob(query)
        print("EQUI_DONE:", equi_join.done, "check:", check)
        print("ALGEBRAIC_EQ:", equi_join.algebraic_eq_predicates)
        print("ARITHMETIC_EQ:", equi_join.arithmetic_eq_predicates)
        print("PENDING:", equi_join.pending_predicates)

        self.conn.execute_sql(["Drop Schema if exists unmasque cascade;"])
        self.conn.closeConnection()

    def test_diff(self):
        list1 = [('hello', 'again')]
        list2 = [('hello', 'ahana')]
        d = find_diff_idx(list1, list2)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0], 1)


if __name__ == '__main__':
    unittest.main()
