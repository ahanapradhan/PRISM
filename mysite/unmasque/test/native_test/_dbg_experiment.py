"""Debug CopyBasedMinimizerExperiment failure: run ViewMinimizer.doJob live."""
import traceback

from mysite.unmasque.src.core.abstract.ExtractorBase import Base
from mysite.unmasque.src.core.view_minimizer import ViewMinimizer
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory

CORE_TABLES = ["customer", "orders", "lineitem"]

MQ18 = """SELECT c_name, o_orderdate, o_totalprice, SUM(l_quantity)
FROM customer, orders, lineitem
WHERE c_phone LIKE '27-%'
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
GROUP BY c_name, o_orderdate, o_totalprice
ORDER BY o_orderdate, o_totalprice DESC
LIMIT 100;"""

conn = ConnectionHelperFactory().createConnectionHelper()
conn.connectUsingParams()
config = conn.config
for name in ("detect_union", "detect_oj", "detect_nep", "detect_or", "use_cs2"):
    setattr(config, name, False)

prep = Base(conn, "ExperimentPrep")
prep.set_all_relations(list(CORE_TABLES))
prep._create_working_schema()
prep.take_backup(CORE_TABLES)
sizes = {t: int(conn.execute_sql_fetchone_0(conn.queries.get_row_count(f"{config.schema}.{t}")))
         for t in CORE_TABLES}
print("sizes:", sizes)

minimizer = ViewMinimizer(conn, CORE_TABLES, sizes, False)
try:
    result = minimizer.doJob(MQ18)
    print("doJob returned:", repr(result))
except Exception:
    traceback.print_exc()
finally:
    prep.remove_footprint()
    conn.conn.commit()
    conn.closeConnection()
