# Reverse-engineering the closed Hibernate report

## Executive summary

The evidence is insufficient to recover the application exactly because the four PostgreSQL functions and their bound parameters are hidden. The SQL below is therefore a **best-behavioral guess**, not a proof of equivalence.

My strongest inference is that the last 20 rows are a conventional supplier-revenue ranking. Their third column is consistent with a `numeric` expression such as `SUM(l_extendedprice * (1 - l_discount))`, and the rows are ordered by that value descending. The first 10 rows appear to be a separate numeric list that the Java application projected into the same three-column report shape, padding the first two columns with SQL `NULL`.

The least defensible part is the first section's predicate and semantics. The displayed values lie in the natural range of `partsupp.ps_supplycost`, so I model them as supply-cost values. However, neither the hidden threshold nor the rule that reduces the candidates to ten values is observable.

## Best-guess query

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

## Important qualification

The query above is intended as an explicit, testable hypothesis. It is **unlikely to reproduce the supplied 30 rows without replacing the guessed predicates with the real bind values**. In particular:

1. The `partsupp` interval was inferred directly from the first and last displayed values. It is therefore fitted to the observation and is not independently established.
2. An unfiltered `lineitem` revenue aggregation will almost certainly produce amounts much larger than roughly 14,500. The hidden `hq_4` parameters probably impose a date window, quantity range, discount range, ship mode, or some combination.
3. The exact decimal scale shown by the Java program may depend on JDBC/Hibernate `BigDecimal` handling rather than only PostgreSQL's display behavior.
4. Ties cannot be reconstructed. I added stable supplier-name and key tie-breakers so the guessed query has deterministic output.

## Evidence inventory

### Database facts

The schema is TPC-H-like and contains `nation`, `region`, `customer`, `supplier`, `part`, `partsupp`, `orders`, and `lineitem`. The supplied output has exactly 30 rows and three columns. Its first ten rows have NULL in columns one and two; its last twenty rows contain a supplier name, nation name, and a decimal amount.

### Observed application calls

The application executed four opaque calls:

```sql
select * from hq_1(?);
select * from hq_2(?);
select * from hq_4(?, ?, ?);
select * from hq_3(?);
```

The plans reveal only wrapper-level `Function Scan` nodes. They report these cardinalities:

| Function | Bind count | Rows returned | Plan width |
|---|---:|---:|---:|
| `hq_1` | 1 | 25 | 41 |
| `hq_2` | 1 | 13,551 | 104 |
| `hq_4` | 3 | 6,534 | 72 |
| `hq_3` | 1 | 47,406 | 40 |

The row counts are useful clues but do not reveal column identities, predicates, ordering, or parameter values.

## Reconstruction reasoning

### 1. The report is probably assembled in Java

No one function returned 30 rows according to the plans. The application therefore likely fetched larger intermediate result sets and performed joins, filtering, aggregation, ranking, projection, or concatenation in Java. The sharp split between ten NULL-padded rows and twenty supplier rows strongly suggests two report sections were concatenated.

A SQL reconstruction should consequently use `UNION ALL`, not `UNION`, because the application printed two ordered sections and duplicate elimination is not evidenced.

### 2. The last 20 rows look like discounted revenue

Every row in the second section has:

- an existing-looking supplier identifier,
- a nation name,
- a high-precision decimal,
- descending ordering by the decimal amount.

The schema's most natural supplier-level monetary measure is:

```sql
SUM(lineitem.l_extendedprice * (1 - lineitem.l_discount))
```

This is also a standard TPC-H revenue expression. Joining `lineitem.l_suppkey` to `supplier.s_suppkey`, then `supplier.s_nationkey` to `nation.n_nationkey`, directly explains the first two columns.

**Confidence: medium-high** for the joins, grouping entity, revenue expression, descending sort, and top-20 limit.

**Confidence: very low** for the missing filter. Without a restrictive condition, total supplier revenue across all line items should be far above the displayed range. The three parameters of `hq_4` are the strongest clue that this section used several filter values.

### 3. The first 10 values resemble supply costs

The first-section values range from `857.71` through `895.39`. Of the listed columns, `partsupp.ps_supplycost numeric(15,2)` is the cleanest semantic and type match. The ascending order is obvious.

Other plausible sources include:

- `supplier.s_acctbal`,
- `customer.c_acctbal`,
- an average or minimum derived from `partsupp`,
- a Java-side computation over one of the hidden result sets.

Raw `p_retailprice` is less plausible because the shown sample starts around 901 and the TPC-H retail-price formula normally stays above that neighborhood.

**Confidence: medium** that these are monetary/cost values sorted ascending.

**Confidence: low** that they are raw `ps_supplycost` values.

**Confidence: near zero** for the threshold and limiting rule used in the candidate query.

### 4. Possible roles of the hidden functions

A plausible, but unproved, mapping is:

| Function | Possible role | Rationale |
|---|---|---|
| `hq_1(?)` | Nation lookup/filter | Exactly 25 rows, matching the table's nation count |
| `hq_2(?)` | Orders or customer-side candidates | 13,551 rows with relatively wide tuples |
| `hq_4(?, ?, ?)` | Filtered line items | Three binds, 6,534 rows, longest execution time, very high buffer activity |
| `hq_3(?)` | Partsupp/order-side candidates | 47,406 rows with narrow tuples |

This mapping is only suggestive. PostgreSQL function plan widths are not sufficient to identify return schemas, and Java may combine the functions in a non-obvious order.

## What is reasonably certain

- The final shape is three columns and 30 rows.
- The first section contains ten rows and intentionally or effectively supplies NULL for its first two projected fields.
- The second section contains twenty supplier/nation/amount rows.
- The second section is sorted by amount descending in the observed output.
- The first section is sorted by amount ascending in the observed output.
- A faithful SQL version needs an explicit outer ordering; relying on CTE or subquery order alone would be incorrect.
- `UNION ALL` is safer than `UNION` because section concatenation, not set semantics, matches the observed behavior.

## What is guessed

- `ps_supplycost` as the source of the first ten values.
- The first-section bounds `857.71` and `895.39`.
- The use of `SUM(l_extendedprice * (1 - l_discount))` for the last column.
- Any revenue filter, especially a date window.
- Tie-break ordering.
- The correspondence between each hidden function and a base table.
- Whether Java used all returned intermediate rows or stopped early.

## Why no exact validation is possible from the prompt

Only the first three rows of each base table are supplied, not a database dump. Therefore the proposed query cannot be executed against the described instance here. The output itself is not enough to distinguish among many queries that agree on this database but diverge on another.

To turn this hypothesis into a defensible reconstruction, obtain any one of the following, in descending order of value:

1. `pg_get_functiondef` output for `hq_1`, `hq_2`, `hq_3`, and `hq_4`.
2. PostgreSQL parameter logging, such as `log_parameter_max_length` plus suitable statement logging, or a JDBC/Hibernate bind-parameter trace.
3. `EXPLAIN (ANALYZE, VERBOSE, BUFFERS)` of the SQL inside each function rather than the wrapper call.
4. A database dump or read-only access for differential testing.
5. Outputs from multiple databases or from controlled data mutations.

## Recommended validation procedure

1. Run the candidate query and capture results in tab-separated, headerless form.
2. Compare row count, column count, NULL placement, numeric scale, values, and order.
3. If the supplier identities are close but values differ, test candidate predicates against `l_shipdate`, `l_quantity`, `l_discount`, and `l_shipmode`.
4. If supplier identities differ completely, test whether the aggregation uses `ps_supplycost * ps_availqty`, plain `l_extendedprice`, or tax-adjusted revenue.
5. For the first section, inspect whether each displayed value exists exactly in `partsupp.ps_supplycost`, `supplier.s_acctbal`, or `customer.c_acctbal`. Exact membership is a fast discriminator.
6. Add deterministic tie-breakers only after matching the primary observed order.

## Bottom line

The proposed SQL captures the most plausible report structure: an ascending ten-row, NULL-padded cost section followed by a descending top-20 supplier revenue section. The supplier joins and top-20 ranking are the strongest parts. The first-section bounds and all hidden filters are fitted guesses and should not be represented as recovered facts.
