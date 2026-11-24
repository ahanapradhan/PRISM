# Unresolved queries and known issues

Last reviewed: **2026-11-24**

Use this file as the lookup table when asked about unresolved/false queries or about whether a query has the same projection/equation-building issue as A7/A8.

## Quick answers

- **Same projection/equation issue as A7/A8:** **F3 only historically**.
  - Historical symptom: `numpy.linalg.LinAlgError: Singular matrix`.
  - Historical evidence: duplicate coefficient rows such as `[[1007, 1], [1007, 1]]` with `b=[[1007], [1007]]`.
  - F3 is now correct in 3 of 4 current reruns (`unresolved`, `recheck`, `stability`); the one false `allflags` run was the old outer-join class. It has been moved out of the active table.
- **A7:** fixed/correct; extracts `Avg(2*o_totalprice + 1)`.
- **A8:** projection fixed; removed because its only remaining diff was a spurious `n_name asc` ORDER BY key.
- **No current false query has the singular-matrix/duplicate-equation signature.** Several MQ/N-series queries have a different projection-solver regression: they invent a non-zero constant and then lose the enclosing `SUM(...)`. That is recorded below but is not the A7/A8 equation-building bug.
- **Flaky queries:** `O3`, `A13`, `UK6`, and `DISJ_OJ1` changed result between reruns with the same source. Their reasons below come from the false runs. `UK6`/`UK8` were comparator typmod/padding artifacts: the result comparator now materializes both sides as trimmed text. `UK8` was rerun after the fix and passed; `UK6` has not been rerun yet.

## Verification runs

All runs used `tmp_run_matrix.py` with the same all-advanced-extractors configuration (`union=True`, `oj=True`, `nep=True`, `orf=True`, `cs2=False`, native backup):

```bash
/home/iiitb/Downloads/Python-3.9.0/python tmp_run_matrix.py --only O3,oj_bug,F16,A10,A13,UK6,UK8,DISJ_OJ1,DISJ_UN3,N9,U8,F12,F17,N8,Alaap --label unresolved --timeout 1800
/home/iiitb/Downloads/Python-3.9.0/python tmp_run_matrix.py --only MQ3,MQ5,F3,MQ10,MQ11 --label unresolved --timeout 1800
/home/iiitb/Downloads/Python-3.9.0/python tmp_run_matrix.py --only F3,A13,UK6,DISJ_OJ1 --label recheck --timeout 1800
/home/iiitb/Downloads/Python-3.9.0/python tmp_run_matrix.py --only F3,DISJ_OJ1,oj_bug,O3,UK8 --label stability --timeout 1800
/home/iiitb/Downloads/Python-3.9.0/python tmp_run_matrix.py --only UK8,UK3 --label comparator_fix --timeout 1800
```

Result counts used below: `correct=False` unless noted. `F3` passed 3/4; `O3`, `A13`, `UK6`, and `DISJ_OJ1` were mixed. In the post-comparator-fix run, `UK8` passed and `UK3` was still killed by the runner's memory cap.

## Current unresolved/false queries

| Query | Actual reason from rerun | Same projection equation issue? |
|---|---|---|
| `O3` | **Intermittent** (false twice, true once). False runs collapse the `FULL OUTER JOIN` to an inner join, use `c_custkey as key` instead of `o_custkey`, and add `o_clerk asc, c_name asc` before `LIMIT 35`. | No |
| `oj_bug` | False 3/3. Extracted query replaces `c_mktsegment` with the literal `'BUILDING  ' as c_mktsegment` and adds a spurious `Order By c_mktsegment asc`. A direct SQL row-multiset comparison of the emitted SQL against the original returned zero differences, so the remaining failure appears to be in comparator/materialization of the literal/char type rather than missing rows. | No |
| `F16` | `AVG` and `GROUP BY` are lost: emits raw `2*o_totalprice + 35.9 as total_price`; `c_acctbal` becomes the literal `2338.46`; the `c_nationkey IN (...)` filter is over-approximated as `(c_nationkey between 3 and 11 OR c_acctbal between 1000.01 and 6999.99)`. | No |
| `A10` | `COUNT(*)` extraction failed: emits `Select l_shipmode,  as count` with no aggregate and no `GROUP BY`. Consistent with the earlier empty-probe grouping failure. | No |
| `A13` | **Intermittent** (false, true, false). False runs add two spurious lower bounds — `l_receiptdate >= '1993-08-08'` and `l_receiptdate >= '1993-08-24'` — that are not in the original query and filter out valid rows. | No |
| `UK6` | **Intermittent** (false, true, false). False runs emit the same six `UNION ALL` arms in a different order. The first arm determines the output column type (`character varying` in the original ordering, `character` in the extracted ordering); an `EXCEPT ALL` check showed 796,480 row differences from char padding/trailing-space handling. Comparator now canonicalizes both sides to trimmed text; rerun needed to confirm removal. | No |
| `UK3` | **Memory kill**, not an extraction mismatch. `comparator_fix` run: `status=memkill`, `wall=25.75s`, `-9`. Native restores of `lineitem`, `part`, and `partsupp` all logged `index=0.000s`; the runner killed the process while a three-table join for `Select ps_comment as r_name, ps_supplycost as r_regionkey ...` was executing during NEP probing, before the final comparator ran. | No |
| `DISJ_OJ1` | **Intermittent** (false, true, true, false). False runs collapse the `LEFT OUTER JOIN` to an inner join and project `o_custkey as c_custkey`; true runs preserve the left join and `c_custkey`. | No |
| `DISJ_UN3` | The second `UNION ALL` arm projects the literal `'FRANCE' as c_name` instead of `n_name`, so the `FRANCE`/`GERMANY` rows are collapsed into one label. It also emits a stray ORDER BY inside that arm. | No |
| `N9` | Both negative string predicates are dropped: `ps_comment <> 'dependencies'` and `ps_comment <> 'hello world regular mina dependencies'`. `n_name` is emitted as the padded literal `'ARGENTINA                '`. | No |
| `U8` | The two `UNION ALL` arms are swapped, and the first arm gains an extra `order_id desc` tie-breaker. With `LIMIT 10`, that changes which rows survive. | No |
| `MQ3` | Projection emits `l_extendedprice*(1 - l_discount) - 0.21 as revenue` with no `SUM`. The spurious constant also makes the aggregate probe predict the wrong sum, so aggregation is never recognized. | No — constant-only projection regression |
| `MQ5` | Same class: emits `l_extendedprice*(1 - l_discount) + 1.21 as revenue` with no `SUM`; extra `n_name asc` ORDER BY key. | No — constant-only projection regression |
| `MQ10` | Same class: emits `l_extendedprice*(1 - l_discount) + 0.42 as revenue` with no `SUM`; several extra ORDER BY tie-breakers. | No — constant-only projection regression |
| `MQ11` | Same class: emits `ps_availqty*ps_supplycost - 0.01 as value` with no `SUM`; extra `ps_comment asc` ORDER BY key and warning `Projected attribute in place 2 in extracted query is not extracted correctly.` | No — constant-only projection regression |
| `F12` | The three-way OR is collapsed to `l_quantity <= 42.00 AND l_quantity <= 9.99`, effectively keeping only `l_quantity < 10` and dropping the `24..42` and `>= 50` branches. The older QSG `ValueError` note is stale for this rerun. | No |
| `F17` | Projection emits `Sum(c_acctbal + 3.54*o_totalprice - 0.01)` — the extra `- 0.01` is spurious. Numeric boundaries shift (`>= 5001`, `<= 6999.99`, `>= 1000.01`), the `n_nationkey IN (...)` list becomes `between 1 and 10`, and the projection warning fires. | No — constant-only projection regression |
| `N8` | `SUM` is lost: emits `ps_availqty*ps_supplycost - 1.15 as value`. It also drops `ps_comment NOT LIKE '%regular%dependencies%'` and `s_acctbal <> 2177.90`, adds `ps_comment asc`, and warns that projected attribute 2 is wrong. | No — constant-only projection regression |
| `Alaap` | Projection solver produces a badly wrong expression: `-0.01*l_discount*(125*l_extendedprice + 11) + 0.92*l_extendedprice - 0.76*l_quantity + 206.88 as revenue`, with no `SUM`. Adds a spurious `c_mktsegment asc` ORDER BY key and warns that projected attribute 2 is wrong. | No — constant-only projection regression |

## Fixed / historical issues to avoid confusing with current failures

| Query/group | Historical issue | Current interpretation |
|---|---|---|
| `F3` | Duplicate projection equations caused `numpy.linalg.LinAlgError: Singular matrix`; later reruns still showed an inner join replacing the `customer`/`orders` `LEFT OUTER JOIN`. | Projection fixed; passed 3 of 4 current reruns. Removed from the active false list, but the outer-join path can still be intermittent. |
| `UK6` | Reordered `UNION ALL` arms changed the first column's type/typmod, so char padding made equal values look different to the result comparator. | Comparator fix applied: both result sides are materialized with every projected value cast to text and surrounding whitespace trimmed. Not rerun yet, so it remains in the active table. |
| `UK8` | Same arm-order/type/typmod mismatch as `UK6`; false runs showed 902,543 `EXCEPT ALL` row differences despite identical row counts. | Removed after the comparator fix: rerun `comparator_fix` passed with `correct=True` (`wall=85.59s`, `minimizer=hybrid`). Targeted SQL also gives equal hashes and zero `EXCEPT ALL` differences. |
| `A7` | Original projection failure: `Why null result? Trouble!!!` → `Cannot find projected attributes`. | Fixed. Extracts `Avg(2*o_totalprice + 1)` and is correct. |
| `A8` | Original projection failure class; projection/aggregation now extracts `Sum(c_acctbal + 2*o_totalprice)`. | Removed: remaining mismatch was only spurious `n_name asc` in ORDER BY. |
| `MQ4` | Extra secondary ORDER BY/LIMIT sort key changed which 10 rows survived. | Removed: only spurious ORDER BY/LIMIT issue. |
| `TPCH_Q12`, `TPCH_Q14` | Contained SQL `CASE` expressions, outside the supported domain. | Removed from workload and unresolved list. String literals such as `'SM CASE'` were left alone. |
| `F10` | Pathological case. | Removed from workload and unresolved list. |
| ~15 half-baked queries | ORDER BY probe passed tuples from `hash_aggregate_probe_settings()` into `execute_sql()`, causing `AttributeError: 'tuple' object has no attribute 'replace'`. | Fixed; the current helper returns SQL strings. Not the same projection issue. |
| `NEP4` | Single-attribute NEP probe limitation. | Historical, separate from projection equations. |
| `TPCH_Q16` | Previously discussed as a separate issue after LIMIT fix work. | Not in the current false list. |
| `TPCH_Q9`, `TPCH_Q11`, `TPCH_Q13` | Previously removed nested-query cases. | Not in the current false list. |

## Projection equation issue checklist

When deciding whether a query belongs in the F3/A7/A8 projection-equation category, look for one of these signatures:

- `numpy.linalg.LinAlgError: Singular matrix`
- duplicate or linearly dependent coefficient rows in projection logs, e.g. `[[1007, 1], [1007, 1]]`
- `Why null result? Trouble!!!` followed by `Cannot find projected attributes`
- failure while solving projection coefficients before aggregation extraction
- coefficients built by repeated dmin values without independent observed result equations

Do **not** classify a query as this issue solely because it is `correct=False`, has a bad ORDER BY/LIMIT/WHERE/GROUP BY output, or has a spurious non-zero constant. The MQ/N8/F17/Alaap constant problem is a separate projection regression: the aggregate detector correctly refuses to match a probe prediction polluted by the invented constant.

## Maintenance

After any future full or partial rerun:

1. Update the false-query list from `timings_per_query.csv`.
2. Move fixed queries out of the current table into “Fixed / historical issues”.
3. Record whether a query was stable or intermittent, and keep exact SQL/error examples where available.
4. Drop the `unmasque` verification schema after the run so the database is left clean.
