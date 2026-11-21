#!/usr/bin/env python3
"""Generate a synthetic 30-table schema + union queries with growing |AUX|.

|AUX| = number of distinct tables appearing across all subqueries of the union.
Number of subqueries is fixed (N_SUB); tables are split disjointly among them.
"""
import random
from pathlib import Path

N_TABLES = 30
N_SUB = 3
AUX_SIZES = [10, 15, 20, 25, 30]
MIN_ROWS, MAX_ROWS = 10, 100
SEED = 42

OUT = Path(".")
(OUT / "queries").mkdir(exist_ok=True)


def t(i):
    return f"t{i:02d}"


def gen_schema_and_data():
    rnd = random.Random(SEED)
    ddl, dml = [], []
    for i in range(1, N_TABLES + 1):
        p = t(i)
        ddl.append(
            f"CREATE TABLE {p} (\n"
            f"    {p}_key  INTEGER PRIMARY KEY,   -- shared join domain\n"
            f"    {p}_grp  INTEGER,\n"
            f"    {p}_val  NUMERIC(8,2),\n"
            f"    {p}_name VARCHAR(20),\n"
            f"    {p}_date DATE\n"
            f");"
        )
        n = rnd.randint(MIN_ROWS, MAX_ROWS)
        # keys are 1..n in every table -> any two tables join on >= MIN_ROWS keys
        for k in range(1, n + 1):
            grp = rnd.randint(1, 5)
            val = round(rnd.uniform(0, 100), 2)
            name = f"{p}_name_{k}"
            d = f"20{rnd.randint(15, 24)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
            dml.append(
                f"INSERT INTO {p} VALUES ({k}, {grp}, {val}, '{name}', '{d}');"
            )
    (OUT / "schema_data.sql").write_text("\n\n".join(ddl) + "\n\n" + "\n".join(dml) + "\n")


def split(aux, parts):
    base, extra = divmod(aux, parts)
    sizes = [base + (1 if j < extra else 0) for j in range(parts)]
    out, start = [], 1
    for s in sizes:
        out.append(list(range(start, start + s)))
        start += s
    return out


# one extractable filter per subquery, on the subquery's first table
FILTERS = [
    lambda p: f"{p}_val < 40",
    lambda p: f"{p}_grp <= 2",
    lambda p: f"{p}_val > 60",
]


def subquery(tabs, j):
    first = t(tabs[0])
    sel = f"SELECT {first}_key AS k, {first}_name AS nm"
    frm = "FROM " + ", ".join(t(i) for i in tabs)
    conds = [f"{t(a)}_key = {t(b)}_key" for a, b in zip(tabs, tabs[1:])]
    conds.append(FILTERS[j % len(FILTERS)](first))
    return f"({sel}\n {frm}\n WHERE " + "\n   AND ".join(conds) + ")"


def gen_queries():
    for aux in AUX_SIZES:
        groups = split(aux, N_SUB)
        body = "\nUNION ALL\n".join(subquery(g, j) for j, g in enumerate(groups)) + ";\n"
        header = (
            f"-- |AUX| = {aux} tables, {N_SUB} subqueries, "
            f"tables per subquery: {[len(g) for g in groups]}\n"
        )
        (OUT / "queries" / f"union_aux{aux:02d}.sql").write_text(header + body)


if __name__ == "__main__":
    gen_schema_and_data()
    gen_queries()
    print("done")