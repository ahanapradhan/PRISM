import unittest
import sys
sys.path.append("../../../")
from mysite.unmasque.src.core import algorithm1
from mysite.unmasque.src.core.union_from_clause import UnionFromClause
from mysite.unmasque.src.mocks.database import TPCH
from mysite.unmasque.test.util.BaseTestCase import BaseTestCase


class MyTestCase(BaseTestCase):

    def test_nullify_and_runQuery(self):
        query = "(select * from part,orders) union all (select * from customer)"
        db = TPCH()
        check = algorithm1.nullify_and_runQuery(query, db, {'part', 'orders'})
        self.assertEqual(check, True)

    def test_nullify_and_runQuery2(self):
        query = "(select * from part,orders) union all (select * from customer)"
        db = TPCH()
        check = algorithm1.nullify_and_runQuery(query, db, {'part'})
        self.assertEqual(check, True)

    def test_nullify_and_runQuery3(self):
        query = "(select * from part,orders) union all (select * from customer)"
        db = TPCH()
        check = algorithm1.nullify_and_runQuery(query, db, {'part', 'orders', 'customer'})
        self.assertEqual(check, False)

    def test_nullify_and_runQuery1(self):
        query = "(select * from part,orders) union all (select * from customer)"
        db = TPCH()
        check = algorithm1.nullify_and_runQuery(query, db, {'customer'})
        self.assertEqual(check, True)

    def test_algo_another_query(self):
        query = "(SELECT l_orderkey as key, l_quantity as dummy, " \
                "l_partkey as s_key FROM lineitem WHERE l_shipdate >= DATE '1994-01-01'" \
                " AND l_shipdate < DATE '1995-01-01' " \
                "AND l_quantity > 30) UNION ALL (SELECT " \
                "ps_partkey as key, ps_supplycost as dummy, " \
                "ps_suppkey as s_key FROM partsupp, orders WHERE" \
                " partsupp.ps_suppkey = orders.o_custkey " \
                "AND orders.o_orderdate >= DATE '1994-01-01' AND orders.o_orderdate < DATE '1995-01-01' " \
                "AND partsupp.ps_supplycost < 100);"
        db = TPCH()
        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, frozenset({frozenset({'lineitem'}), frozenset({'partsupp', 'orders'})}))

    def test_algo(self):
        query = "(SELECT * FROM lineitem,nation,region) union all " \
                "(SELECT * FROM customer,nation,region) union all " \
                "(SELECT * FROM orders,nation,region)"
        db = TPCH()
        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'orders'}), frozenset({'customer'}), frozenset({'lineitem'})})

    def test_algo1(self):
        query = "(SELECT * FROM lineitem,nation where something) union all " \
                "(SELECT * FROM customer,nation where some other thing) union all " \
                "(SELECT * FROM customer,lineitem where more things)"
        db = TPCH()
        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'lineitem', 'nation'}), frozenset({'customer', 'nation'}),
                             frozenset({'lineitem', 'customer'})})

    def test_algo1_2(self):
        query = "(SELECT * FROM part,lineitem) union all " \
                "(SELECT * FROM customer,orders) union all " \
                "(SELECT * FROM nation,region,part)"
        db = TPCH()
        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'lineitem', 'part'}), frozenset({'customer', 'orders'}),
                             frozenset({'nation', 'region', 'part'})})

    def test_algo_with_real_flow(self):
        query = "(select l_partkey as key from lineitem, part where l_partkey = p_partkey limit 2) " \
                "union all " \
                "(select l_orderkey as key from lineitem, orders where l_orderkey = o_orderkey limit 2)"

        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        db = UnionFromClause(self.conn)
        db.reset_data_schema()

        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'lineitem', 'part'}), frozenset({'lineitem', 'orders'})})
        self.conn.closeConnection()

    def test_no_union(self):
        query = "select l_partkey as key from lineitem, part where l_partkey = p_partkey limit 2"
        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        db = UnionFromClause(self.conn)
        db.reset_data_schema()

        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'lineitem', 'part'})})
        self.assertTrue("FROM(q1)" in pstr)
        self.assertTrue("FROM(q2)" not in pstr)
        self.conn.closeConnection()

    def test_3_case(self):
        query = "(select l_partkey as key from lineitem,part where l_partkey = p_partkey and l_extendedprice <= 905) " \
                "union all " \
                "(select l_orderkey as key from lineitem,orders where l_orderkey = o_orderkey and o_totalprice <= 905) " \
                "union all " \
                "(select o_orderkey as key from customer,orders where c_custkey = o_custkey and o_totalprice <= 890);"
        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        db = UnionFromClause(self.conn)
        db.reset_data_schema()

        p, pstr, _ = algorithm1.algo(db, query)
        self.assertEqual(p, {frozenset({'lineitem', 'part'}), frozenset({'lineitem', 'orders'}),
                             frozenset({'customer', 'orders'})})
        self.assertTrue("FROM(q1)" in pstr)
        self.assertTrue("FROM(q2)" in pstr)
        self.assertTrue("FROM(q3)" in pstr)
        self.conn.closeConnection()
    def test_outerjoin_case(self):
        query = "select n_name, r_comment from nation LEFT OUTER JOIN region on n_regionkey = r_regionkey and r_name " \
                "= 'AFRICA'" \
                " UNION ALL " \
                "select n_name, c_comment from nation RIGHT OUTER JOIN customer on " \
                "c_nationkey = n_nationkey and c_acctbal < 1000;"
        self.conn.config.detect_oj = True
        self.conn.config.detect_union = True
        self.conn.connectUsingParams()
        self.assertTrue(self.conn.conn is not None)
        db = UnionFromClause(self.conn)
        db.reset_data_schema()

        p, pstr, _ = algorithm1.algo(db, query)
        print(p)
        print(pstr)
        self.assertEqual(p, {frozenset({'nation', 'region'}),
                             frozenset({'customer', 'nation'})})
        self.assertTrue("FROM(q1)" in pstr)
        self.assertTrue("FROM(q2)" in pstr)
        self.conn.closeConnection()


if __name__ == '__main__':
    unittest.main()
