# Query Extraction Comparison: Black-Box vs. Extracted Query

This document compares the query inside the black-box application (input) with the query recovered by the LLM-based extraction (output).

- **Black-box application:** [AccountExposureReport.java](https://github.com/ahanapradhan/PRISM/blob/main/usecase/prism-usecase/src/main/java/AccountExposureReport.java)
- **LLM analysis for query recovery:** [closed_hibernate_report_analysis.md](https://github.com/ahanapradhan/PRISM/blob/main/usecase/prism-usecase/out/closed_hibernate_report_analysis.md)

## Side-by-Side Comparison

<table>
<tr>
<th width="50%">Black-box query (input)</th>
<th width="50%">Extracted query (output)</th>
</tr>
<tr>
<td valign="top">

```sql
(SELECT c_name AS entity_name, n_name AS country, o_totalprice AS price
 FROM customer RIGHT OUTER JOIN orders ON c_custkey = o_custkey
               AND c_acctbal >= o_totalprice AND c_acctbal >= 9000
      LEFT OUTER JOIN nation ON c_nationkey = n_nationkey
 WHERE o_totalprice <= 15000
 GROUP BY n_name, c_name, o_totalprice
 ORDER BY price, country, entity_name LIMIT 10)
UNION ALL
(SELECT s_name AS entity_name, n_name AS country, avg(l_extendedprice*(1 - l_discount)) AS price
 FROM supplier, lineitem, orders, nation, region
 WHERE l_suppkey = s_suppkey AND l_orderkey = o_orderkey
   AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey
   AND (l_shipmode = 'AIR' OR l_shipmode = 'TRUCK') AND r_name <> 'EUROPE'
   AND o_totalprice >= s_acctbal AND 15000 >= o_totalprice
 GROUP BY n_name, s_name
 ORDER BY price DESC, country DESC, entity_name LIMIT 20)
```

</td>
<td valign="top">

```sql
WITH cost_section AS (
    SELECT
        NULL::varchar AS supplier_name,
        NULL::varchar AS nation_name,
        ps.ps_supplycost::numeric AS amount,
        1 AS section_order,
        row_number() OVER (
            ORDER BY ps.ps_supplycost ASC,
                     ps.ps_partkey ASC,
                     ps.ps_suppkey ASC
        ) AS row_order
    FROM partsupp AS ps
    WHERE ps.ps_supplycost >= 857.71
      AND ps.ps_supplycost <= 895.39
    ORDER BY ps.ps_supplycost ASC,
             ps.ps_partkey ASC,
             ps.ps_suppkey ASC
    LIMIT 10
),
revenue_by_supplier AS (
    SELECT
        s.s_name::varchar AS supplier_name,
        n.n_name::varchar AS nation_name,
        SUM(li.l_extendedprice * (1 - li.l_discount))::numeric AS amount
    FROM lineitem AS li
    JOIN supplier AS s
      ON s.s_suppkey = li.l_suppkey
    JOIN nation AS n
      ON n.n_nationkey = s.s_nationkey
    /*
       The real application almost certainly supplied one or more hidden
       predicates here. A common TPC-H-style candidate is a half-open ship-date
       interval, for example:

       WHERE li.l_shipdate >= DATE '1996-01-01'
         AND li.l_shipdate <  DATE '1996-04-01'

       I leave it disabled because the actual dates cannot be inferred from the
       exposed plans or output.
    */
    GROUP BY s.s_suppkey, s.s_name, n.n_name
),
revenue_section AS (
    SELECT
        ranked.supplier_name,
        ranked.nation_name,
        ranked.amount,
        2 AS section_order,
        row_number() OVER (
            ORDER BY ranked.amount DESC,
                     ranked.supplier_name ASC,
                     ranked.nation_name ASC
        ) AS row_order
    FROM (
        SELECT supplier_name, nation_name, amount
        FROM revenue_by_supplier
        ORDER BY amount DESC,
                 supplier_name ASC,
                 nation_name ASC
        LIMIT 20
    ) AS ranked
)
SELECT supplier_name, nation_name, amount
FROM (
    SELECT supplier_name, nation_name, amount, section_order, row_order
    FROM cost_section

    UNION ALL

    SELECT supplier_name, nation_name, amount, section_order, row_order
    FROM revenue_section
) AS report
ORDER BY section_order ASC, row_order ASC;
```

</td>
</tr>
<tr>
<td colspan="2"><b>Exact differences</b></td>
</tr>
<tr>
<td valign="top">

**Overall structure**
Two parenthesised `SELECT` blocks combined with `UNION ALL`. Each block has its own `ORDER BY` and `LIMIT`.

</td>
<td valign="top">

**Overall structure**
Three CTEs (`cost_section`, `revenue_by_supplier`, `revenue_section`) combined with `UNION ALL` inside an outer wrapper. The wrapper adds `section_order` and `row_order` and sorts by them to preserve the section sequence.

</td>
</tr>
<tr>
<td valign="top">

**Branch 1: tables**
`customer`, `orders`, `nation` (RIGHT OUTER JOIN and LEFT OUTER JOIN).

</td>
<td valign="top">

**Branch 1: tables**
Only `partsupp`. No joins. This is a different table set from the input.

</td>
</tr>
<tr>
<td valign="top">

**Branch 1: columns**
`c_name AS entity_name`, `n_name AS country`, `o_totalprice AS price`.

</td>
<td valign="top">

**Branch 1: columns**
`NULL AS supplier_name`, `NULL AS nation_name`, `ps_supplycost AS amount`. Names and nation are not recovered, and the amount comes from a different column.

</td>
</tr>
<tr>
<td valign="top">

**Branch 1: filters**
`c_acctbal >= o_totalprice`, `c_acctbal >= 9000` (in the join condition) and `o_totalprice <= 15000`.

</td>
<td valign="top">

**Branch 1: filters**
`ps_supplycost >= 857.71 AND ps_supplycost <= 895.39`. These are different predicates and constants on a different column.

</td>
</tr>
<tr>
<td valign="top">

**Branch 1: grouping and ordering**
`GROUP BY n_name, c_name, o_totalprice`. `ORDER BY price, country, entity_name`. `LIMIT 10`.

</td>
<td valign="top">

**Branch 1: grouping and ordering**
No `GROUP BY`. `ORDER BY ps_supplycost, ps_partkey, ps_suppkey`. `LIMIT 10` (the only element that matches).

</td>
</tr>
<tr>
<td valign="top">

**Branch 2: tables**
`supplier`, `lineitem`, `orders`, `nation`, `region` (implicit comma joins).

</td>
<td valign="top">

**Branch 2: tables**
`lineitem`, `supplier`, `nation` (explicit `JOIN ... ON`). `orders` and `region` are missing.

</td>
</tr>
<tr>
<td valign="top">

**Branch 2: filters**
`l_shipmode = 'AIR' OR 'TRUCK'`, `r_name <> 'EUROPE'`, `o_totalprice >= s_acctbal`, `o_totalprice <= 15000`, plus the join predicates for `orders` and `region`.

</td>
<td valign="top">

**Branch 2: filters**
None. A commented-out, guessed ship-date range is left disabled. None of the input predicates (ship mode, region, account balance, price bound) are recovered.

</td>
</tr>
<tr>
<td valign="top">

**Branch 2: aggregate**
`avg(l_extendedprice * (1 - l_discount))`.

</td>
<td valign="top">

**Branch 2: aggregate**
`SUM(li.l_extendedprice * (1 - li.l_discount))`. This is `SUM` instead of `AVG`.

</td>
</tr>
<tr>
<td valign="top">

**Branch 2: grouping and ordering**
`GROUP BY n_name, s_name`. `ORDER BY price DESC, country DESC, entity_name`. `LIMIT 20`.

</td>
<td valign="top">

**Branch 2: grouping and ordering**
`GROUP BY s_suppkey, s_name, n_name`. `ORDER BY amount DESC, supplier_name ASC, nation_name ASC` (nation is ASC here, but DESC in the input). `LIMIT 20` (matches).

</td>
</tr>
<tr>
<td valign="top">

**Output schema**
`entity_name`, `country`, `price`.

</td>
<td valign="top">

**Output schema**
`supplier_name`, `nation_name`, `amount`. Names differ, and explicit casts (`::varchar`, `::numeric`) are added.

</td>
</tr>
<tr>
<td valign="top">

**Final ordering**
None across the union. Row order between the two blocks is not formally guaranteed.

</td>
<td valign="top">

**Final ordering**
`ORDER BY section_order, row_order` keeps the first block's rows ahead of the second block's rows.

</td>
</tr>
<tr>
<td valign="top">

**Meaning (input)**
Returns an "account exposure" report in two parts. Part 1 lists up to 10 customer/orders rows (customer name, nation, order price). Orders priced at or below 15,000 are kept, and the customer is matched only when their balance is at least 9,000 and covers the order price. Part 2 lists up to 20 suppliers with their nation and their *average* discounted line revenue. It covers only AIR or TRUCK shipments, only nations outside the EUROPE region, and only orders priced at most 15,000 that are at least the supplier's account balance. These are the highest-ranked suppliers.

</td>
<td valign="top">

**Meaning (output)**
Returns a two-section report. Section 1 lists up to 10 part-supplier supply costs between 857.71 and 895.39, lowest first, with no supplier or nation names. Section 2 lists the top 20 suppliers with their nation, ranked by *total* (summed) discounted line revenue across all their line items, with no ship mode, region, order price or balance conditions. Both sections are numbered so the cost section always appears before the revenue section.

</td>
</tr>
</table>

## Summary

The extracted query reproduces only the high-level shape of the black-box query. It is a `UNION ALL` of two ranked blocks, with `LIMIT 10` and `LIMIT 20` respectively, and the second block is a discounted-revenue aggregate over `lineitem`, `supplier` and `nation`. The first block's tables, columns, predicates and grouping are all different. The second block's joins (`orders`, `region`), filters, and aggregate function (`SUM` vs. `AVG`) are not recovered, so the two queries are not semantically equivalent.
