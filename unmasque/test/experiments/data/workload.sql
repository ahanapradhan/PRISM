-- U1
(SELECT p_partkey, p_name FROM part, partsupp
 WHERE p_partkey = ps_partkey AND ps_availqty > 100
 ORDER BY p_partkey LIMIT 5)
UNION ALL
(SELECT s_suppkey, s_name FROM supplier, partsupp
 WHERE s_suppkey = ps_suppkey AND ps_availqty > 200
 ORDER BY s_suppkey LIMIT 7);

-- U2
(SELECT s_suppkey, s_name
 FROM supplier, nation
 WHERE s_nationkey = n_nationkey AND n_name = 'GERMANY'
 ORDER BY s_suppkey DESC, s_name LIMIT 12)
UNION ALL
(SELECT c_custkey, c_name
 FROM customer, orders
 WHERE c_custkey = o_custkey AND o_orderpriority = '1-URGENT'
 ORDER BY c_custkey, c_name DESC LIMIT 10);

-- U3
(SELECT c_custkey AS key, c_name AS name
 FROM customer, nation
 WHERE c_nationkey = n_nationkey AND n_name = 'UNITED STATES'
 ORDER BY key LIMIT 10)
UNION ALL
(SELECT p_partkey AS key, p_name AS name
 FROM part, lineitem
 WHERE p_partkey = l_partkey AND l_quantity > 35
 ORDER BY key LIMIT 10)
UNION ALL
(SELECT n_nationkey AS key, r_name AS name
 FROM nation, region
 WHERE n_name LIKE 'B%'
 ORDER BY key LIMIT 5);

-- U4
(SELECT c_custkey, c_name
 FROM customer, nation
 WHERE c_nationkey = n_nationkey AND n_name = 'UNITED STATES'
 ORDER BY c_custkey DESC LIMIT 5)
UNION ALL
(SELECT s_suppkey, s_name
 FROM supplier, nation
 WHERE s_nationkey = n_nationkey AND n_name = 'CANADA'
 ORDER BY s_suppkey LIMIT 6)
UNION ALL
(SELECT p_partkey, p_name
 FROM part, lineitem
 WHERE p_partkey = l_partkey AND l_quantity > 20
 ORDER BY p_partkey DESC LIMIT 7)
UNION ALL
(SELECT ps_partkey, p_name
 FROM part, partsupp
 WHERE p_partkey = ps_partkey AND ps_supplycost >= 1000
 ORDER BY ps_partkey LIMIT 8);

-- U5
(SELECT o_orderkey, o_orderdate, n_name
 FROM orders, customer, nation
 WHERE o_custkey = c_custkey
   AND c_nationkey = n_nationkey
   AND c_name LIKE '%0001248%'
   AND o_orderdate >= '1997-01-01'
 ORDER BY o_orderkey LIMIT 20)
UNION ALL
(SELECT l_orderkey, l_shipdate, o_orderstatus
 FROM lineitem, orders
 WHERE l_orderkey = o_orderkey
   AND o_orderdate < '1994-01-01'
   AND l_quantity > 20
   AND l_extendedprice > 1000
 ORDER BY l_orderkey LIMIT 5);

-- U6
(SELECT o_clerk AS name, SUM(l_extendedprice) AS total_price
 FROM orders, lineitem
 WHERE o_orderkey = l_orderkey
   AND o_orderdate <= '1995-01-01'
 GROUP BY o_clerk
 ORDER BY total_price DESC LIMIT 10)
UNION ALL
(SELECT n_name AS name, SUM(s_acctbal) AS total_price
 FROM nation, supplier
 WHERE n_nationkey = s_nationkey
   AND n_name LIKE '%UNITED%'
 GROUP BY n_name
 ORDER BY n_name DESC LIMIT 10);

-- U7
(SELECT l_orderkey AS key, l_extendedprice AS price, l_partkey AS s_key
 FROM lineitem
 WHERE l_shipdate >= DATE '1994-01-01'
   AND l_shipdate < DATE '1995-01-01'
   AND l_quantity > 30
 ORDER BY key LIMIT 20)
UNION ALL
(SELECT ps_partkey AS key, p_retailprice AS price, ps_suppkey AS s_key
 FROM partsupp, supplier, part
 WHERE ps_suppkey = s_suppkey
   AND ps_partkey = p_partkey
   AND ps_supplycost < 100
 ORDER BY price LIMIT 20);

-- U8
(SELECT c_custkey AS order_id, COUNT(*) AS total
 FROM customer, orders
 WHERE c_custkey = o_custkey
   AND o_orderdate >= '1995-01-01'
 GROUP BY c_custkey
 ORDER BY total ASC LIMIT 10)
UNION ALL
(SELECT wl_orderkey AS order_id, AVG(wl_quantity) AS total
 FROM orders, web_lineitem
 WHERE wl_orderkey = o_orderkey
   AND o_orderdate < DATE '1996-07-01'
 GROUP BY wl_orderkey
 ORDER BY total DESC LIMIT 10);

-- U9
(SELECT c_name, n_name
 FROM customer, nation
 WHERE c_mktsegment = 'BUILDING'
   AND c_acctbal > 100
   AND c_nationkey = n_nationkey)
UNION ALL
(SELECT s_name, n_name
 FROM supplier, nation
 WHERE s_acctbal > 4000
   AND s_nationkey = n_nationkey);

-- O1
SELECT
    c_name,
    n_name,
    COUNT(*) AS total
FROM nation
RIGHT OUTER JOIN customer
    ON c_nationkey = n_nationkey
   AND c_acctbal < 1000
GROUP BY
    c_name,
    n_name
ORDER BY
    c_name,
    n_name DESC
LIMIT 10;

-- O2
SELECT
    l_shipmode,
    o_shippriority,
    COUNT(*) AS low_line_count
FROM lineitem
LEFT OUTER JOIN orders
    ON l_orderkey = o_orderkey
   AND o_totalprice > 50000
WHERE
    l_linenumber = 4
    AND l_quantity < 30
GROUP BY
    l_shipmode,
    o_shippriority
ORDER BY
    l_shipmode
LIMIT 5;

-- O3
SELECT
    o_custkey AS key,
    SUM(c_acctbal),
    o_clerk,
    c_name
FROM orders
FULL OUTER JOIN customer
    ON c_custkey = o_custkey
   AND o_orderstatus = 'F'
GROUP BY
    o_custkey,
    o_clerk,
    c_name
ORDER BY
    key
LIMIT 35;

-- O4
SELECT
    p_size,
    s_phone,
    ps_supplycost,
    n_name
FROM part
RIGHT OUTER JOIN partsupp
    ON p_partkey = ps_partkey
   AND p_size > 7
LEFT OUTER JOIN supplier
    ON ps_suppkey = s_suppkey
   AND s_acctbal < 2000
FULL OUTER JOIN nation
    ON s_nationkey = n_nationkey
   AND n_regionkey > 3
ORDER BY
    ps_supplycost ASC
LIMIT 50;

-- O5
SELECT
    ps_suppkey,
    p_name,
    p_type
FROM part
RIGHT OUTER JOIN partsupp
    ON p_partkey = ps_partkey
   AND p_size > 4
   AND ps_availqty > 3350
ORDER BY
    ps_suppkey
LIMIT 100;

-- O6
SELECT
    p_name,
    s_phone,
    ps_supplycost,
    n_name
FROM part
RIGHT OUTER JOIN partsupp
    ON p_partkey = ps_partkey
   AND p_size > 7
LEFT OUTER JOIN supplier
    ON ps_suppkey = s_suppkey
   AND s_acctbal < 2000
FULL OUTER JOIN nation
    ON s_nationkey = n_nationkey
   AND n_regionkey > 3
ORDER BY
    p_name,
    s_phone,
    ps_supplycost,
    n_name DESC
LIMIT 20;
-- A1
SELECT
    l_shipmode,
    COUNT(*) AS count
FROM orders, lineitem
WHERE
    o_orderkey = l_orderkey
    AND l_commitdate < l_receiptdate
    AND l_shipdate < l_commitdate
    AND l_receiptdate >= '1994-01-01'
    AND l_receiptdate < '1995-01-01'
    AND l_extendedprice <= o_totalprice
    AND l_extendedprice <= 70000
    AND o_totalprice > 60000
GROUP BY
    l_shipmode
ORDER BY
    l_shipmode;

-- A2
SELECT
    o_orderpriority,
    COUNT(*) AS order_count
FROM orders, lineitem
WHERE
    l_orderkey = o_orderkey
    AND o_orderdate >= '1993-07-01'
    AND o_orderdate < '1993-10-01'
    AND l_commitdate <= l_receiptdate
GROUP BY
    o_orderpriority
ORDER BY
    o_orderpriority;

-- A3
SELECT
    l_orderkey,
    l_linenumber
FROM orders, lineitem, partsupp
WHERE
    o_orderkey = l_orderkey
    AND ps_partkey = l_partkey
    AND ps_suppkey = l_suppkey
    AND ps_availqty = l_linenumber
    AND l_shipdate >= o_orderdate
    AND o_orderdate >= '1990-01-01'
    AND l_commitdate <= l_receiptdate
    AND l_shipdate <= l_commitdate
    AND l_receiptdate > '1994-01-01'
ORDER BY
    l_orderkey
LIMIT 7;

-- A4
SELECT
    s_name,
    COUNT(*) AS numwait
FROM supplier, lineitem, orders, nation
WHERE
    s_suppkey = l_suppkey
    AND o_orderkey = l_orderkey
    AND o_orderstatus = 'F'
    AND l_receiptdate >= l_commitdate
    AND s_nationkey = n_nationkey
GROUP BY
    s_name
ORDER BY
    numwait DESC
LIMIT 100;

-- A5
SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM lineitem
WHERE
    l_shipdate <= l_receiptdate
    AND l_receiptdate <= l_commitdate
GROUP BY
    l_returnflag,
    l_linestatus
ORDER BY
    l_returnflag,
    l_linestatus;

-- N1
SELECT
    p_brand,
    p_type,
    p_size,
    COUNT(*) AS supplier_cnt
FROM part, partsupp
WHERE
    p_partkey = ps_partkey
    AND p_size >= 4
    AND p_type NOT LIKE 'SMALL PLATED%'
    AND p_brand <> 'Brand#45'
GROUP BY
    p_brand,
    p_size,
    p_type
ORDER BY
    supplier_cnt DESC,
    p_brand ASC,
    p_type ASC,
    p_size ASC;

-- F1
(
    SELECT
        c_name AS name,
        c_acctbal AS account_balance
    FROM orders, customer, nation
    WHERE
        c_custkey = o_custkey
        AND c_nationkey = n_nationkey
        AND c_mktsegment = 'FURNITURE'
        AND n_name = 'INDIA'
        AND o_orderdate BETWEEN '1998-01-01' AND '1998-12-05'
        AND o_totalprice <= c_acctbal
)
UNION ALL
(
    SELECT
        s_name AS name,
        s_acctbal AS account_balance
    FROM supplier, lineitem, orders, nation
    WHERE
        l_suppkey = s_suppkey
        AND l_orderkey = o_orderkey
        AND s_nationkey = n_nationkey
        AND n_name = 'ARGENTINA'
        AND o_orderdate BETWEEN '1998-01-01' AND '1998-01-05'
        AND o_totalprice > s_acctbal
        AND o_totalprice >= 30000
        AND 50000 >= s_acctbal
    ORDER BY
        account_balance DESC
    LIMIT 20
);

-- F2
(
    SELECT
        p_brand,
        o_clerk,
        l_shipmode
    FROM orders, lineitem, part
    WHERE
        l_partkey = p_partkey
        AND o_orderkey = l_orderkey
        AND l_shipdate >= o_orderdate
        AND o_orderdate > '1994-01-01'
        AND l_shipdate > '1995-01-01'
        AND p_retailprice >= l_extendedprice
        AND p_partkey < 10000
        AND l_suppkey < 10000
        AND p_container = 'LG CAN'
    ORDER BY
        o_clerk
    LIMIT 5
)
UNION ALL
(
    SELECT
        p_brand,
        s_name,
        l_shipmode
    FROM lineitem, part, supplier
    WHERE
        l_partkey = p_partkey
        AND s_suppkey = s_suppkey
        AND l_shipdate > '1995-01-01'
        AND s_acctbal >= l_extendedprice
        AND p_partkey < 15000
        AND l_suppkey < 14000
        AND p_container = 'LG CAN'
    ORDER BY
        s_name
    LIMIT 10
);

-- F3
(
    SELECT
        l_orderkey,
        l_extendedprice AS price,
        p_partkey
    FROM lineitem, part
    WHERE
        l_partkey = p_partkey
        AND p_container LIKE 'JUMBO%'
        AND p_partkey > 3000
        AND l_partkey < 3010
    ORDER BY
        l_orderkey,
        price DESC
    LIMIT 100
)
UNION ALL
(
    SELECT
        o_orderkey,
        c_acctbal AS price,
        c_custkey
    FROM customer
    LEFT OUTER JOIN orders
        ON c_custkey = o_custkey
    WHERE
        c_custkey > 1000
        AND c_custkey < 1010
    ORDER BY
        price DESC,
        o_orderkey,
        c_custkey
    LIMIT 100
);

-- F4
SELECT
    n_name,
    c_acctbal
FROM nation
LEFT OUTER JOIN customer
    ON n_nationkey = c_nationkey
   AND c_nationkey > 3
   AND n_nationkey < 20
   AND c_nationkey != 10
LIMIT 200;

-- MQ1
SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM lineitem
WHERE
    l_shipdate <= DATE '1998-12-01' - INTERVAL '71 days'
GROUP BY
    l_returnflag,
    l_linestatus
ORDER BY
    l_returnflag,
    l_linestatus;

-- MQ2
SELECT
    s_acctbal,
    s_name,
    n_name,
    p_partkey,
    p_mfgr,
    s_address,
    s_phone,
    s_comment
FROM part, supplier, partsupp, nation, region
WHERE
    p_partkey = ps_partkey
    AND s_suppkey = ps_suppkey
    AND p_size = 38
    AND p_type LIKE '%TIN'
    AND s_nationkey = n_nationkey
    AND n_regionkey = r_regionkey
    AND r_name = 'MIDDLE EAST'
ORDER BY
    s_acctbal DESC,
    n_name,
    s_name,
    p_partkey
LIMIT 100;

-- MQ3
SELECT
    l_orderkey,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
    o_orderdate,
    o_shippriority
FROM customer, orders, lineitem
WHERE
    c_mktsegment = 'BUILDING'
    AND c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND o_orderdate < DATE '1995-03-15'
    AND l_shipdate > DATE '1995-03-15'
GROUP BY
    l_orderkey,
    o_orderdate,
    o_shippriority
ORDER BY
    revenue DESC,
    o_orderdate
LIMIT 10;

-- MQ4
SELECT
    o_orderdate,
    o_orderpriority,
    COUNT(*) AS order_count
FROM orders
WHERE
    o_orderdate >= DATE '1997-07-01'
    AND o_orderdate < DATE '1997-07-01' + INTERVAL '3 months'
GROUP BY
    o_orderdate,
    o_orderpriority
ORDER BY
    o_orderpriority
LIMIT 10;

-- MQ5
SELECT
    n_name,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM customer, orders, lineitem, supplier, nation, region
WHERE
    c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND l_suppkey = s_suppkey
    AND c_nationkey = s_nationkey
    AND s_nationkey = n_nationkey
    AND n_regionkey = r_regionkey
    AND r_name = 'MIDDLE EAST'
    AND o_orderdate >= DATE '1994-01-01'
    AND o_orderdate < DATE '1994-01-01' + INTERVAL '1 year'
GROUP BY
    n_name
ORDER BY
    revenue DESC
LIMIT 100;

-- MQ6
SELECT
    l_shipmode,
    SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE
    l_shipdate >= DATE '1994-01-01'
    AND l_shipdate < DATE '1994-01-01' + INTERVAL '1 year'
    AND l_quantity < 24
GROUP BY
    l_shipmode
LIMIT 100;

-- MQ10
SELECT
    c_name,
    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
    c_acctbal,
    n_name,
    c_address,
    c_phone,
    c_comment
FROM customer, orders, lineitem, nation
WHERE
    c_custkey = o_custkey
    AND l_orderkey = o_orderkey
    AND o_orderdate >= DATE '1994-01-01'
    AND o_orderdate < DATE '1994-01-01' + INTERVAL '3 months'
    AND l_returnflag = 'R'
    AND c_nationkey = n_nationkey
GROUP BY
    c_name,
    c_acctbal,
    c_phone,
    n_name,
    c_address,
    c_comment
ORDER BY
    revenue DESC
LIMIT 20;

-- MQ11
SELECT
    ps_comment,
    SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE
    ps_suppkey = s_suppkey
    AND s_nationkey = n_nationkey
    AND n_name = 'ARGENTINA'
GROUP BY
    ps_comment
ORDER BY
    value DESC
LIMIT 100;

-- MQ17
SELECT
    AVG(l_extendedprice) AS avg_total
FROM lineitem, part
WHERE
    p_partkey = l_partkey
    AND p_brand = 'Brand#52'
    AND p_container = 'LG CAN';

-- MQ18
SELECT
    c_name,
    o_orderdate,
    o_totalprice,
    SUM(l_quantity)
FROM customer, orders, lineitem
WHERE
    c_phone LIKE '27-%'
    AND c_custkey = o_custkey
    AND o_orderkey = l_orderkey
GROUP BY
    c_name,
    o_orderdate,
    o_totalprice
ORDER BY
    o_orderdate,
    o_totalprice DESC
LIMIT 100;

-- MQ21
SELECT
    s_name,
    COUNT(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE
    s_suppkey = l1.l_suppkey
    AND o_orderkey = l1.l_orderkey
    AND o_orderstatus = 'F'
    AND s_nationkey = n_nationkey
    AND n_name = 'GERMANY'
GROUP BY
    s_name
ORDER BY
    numwait DESC,
    s_name
LIMIT 100;
