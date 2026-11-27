-- PRISM SQL workload
-- Every query defined in mysite/unmasque/src/main_cmd.py (build_workload()).
-- Each query is labelled with the qid used by: python -m unmasque.src.main_cmd <qid>

-- Query: U1
(SELECT p_partkey, p_name FROM part, partsupp where p_partkey = ps_partkey and ps_availqty > 100
Order By p_partkey Limit 5)
UNION ALL (SELECT s_suppkey, s_name FROM supplier, partsupp where s_suppkey = ps_suppkey and
ps_availqty > 200 Order By s_suppkey Limit 7);

-- Query: U2
(SELECT s_suppkey, s_name FROM supplier, nation where s_nationkey = n_nationkey and  n_name = 'GERMANY' order by s_suppkey desc, s_name limit 12)UNION ALL (SELECT c_custkey, c_name FROM customer,  orders where c_custkey = o_custkey and o_orderpriority = '1-URGENT' order by c_custkey, c_name desc limit 10);

-- Query: U3
(SELECT c_custkey as key, c_name as name FROM customer, nation where c_nationkey = n_nationkey and  n_name = 'UNITED STATES' Order by key Limit 10)
 UNION ALL (SELECT p_partkey as key, p_name as name FROM part , lineitem where p_partkey = l_partkey and l_quantity > 35 Order By key Limit 10) 
 UNION ALL (select n_nationkey as key, r_name as name from nation, region where n_name LIKE 'B%' Order By key Limit 5);

-- Query: U4
(SELECT c_custkey, c_name FROM customer,  nation where c_nationkey = n_nationkey and n_name = 'UNITED STATES' Order By c_custkey desc Limit 5) 
 UNION ALL (SELECT s_suppkey, s_name FROM supplier ,  nation where s_nationkey = n_nationkey and n_name = 'CANADA' Order By s_suppkey Limit 6) 
 UNION ALL (SELECT p_partkey, p_name FROM part ,  lineitem where p_partkey = l_partkey and l_quantity > 20 Order By p_partkey desc Limit 7) 
 UNION ALL (SELECT ps_partkey, p_name FROM part ,  partsupp where p_partkey = ps_partkey and ps_supplycost >= 1000 Order By ps_partkey Limit 8);

-- Query: U5
(SELECT o_orderkey, o_orderdate, n_name FROM orders, customer, nation where o_custkey = c_custkey and c_nationkey = n_nationkey and c_name like '%0001248%'  AND o_orderdate >= '1997-01-01' order by o_orderkey Limit 20) 
 UNION ALL (SELECT l_orderkey, l_shipdate, o_orderstatus FROM lineitem, orders where l_orderkey = o_orderkey and o_orderdate < '1994-01-01'   AND l_quantity > 20   AND l_extendedprice > 1000 order by l_orderkey Limit 5);

-- Query: U6
(SELECT o_clerk as name, SUM(l_extendedprice) AS total_price FROM orders, lineitem where o_orderkey = l_orderkey and o_orderdate <= '1995-01-01' GROUP BY o_clerk ORDER BY total_price DESC LIMIT 10) 
 UNION ALL (SELECT n_name as name, SUM(s_acctbal) AS total_price FROM nation ,supplier where n_nationkey = s_nationkey and n_name like '%UNITED%' GROUP BY n_name ORDER BY n_name DESC Limit 10);

-- Query: U7
(SELECT     l_orderkey as key,     l_extendedprice as price,     l_partkey as s_key FROM     lineitem WHERE     l_shipdate >= DATE '1994-01-01'     AND l_shipdate < DATE '1995-01-01'     AND l_quantity > 30  Order By key Limit 20)
 UNION ALL  (SELECT     ps_partkey as key,     p_retailprice as price,     ps_suppkey as s_key FROM     partsupp,supplier,part where ps_suppkey = s_suppkey and ps_partkey = p_partkey     AND ps_supplycost < 100 Order By price Limit 20);

-- Query: U8
(SELECT c_custkey AS order_id, COUNT(*) AS total
 FROM customer, orders
 WHERE c_custkey = o_custkey
   AND o_orderdate >= '1995-01-01'
 GROUP BY c_custkey
 ORDER BY total ASC)
UNION ALL
(SELECT l_orderkey AS order_id, AVG(l_quantity) AS total
 FROM orders, lineitem
 WHERE l_orderkey = o_orderkey
   AND o_orderdate < DATE '1996-07-01'
 GROUP BY l_orderkey
 ORDER BY total DESC LIMIT 10);

-- Query: U9
(select c_name, n_name from customer, nation where
c_mktsegment='BUILDING' and c_acctbal > 100 and c_nationkey
= n_nationkey) UNION ALL (select s_name, n_name from supplier,
nation where s_acctbal > 4000 and s_nationkey = n_nationkey);

-- Query: O1
select c_name, n_name, count(*) as total from nation RIGHT OUTER
JOIN customer ON c_nationkey = n_nationkey and c_acctbal < 1000
        GROUP BY c_name,
n_name Order by c_name, n_name desc Limit 10;

-- Query: O2
SELECT l_shipmode, o_shippriority ,count(*) as low_line_count FROM
lineitem LEFT OUTER JOIN orders ON ( l_orderkey = o_orderkey AND
o_totalprice > 50000 ) WHERE l_linenumber = 4 AND l_quantity < 30
GROUP BY l_shipmode, o_shippriority Order By l_shipmode Limit 5;

-- Query: O3
SELECT o_custkey as key, sum(c_acctbal), o_clerk, c_name from orders FULL OUTER JOIN customer on c_custkey = o_custkey and
o_orderstatus = 'F' group by o_custkey, o_clerk, c_name order by key
limit 35;

-- Query: O4
SELECT p_size, s_phone, ps_supplycost, n_name FROM part RIGHT
OUTER JOIN partsupp ON p_partkey = ps_partkey AND p_size >
7 LEFT OUTER JOIN supplier ON ps_suppkey = s_suppkey AND
s_acctbal < 2000 FULL OUTER JOIN nation on s_nationkey =
n_nationkey and n_regionkey > 3 Order by ps_supplycost asc Limit 50;

-- Query: O5
Select ps_suppkey, p_name, p_type from part RIGHT outer join partsupp on p_partkey=ps_partkey and p_size > 4 and ps_availqty > 3350 Order By ps_suppkey Limit 100;

-- Query: O6
SELECT p_name, s_phone, ps_supplycost, n_name FROM part RIGHT OUTER JOIN partsupp ON p_partkey = ps_partkey AND p_size > 7
	LEFT OUTER JOIN supplier ON ps_suppkey = s_suppkey AND s_acctbal < 2000 FULL OUTER JOIN nation on s_nationkey = n_nationkey
	and n_regionkey > 3 Order By p_name, s_phone, ps_supplycost, n_name desc Limit 20;

-- Query: A1
Select l_shipmode, count(*) as count From orders, lineitem Where
o_orderkey = l_orderkey and l_commitdate < l_receiptdate and
l_shipdate < l_commitdate and l_receiptdate >= '1994-01-01' and
l_receiptdate < '1995-01-01' and l_extendedprice <= o_totalprice
and l_extendedprice <= 70000 and o_totalprice > 60000 Group By
l_shipmode Order By l_shipmode;

-- Query: A2
Select o_orderpriority, count(*) as order_count From orders, lineitem
Where l_orderkey = o_orderkey and o_orderdate >= '1993-07-01' and
o_orderdate < '1993-10-01' and l_commitdate <= l_receiptdate Group
By o_orderpriority Order By o_orderpriority;

-- Query: A3
Select l_orderkey, l_linenumber From orders, lineitem, partsupp Where
o_orderkey = l_orderkey and ps_partkey = l_partkey and ps_suppkey
= l_suppkey and ps_availqty = l_linenumber and l_shipdate >=
o_orderdate and o_orderdate >= '1990-01-01' and l_commitdate <=
l_receiptdate and l_shipdate <= l_commitdate and l_receiptdate > '1994-01-01' Order By l_orderkey Limit 7;

-- Query: A4
Select s_name, count(*) as numwait From supplier, lineitem, orders,
nation Where s_suppkey = l_suppkey and o_orderkey = l_orderkey and
o_orderstatus = 'F' and l_receiptdate >= l_commitdate and s_nationkey
= n_nationkey Group By s_name Order By numwait desc Limit 100;

-- Query: A5
Select l_returnflag, l_linestatus, sum(l_quantity) as sum_qty,
sum(l_extendedprice) as sum_base_price, sum(l_extendedprice
* (1 - l_discount)) as sum_disc_price, sum(l_extendedprice * (1 -
l_discount) * (1 + l_tax)) as sum_charge, avg(l_quantity) as avg_qty,
avg(l_extendedprice) as avg_price, avg(l_discount) as avg_disc, count(*)
as count_order From lineitem Where l_shipdate <= l_receiptdate and
l_receiptdate <= l_commitdate Group By l_returnflag, l_linestatus
Order by l_returnflag, l_linestatus;

-- Query: N1
Select p_brand, p_type, p_size, Count(*) as supplier_cnt
 From part, partsupp
 Where p_partkey = ps_partkey
 and p_size >= 4 and p_type NOT LIKE 'SMALL PLATED%'  and p_brand <> 'Brand#45'
 Group By p_brand, p_size, p_type
 Order By supplier_cnt desc, p_brand asc, p_type asc, p_size asc;

-- Query: F1
(SELECT c_name as name, c_acctbal as account_balance FROM orders,
customer, nation WHERE c_custkey = o_custkey and c_nationkey
= n_nationkey and c_mktsegment = 'FURNITURE' and n_name =
'INDIA' and o_orderdate between '1998-01-01' and '1998-12-05' and
o_totalprice <= c_acctbal) UNION ALL (SELECT s_name as name,
s_acctbal as account_balance FROM supplier, lineitem, orders, nation
WHERE l_suppkey = s_suppkey and l_orderkey = o_orderkey
and s_nationkey = n_nationkey and n_name = 'ARGENTINA' and
o_orderdate between '1998-01-01' and '1998-01-05' and o_totalprice >
s_acctbal and o_totalprice >= 30000 and 50000 >= s_acctbal Order by account_balance desc limit 20);

-- Query: F2
(Select p_brand, o_clerk, l_shipmode From orders, lineitem, part Where
l_partkey = p_partkey and o_orderkey = l_orderkey and l_shipdate >=
o_orderdate and o_orderdate > '1994-01-01' and l_shipdate > '1995-01-01' and p_retailprice >= l_extendedprice and p_partkey < 10000 and
l_suppkey < 10000 and p_container = 'LG CAN' Order By o_clerk LIMIT
5) UNION ALL (Select p_brand, s_name, l_shipmode From lineitem,
part, supplier Where l_partkey = p_partkey and l_suppkey = s_suppkey
and l_shipdate > '1995-01-01' and s_acctbal >= l_extendedprice and
p_partkey < 15000 and l_suppkey < 14000 and p_container = 'LG CAN'
Order By s_name LIMIT 10);

-- Query: F3
(
	select l_orderkey, l_extendedprice as price, p_partkey from lineitem, part
	where l_partkey = p_partkey  and p_container LIKE 'JUMBO%' and p_partkey > 3000 and l_partkey < 3010
	Order by l_orderkey, price desc Limit 100
) union all (select o_orderkey, c_acctbal as price, c_custkey
from customer LEFT OUTER JOIN orders on c_custkey = o_custkey
 where c_acctbal > 9000 and c_acctbal < 9100 Order By price desc, o_orderkey, c_custkey Limit 100);

-- Query: F4
select n_name, c_acctbal from nation LEFT OUTER JOIN customer 
                     ON n_nationkey = c_nationkey and c_nationkey > 3 and n_nationkey < 20 and 
                     c_nationkey != 10 LIMIT 200;

-- Query: MQ1
SELECT l_returnflag, l_linestatus, 
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
ORDER BY l_returnflag, l_linestatus;

-- Query: MQ2
SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
FROM part, supplier, partsupp, nation, region
WHERE p_partkey = ps_partkey 
  AND s_suppkey = ps_suppkey 
  AND p_size = 38 
  AND p_type LIKE '%TIN' 
  AND s_nationkey = n_nationkey 
  AND n_regionkey = r_regionkey 
  AND r_name = 'MIDDLE EAST'
ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
LIMIT 100;

-- Query: MQ3
SELECT l_orderkey, 
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
LIMIT 10;

-- Query: MQ5
SELECT n_name, 
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
LIMIT 100;

-- Query: MQ6
SELECT l_shipmode, 
       SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= DATE '1994-01-01' 
  AND l_shipdate < DATE '1994-01-01' + INTERVAL '1 year' 
  AND l_quantity < 24
GROUP BY l_shipmode
LIMIT 100;

-- Query: MQ10
SELECT c_name, 
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
LIMIT 20;

-- Query: MQ11
SELECT ps_comment, 
       SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey 
  AND s_nationkey = n_nationkey 
  AND n_name = 'ARGENTINA'
GROUP BY ps_comment
ORDER BY value DESC
LIMIT 100;

-- Query: MQ17
SELECT AVG(l_extendedprice) AS avg_total
FROM lineitem, part
WHERE p_partkey = l_partkey 
  AND p_brand = 'Brand#52' 
  AND p_container = 'LG CAN';

-- Query: MQ18
SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%' 
  AND c_custkey = o_custkey 
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;

-- Query: MQ21
SELECT s_name, COUNT(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE s_suppkey = l1.l_suppkey 
  AND o_orderkey = l1.l_orderkey 
  AND o_orderstatus = 'F' 
  AND s_nationkey = n_nationkey 
  AND n_name = 'GERMANY'
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100;

-- Query: Alaap
select c_mktsegment, 
                         sum(l_extendedprice*(1-l_discount) + l_quantity) as revenue,
                         o_orderdate, o_shippriority 
                         from customer, orders, lineitem 
                         where c_custkey = o_custkey and l_orderkey = o_orderkey and 
                         o_orderdate <= date '1995-10-13' and l_extendedprice between 212 and 3000 
                        and l_quantity <= 123  group by o_orderdate, o_shippriority, c_mktsegment 
                         order by revenue desc, o_orderdate asc, o_shippriority asc;

-- Query: oj_bug
SELECT c_custkey, c_name, c_mktsegment, o_orderkey
FROM customer FULL OUTER JOIN orders ON c_custkey = o_custkey
WHERE c_mktsegment = 'BUILDING';

-- Query: QN1
SELECT c_name, c_acctbal FROM customer WHERE c_mktsegment <> 'BUILDING' AND c_acctbal > 9000;

-- Query: QN2
SELECT o_orderkey, o_totalprice FROM orders WHERE o_orderstatus <> 'F' AND o_orderpriority <> '1-URGENT';

-- Query: QD2
SELECT c_name, c_acctbal FROM customer WHERE c_mktsegment IN ('BUILDING', 'MACHINERY', 'AUTOMOBILE') AND c_acctbal > 5000;

-- Query: nep
SELECT l_shipmode, SUM(l_extendedprice) AS revenue FROM lineitem WHERE l_shipdate < '1994-01-01' AND l_quantity < 24 AND l_linenumber <> 4 AND l_returnflag <> 'R' GROUP BY l_shipmode LIMIT 100;

-- Query: A7
SELECT
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
ORDER BY total_price DESC, o_clerk, c_acctbal, n_name;

-- Query: A8
SELECT
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
ORDER BY o_clerk;

-- Query: F17
SELECT
    o_clerk,
    SUM(c_acctbal + 3.54 * o_totalprice) AS total_price,
    n_name
FROM orders, customer, nation
WHERE
    c_custkey = o_custkey
    AND c_custkey > 5000
    AND c_nationkey = n_nationkey
    AND n_nationkey IN (1, 10)
    AND c_acctbal < 7000
    AND o_totalprice > 1000
    AND c_acctbal <= o_totalprice
GROUP BY o_clerk, n_name
ORDER BY o_clerk
LIMIT 30;

-- Query: A10
SELECT
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
ORDER BY l_shipmode;

-- Query: A11
SELECT
    c_name AS name,
    c_acctbal AS account_balance
FROM orders, customer, nation
WHERE
    o_custkey > 1000
    AND c_custkey = o_custkey
    AND c_custkey <= 5527
    AND c_nationkey = n_nationkey
    AND o_orderdate BETWEEN '1998-01-01' AND '1998-01-15'
    AND o_totalprice <= c_acctbal;

-- Query: F5
(SELECT
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
   AND ps_availqty >= 201);

-- Query: A12
SELECT
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
ORDER BY l_shipmode ASC;

-- Query: A13
SELECT
    o_orderpriority,
    COUNT(*) AS order_count
FROM lineitem, orders
WHERE
    l_orderkey = o_orderkey
    AND l_commitdate <= l_receiptdate
    AND '1993-07-01' <= o_orderdate
    AND o_orderdate <= '1993-09-30'
GROUP BY o_orderpriority
ORDER BY o_orderpriority ASC;

-- Query: F6
(SELECT
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
 LIMIT 5);

-- Query: A14
SELECT
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
LIMIT 7;

-- Query: A15
SELECT
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
LIMIT 100;

-- Query: A16
SELECT
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
ORDER BY l_returnflag ASC, l_linestatus ASC;

-- Query: U10
(SELECT
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
    AND o_orderpriority = '1-URGENT');

-- Query: U11
(SELECT
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
    AND l_quantity > 35);

-- Query: U12
(SELECT
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
    AND l_quantity > 20);

-- Query: U13
(SELECT
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
    AND o_orderdate >= '1997-01-01');

-- Query: U14
(SELECT
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
 LIMIT 10);

-- Query: U15
(SELECT
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
    AND ps_supplycost < 100);

-- Query: U16
(SELECT
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
 LIMIT 10);

-- Query: F7
(SELECT
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
    AND o_totalprice <= c_acctbal);

-- Query: O7
SELECT
    n_name,
    r_comment
FROM nation
FULL OUTER JOIN region
    ON n_regionkey = r_regionkey
   AND r_name = 'AFRICA';

-- Query: O8
SELECT
    n_name,
    c_comment
FROM nation
RIGHT OUTER JOIN customer
    ON c_nationkey = n_nationkey
   AND c_acctbal < 1000;

-- Query: F8
SELECT
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
   AND c_acctbal < 1000;

-- Query: F9
SELECT
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
   AND o_orderstatus = 'F';

-- Query: O9
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
   AND o_orderstatus = 'F';

-- Query: N2
SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_shipdate >= '1994-01-01'
  AND l_quantity < 24
  AND l_returnflag <> 'R'
GROUP BY l_shipmode
LIMIT 100;

-- Query: N3
SELECT l_shipmode, COUNT(*) AS count
FROM lineitem
WHERE l_quantity > 20
  AND l_quantity <> 25
GROUP BY l_shipmode
ORDER BY l_shipmode;

-- Query: N4
SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_shipdate < '1994-01-01'
  AND l_quantity < 24
  AND l_linenumber <> 4
  AND l_returnflag <> 'R'
GROUP BY l_shipmode
LIMIT 100;

-- Query: N5
SELECT l_shipmode, SUM(l_extendedprice) AS revenue
FROM lineitem
WHERE l_quantity < 24
  AND l_shipdate <> '1994-01-02'
  AND l_shipmode NOT LIKE '%AIR%'
GROUP BY l_shipmode
LIMIT 100;

-- Query: N6
SELECT s_name, COUNT(*) AS numwait
FROM supplier, lineitem, orders, nation
WHERE s_suppkey = l_suppkey
  AND o_orderkey = l_orderkey
  AND o_orderstatus = 'F'
  AND s_nationkey = n_nationkey
  AND n_name <> 'GERMANY'
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100;

-- Query: N7
SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-_%'
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
  AND c_name <> 'Customer#000060217'
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;

-- Query: N8
SELECT ps_comment, SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = 'ARGENTINA'
  AND ps_comment NOT LIKE '%regular%dependencies%'
  AND s_acctbal <> 2177.90
GROUP BY ps_comment
ORDER BY value DESC
LIMIT 100;

-- Query: N9
SELECT *
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = 'ARGENTINA'
  AND ps_comment <> 'dependencies'
  AND ps_comment <> 'hello world regular mina dependencies';

-- Query: F11
select n_name, c_acctbal from nation, customer where n_nationkey = c_nationkey and c_nationkey > 3 and 
  n_nationkey < 20 and c_nationkey != 10 and c_acctbal < 7000 LIMIT 200;

-- Query: F13
select avg(ps_supplycost) as cost from part, partsupp where p_partkey = ps_partkey 
  and (p_brand = 'Brand#52' or p_brand = 'Brand#12');

-- Query: F14
select p_size, ps_suppkey, count(*) as low_line_count from part, partsupp where 
  p_partkey = ps_partkey and p_brand IN ('Brand#52', 'Brand#34', 'Brand#15') and p_container IN ('WRAP BOX', 'MED BOX') 
  GROUP BY p_size, ps_suppkey  ORDER BY ps_suppkey desc LIMIT 30;

-- Query: F15
select n_name, s_acctbal, ps_availqty  from supplier, partsupp, nation where 
  ps_suppkey=s_suppkey AND ps_supplycost < 50 and s_nationkey=n_nationkey and (n_regionkey = 1 or n_regionkey =3) ORDER BY n_name;

-- Query: NEP1
SELECT * FROM part WHERE p_size <> 20;

-- Query: NEP2
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25;

-- Query: NEP3
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53';

-- Query: NEP4
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3';

-- Query: NEP5
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS';

-- Query: NEP6
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR';

-- Query: NEP7
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace';

-- Query: NEP8
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo';

-- Query: NEP9
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo' AND p_partkey <> 500;

-- Query: NEP10
SELECT * FROM part WHERE p_size <> 20 AND p_retailprice <> 1150.25 AND p_brand <> 'Brand#53' AND p_mfgr <> 'Manufacturer#3' AND p_type <> 'PROMO BRUSHED BRASS' AND p_container <> 'LG JAR' AND p_name <> 'goldenrod lavender spring chocolate lace' AND p_comment <> 'lar accounts amo' AND p_partkey <> 500 AND p_retailprice <> 1650.75;

-- Query: OJ1
SELECT r_name, n_name FROM region LEFT OUTER JOIN nation ON r_regionkey = n_regionkey;

-- Query: OJ2
SELECT r_name, n_name, s_name FROM region LEFT OUTER JOIN nation ON r_regionkey = n_regionkey LEFT OUTER JOIN supplier ON n_nationkey = s_nationkey;

-- Query: OJ3
SELECT r_name, n_name, s_name, ps_availqty FROM region LEFT OUTER JOIN nation ON r_regionkey = n_regionkey LEFT OUTER JOIN supplier ON n_nationkey = s_nationkey LEFT OUTER JOIN partsupp ON s_suppkey = ps_suppkey;

-- Query: OJ4
SELECT r_name, n_name, s_name, ps_availqty, p_name FROM region LEFT OUTER JOIN nation ON r_regionkey = n_regionkey LEFT OUTER JOIN supplier ON n_nationkey = s_nationkey LEFT OUTER JOIN partsupp ON s_suppkey = ps_suppkey LEFT OUTER JOIN part ON ps_partkey = p_partkey;

-- Query: DS1
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE');

-- Query: DS2
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX');

-- Query: DS3
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK');

-- Query: DS4
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG');

-- Query: DS5
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG');

-- Query: DS6
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG', 'MED BOX');

-- Query: DS7
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG', 'MED BOX', 'MED PKG');

-- Query: DS8
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG', 'MED BOX', 'MED PKG', 'MED PACK');

-- Query: DS9
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG', 'MED BOX', 'MED PKG', 'MED PACK', 'LG CASE');

-- Query: DS10
SELECT p_partkey, p_name, p_comment FROM part WHERE p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG', 'MED BAG', 'MED BOX', 'MED PKG', 'MED PACK', 'LG CASE', 'LG BOX');

-- Query: UK2
(SELECT r_name, r_regionkey FROM region, nation, supplier, partsupp WHERE r_regionkey = n_regionkey AND n_nationkey = s_nationkey AND s_suppkey = ps_suppkey) UNION ALL (SELECT p_name, p_retailprice FROM part, lineitem, orders, customer WHERE p_partkey = l_partkey AND l_orderkey = o_orderkey AND o_custkey = c_custkey);

-- Query: UK4
(SELECT r_name, r_regionkey FROM region, nation WHERE r_regionkey = n_regionkey) UNION ALL (SELECT s_name, s_acctbal FROM supplier, partsupp WHERE s_suppkey = ps_suppkey) UNION ALL (SELECT p_name, p_retailprice FROM part, lineitem WHERE p_partkey = l_partkey) UNION ALL (SELECT o_clerk, o_totalprice FROM orders, customer WHERE o_custkey = c_custkey);

-- Query: UK5
(SELECT r_name, r_regionkey FROM region, nation WHERE r_regionkey = n_regionkey) UNION ALL (SELECT s_name, s_acctbal FROM supplier, partsupp WHERE s_suppkey = ps_suppkey) UNION ALL (SELECT p_name, p_retailprice FROM part, lineitem WHERE p_partkey = l_partkey) UNION ALL (SELECT o_clerk, o_totalprice FROM orders) UNION ALL (SELECT c_name, c_acctbal FROM customer);

-- Query: UK6
(SELECT r_name, r_regionkey FROM region, nation WHERE r_regionkey = n_regionkey) UNION ALL (SELECT s_name, s_acctbal FROM supplier, partsupp WHERE s_suppkey = ps_suppkey) UNION ALL (SELECT p_name, p_retailprice FROM part) UNION ALL (SELECT l_comment, l_extendedprice FROM lineitem) UNION ALL (SELECT o_clerk, o_totalprice FROM orders) UNION ALL (SELECT c_name, c_acctbal FROM customer);

-- Query: UK7
(SELECT r_name, r_regionkey FROM region, nation WHERE r_regionkey = n_regionkey) UNION ALL (SELECT s_name, s_acctbal FROM supplier) UNION ALL (SELECT ps_comment, ps_supplycost FROM partsupp) UNION ALL (SELECT p_name, p_retailprice FROM part) UNION ALL (SELECT l_comment, l_extendedprice FROM lineitem) UNION ALL (SELECT o_clerk, o_totalprice FROM orders) UNION ALL (SELECT c_name, c_acctbal FROM customer);

-- Query: UK8
(SELECT r_name, r_regionkey FROM region) UNION ALL (SELECT n_name, n_nationkey FROM nation) UNION ALL (SELECT s_name, s_acctbal FROM supplier) UNION ALL (SELECT ps_comment, ps_supplycost FROM partsupp) UNION ALL (SELECT p_name, p_retailprice FROM part) UNION ALL (SELECT l_comment, l_extendedprice FROM lineitem) UNION ALL (SELECT o_clerk, o_totalprice FROM orders) UNION ALL (SELECT c_name, c_acctbal FROM customer);

-- Query: UN3
(SELECT s_name, s_acctbal FROM supplier) UNION ALL (SELECT c_name, c_acctbal FROM customer) UNION ALL (SELECT p_name, p_retailprice FROM part);

-- Query: UN4
(SELECT s_name, s_acctbal FROM supplier, nation WHERE s_nationkey = n_nationkey) UNION ALL (SELECT c_name, c_acctbal FROM customer) UNION ALL (SELECT p_name, p_retailprice FROM part);

-- Query: UN5
(SELECT s_name, s_acctbal FROM supplier, nation WHERE s_nationkey = n_nationkey) UNION ALL (SELECT c_name, c_acctbal FROM customer, orders WHERE c_custkey = o_custkey) UNION ALL (SELECT p_name, p_retailprice FROM part);

-- Query: UN6
(SELECT s_name, s_acctbal FROM supplier, nation WHERE s_nationkey = n_nationkey) UNION ALL (SELECT c_name, c_acctbal FROM customer, orders WHERE c_custkey = o_custkey) UNION ALL (SELECT p_name, p_retailprice FROM part, partsupp WHERE p_partkey = ps_partkey);

-- Query: UN7
(SELECT s_name, s_acctbal FROM supplier, nation, region WHERE s_nationkey = n_nationkey AND n_regionkey = r_regionkey) UNION ALL (SELECT c_name, c_acctbal FROM customer, orders WHERE c_custkey = o_custkey) UNION ALL (SELECT p_name, p_retailprice FROM part, partsupp WHERE p_partkey = ps_partkey);

-- Query: UN8
(SELECT s_name, s_acctbal FROM supplier, nation, region WHERE s_nationkey = n_nationkey AND n_regionkey = r_regionkey) UNION ALL (SELECT c_name, c_acctbal FROM customer, orders, lineitem WHERE c_custkey = o_custkey AND o_orderkey = l_orderkey) UNION ALL (SELECT p_name, p_retailprice FROM part, partsupp WHERE p_partkey = ps_partkey);

-- Query: IJ1
SELECT r_name, n_name FROM region INNER JOIN nation ON r_regionkey = n_regionkey;

-- Query: IJ2
SELECT r_name, n_name, s_name FROM region INNER JOIN nation ON r_regionkey = n_regionkey INNER JOIN supplier ON n_nationkey = s_nationkey;

-- Query: IJ3
SELECT r_name, n_name, s_name, ps_availqty FROM region INNER JOIN nation ON r_regionkey = n_regionkey INNER JOIN supplier ON n_nationkey = s_nationkey INNER JOIN partsupp ON s_suppkey = ps_suppkey;

-- Query: IJ4
SELECT r_name, n_name, s_name, ps_availqty, p_name FROM region INNER JOIN nation ON r_regionkey = n_regionkey INNER JOIN supplier ON n_nationkey = s_nationkey INNER JOIN partsupp ON s_suppkey = ps_suppkey INNER JOIN part ON ps_partkey = p_partkey;

-- Query: DISJ1
SELECT p_partkey, p_name, p_size FROM part WHERE p_size IN (3, 7, 15);

-- Query: DISJ2
SELECT s_suppkey, s_name, s_nationkey FROM supplier WHERE s_nationkey IN (1, 5, 10);

-- Query: DISJ3
SELECT c_custkey, c_name, c_mktsegment FROM customer WHERE c_mktsegment = 'BUILDING' OR c_mktsegment = 'AUTOMOBILE';

-- Query: DISJ4
SELECT p_partkey, p_name, p_retailprice FROM part WHERE p_size = 10 OR p_retailprice > 1500.00;

-- Query: DISJ5
SELECT o_orderkey, o_totalprice, o_orderpriority FROM orders WHERE o_orderstatus = 'F' AND (o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH');

-- Query: DISJ6
SELECT p_partkey, p_name, p_brand FROM part WHERE p_brand = 'Brand#12' OR p_brand = 'Brand#23' OR p_brand = 'Brand#34';

-- Query: DISJ7
SELECT c_name, o_orderkey, o_totalprice FROM customer, orders WHERE c_custkey = o_custkey AND (c_mktsegment = 'BUILDING' OR c_mktsegment = 'MACHINERY');

-- Query: DISJ8
SELECT n_name, s_name, s_acctbal FROM nation, supplier WHERE n_nationkey = s_nationkey AND (n_name = 'FRANCE' OR n_name = 'GERMANY');

-- Query: DISJ9
SELECT l_orderkey, l_linenumber, l_quantity FROM lineitem WHERE l_quantity = 10 OR l_quantity = 20 OR l_quantity = 30;

-- Query: DISJ10
SELECT p_name, ps_supplycost, p_container FROM part, partsupp WHERE p_partkey = ps_partkey AND p_size > 10 AND (p_container = 'SM CASE' OR p_container = 'LG BOX' OR p_container = 'MED PACK');

-- Query: DISJ_NEP1
SELECT p_partkey, p_name, p_size FROM part WHERE p_brand <> 'Brand#13' AND (p_size = 10 OR p_size = 20);

-- Query: DISJ_NEP2
SELECT s_suppkey, s_name, s_acctbal FROM supplier WHERE s_acctbal > 5000 AND s_nationkey <> 22 AND (s_nationkey = 1 OR s_nationkey = 2 OR s_nationkey = 3);

-- Query: DISJ_NEP3
SELECT c_custkey, c_name, o_orderpriority FROM customer, orders WHERE c_custkey = o_custkey AND c_mktsegment <> 'AUTOMOBILE' AND (o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH');

-- Query: DISJ_OJ1
SELECT c_custkey, c_name, o_orderkey FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey WHERE c_mktsegment = 'BUILDING' OR c_mktsegment = 'FURNITURE';

-- Query: DISJ_OJ2
SELECT n_name, s_name, s_acctbal FROM nation LEFT OUTER JOIN supplier ON n_nationkey = s_nationkey WHERE n_name = 'FRANCE' OR n_name = 'GERMANY';

-- Query: DISJ_OJ3
SELECT c_name, o_orderkey, o_totalprice FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey WHERE c_nationkey = 1 OR c_nationkey = 2;

-- Query: DISJ_UN1
(SELECT p_partkey, p_name FROM part WHERE p_size = 10 OR p_size = 20) UNION ALL (SELECT s_suppkey, s_name FROM supplier WHERE s_nationkey = 1 OR s_nationkey = 2);

-- Query: DISJ_UN2
(SELECT c_custkey, c_name FROM customer WHERE c_mktsegment IN ('BUILDING', 'MACHINERY')) UNION ALL (SELECT s_suppkey, s_name FROM supplier WHERE s_acctbal > 5000 AND s_nationkey IN (3, 4));

-- Query: DISJ_UN3
(SELECT c_name, o_orderkey FROM customer, orders WHERE c_custkey = o_custkey AND (o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH')) UNION ALL (SELECT n_name, s_suppkey FROM nation, supplier WHERE n_nationkey = s_nationkey AND (n_name = 'FRANCE' OR n_name = 'GERMANY'));

-- Query: DISJ_UN4
(SELECT p_partkey, p_name FROM part WHERE p_brand = 'Brand#12' OR p_brand = 'Brand#23' OR p_container = 'SM BOX') UNION ALL (SELECT ps_partkey, ps_comment FROM partsupp WHERE ps_availqty > 100 AND (ps_supplycost < 100.00 OR ps_supplycost > 900.00));

