#!/usr/bin/env bash
# run_usecase.sh -- one-shot setup + run for the PRISM ORM use case, v7
# (macOS, Homebrew, existing Postgres + TPC-H, all 8 tables incl. lineitem and region).
#
# Q_full (the single SQL the application is equivalent to):
#
#  (SELECT c_name AS entity_name, n_name AS country, o_totalprice AS price
#   FROM customer RIGHT OUTER JOIN orders ON c_custkey = o_custkey
#                 AND c_acctbal >= o_totalprice AND c_acctbal >= 9000
#        LEFT OUTER JOIN nation ON c_nationkey = n_nationkey
#   WHERE o_totalprice <= 15000
#   GROUP BY n_name, c_name, o_totalprice
#   ORDER BY price, country, entity_name LIMIT 10)
#  UNION ALL
#  (SELECT s_name AS entity_name, n_name AS country, avg(l_extendedprice*(1 - l_discount)) AS price
#   FROM supplier, lineitem, orders, nation, region
#   WHERE l_suppkey = s_suppkey AND l_orderkey = o_orderkey
#     AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey
#     AND (l_shipmode = 'AIR' OR l_shipmode = 'TRUCK') AND r_name <> 'EUROPE'
#     AND o_totalprice >= s_acctbal AND 15000 >= o_totalprice
#   GROUP BY n_name, s_name
#   ORDER BY price DESC, country DESC, entity_name LIMIT 20)
#
# Design (v7)
#   * Four templated extract functions hq_1..hq_4. NONE of them is a plain table projection: each pushes a join,
#     an outer join, a DISTINCT, a computed flag or an aggregate into the database, so a function cannot be
#     mapped to a table by looking at its row count or width:
#       hq_1(region)            nation LEFT JOIN region, plus a computed in-scope flag          (25 rows)
#       hq_2(min_acctbal)       customer LEFT JOIN nation, filtered on balance                  (~9% of customers)
#       hq_3(price_cap)         DISTINCT (o_custkey, o_totalprice) of cheap orders              (small)
#       hq_4(mode1,mode2,cap)   supplier JOIN lineitem JOIN orders, OR on ship mode, supplier-balance vs
#                               order-price comparison, AVG per (nationkey, supplier)           (<= #suppliers rows)
#     lineitem (6M rows) and the AVG never leave the database.
#   * All constants (segments of the old design are gone; now 9000, 15000, AIR, TRUCK, EUROPE) are JDBC BIND PARAMETERS:
#     the Hibernate log shows only  select * from hq_4(?1, ?2, ?3)  and EXPLAIN shows only "Function Scan".
#   * Java keeps the rest of the logic, hidden from the log: the RIGHT OUTER JOIN with its attribute-vs-attribute
#     condition, NULL-extension, grouping, region exclusion, ordering, LIMITs and the UNION ALL.
#   * The statements are issued interleaved (hq_1, hq_2, hq_4, hq_3), so the log does not show two sections.
#   * The report goes to its own file (REPORT_OUT): log lines can never leak into the application output.
#   * A leak check verifies that no business constant appears in the SQL log or the plans.
#
# Usage:   chmod +x run_usecase.sh && PGUSER=postgres PGPASSWORD=postgres PGDATABASE=tpch ./run_usecase.sh
# Config (all optional, via env):
#   PGDATABASE (default tpch)  PGHOST (localhost)  PGPORT (5432)  PGUSER (your macOS user)  PGPASSWORD (empty)
#   PROJECT_DIR (default ~/prism-usecase)       GEN_ONLY=1 -> only write project files, then exit
#
# Produces in $PROJECT_DIR/out/ :
#   result_java.txt   the application's output (tab separated, no header, NULL for SQL NULL)
#   result_sql.txt    the same report computed by the single SQL (Q_full), for the equivalence check
#   run.log / sql_log.txt   what Hibernate sent to the database (SHOW_SQL)
#   plans.txt         real EXPLAIN (ANALYZE) of the statements in the log
#   transfer.txt      rows/bytes pulled by the application vs plain scans of the underlying tables
#   leak_check.txt    proof that constants are absent from the log and the plans
#   llm_input.txt     self-contained prompt for an LLM: task + DB schema/counts/samples + app output + log + plans
#   check_candidate.sh  run an LLM's candidate SQL and compare with result_java.txt
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/prism-usecase}"
export PGDATABASE="${PGDATABASE:-tpch}"
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-$(whoami)}"
export PGPASSWORD="${PGPASSWORD:-}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Harness-only helpers (never shown to the LLM): the real call with literals, and the shape the application logs.
call_expr() { case "$1" in
  1) echo "hq_1('EUROPE')";;
  2) echo "hq_2(9000)";;
  3) echo "hq_3(15000)";;
  4) echo "hq_4('AIR','TRUCK',15000)";;
esac; }
shape_of() { case "$1" in
  1) echo "hq_1(?)";;
  2) echo "hq_2(?)";;
  3) echo "hq_3(?)";;
  4) echo "hq_4(?, ?, ?)";;
esac; }

# ---------------------------------------------------------------- 1. project files
say "Writing project files to $PROJECT_DIR"
mkdir -p "$PROJECT_DIR/src/main/java" "$PROJECT_DIR/out"

cat > "$PROJECT_DIR/pom.xml" <<'POM_EOF'
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>prism.usecase</groupId>
  <artifactId>account-exposure</artifactId>
  <version>1.0</version>

  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <exec.mainClass>AccountExposureReport</exec.mainClass>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.hibernate.orm</groupId>
      <artifactId>hibernate-core</artifactId>
      <version>6.4.4.Final</version>
    </dependency>
    <dependency>
      <groupId>org.postgresql</groupId>
      <artifactId>postgresql</artifactId>
      <version>42.7.3</version>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.codehaus.mojo</groupId>
        <artifactId>exec-maven-plugin</artifactId>
        <version>3.1.0</version>
        <configuration>
          <mainClass>${exec.mainClass}</mainClass>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
POM_EOF

cat > "$PROJECT_DIR/src/main/java/AccountExposureReport.java" <<'JAVA_EOF'
// AccountExposureReport.java  --  PRISM use case v7.
// Hibernate 6 + PostgreSQL, TPC-H schema. Constants are bind parameters, so the Hibernate log never shows them.
//
// Observable behaviour (the report file, as a function of the database) is exactly this ONE SQL (Q_full):
//
//  (SELECT c_name AS entity_name, n_name AS country, o_totalprice AS price
//   FROM customer RIGHT OUTER JOIN orders ON c_custkey = o_custkey
//                 AND c_acctbal >= o_totalprice AND c_acctbal >= 9000
//        LEFT OUTER JOIN nation ON c_nationkey = n_nationkey
//   WHERE o_totalprice <= 15000
//   GROUP BY n_name, c_name, o_totalprice
//   ORDER BY price, country, entity_name LIMIT 10)
//  UNION ALL
//  (SELECT s_name AS entity_name, n_name AS country, avg(l_extendedprice*(1 - l_discount)) AS price
//   FROM supplier, lineitem, orders, nation, region
//   WHERE l_suppkey = s_suppkey AND l_orderkey = o_orderkey
//     AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey
//     AND (l_shipmode = 'AIR' OR l_shipmode = 'TRUCK') AND r_name <> 'EUROPE'
//     AND o_totalprice >= s_acctbal AND 15000 >= o_totalprice
//   GROUP BY n_name, s_name
//   ORDER BY price DESC, country DESC, entity_name LIMIT 20)
//
// Division of labour (see db_objects.sql for the pushed-down parts):
//   hq_1  nation LEFT JOIN region + in-scope flag            hq_2  customer LEFT JOIN nation, balance filter
//   hq_3  DISTINCT (o_custkey, o_totalprice) of cheap orders  hq_4  supplier JOIN lineitem JOIN orders, AVG per supplier
//   Java: RIGHT OUTER JOIN with the balance-vs-price condition (NULL-extension), GROUP BY, region exclusion,
//         ORDER BY / LIMIT of both branches and the UNION ALL.

import org.hibernate.Session;
import org.hibernate.SessionFactory;
import org.hibernate.cfg.Configuration;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.function.Consumer;
import java.util.stream.Stream;

public class AccountExposureReport {

    // ---- business constants: only ever sent as bind parameters, never concatenated into SQL ----
    static final BigDecimal MIN_ACCTBAL = new BigDecimal("9000");      // -> hq_2
    static final BigDecimal PRICE_CAP   = new BigDecimal("15000");     // -> hq_3, hq_4
    static final String SHIP_A = "AIR", SHIP_B = "TRUCK";              // -> hq_4
    static final String EXCLUDED_REGION = "EUROPE";                    // -> hq_1

    record Row(String entity, String country, BigDecimal amount) {}
    record Cust(String name, String country, BigDecimal bal) {}
    record Nat(String name, boolean inScope) {}

    static long id(Object o) { return ((Number) o).longValue(); }

    /** One bulk statement per call: select * from fn(?1, ?2, ...), streamed with a cursor.
     *  Constants go in as bind parameters. Single-column results would come back as a bare value, so wrap them. */
    static void scan(Session s, String fn, Consumer<Object[]> each, Object... params) {
        StringBuilder sql = new StringBuilder("select * from ").append(fn).append("(");
        for (int i = 0; i < params.length; i++) sql.append(i == 0 ? "" : ", ").append("?").append(i + 1);
        sql.append(")");
        org.hibernate.query.NativeQuery<?> q = s.createNativeQuery(sql.toString());
        for (int i = 0; i < params.length; i++) q.setParameter(i + 1, params[i]);
        q.setFetchSize(10000);
        try (Stream<?> st = q.stream()) {
            st.forEach(o -> each.accept(o instanceof Object[] a ? a : new Object[]{o}));
        }
    }

    static List<Row> buildReport(Session s) {
        // Statement order is interleaved on purpose: hq_1, hq_2, hq_4, hq_3.

        Map<Long, Nat> nat = new HashMap<>();                                // nationkey -> (name, region not excluded)
        scan(s, "hq_1", r -> {
            if (r[0] != null) nat.put(id(r[0]), new Nat((String) r[1], Boolean.TRUE.equals(r[2])));
        }, EXCLUDED_REGION);

        Map<Long, Cust> cust = new HashMap<>();                              // custkey -> customers with a high balance
        scan(s, "hq_2", r -> {
            if (r[0] != null) cust.put(id(r[0]), new Cust((String) r[1], (String) r[2], (BigDecimal) r[3]));
        }, MIN_ACCTBAL);

        // ---- branch 2: per-supplier AVG arrives from the DB; join to nation/region locally, ORDER BY ... LIMIT 20 ----
        List<Row> part2 = new ArrayList<>();
        Set<List<String>> groups = new HashSet<>();                          // GROUP BY (n_name, s_name)
        scan(s, "hq_4", r -> {
            if (r[0] == null || r[2] == null) return;
            Nat n = nat.get(id(r[0]));                                       // inner join nation + region predicate
            if (n == null || !n.inScope()) return;
            if (!groups.add(Arrays.asList(n.name(), (String) r[1])))
                throw new IllegalStateException("duplicate (nation, supplier name): per-supplier AVG cannot be merged");
            part2.add(new Row((String) r[1], n.name(), (BigDecimal) r[2]));
        }, SHIP_A, SHIP_B, PRICE_CAP);

        // ---- branch 1: customer RIGHT OUTER JOIN orders (theta condition) LEFT JOIN nation, GROUP BY ----
        Set<Row> custRows = new LinkedHashSet<>();                           // acts as GROUP BY (name, country, price)
        scan(s, "hq_3", r -> {
            if (r[1] == null) return;
            BigDecimal price = (BigDecimal) r[1];
            Cust c = r[0] == null ? null : cust.get(id(r[0]));
            if (c != null && c.bal().compareTo(price) >= 0)                  // c_acctbal >= o_totalprice (balance >= 9000 is in hq_2)
                custRows.add(new Row(c.name(), c.country(), price));
            else
                custRows.add(new Row(null, null, price));                    // preserved side of the RIGHT JOIN, NULL-extended
        }, PRICE_CAP);

        List<Row> part1 = new ArrayList<>(custRows);
        Comparator<Row> c1 = Comparator
                .<Row, BigDecimal>comparing(Row::amount)
                .thenComparing(Row::country, Comparator.nullsLast(Comparator.<String>naturalOrder()))
                .thenComparing(Row::entity, Comparator.nullsLast(Comparator.<String>naturalOrder()));
        part1.sort(c1);
        List<Row> top1 = new ArrayList<>(part1.subList(0, Math.min(10, part1.size())));

        Comparator<Row> c2 = Comparator
                .<Row, BigDecimal>comparing(Row::amount, Comparator.<BigDecimal>reverseOrder())
                .thenComparing(Row::country, Comparator.<String>reverseOrder())
                .thenComparing(Row::entity);
        part2.sort(c2);
        List<Row> top2 = new ArrayList<>(part2.subList(0, Math.min(20, part2.size())));

        // ---- UNION ALL, in the application ----
        List<Row> all = new ArrayList<>(top1);
        all.addAll(top2);
        return all;
    }

    static String cell(Object v) { return v == null ? "NULL" : v instanceof BigDecimal b ? b.toPlainString() : v.toString(); }

    public static void main(String[] args) {
        Configuration cfg = new Configuration()                              // no entity mappings: bulk native calls only
                .setProperty("hibernate.connection.url", System.getenv().getOrDefault("DB_URL", "jdbc:postgresql://localhost/tpch"))
                .setProperty("hibernate.connection.username", System.getenv().getOrDefault("DB_USER", "postgres"))
                .setProperty("hibernate.connection.password", System.getenv().getOrDefault("DB_PASS", "postgres"))
                // SHOW_SQL=true prints the "log" an analyst would get (placeholders only, no bind values)
                .setProperty("hibernate.show_sql", System.getenv().getOrDefault("SHOW_SQL", "false"));
        List<Row> report;
        try (SessionFactory sf = cfg.buildSessionFactory(); Session s = sf.openSession()) {
            s.beginTransaction();                                            // needed for cursor streaming in PgJDBC
            report = buildReport(s);
            s.getTransaction().commit();
        }
        StringBuilder sb = new StringBuilder();
        for (Row r : report)
            sb.append(cell(r.entity())).append('\t').append(cell(r.country())).append('\t').append(cell(r.amount())).append('\n');
        String outPath = System.getenv("REPORT_OUT");                        // report goes to its own file: no log mixing
        if (outPath == null || outPath.isEmpty()) System.out.print(sb);
        else {
            try { Files.writeString(Path.of(outPath), sb.toString(), StandardCharsets.UTF_8); }
            catch (IOException e) { throw new UncheckedIOException(e); }
        }
    }
}
JAVA_EOF

cat > "$PROJECT_DIR/db_objects.sql" <<'DBSQL_EOF'
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
DBSQL_EOF

[ "${GEN_ONLY:-0}" = "1" ] && { echo "GEN_ONLY set: files written, exiting."; exit 0; }

# ---------------------------------------------------------------- 2. locate psql
say "Locating psql"
if ! command -v psql >/dev/null 2>&1; then
  for d in /opt/homebrew/opt/postgresql@17/bin /usr/local/opt/postgresql@17/bin \
           /opt/homebrew/bin /usr/local/bin /Applications/Postgres.app/Contents/Versions/17/bin \
           /Applications/Postgres.app/Contents/Versions/latest/bin; do
    [ -x "$d/psql" ] && { export PATH="$d:$PATH"; break; }
  done
fi
command -v psql >/dev/null 2>&1 || die "psql not found. Put your Postgres bin directory on PATH and re-run."
psql --version

# ---------------------------------------------------------------- 3. check database
say "Checking database '$PGDATABASE' on $PGHOST:$PGPORT as $PGUSER"
if ! psql -Atc "select 1" >/dev/null 2>&1; then
  echo "Cannot connect. Databases visible to you:" >&2
  psql -d postgres -Atc "select datname from pg_database where not datistemplate" >&2 || true
  die "Set PGDATABASE/PGUSER/PGPASSWORD/PGHOST/PGPORT and re-run."
fi
for t in nation region supplier customer orders lineitem partsupp part; do
  n=$(psql -Atc "select count(*) from $t" 2>/dev/null) || die "table '$t' missing or unreadable in $PGDATABASE"
  printf '  %-9s %s rows\n' "$t" "$n"
  [ "$n" -gt 0 ] || die "table $t is empty"
done
echo "Data present for the observability conditions (informational):"
psql -Atc "select '  orders with o_totalprice <= 15000: '||count(*) from orders where o_totalprice <= 15000"
psql -Atc "select '  customers with c_acctbal >= 9000: '||count(*) from customer where c_acctbal >= 9000"
psql -Atc "select '  nations in region EUROPE: '||count(*) from nation n join region r on n_regionkey=r_regionkey where trim(r_name)='EUROPE'"

# ---------------------------------------------------------------- 4. install the DB-side objects
say "Installing templated DB extract functions hq_1()..hq_4()"
psql -q -v ON_ERROR_STOP=1 -f "$PROJECT_DIR/db_objects.sql" || die "could not create the functions (need CREATE privilege on schema public)"
for k in 1 2 3 4; do printf '  %s returns %s rows\n' "$(shape_of $k)" "$(psql -Atc "select count(*) from $(call_expr $k)")"; done

# ---------------------------------------------------------------- 5. Java + Maven
say "Checking Java (>=17) and Maven"
# Hibernate 6.4's bundled ByteBuddy breaks on very new JDKs, so accept only 17..23.
java_ok() { command -v java >/dev/null 2>&1 && v=$(java -version 2>&1 | head -1 | sed -E 's/.*"([0-9]+)[.".].*/\1/') && [ "$v" -ge 17 ] && [ "$v" -le 23 ] 2>/dev/null; }
if ! java_ok; then
  if [ -x /usr/libexec/java_home ] && JH=$(/usr/libexec/java_home -v 21 2>/dev/null); then
    export JAVA_HOME="$JH"; export PATH="$JAVA_HOME/bin:$PATH"
  fi
fi
if ! java_ok; then
  command -v brew >/dev/null 2>&1 || die "Java 17+ not found and Homebrew missing (https://brew.sh)."
  brew list openjdk@21 >/dev/null 2>&1 || brew install openjdk@21
  export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
  export PATH="$JAVA_HOME/bin:$PATH"
fi
java -version 2>&1 | head -1
if ! command -v mvn >/dev/null 2>&1; then
  command -v brew >/dev/null 2>&1 || die "Maven not found and Homebrew missing."
  brew install maven
fi
mvn -v | head -1

# ---------------------------------------------------------------- 6. build + run
export DB_URL="jdbc:postgresql://${PGHOST}:${PGPORT}/${PGDATABASE}"
export DB_USER="$PGUSER"
export DB_PASS="${PGPASSWORD:-x}"      # ignored by Postgres under trust auth
OUT="$PROJECT_DIR/out"
cd "$PROJECT_DIR"
export MAVEN_OPTS="${MAVEN_OPTS:--Xmx2g}"

say "Building (first run downloads Hibernate from Maven Central)"
mvn -q -DskipTests compile 2>&1 | tail -n 30

say "Run 1: black-box mode (report written to its own file)"
rm -f "$OUT/result_java.txt" "$OUT/result_java_run2.txt"
REPORT_OUT="$OUT/result_java.txt" SHOW_SQL=false mvn -q exec:java > "$OUT/stdout_run1.txt" 2> "$OUT/stderr_run1.txt" \
  || { cat "$OUT/stdout_run1.txt" "$OUT/stderr_run1.txt" | tail -n 60; die "Java run failed (see above)"; }
[ -s "$OUT/result_java.txt" ] || die "Java run produced no report file"
wc -l < "$OUT/result_java.txt" | xargs echo "  result rows:"

say "Run 2: with Hibernate SQL logging"
REPORT_OUT="$OUT/result_java_run2.txt" SHOW_SQL=true mvn -q exec:java > "$OUT/run.log" 2> "$OUT/stderr_run2.txt" \
  || { cat "$OUT/run.log" "$OUT/stderr_run2.txt" | tail -n 60; die "logged run failed"; }
grep '^Hibernate:' "$OUT/run.log" > "$OUT/sql_log.txt" || true
STMTS=$(wc -l < "$OUT/sql_log.txt" | xargs)
echo "  SQL statements issued by Hibernate: $STMTS"
cmp -s "$OUT/result_java.txt" "$OUT/result_java_run2.txt" && echo "  run 2 report identical to run 1" || echo "  WARNING: run 2 report differs from run 1"

# ---------------------------------------------------------------- 7. equivalence vs Q_full
say "Equivalence check: Java report vs the single SQL (Q_full)"
# Q_full exactly as specified. Harness-only additions so psql output is byte-comparable with Java:
#   rtrim() strips char(n) padding; COLLATE "C" gives byte-wise string order like Java's String.compareTo.
psql -At -F $'\t' -P null=NULL > "$OUT/result_sql.txt" <<'SQL_EOF'
(SELECT rtrim(c_name) AS entity_name, rtrim(n_name) AS country, o_totalprice AS price
 FROM customer RIGHT OUTER JOIN orders ON c_custkey = o_custkey
               AND c_acctbal >= o_totalprice AND c_acctbal >= 9000
      LEFT OUTER JOIN nation ON c_nationkey = n_nationkey
 WHERE o_totalprice <= 15000
 GROUP BY n_name, c_name, o_totalprice
 ORDER BY o_totalprice, rtrim(n_name) COLLATE "C", rtrim(c_name) COLLATE "C" LIMIT 10)
UNION ALL
(SELECT rtrim(s_name), rtrim(n_name), avg(l_extendedprice*(1 - l_discount))
 FROM supplier, lineitem, orders, nation, region
 WHERE l_suppkey = s_suppkey AND l_orderkey = o_orderkey
   AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey
   AND (l_shipmode = 'AIR' OR l_shipmode = 'TRUCK') AND r_name <> 'EUROPE'
   AND o_totalprice >= s_acctbal AND 15000 >= o_totalprice
 GROUP BY n_name, s_name
 ORDER BY avg(l_extendedprice*(1 - l_discount)) DESC, rtrim(n_name) COLLATE "C" DESC, rtrim(s_name) COLLATE "C" LIMIT 20);
SQL_EOF
if diff -u "$OUT/result_sql.txt" "$OUT/result_java.txt" > "$OUT/diff.txt"; then
  VERDICT="PASS: Java report is identical to Q_full ($(wc -l < "$OUT/result_sql.txt" | xargs) rows)"
else
  VERDICT="FAIL: outputs differ, see $OUT/diff.txt"; head -n 30 "$OUT/diff.txt"
fi
echo "  $VERDICT"

# ---------------------------------------------------------------- 8. real plans of the logged statements
say "Real EXPLAIN (ANALYZE) of the statements in the log"
{
  echo "# The application sends these statements with bind parameters (see sql_log.txt); plans show only the wrapper function."
  for k in 1 2 3 4; do
    echo; echo "-- select * from $(shape_of $k)"
    psql -Atc "EXPLAIN (ANALYZE, BUFFERS) select * from $(call_expr $k)"
  done
} > "$OUT/plans.txt"
echo "  wrote $OUT/plans.txt"

# ---------------------------------------------------------------- 8a. leak check: constants must not be observable
say "Leak check: business constants must not appear in the SQL log or the plans"
LEAK_HITS="$OUT/leak_hits.txt"; : > "$LEAK_HITS"
grep -En '\b(AIR|TRUCK|EUROPE)\b' "$OUT/sql_log.txt" "$OUT/plans.txt" >> "$LEAK_HITS" || true
grep -En '\b(9000|15000)\b' "$OUT/sql_log.txt" >> "$LEAK_HITS" || true
if [ -s "$LEAK_HITS" ]; then
  LEAK="FAIL: constants visible in log/plans (see $LEAK_HITS)"; head -n 10 "$LEAK_HITS"
else
  LEAK="PASS: no business constant appears in sql_log.txt or plans.txt"; rm -f "$LEAK_HITS"
fi
echo "  $LEAK" | tee "$OUT/leak_check.txt"

# ---------------------------------------------------------------- 8b. how much data the application pulls
say "Data transferred to the application vs plain scans of the underlying tables"
{
  printf '%-7s %-10s %12s %12s %9s %14s %14s\n' stmt base_table rows_sent table_rows pct_rows approx_MB_sent table_MB
  tot_sent=0; tot_tab=0
  for pair in "1 nation" "2 customer" "3 orders" "4 lineitem"; do
    set -- $pair; k=$1; tb=$2
    sent=$(psql -Atc "select count(*) from $(call_expr $k)")
    rows=$(psql -Atc "select count(*) from $tb")
    sb=$(psql -Atc "select coalesce(sum(pg_column_size(h.*)),0) from $(call_expr $k) h")
    tbb=$(psql -Atc "select pg_relation_size('$tb')")
    pct=$(awk -v a="$sent" -v b="$rows" 'BEGIN{ if (b>0) printf "%.3f", 100*a/b; else print "0" }')
    printf '%-7s %-10s %12s %12s %8s%% %14.2f %14.2f\n' "hq_$k" "$tb" "$sent" "$rows" "$pct" "$(awk -v x="$sb" 'BEGIN{print x/1048576}')" "$(awk -v x="$tbb" 'BEGIN{print x/1048576}')"
    tot_sent=$((tot_sent+sb)); tot_tab=$((tot_tab+tbb))
  done
  awk -v a="$tot_sent" -v b="$tot_tab" 'BEGIN{ printf "TOTAL   approx %.2f MB sent (row payload) vs %.2f MB for plain scans of the four base tables (heap size): %.3f%%\n", a/1048576, b/1048576, 100*a/b }'
} | tee "$OUT/transfer.txt"

# ---------------------------------------------------------------- 9. LLM input (task + input + output + log + plans)
say "Building llm_input.txt (task, database description, application output, log, plans)"
NROWS=$(wc -l < "$OUT/result_java.txt" | xargs)
NCOLS=$(head -n1 "$OUT/result_java.txt" | awk -F'\t' '{print NF}')
LLM="$OUT/llm_input.txt"
{
cat <<TASK
### TASK
A closed Java application reads a PostgreSQL database through Hibernate and prints a report. Its source code is NOT
available. You are given everything observable about it: the database it ran on (INPUT), the exact lines it printed
(OUTPUT), the SQL statements Hibernate sent to the database (LOG) and the execution plans of those statements (PLANS).
Statement parameters are bound separately and are not part of the log.

Write ONE PostgreSQL SELECT statement Q such that, executed on the database described under INPUT, Q returns exactly
the lines under OUTPUT: the same $NROWS rows, $NCOLS columns, values and order. Q is the single query that the whole
application is equivalent to on every database of this schema, not just on this one.

Rules for your answer:
  1. Q must return exactly $NROWS rows and $NCOLS columns on this database. A query that returns more or fewer rows,
     or a different number of columns, is wrong. Check this before answering.
  2. Use only the tables and columns listed under INPUT. Do not return raw table dumps.
  3. Values in OUTPUT are tab-separated, no header; the word NULL stands for SQL NULL.
  4. Reproduce the row ORDER of OUTPUT exactly.
  5. State which parts of Q you are sure of from the evidence and which are guesses.

TASK
echo
echo "### INPUT: DATABASE (PostgreSQL, schema public)"
for t in nation region customer supplier part partsupp orders lineitem; do
  echo; echo "TABLE $t -- $(psql -Atc "select count(*) from $t") rows"
  psql -Atc "select '  '||a.attname||' '||format_type(a.atttypid,a.atttypmod)
             from pg_attribute a where a.attrelid='public.$t'::regclass and a.attnum>0 and not a.attisdropped
             order by a.attnum"
  echo "  first 3 rows (column order as above):"
  psql -At -F ' | ' -c "select * from $t order by 1 limit 3" | cut -c1-230 | sed 's/^/    /'
done
echo
echo "Distinct values of low-cardinality columns:"
psql -Atc "select '  customer.c_mktsegment: '||string_agg(distinct trim(c_mktsegment), ', ') from customer"
psql -Atc "select '  orders.o_orderstatus: '||string_agg(distinct trim(o_orderstatus), ', ') from orders"
psql -Atc "select '  lineitem.l_shipmode: '||string_agg(distinct trim(l_shipmode), ', ') from lineitem"
psql -Atc "select '  region.r_name: '||string_agg(distinct trim(r_name), ', ') from region"
psql -Atc "select '  nation.n_name: '||string_agg(distinct trim(n_name), ', ') from nation"
echo
echo "### OUTPUT: everything the application printed ($NROWS lines, $NCOLS tab-separated columns, no header)"
cat "$OUT/result_java.txt"
echo
echo "### LOG: every SQL statement Hibernate sent to the database ($STMTS statements, parameters bound separately)"
cat "$OUT/sql_log.txt"
echo
echo "### PLANS: EXPLAIN (ANALYZE) of those statements"
cat "$OUT/plans.txt"
} > "$LLM"
echo "  wrote $LLM ($(wc -l < "$LLM" | xargs) lines)"

cat > "$OUT/check_candidate.sh" <<'CHK_EOF'
#!/usr/bin/env bash
# Usage: PGUSER=.. PGPASSWORD=.. PGDATABASE=.. ./check_candidate.sh candidate.sql
# Runs an LLM's candidate query and compares it with the application's real output.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cand="${1:?usage: check_candidate.sh candidate.sql}"
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-$(whoami)}"
if ! psql -At -F $'\t' -P null=NULL -v ON_ERROR_STOP=1 -f "$cand" > "$HERE/candidate_out.txt" 2> "$HERE/candidate_err.txt"; then
  echo "CANDIDATE FAILED TO RUN:"; cat "$HERE/candidate_err.txt"; exit 2; fi
cr=$(wc -l < "$HERE/candidate_out.txt" | xargs); cc=$(head -n1 "$HERE/candidate_out.txt" | awk -F'\t' '{print NF}')
er=$(wc -l < "$HERE/result_java.txt" | xargs);   ec=$(head -n1 "$HERE/result_java.txt" | awk -F'\t' '{print NF}')
echo "candidate: $cr rows x ${cc:-0} columns | expected: $er rows x $ec columns"
if cmp -s "$HERE/candidate_out.txt" "$HERE/result_java.txt"; then echo "EXACT MATCH"
elif diff -q <(sort "$HERE/candidate_out.txt") <(sort "$HERE/result_java.txt") >/dev/null; then echo "SAME ROWS, DIFFERENT ORDER"
else echo "DIFFERENT"; diff <(sort "$HERE/candidate_out.txt") <(sort "$HERE/result_java.txt") | head -n 20; fi
CHK_EOF
chmod +x "$OUT/check_candidate.sh"

# ---------------------------------------------------------------- 10. summary
{
  echo "$VERDICT"
  echo "$LEAK"
  echo "Hibernate SQL statements: $STMTS"
  echo "Output: $NROWS rows x $NCOLS columns"
  echo "Statements:"; sed 's/^/  /' "$OUT/sql_log.txt"
  echo; echo "Data transfer:"; sed 's/^/  /' "$OUT/transfer.txt"
} > "$OUT/summary.txt"

say "Done"
cat "$OUT/summary.txt"
echo
echo "Files in $OUT:"; ls -1 "$OUT" | sed 's/^/  /'
echo
echo "Next: give out/llm_input.txt to an LLM, save its SQL to a file, then run:  out/check_candidate.sh candidate.sql"
