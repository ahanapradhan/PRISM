"""Prep the unmasque working schema with full copies of the tpch tables,
as the pipeline's Initiator would. Needed by ViewMinimizerTest etc."""
from mysite.unmasque.src.util.ConnectionFactory import ConnectionHelperFactory

TABLES = ["customer", "lineitem", "nation", "orders", "part", "partsupp",
          "region", "supplier"]

conn = ConnectionHelperFactory().createConnectionHelper()
conn.connectUsingParams()
cur = conn.conn.cursor()
cur.execute("drop schema if exists unmasque cascade")
cur.execute("create schema unmasque")
conn.conn.commit()
import time
for t in TABLES:
    t0 = time.time()
    cur.execute(f'create unlogged table unmasque."{t}" (like public."{t}" including indexes)')
    cur.execute(f'insert into unmasque."{t}" select * from public."{t}"')
    conn.conn.commit()
    print(f"{t}: {time.time() - t0:.1f}s")
cur.execute("analyze")
conn.conn.commit()
cur.execute("select relname, n_live_tup from pg_stat_user_tables where schemaname='unmasque' order by 1")
for r in cur.fetchall():
    print(r)
conn.closeConnection()
