-- DB-side objects: four TEMPLATED extract functions. Each one pushes something non-trivial into the database
-- (a join, an outer join, a DISTINCT, a computed flag, a multi-table aggregate), so none maps to a single table.
-- Constants arrive as parameters, bound by the application: they never appear in the SQL text Hibernate logs.
DROP FUNCTION IF EXISTS hq_1();  DROP FUNCTION IF EXISTS hq_1(text);
DROP FUNCTION IF EXISTS hq_2();  DROP FUNCTION IF EXISTS hq_2(text, text);  DROP FUNCTION IF EXISTS hq_2(numeric);
DROP FUNCTION IF EXISTS hq_3();  DROP FUNCTION IF EXISTS hq_3(text);        DROP FUNCTION IF EXISTS hq_3(numeric);
DROP FUNCTION IF EXISTS hq_4();  DROP FUNCTION IF EXISTS hq_4(text, text, numeric);
DROP FUNCTION IF EXISTS hq_5();  DROP FUNCTION IF EXISTS hq_6();  DROP FUNCTION IF EXISTS hq_6(text, text, text);

-- nation LEFT JOIN region, with a computed flag "region differs from k1" (false when the region is missing)
CREATE FUNCTION hq_1(k1 text) RETURNS TABLE (c1 bigint, c2 text, c3 boolean)
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
  RETURN QUERY
    SELECT n.n_nationkey::bigint, n.n_name::text, COALESCE(rtrim(r.r_name) <> k1, false)
    FROM nation n LEFT JOIN region r ON n.n_regionkey = r.r_regionkey;
END $fn$;

-- customer LEFT JOIN nation, restricted to balances >= k1
CREATE FUNCTION hq_2(k1 numeric) RETURNS TABLE (c1 bigint, c2 text, c3 text, c4 numeric)
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
  RETURN QUERY
    SELECT c.c_custkey::bigint, c.c_name::text, n.n_name::text, c.c_acctbal::numeric
    FROM customer c LEFT JOIN nation n ON c.c_nationkey = n.n_nationkey
    WHERE c.c_acctbal >= k1;
END $fn$;

-- distinct (customer key, price) pairs of the orders priced <= k1
CREATE FUNCTION hq_3(k1 numeric) RETURNS TABLE (c1 bigint, c2 numeric)
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
  RETURN QUERY
    SELECT DISTINCT o.o_custkey::bigint, o.o_totalprice::numeric
    FROM orders o
    WHERE o.o_totalprice <= k1;
END $fn$;

-- supplier JOIN lineitem JOIN orders: ship mode in (k1, k2), order price >= supplier balance and <= k3,
-- AVG of the discounted line price per (supplier nation, supplier name)
CREATE FUNCTION hq_4(k1 text, k2 text, k3 numeric) RETURNS TABLE (c1 bigint, c2 text, c3 numeric)
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
  RETURN QUERY
    SELECT s.s_nationkey::bigint, s.s_name::text, avg(l.l_extendedprice * (1 - l.l_discount))::numeric
    FROM supplier s
         JOIN lineitem l ON l.l_suppkey = s.s_suppkey
         JOIN orders   o ON o.o_orderkey = l.l_orderkey
    WHERE (rtrim(l.l_shipmode) = k1 OR rtrim(l.l_shipmode) = k2)
      AND o.o_totalprice >= s.s_acctbal AND o.o_totalprice <= k3
    GROUP BY s.s_nationkey, s.s_name;
END $fn$;
