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
