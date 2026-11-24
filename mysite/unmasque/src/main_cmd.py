import argparse
import signal
import sys
import traceback

from .core.factory.PipeLineFactory import PipeLineFactory
from .pipeline.abstract.SchemaSanitizer import SchemaSanitizer
from .util.ConnectionFactory import ConnectionHelperFactory
from .util.workload_queries import TestQuery


def signal_handler(signum, frame):
    print('You pressed Ctrl+C!')
    sigconn = ConnectionHelperFactory().createConnectionHelper()
    sigconn.connectUsingParams()
    sanitizer = SchemaSanitizer(sigconn)
    sanitizer.sanitize()
    sigconn.closeConnection()
    print("database restored!")
    sys.exit(0)


class TestQuery:
    def __init__(self, name: str, hidden_query: str, cs2: bool, union: bool, oj: bool, nep: bool, orf=None):
        self.qid = name
        self.cs2 = cs2
        self.union = union
        self.oj = oj
        self.nep = nep
        self.query = hidden_query
        self.orf = orf if orf is not None else False

    @classmethod
    def print(cls, qid):
        for test_query in build_workload():
            if test_query.qid == qid:
                print(test_query.query)
                return
        print(f"Unknown query id: {qid}", file=sys.stderr)
        sys.exit(2)


def create_workload():
    test_workload = [TestQuery("U1", """(SELECT p_partkey, p_name FROM part, partsupp where p_partkey = ps_partkey and ps_availqty > 100
Order By p_partkey Limit 5)
UNION ALL (SELECT s_suppkey, s_name FROM supplier, partsupp where s_suppkey = ps_suppkey and
ps_availqty > 200 Order By s_suppkey Limit 7);""",False, True, False, False),
                     TestQuery("U2", """(SELECT s_suppkey, s_name FROM supplier, nation where s_nationkey = n_nationkey and  n_name = 'GERMANY' order by s_suppkey desc, s_name limit 12)UNION ALL (SELECT c_custkey, c_name FROM customer,  orders where c_custkey = o_custkey and o_orderpriority = '1-URGENT' order by c_custkey, c_name desc limit 10);
""", False, True, False, False),
                     TestQuery("U3", """(SELECT c_custkey as key, c_name as name FROM customer, nation where c_nationkey = n_nationkey and  n_name = 'UNITED STATES' Order by key Limit 10)
 UNION ALL (SELECT p_partkey as key, p_name as name FROM part , lineitem where p_partkey = l_partkey and l_quantity > 35 Order By key Limit 10) 
 UNION ALL (select n_nationkey as key, r_name as name from nation, region where n_name LIKE 'B%' Order By key Limit 5)
""", False, True, False, False),
                     TestQuery("U4", """(SELECT c_custkey, c_name FROM customer,  nation where c_nationkey = n_nationkey and n_name = 'UNITED STATES' Order By c_custkey desc Limit 5) 
 UNION ALL (SELECT s_suppkey, s_name FROM supplier ,  nation where s_nationkey = n_nationkey and n_name = 'CANADA' Order By s_suppkey Limit 6) 
 UNION ALL (SELECT p_partkey, p_name FROM part ,  lineitem where p_partkey = l_partkey and l_quantity > 20 Order By p_partkey desc Limit 7) 
 UNION ALL (SELECT ps_partkey, p_name FROM part ,  partsupp where p_partkey = ps_partkey and ps_supplycost >= 1000 Order By ps_partkey Limit 8)
""", False, True, False, False),
                     TestQuery("U5", """(SELECT o_orderkey, o_orderdate, n_name FROM orders, customer, nation where o_custkey = c_custkey and c_nationkey = n_nationkey and c_name like '%0001248%'  AND o_orderdate >= '1997-01-01' order by o_orderkey Limit 20) 
 UNION ALL (SELECT l_orderkey, l_shipdate, o_orderstatus FROM lineitem, orders where l_orderkey = o_orderkey and o_orderdate < '1994-01-01'   AND l_quantity > 20   AND l_extendedprice > 1000 order by l_orderkey Limit 5);
""", False, True, False, False),
                     TestQuery("U6", """(SELECT o_clerk as name, SUM(l_extendedprice) AS total_price FROM orders, lineitem where o_orderkey = l_orderkey and o_orderdate <= '1995-01-01' GROUP BY o_clerk ORDER BY total_price DESC LIMIT 10) 
 UNION ALL (SELECT n_name as name, SUM(s_acctbal) AS total_price FROM nation ,supplier where n_nationkey = s_nationkey and n_name like '%UNITED%' GROUP BY n_name ORDER BY n_name DESC Limit 10);
""", False, True, False, False),
                     TestQuery("U7", """(SELECT     l_orderkey as key,     l_extendedprice as price,     l_partkey as s_key FROM     lineitem WHERE     l_shipdate >= DATE '1994-01-01'     AND l_shipdate < DATE '1995-01-01'     AND l_quantity > 30  Order By key Limit 20)
 UNION ALL  (SELECT     ps_partkey as key,     p_retailprice as price,     ps_suppkey as s_key FROM     partsupp,supplier,part where ps_suppkey = s_suppkey and ps_partkey = p_partkey     AND ps_supplycost < 100 Order By price Limit 20);
""", False, True, False, False),
                     TestQuery("U8", """(SELECT c_custkey AS order_id, COUNT(*) AS total
 FROM customer, orders
 WHERE c_custkey = o_custkey
   AND o_orderdate >= '1995-01-01'
 GROUP BY c_custkey
 ORDER BY total ASC LIMIT 10)
UNION ALL
(SELECT l_orderkey AS order_id, AVG(l_quantity) AS total
 FROM orders, lineitem
 WHERE l_orderkey = o_orderkey
   AND o_orderdate < DATE '1996-07-01'
 GROUP BY l_orderkey
 ORDER BY total DESC LIMIT 10);""", False, True, False, False),
                     TestQuery("U9", """(select c_name, n_name from customer, nation where
c_mktsegment='BUILDING' and c_acctbal > 100 and c_nationkey
= n_nationkey) UNION ALL (select s_name, n_name from supplier,
nation where s_acctbal > 4000 and s_nationkey = n_nationkey);""", False, True, False, False),
                     TestQuery("O1", """select c_name, n_name, count(*) as total from nation RIGHT OUTER
JOIN customer ON c_nationkey = n_nationkey and c_acctbal < 1000
        GROUP BY c_name,
n_name Order by c_name, n_name desc Limit 10;""",False, False, True, False),
                     TestQuery("O2", """SELECT l_shipmode, o_shippriority ,count(*) as low_line_count FROM
lineitem LEFT OUTER JOIN orders ON ( l_orderkey = o_orderkey AND
o_totalprice > 50000 ) WHERE l_linenumber = 4 AND l_quantity < 30
GROUP BY l_shipmode, o_shippriority Order By l_shipmode Limit 5;""",False, False, True, False),
                     TestQuery("O3", """SELECT o_custkey as key, sum(c_acctbal), o_clerk, c_name from orders FULL OUTER JOIN customer on c_custkey = o_custkey and
o_orderstatus = 'F' group by o_custkey, o_clerk, c_name order by key
limit 35;""",False, False, True, False),
                     TestQuery("O4", """SELECT p_size, s_phone, ps_supplycost, n_name FROM part RIGHT
OUTER JOIN partsupp ON p_partkey = ps_partkey AND p_size >
7 LEFT OUTER JOIN supplier ON ps_suppkey = s_suppkey AND
s_acctbal < 2000 FULL OUTER JOIN nation on s_nationkey =
n_nationkey and n_regionkey > 3 Order by ps_supplycost asc Limit 50;""",False, False, True, False),
                     TestQuery("O5", """Select ps_suppkey, p_name, p_type from part RIGHT outer join partsupp on p_partkey=ps_partkey and p_size > 4 and ps_availqty > 3350 Order By ps_suppkey Limit 100;
""",False, False, True, False),
                     TestQuery("O6", """SELECT p_name, s_phone, ps_supplycost, n_name FROM part RIGHT OUTER JOIN partsupp ON p_partkey = ps_partkey AND p_size > 7
	LEFT OUTER JOIN supplier ON ps_suppkey = s_suppkey AND s_acctbal < 2000 FULL OUTER JOIN nation on s_nationkey = n_nationkey
	and n_regionkey > 3 Order By p_name, s_phone, ps_supplycost, n_name desc Limit 20;
""",False, False, True, False),
                     TestQuery("A1", """Select l_shipmode, count(*) as count From orders, lineitem Where
o_orderkey = l_orderkey and l_commitdate < l_receiptdate and
l_shipdate < l_commitdate and l_receiptdate >= '1994-01-01' and
l_receiptdate < '1995-01-01' and l_extendedprice <= o_totalprice
and l_extendedprice <= 70000 and o_totalprice > 60000 Group By
l_shipmode Order By l_shipmode;""",False, False, False, False),
                     TestQuery("A2", """Select o_orderpriority, count(*) as order_count From orders, lineitem
Where l_orderkey = o_orderkey and o_orderdate >= '1993-07-01' and
o_orderdate < '1993-10-01' and l_commitdate <= l_receiptdate Group
By o_orderpriority Order By o_orderpriority;""",False, False, False, False),
                     TestQuery("A3", """Select l_orderkey, l_linenumber From orders, lineitem, partsupp Where
o_orderkey = l_orderkey and ps_partkey = l_partkey and ps_suppkey
= l_suppkey and ps_availqty = l_linenumber and l_shipdate >=
o_orderdate and o_orderdate >= '1990-01-01' and l_commitdate <=
l_receiptdate and l_shipdate <= l_commitdate and l_receiptdate > '1994-01-01' Order By l_orderkey Limit 7;
""",False, False, False, False),
                     TestQuery("A4", """Select s_name, count(*) as numwait From supplier, lineitem, orders,
nation Where s_suppkey = l_suppkey and o_orderkey = l_orderkey and
o_orderstatus = 'F' and l_receiptdate >= l_commitdate and s_nationkey
= n_nationkey Group By s_name Order By numwait desc Limit 100;""",False, False, False, False),
                     TestQuery("A5", """Select l_returnflag, l_linestatus, sum(l_quantity) as sum_qty,
sum(l_extendedprice) as sum_base_price, sum(l_extendedprice
* (1 - l_discount)) as sum_disc_price, sum(l_extendedprice * (1 -
l_discount) * (1 + l_tax)) as sum_charge, avg(l_quantity) as avg_qty,
avg(l_extendedprice) as avg_price, avg(l_discount) as avg_disc, count(*)
as count_order From lineitem Where l_shipdate <= l_receiptdate and
l_receiptdate <= l_commitdate Group By l_returnflag, l_linestatus
Order by l_returnflag, l_linestatus;""",False, False, False, False),
                     TestQuery("N1", """Select p_brand, p_type, p_size, Count(*) as supplier_cnt
 From part, partsupp
 Where p_partkey = ps_partkey
 and p_size >= 4 and p_type NOT LIKE 'SMALL PLATED%'  and p_brand <> 'Brand#45'
 Group By p_brand, p_size, p_type
 Order By supplier_cnt desc, p_brand asc, p_type asc, p_size asc;""", False, False, False, True),
                     TestQuery("F1", """(SELECT c_name as name, c_acctbal as account_balance FROM orders,
customer, nation WHERE c_custkey = o_custkey and c_nationkey
= n_nationkey and c_mktsegment = 'FURNITURE' and n_name =
'INDIA' and o_orderdate between '1998-01-01' and '1998-12-05' and
o_totalprice <= c_acctbal) UNION ALL (SELECT s_name as name,
s_acctbal as account_balance FROM supplier, lineitem, orders, nation
WHERE l_suppkey = s_suppkey and l_orderkey = o_orderkey
and s_nationkey = n_nationkey and n_name = 'ARGENTINA' and
o_orderdate between '1998-01-01' and '1998-01-05' and o_totalprice >
s_acctbal and o_totalprice >= 30000 and 50000 >= s_acctbal Order by account_balance desc limit 20);
""", False, True, True, False),
                     TestQuery("F2", """(Select p_brand, o_clerk, l_shipmode From orders, lineitem, part Where
l_partkey = p_partkey and o_orderkey = l_orderkey and l_shipdate >=
o_orderdate and o_orderdate > '1994-01-01' and l_shipdate > '1995-01-01' and p_retailprice >= l_extendedprice and p_partkey < 10000 and
l_suppkey < 10000 and p_container = 'LG CAN' Order By o_clerk LIMIT
5) UNION ALL (Select p_brand, s_name, l_shipmode From lineitem,
part, supplier Where l_partkey = p_partkey and l_suppkey = s_suppkey
and l_shipdate > '1995-01-01' and s_acctbal >= l_extendedprice and
p_partkey < 15000 and l_suppkey < 14000 and p_container = 'LG CAN'
Order By s_name LIMIT 10);""", False, True, True, False),
                     TestQuery("F3", """(
	select l_orderkey, l_extendedprice as price, p_partkey from lineitem, part
	where l_partkey = p_partkey  and p_container LIKE 'JUMBO%' and p_partkey > 3000 and l_partkey < 3010
	Order by l_orderkey, price desc Limit 100
) union all (select o_orderkey, c_acctbal as price, c_custkey
from customer LEFT OUTER JOIN orders on c_custkey = o_custkey
 where c_custkey > 1000 and c_custkey < 1010 Order By price desc, o_orderkey, c_custkey Limit 100);
""", False, True, True, False),
                     TestQuery("F4", """select n_name, c_acctbal from nation LEFT OUTER JOIN customer 
                     ON n_nationkey = c_nationkey and c_nationkey > 3 and n_nationkey < 20 and 
                     c_nationkey != 10 LIMIT 200;
""", False, True, True, True),
                     TestQuery("MQ1", """SELECT l_returnflag, l_linestatus, 
       SUM(l_quantity) AS sum_qty, 
       SUM(l_extendedprice) AS sum_base_price, 
       SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price, 
       SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, 
       AVG(l_quantity) AS avg_qty, 
       AVG(l_extendedprice) AS avg_price, 
       AVG(l_discount) AS avg_disc, 
       COUNT(*) AS count_order
FROM lineitem 
WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL '71 days' 
GROUP BY l_returnflag, l_linestatus 
ORDER BY l_returnflag, l_linestatus;""",False, False, False, False),
                     TestQuery("MQ2", """SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
FROM part, supplier, partsupp, nation, region
WHERE p_partkey = ps_partkey 
  AND s_suppkey = ps_suppkey 
  AND p_size = 38 
  AND p_type LIKE '%TIN' 
  AND s_nationkey = n_nationkey 
  AND n_regionkey = r_regionkey 
  AND r_name = 'MIDDLE EAST'
ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
LIMIT 100;""",False, True, True, True, True),
                     TestQuery("MQ3", """SELECT l_orderkey, 
       SUM(l_extendedprice * (1 - l_discount)) AS revenue, 
       o_orderdate, o_shippriority
FROM customer, orders, lineitem
WHERE c_mktsegment = 'BUILDING' 
  AND c_custkey = o_custkey 
  AND l_orderkey = o_orderkey 
  AND o_orderdate < DATE '1995-03-15' 
  AND l_shipdate > DATE '1995-03-15'
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate
LIMIT 10;""", False, False, False, False),
                     TestQuery("MQ4", """SELECT o_orderdate, o_orderpriority, COUNT(*) AS order_count
FROM orders
WHERE o_orderdate >= DATE '1997-07-01' 
  AND o_orderdate < DATE '1997-07-01' + INTERVAL '3 months'
GROUP BY o_orderdate, o_orderpriority
ORDER BY o_orderpriority
LIMIT 10;""",False, False, False, False),
                     TestQuery("MQ5", """SELECT n_name, 
       SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM customer, orders, lineitem, supplier, nation, region
WHERE c_custkey = o_custkey 
  AND l_orderkey = o_orderkey 
  AND l_suppkey = s_suppkey 
  AND c_nationkey = s_nationkey 
  AND s_nationkey = n_nationkey 
  AND n_regionkey = r_regionkey 
  AND r_name = 'MIDDLE EAST' 
  AND o_orderdate >= DATE '1994-01-01' 
  AND o_orderdate < DATE '1994-01-01' + INTERVAL '1 year'
GROUP BY n_name
ORDER BY revenue DESC
LIMIT 100;""",False, False, False, False),
                     TestQuery("MQ6", """SELECT l_shipmode, 
       SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= DATE '1994-01-01' 
  AND l_shipdate < DATE '1994-01-01' + INTERVAL '1 year' 
  AND l_quantity < 24
GROUP BY l_shipmode
LIMIT 100;""",False, False, False, False),
                     TestQuery("MQ10", """SELECT c_name, 
       SUM(l_extendedprice * (1 - l_discount)) AS revenue, 
       c_acctbal, n_name, c_address, c_phone, c_comment
FROM customer, orders, lineitem, nation
WHERE c_custkey = o_custkey 
  AND l_orderkey = o_orderkey 
  AND o_orderdate >= DATE '1994-01-01' 
  AND o_orderdate < DATE '1994-01-01' + INTERVAL '3 months' 
  AND l_returnflag = 'R' 
  AND c_nationkey = n_nationkey
GROUP BY c_name, c_acctbal, c_phone, n_name, c_address, c_comment
ORDER BY revenue DESC
LIMIT 20;""",False, False, False, False),
                     TestQuery("MQ11", """SELECT ps_comment, 
       SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey 
  AND s_nationkey = n_nationkey 
  AND n_name = 'ARGENTINA'
GROUP BY ps_comment
ORDER BY value DESC
LIMIT 100;""",False, False, False, False),
                     TestQuery("MQ17", """SELECT AVG(l_extendedprice) AS avg_total
FROM lineitem, part
WHERE p_partkey = l_partkey 
  AND p_brand = 'Brand#52' 
  AND p_container = 'LG CAN';""",False, False, False, False),
                     TestQuery("MQ18", """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%' 
  AND c_custkey = o_custkey 
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;""",False, False, False, False, False),
                     TestQuery("MQ21", """SELECT s_name, COUNT(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE s_suppkey = l1.l_suppkey 
  AND o_orderkey = l1.l_orderkey 
  AND o_orderstatus = 'F' 
  AND s_nationkey = n_nationkey 
  AND n_name = 'GERMANY'
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100;""",False, False, False, False),
                     TestQuery("Alaap", """select c_mktsegment, 
                         sum(l_extendedprice*(1-l_discount) + l_quantity) as revenue,
                         o_orderdate, o_shippriority 
                         from customer, orders, lineitem 
                         where c_custkey = o_custkey and l_orderkey = o_orderkey and 
                         o_orderdate <= date '1995-10-13' and l_extendedprice between 212 and 3000 
                        and l_quantity <= 123  group by o_orderdate, o_shippriority, c_mktsegment 
                         order by revenue desc, o_orderdate asc, o_shippriority asc;""", False, False, False, False),
                     TestQuery("TPCH_Q12", """select
	l_shipmode,
	sum(case
		when o_orderpriority = '1-URGENT'
			or o_orderpriority = '2-HIGH'
			then 1
		else 0
	end) as high_line_count,
	sum(case
		when o_orderpriority <> '1-URGENT'
			and o_orderpriority <> '2-HIGH'
			then 1
		else 0
	end) as low_line_count
from
	orders,
	lineitem
where
	o_orderkey = l_orderkey
	and l_shipmode = 'SHIP'
	and l_commitdate < l_receiptdate
	and l_shipdate < l_commitdate
	and l_receiptdate >= date '1995-01-01'
	and l_receiptdate < date '1995-01-01' + interval '1' year
group by
	l_shipmode
order by
	l_shipmode;""", False, False, False, False),
                     TestQuery("TPCH_Q14", """select
	100.00 * sum(case
		when p_type like 'PROMO%'
			then l_extendedprice * (1 - l_discount)
		else 0
	end) / sum(l_extendedprice * (1 - l_discount)) as promo_revenue
from
	lineitem,
	part
where
	l_partkey = p_partkey
	and l_shipdate >= date '1995-01-01'
	and l_shipdate < date '1995-01-01' + interval '1' month;""", False, False, False, False),
                     TestQuery("oj_bug", """SELECT c_custkey, c_name, c_mktsegment, o_orderkey
FROM customer FULL OUTER JOIN orders ON c_custkey = o_custkey
WHERE c_mktsegment = 'BUILDING';""", False, False, True, False),
                     TestQuery("QN1", "SELECT c_name, c_acctbal FROM customer "
            "WHERE c_mktsegment <> 'BUILDING' AND c_acctbal > 9000;", False, False, False, True, False),
        TestQuery("QN2", "SELECT o_orderkey, o_totalprice FROM orders WHERE o_orderstatus <> 'F' AND o_orderpriority <> '1-URGENT';", False, False, False, True, False)
, TestQuery("QD2", "SELECT c_name, c_acctbal FROM customer WHERE c_mktsegment IN ('BUILDING', 'MACHINERY', 'AUTOMOBILE') AND c_acctbal > 5000;", False, False, False, False, True),
TestQuery("nep", "SELECT l_shipmode, SUM(l_extendedprice) AS revenue FROM lineitem WHERE l_shipdate < '1994-01-01' AND l_quantity < 24 AND l_linenumber <> 4 AND l_returnflag <> 'R' GROUP BY l_shipmode LIMIT 100;", False, False, False, True, False),
                     # Queries added from U2_workload.sql
                     TestQuery("F16", """SELECT
    o_clerk,
    AVG(2 * o_totalprice + 35.90) AS total_price,
    c_acctbal,
    n_name
FROM orders, customer, nation
WHERE
    c_custkey = o_custkey
    AND c_nationkey = n_nationkey
    AND n_nationkey IN (1, 3, 5, 4, 10, 11)
    AND c_acctbal < 7000
    AND c_acctbal > 1000
    AND o_totalprice > 2500
    AND o_totalprice <= 15005.06
    AND c_acctbal <= o_totalprice
GROUP BY o_clerk, c_acctbal, n_name
ORDER BY total_price DESC, o_clerk, c_acctbal, n_name;""", False, False, False, False, True),
                     TestQuery("A7", """SELECT
    o_clerk,
    AVG(2 * o_totalprice + 1) AS total_price,
    c_acctbal,
    n_name
FROM orders, customer, nation
WHERE
    c_custkey = o_custkey
    AND c_nationkey = n_nationkey
    AND c_acctbal < 7000
    AND c_acctbal > 1000
    AND o_totalprice > 2500
    AND o_totalprice <= 15005.06
    AND c_acctbal <= o_totalprice
GROUP BY o_clerk, c_acctbal, n_name
ORDER BY total_price DESC, o_clerk, c_acctbal, n_name;""", False, False, False, False, False),
                     TestQuery("A8", """SELECT
    o_clerk,
    SUM(c_acctbal + 2 * o_totalprice) AS total_price,
    n_name
FROM orders, customer, nation
WHERE
    c_custkey = o_custkey
    AND c_nationkey = n_nationkey
    AND c_acctbal < 7000
    AND c_acctbal > 1000
    AND c_acctbal <= o_totalprice
GROUP BY o_clerk, n_name
ORDER BY o_clerk
LIMIT 30;""", False, False, False, False, False),
                     TestQuery("F17", """SELECT
    o_clerk,
    SUM(c_acctbal + 3.54 * o_totalprice) AS total_price,
    n_name
FROM orders, customer, nation
WHERE
    c_custkey = o_custkey
    AND c_custkey > 5000
    AND c_nationkey = n_nationkey
    AND n_nationkey IN (1, 2, 4, 5, 3, 10)
    AND c_acctbal < 7000
    AND o_totalprice > 1000
    AND c_acctbal <= o_totalprice
GROUP BY o_clerk, n_name
ORDER BY o_clerk
LIMIT 30;""", False, False, False, False, True),
                     TestQuery("A10", """SELECT
    l_shipmode,
    COUNT(*) AS count
FROM orders, lineitem
WHERE
    o_orderkey = l_orderkey
    AND l_commitdate <= l_receiptdate
    AND l_shipdate <= l_commitdate
    AND l_receiptdate >= '1994-01-01'
    AND l_receiptdate <= '1995-01-01'
    AND l_extendedprice < o_totalprice
    AND l_extendedprice <= 70000
    AND o_totalprice >= 60000
GROUP BY l_shipmode
ORDER BY l_shipmode;""", False, False, False, False, False),
                     TestQuery("A11", """SELECT
    c_name AS name,
    c_acctbal AS account_balance
FROM orders, customer, nation
WHERE
    o_custkey > 1000
    AND c_custkey = o_custkey
    AND c_custkey <= 5527
    AND c_nationkey = n_nationkey
    AND o_orderdate BETWEEN '1998-01-01' AND '1998-01-15'
    AND o_totalprice <= c_acctbal;""", False, False, False, False, False),
                     TestQuery("F5", """(SELECT
    p_partkey,
    p_name
 FROM part, partsupp
 WHERE p_partkey = ps_partkey
   AND ps_availqty >= 101)
UNION ALL
(SELECT
    s_suppkey AS p_partkey,
    s_name AS p_name
 FROM partsupp, supplier
 WHERE ps_suppkey = s_suppkey
   AND ps_availqty >= 201);""", False, True, False, False, False),
                     TestQuery("A12", """SELECT
    l_shipmode,
    COUNT(*) AS count
FROM lineitem, orders
WHERE
    l_orderkey = o_orderkey
    AND l_extendedprice <= o_totalprice
    AND 60000 < o_totalprice
    AND l_extendedprice < 70000
    AND l_receiptdate <= '1994-12-31'
    AND '1994-01-01' <= l_receiptdate
    AND l_shipdate < l_commitdate
    AND l_commitdate < l_receiptdate
GROUP BY l_shipmode
ORDER BY l_shipmode ASC;""", False, False, False, False, False),
                     TestQuery("A13", """SELECT
    o_orderpriority,
    COUNT(*) AS order_count
FROM lineitem, orders
WHERE
    l_orderkey = o_orderkey
    AND l_commitdate <= l_receiptdate
    AND '1993-07-01' <= o_orderdate
    AND o_orderdate <= '1993-09-30'
GROUP BY o_orderpriority
ORDER BY o_orderpriority ASC;""", False, False, False, False, False),
                     TestQuery("F6", """(SELECT
    p_brand,
    s_name AS o_clerk,
    l_shipmode
 FROM lineitem, part, supplier
 WHERE
    l_partkey = p_partkey
    AND p_container = 'LG CAN'
    AND l_shipdate >= '1995-01-02'
    AND l_suppkey < 14000
    AND l_partkey < 15000
    AND l_extendedprice <= s_acctbal
 ORDER BY o_clerk ASC
 LIMIT 10)
UNION ALL
(SELECT
    p_brand,
    o_clerk,
    l_shipmode
 FROM lineitem, orders, part
 WHERE
    l_orderkey = o_orderkey
    AND l_partkey = p_partkey
    AND p_container = 'LG CAN'
    AND l_suppkey < 10000
    AND l_partkey < 10000
    AND l_extendedprice <= p_retailprice
    AND o_orderdate <= l_shipdate
    AND '1994-01-02' <= o_orderdate
    AND '1995-01-02' <= l_shipdate
 ORDER BY o_clerk ASC
 LIMIT 5);""", False, True, False, False, False),
                     TestQuery("A14", """SELECT
    o_orderkey AS l_orderkey,
    ps_availqty AS l_linenumber
FROM lineitem, orders, partsupp
WHERE
    l_partkey = ps_partkey
    AND l_suppkey = ps_suppkey
    AND l_linenumber = ps_availqty
    AND l_orderkey = o_orderkey
    AND o_orderdate <= l_shipdate
    AND l_shipdate <= l_commitdate
    AND l_commitdate <= l_receiptdate
    AND '1990-01-01' <= o_orderdate
    AND '1994-01-02' <= l_receiptdate
ORDER BY l_orderkey ASC
LIMIT 7;""", False, False, False, False, False),
                     TestQuery("A15", """SELECT
    s_name,
    COUNT(*) AS numwait
FROM lineitem, nation, orders, supplier
WHERE
    l_orderkey = o_orderkey
    AND l_suppkey = s_suppkey
    AND n_nationkey = s_nationkey
    AND o_orderstatus = 'F'
    AND l_commitdate <= l_receiptdate
GROUP BY s_name
ORDER BY numwait DESC, s_name ASC
LIMIT 100;""", False, False, False, False, False),
                     TestQuery("A16", """SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (-l_discount * l_tax - l_discount + l_tax + 1)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM lineitem
WHERE
    l_shipdate <= l_receiptdate
    AND l_receiptdate <= l_commitdate
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag ASC, l_linestatus ASC;""", False, False, False, False, False),
                     TestQuery("U10", """(SELECT
    s_suppkey,
    s_name
 FROM nation, supplier
 WHERE
    n_nationkey = s_nationkey
    AND n_name = 'GERMANY')
UNION ALL
(SELECT
    c_custkey AS s_suppkey,
    c_name AS s_name
 FROM customer, orders
 WHERE
    c_custkey = o_custkey
    AND o_orderpriority = '1-URGENT');""", False, True, False, False, False),
                     TestQuery("U11", """(SELECT
    c_custkey AS key,
    c_name AS name
 FROM customer, nation
 WHERE
    c_nationkey = n_nationkey
    AND n_name = 'UNITED STATES')
UNION ALL
(SELECT
    l_partkey AS key,
    p_name AS name
 FROM lineitem, part
 WHERE
    l_partkey = p_partkey
    AND l_quantity > 35);""", False, True, False, False, False),
                     TestQuery("U12", """(SELECT
    s_suppkey AS c_custkey,
    s_name AS c_name
 FROM nation, supplier
 WHERE
    n_nationkey = s_nationkey
    AND n_name = 'CANADA')
UNION ALL
(SELECT
    c_custkey,
    c_name
 FROM customer, nation
 WHERE
    c_nationkey = n_nationkey
    AND n_name = 'UNITED STATES')
UNION ALL
(SELECT
    l_partkey AS c_custkey,
    p_name AS c_name
 FROM lineitem, part
 WHERE
    l_partkey = p_partkey
    AND l_quantity > 20);""", False, True, False, False, False),
                     TestQuery("U13", """(SELECT
    o_orderkey,
    l_shipdate AS o_orderdate
 FROM lineitem, orders
 WHERE
    l_orderkey = o_orderkey
    AND o_orderdate <= '1993-12-31'
    AND 20 < l_quantity
    AND 1000 < l_extendedprice)
UNION ALL
(SELECT
    o_orderkey,
    o_orderdate
 FROM customer, orders
 WHERE
    c_custkey = o_custkey
    AND c_name LIKE '%0001248%'
    AND o_orderdate >= '1997-01-01');""", False, True, False, False, False),
                     TestQuery("U14", """(SELECT
    n_name AS name,
    SUM(s_acctbal) AS total_price
 FROM nation, supplier
 WHERE
    n_nationkey = s_nationkey
    AND n_name LIKE '%UNITED%'
 GROUP BY n_name
 ORDER BY name DESC)
UNION ALL
(SELECT
    o_clerk AS name,
    SUM(l_extendedprice) AS total_price
 FROM lineitem, orders
 WHERE
    l_orderkey = o_orderkey
    AND o_orderdate <= '1995-01-01'
 GROUP BY o_clerk
 ORDER BY total_price DESC, name DESC
 LIMIT 10);""", False, True, False, False, False),
                     TestQuery("U15", """(SELECT
    l_orderkey AS key,
    l_extendedprice AS price,
    l_partkey AS s_key
 FROM lineitem
 WHERE
    l_quantity > 30
    AND l_shipdate >= '1994-01-01'
    AND l_shipdate <= '1994-12-31')
UNION ALL
(SELECT
    p_partkey AS key,
    p_retailprice AS price,
    s_suppkey AS s_key
 FROM part, partsupp, supplier
 WHERE
    p_partkey = ps_partkey
    AND ps_suppkey = s_suppkey
    AND ps_supplycost < 100);""", False, True, False, False, False),
                     TestQuery("U16", """(SELECT
    c_custkey AS order_id,
    COUNT(*) AS total
 FROM customer, orders
 WHERE
    c_custkey = o_custkey
    AND o_orderdate >= '1995-01-01'
 GROUP BY c_custkey
 ORDER BY total ASC, order_id DESC
 LIMIT 10)
UNION ALL
(SELECT
    l_orderkey AS order_id,
    AVG(l_quantity) AS total
 FROM lineitem, orders
 WHERE
    l_orderkey = o_orderkey
    AND o_orderdate <= '1996-06-30'
 GROUP BY l_orderkey
 ORDER BY total DESC, order_id ASC
 LIMIT 10);""", False, True, False, False, False),
                     TestQuery("F7", """(SELECT
    s_name AS name,
    s_acctbal AS account_balance
 FROM lineitem, nation, orders, supplier
 WHERE
    l_orderkey = o_orderkey
    AND l_suppkey = s_suppkey
    AND n_nationkey = s_nationkey
    AND n_name = 'ARGENTINA'
    AND o_orderdate >= '1998-01-01'
    AND o_orderdate <= '1998-01-05'
    AND s_acctbal <= o_totalprice
    AND 30000 < o_totalprice
    AND s_acctbal < 50000)
UNION ALL
(SELECT
    c_name AS name,
    c_acctbal AS account_balance
 FROM customer, nation, orders
 WHERE
    c_nationkey = n_nationkey
    AND c_custkey = o_custkey
    AND n_name = 'INDIA'
    AND c_mktsegment = 'FURNITURE'
    AND o_orderdate >= '1998-01-01'
    AND o_orderdate <= '1998-01-05'
    AND o_totalprice <= c_acctbal);""", False, True, False, False, False),
                     TestQuery("O7", """SELECT
    n_name,
    r_comment
FROM nation
FULL OUTER JOIN region
    ON n_regionkey = r_regionkey
   AND r_name = 'AFRICA';""", False, False, True, False, False),
                     TestQuery("O8", """SELECT
    n_name,
    c_comment
FROM nation
RIGHT OUTER JOIN customer
    ON c_nationkey = n_nationkey
   AND c_acctbal < 1000;""", False, False, True, False, False),
                     TestQuery("F8", """SELECT
    n_name,
    r_comment
FROM nation
FULL OUTER JOIN region
    ON n_regionkey = r_regionkey
   AND r_name = 'AFRICA'

UNION ALL

SELECT
    n_name,
    c_comment
FROM nation
RIGHT OUTER JOIN customer
    ON c_nationkey = n_nationkey
   AND c_acctbal < 1000;""", False, True, True, False, False),
                     TestQuery("F9", """SELECT
    n_name,
    r_comment,
    c_acctbal
FROM nation
FULL OUTER JOIN region
    ON n_regionkey = r_regionkey
   AND r_name = 'AFRICA'
LEFT OUTER JOIN customer
    ON c_nationkey = n_nationkey
   AND c_mktsegment = 'BUILDING'

UNION ALL

SELECT
    c_name,
    o_comment,
    l_discount
FROM orders
RIGHT OUTER JOIN customer
    ON c_custkey = o_custkey
   AND c_acctbal < 1000
RIGHT OUTER JOIN lineitem
    ON o_orderkey = l_orderkey
   AND l_extendedprice > 7000
   AND o_orderstatus = 'F';""", False, True, True, False, False),
                     TestQuery("O9", """SELECT
    c_name,
    o_comment,
    l_discount
FROM orders
RIGHT OUTER JOIN customer
    ON c_custkey = o_custkey
   AND c_acctbal < 1000
RIGHT OUTER JOIN lineitem
    ON o_orderkey = l_orderkey
   AND l_extendedprice > 7000
   AND o_orderstatus = 'F';""", False, False, True, False, False),
                     TestQuery("N2", """SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_shipdate >= '1994-01-01'
  AND l_quantity < 24
  AND l_returnflag <> 'R'
GROUP BY l_shipmode
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N3", """SELECT l_shipmode, COUNT(*) AS count
FROM lineitem
WHERE l_quantity > 20
  AND l_quantity <> 25
GROUP BY l_shipmode
ORDER BY l_shipmode;""", False, False, False, True, False),
                     TestQuery("N4", """SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_shipdate < '1994-01-01'
  AND l_quantity < 24
  AND l_linenumber <> 4
  AND l_returnflag <> 'R'
GROUP BY l_shipmode
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N5", """SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_quantity < 24
  AND l_shipdate <> '1994-01-02'
  AND l_shipmode NOT LIKE '%AIR%'
GROUP BY l_shipmode
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N6", """SELECT s_name, COUNT(*) AS numwait
FROM supplier, lineitem, orders, nation
WHERE s_suppkey = l_suppkey
  AND o_orderkey = l_orderkey
  AND o_orderstatus = 'F'
  AND s_nationkey = n_nationkey
  AND n_name <> 'GERMANY'
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N7", """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-_%'
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
  AND c_name <> 'Customer#000060217'
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N8", """SELECT ps_comment, SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = 'ARGENTINA'
  AND ps_comment NOT LIKE '%regular%dependencies%'
  AND s_acctbal <> 2177.90
GROUP BY ps_comment
ORDER BY value DESC
LIMIT 100;""", False, False, False, True, False),
                     TestQuery("N9", """SELECT *
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = 'ARGENTINA'
  AND ps_comment <> 'dependencies'
  AND ps_comment <> 'hello world regular mina dependencies';""", False, False, False, True, False),
                     TestQuery("F10", """select n_name, c_acctbal from nation, customer WHERE n_nationkey = c_nationkey and 
  n_nationkey IN (1, 2, 3, 5, 4, 13, 14, 15) and c_acctbal < 7000 and c_acctbal > 1000 ORDER BY c_acctbal;""", False, False, False, False, True),
                     TestQuery("F11", """select n_name, c_acctbal from nation, customer where n_nationkey = c_nationkey and c_nationkey > 3 and 
  n_nationkey < 20 and c_nationkey != 10 and c_acctbal < 7000 LIMIT 200;""", False, False, False, True, False),
                     TestQuery("F12", """select sum(l_extendedprice) as revenue from lineitem 
  where l_shipdate >= date '1994-01-01' and l_shipdate < date '1994-01-01' + interval '1' year 
  and (l_quantity < 10 or l_quantity between 24 and 42 or l_quantity >= 50);""", False, False, False, False, True),
                     TestQuery("F13", """select avg(ps_supplycost) as cost from part, partsupp where p_partkey = ps_partkey 
  and (p_brand = 'Brand#52' or p_brand = 'Brand#12');""", False, False, False, False, True),
                     TestQuery("F14", """select p_size, ps_suppkey, count(*) as low_line_count from part, partsupp where 
  p_partkey = ps_partkey and p_brand IN ('Brand#52', 'Brand#34', 'Brand#15') and p_container IN ('WRAP BOX', 'MED BOX') 
  GROUP BY p_size, ps_suppkey  ORDER BY ps_suppkey desc LIMIT 30;""", False, False, False, False, True),
                     TestQuery("F15", """select n_name, s_acctbal, ps_availqty  from supplier, partsupp, nation where 
  ps_suppkey=s_suppkey AND ps_supplycost < 50 and s_nationkey=n_nationkey and (n_regionkey = 1 or n_regionkey =3) ORDER BY n_name;""", False, False, False, False, True),
                     ]
    return test_workload

OJ_SPEC = [("region", "r_name", None),
           ("nation", "n_name", "r_regionkey = n_regionkey"),
           ("supplier", "s_name", "n_nationkey = s_nationkey"),
           ("partsupp", "ps_availqty", "s_suppkey = ps_suppkey"),
           ("part", "p_name", "ps_partkey = p_partkey"),
           ("lineitem", "l_quantity", "p_partkey = l_partkey"),
           ("orders", "o_totalprice", "l_orderkey = o_orderkey"),
           ("customer", "c_name", "o_custkey = c_custkey")]

def oj_chain(k):
    sel = ", ".join(p for _, p, _ in OJ_SPEC[:k + 1])
    joins = "".join(f" LEFT OUTER JOIN {t} ON {on}" for t, _, on in OJ_SPEC[1:k + 1])
    return f"SELECT {sel} FROM region{joins};"

def ij_chain(k):
    """Inner-join version of oj_chain(k): same tables, same projections, same ON conditions."""
    sel = ", ".join(p for _, p, _ in OJ_SPEC[:k + 1])
    joins = "".join(f" INNER JOIN {t} ON {on}" for t, _, on in OJ_SPEC[1:k + 1])
    return f"SELECT {sel} FROM region{joins};"



# Disjunction scaling workload: DJ1..DJ10 (k = number of IN values). Add before `return test_workload`.
# Disjunction scaling workload on a string attribute: DS1..DS10 (k = number of IN values).
# Add before `return test_workload`.
DISJ_STR_VALUES = ['SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG',
                   'MED BOX', 'MED PKG', 'MED PACK', 'LG CASE', 'LG BOX']

def disj_str_query(k):
    vals = ", ".join(f"'{v}'" for v in DISJ_STR_VALUES[:k])
    return f"SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ({vals});"

# Fixed |AUX| = 8, varying number of branches k = 2..8 (ids UK2..UK8). Add before `return test_workload`.
# The 8 TPC-H tables form one foreign-key path, so any split into consecutive segments gives connected branches.
FA_PATH = ["region", "nation", "supplier", "partsupp", "part", "lineitem", "orders", "customer"]
FA_EDGES = ["r_regionkey = n_regionkey", "n_nationkey = s_nationkey", "s_suppkey = ps_suppkey",
            "ps_partkey = p_partkey", "p_partkey = l_partkey", "l_orderkey = o_orderkey",
            "o_custkey = c_custkey"]            # FA_EDGES[j] joins FA_PATH[j] and FA_PATH[j+1]
FA_PROJ = {"region": "r_name, r_regionkey", "nation": "n_name, n_nationkey",
           "supplier": "s_name, s_acctbal", "partsupp": "ps_comment, ps_supplycost",
           "part": "p_name, p_retailprice", "lineitem": "l_comment, l_extendedprice",
           "orders": "o_clerk, o_totalprice", "customer": "c_name, c_acctbal"}
# number of tables per branch, for each k
FA_SPLITS = {2: [4, 4], 3: [3, 3, 2], 4: [2, 2, 2, 2], 5: [2, 2, 2, 1, 1],
             6: [2, 2, 1, 1, 1, 1], 7: [2, 1, 1, 1, 1, 1, 1], 8: [1] * 8}

def fixed_aux_query(k):
    branches, i = [], 0
    for n in FA_SPLITS[k]:
        tabs, joins = FA_PATH[i:i + n], FA_EDGES[i:i + n - 1]
        i += n
        q = f"SELECT {FA_PROJ[tabs[0]]} FROM {', '.join(tabs)}"   # projects from the first table of the branch
        if joins:
            q += " WHERE " + " AND ".join(joins)
        branches.append(f"({q})")
    return " UNION ALL ".join(branches) + ";"

# Union scaling workload: UN3..UN8 (the number is |AUX|, the number of partial tables). 3 branches throughout.
# Add before `return test_workload`.
UNION_BRANCHES = [  # (tables in growth order, projection, join conditions in growth order)
    (["supplier", "nation", "region"], "s_name, s_acctbal",
     ["s_nationkey = n_nationkey", "n_regionkey = r_regionkey"]),
    (["customer", "orders", "lineitem"], "c_name, c_acctbal",
     ["c_custkey = o_custkey", "o_orderkey = l_orderkey"]),
    (["part", "partsupp"], "p_name, p_retailprice",
     ["p_partkey = ps_partkey"]),
]
# tables used per branch, for each |AUX|
UNION_SIZES = {3: (1, 1, 1), 4: (2, 1, 1), 5: (2, 2, 1), 6: (2, 2, 2), 7: (3, 2, 2), 8: (3, 3, 2)}

def union_query(m):
    branches = []
    for (tabs, proj, joins), n in zip(UNION_BRANCHES, UNION_SIZES[m]):
        q = f"SELECT {proj} FROM {', '.join(tabs[:n])}"
        if n > 1:
            q += " WHERE " + " AND ".join(joins[:n - 1])
        branches.append(f"({q})")
    return " UNION ALL ".join(branches) + ";"


# TPC-DS union scaling workload. Add before `return test_workload`.
#   T3B3..T3B12 : 3 branches, |AUX| grows from 3 to 12
#   T6B6..T6B12 : 6 branches, |AUX| grows from 6 to 12
# Branches are disjoint stars (a fact table plus dimensions joined on single surrogate-key equalities); no common tables.
TPCDS_3B = [  # (tables in growth order, projection, join conditions in growth order)
    (["store_sales", "store", "household_demographics", "promotion"], "ss_ticket_number, ss_net_paid",
     ["ss_store_sk = s_store_sk", "ss_hdemo_sk = hd_demo_sk", "ss_promo_sk = p_promo_sk"]),
    (["catalog_sales", "catalog_page", "call_center", "ship_mode"], "cs_order_number, cs_net_paid",
     ["cs_catalog_page_sk = cp_catalog_page_sk", "cs_call_center_sk = cc_call_center_sk",
      "cs_ship_mode_sk = sm_ship_mode_sk"]),
    (["web_sales", "web_site", "web_page", "customer_address"], "ws_order_number, ws_net_paid",
     ["ws_web_site_sk = web_site_sk", "ws_web_page_sk = wp_web_page_sk", "ws_bill_addr_sk = ca_address_sk"]),
]
TPCDS_3B_SIZES = {3: (1, 1, 1), 4: (2, 1, 1), 5: (2, 2, 1), 6: (2, 2, 2), 7: (3, 2, 2),
                  8: (3, 3, 2), 9: (3, 3, 3), 10: (4, 3, 3), 11: (4, 4, 3), 12: (4, 4, 4)}

TPCDS_6B = [
    (["store_sales", "store"], "ss_ticket_number, ss_net_paid", ["ss_store_sk = s_store_sk"]),
    (["catalog_sales", "catalog_page"], "cs_order_number, cs_net_paid", ["cs_catalog_page_sk = cp_catalog_page_sk"]),
    (["web_sales", "web_site"], "ws_order_number, ws_net_paid", ["ws_web_site_sk = web_site_sk"]),
    (["store_returns", "reason"], "sr_ticket_number, sr_return_amt", ["sr_reason_sk = r_reason_sk"]),
    (["catalog_returns", "call_center"], "cr_order_number, cr_return_amount", ["cr_call_center_sk = cc_call_center_sk"]),
    (["web_returns", "web_page"], "wr_order_number, wr_return_amt", ["wr_web_page_sk = wp_web_page_sk"]),
]
TPCDS_6B_SIZES = {6: (1, 1, 1, 1, 1, 1), 7: (2, 1, 1, 1, 1, 1), 8: (2, 2, 1, 1, 1, 1),
                  9: (2, 2, 2, 1, 1, 1), 10: (2, 2, 2, 2, 1, 1), 11: (2, 2, 2, 2, 2, 1), 12: (2, 2, 2, 2, 2, 2)}

def tpcds_union_query(branches, sizes):
    parts = []
    for (tabs, proj, joins), n in zip(branches, sizes):
        q = f"SELECT {proj} FROM {', '.join(tabs[:n])}"
        if n > 1:
            q += " WHERE " + " AND ".join(joins[:n - 1])
        parts.append(f"({q})")
    return " UNION ALL ".join(parts) + ";"



def build_workload():
    workload = create_workload()
    workload += [
        TestQuery("NEP1",
                  "SELECT * FROM part WHERE p_size <> 20;",
                  False, False, False, True, False),
        TestQuery("NEP2",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25;",
                  False, False, False, True, False),
        TestQuery("NEP3",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53';",
                  False, False, False, True, False),
        TestQuery("NEP4",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3';",
                  False, False, False, True, False),
        TestQuery("NEP5",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS';",
                  False, False, False, True, False),
        TestQuery("NEP6",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR';",
                  False, False, False, True, False),
        TestQuery("NEP7",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace';",
                  False, False, False, True, False),
        TestQuery("NEP8",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo';",
                  False, False, False, True, False),
        TestQuery("NEP9",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo' AND p_partkey <> 500;",
                  False, False, False, True, False),
        TestQuery("NEP10",
                  "SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo' AND p_partkey <> 500 AND p_retailprice <> 1650.75;",
                  False, False, False, True, False)]
    workload += [TestQuery(f"OJ{k}", oj_chain(k), False, True, True, True, True) for k in range(1, 8)]
    workload += [TestQuery(f"DS{k}", disj_str_query(k), False, False, False, False, True)
                  for k in range(1, 11)]
    workload += [TestQuery(f"UK{k}", fixed_aux_query(k), False, True, False, False) for k in FA_SPLITS]
    workload += [TestQuery(f"UN{m}", union_query(m), False, True, False, False) for m in UNION_SIZES]
    # flags: cs2, union, oj, nep, orf
    workload += [TestQuery(f"T3B{m}", tpcds_union_query(TPCDS_3B, s), False, True, False, False)
                 for m, s in TPCDS_3B_SIZES.items()]
    workload += [TestQuery(f"T6B{m}", tpcds_union_query(TPCDS_6B, s), False, True, False, False)
                 for m, s in TPCDS_6B_SIZES.items()]
    workload += [TestQuery(f"IJ{k}", ij_chain(k), False, False, False, False, False)
                 for k in range(1, 8)]
    # Disjunction stress-test workload (20 queries)
    # flags: TestQuery(name, hidden_query, cs2, union, oj, nep, orf=None)
    workload += [
        # --- 10 pure disjunction (orf=True) ---
        TestQuery("DISJ1",
                  "SELECT p_partkey, p_name, p_size FROM part "
                  "WHERE p_size IN (3, 7, 15);",
                  False, False, False, False, True),
        TestQuery("DISJ2",
                  "SELECT s_suppkey, s_name, s_nationkey FROM supplier "
                  "WHERE s_nationkey IN (1, 5, 10);",
                  False, False, False, False, True),
        TestQuery("DISJ3",
                  "SELECT c_custkey, c_name, c_mktsegment FROM customer "
                  "WHERE c_mktsegment = 'BUILDING' OR c_mktsegment = 'AUTOMOBILE';",
                  False, False, False, False, True),
        TestQuery("DISJ4",
                  "SELECT p_partkey, p_name, p_retailprice FROM part "
                  "WHERE p_size = 10 OR p_retailprice > 1500.00;",
                  False, False, False, False, True),
        TestQuery("DISJ5",
                  "SELECT o_orderkey, o_totalprice, o_orderpriority FROM orders "
                  "WHERE o_orderstatus = 'F' AND "
                  "(o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH');",
                  False, False, False, False, True),
        TestQuery("DISJ6",
                  "SELECT p_partkey, p_name, p_brand FROM part "
                  "WHERE p_brand = 'Brand#12' OR p_brand = 'Brand#23' OR p_brand = 'Brand#34';",
                  False, False, False, False, True),
        TestQuery("DISJ7",
                  "SELECT c_name, o_orderkey, o_totalprice FROM customer, orders "
                  "WHERE c_custkey = o_custkey AND "
                  "(c_mktsegment = 'BUILDING' OR c_mktsegment = 'MACHINERY');",
                  False, False, False, False, True),
        TestQuery("DISJ8",
                  "SELECT n_name, s_name, s_acctbal FROM nation, supplier "
                  "WHERE n_nationkey = s_nationkey AND "
                  "(n_name = 'FRANCE' OR n_name = 'GERMANY');",
                  False, False, False, False, True),
        TestQuery("DISJ9",
                  "SELECT l_orderkey, l_linenumber, l_quantity FROM lineitem "
                  "WHERE l_quantity = 10 OR l_quantity = 20 OR l_quantity = 30;",
                  False, False, False, False, True),
        TestQuery("DISJ10",
                  "SELECT p_name, ps_supplycost, p_container FROM part, partsupp "
                  "WHERE p_partkey = ps_partkey AND p_size > 10 AND "
                  "(p_container = 'SM CASE' OR p_container = 'LG BOX' OR p_container = 'MED PACK');",
                  False, False, False, False, True),

        # --- 3 disjunction with NEP (nep=True, orf=True) ---
        TestQuery("DISJ_NEP1",
                  "SELECT p_partkey, p_name, p_size FROM part "
                  "WHERE p_brand <> 'Brand#13' AND (p_size = 10 OR p_size = 20);",
                  False, False, False, True, True),
        TestQuery("DISJ_NEP2",
                  "SELECT s_suppkey, s_name, s_acctbal FROM supplier "
                  "WHERE s_acctbal > 5000 AND s_nationkey <> 22 AND "
                  "(s_nationkey = 1 OR s_nationkey = 2 OR s_nationkey = 3);",
                  False, False, False, True, True),
        TestQuery("DISJ_NEP3",
                  "SELECT c_custkey, c_name, o_orderpriority FROM customer, orders "
                  "WHERE c_custkey = o_custkey AND c_mktsegment <> 'AUTOMOBILE' AND "
                  "(o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH');",
                  False, False, False, True, True),

        # --- 3 disjunction with outer join (oj=True, orf=True) ---
        TestQuery("DISJ_OJ1",
                  "SELECT c_custkey, c_name, o_orderkey FROM customer "
                  "LEFT OUTER JOIN orders ON c_custkey = o_custkey "
                  "WHERE c_mktsegment = 'BUILDING' OR c_mktsegment = 'FURNITURE';",
                  False, False, True, False, True),
        TestQuery("DISJ_OJ2",
                  "SELECT n_name, s_name, s_acctbal FROM nation "
                  "LEFT OUTER JOIN supplier ON n_nationkey = s_nationkey "
                  "WHERE n_name = 'FRANCE' OR n_name = 'GERMANY';",
                  False, False, True, False, True),
        TestQuery("DISJ_OJ3",
                  "SELECT c_name, o_orderkey, o_totalprice FROM customer "
                  "LEFT OUTER JOIN orders ON c_custkey = o_custkey "
                  "WHERE c_nationkey = 1 OR c_nationkey = 2;",
                  False, False, True, False, True),

        # --- 4 disjunction with union (union=True, orf=True) ---
        TestQuery("DISJ_UN1",
                  "(SELECT p_partkey, p_name FROM part "
                  "WHERE p_size = 10 OR p_size = 20) "
                  "UNION ALL "
                  "(SELECT s_suppkey, s_name FROM supplier "
                  "WHERE s_nationkey = 1 OR s_nationkey = 2);",
                  False, True, False, False, True),
        TestQuery("DISJ_UN2",
                  "(SELECT c_custkey, c_name FROM customer "
                  "WHERE c_mktsegment IN ('BUILDING', 'MACHINERY')) "
                  "UNION ALL "
                  "(SELECT s_suppkey, s_name FROM supplier "
                  "WHERE s_acctbal > 5000 AND s_nationkey IN (3, 4));",
                  False, True, False, False, True),
        TestQuery("DISJ_UN3",
                  "(SELECT c_name, o_orderkey FROM customer, orders "
                  "WHERE c_custkey = o_custkey AND "
                  "(o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH')) "
                  "UNION ALL "
                  "(SELECT n_name, s_suppkey FROM nation, supplier "
                  "WHERE n_nationkey = s_nationkey AND "
                  "(n_name = 'FRANCE' OR n_name = 'GERMANY'));",
                  False, True, False, False, True),
        TestQuery("DISJ_UN4",
                  "(SELECT p_partkey, p_name FROM part "
                  "WHERE p_brand = 'Brand#12' OR p_brand = 'Brand#23' OR p_container = 'SM BOX') "
                  "UNION ALL "
                  "(SELECT ps_partkey, ps_comment FROM partsupp "
                  "WHERE ps_availqty > 100 AND "
                  "(ps_supplycost < 100.00 OR ps_supplycost > 900.00));",
                  False, True, False, False, True),
    ]

    workload += [TestQuery("demo", """
    (
    SELECT
        c_name AS entity_name,
        n_name AS country,
        o_totalprice AS price
    FROM customer
    RIGHT OUTER JOIN orders
        ON c_custkey = o_custkey
        AND c_acctbal >= o_totalprice
        AND c_acctbal >= 9000
    LEFT OUTER JOIN nation
        ON c_nationkey = n_nationkey
    WHERE o_totalprice <= 15000
    GROUP BY n_name, c_name, o_totalprice
    ORDER BY price, country, entity_name
    LIMIT 10
)

UNION ALL

(
    SELECT
        s_name AS entity_name,
        n_name AS country,
        AVG(l_extendedprice * (1 - l_discount)) AS price
    FROM supplier, lineitem, orders, nation, region
    WHERE l_suppkey = s_suppkey
      AND l_orderkey = o_orderkey
      AND s_nationkey = n_nationkey
      AND n_regionkey = r_regionkey
      AND (l_shipmode = 'AIR' OR l_shipmode = 'TRUCK')
      AND r_name <> 'EUROPE'
      AND o_totalprice >= s_acctbal
      AND o_totalprice <= 15000
    GROUP BY n_name, s_name
    ORDER BY price DESC, country DESC, entity_name
    LIMIT 20
);""", False, True, True, True, True)]
    return workload

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Extract a hidden query from PRISM's workload.")
    parser.add_argument('qid', help="query id to run")
    parser.add_argument('--print', action='store_true', help="print the query text and exit")
    args = parser.parse_args()

    qid = args.qid
    if args.print:
        TestQuery.print(qid)
        sys.exit(0)

    workload = build_workload()

    workload_dict = {elem.qid: i for i, elem in enumerate(workload)}

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    if qid not in workload_dict:
        print(f"Unknown query id: {qid}")
        sys.exit(2)
    hq = workload[workload_dict[qid]]
    query = hq.query
    print(query)

    conn = ConnectionHelperFactory().createConnectionHelper()
    conn.config.detect_union = hq.union
    conn.config.detect_oj = hq.oj
    conn.config.detect_nep = hq.nep
    conn.config.use_cs2 = hq.cs2
    conn.config.detect_or = hq.orf

    print(f"Flags: Scale Down {conn.config.scale_down}, Union {conn.config.detect_union}, "
          f"OJ {conn.config.detect_oj}, NEP {conn.config.detect_nep}, CS2 {conn.config.use_cs2}")

    try:
        factory = PipeLineFactory()
        token = factory.init_job(conn, query)
        factory.doJob(query, token)
        result = factory.result

        if result is not None:
            print("============= Given Query ===============")
            print(query)
            print("=========== Extracted Query =============")
            print(result)
            print("================ Profile ================")
            pipe = factory.get_pipeline_obj(token)
            pipe.time_profile.print()
        else:
            print(f"{qid}: I had some Trouble! Check the log file for the details..")
            sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)