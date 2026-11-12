# PRISM

PRISM deterministically extracts a hidden SQL query `Q_H` from an initial database `D_I`. It is `unmasque` core extended with the notion of FIT-ness (fully instantiated results), plus the full implementation of the PRISM extractors.

## Contents

1. [Quick Start](#quick-start)
2. [Setup](#setup)
3. [Configuration](#configuration)
4. [Running PRISM](#running-prism)
5. [Project Layout](#project-layout)
6. [Extractable Query Class](#extractable-query-class)
7. [Observability Conditions](#observability-conditions)

---

## Quick Start

1. Install PostgreSQL and load TPC-H data ([Database Setup](#1-database-setup)). For the JOB database, use the `JOB` branch of this repo instead ([details](#13-using-the-job-database-alternative-to-tpc-h)).
2. Install Python 3.8+ and the dependencies ([Python Environment](#2-python-environment)).
3. Edit `mysite/config.ini` with your database credentials.
4. From inside `mysite`, run:

   ```bash
   python -m unmasque.src.main_cmd <qid>
   ```

---

## Setup

### 1. Database Setup

#### 1.1 Install PostgreSQL

Download and install the distribution for your platform: <https://www.postgresql.org/download/>

#### 1.2 Load TPC-H Data

Choose **one** of the three options.

**Option A: Sample data (fastest)**

- Download the TPC-H 100MB (sf=0.1) data: [tpch_tiny.zip](https://github.com/ahanapradhan/UnionExtraction/blob/master/mysite/unmasque/test/experiments/data/tpch_tiny.zip)
- Update `load.sql` in the extracted folder with the location of your `.csv` data files.

**Option B: Generate data with DBGEN**

1. *Obtain DBGEN*
   1. Open the [TPC specifications page](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp).
   2. In the `Active Benchmarks` table (first table), follow the `Download TPC-H_Tools_v3.0.1.zip` link. It redirects to the `TPC-H Tools Download` page.
   3. Enter your details and click `download`. A download link is emailed to you.
   4. Download and unzip the file. The extracted contents must include the `dbgen` folder.
2. *Load into PostgreSQL*
   1. Download [`tpch-pgsql`](https://github.com/ahanapradhan/tpch-pgsql).
   2. Follow its README to prepare and load the data.
   3. If you get an error that `malloc.h` is not found, open the file named in the error (inside the `dbgen` folder) and replace `malloc.h` with `stdlib.h`.

**Option C: DuckDB**

Load TPC-H using the DuckDB extension: <https://duckdb.org/docs/extensions/tpch.html>

#### 1.3 Using the JOB Database (alternative to TPC-H)

To run PRISM on the JOB (Join Order Benchmark) database instead of TPC-H:

1. Load the JOB database into PostgreSQL.
2. In the [PRISM repository](https://github.com/ahanapradhan/PRISM), switch to the **`JOB` branch**. It contains the config files for the JOB database (for example, the schema's key details in place of the TPC-H `pkfkrelations.csv`, and a matching `config.ini`).
3. Use those config files in `mysite` in place of the default ones, and set your database credentials in `config.ini`.

```bash
git checkout JOB
```

See [Configuration](#configuration) for what each file controls.

### 2. Python Environment

Install an IDE (optional), e.g. [PyCharm Community Edition](https://www.jetbrains.com/pycharm/download/). Any other IDE is fine.

**Requirements**

| Package | Version | Needed for |
|---|---|---|
| Python | 3.8.0 or above | Everything |
| `sympy` | 1.4 | Everything |
| `psycopg2` | 2.9.3 | Everything |
| `numpy` | 1.22.4 | Everything |
| `django` | 4.2.4 | GUI only (**optional**, no longer maintained) |

```bash
# Required for running from the terminal or an IDE
pip install sympy==1.4 psycopg2==2.9.3 numpy==1.22.4

# Only if you want the (unmaintained) Django GUI
pip install django==4.2.4
```

> Django is **not** required to run PRISM from the terminal.

---

## Configuration

Two files in the `mysite` directory control the setup:

| File | Purpose |
|---|---|
| `pkfkrelations.csv` | Primary/foreign key details for the TPC-H schema. Change it if you use a different schema. |
| `config.ini` | Database credentials and feature flags. |

> For the JOB database, the ready-made config files are in the `JOB` branch of the repo ([see Database Setup](#13-using-the-job-database-alternative-to-tpc-h)).

### `config.ini` sections

| Section | What to set |
|---|---|
| `database` | Your database credentials. |
| `support` | Support file name. The file must be in the same directory as `config.ini`. |
| `logging` | Log level: `DEBUG` (developer mode), `INFO`, or `ERROR`. |
| `feature` | Flags for advanced features: `UNION`, `OUTER JOIN`, `<>` / `!=` in arithmetic filter predicates, and `IN`. |
| `options` | Extractor options. E.g. the maximum `LIMIT` value is 1000; set `limit=value` to raise it. |

---

## Running PRISM

The entry point is `mysite/unmasque/src/main_cmd.py`. It ships with one default input query and a workload list, each entry identified by a `qid`. Sample queries are in the `test.util` package (`queries.py`). To test more queries, add them to the workload.

### Command line

From the `mysite` directory:

```bash
python -m unmasque.src.main_cmd <qid>
```

### IDE

Run the `main` function in `main_cmd.py`.

> `main_cmd.py` uses relative imports. If this causes import errors when running from an IDE, change them to absolute imports.

### GUI (no longer maintained)

> The Django-based UI is **no longer maintained** and may not work with current code. Prefer the command line or an IDE. Django is not needed for those.

If you still want to try it, install Django (see [Python Environment](#2-python-environment)), then from inside the `unmasque` folder:

```bash
python3 manage.py runserver
```

Once the server is up on port 8080, open <http://localhost:8080/unmasque/>.

---

## Project Layout

```
mysite/
├── config.ini            # DB credentials, feature flags
├── pkfkrelations.csv     # Key details for the schema
└── unmasque/
    ├── src/              # PRISM code: unmasque core + FIT-ness + all extractors
    └── test/             # (obsolete) unit tests for each extractor module
```

---

## Extractable Query Class

PRISM can extract queries that conform to the following grammar.

```ebnf
query      ::= flat | branch (union_op branch)+
branch     ::= "(" flat ")"
union_op   ::= UNION ALL

flat       ::= SELECT list(item) FROM source
               [WHERE condition] [GROUP BY list(column)]
               [ORDER BY list(order_item)] [LIMIT int]

item       ::= expression [AS identifier]
expression ::= scalar | aggregate "(" scalar ")" | COUNT(*)
aggregate  ::= SUM | AVG | MIN | MAX | COUNT
scalar     ::= column | constant | "(" scalar ")"
             | scalar arithmetic scalar
arithmetic ::= "+" | "-" | "*" | "/"

source     ::= list(table) | table (join_op table ON condition)+
join_op    ::= JOIN | INNER JOIN | LEFT OUTER JOIN
             | RIGHT OUTER JOIN | FULL OUTER JOIN

condition  ::= conjunct (AND conjunct)*
conjunct   ::= atom (OR atom)* | column IN "(" list(constant) ")"
             | column <> constant | column NOT LIKE string
atom       ::= column comparison (column | constant)
             | column LIKE string
comparison ::= "=" | "<" | "<=" | ">" | ">="

order_item ::= (identifier | column) [ASC | DESC]
column     ::= identifier ["." identifier]
constant   ::= number | date | string
```

> `HAVING` support is added within the flat scope. It is not integrated with the newer PRISM features.

---

## Observability Conditions

PRISM can deterministically extract `Q_H` from `D_I` only if the following hold.

### General (always apply)

| # | Condition |
|---|---|
| 1 | `D_I` is NULL-free (if not, a NULL-free sample can be constructed from it). |
| 2 | `Q_H` produces a populated result on `D_I`. With outer joins or unions, the result must be a **FIT-result**, i.e. contain at least one tuple with no NULL values. |
| 3 | No table is repeated in the `FROM` clause (no self-joins). |
| 4 | `Q_H` is conjunctive, extended to a conjunction of clauses, each a disjunction of atomic predicates. |
| 5 | `Q_H` is not a pure count query. |
